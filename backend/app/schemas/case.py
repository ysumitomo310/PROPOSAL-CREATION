"""Caseスキーマ（design.md準拠）"""

from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.schemas.column_mapping import ColumnMappingConfig


class CaseCreate(BaseModel):
    """案件作成リクエスト。"""

    name: str
    product: str  # "SAP" or "GRANDIT"
    description: str | None = None
    column_mapping: ColumnMappingConfig | None = None


class CaseResponse(BaseModel):
    """案件レスポンス。"""

    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    product: str
    status: str
    total_requirements: int
    created_at: datetime
