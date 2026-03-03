"""Agentic RAG パイプライン（TASK-C09 + C10）

LangGraph StateGraphで7ノードを接続。
evaluate_results → retry/proceed の条件分岐を含む。
MappingBatchProcessor でバッチ並行処理 + SSEイベント配信。
"""

import asyncio
import json
import logging
from collections.abc import AsyncGenerator
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Literal
from uuid import uuid4

from langgraph.graph import END, StateGraph
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.llm_client import LLMClient
from app.core.neo4j_client import Neo4jClient
from app.models.mapping_result import MappingResult
from app.models.requirement import FunctionalRequirement
from app.services.knowledge.search import HybridSearchService
from app.services.mapping.nodes.analyze import build_analyze_node
from app.services.mapping.nodes.evaluate import build_evaluate_results_node
from app.services.mapping.nodes.generate_proposal import build_generate_proposal_node
from app.services.mapping.nodes.generate_query import build_generate_query_node
from app.services.mapping.nodes.judge import build_final_judgment_node
from app.services.mapping.nodes.search import build_hybrid_search_node
from app.services.mapping.nodes.traverse import build_traverse_graph_node
from app.services.mapping.state import MappingState, build_initial_state

logger = logging.getLogger(__name__)


def should_retry_search(state: MappingState) -> Literal["retry", "proceed"]:
    """検索リトライ判定ロジック。

    - not sufficient AND retry_count < 3 → retry
    - otherwise → proceed
    """
    if not state.get("is_sufficient", False) and state.get("retry_count", 0) < 3:
        return "retry"
    return "proceed"


def build_mapping_graph(
    llm_client: LLMClient,
    neo4j_client: Neo4jClient,
    search_service: HybridSearchService,
):
    """Agentic RAGパイプラインのワークフロー定義。

    Graph Flow:
        START → AnalyzeRequirement → GenerateQuery → HybridSearch → EvaluateResults
        EvaluateResults → [retry] → GenerateQuery (loop, max 3)
        EvaluateResults → [proceed] → TraverseGraph → FinalJudgment → GenerateProposal → END
    """
    workflow = StateGraph(MappingState)

    # ノード登録
    workflow.add_node("analyze_requirement", build_analyze_node(llm_client))
    workflow.add_node("generate_query", build_generate_query_node(llm_client))
    workflow.add_node("hybrid_search", build_hybrid_search_node(search_service))
    workflow.add_node("evaluate_results", build_evaluate_results_node())
    workflow.add_node("traverse_graph", build_traverse_graph_node(neo4j_client))
    workflow.add_node("final_judgment", build_final_judgment_node(llm_client))
    workflow.add_node("generate_proposal", build_generate_proposal_node(llm_client))

    # エントリーポイント
    workflow.set_entry_point("analyze_requirement")

    # シーケンシャルエッジ
    workflow.add_edge("analyze_requirement", "generate_query")
    workflow.add_edge("generate_query", "hybrid_search")
    workflow.add_edge("hybrid_search", "evaluate_results")

    # 条件分岐エッジ
    workflow.add_conditional_edges(
        "evaluate_results",
        should_retry_search,
        {
            "retry": "generate_query",
            "proceed": "traverse_graph",
        },
    )

    # 最終パイプライン
    workflow.add_edge("traverse_graph", "final_judgment")
    workflow.add_edge("final_judgment", "generate_proposal")
    workflow.add_edge("generate_proposal", END)

    return workflow.compile()


# ─── TASK-C10: バッチプロセッサ + SSEキュー ───


@dataclass
class SSEEvent:
    """SSEイベントペイロード。"""

    type: str  # requirement_complete / progress / batch_complete / error
    data: dict = field(default_factory=dict)

    def format_sse(self) -> str:
        """SSEワイヤプロトコル形式にフォーマット。"""
        return f"event: {self.type}\ndata: {json.dumps(self.data, ensure_ascii=False)}\n\n"


@dataclass
class BatchResult:
    """バッチ処理サマリー。"""

    case_id: str
    total: int
    completed: int
    errors: int
    aborted: bool = False


class BatchAbortError(Exception):
    """エラー率が閾値を超えた場合に送出。"""

    pass


class MappingBatchProcessor:
    """バッチマッピング処理コントローラ。

    asyncio.Semaphore で並行制御、SSE Queue でリアルタイムイベント配信。
    エラー率が閾値(20%)を超えた場合はバッチ中止。
    """

    def __init__(
        self,
        graph,
        session_factory: async_sessionmaker[AsyncSession],
        max_concurrency: int = 5,
        error_threshold: float = 0.2,
    ) -> None:
        self._graph = graph
        self._session_factory = session_factory
        self._semaphore = asyncio.Semaphore(max_concurrency)
        self._error_threshold = error_threshold
        self._sse_queue: asyncio.Queue[SSEEvent] = asyncio.Queue()
        self._abort_event = asyncio.Event()
        self._error_count = 0
        self._completed_count = 0
        self._lock = asyncio.Lock()

    async def run_batch(
        self,
        case_id: str,
        requirements: list[FunctionalRequirement],
    ) -> BatchResult:
        """全要件を並行処理しバッチ結果を返す。"""
        total = len(requirements)
        self._error_count = 0
        self._completed_count = 0

        tasks = [
            asyncio.create_task(self._process_single(req, total))
            for req in requirements
        ]

        await asyncio.gather(*tasks, return_exceptions=True)

        aborted = self._abort_event.is_set()
        result = BatchResult(
            case_id=case_id,
            total=total,
            completed=self._completed_count,
            errors=self._error_count,
            aborted=aborted,
        )

        # Case ステータス更新
        async with self._session_factory() as session:
            from app.models.case import Case

            case = await session.get(Case, case_id)
            if case:
                case.status = "completed"
                case.completed_requirements = self._completed_count
                await session.commit()

        # batch_complete SSE
        await self._sse_queue.put(
            SSEEvent(
                type="batch_complete",
                data={
                    "case_id": case_id,
                    "total": total,
                    "completed": self._completed_count,
                    "errors": self._error_count,
                    "aborted": aborted,
                },
            )
        )

        return result

    async def _process_single(
        self,
        req: FunctionalRequirement,
        total: int,
    ) -> None:
        """単一要件のマッピング処理。"""
        if self._abort_event.is_set():
            return

        async with self._semaphore:
            if self._abort_event.is_set():
                return

            run_id = str(uuid4())

            async with self._session_factory() as session:
                # 既にcompletedの場合はスキップ（再実行時の重複処理防止）
                from sqlalchemy import select as sa_select
                existing = await session.execute(
                    sa_select(MappingResult).where(
                        MappingResult.functional_requirement_id == req.id,
                        MappingResult.status == "completed",
                    )
                )
                if existing.scalar_one_or_none():
                    async with self._lock:
                        self._completed_count += 1
                    return

                try:
                    # MappingResult 作成（processing状態）
                    mapping_result = MappingResult(
                        functional_requirement_id=req.id,
                        status="processing",
                        started_at=datetime.now(timezone.utc),
                        langsmith_trace_id=run_id,
                    )
                    session.add(mapping_result)
                    await session.commit()
                    result_id = mapping_result.id
                except Exception as e:
                    # 挿入失敗（unique制約等）はエラーとして計上
                    logger.error("Failed to create MappingResult for req %s: %s", req.id, e)
                    async with self._lock:
                        self._error_count += 1
                    return

                try:
                    # LangGraph 実行
                    initial_state = build_initial_state(
                        requirement_id=str(req.id),
                        function_name=req.function_name or "",
                        requirement_summary=req.requirement_summary or "",
                        requirement_detail=req.requirement_detail or "",
                        business_category=req.business_category or "",
                        importance=req.importance or "",
                    )

                    result = await self._graph.ainvoke(
                        initial_state,
                        config={"run_id": run_id},
                    )

                    # MappingResult 更新（completed）
                    mr = await session.get(MappingResult, result_id)
                    if mr:
                        mr.judgment_level = result.get("judgment_level")
                        mr.confidence = result.get("confidence")
                        mr.confidence_score = result.get("confidence_score")
                        mr.proposal_text = result.get("proposal_text")
                        mr.scope_item_analysis = result.get("scope_item_analysis")
                        mr.gap_analysis = result.get("gap_analysis")
                        mr.judgment_reason = result.get("judgment_reason")
                        mr.matched_scope_items = result.get("matched_scope_items")
                        mr.related_nodes = result.get("traversed_nodes")
                        mr.search_retry_count = result.get("retry_count", 0)
                        mr.search_score = result.get("search_score")
                        mr.status = "completed"
                        mr.completed_at = datetime.now(timezone.utc)
                        await session.commit()

                    async with self._lock:
                        self._completed_count += 1
                        completed = self._completed_count

                    # requirement_complete SSE
                    await self._sse_queue.put(
                        SSEEvent(
                            type="requirement_complete",
                            data={
                                "requirement_id": str(req.id),
                                "sequence_number": req.sequence_number,
                                "function_name": req.function_name,
                                "judgment_level": result.get("judgment_level"),
                                "confidence": result.get("confidence"),
                                "status": "completed",
                                "completed_count": completed,
                                "total_count": total,
                            },
                        )
                    )

                except Exception as e:
                    logger.error(
                        "Error processing requirement %s: %s",
                        req.id,
                        e,
                        exc_info=True,
                    )

                    # MappingResult をエラー状態に更新
                    mr = await session.get(MappingResult, result_id)
                    if mr:
                        mr.status = "error"
                        mr.error_message = str(e)[:1000]
                        mr.completed_at = datetime.now(timezone.utc)
                        await session.commit()

                    async with self._lock:
                        self._error_count += 1
                        error_count = self._error_count
                        processed = self._completed_count + error_count

                    # error SSE
                    await self._sse_queue.put(
                        SSEEvent(
                            type="error",
                            data={
                                "requirement_id": str(req.id),
                                "error": str(e)[:200],
                            },
                        )
                    )

                    # エラー閾値チェック
                    if (
                        processed >= 5
                        and (error_count / processed) > self._error_threshold
                    ):
                        self._abort_event.set()
                        logger.error(
                            "Batch abort: error rate %d/%d exceeds %.0f%%",
                            error_count,
                            processed,
                            self._error_threshold * 100,
                        )

    async def get_sse_events(self) -> AsyncGenerator[SSEEvent, None]:
        """SSEイベントを非同期で返すジェネレータ。batch_completeで終了。"""
        while True:
            event = await self._sse_queue.get()
            yield event
            if event.type == "batch_complete":
                break
