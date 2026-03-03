"""マッピング結果スキーマ（design.md準拠）"""

from datetime import datetime

from pydantic import BaseModel, ConfigDict


class MappingStartResponse(BaseModel):
    """マッピング開始レスポンス。"""

    case_id: str
    message: str = "Mapping started"
    total_requirements: int


class MappingResultItem(BaseModel):
    """マッピング結果一覧の1行。"""

    model_config = ConfigDict(from_attributes=True)

    id: str
    requirement_id: str
    sequence_number: int
    function_name: str
    requirement_summary: str | None
    importance: str | None
    judgment_level: str | None
    confidence: str | None
    confidence_score: float | None
    proposal_text: str | None
    rationale: str | None = None           # 旧フォーマット（後方互換）
    scope_item_analysis: str | None = None # ScopeItem適合根拠
    gap_analysis: str | None = None        # ギャップ・課題
    judgment_reason: str | None = None     # 判定結論
    matched_scope_items: list[dict] | None
    langsmith_trace_id: str | None
    status: str


class MappingResultsResponse(BaseModel):
    """マッピング結果一覧レスポンス。"""

    case_id: str
    total: int
    completed: int
    results: list[MappingResultItem]


class MappingResultDetail(MappingResultItem):
    """サイドパネル用の詳細レスポンス。"""

    business_category: str | None
    business_name: str | None
    requirement_detail: str | None
    related_nodes: list[dict] | None
    module_overview_context: str | None
    search_retry_count: int
    search_history: list[dict] | None
    started_at: datetime | None
    completed_at: datetime | None
