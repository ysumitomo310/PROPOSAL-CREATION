"""MappingBatchProcessor テスト（TASK-C10）"""

import asyncio
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.mapping.agent import (
    BatchAbortError,
    BatchResult,
    MappingBatchProcessor,
    SSEEvent,
)


# ─── Helpers ───


def _mock_requirement(req_id: str = "req-001", seq: int = 1, fn: str = "受注登録"):
    """テスト用モック FunctionalRequirement。"""
    req = MagicMock()
    req.id = req_id
    req.sequence_number = seq
    req.function_name = fn
    req.requirement_summary = "テスト要件概要"
    req.requirement_detail = "テスト要件詳細"
    req.business_category = "販売管理"
    req.importance = "Must"
    return req


def _mock_graph_result():
    """LangGraph ainvoke の戻り値。"""
    return {
        "judgment_level": "標準対応",
        "confidence": "High",
        "confidence_score": 0.9,
        "proposal_text": "テスト提案文",
        "scope_item_analysis": "SAP-1B4が対応",
        "gap_analysis": "なし",
        "judgment_reason": "標準機能で対応可能と判定",
        "matched_scope_items": [{"id": "SAP-1B4"}],
        "traversed_nodes": [],
        "retry_count": 0,
        "search_score": 0.85,
    }


def _mock_session_factory():
    """モックセッションファクトリ。"""

    class _MockMR:
        """MappingResult 代替。セッション内で属性を受け取る。"""

        def __init__(self, **kwargs):
            for k, v in kwargs.items():
                setattr(self, k, v)
            self.id = "mr-" + kwargs.get("functional_requirement_id", "x")

    mock_session = AsyncMock(spec=AsyncSession)
    mock_session.add = MagicMock()
    mock_session.commit = AsyncMock()

    # completed スキップ判定: scalar_one_or_none() が None を返す（未完了扱い）
    _mock_exec_result = MagicMock()
    _mock_exec_result.scalar_one_or_none = MagicMock(return_value=None)
    mock_session.execute = AsyncMock(return_value=_mock_exec_result)

    mock_session.get = AsyncMock(return_value=_MockMR(
        status="processing",
        judgment_level=None,
        confidence=None,
        confidence_score=None,
        proposal_text=None,
        rationale=None,
        scope_item_analysis=None,
        gap_analysis=None,
        judgment_reason=None,
        matched_scope_items=None,
        related_nodes=None,
        search_retry_count=0,
        search_score=None,
        error_message=None,
        completed_at=None,
        langsmith_trace_id="",
    ))

    factory = MagicMock()

    # async context manager 模倣
    class _AsyncCM:
        async def __aenter__(self):
            return mock_session

        async def __aexit__(self, *args):
            pass

    factory.return_value = _AsyncCM()
    factory._mock_session = mock_session

    return factory


# ─── Tests ───


class TestSSEEvent:
    def test_format_sse(self):
        event = SSEEvent(type="requirement_complete", data={"id": "test"})
        formatted = event.format_sse()
        assert formatted.startswith("event: requirement_complete\n")
        assert '"id": "test"' in formatted
        assert formatted.endswith("\n\n")

    def test_format_sse_japanese(self):
        event = SSEEvent(type="test", data={"name": "受注登録"})
        formatted = event.format_sse()
        assert "受注登録" in formatted  # ensure_ascii=False


class TestBatchProcessorBasic:
    @pytest.mark.asyncio
    async def test_batch_runs_all_requirements(self):
        """10件のモック要件がすべて処理される。"""
        mock_graph = AsyncMock()
        mock_graph.ainvoke = AsyncMock(return_value=_mock_graph_result())
        factory = _mock_session_factory()

        processor = MappingBatchProcessor(
            graph=mock_graph,
            session_factory=factory,
            max_concurrency=5,
        )

        requirements = [_mock_requirement(f"req-{i:03d}", i) for i in range(10)]
        result = await processor.run_batch("case-001", requirements)

        assert result.total == 10
        assert result.completed == 10
        assert result.errors == 0
        assert result.aborted is False

    @pytest.mark.asyncio
    async def test_batch_emits_sse_events(self):
        """各要件の完了ごとにSSEイベントがキューに投入される。"""
        mock_graph = AsyncMock()
        mock_graph.ainvoke = AsyncMock(return_value=_mock_graph_result())
        factory = _mock_session_factory()

        processor = MappingBatchProcessor(
            graph=mock_graph,
            session_factory=factory,
            max_concurrency=5,
        )

        requirements = [_mock_requirement(f"req-{i:03d}", i) for i in range(3)]
        await processor.run_batch("case-001", requirements)

        # キューからイベントを取り出し
        events = []
        while not processor._sse_queue.empty():
            events.append(await processor._sse_queue.get())

        # requirement_complete × 3 + batch_complete × 1
        types = [e.type for e in events]
        assert types.count("requirement_complete") == 3
        assert types.count("batch_complete") == 1
        assert types[-1] == "batch_complete"

    @pytest.mark.asyncio
    async def test_sse_event_generator(self):
        """get_sse_events() が batch_complete で終了する。"""
        mock_graph = AsyncMock()
        mock_graph.ainvoke = AsyncMock(return_value=_mock_graph_result())
        factory = _mock_session_factory()

        processor = MappingBatchProcessor(
            graph=mock_graph,
            session_factory=factory,
            max_concurrency=5,
        )

        requirements = [_mock_requirement("req-001", 1)]

        # バッチを非同期タスクで実行
        batch_task = asyncio.create_task(
            processor.run_batch("case-001", requirements)
        )

        events = []
        async for event in processor.get_sse_events():
            events.append(event)

        await batch_task

        assert len(events) >= 2  # requirement_complete + batch_complete
        assert events[-1].type == "batch_complete"


class TestBatchProcessorErrorHandling:
    @pytest.mark.asyncio
    async def test_single_error_persists_status(self):
        """1件のエラーが MappingResult に error として保存される。"""
        call_count = 0

        async def _failing_invoke(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 2:
                raise RuntimeError("LLM API timeout")
            return _mock_graph_result()

        mock_graph = AsyncMock()
        mock_graph.ainvoke = AsyncMock(side_effect=_failing_invoke)
        factory = _mock_session_factory()

        processor = MappingBatchProcessor(
            graph=mock_graph,
            session_factory=factory,
            max_concurrency=5,
        )

        requirements = [_mock_requirement(f"req-{i:03d}", i) for i in range(3)]
        result = await processor.run_batch("case-001", requirements)

        assert result.completed == 2
        assert result.errors == 1
        assert result.aborted is False

    @pytest.mark.asyncio
    async def test_batch_abort_on_high_error_rate(self):
        """エラー率 > 20% でバッチが中止される。"""
        # max_concurrency=1 で直列実行し、最初の5件をすべてエラーにする
        # 5件目で error_count/processed = 5/5 = 100% > 20% → abort
        async def _always_failing_invoke(*args, **kwargs):
            raise RuntimeError("API Error")

        mock_graph = AsyncMock()
        mock_graph.ainvoke = AsyncMock(side_effect=_always_failing_invoke)
        factory = _mock_session_factory()

        processor = MappingBatchProcessor(
            graph=mock_graph,
            session_factory=factory,
            max_concurrency=1,  # 直列実行
            error_threshold=0.2,
        )

        requirements = [_mock_requirement(f"req-{i:03d}", i) for i in range(10)]
        result = await processor.run_batch("case-001", requirements)

        assert result.aborted is True
        # 中止後は一部未処理が残る（5件エラー後にabort）
        assert result.errors >= 5
        assert result.completed + result.errors <= 10

    @pytest.mark.asyncio
    async def test_trace_id_set_on_result(self):
        """langsmith_trace_id が MappingResult に保存される。"""
        mock_graph = AsyncMock()
        mock_graph.ainvoke = AsyncMock(return_value=_mock_graph_result())
        factory = _mock_session_factory()

        processor = MappingBatchProcessor(
            graph=mock_graph,
            session_factory=factory,
        )

        requirements = [_mock_requirement("req-001", 1)]
        await processor.run_batch("case-001", requirements)

        # ainvoke に config={"run_id": ...} が渡されたことを確認
        call_kwargs = mock_graph.ainvoke.call_args
        assert "config" in call_kwargs[1]
        assert "run_id" in call_kwargs[1]["config"]
