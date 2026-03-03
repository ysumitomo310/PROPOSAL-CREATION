"""ModuleClassificationService テスト（TASK-B01）"""

import csv
import tempfile
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.models.base import Base
from app.models.module_classification import ModuleClassification
from app.services.knowledge.master import ModuleClassificationService, ModuleInfo


@pytest.fixture
async def async_session():
    """テスト用 async PostgreSQL セッション。"""
    # テスト用に実際のPostgreSQLを使用（docker compose で起動済み前提）
    url = "postgresql+asyncpg://proposal_user:proposal_dev_2026@localhost:5435/proposal_creation"
    engine = create_async_engine(url, echo=False)

    async with engine.begin() as conn:
        # テーブルが存在することを確認（alembic で作成済み）
        await conn.execute(text("DELETE FROM module_classification"))

    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        yield session

    await engine.dispose()


@pytest.mark.asyncio
async def test_bulk_upsert_and_get(async_session: AsyncSession):
    service = ModuleClassificationService(async_session)

    records = [
        {
            "scope_item_prefix": "1B4",
            "module": "SD",
            "module_name_ja": "販売管理",
            "business_domain": "販売",
            "product": "SAP",
        },
        {
            "scope_item_prefix": "BD9",
            "module": "SD",
            "module_name_ja": "販売管理",
            "business_domain": "販売",
            "product": "SAP",
        },
    ]
    count = await service.bulk_upsert(records)
    assert count == 2

    info = await service.get_module("1B4")
    assert info is not None
    assert info.module == "SD"
    assert info.module_name_ja == "販売管理"
    assert info.business_domain == "販売"


@pytest.mark.asyncio
async def test_get_module_not_found(async_session: AsyncSession):
    service = ModuleClassificationService(async_session)
    info = await service.get_module("NONEXISTENT")
    assert info is None


@pytest.mark.asyncio
async def test_upsert_updates_existing(async_session: AsyncSession):
    service = ModuleClassificationService(async_session)

    await service.bulk_upsert([{
        "scope_item_prefix": "1NS",
        "module": "MM",
        "module_name_ja": "購買管理",
        "business_domain": "購買",
        "product": "SAP",
    }])

    # 更新
    await service.bulk_upsert([{
        "scope_item_prefix": "1NS",
        "module": "MM",
        "module_name_ja": "購買管理（更新）",
        "business_domain": "購買",
        "product": "SAP",
    }])

    info = await service.get_module("1NS")
    assert info is not None
    assert info.module_name_ja == "購買管理（更新）"


@pytest.mark.asyncio
async def test_import_csv(async_session: AsyncSession):
    service = ModuleClassificationService(async_session)

    # テスト用CSV作成
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".csv", delete=False, newline="", encoding="utf-8"
    ) as f:
        writer = csv.DictWriter(
            f,
            fieldnames=["scope_item_prefix", "module", "module_name_ja", "business_domain", "product"],
        )
        writer.writeheader()
        writer.writerow({
            "scope_item_prefix": "TEST1",
            "module": "FI",
            "module_name_ja": "財務会計",
            "business_domain": "財務",
            "product": "SAP",
        })
        writer.writerow({
            "scope_item_prefix": "TEST2",
            "module": "CO",
            "module_name_ja": "管理会計",
            "business_domain": "管理会計",
            "product": "SAP",
        })
        csv_path = Path(f.name)

    count = await service.import_csv(csv_path)
    assert count == 2

    info = await service.get_module("TEST1")
    assert info is not None
    assert info.module == "FI"

    csv_path.unlink()


@pytest.mark.asyncio
async def test_get_all(async_session: AsyncSession):
    service = ModuleClassificationService(async_session)

    await service.bulk_upsert([
        {"scope_item_prefix": "A1", "module": "SD", "module_name_ja": "販売管理", "business_domain": "販売", "product": "SAP"},
        {"scope_item_prefix": "A2", "module": "MM", "module_name_ja": "購買管理", "business_domain": "購買", "product": "SAP"},
    ])

    all_records = await service.get_all()
    assert len(all_records) >= 2

    sap_records = await service.get_all(product="SAP")
    assert len(sap_records) >= 2
