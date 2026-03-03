"""マッピングAPI テスト（TASK-D02）"""

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.api.mapping import router
from app.schemas.mapping import MappingStartResponse


# ─── Helpers ───


def _create_test_app() -> FastAPI:
    """テスト用 FastAPI アプリ。"""
    app = FastAPI()
    app.include_router(router)
    app.state.active_batch_processors = {}
    app.state.settings = MagicMock()
    app.state.settings.MAPPING_MAX_CONCURRENCY = 5
    app.state.settings.MAPPING_ERROR_THRESHOLD = 0.2
    app.state.mapping_graph = MagicMock()
    return app


def _mock_session():
    """モック AsyncSession。"""
    session = AsyncMock()
    session.get = AsyncMock()
    session.execute = AsyncMock()
    session.commit = AsyncMock()
    return session


def _mock_case(case_id: str = "case-001", status: str = "created", total: int = 5):
    """モック Case。"""
    case = MagicMock()
    case.id = case_id
    case.status = status
    case.total_requirements = total
    return case


def _mock_requirement(req_id: str, seq: int):
    """モック FunctionalRequirement。"""
    req = MagicMock()
    req.id = req_id
    req.case_id = "case-001"
    req.sequence_number = seq
    req.function_name = f"機能{seq}"
    req.requirement_summary = "テスト"
    req.importance = "Must"
    return req


def _mock_mapping_result(mr_id: str, req_id: str, seq: int):
    """モック MappingResult + FunctionalRequirement ペア。"""
    mr = MagicMock()
    mr.id = mr_id
    mr.functional_requirement_id = req_id
    mr.judgment_level = "標準対応"
    mr.confidence = "High"
    mr.confidence_score = 0.9
    mr.proposal_text = "テスト提案文"
    mr.rationale = "SAP-1B4"
    mr.scope_item_analysis = "SAP-1B4が対応"
    mr.gap_analysis = "なし"
    mr.judgment_reason = "標準機能で対応可能"
    mr.matched_scope_items = [{"id": "SAP-1B4"}]
    mr.langsmith_trace_id = "trace-001"
    mr.status = "completed"

    fr = MagicMock()
    fr.id = req_id
    fr.sequence_number = seq
    fr.function_name = f"機能{seq}"
    fr.requirement_summary = "テスト"
    fr.importance = "Must"
    fr.case_id = "case-001"

    return mr, fr


# ─── Tests ───


class TestStartMapping:
    @pytest.mark.asyncio
    async def test_start_mapping_202(self):
        """正常系: 202 Accepted。"""
        session = _mock_session()
        case = _mock_case()
        session.get = AsyncMock(return_value=case)

        # 要件一覧のモック
        reqs = [_mock_requirement(f"req-{i}", i) for i in range(5)]
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = reqs
        session.execute = AsyncMock(return_value=mock_result)

        app = _create_test_app()

        class _CM:
            async def __aenter__(self):
                return session
            async def __aexit__(self, *a):
                pass

        factory = MagicMock(return_value=_CM())
        app.state.session_factory = factory

        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            resp = await client.post("/api/v1/cases/case-001/mapping/start")

        assert resp.status_code == 202
        data = resp.json()
        assert data["case_id"] == "case-001"
        assert data["total_requirements"] == 5

    @pytest.mark.asyncio
    async def test_start_mapping_case_not_found(self):
        """案件なし → 404。"""
        session = _mock_session()
        session.get = AsyncMock(return_value=None)

        app = _create_test_app()

        class _CM:
            async def __aenter__(self):
                return session
            async def __aexit__(self, *a):
                pass

        factory = MagicMock(return_value=_CM())
        app.state.session_factory = factory

        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            resp = await client.post("/api/v1/cases/nonexist/mapping/start")

        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_start_mapping_already_running(self):
        """実行中 → 409 Conflict。"""
        session = _mock_session()
        case = _mock_case(status="mapping")
        session.get = AsyncMock(return_value=case)

        app = _create_test_app()

        class _CM:
            async def __aenter__(self):
                return session
            async def __aexit__(self, *a):
                pass

        factory = MagicMock(return_value=_CM())
        app.state.session_factory = factory

        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            resp = await client.post("/api/v1/cases/case-001/mapping/start")

        assert resp.status_code == 409


class TestGetMappingResults:
    @pytest.mark.asyncio
    async def test_get_results_success(self):
        """正常系: 結果取得。"""
        session = _mock_session()
        case = _mock_case(total=2)
        session.get = AsyncMock(return_value=case)

        # JOINクエリ結果
        pairs = [_mock_mapping_result(f"mr-{i}", f"req-{i}", i) for i in range(2)]
        mock_result = MagicMock()
        mock_result.all.return_value = pairs
        session.execute = AsyncMock(return_value=mock_result)

        app = _create_test_app()

        class _CM:
            async def __aenter__(self):
                return session
            async def __aexit__(self, *a):
                pass

        factory = MagicMock(return_value=_CM())
        app.state.session_factory = factory

        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            resp = await client.get("/api/v1/cases/case-001/mapping/results")

        assert resp.status_code == 200
        data = resp.json()
        assert data["case_id"] == "case-001"
        assert data["total"] == 2
        assert len(data["results"]) == 2
        assert data["results"][0]["judgment_level"] == "標準対応"

    @pytest.mark.asyncio
    async def test_get_results_case_not_found(self):
        """案件なし → 404。"""
        session = _mock_session()
        session.get = AsyncMock(return_value=None)

        app = _create_test_app()

        class _CM:
            async def __aenter__(self):
                return session
            async def __aexit__(self, *a):
                pass

        factory = MagicMock(return_value=_CM())
        app.state.session_factory = factory

        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            resp = await client.get("/api/v1/cases/nonexist/mapping/results")

        assert resp.status_code == 404


class TestStreamMapping:
    @pytest.mark.asyncio
    async def test_stream_no_active_processor(self):
        """アクティブなプロセッサなし → 404。"""
        app = _create_test_app()

        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            resp = await client.get("/api/v1/cases/case-001/mapping/stream")

        assert resp.status_code == 404
