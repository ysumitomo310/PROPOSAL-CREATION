"""ナレッジ管理API

GET  /api/v1/knowledge/stats        — 統計情報
GET  /api/v1/knowledge/items         — 登録済みナレッジ一覧
DELETE /api/v1/knowledge/items/{id}  — 個別削除
POST /api/v1/knowledge/scan          — ディレクトリスキャン
POST /api/v1/knowledge/load/bulk     — 一括投入開始
GET  /api/v1/knowledge/load/stream/{task_id} — SSE進捗
POST /api/v1/knowledge/upload        — 個別アップロード
"""

import asyncio
import logging
import os
import time
import uuid
from io import BytesIO
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import get_settings
from app.core.embedding import EmbeddingService
from app.core.neo4j_client import Neo4jClient
from app.services.knowledge.loader import KnowledgeLoader
from app.services.knowledge.master import ModuleClassificationService
from app.services.knowledge.parser import (
    BPDParser,
    ModuleOverviewParser,
    ScopeItemData,
    ModuleOverviewData,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/knowledge", tags=["knowledge"])

# ─── Active load tasks ───
_active_tasks: dict[str, "LoadTask"] = {}


class LoadTask:
    """バックグラウンドロードタスクの状態管理。"""

    def __init__(self, total_bpd: int, total_pdf: int) -> None:
        self.task_id = str(uuid.uuid4())[:8]
        self.total_bpd = total_bpd
        self.total_pdf = total_pdf
        self.completed_bpd = 0
        self.completed_pdf = 0
        self.errors: list[str] = []
        self.phase = "initializing"
        self.is_complete = False
        self.queue: asyncio.Queue[dict] = asyncio.Queue()

    @property
    def total(self) -> int:
        return self.total_bpd + self.total_pdf

    @property
    def completed(self) -> int:
        return self.completed_bpd + self.completed_pdf

    async def send_event(self, event: dict) -> None:
        await self.queue.put(event)


# ─── Schemas ───


class KnowledgeStats(BaseModel):
    scope_items: int = 0
    module_overviews: int = 0
    modules: dict[str, int] = {}


class KnowledgeItem(BaseModel):
    id: str
    type: str  # "ScopeItem" or "ModuleOverview"
    scope_item_id: str | None = None
    function_name: str | None = None
    module: str | None = None
    business_domain: str | None = None
    description: str | None = None
    module_name: str | None = None
    summary: str | None = None
    source_doc: str | None = None
    has_embedding: bool = False


class ScanResult(BaseModel):
    bpd_sets: list[dict]
    pdfs: list[str]
    total_bpd: int
    total_pdf: int
    existing_scope_items: int
    new_bpd_count: int


class LoadBulkRequest(BaseModel):
    path: str
    skip_embedding: bool = False
    skip_llm: bool = False


class LoadStartResponse(BaseModel):
    task_id: str
    total_bpd: int
    total_pdf: int
    message: str


class UploadProcessResponse(BaseModel):
    processed: int
    scope_items: list[dict]
    module_overviews: list[dict]
    errors: list[str]


# ─── Helpers ───


def _get_neo4j(request: Request) -> Neo4jClient:
    settings = get_settings()
    return Neo4jClient(
        uri=settings.NEO4J_URI,
        user=settings.NEO4J_USER,
        password=settings.NEO4J_PASSWORD,
    )


def _discover_bpd_sets(bpd_dir: Path) -> list[dict[str, str]]:
    """BPD 3ファイルセットを検出。"""
    ja_files: dict[str, Path] = {}
    en_files: dict[str, Path] = {}
    xlsx_files: dict[str, Path] = {}

    for f in bpd_dir.iterdir():
        if not f.is_file():
            continue
        name = f.name
        if "_BPD_JA_" in name and name.endswith(".docx"):
            prefix = name.split("_S4CLD")[0]
            ja_files[prefix] = f
        elif "_BPD_EN_" in name and name.endswith(".docx"):
            prefix = name.split("_S4CLD")[0]
            en_files[prefix] = f
        elif "_BPD_EN_" in name and name.endswith(".xlsx"):
            prefix = name.split("_S4CLD")[0]
            xlsx_files[prefix] = f

    sets = []
    for prefix in sorted(ja_files.keys()):
        entry = {
            "prefix": prefix,
            "ja": str(ja_files[prefix]),
            "has_en": prefix in en_files,
            "has_xlsx": prefix in xlsx_files,
        }
        if prefix in en_files:
            entry["en"] = str(en_files[prefix])
        if prefix in xlsx_files:
            entry["xlsx"] = str(xlsx_files[prefix])
        sets.append(entry)
    return sets


def _discover_pdfs(pdf_dir: Path) -> list[Path]:
    """Discovery WS PDFファイルを検出。"""
    return sorted(
        f for f in pdf_dir.iterdir()
        if f.is_file() and f.suffix.lower() == ".pdf"
        and "Discovery" in f.name
    )


# ─── Endpoints ───


@router.get("/stats", response_model=KnowledgeStats)
async def get_stats(request: Request) -> KnowledgeStats:
    """ナレッジ統計情報を取得。"""
    neo4j = _get_neo4j(request)
    try:
        # ノード数
        counts = await neo4j.execute_query(
            "MATCH (n) RETURN labels(n)[0] AS label, count(n) AS cnt"
        )
        si_count = 0
        mo_count = 0
        for row in counts:
            if row["label"] == "ScopeItem":
                si_count = row["cnt"]
            elif row["label"] == "ModuleOverview":
                mo_count = row["cnt"]

        # モジュール分布
        modules_raw = await neo4j.execute_query(
            "MATCH (s:ScopeItem) RETURN s.module AS module, count(*) AS cnt ORDER BY cnt DESC"
        )
        modules = {r["module"]: r["cnt"] for r in modules_raw}

        return KnowledgeStats(
            scope_items=si_count,
            module_overviews=mo_count,
            modules=modules,
        )
    finally:
        await neo4j.close()


@router.get("/items", response_model=list[KnowledgeItem])
async def list_items(
    request: Request,
    module: str | None = None,
    search: str | None = None,
    item_type: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> list[KnowledgeItem]:
    """登録済みナレッジ一覧を取得。"""
    neo4j = _get_neo4j(request)
    try:
        items: list[KnowledgeItem] = []

        # ScopeItems
        if item_type is None or item_type == "ScopeItem":
            where_clauses = []
            params: dict = {"limit": limit, "offset": offset}
            if module:
                where_clauses.append("s.module = $module")
                params["module"] = module
            if search:
                where_clauses.append(
                    "(s.function_name CONTAINS $search OR s.description CONTAINS $search)"
                )
                params["search"] = search

            where = f"WHERE {' AND '.join(where_clauses)}" if where_clauses else ""
            rows = await neo4j.execute_query(
                f"""MATCH (s:ScopeItem)
                {where}
                RETURN s.id AS id, s.scope_item_id AS scope_item_id,
                       s.function_name AS function_name, s.module AS module,
                       s.business_domain AS business_domain,
                       s.description AS description, s.source_doc AS source_doc,
                       s.embedding IS NOT NULL AS has_embedding
                ORDER BY s.module, s.function_name
                SKIP $offset LIMIT $limit""",
                params,
            )
            for r in rows:
                items.append(KnowledgeItem(
                    id=r["id"],
                    type="ScopeItem",
                    scope_item_id=r["scope_item_id"],
                    function_name=r["function_name"],
                    module=r["module"],
                    business_domain=r["business_domain"],
                    description=r["description"],
                    source_doc=r["source_doc"],
                    has_embedding=bool(r["has_embedding"]),
                ))

        # ModuleOverviews
        if item_type is None or item_type == "ModuleOverview":
            mo_rows = await neo4j.execute_query(
                """MATCH (m:ModuleOverview)
                RETURN m.id AS id, m.module AS module, m.module_name AS module_name,
                       m.summary AS summary, m.source_doc AS source_doc,
                       m.embedding IS NOT NULL AS has_embedding
                ORDER BY m.module"""
            )
            for r in mo_rows:
                items.append(KnowledgeItem(
                    id=r["id"],
                    type="ModuleOverview",
                    module=r["module"],
                    module_name=r["module_name"],
                    summary=r["summary"],
                    source_doc=r["source_doc"],
                    has_embedding=bool(r["has_embedding"]),
                ))

        return items
    finally:
        await neo4j.close()


@router.delete("/items/{item_id}")
async def delete_item(item_id: str, request: Request) -> dict:
    """ナレッジアイテムを削除。"""
    neo4j = _get_neo4j(request)
    try:
        result = await neo4j.execute_query(
            "MATCH (n {id: $id}) DETACH DELETE n RETURN count(n) AS deleted",
            {"id": item_id},
        )
        deleted = result[0]["deleted"] if result else 0
        if deleted == 0:
            raise HTTPException(404, f"アイテムが見つかりません: {item_id}")
        return {"deleted": item_id}
    finally:
        await neo4j.close()


@router.post("/scan", response_model=ScanResult)
async def scan_directory(body: LoadBulkRequest, request: Request) -> ScanResult:
    """ディレクトリをスキャンしてBPDセット/PDFを検出。"""
    dir_path = Path(body.path)
    if not dir_path.exists() or not dir_path.is_dir():
        raise HTTPException(422, f"ディレクトリが見つかりません: {body.path}")

    bpd_sets = _discover_bpd_sets(dir_path)
    pdfs = _discover_pdfs(dir_path)

    # 既存ノード数を取得して差分を推定
    neo4j = _get_neo4j(request)
    try:
        existing = await neo4j.execute_query(
            "MATCH (s:ScopeItem) RETURN s.scope_item_id AS sid"
        )
        existing_ids = {r["sid"] for r in existing}
    finally:
        await neo4j.close()

    new_count = sum(1 for s in bpd_sets if s["prefix"] not in existing_ids)

    return ScanResult(
        bpd_sets=[{"prefix": s["prefix"], "has_en": s["has_en"], "has_xlsx": s["has_xlsx"]} for s in bpd_sets],
        pdfs=[p.name for p in pdfs],
        total_bpd=len(bpd_sets),
        total_pdf=len(pdfs),
        existing_scope_items=len(existing_ids),
        new_bpd_count=new_count,
    )


@router.post("/load/bulk", response_model=LoadStartResponse, status_code=202)
async def start_bulk_load(
    body: LoadBulkRequest,
    request: Request,
) -> LoadStartResponse:
    """一括ナレッジ投入を開始（バックグラウンド）。"""
    dir_path = Path(body.path)
    if not dir_path.exists() or not dir_path.is_dir():
        raise HTTPException(422, f"ディレクトリが見つかりません: {body.path}")

    bpd_sets = _discover_bpd_sets(dir_path)
    pdfs = _discover_pdfs(dir_path)

    if not bpd_sets and not pdfs:
        raise HTTPException(422, "処理対象ファイルが見つかりません")

    task = LoadTask(total_bpd=len(bpd_sets), total_pdf=len(pdfs))
    _active_tasks[task.task_id] = task

    session_factory = request.app.state.session_factory

    # asyncio.create_task で直接イベントループに投入
    # （BackgroundTasks はレスポンス後実行のためSSEと相性が悪い）
    async def _wrapped():
        try:
            await _run_bulk_load(
                task=task,
                bpd_sets=bpd_sets,
                pdfs=pdfs,
                session_factory=session_factory,
                skip_embedding=body.skip_embedding,
                skip_llm=body.skip_llm,
            )
        except Exception:
            logger.exception("Bulk load task failed")

    asyncio.create_task(_wrapped())

    return LoadStartResponse(
        task_id=task.task_id,
        total_bpd=len(bpd_sets),
        total_pdf=len(pdfs),
        message=f"ナレッジ投入を開始: BPD {len(bpd_sets)}セット + PDF {len(pdfs)}件",
    )


@router.get("/load/stream/{task_id}")
async def load_stream(task_id: str) -> StreamingResponse:
    """ナレッジ投入のSSE進捗ストリーム。"""
    task = _active_tasks.get(task_id)
    if not task:
        raise HTTPException(404, f"タスクが見つかりません: {task_id}")

    import json as _json

    async def event_generator():
        # まずキューに溜まっているイベントをすべて吐き出す
        while not task.queue.empty():
            event = task.queue.get_nowait()
            yield f"data: {_json.dumps(event, ensure_ascii=False)}\n\n"
            if event.get("type") in ("complete", "error"):
                _active_tasks.pop(task_id, None)
                return

        # まだ完了していなければ待機
        while not task.is_complete:
            try:
                event = await asyncio.wait_for(task.queue.get(), timeout=30.0)
            except asyncio.TimeoutError:
                yield f"data: {_json.dumps({'type': 'keepalive'})}\n\n"
                continue

            yield f"data: {_json.dumps(event, ensure_ascii=False)}\n\n"

            if event.get("type") in ("complete", "error"):
                break

        # 残りのイベントを吐き出す
        while not task.queue.empty():
            event = task.queue.get_nowait()
            yield f"data: {_json.dumps(event, ensure_ascii=False)}\n\n"

        # Cleanup
        _active_tasks.pop(task_id, None)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/load/status/{task_id}")
async def load_status(task_id: str) -> dict:
    """ナレッジ投入タスクのステータス（ポーリング用）。"""
    task = _active_tasks.get(task_id)
    if not task:
        return {
            "task_id": task_id,
            "found": False,
            "message": "タスクが完了済みまたは存在しません",
        }
    return {
        "task_id": task_id,
        "found": True,
        "phase": task.phase,
        "is_complete": task.is_complete,
        "completed_bpd": task.completed_bpd,
        "total_bpd": task.total_bpd,
        "completed_pdf": task.completed_pdf,
        "total_pdf": task.total_pdf,
        "errors": len(task.errors),
    }


@router.post("/upload", response_model=UploadProcessResponse)
async def upload_files(
    request: Request,
    files: list[UploadFile],
) -> UploadProcessResponse:
    """個別ファイルアップロード＋処理。"""
    import tempfile
    import shutil

    settings = get_settings()
    session_factory = request.app.state.session_factory

    # 一時ディレクトリにファイルを保存
    tmpdir = Path(tempfile.mkdtemp(prefix="knowledge_upload_"))
    try:
        for f in files:
            content = await f.read()
            dest = tmpdir / (f.filename or "unknown")
            dest.write_bytes(content)

        bpd_sets = _discover_bpd_sets(tmpdir)
        pdfs = _discover_pdfs(tmpdir)

        # サービス初期化
        neo4j = Neo4jClient(
            uri=settings.NEO4J_URI,
            user=settings.NEO4J_USER,
            password=settings.NEO4J_PASSWORD,
        )
        embedding_service = None
        if settings.OPENAI_API_KEY:
            embedding_service = EmbeddingService(
                api_key=settings.OPENAI_API_KEY,
                model=settings.EMBEDDING_MODEL,
            )
        llm_client = None
        try:
            from app.core.llm_client import LLMClient
            llm_client = LLMClient(settings)
        except Exception:
            pass

        loader = KnowledgeLoader(neo4j, embedding_service)
        scope_items_result: list[dict] = []
        mo_result: list[dict] = []
        errors: list[str] = []

        # BPDパース+投入
        for bpd_set in bpd_sets:
            try:
                async with session_factory() as session:
                    master = ModuleClassificationService(session)
                    parser = BPDParser(llm_client=llm_client, master_service=master)
                    si = await parser.parse_scope_item(
                        ja_docx_path=Path(bpd_set["ja"]),
                        en_docx_path=Path(bpd_set["en"]) if "en" in bpd_set else None,
                        xlsx_path=Path(bpd_set["xlsx"]) if "xlsx" in bpd_set else None,
                    )
                    # Embedding
                    emb = None
                    if embedding_service:
                        emb_list = await embedding_service.embed_batch(
                            [f"{si.function_name} {si.description}"],
                            batch_size=1,
                        )
                        emb = emb_list[0]
                    await loader.load_scope_item(si, emb)
                    scope_items_result.append({
                        "id": si.id,
                        "function_name": si.function_name,
                        "module": si.module,
                    })
            except Exception as e:
                errors.append(f"BPD {bpd_set['prefix']}: {e}")

        # PDFパース+投入
        for pdf_path in pdfs:
            try:
                pdf_parser = ModuleOverviewParser(llm_client=llm_client)
                mo = await pdf_parser.parse_module_overview(pdf_path)
                emb = None
                if embedding_service:
                    emb_list = await embedding_service.embed_batch(
                        [f"{mo.module_name} {mo.summary}"],
                        batch_size=1,
                    )
                    emb = emb_list[0]
                await loader.load_module_overview(mo, emb)
                mo_result.append({
                    "id": mo.id,
                    "module_name": mo.module_name,
                    "module": mo.module,
                })
            except Exception as e:
                errors.append(f"PDF {pdf_path.name}: {e}")

        await neo4j.close()

        return UploadProcessResponse(
            processed=len(scope_items_result) + len(mo_result),
            scope_items=scope_items_result,
            module_overviews=mo_result,
            errors=errors,
        )
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


# ─── Background Task ───


async def _run_bulk_load(
    task: LoadTask,
    bpd_sets: list[dict],
    pdfs: list[Path],
    session_factory: async_sessionmaker[AsyncSession],
    skip_embedding: bool = False,
    skip_llm: bool = False,
) -> None:
    """バックグラウンドで一括ナレッジ投入。"""
    settings = get_settings()
    errors: list[str] = []

    try:
        # サービス初期化
        neo4j = Neo4jClient(
            uri=settings.NEO4J_URI,
            user=settings.NEO4J_USER,
            password=settings.NEO4J_PASSWORD,
        )
        embedding_service = None
        if not skip_embedding and settings.OPENAI_API_KEY:
            embedding_service = EmbeddingService(
                api_key=settings.OPENAI_API_KEY,
                model=settings.EMBEDDING_MODEL,
            )

        llm_client = None
        if not skip_llm:
            try:
                from app.core.llm_client import LLMClient
                llm_client = LLMClient(settings)
            except Exception as e:
                logger.warning("LLM client init failed: %s", e)

        loader = KnowledgeLoader(neo4j, embedding_service)

        # ─── BPD パース ───
        task.phase = "bpd_parsing"
        await task.send_event({
            "type": "phase",
            "phase": "bpd_parsing",
            "message": f"BPDパース開始: {len(bpd_sets)}セット",
        })

        scope_items: list[ScopeItemData] = []
        for i, bpd_set in enumerate(bpd_sets):
            prefix = bpd_set["prefix"]
            try:
                async with session_factory() as session:
                    master = ModuleClassificationService(session)
                    parser = BPDParser(llm_client=llm_client, master_service=master)
                    si = await parser.parse_scope_item(
                        ja_docx_path=Path(bpd_set["ja"]),
                        en_docx_path=Path(bpd_set["en"]) if "en" in bpd_set else None,
                        xlsx_path=Path(bpd_set["xlsx"]) if "xlsx" in bpd_set else None,
                    )
                    scope_items.append(si)
                    task.completed_bpd += 1
                    await task.send_event({
                        "type": "bpd_progress",
                        "completed": task.completed_bpd,
                        "total": task.total_bpd,
                        "current": f"{prefix}: {si.function_name}",
                    })
            except Exception as e:
                err = f"BPD {prefix}: {e}"
                errors.append(err)
                task.errors.append(err)
                task.completed_bpd += 1
                await task.send_event({
                    "type": "bpd_error",
                    "completed": task.completed_bpd,
                    "total": task.total_bpd,
                    "error": err,
                })

        # ─── PDF パース ───
        task.phase = "pdf_parsing"
        await task.send_event({
            "type": "phase",
            "phase": "pdf_parsing",
            "message": f"PDFパース開始: {len(pdfs)}件",
        })

        module_overviews: list[ModuleOverviewData] = []
        pdf_parser = ModuleOverviewParser(llm_client=llm_client)
        for i, pdf_path in enumerate(pdfs):
            try:
                mo = await pdf_parser.parse_module_overview(pdf_path)
                module_overviews.append(mo)
                task.completed_pdf += 1
                await task.send_event({
                    "type": "pdf_progress",
                    "completed": task.completed_pdf,
                    "total": task.total_pdf,
                    "current": pdf_path.name[:50],
                })
            except Exception as e:
                err = f"PDF {pdf_path.name}: {e}"
                errors.append(err)
                task.errors.append(err)
                task.completed_pdf += 1

        # ─── Neo4j 投入 ───
        task.phase = "neo4j_load"
        await task.send_event({
            "type": "phase",
            "phase": "neo4j_load",
            "message": f"Neo4j投入: {len(scope_items)} ScopeItems + {len(module_overviews)} ModuleOverviews",
        })

        result = await loader.bulk_load(
            scope_items=scope_items,
            module_overviews=module_overviews,
            batch_size=settings.EMBEDDING_BATCH_SIZE,
        )

        # ─── 完了 ───
        task.phase = "complete"
        task.is_complete = True
        await task.send_event({
            "type": "complete",
            "scope_items_loaded": result.scope_items_loaded,
            "module_overviews_loaded": result.module_overviews_loaded,
            "relations_created": result.scope_item_relations_created + result.covers_relations_created,
            "warnings": len(result.warnings),
            "errors": len(errors),
            "duration_seconds": result.duration_seconds,
        })

        await neo4j.close()

    except Exception as e:
        logger.exception("Bulk load failed")
        task.is_complete = True
        await task.send_event({
            "type": "error",
            "message": f"ナレッジ投入に失敗: {e}",
        })
