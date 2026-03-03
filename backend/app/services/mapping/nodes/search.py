"""HybridSearch ノード（TASK-C04）

HybridSearchServiceをLangGraphノードとしてラップ。
クエリEmbedding生成→検索実行→search_results/search_scoreをstateにセット。

[UPGRADE-D] RAG-Fusion（複数クエリ並列検索 + RRFマージ）:
- search_queries（複数クエリ）を asyncio.gather で並列検索
- Reciprocal Rank Fusion（RRF, k=60）で結果をマージしランク安定化
- 各クエリのbest_scoreをノードの最終スコアとして保持（既存閾値と互換）
"""

import asyncio
from collections import defaultdict

from app.services.knowledge.search import HybridSearchService, SearchResult
from app.services.mapping.state import MappingState


def _rrf_merge(results_list: list[list[SearchResult]], k: int = 60) -> list[SearchResult]:
    """Reciprocal Rank Fusion で複数クエリの検索結果をマージ。

    Args:
        results_list: 各クエリの SearchResult リスト（順序＝ランク）
        k: RRFの平滑化定数（デフォルト60が文献上の最適値）

    Returns:
        RRFスコア降順でソートされた SearchResult リスト（重複排除済み）
        各ノードのスコアは全クエリ中のbest_scoreを採用（既存閾値と互換）
    """
    rrf_scores: dict[str, float] = defaultdict(float)
    best_score: dict[str, float] = {}
    best_result: dict[str, SearchResult] = {}

    for results in results_list:
        for rank, r in enumerate(results):
            rrf_scores[r.node_id] += 1.0 / (k + rank + 1)
            current_best = best_score.get(r.node_id, -1.0)
            if r.score > current_best:
                best_score[r.node_id] = r.score
                best_result[r.node_id] = r

    # RRFスコア降順でソート、best_scoreでSearchResultを再構築
    sorted_ids = sorted(rrf_scores, key=lambda x: rrf_scores[x], reverse=True)
    merged = []
    for nid in sorted_ids:
        r = best_result[nid]
        merged.append(SearchResult(
            node_id=r.node_id,
            function_name=r.function_name,
            description=r.description,
            module=r.module,
            business_domain=r.business_domain,
            keywords=r.keywords,
            score=best_score[nid],         # 全クエリ中の最高スコアを採用
            vector_score=r.vector_score,
            keyword_score=r.keyword_score,
        ))
    return merged


def build_hybrid_search_node(search_service: HybridSearchService):
    """HybridSearch ノード関数を生成。"""

    async def hybrid_search_node(state: MappingState) -> dict:
        product_namespace = state.get("product_namespace", "SAP")

        # [UPGRADE-D] 複数クエリを並列実行（search_queries 優先、なければ search_query）
        queries = state.get("search_queries") or []
        if not queries:
            single = state.get("search_query", "")
            queries = [single] if single else []

        if not queries:
            return {
                "search_results": [],
                "search_score": 0.0,
            }

        # 並列検索（asyncio.gather）
        results_per_query: list[list[SearchResult]] = await asyncio.gather(*[
            search_service.search(
                query_text=q,
                product_namespace=product_namespace,
            )
            for q in queries
        ])

        # 複数クエリの結果をRRFでマージ
        if len(results_per_query) == 1:
            merged = results_per_query[0]  # 単一クエリはそのまま
        else:
            merged = _rrf_merge(results_per_query)

        # 上位10件に絞る（Judge に渡す最大件数）
        results = merged[:10]

        search_results = [
            {
                "node_id": r.node_id,
                "function_name": r.function_name,
                "description": r.description,
                "module": r.module,
                "business_domain": r.business_domain,
                "keywords": r.keywords,
                "score": r.score,
                "vector_score": r.vector_score,
                "keyword_score": r.keyword_score,
            }
            for r in results
        ]

        # top-3の加重平均スコア（top-1のみだとノイズマッチに弱いため）
        if results:
            top3 = results[:3]
            weights = [0.6, 0.3, 0.1][: len(top3)]
            search_score = sum(
                top3[i].score * weights[i] for i in range(len(top3))
            ) / sum(weights)
        else:
            search_score = 0.0

        return {
            "search_results": search_results,
            "search_score": search_score,
        }

    return hybrid_search_node
