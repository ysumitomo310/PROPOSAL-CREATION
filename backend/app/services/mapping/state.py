"""MappingState 定義（TASK-C01）

LangGraph TypedDict ステート。design.md MappingState 準拠。
8グループ: Input / Analysis / Search / Evaluation / Traversal / Judgment / Generation / Metadata
"""

from typing import TypedDict


class MappingState(TypedDict, total=False):
    """Agentic RAG パイプラインの状態。

    total=False で全フィールドをOptionalとし、
    LangGraphノードが段階的にフィールドを埋める設計。
    """

    # --- Input（開始時セット、不変） ---
    requirement_id: str
    function_name: str
    requirement_summary: str
    requirement_detail: str
    business_category: str
    importance: str
    product_namespace: str  # "SAP"

    # --- Analysis（AnalyzeRequirementがセット） ---
    analyzed_keywords: list[str]
    analyzed_domain: str
    analyzed_intent: str

    # --- Search（イテレーションごと更新） ---
    search_query: str           # 代表クエリ（履歴・ログ用）
    search_queries: list[str]   # [UPGRADE-D] 複数クエリ（RAG-Fusion並列検索用）
    search_results: list[dict]
    search_score: float  # top-3加重平均スコア
    retry_count: int  # 0-3
    search_history: list[dict]

    # --- Evaluation ---
    is_sufficient: bool
    evaluation_reasoning: str

    # --- Traversal ---
    traversed_nodes: list[dict]
    module_overview_context: str

    # --- Judgment ---
    judgment_level: str  # SAP: 標準対応/標準(業務変更含む)/アドオン開発/外部連携/対象外
    confidence: str  # High/Medium/Low
    confidence_score: float  # 0.0-1.0
    scope_item_analysis: str  # ScopeItem適合根拠
    gap_analysis: str         # ギャップ・課題
    judgment_reason: str      # 判定結論
    matched_scope_items: list[dict]

    # --- Generation ---
    proposal_text: str

    # --- Metadata ---
    langsmith_trace_id: str
    started_at: str
    completed_at: str
    error_message: str | None


def build_initial_state(
    requirement_id: str,
    function_name: str,
    requirement_summary: str = "",
    requirement_detail: str = "",
    business_category: str = "",
    importance: str = "",
    product_namespace: str = "SAP",
) -> MappingState:
    """初期状態を構築するヘルパー。"""
    return MappingState(
        requirement_id=requirement_id,
        function_name=function_name,
        requirement_summary=requirement_summary,
        requirement_detail=requirement_detail,
        business_category=business_category,
        importance=importance,
        product_namespace=product_namespace,
        analyzed_keywords=[],
        analyzed_domain="",
        analyzed_intent="",
        search_query="",
        search_queries=[],
        search_results=[],
        search_score=0.0,
        retry_count=0,
        search_history=[],
        is_sufficient=False,
        evaluation_reasoning="",
        traversed_nodes=[],
        module_overview_context="",
        judgment_level="",
        confidence="",
        confidence_score=0.0,
        scope_item_analysis="",
        gap_analysis="",
        judgment_reason="",
        matched_scope_items=[],
        proposal_text="",
        langsmith_trace_id="",
        started_at="",
        completed_at="",
        error_message=None,
    )
