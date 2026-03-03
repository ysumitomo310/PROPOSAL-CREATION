"""Mapping ノード + ワークフロー テスト（TASK-C02〜C09）"""

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic import BaseModel

from app.services.mapping.state import MappingState, build_initial_state


# ─── Helpers ───


def _base_state(**overrides) -> MappingState:
    """テスト用の基本state。"""
    state = build_initial_state(
        requirement_id="REQ-001",
        function_name="受注登録画面",
        requirement_summary="受注伝票を作成できること",
        requirement_detail="受注登録画面で受注伝票を作成できること。得意先、品目、数量を入力し受注伝票を登録する。",
        business_category="販売管理",
        importance="必須",
    )
    state.update(overrides)
    return state


def _mock_llm_client():
    """モックLLMClient。"""
    client = MagicMock()
    client.call_light_structured = AsyncMock()
    client.call_heavy_structured = AsyncMock()
    client.call_heavy = AsyncMock()
    return client


# ─── C02: AnalyzeRequirement ───


class TestAnalyzeRequirementNode:
    @pytest.mark.asyncio
    async def test_analyze_returns_keywords_domain_intent(self):
        from app.services.mapping.nodes.analyze import AnalysisOutput, build_analyze_node

        mock_llm = _mock_llm_client()
        mock_llm.call_light_structured.return_value = AnalysisOutput(
            keywords=["受注", "受注伝票", "受注登録", "販売"],
            domain="販売",
            intent="受注伝票の登録機能",
        )

        node = build_analyze_node(mock_llm)
        result = await node(_base_state())

        assert "analyzed_keywords" in result
        assert "受注" in result["analyzed_keywords"]
        assert result["analyzed_domain"] == "販売"
        assert "受注" in result["analyzed_intent"]

    @pytest.mark.asyncio
    async def test_analyze_calls_light_structured(self):
        from app.services.mapping.nodes.analyze import AnalysisOutput, build_analyze_node

        mock_llm = _mock_llm_client()
        mock_llm.call_light_structured.return_value = AnalysisOutput(
            keywords=["テスト"], domain="その他", intent="テスト"
        )

        node = build_analyze_node(mock_llm)
        await node(_base_state())

        mock_llm.call_light_structured.assert_called_once()
        call_args = mock_llm.call_light_structured.call_args
        assert call_args[0][1] == AnalysisOutput


# ─── C03: GenerateQuery ───


class TestGenerateQueryNode:
    @pytest.mark.asyncio
    async def test_initial_query_generation_multi(self):
        """初回クエリ生成: 3視点クエリ + search_queriesリストを返す。"""
        from app.services.mapping.nodes.generate_query import MultiQueryOutput, build_generate_query_node

        mock_llm = _mock_llm_client()
        mock_llm.call_light_structured.return_value = MultiQueryOutput(
            query_function="受注登録 在庫確認 引当",
            query_process="販売 出荷 請求 入金",
            query_module="SD 販売管理 オーダー",
        )

        node = build_generate_query_node(mock_llm)
        state = _base_state(
            analyzed_keywords=["受注", "伝票", "販売"],
            analyzed_domain="販売",
            analyzed_intent="受注伝票登録",
        )
        result = await node(state)

        # search_queries（3クエリリスト）が返される
        assert "search_queries" in result
        assert len(result["search_queries"]) == 3
        # search_query（代表、1つ目）も返される
        assert "search_query" in result
        assert result["search_query"] == result["search_queries"][0]
        assert result["search_query"] == "受注登録 在庫確認 引当"

    @pytest.mark.asyncio
    async def test_retry_uses_search_history(self):
        """リトライ時: search_historyを参照した異なる3クエリを生成。"""
        from app.services.mapping.nodes.generate_query import MultiQueryOutput, build_generate_query_node

        mock_llm = _mock_llm_client()
        mock_llm.call_light_structured.return_value = MultiQueryOutput(
            query_function="売上伝票 得意先 販売注文",
            query_process="販売受注 出荷プロセス",
            query_module="SD 得意先マスタ",
        )

        node = build_generate_query_node(mock_llm)
        state = _base_state(
            retry_count=1,
            analyzed_keywords=["受注"],
            analyzed_domain="販売",
            search_history=[{
                "query": "受注伝票 登録",
                "queries": ["受注登録 在庫確認", "販売 出荷", "SD オーダー"],
                "reasoning": "関連するScope Itemが見つからない",
            }],
        )
        result = await node(state)

        assert result["search_queries"][0] == "売上伝票 得意先 販売注文"
        # プロンプトにsearch_historyが含まれることを確認
        call_args = mock_llm.call_light_structured.call_args
        messages = call_args[0][0]
        assert "前回" in messages[1].content

    @pytest.mark.asyncio
    async def test_requirement_summary_in_initial_prompt(self):
        """requirement_summaryが初回クエリ生成プロンプトに含まれる（カテゴリコード対応）。"""
        from app.services.mapping.nodes.generate_query import MultiQueryOutput, build_generate_query_node

        mock_llm = _mock_llm_client()
        mock_llm.call_light_structured.return_value = MultiQueryOutput(
            query_function="受注登録 販売伝票",
            query_process="販売 出荷",
            query_module="SD オーダー",
        )

        node = build_generate_query_node(mock_llm)
        state = _base_state(
            function_name="4.販売",  # カテゴリコード
            requirement_summary="受注伝票を作成できること",
            analyzed_keywords=["受注"],
            analyzed_domain="販売",
            analyzed_intent="受注伝票登録",
        )
        await node(state)

        call_args = mock_llm.call_light_structured.call_args
        messages = call_args[0][0]
        prompt = messages[1].content
        assert "受注伝票を作成できること" in prompt

    @pytest.mark.asyncio
    async def test_empty_queries_fallback_to_function_name(self):
        """空クエリが返された場合、function_nameでフォールバック。"""
        from app.services.mapping.nodes.generate_query import MultiQueryOutput, build_generate_query_node

        mock_llm = _mock_llm_client()
        mock_llm.call_light_structured.return_value = MultiQueryOutput(
            query_function="",
            query_process="",
            query_module="",
        )

        node = build_generate_query_node(mock_llm)
        state = _base_state(function_name="受注登録画面", retry_count=0, search_history=[])
        result = await node(state)

        # 空クエリはフォールバック
        assert result["search_query"] == "受注登録画面"
        assert len(result["search_queries"]) >= 1


# ─── C04: HybridSearch ───


def _make_search_result(node_id: str, score: float, module: str = "SD"):
    """SearchResult モックを生成するヘルパー。"""
    from app.services.knowledge.search import SearchResult
    return SearchResult(
        node_id=node_id,
        function_name=f"機能{node_id}",
        description=f"説明{node_id}",
        module=module,
        business_domain="販売",
        keywords=[],
        score=score,
        vector_score=score,
        keyword_score=0.0,
    )


class TestHybridSearchNode:
    @pytest.mark.asyncio
    async def test_single_query_fallback(self):
        """search_queriesがない場合はsearch_query単体で検索。"""
        from app.services.mapping.nodes.search import build_hybrid_search_node

        mock_service = AsyncMock()
        mock_service.search.return_value = [_make_search_result("SAP-1B4", 0.92)]

        node = build_hybrid_search_node(mock_service)
        state = _base_state(search_query="受注 販売", search_queries=[])
        result = await node(state)

        assert len(result["search_results"]) == 1
        assert result["search_results"][0]["node_id"] == "SAP-1B4"
        assert result["search_score"] == pytest.approx(0.92, abs=0.01)
        # 1クエリで1回だけ search が呼ばれる
        assert mock_service.search.call_count == 1

    @pytest.mark.asyncio
    async def test_multi_query_parallel_search(self):
        """search_queries（3クエリ）を並列検索してRRFマージ。"""
        from app.services.mapping.nodes.search import build_hybrid_search_node

        # 3クエリで異なる結果が返る
        mock_service = AsyncMock()
        mock_service.search.side_effect = [
            [_make_search_result("SAP-A", 0.90), _make_search_result("SAP-B", 0.70)],
            [_make_search_result("SAP-B", 0.80), _make_search_result("SAP-C", 0.60)],
            [_make_search_result("SAP-A", 0.85), _make_search_result("SAP-D", 0.75)],
        ]

        node = build_hybrid_search_node(mock_service)
        state = _base_state(
            search_queries=["受注登録 在庫", "販売 出荷 請求", "SD オーダー"],
            search_query="受注登録 在庫",
        )
        result = await node(state)

        # 3回並列検索が実行される
        assert mock_service.search.call_count == 3
        # RRFマージ: SAP-A（2クエリでtop1）, SAP-B（2クエリ）, SAP-D, SAP-C が含まれる
        node_ids = [r["node_id"] for r in result["search_results"]]
        assert "SAP-A" in node_ids
        assert "SAP-B" in node_ids

    @pytest.mark.asyncio
    async def test_rrf_deduplication(self):
        """RRFマージで重複ノードは1件に集約される。"""
        from app.services.mapping.nodes.search import _rrf_merge

        # 同じノードが両クエリに出てくる
        results1 = [_make_search_result("SAP-A", 0.90), _make_search_result("SAP-B", 0.70)]
        results2 = [_make_search_result("SAP-A", 0.85), _make_search_result("SAP-C", 0.60)]

        merged = _rrf_merge([results1, results2])

        # SAP-Aは1件のみ（重複排除）
        node_ids = [r.node_id for r in merged]
        assert node_ids.count("SAP-A") == 1
        assert len(node_ids) == 3  # A, B, C

    @pytest.mark.asyncio
    async def test_rrf_best_score_preserved(self):
        """RRFマージ後のスコアは全クエリ中の最高値。"""
        from app.services.mapping.nodes.search import _rrf_merge

        results1 = [_make_search_result("SAP-A", 0.70)]
        results2 = [_make_search_result("SAP-A", 0.90)]  # 同ノードの高スコア

        merged = _rrf_merge([results1, results2])

        # SAP-Aのスコアはmax(0.70, 0.90) = 0.90
        assert merged[0].node_id == "SAP-A"
        assert merged[0].score == pytest.approx(0.90, abs=0.01)

    @pytest.mark.asyncio
    async def test_search_empty_results(self):
        from app.services.mapping.nodes.search import build_hybrid_search_node

        mock_service = AsyncMock()
        mock_service.search.return_value = []

        node = build_hybrid_search_node(mock_service)
        result = await node(_base_state(search_queries=["不明クエリ"], search_query="不明クエリ"))

        assert result["search_results"] == []
        assert result["search_score"] == 0.0

    @pytest.mark.asyncio
    async def test_search_top3_weighted_average(self):
        """3件以上の結果の場合はtop-3加重平均スコアが計算される。"""
        from app.services.mapping.nodes.search import build_hybrid_search_node

        mock_service = AsyncMock()
        # scores: 0.9, 0.7, 0.5 → weighted: (0.9*0.6 + 0.7*0.3 + 0.5*0.1) / 1.0 = 0.80
        mock_service.search.return_value = [
            _make_search_result("SAP-A", 0.9),
            _make_search_result("SAP-B", 0.7),
            _make_search_result("SAP-C", 0.5),
        ]

        node = build_hybrid_search_node(mock_service)
        result = await node(_base_state(search_queries=["テスト"], search_query="テスト"))

        assert result["search_score"] == pytest.approx(0.80, abs=0.01)


# ─── C05: EvaluateResults（ルールベース）───


class TestEvaluateResultsNode:
    @pytest.mark.asyncio
    async def test_sufficient_high_score(self):
        """スコア≥0.70は即sufficient（LLMコールなし）。"""
        from app.services.mapping.nodes.evaluate import build_evaluate_results_node

        node = build_evaluate_results_node()
        state = _base_state(
            search_query="受注 販売",
            search_results=[{"node_id": "SAP-1B4", "score": 0.75, "function_name": "受注"}],
            search_score=0.75,
            retry_count=0,
            search_history=[],
        )
        result = await node(state)

        assert result["is_sufficient"] is True
        assert result["retry_count"] == 1
        assert len(result["search_history"]) == 1
        assert "0.75" in result["evaluation_reasoning"]

    @pytest.mark.asyncio
    async def test_insufficient_zero_results(self):
        """結果0件は即insufficient。"""
        from app.services.mapping.nodes.evaluate import build_evaluate_results_node

        node = build_evaluate_results_node()
        state = _base_state(
            search_query="不明クエリ",
            search_results=[],
            search_score=0.0,
            retry_count=0,
            search_history=[],
        )
        result = await node(state)

        assert result["is_sufficient"] is False
        assert result["retry_count"] == 1

    @pytest.mark.asyncio
    async def test_insufficient_low_score(self):
        """スコア<0.40は即insufficient。"""
        from app.services.mapping.nodes.evaluate import build_evaluate_results_node

        node = build_evaluate_results_node()
        state = _base_state(
            search_query="テスト",
            search_results=[{"node_id": "SAP-X", "score": 0.35, "function_name": "不関連"}],
            search_score=0.35,
            retry_count=0,
            search_history=[],
        )
        result = await node(state)

        assert result["is_sufficient"] is False

    @pytest.mark.asyncio
    async def test_gray_zone_sufficient(self):
        """灰色ゾーン(0.40-0.70): 3件以上 + top3avg≥0.50 → sufficient。"""
        from app.services.mapping.nodes.evaluate import build_evaluate_results_node

        node = build_evaluate_results_node()
        state = _base_state(
            search_query="テスト",
            search_results=[
                {"node_id": "SAP-A", "score": 0.60},
                {"node_id": "SAP-B", "score": 0.55},
                {"node_id": "SAP-C", "score": 0.50},
            ],
            search_score=0.60,
            retry_count=0,
            search_history=[],
        )
        result = await node(state)

        # top3avg = (0.60+0.55+0.50)/3 = 0.55 ≥ 0.50, count=3 → sufficient
        assert result["is_sufficient"] is True

    @pytest.mark.asyncio
    async def test_gray_zone_insufficient_few_results(self):
        """灰色ゾーン: 2件のみ → insufficient（件数不足）。"""
        from app.services.mapping.nodes.evaluate import build_evaluate_results_node

        node = build_evaluate_results_node()
        state = _base_state(
            search_query="テスト",
            search_results=[
                {"node_id": "SAP-A", "score": 0.65},
                {"node_id": "SAP-B", "score": 0.60},
            ],
            search_score=0.65,
            retry_count=0,
            search_history=[],
        )
        result = await node(state)

        # count=2 < 3 → insufficient
        assert result["is_sufficient"] is False

    @pytest.mark.asyncio
    async def test_no_llm_call(self):
        """EvaluateResultsはLLMを呼び出さない。"""
        from app.services.mapping.nodes.evaluate import build_evaluate_results_node

        # 依存なし（LLMクライアント不要）でノードが生成できる
        node = build_evaluate_results_node()
        state = _base_state(
            search_results=[{"node_id": "SAP-1B4", "score": 0.80}],
            search_score=0.80,
            retry_count=0,
            search_history=[],
        )
        # LLMモックなしで正常に動作することを確認
        result = await node(state)
        assert "is_sufficient" in result


# ─── C06: TraverseGraph ───


class TestTraverseGraphNode:
    @pytest.mark.asyncio
    async def test_traverse_returns_nodes(self):
        """RELATEDリレーションとModuleOverviewが返される。"""
        from app.services.mapping.nodes.traverse import build_traverse_graph_node

        mock_neo4j = AsyncMock()
        mock_neo4j.execute_query.return_value = [{
            "source_module": "SD",
            "related": [{"id": "SAP-BD9", "function_name": "在庫販売", "description": "テスト"}],
            "module_overviews": [{"id": "MO-SD", "module_name": "SD販売管理", "summary": "販売管理モジュール"}],
        }]

        node = build_traverse_graph_node(mock_neo4j)
        state = _base_state(
            search_results=[{"node_id": "SAP-1B4", "score": 0.9}],
        )
        result = await node(state)

        assert len(result["traversed_nodes"]) == 1
        assert result["traversed_nodes"][0]["source_id"] == "SAP-1B4"
        assert result["traversed_nodes"][0]["source_module"] == "SD"
        # relatedが返る（prerequisite/follow_onは削除済み）
        assert len(result["traversed_nodes"][0]["related"]) == 1
        assert "SD販売管理" in result["module_overview_context"]

    @pytest.mark.asyncio
    async def test_traverse_empty_search_results(self):
        from app.services.mapping.nodes.traverse import build_traverse_graph_node

        mock_neo4j = AsyncMock()
        node = build_traverse_graph_node(mock_neo4j)
        result = await node(_base_state(search_results=[]))

        assert result["traversed_nodes"] == []
        assert result["module_overview_context"] == ""

    @pytest.mark.asyncio
    async def test_traverse_no_prerequisite_or_follow_on_keys(self):
        """traversed_nodesにprerequisite/follow_onキーが存在しない。"""
        from app.services.mapping.nodes.traverse import build_traverse_graph_node

        mock_neo4j = AsyncMock()
        mock_neo4j.execute_query.return_value = [{
            "source_module": "FI",
            "related": [],
            "module_overviews": [],
        }]

        node = build_traverse_graph_node(mock_neo4j)
        state = _base_state(search_results=[{"node_id": "SAP-X", "score": 0.8}])
        result = await node(state)

        assert len(result["traversed_nodes"]) == 1
        tn = result["traversed_nodes"][0]
        assert "prerequisite" not in tn
        assert "follow_on" not in tn
        assert "related" in tn

    @pytest.mark.asyncio
    async def test_traverse_module_overview_fallback(self):
        """ModuleOverview未接続時に補完クエリが実行される。"""
        from app.services.mapping.nodes.traverse import build_traverse_graph_node

        mock_neo4j = AsyncMock()
        # メインクエリ: MOなし
        # 補完クエリ: MOあり
        mock_neo4j.execute_query.side_effect = [
            [{"source_module": "MM", "related": [], "module_overviews": []}],
            [{"module_name": "MM購買管理", "summary": "購買・調達プロセス"}],
        ]

        node = build_traverse_graph_node(mock_neo4j)
        state = _base_state(search_results=[{"node_id": "SAP-Y", "score": 0.8}])
        result = await node(state)

        assert mock_neo4j.execute_query.call_count == 2
        assert "MM購買管理" in result["module_overview_context"]


# ─── C07: FinalJudgment ───


class TestFinalJudgmentNode:
    @pytest.mark.asyncio
    async def test_judgment_standard(self):
        from app.services.mapping.nodes.judge import JudgmentOutput, build_final_judgment_node

        mock_llm = _mock_llm_client()
        # 3軸評価: llm_conf = 0.4*0.95 + 0.35*0.90 + 0.25*0.85 = 0.9075
        mock_llm.call_heavy_structured.return_value = JudgmentOutput(
            judgment_level="標準対応",
            match_quality=0.95,
            coverage=0.90,
            certainty=0.85,
            scope_item_analysis="SAP-1B4（受注から入金）が要件をカバー",
            gap_analysis="なし",
            judgment_reason="標準機能で要件を満たすため標準対応と判定",
            matched_items=["SAP-1B4"],
        )

        node = build_final_judgment_node(mock_llm)
        state = _base_state(
            search_results=[{
                "node_id": "SAP-1B4",
                "function_name": "受注から入金",
                "description": "テスト",
                "score": 0.92,
            }],
            search_score=0.92,
            traversed_nodes=[],
        )
        result = await node(state)

        assert result["judgment_level"] == "標準対応"
        # conf_score = 0.2*0.92 + 0.8*0.9075 = 0.910
        assert result["confidence"] == "High"
        assert result["confidence_score"] == pytest.approx(0.910, abs=0.01)
        assert "SAP-1B4" in result["scope_item_analysis"]
        assert len(result["matched_scope_items"]) == 1

    @pytest.mark.asyncio
    async def test_judgment_low_confidence(self):
        from app.services.mapping.nodes.judge import JudgmentOutput, build_final_judgment_node

        mock_llm = _mock_llm_client()
        # 3軸評価: llm_conf = 0.4*0.2 + 0.35*0.3 + 0.25*0.4 = 0.285
        mock_llm.call_heavy_structured.return_value = JudgmentOutput(
            judgment_level="アドオン開発",
            match_quality=0.2,
            coverage=0.3,
            certainty=0.4,
            scope_item_analysis="該当するScope Itemが見つからない",
            gap_analysis="標準機能に対応するScope Itemが存在しないためアドオン開発が必要",
            judgment_reason="標準機能では対応不可のためアドオン開発と判定",
            matched_items=[],
        )

        node = build_final_judgment_node(mock_llm)
        state = _base_state(search_score=0.2, search_results=[], traversed_nodes=[])
        result = await node(state)

        assert result["judgment_level"] == "アドオン開発"
        # conf_score = 0.2*0.2 + 0.8*0.285 = 0.268
        assert result["confidence"] == "Low"
        assert result["confidence_score"] == pytest.approx(0.268, abs=0.01)

    @pytest.mark.asyncio
    async def test_judgment_uses_temperature_zero(self):
        from app.services.mapping.nodes.judge import JudgmentOutput, build_final_judgment_node

        mock_llm = _mock_llm_client()
        mock_llm.call_heavy_structured.return_value = JudgmentOutput(
            judgment_level="標準対応",
            match_quality=0.8,
            coverage=0.8,
            certainty=0.8,
            scope_item_analysis="テスト",
            gap_analysis="なし",
            judgment_reason="テスト",
            matched_items=[],
        )

        node = build_final_judgment_node(mock_llm)
        await node(_base_state(search_results=[], traversed_nodes=[]))

        call_kwargs = mock_llm.call_heavy_structured.call_args[1]
        assert call_kwargs["temperature"] == 0

    @pytest.mark.asyncio
    async def test_judgment_multi_criteria_spread(self):
        """3軸の値が異なるとき、加重平均で正しく算出される。"""
        from app.services.mapping.nodes.judge import JudgmentOutput, build_final_judgment_node

        mock_llm = _mock_llm_client()
        # 3軸評価: llm_conf = 0.4*0.9 + 0.35*0.5 + 0.25*0.7 = 0.36 + 0.175 + 0.175 = 0.71
        mock_llm.call_heavy_structured.return_value = JudgmentOutput(
            judgment_level="標準(業務変更含む)",
            match_quality=0.9,
            coverage=0.5,
            certainty=0.7,
            scope_item_analysis="SAP-1B4の標準機能で一部対応可能",
            gap_analysis="業務変更が必要",
            judgment_reason="標準機能で対応可能だが業務プロセスの変更が必要なため標準(業務変更含む)と判定",
            matched_items=["SAP-1B4"],
        )

        node = build_final_judgment_node(mock_llm)
        state = _base_state(
            search_results=[{"node_id": "SAP-1B4", "function_name": "受注", "description": "テスト", "score": 0.85}],
            search_score=0.85,
            traversed_nodes=[],
        )
        result = await node(state)

        # conf_score = 0.2*0.85 + 0.8*0.71 = 0.17 + 0.568 = 0.738 → High (≥0.65)
        assert result["confidence_score"] == pytest.approx(0.738, abs=0.01)
        assert result["confidence"] == "High"

    @pytest.mark.asyncio
    async def test_judgment_zero_search_penalty(self):
        """search_score=0のとき、高llm_confidenceでもHighにならない。"""
        from app.services.mapping.nodes.judge import JudgmentOutput, build_final_judgment_node

        mock_llm = _mock_llm_client()
        # llm_conf = 0.4*0.8 + 0.35*0.7 + 0.25*0.6 = 0.32 + 0.245 + 0.15 = 0.715
        mock_llm.call_heavy_structured.return_value = JudgmentOutput(
            judgment_level="アドオン開発",
            match_quality=0.8,
            coverage=0.7,
            certainty=0.6,
            scope_item_analysis="なし",
            gap_analysis="なし",
            judgment_reason="検索結果なしだが関連知識から判定",
            matched_items=[],
        )

        node = build_final_judgment_node(mock_llm)
        state = _base_state(search_score=0.0, search_results=[], traversed_nodes=[])
        result = await node(state)

        # conf_score = 0.715 * 0.7 = 0.5005 → Medium (≥0.40)
        assert result["confidence_score"] == pytest.approx(0.5005, abs=0.01)
        assert result["confidence"] == "Medium"
        assert result["confidence_score"] < 0.65  # Highにはならない

    @pytest.mark.asyncio
    async def test_judgment_zero_search_medium(self):
        """search_score=0でもLLMが非常に高い確信度ならMediumになれる。"""
        from app.services.mapping.nodes.judge import JudgmentOutput, build_final_judgment_node

        mock_llm = _mock_llm_client()
        # llm_conf = 0.4*0.95 + 0.35*0.95 + 0.25*0.90 = 0.38 + 0.3325 + 0.225 = 0.9375
        mock_llm.call_heavy_structured.return_value = JudgmentOutput(
            judgment_level="対象外",
            match_quality=0.95,
            coverage=0.95,
            certainty=0.90,
            scope_item_analysis="なし",
            gap_analysis="なし",
            judgment_reason="明らかにSAP対象外の要件",
            matched_items=[],
        )

        node = build_final_judgment_node(mock_llm)
        state = _base_state(search_score=0.0, search_results=[], traversed_nodes=[])
        result = await node(state)

        # conf_score = 0.9375 * 0.7 = 0.65625 → 対象外capでMedium (Highは不可)
        assert result["confidence_score"] == pytest.approx(0.65625, abs=0.01)
        # 対象外なのでHighにはならない（Mediumに上限）
        assert result["confidence"] == "Medium"

    @pytest.mark.asyncio
    async def test_judgment_invalid_level_fallback(self):
        """LLMが定義外のjudgment_levelを返した場合、'アドオン開発'に補正される。"""
        from app.services.mapping.nodes.judge import JudgmentOutput, build_final_judgment_node

        mock_llm = _mock_llm_client()
        mock_llm.call_heavy_structured.return_value = JudgmentOutput(
            judgment_level="カスタマイズ対応",  # 定義外
            match_quality=0.7,
            coverage=0.6,
            certainty=0.7,
            scope_item_analysis="テスト",
            gap_analysis="なし",
            judgment_reason="テスト",
            matched_items=[],
        )

        node = build_final_judgment_node(mock_llm)
        result = await node(_base_state(search_results=[], traversed_nodes=[]))

        assert result["judgment_level"] == "アドオン開発"

    @pytest.mark.asyncio
    async def test_judgment_invalid_matched_items_filtered(self):
        """存在しないScope Item IDはmatched_scope_itemsから除外される。"""
        from app.services.mapping.nodes.judge import JudgmentOutput, build_final_judgment_node

        mock_llm = _mock_llm_client()
        mock_llm.call_heavy_structured.return_value = JudgmentOutput(
            judgment_level="標準対応",
            match_quality=0.8,
            coverage=0.7,
            certainty=0.8,
            scope_item_analysis="SAP-1B4とSAP-GHOSTが対応",
            gap_analysis="なし",
            judgment_reason="SAP-1B4が要件をカバーするため標準対応と判定",
            matched_items=["SAP-1B4", "SAP-GHOST"],  # SAP-GHOSTは存在しない
        )

        node = build_final_judgment_node(mock_llm)
        state = _base_state(
            search_results=[{
                "node_id": "SAP-1B4",
                "function_name": "受注から入金",
                "description": "テスト",
                "score": 0.85,
            }],
            search_score=0.85,
            traversed_nodes=[],
        )
        result = await node(state)

        # SAP-GHOSTは除外され、SAP-1B4のみ残る
        item_ids = [m["id"] for m in result["matched_scope_items"]]
        assert "SAP-1B4" in item_ids
        assert "SAP-GHOST" not in item_ids

    @pytest.mark.asyncio
    async def test_judgment_matched_items_fallback_to_top1(self):
        """matched_itemsが全件無効かつ検索結果あり → top-1で補填される。"""
        from app.services.mapping.nodes.judge import JudgmentOutput, build_final_judgment_node

        mock_llm = _mock_llm_client()
        mock_llm.call_heavy_structured.return_value = JudgmentOutput(
            judgment_level="標準対応",
            match_quality=0.8,
            coverage=0.7,
            certainty=0.8,
            scope_item_analysis="幻覚IDのみ引用",
            gap_analysis="なし",
            judgment_reason="幻覚IDのみ引用",
            matched_items=["SAP-NONEXISTENT"],  # 全件無効
        )

        node = build_final_judgment_node(mock_llm)
        state = _base_state(
            search_results=[{
                "node_id": "SAP-1B4",
                "function_name": "受注から入金",
                "description": "テスト",
                "score": 0.85,
            }],
            search_score=0.85,
            traversed_nodes=[],
        )
        result = await node(state)

        # top-1で補填
        assert len(result["matched_scope_items"]) == 1
        assert result["matched_scope_items"][0]["id"] == "SAP-1B4"

    @pytest.mark.asyncio
    async def test_judgment_taishogai_caps_confidence_to_medium(self):
        """対象外判定でconfidence_score≥0.5のとき、HighはMediumに上限。"""
        from app.services.mapping.nodes.judge import JudgmentOutput, build_final_judgment_node

        mock_llm = _mock_llm_client()
        # 高スコア環境で「対象外」を返す
        mock_llm.call_heavy_structured.return_value = JudgmentOutput(
            judgment_level="対象外",
            match_quality=0.9,
            coverage=0.9,
            certainty=0.9,
            scope_item_analysis="SAP-1B4が対象外を明示",
            gap_analysis="なし",
            judgment_reason="SAP製品の対象範囲外と判定",
            matched_items=["SAP-1B4"],
        )

        node = build_final_judgment_node(mock_llm)
        state = _base_state(
            search_results=[{
                "node_id": "SAP-1B4",
                "function_name": "受注から入金",
                "description": "テスト",
                "score": 0.95,
            }],
            search_score=0.95,
            traversed_nodes=[],
        )
        result = await node(state)

        assert result["judgment_level"] == "対象外"
        assert result["confidence"] != "High"  # Highには絶対ならない

    @pytest.mark.asyncio
    async def test_judgment_requirement_summary_in_prompt(self):
        """requirement_summaryがFinalJudgmentのプロンプトに含まれる。"""
        from app.services.mapping.nodes.judge import JudgmentOutput, build_final_judgment_node

        mock_llm = _mock_llm_client()
        mock_llm.call_heavy_structured.return_value = JudgmentOutput(
            judgment_level="標準対応",
            match_quality=0.8,
            coverage=0.8,
            certainty=0.8,
            scope_item_analysis="テスト",
            gap_analysis="なし",
            judgment_reason="テスト",
            matched_items=[],
        )

        node = build_final_judgment_node(mock_llm)
        state = _base_state(
            requirement_summary="受注伝票を作成できること",
            search_results=[],
            traversed_nodes=[],
        )
        await node(state)

        call_args = mock_llm.call_heavy_structured.call_args
        messages = call_args[0][0]
        human_message_content = messages[1].content
        assert "受注伝票を作成できること" in human_message_content

    @pytest.mark.asyncio
    async def test_judgment_module_domain_keywords_in_prompt(self):
        """[UPGRADE-A] module/business_domain/keywordsがプロンプトに含まれる。"""
        from app.services.mapping.nodes.judge import JudgmentOutput, build_final_judgment_node

        mock_llm = _mock_llm_client()
        mock_llm.call_heavy_structured.return_value = JudgmentOutput(
            judgment_level="標準対応",
            match_quality=0.9,
            coverage=0.8,
            certainty=0.9,
            scope_item_analysis="テスト",
            gap_analysis="なし",
            judgment_reason="テスト",
            matched_items=["SAP-1B4"],
        )

        node = build_final_judgment_node(mock_llm)
        state = _base_state(
            search_results=[{
                "node_id": "SAP-1B4",
                "function_name": "受注から入金",
                "description": "受注伝票登録から入金処理まで",
                "module": "SD",
                "business_domain": "販売",
                "keywords": ["受注", "出荷", "請求", "入金"],
                "score": 0.92,
                "vector_score": 0.88,
                "keyword_score": 0.75,
            }],
            search_score=0.92,
            traversed_nodes=[],
        )
        await node(state)

        call_args = mock_llm.call_heavy_structured.call_args
        messages = call_args[0][0]
        prompt = messages[1].content

        # モジュール・業務ドメイン・キーワードがプロンプトに含まれる
        assert "SD" in prompt
        assert "販売" in prompt
        assert "受注" in prompt  # keywords から

    @pytest.mark.asyncio
    async def test_judgment_related_node_description_in_prompt(self):
        """[UPGRADE-B] 関連ノードのdescriptionがプロンプトに含まれる。"""
        from app.services.mapping.nodes.judge import JudgmentOutput, build_final_judgment_node

        mock_llm = _mock_llm_client()
        mock_llm.call_heavy_structured.return_value = JudgmentOutput(
            judgment_level="標準対応",
            match_quality=0.8,
            coverage=0.8,
            certainty=0.8,
            scope_item_analysis="テスト",
            gap_analysis="なし",
            judgment_reason="テスト",
            matched_items=[],
        )

        node = build_final_judgment_node(mock_llm)
        state = _base_state(
            search_results=[],
            traversed_nodes=[{
                "source_id": "SAP-1B4",
                "source_module": "SD",
                "related": [{
                    "id": "SAP-BD9",
                    "function_name": "在庫販売",
                    "description": "在庫品の販売処理を管理するScope Item",
                }],
                "module_overviews": [],
            }],
        )
        await node(state)

        call_args = mock_llm.call_heavy_structured.call_args
        messages = call_args[0][0]
        prompt = messages[1].content

        # 関連ノードのdescriptionがプロンプトに含まれる
        assert "SAP-BD9" in prompt
        assert "在庫品の販売処理" in prompt

    @pytest.mark.asyncio
    async def test_judgment_domain_safety_net_overrides_taishogai(self):
        """対象外判定でanalyzed_domain='販売'の場合、アドオン開発に補正される。"""
        from app.services.mapping.nodes.judge import JudgmentOutput, build_final_judgment_node

        mock_llm = _mock_llm_client()
        mock_llm.call_heavy_structured.return_value = JudgmentOutput(
            judgment_level="対象外",
            match_quality=0.3,
            coverage=0.2,
            certainty=0.4,
            scope_item_analysis="マッチするScope Itemが見つからない",
            gap_analysis="該当機能なし",
            judgment_reason="SAP対象範囲外と判定",
            matched_items=[],
        )

        node = build_final_judgment_node(mock_llm)
        state = _base_state(
            search_results=[],
            search_score=0.0,
            traversed_nodes=[],
            analyzed_domain="販売",  # SAP標準ドメイン
        )
        result = await node(state)

        # ドメインセーフティネットにより「対象外」→「アドオン開発」に補正
        assert result["judgment_level"] == "アドオン開発"
        assert "自動補正" in result["judgment_reason"]

    @pytest.mark.asyncio
    async def test_judgment_domain_safety_net_preserves_non_sap_domain(self):
        """対象外判定でanalyzed_domain='その他'の場合、対象外のまま。"""
        from app.services.mapping.nodes.judge import JudgmentOutput, build_final_judgment_node

        mock_llm = _mock_llm_client()
        mock_llm.call_heavy_structured.return_value = JudgmentOutput(
            judgment_level="対象外",
            match_quality=0.1,
            coverage=0.1,
            certainty=0.3,
            scope_item_analysis="ERP範囲外の要件",
            gap_analysis="該当なし",
            judgment_reason="SAP対象範囲外",
            matched_items=[],
        )

        node = build_final_judgment_node(mock_llm)
        state = _base_state(
            search_results=[],
            search_score=0.0,
            traversed_nodes=[],
            analyzed_domain="その他",  # 非SAP標準ドメイン
        )
        result = await node(state)

        # セーフティネット不発動 → 対象外のまま
        assert result["judgment_level"] == "対象外"

    @pytest.mark.asyncio
    async def test_judgment_domain_safety_net_ignores_non_taishogai(self):
        """標準対応判定ではセーフティネットが発動しない。"""
        from app.services.mapping.nodes.judge import JudgmentOutput, build_final_judgment_node

        mock_llm = _mock_llm_client()
        mock_llm.call_heavy_structured.return_value = JudgmentOutput(
            judgment_level="標準対応",
            match_quality=0.9,
            coverage=0.85,
            certainty=0.9,
            scope_item_analysis="SAP-1B4が対応",
            gap_analysis="なし",
            judgment_reason="標準機能で対応可能",
            matched_items=["SAP-1B4"],
        )

        node = build_final_judgment_node(mock_llm)
        state = _base_state(
            search_results=[{
                "node_id": "SAP-1B4",
                "function_name": "受注から入金",
                "description": "テスト",
                "score": 0.9,
            }],
            search_score=0.9,
            traversed_nodes=[],
            analyzed_domain="販売",
        )
        result = await node(state)

        # 標準対応のまま（セーフティネットは対象外のみ対象）
        assert result["judgment_level"] == "標準対応"

    @pytest.mark.asyncio
    async def test_judgment_few_shot_examples_in_prompt(self):
        """[UPGRADE-C] Few-Shot例（標準対応/アドオン開発等）がシステムプロンプトに含まれる。"""
        from app.services.mapping.nodes.judge import JudgmentOutput, build_final_judgment_node, _USER_PROMPT

        # Few-Shot例がプロンプトテンプレートに含まれているかチェック
        assert "標準対応の例" in _USER_PROMPT or "標準対応" in _USER_PROMPT
        assert "アドオン開発" in _USER_PROMPT
        assert "外部連携" in _USER_PROMPT
        assert "対象外" in _USER_PROMPT


# ─── C08: GenerateProposal ───


class TestGenerateProposalNode:
    @pytest.mark.asyncio
    async def test_proposal_text_generated(self):
        from app.services.mapping.nodes.generate_proposal import build_generate_proposal_node

        mock_llm = _mock_llm_client()
        mock_response = MagicMock()
        mock_response.content = "貴社の受注管理機能は、SAP S/4 HANAの標準機能である「受注から入金（SAP-1B4）」で対応いたします。"
        mock_llm.call_heavy.return_value = mock_response

        node = build_generate_proposal_node(mock_llm)
        state = _base_state(
            judgment_level="標準対応",
            confidence="High",
            confidence_score=0.9,
            scope_item_analysis="SAP-1B4（受注から入金）が要件をカバー",
            gap_analysis="なし",
            judgment_reason="SAP-1B4が対応",
            matched_scope_items=[{"id": "SAP-1B4", "function_name": "受注から入金"}],
        )
        result = await node(state)

        assert "proposal_text" in result
        assert len(result["proposal_text"]) > 0
        assert "completed_at" in result

    @pytest.mark.asyncio
    async def test_proposal_uses_temperature_03(self):
        from app.services.mapping.nodes.generate_proposal import build_generate_proposal_node

        mock_llm = _mock_llm_client()
        mock_response = MagicMock()
        mock_response.content = "テスト提案文"
        mock_llm.call_heavy.return_value = mock_response

        node = build_generate_proposal_node(mock_llm)
        # 対象外以外のケース
        await node(_base_state(judgment_level="標準対応", matched_scope_items=[]))

        call_kwargs = mock_llm.call_heavy.call_args[1]
        assert call_kwargs["temperature"] == 0.3

    @pytest.mark.asyncio
    async def test_proposal_taishogai_skips_llm(self):
        """対象外判定時はLLMコールなしで定型文が返る。"""
        from app.services.mapping.nodes.generate_proposal import (
            _TAISHOGAI_PROPOSAL,
            build_generate_proposal_node,
        )

        mock_llm = _mock_llm_client()

        node = build_generate_proposal_node(mock_llm)
        state = _base_state(judgment_level="対象外")
        result = await node(state)

        # LLMコールなし
        mock_llm.call_heavy.assert_not_called()
        assert result["proposal_text"] == _TAISHOGAI_PROPOSAL
        assert "completed_at" in result


# ─── C09: Workflow ───


class TestWorkflow:
    def test_should_retry_search_insufficient(self):
        from app.services.mapping.agent import should_retry_search

        state = _base_state(is_sufficient=False, retry_count=1)
        assert should_retry_search(state) == "retry"

    def test_should_retry_search_sufficient(self):
        from app.services.mapping.agent import should_retry_search

        state = _base_state(is_sufficient=True, retry_count=1)
        assert should_retry_search(state) == "proceed"

    def test_should_retry_search_max_retries(self):
        from app.services.mapping.agent import should_retry_search

        state = _base_state(is_sufficient=False, retry_count=3)
        assert should_retry_search(state) == "proceed"

    def test_should_retry_search_zero_retries_insufficient(self):
        from app.services.mapping.agent import should_retry_search

        state = _base_state(is_sufficient=False, retry_count=0)
        assert should_retry_search(state) == "retry"

    def test_build_mapping_graph_compiles(self):
        from app.services.mapping.agent import build_mapping_graph

        mock_llm = _mock_llm_client()
        mock_neo4j = AsyncMock()
        mock_search = AsyncMock()

        graph = build_mapping_graph(mock_llm, mock_neo4j, mock_search)
        assert graph is not None
        # CompiledGraphはget_graphメソッドを持つ
        graph_repr = graph.get_graph()
        node_ids = [n.id for n in graph_repr.nodes.values()]
        assert "analyze_requirement" in node_ids
        assert "generate_query" in node_ids
        assert "hybrid_search" in node_ids
        assert "evaluate_results" in node_ids
        assert "traverse_graph" in node_ids
        assert "final_judgment" in node_ids
        assert "generate_proposal" in node_ids
