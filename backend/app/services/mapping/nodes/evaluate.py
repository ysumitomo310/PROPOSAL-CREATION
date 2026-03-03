"""EvaluateResults ノード（TASK-C05）

ルールベースで検索結果の十分性を判定（LLMコールなし）。
スコア閾値と件数で即断し、灰色ゾーンのみtop-3平均で判定。

改善点: 旧実装はLLM（gpt-4o-mini）に判定を委ねていたが、
「スコア0.6以上か」「結果件数があるか」という判断はルールで実装できる。
LLM廃止により最大4回×要件数のコールを削減。
"""

from app.services.mapping.state import MappingState

# ─── 閾値定数 ───
_SCORE_SUFFICIENT = 0.70      # ≥ この値 → 即 sufficient
_SCORE_INSUFFICIENT = 0.40    # < この値 → 即 insufficient
_MIN_RESULTS_FOR_GRAY = 3     # 灰色ゾーン(0.40-0.70)で sufficient とみなす最低件数
_GRAY_TOP3_AVG_THRESHOLD = 0.50  # 灰色ゾーンでのtop-3平均閾値


def build_evaluate_results_node():
    """EvaluateResults ノード関数を生成（依存なし）。"""

    async def evaluate_results_node(state: MappingState) -> dict:
        search_results = state.get("search_results", [])
        search_score = state.get("search_score", 0.0)
        search_query = state.get("search_query", "")
        retry_count = state.get("retry_count", 0)
        search_history = list(state.get("search_history", []))

        result_count = len(search_results)

        # ─── ルールベース判定 ───
        if result_count == 0:
            is_sufficient = False
            reasoning = "検索結果0件のため不十分"

        elif search_score >= _SCORE_SUFFICIENT:
            is_sufficient = True
            reasoning = (
                f"上位スコア {search_score:.2f} ≥ 閾値 {_SCORE_SUFFICIENT}"
            )

        elif search_score < _SCORE_INSUFFICIENT:
            is_sufficient = False
            reasoning = (
                f"上位スコア {search_score:.2f} < 閾値 {_SCORE_INSUFFICIENT}"
            )

        else:
            # 灰色ゾーン（0.40 ≤ score < 0.70）: top-3平均と件数で判定
            top3 = search_results[:3]
            top3_avg = sum(r.get("score", 0) for r in top3) / len(top3)
            is_sufficient = (
                result_count >= _MIN_RESULTS_FOR_GRAY
                and top3_avg >= _GRAY_TOP3_AVG_THRESHOLD
            )
            reasoning = (
                f"灰色ゾーン: top={search_score:.2f}, "
                f"top3avg={top3_avg:.2f}, count={result_count} "
                f"→ {'sufficient' if is_sufficient else 'insufficient'}"
            )

        # [UPGRADE-D] search_queries が存在する場合は全クエリを履歴に記録
        search_queries = state.get("search_queries") or []
        search_history.append({
            "query": search_query,
            "queries": search_queries if search_queries else [search_query],
            "top_score": search_score,
            "result_count": result_count,
            "reasoning": reasoning,
            "sufficient": is_sufficient,
        })

        return {
            "is_sufficient": is_sufficient,
            "evaluation_reasoning": reasoning,
            "retry_count": retry_count + 1,
            "search_history": search_history,
        }

    return evaluate_results_node
