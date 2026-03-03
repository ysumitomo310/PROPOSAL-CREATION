"""Excelカラムマッピング設定スキーマ（design.md準拠）"""

from pydantic import BaseModel, ConfigDict


class ColumnMapping(BaseModel):
    """各フィールドとExcel列名の対応。"""

    model_config = ConfigDict(from_attributes=True)

    business_category: list[str] | None = None  # 階層分類列名（複数対応: ["Lv.1","Lv.2","Lv.3"]）
    business_name: str | None = None  # 業務名列
    function_name: str  # 必須: 機能名列
    requirement_summary: str | None = None  # 要件概要列
    requirement_detail: str | None = None  # 要件詳細列
    importance: str | None = None  # 重要度列
    importance_mapping: dict[str, str] | None = None  # 値変換: {"1":"Must","2":"Should","3":"Could"}


class ColumnMappingConfig(BaseModel):
    """Excelカラムマッピング設定。"""

    model_config = ConfigDict(from_attributes=True)

    header_row: int = 1  # ヘッダー行番号
    data_start_row: int = 2  # データ開始行
    sheet_name: str | None = None  # シート名（None=最初のシート）
    columns: ColumnMapping
