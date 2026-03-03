"""Pydantic スキーマのバリデーションテスト（TASK-A06）"""

import pytest
from pydantic import ValidationError

from app.schemas.case import CaseCreate, CaseResponse
from app.schemas.column_mapping import ColumnMapping, ColumnMappingConfig
from app.schemas.mapping import (
    MappingResultDetail,
    MappingResultItem,
    MappingResultsResponse,
    MappingStartResponse,
)


class TestColumnMapping:
    def test_minimal(self):
        cm = ColumnMapping(function_name="機能名")
        assert cm.function_name == "機能名"
        assert cm.business_category is None
        assert cm.importance_mapping is None

    def test_full(self):
        cm = ColumnMapping(
            business_category=["Lv.1", "Lv.2", "Lv.3"],
            business_name="業務名",
            function_name="機能名",
            requirement_summary="要件概要",
            requirement_detail="要件詳細",
            importance="重要度",
            importance_mapping={"1": "Must", "2": "Should", "3": "Could"},
        )
        assert len(cm.business_category) == 3
        assert cm.importance_mapping["1"] == "Must"

    def test_function_name_required(self):
        with pytest.raises(ValidationError):
            ColumnMapping()


class TestColumnMappingConfig:
    def test_defaults(self):
        cfg = ColumnMappingConfig(columns=ColumnMapping(function_name="機能名"))
        assert cfg.header_row == 1
        assert cfg.data_start_row == 2
        assert cfg.sheet_name is None

    def test_custom_values(self):
        cfg = ColumnMappingConfig(
            header_row=3,
            data_start_row=4,
            sheet_name="Sheet2",
            columns=ColumnMapping(function_name="Col_A"),
        )
        assert cfg.header_row == 3
        assert cfg.sheet_name == "Sheet2"


class TestCaseSchemas:
    def test_case_create_minimal(self):
        case = CaseCreate(name="Test Case", product="SAP")
        assert case.name == "Test Case"
        assert case.product == "SAP"
        assert case.description is None
        assert case.column_mapping is None

    def test_case_create_with_mapping(self):
        case = CaseCreate(
            name="SAP提案",
            product="SAP",
            description="テスト案件",
            column_mapping=ColumnMappingConfig(
                columns=ColumnMapping(function_name="機能名"),
            ),
        )
        assert case.column_mapping.columns.function_name == "機能名"

    def test_case_create_missing_required(self):
        with pytest.raises(ValidationError):
            CaseCreate(name="Test")  # product missing

    def test_case_response(self):
        resp = CaseResponse(
            id="abc-123",
            name="Test",
            product="GRANDIT",
            status="created",
            total_requirements=10,
            created_at="2026-02-18T00:00:00+09:00",
        )
        assert resp.id == "abc-123"
        assert resp.total_requirements == 10


class TestMappingSchemas:
    def test_mapping_start_response(self):
        resp = MappingStartResponse(case_id="abc", total_requirements=5)
        assert resp.message == "Mapping started"
        assert resp.total_requirements == 5

    def test_mapping_result_item(self):
        item = MappingResultItem(
            id="r1",
            requirement_id="req1",
            sequence_number=1,
            function_name="受注登録",
            requirement_summary="受注データの登録",
            importance="Must",
            judgment_level="標準",
            confidence="High",
            confidence_score=0.85,
            proposal_text="標準機能で対応可能",
            rationale="SAP-001に該当",
            matched_scope_items=[{"id": "SAP-001", "score": 0.9}],
            langsmith_trace_id="trace-xyz",
            status="completed",
        )
        assert item.confidence_score == 0.85
        assert item.matched_scope_items[0]["id"] == "SAP-001"

    def test_mapping_result_item_nullable_fields(self):
        item = MappingResultItem(
            id="r2",
            requirement_id="req2",
            sequence_number=2,
            function_name="在庫照会",
            requirement_summary=None,
            importance=None,
            judgment_level=None,
            confidence=None,
            confidence_score=None,
            proposal_text=None,
            rationale=None,
            matched_scope_items=None,
            langsmith_trace_id=None,
            status="pending",
        )
        assert item.status == "pending"
        assert item.confidence_score is None

    def test_mapping_results_response(self):
        resp = MappingResultsResponse(
            case_id="abc",
            total=2,
            completed=1,
            results=[
                MappingResultItem(
                    id="r1",
                    requirement_id="req1",
                    sequence_number=1,
                    function_name="受注登録",
                    requirement_summary=None,
                    importance=None,
                    judgment_level=None,
                    confidence=None,
                    confidence_score=None,
                    proposal_text=None,
                    rationale=None,
                    matched_scope_items=None,
                    langsmith_trace_id=None,
                    status="completed",
                ),
            ],
        )
        assert resp.total == 2
        assert len(resp.results) == 1

    def test_mapping_result_detail(self):
        detail = MappingResultDetail(
            id="r1",
            requirement_id="req1",
            sequence_number=1,
            function_name="受注登録",
            requirement_summary="受注データの登録",
            importance="Must",
            judgment_level="標準",
            confidence="High",
            confidence_score=0.85,
            proposal_text="標準機能で対応可能",
            rationale="SAP-001に該当",
            matched_scope_items=[{"id": "SAP-001"}],
            langsmith_trace_id="trace-xyz",
            status="completed",
            business_category="販売管理",
            business_name="受注管理",
            requirement_detail="受注データを登録する機能",
            related_nodes=[{"type": "Module", "name": "SD"}],
            module_overview_context="SDモジュールの概要...",
            search_retry_count=1,
            search_history=[{"query": "受注登録", "score": 0.8}],
            started_at="2026-02-18T10:00:00+09:00",
            completed_at="2026-02-18T10:00:05+09:00",
        )
        assert detail.business_category == "販売管理"
        assert detail.search_retry_count == 1
        assert detail.related_nodes[0]["type"] == "Module"
