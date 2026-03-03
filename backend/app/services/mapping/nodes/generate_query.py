"""GenerateQuery ノード（TASK-C03）

LLM(軽量)で分析結果+要件テキストからHybrid Search用クエリを生成。
リトライ時はsearch_historyを参照し異なるクエリを生成。

[UPGRADE-D] 複数クエリ（RAG-Fusion）対応:
- 1回のLLMコールで3つの異なる視点（機能/業務プロセス/ERPモジュール）のクエリを生成
- 各クエリを並列検索してRRFマージすることで検索リコールを大幅改善
"""

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field

from app.core.llm_client import LLMClient
from app.services.mapping.state import MappingState

_SYSTEM_PROMPT = "あなたはNeo4jナレッジグラフの検索クエリ生成AIです。日本語の業務キーワードをスペース区切りで並べた検索クエリを生成してください。Boolean演算子（AND/OR/NOT）は絶対に使用しないでください。"

_USER_PROMPT_INITIAL = """\
以下の機能要件に最もマッチするSAP Scope Itemを検索するため、3つの異なる視点のクエリを生成してください。

## 機能名
{function_name}

## 要件概要
{requirement_summary}

## 要件詳細
{requirement_detail}

## 分析結果
- キーワード: {keywords}
- 業務ドメイン: {domain}
- 意図: {intent}

## クエリ生成ルール
- 各クエリは日本語キーワードを3-5個、スペース区切りで連結
- Boolean演算子（AND, OR, NOT）は使用禁止
- 括弧、引用符、特殊記号は使用禁止
- 3つのクエリは互いに異なる視点で生成すること

## 生成する3クエリの視点
query_function: 機能・処理内容に注目（例: 「受注登録 在庫確認 引当」）
query_process:  業務プロセス・フローに注目（例: 「販売 出荷 請求 入金」）
query_module:   SAPモジュール・技術用語に注目（例: 「SD 販売管理 オーダー管理」）

各クエリは10-50文字のスペース区切りキーワード列で出力してください。"""

_USER_PROMPT_RETRY = """\
前回の検索では十分な結果が得られませんでした。別のアプローチで3つのクエリを再生成してください。

## 機能名
{function_name}

## 要件概要
{requirement_summary}

## 要件詳細
{requirement_detail}

## 分析結果
- キーワード: {keywords}
- 業務ドメイン: {domain}

## 前回の検索履歴
{search_history}

## 再検索戦略（リトライ回数に応じて）
- 1回目リトライ: 同義語・別の表現（例: 「受注」→「売上」「販売注文」）を活用
- 2回目リトライ: より一般的・広範なキーワード（1-2語に絞る）

## クエリ生成ルール
- スペース区切りのキーワード列のみ（Boolean演算子禁止）
- 括弧、引用符、特殊記号は使用禁止
- 前回と異なる表現を必ず使用すること
- 3つのクエリは互いに異なる視点で生成すること

query_function: 機能・処理内容に注目
query_process:  業務プロセス・フローに注目
query_module:   SAPモジュール・技術用語に注目

各クエリは10-40文字のスペース区切りキーワード列で出力してください。"""


class MultiQueryOutput(BaseModel):
    """複数検索クエリの構造化出力（RAG-Fusion用）。"""

    query_function: str = Field(description="機能・処理内容視点のクエリ（3-5語、スペース区切り）")
    query_process: str = Field(description="業務プロセス・フロー視点のクエリ（3-5語、スペース区切り）")
    query_module: str = Field(description="SAPモジュール・技術用語視点のクエリ（3-5語、スペース区切り）")


def build_generate_query_node(llm_client: LLMClient):
    """GenerateQuery ノード関数を生成。"""

    async def generate_query_node(state: MappingState) -> dict:
        retry_count = state.get("retry_count", 0)
        search_history = state.get("search_history", [])

        keywords_str = ", ".join(state.get("analyzed_keywords", []))

        if retry_count == 0 or not search_history:
            prompt = _USER_PROMPT_INITIAL.format(
                function_name=state.get("function_name", ""),
                requirement_summary=state.get("requirement_summary", ""),
                requirement_detail=state.get("requirement_detail", ""),
                keywords=keywords_str,
                domain=state.get("analyzed_domain", ""),
                intent=state.get("analyzed_intent", ""),
            )
        else:
            history_text = "\n".join(
                f"- クエリ群: {h.get('queries', [h.get('query', '')])} → 結果: {h.get('reasoning', '不十分')}"
                for h in search_history
            )
            prompt = _USER_PROMPT_RETRY.format(
                function_name=state.get("function_name", ""),
                requirement_summary=state.get("requirement_summary", ""),
                requirement_detail=state.get("requirement_detail", ""),
                keywords=keywords_str,
                domain=state.get("analyzed_domain", ""),
                search_history=history_text,
            )

        messages = [
            SystemMessage(content=_SYSTEM_PROMPT),
            HumanMessage(content=prompt),
        ]

        result = await llm_client.call_light_structured(messages, MultiQueryOutput)

        # 3クエリをリストとして保持、代表クエリは最初のもの（履歴・ログ用）
        queries = [result.query_function, result.query_process, result.query_module]
        # 空文字列を除外
        queries = [q.strip() for q in queries if q.strip()]
        if not queries:
            queries = [state.get("function_name", "")]

        return {
            "search_queries": queries,
            "search_query": queries[0],  # 代表クエリ（履歴・EvaluateResults用）
        }

    return generate_query_node
