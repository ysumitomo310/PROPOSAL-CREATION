"""AnalyzeRequirement ノード（TASK-C02）

LLM(軽量)で機能要件テキストからキーワード・業務ドメイン・要件意図を分析。
"""

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel

from app.core.llm_client import LLMClient
from app.services.mapping.state import MappingState

_SYSTEM_PROMPT = (
    "あなたはERP導入コンサルタントです。機能要件を分析し、検索に最適なキーワードと業務ドメインを特定してください。"
    "機能名が「1.購買」「4.販売」のようなカテゴリ番号コードの場合は、要件概要・要件詳細を優先して分析してください。"
)

_USER_PROMPT = """\
以下の機能要件を分析してください。

## 機能名
{function_name}

## 要件概要
{requirement_summary}

## 要件詳細
{requirement_detail}

## 業務カテゴリ
{business_category}

以下の形式でJSON出力してください:
- keywords: 検索に使用する主要キーワード（5-10個、日本語）
- domain: 業務ドメイン分類（販売/購買/財務/生産/倉庫/人事/管理会計/プロジェクト/その他 のいずれか）
- intent: この要件が求めている機能の意図を1-2文で説明"""


class AnalysisOutput(BaseModel):
    """要件分析の構造化出力。"""

    keywords: list[str]
    domain: str
    intent: str


def build_analyze_node(llm_client: LLMClient):
    """AnalyzeRequirement ノード関数を生成。"""

    async def analyze_requirement_node(state: MappingState) -> dict:
        messages = [
            SystemMessage(content=_SYSTEM_PROMPT),
            HumanMessage(content=_USER_PROMPT.format(
                function_name=state.get("function_name", ""),
                requirement_summary=state.get("requirement_summary", ""),
                requirement_detail=state.get("requirement_detail", ""),
                business_category=state.get("business_category", ""),
            )),
        ]

        result = await llm_client.call_light_structured(messages, AnalysisOutput)

        return {
            "analyzed_keywords": result.keywords,
            "analyzed_domain": result.domain,
            "analyzed_intent": result.intent,
        }

    return analyze_requirement_node
