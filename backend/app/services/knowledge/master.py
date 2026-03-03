"""モジュール分類マスターサービス（TASK-B01）

Scope Item ID → SAPモジュール分類のCRUD + CSVバルクインポート。
"""

import csv
import logging
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.module_classification import ModuleClassification

logger = logging.getLogger(__name__)


@dataclass
class ModuleInfo:
    module: str  # "SD"
    module_name_ja: str  # "販売管理"
    business_domain: str  # "販売"
    product: str  # "SAP"


class ModuleClassificationService:
    """モジュール分類マスターのCRUD操作。"""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_module(self, scope_item_prefix: str) -> ModuleInfo | None:
        """Scope Item Prefixからモジュール情報を取得。"""
        stmt = select(ModuleClassification).where(
            ModuleClassification.scope_item_prefix == scope_item_prefix
        )
        result = await self._session.execute(stmt)
        row = result.scalar_one_or_none()
        if row is None:
            return None
        return ModuleInfo(
            module=row.module,
            module_name_ja=row.module_name_ja,
            business_domain=row.business_domain,
            product=row.product,
        )

    async def get_all(self, product: str | None = None) -> list[ModuleInfo]:
        """全モジュール分類を取得。"""
        stmt = select(ModuleClassification)
        if product:
            stmt = stmt.where(ModuleClassification.product == product)
        result = await self._session.execute(stmt)
        return [
            ModuleInfo(
                module=row.module,
                module_name_ja=row.module_name_ja,
                business_domain=row.business_domain,
                product=row.product,
            )
            for row in result.scalars().all()
        ]

    async def bulk_upsert(self, records: list[dict]) -> int:
        """一括挿入/更新（PostgreSQL INSERT ON CONFLICT）。

        records: list of dicts with keys:
            scope_item_prefix, module, module_name_ja, business_domain, product
        """
        if not records:
            return 0
        stmt = pg_insert(ModuleClassification).values(records)
        stmt = stmt.on_conflict_do_update(
            index_elements=["scope_item_prefix"],
            set_={
                "module": stmt.excluded.module,
                "module_name_ja": stmt.excluded.module_name_ja,
                "business_domain": stmt.excluded.business_domain,
                "product": stmt.excluded.product,
            },
        )
        await self._session.execute(stmt)
        await self._session.commit()
        return len(records)

    async def import_csv(self, csv_path: Path) -> int:
        """CSVファイルからマスターデータをインポート。

        CSV format: scope_item_prefix,module,module_name_ja,business_domain,product
        """
        records = []
        with open(csv_path, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                records.append({
                    "scope_item_prefix": row["scope_item_prefix"].strip(),
                    "module": row["module"].strip(),
                    "module_name_ja": row["module_name_ja"].strip(),
                    "business_domain": row["business_domain"].strip(),
                    "product": row["product"].strip(),
                })
        count = await self.bulk_upsert(records)
        logger.info("Imported %d records from %s", count, csv_path)
        return count
