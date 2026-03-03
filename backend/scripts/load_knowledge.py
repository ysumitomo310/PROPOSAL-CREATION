#!/usr/bin/env python3
"""ナレッジ投入CLIスクリプト（TASK-B05）

BPDディレクトリ一括解析→Neo4j投入。進捗表示、エラーログ、dry-runオプション対応。

Usage:
    python scripts/load_knowledge.py \
        --bpd-dir product_doc/ \
        --pdf-dir product_doc/ \
        --csv data/module_classification_sap.csv \
        [--dry-run] [--verbose] [--limit N] [--skip-embedding]
"""

import argparse
import asyncio
import logging
import sys
import time
from pathlib import Path

# プロジェクトルートをPATHに追加
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import get_settings
from app.core.embedding import EmbeddingService
from app.core.neo4j_client import Neo4jClient
from app.services.knowledge.loader import KnowledgeLoader, LoadResult
from app.services.knowledge.master import ModuleClassificationService
from app.services.knowledge.parser import (
    BPDParser,
    ModuleOverviewParser,
    ModuleOverviewData,
    ScopeItemData,
)

logger = logging.getLogger(__name__)


def discover_bpd_sets(bpd_dir: Path) -> list[dict[str, Path]]:
    """BPD 3ファイルセット（JA docx + EN docx + xlsx）を検出。

    命名規則: {PREFIX}_S4CLD2602_BPD_{LANG}_{REGION}.{ext}
    """
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
        entry: dict[str, Path] = {"prefix": prefix, "ja": ja_files[prefix]}
        if prefix in en_files:
            entry["en"] = en_files[prefix]
        if prefix in xlsx_files:
            entry["xlsx"] = xlsx_files[prefix]
        sets.append(entry)

    return sets


def discover_pdfs(pdf_dir: Path) -> list[Path]:
    """Discovery WS Module Overview PDFファイルを検出。"""
    return sorted(
        f for f in pdf_dir.iterdir()
        if f.is_file() and f.suffix.lower() == ".pdf"
        and "Discovery" in f.name
    )


async def run(args: argparse.Namespace) -> None:
    # ローカル実行用: Docker内部ホスト名をlocalhostにオーバーライド
    import os
    if args.local:
        os.environ["POSTGRES_HOST"] = "localhost"
        os.environ["POSTGRES_PORT"] = "5435"
        os.environ["NEO4J_URI"] = "bolt://localhost:7688"

    settings = get_settings()
    start_time = time.time()
    errors: list[str] = []

    # ─── 1. BPDセット検出 ─────────────────────────
    bpd_sets = discover_bpd_sets(args.bpd_dir)
    pdfs = discover_pdfs(args.pdf_dir)

    if args.limit and args.limit > 0:
        bpd_sets = bpd_sets[: args.limit]

    print(f"=== Knowledge Loader ===")
    print(f"BPD sets found: {len(bpd_sets)}")
    print(f"PDF files found: {len(pdfs)}")
    print(f"Mode: {'DRY-RUN' if args.dry_run else 'LIVE'}")
    print(f"Embedding: {'SKIP' if args.skip_embedding else 'ENABLED'}")
    print()

    if not bpd_sets and not pdfs:
        print("No files found. Nothing to do.")
        return

    # ─── 2. サービス初期化 ────────────────────────
    # DB session for module master
    engine = create_async_engine(settings.database_url, echo=False)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    # CSV import (if provided)
    async with session_factory() as session:
        master_service = ModuleClassificationService(session)
        if args.csv and args.csv.exists():
            csv_count = await master_service.import_csv(args.csv)
            print(f"Module classification CSV: {csv_count} records imported")
        else:
            print("Module classification CSV: skipped (not provided or not found)")

    # Neo4j client
    neo4j_client = Neo4jClient(
        uri=settings.NEO4J_URI,
        user=settings.NEO4J_USER,
        password=settings.NEO4J_PASSWORD,
    )

    # Embedding service
    embedding_service = None
    if not args.skip_embedding and settings.OPENAI_API_KEY:
        embedding_service = EmbeddingService(
            api_key=settings.OPENAI_API_KEY,
            model=settings.EMBEDDING_MODEL,
        )
    elif not args.skip_embedding:
        print("WARNING: OPENAI_API_KEY not set, skipping embedding generation")

    # LLM client (for description generation)
    llm_client = None
    if not args.skip_llm:
        try:
            from app.core.llm_client import LLMClient
            llm_client = LLMClient(settings)
        except Exception as e:
            print(f"WARNING: LLM client init failed ({e}), using fallback descriptions")

    # ─── 3. BPDパース ─────────────────────────
    scope_items: list[ScopeItemData] = []

    if bpd_sets:
        print(f"\n--- Phase: BPD Parsing ({len(bpd_sets)} sets) ---")

        for i, bpd_set in enumerate(bpd_sets, 1):
            prefix = bpd_set["prefix"]
            try:
                async with session_factory() as session:
                    master = ModuleClassificationService(session)
                    parser = BPDParser(llm_client=llm_client, master_service=master)

                    si = await parser.parse_scope_item(
                        ja_docx_path=bpd_set["ja"],
                        en_docx_path=bpd_set.get("en"),
                        xlsx_path=bpd_set.get("xlsx"),
                    )
                    scope_items.append(si)
                    status = "OK"
                    detail = f"module={si.module}, fn={si.function_name[:30]}"
            except Exception as e:
                status = "ERROR"
                detail = str(e)[:80]
                errors.append(f"BPD {prefix}: {e}")
                logger.exception("BPD parse error for %s", prefix)

            print(f"  [{i}/{len(bpd_sets)}] {prefix} ... {status} ({detail})")

    # ─── 4. PDFパース ─────────────────────────
    module_overviews: list[ModuleOverviewData] = []

    if pdfs:
        print(f"\n--- Phase: PDF Parsing ({len(pdfs)} files) ---")
        pdf_parser = ModuleOverviewParser(llm_client=llm_client)

        for i, pdf_path in enumerate(pdfs, 1):
            try:
                mo = await pdf_parser.parse_module_overview(pdf_path)
                module_overviews.append(mo)
                status = "OK"
                detail = f"module={mo.module}, pages={mo.page_count}, covers={len(mo.covers_scope_items)}"
            except Exception as e:
                status = "ERROR"
                detail = str(e)[:80]
                errors.append(f"PDF {pdf_path.name}: {e}")
                logger.exception("PDF parse error for %s", pdf_path.name)

            print(f"  [{i}/{len(pdfs)}] {pdf_path.name[:50]} ... {status} ({detail})")

    # ─── 5. Neo4j投入 ─────────────────────────
    result = LoadResult()

    if args.dry_run:
        print(f"\n--- DRY-RUN: Skipping Neo4j load ---")
        result.scope_items_loaded = len(scope_items)
        result.module_overviews_loaded = len(module_overviews)
    else:
        print(f"\n--- Phase: Neo4j Bulk Load ---")
        loader = KnowledgeLoader(neo4j_client, embedding_service)
        result = await loader.bulk_load(
            scope_items=scope_items,
            module_overviews=module_overviews,
            batch_size=settings.EMBEDDING_BATCH_SIZE,
        )

    # ─── 6. 完了レポート ──────────────────────
    total_time = time.time() - start_time

    print(f"\n{'=' * 50}")
    print(f"=== Completion Report ===")
    print(f"{'=' * 50}")
    print(f"ScopeItem nodes loaded:       {result.scope_items_loaded}")
    print(f"ScopeItem relations created:  {result.scope_item_relations_created}")
    print(f"ModuleOverview nodes loaded:  {result.module_overviews_loaded}")
    print(f"COVERS relations created:     {result.covers_relations_created}")
    print(f"Warnings:                     {len(result.warnings)}")
    print(f"Errors:                       {len(errors)}")
    print(f"Total duration:               {total_time:.1f}s")

    if result.warnings:
        print(f"\n--- Warnings ({len(result.warnings)}) ---")
        for w in result.warnings[:20]:
            print(f"  WARN: {w}")
        if len(result.warnings) > 20:
            print(f"  ... and {len(result.warnings) - 20} more")

    if errors:
        print(f"\n--- Errors ({len(errors)}) ---")
        for e in errors:
            print(f"  ERROR: {e}")

    # Cleanup
    await neo4j_client.close()
    await engine.dispose()


def main():
    parser = argparse.ArgumentParser(
        description="Knowledge Loader CLI - BPD/PDF → Neo4j",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--bpd-dir",
        type=Path,
        default=Path(__file__).resolve().parent.parent.parent / "product_doc",
        help="BPDファイルディレクトリ（default: product_doc/）",
    )
    parser.add_argument(
        "--pdf-dir",
        type=Path,
        default=Path(__file__).resolve().parent.parent.parent / "product_doc",
        help="PDFファイルディレクトリ（default: product_doc/）",
    )
    parser.add_argument(
        "--csv",
        type=Path,
        default=Path(__file__).resolve().parent.parent / "data" / "module_classification_sap.csv",
        help="モジュール分類CSVパス",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="パースのみ実行、Neo4j投入をスキップ",
    )
    parser.add_argument(
        "--skip-embedding",
        action="store_true",
        help="Embedding生成をスキップ",
    )
    parser.add_argument(
        "--skip-llm",
        action="store_true",
        help="LLM description生成をスキップ（fallback: purpose先頭テキスト）",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="処理するBPDセット数の上限（0=全件）",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="詳細ログ出力",
    )
    parser.add_argument(
        "--local",
        action="store_true",
        help="ローカル実行（localhost:5435/7688 に接続）",
    )

    args = parser.parse_args()

    log_level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    asyncio.run(run(args))


if __name__ == "__main__":
    main()
