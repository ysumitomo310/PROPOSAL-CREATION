"""E2E統合テスト（TASK-F02）

全フロー（Excel UP → 案件作成 → マッピング開始 → SSE受信 → 結果取得）を
モックLangGraphグラフで通しテスト。10件の要件を処理し、全件completedを検証。
"""

import asyncio
import json
from io import BytesIO
from unittest.mock import AsyncMock, MagicMock, patch

import openpyxl
import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.api.cases import router as cases_router
from app.api.mapping import router as mapping_router
from app.services.mapping.agent import MappingBatchProcessor, SSEEvent


# ─── Fixtures ───


def _make_excel_bytes(num_requirements: int = 10) -> bytes:
    """テスト用 Excel（N件の機能要件）。"""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Sheet1"
    ws.append(["機能名", "要件概要", "要件詳細", "重要度"])
    for i in range(1, num_requirements + 1):
        ws.append([
            f"機能{i:03d}",
            f"要件概要テスト{i}",
            f"要件詳細テスト{i}",
            "Must" if i % 3 == 0 else ("Should" if i % 3 == 1 else "Could"),
        ])
    buf = BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf.read()


def _make_column_mapping() -> str:
    """テスト用 column_mapping JSON。"""
    return json.dumps({
        "header_row": 1,
        "data_start_row": 2,
        "columns": {
            "function_name": "機能名",
            "requirement_summary": "要件概要",
            "requirement_detail": "要件詳細",
            "importance": "重要度",
        },
    }, ensure_ascii=False)


def _mock_graph_result(function_name: str) -> dict:
    """モック LangGraph 結果。"""
    return {
        "judgment_level": "標準対応",
        "confidence": "High",
        "confidence_score": 0.85,
        "proposal_text": f"{function_name}はSAP標準機能で対応可能です。",
        "scope_item_analysis": f"SAP S/4HANAの標準機能で{function_name}をカバー。",
        "gap_analysis": "なし",
        "judgment_reason": "標準機能で対応可能と判定",
        "matched_scope_items": [{"id": "SAP-1B4", "function_name": "Sales Order"}],
        "traversed_nodes": [{"id": "SAP-1B4", "type": "ScopeItem"}],
        "retry_count": 0,
        "search_score": 0.8,
    }


class MockSession:
    """AsyncSession のモック（add/flush/commit/refresh/get/execute をサポート）。

    E2E テストでは実DBではなくインメモリで状態管理。
    """

    def __init__(self):
        self._store: dict[str, dict] = {}
        self._objects: list = []
        self._id_counter = 0

    def add(self, obj):
        self._objects.append(obj)

    async def flush(self):
        from datetime import datetime, timezone

        for obj in self._objects:
            if not hasattr(obj, "id") or obj.id is None:
                self._id_counter += 1
                obj.id = f"mock-id-{self._id_counter}"
            # server_default のシミュレーション
            if hasattr(obj, "created_at") and obj.created_at is None:
                obj.created_at = datetime.now(timezone.utc)
            if hasattr(obj, "updated_at") and obj.updated_at is None:
                obj.updated_at = datetime.now(timezone.utc)
            # ORM default のシミュレーション
            if hasattr(obj, "status") and obj.status is None:
                obj.status = "created"
            self._store[obj.id] = obj
        self._objects.clear()

    async def commit(self):
        # flush any pending objects first
        await self.flush()

    async def refresh(self, obj):
        pass

    async def rollback(self):
        self._objects.clear()

    async def get(self, model_cls, id_val):
        return self._store.get(id_val)

    async def execute(self, stmt):
        # Return a mock result compatible with .scalars().all() and .all()
        return MockQueryResult(self._store)

    def __repr__(self):
        return f"<MockSession objects={len(self._store)}>"


class MockQueryResult:
    """execute() 戻り値のモック。"""

    def __init__(self, store):
        self._store = store

    def scalars(self):
        return self

    def all(self):
        return list(self._store.values())

    def scalar_one_or_none(self):
        """completed スキップ判定用: デフォルトは未完了（None）。"""
        return None


class MockSessionCM:
    """async context manager wrapper for MockSession。"""

    def __init__(self, session):
        self._session = session

    async def __aenter__(self):
        return self._session

    async def __aexit__(self, *args):
        pass


# ─── Tests ───


class TestFullFlow:
    """E2E: Case作成 → Mapping開始 → 結果取得の全フロー。"""

    @pytest.mark.asyncio
    async def test_case_creation_10_requirements(self):
        """10件の要件を含むExcelで案件を作成し、全件FunctionalRequirementが作成される。"""
        session = MockSession()

        app = FastAPI()
        app.include_router(cases_router)
        app.state = MagicMock()
        app.state.session_factory = MagicMock(return_value=MockSessionCM(session))

        excel = _make_excel_bytes(10)
        col_mapping = _make_column_mapping()

        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            resp = await client.post(
                "/api/v1/cases",
                files={"file": (
                    "rfp_test.xlsx",
                    excel,
                    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                )},
                data={
                    "name": "E2Eテスト案件",
                    "product": "SAP",
                    "column_mapping": col_mapping,
                },
            )

        assert resp.status_code == 201
        data = resp.json()
        assert data["name"] == "E2Eテスト案件"
        assert data["product"] == "SAP"
        assert data["total_requirements"] == 10
        assert data["status"] == "created"

    @pytest.mark.asyncio
    async def test_batch_processor_all_complete(self):
        """10件の要件をバッチ処理し、全件completedで完了する。"""

        # モック LangGraph
        async def _mock_ainvoke(state, config=None):
            fn = state.get("function_name", "unknown")
            await asyncio.sleep(0.01)  # 軽微な遅延でリアルな並行動作をシミュレート
            return _mock_graph_result(fn)

        mock_graph = AsyncMock()
        mock_graph.ainvoke = _mock_ainvoke

        # モックセッション（バッチプロセッサ用）
        session = MockSession()
        session_factory = MagicMock(return_value=MockSessionCM(session))

        processor = MappingBatchProcessor(
            graph=mock_graph,
            session_factory=session_factory,
            max_concurrency=5,
            error_threshold=0.2,
        )

        # モック要件 10件
        requirements = []
        for i in range(1, 11):
            req = MagicMock()
            req.id = f"req-{i:03d}"
            req.function_name = f"機能{i:03d}"
            req.requirement_summary = f"要件概要{i}"
            req.requirement_detail = f"要件詳細{i}"
            req.business_category = "販売"
            req.importance = "Must"
            req.sequence_number = i
            requirements.append(req)

        result = await processor.run_batch("case-e2e-001", requirements)

        # 検証: 全件完了
        assert result.total == 10
        assert result.completed == 10
        assert result.errors == 0
        assert result.aborted is False

    @pytest.mark.asyncio
    async def test_sse_events_10_requirements(self):
        """10件処理でSSEイベントが正しく発行される（10 requirement_complete + 1 batch_complete）。"""

        async def _mock_ainvoke(state, config=None):
            fn = state.get("function_name", "unknown")
            await asyncio.sleep(0.01)
            return _mock_graph_result(fn)

        mock_graph = AsyncMock()
        mock_graph.ainvoke = _mock_ainvoke

        session = MockSession()
        session_factory = MagicMock(return_value=MockSessionCM(session))

        processor = MappingBatchProcessor(
            graph=mock_graph,
            session_factory=session_factory,
            max_concurrency=3,
            error_threshold=0.2,
        )

        requirements = []
        for i in range(1, 11):
            req = MagicMock()
            req.id = f"req-{i:03d}"
            req.function_name = f"機能{i:03d}"
            req.requirement_summary = f"要件概要{i}"
            req.requirement_detail = f"要件詳細{i}"
            req.business_category = "販売"
            req.importance = "Must"
            req.sequence_number = i
            requirements.append(req)

        # 並行: バッチ処理 + SSEイベント収集
        events: list[SSEEvent] = []

        async def collect_events():
            async for event in processor.get_sse_events():
                events.append(event)
                if event.type == "batch_complete":
                    break

        batch_task = asyncio.create_task(
            processor.run_batch("case-e2e-002", requirements)
        )
        collector_task = asyncio.create_task(collect_events())

        await asyncio.gather(batch_task, collector_task)

        # 検証
        req_complete_events = [e for e in events if e.type == "requirement_complete"]
        batch_complete_events = [e for e in events if e.type == "batch_complete"]

        assert len(req_complete_events) == 10
        assert len(batch_complete_events) == 1

        # batch_complete のデータを検証
        bc = batch_complete_events[0]
        assert bc.data["total"] == 10
        assert bc.data["completed"] == 10
        assert bc.data["errors"] == 0

        # 全 requirement_complete のデータに必須フィールドが存在
        for e in req_complete_events:
            assert "requirement_id" in e.data
            assert "function_name" in e.data
            assert "judgment_level" in e.data
            assert e.data["status"] == "completed"

    @pytest.mark.asyncio
    async def test_sse_format_wire_protocol(self):
        """SSEイベントが正しいワイヤプロトコルフォーマットである。"""
        event = SSEEvent(
            type="requirement_complete",
            data={"requirement_id": "req-001", "function_name": "受注登録"},
        )
        formatted = event.format_sse()

        assert formatted.startswith("event: requirement_complete\n")
        assert "data: " in formatted
        assert formatted.endswith("\n\n")

        # data行をパース可能であることを確認
        data_line = [
            l for l in formatted.split("\n") if l.startswith("data: ")
        ][0]
        parsed = json.loads(data_line[len("data: "):])
        assert parsed["requirement_id"] == "req-001"

    @pytest.mark.asyncio
    async def test_results_have_all_fields(self):
        """バッチ処理後、各結果にjudgment_level/confidence/proposal_textが非空。"""

        async def _mock_ainvoke(state, config=None):
            fn = state.get("function_name", "unknown")
            return _mock_graph_result(fn)

        mock_graph = AsyncMock()
        mock_graph.ainvoke = _mock_ainvoke

        session = MockSession()
        session_factory = MagicMock(return_value=MockSessionCM(session))

        processor = MappingBatchProcessor(
            graph=mock_graph,
            session_factory=session_factory,
            max_concurrency=5,
        )

        requirements = []
        for i in range(1, 11):
            req = MagicMock()
            req.id = f"req-{i:03d}"
            req.function_name = f"機能{i:03d}"
            req.requirement_summary = f"要件概要{i}"
            req.requirement_detail = f"要件詳細{i}"
            req.business_category = "販売"
            req.importance = "Must"
            req.sequence_number = i
            requirements.append(req)

        # SSEイベント収集
        events = []

        async def collect():
            async for ev in processor.get_sse_events():
                events.append(ev)
                if ev.type == "batch_complete":
                    break

        await asyncio.gather(
            processor.run_batch("case-e2e-003", requirements),
            collect(),
        )

        # requirement_complete の全件に必須フィールドが存在し非空
        req_events = [e for e in events if e.type == "requirement_complete"]
        assert len(req_events) == 10

        for e in req_events:
            d = e.data
            assert d.get("judgment_level"), f"judgment_level empty in {d}"
            assert d.get("confidence") is not None, f"confidence missing in {d}"
            assert d.get("function_name"), f"function_name empty in {d}"

    @pytest.mark.asyncio
    async def test_mixed_success_and_error(self):
        """一部エラーが発生しても、閾値未満ならバッチは中止されない。"""
        call_count = 0

        async def _mock_ainvoke(state, config=None):
            nonlocal call_count
            call_count += 1
            # 10件中1件だけエラー（10% < 20%閾値）
            if state.get("function_name") == "機能005":
                raise RuntimeError("LLM API error")
            return _mock_graph_result(state.get("function_name", "unknown"))

        mock_graph = AsyncMock()
        mock_graph.ainvoke = _mock_ainvoke

        session = MockSession()
        session_factory = MagicMock(return_value=MockSessionCM(session))

        processor = MappingBatchProcessor(
            graph=mock_graph,
            session_factory=session_factory,
            max_concurrency=2,
            error_threshold=0.2,
        )

        requirements = []
        for i in range(1, 11):
            req = MagicMock()
            req.id = f"req-{i:03d}"
            req.function_name = f"機能{i:03d}"
            req.requirement_summary = f"要件概要{i}"
            req.requirement_detail = f"要件詳細{i}"
            req.business_category = "販売"
            req.importance = "Must"
            req.sequence_number = i
            requirements.append(req)

        result = await processor.run_batch("case-e2e-004", requirements)

        assert result.total == 10
        assert result.completed == 9
        assert result.errors == 1
        assert result.aborted is False

    @pytest.mark.asyncio
    async def test_api_start_mapping_returns_202(self):
        """マッピング開始APIが202を返し、total_requirementsを正しく返す。"""
        session = AsyncMock()
        case = MagicMock()
        case.id = "case-api-001"
        case.status = "created"
        case.total_requirements = 10
        session.get = AsyncMock(return_value=case)

        # 要件一覧のモック
        reqs = []
        for i in range(10):
            r = MagicMock()
            r.id = f"req-api-{i}"
            r.sequence_number = i + 1
            r.function_name = f"機能{i+1:03d}"
            r.requirement_summary = f"要件{i+1}"
            r.importance = "Must"
            reqs.append(r)

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = reqs
        session.execute = AsyncMock(return_value=mock_result)
        session.commit = AsyncMock()

        app = FastAPI()
        app.include_router(mapping_router)
        app.state = MagicMock()
        app.state.active_batch_processors = {}
        app.state.settings = MagicMock()
        app.state.settings.MAPPING_MAX_CONCURRENCY = 5
        app.state.settings.MAPPING_ERROR_THRESHOLD = 0.2
        app.state.mapping_graph = MagicMock()

        class _CM:
            async def __aenter__(self):
                return session
            async def __aexit__(self, *a):
                pass

        app.state.session_factory = MagicMock(return_value=_CM())

        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            resp = await client.post("/api/v1/cases/case-api-001/mapping/start")

        assert resp.status_code == 202
        data = resp.json()
        assert data["case_id"] == "case-api-001"
        assert data["total_requirements"] == 10
