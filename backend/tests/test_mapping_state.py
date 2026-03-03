"""MappingState テスト（TASK-C01）"""

from app.services.mapping.state import MappingState, build_initial_state


class TestMappingState:
    def test_build_initial_state(self):
        state = build_initial_state(
            requirement_id="REQ-001",
            function_name="受注登録画面",
            requirement_summary="受注伝票を作成できること",
            requirement_detail="受注登録画面で受注伝票を作成できること",
            business_category="販売管理",
            importance="必須",
        )
        assert state["requirement_id"] == "REQ-001"
        assert state["function_name"] == "受注登録画面"
        assert state["product_namespace"] == "SAP"
        assert state["retry_count"] == 0
        assert state["search_results"] == []
        assert state["is_sufficient"] is False
        assert state["error_message"] is None

    def test_build_initial_state_defaults(self):
        state = build_initial_state(
            requirement_id="REQ-002",
            function_name="テスト機能",
        )
        assert state["requirement_summary"] == ""
        assert state["business_category"] == ""
        assert state["product_namespace"] == "SAP"

    def test_state_is_mutable(self):
        state = build_initial_state(
            requirement_id="REQ-003",
            function_name="テスト",
        )
        state["analyzed_keywords"] = ["受注", "販売"]
        state["search_score"] = 0.85
        state["is_sufficient"] = True

        assert state["analyzed_keywords"] == ["受注", "販売"]
        assert state["search_score"] == 0.85
        assert state["is_sufficient"] is True

    def test_state_has_all_groups(self):
        state = build_initial_state(
            requirement_id="REQ-004",
            function_name="テスト",
        )
        # Input group
        assert "requirement_id" in state
        assert "product_namespace" in state
        # Analysis group
        assert "analyzed_keywords" in state
        assert "analyzed_domain" in state
        # Search group
        assert "search_query" in state
        assert "retry_count" in state
        # Evaluation group
        assert "is_sufficient" in state
        # Traversal group
        assert "traversed_nodes" in state
        assert "module_overview_context" in state
        # Judgment group
        assert "judgment_level" in state
        assert "confidence_score" in state
        assert "matched_scope_items" in state
        # Generation group
        assert "proposal_text" in state
        # Metadata group
        assert "langsmith_trace_id" in state
        assert "error_message" in state
