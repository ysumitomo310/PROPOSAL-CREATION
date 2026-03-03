"""GenerateProposalText ノード（TASK-C08）

LLM(高性能)で提案書転記可能テキスト生成。200-400文字。

改善点:
- 対象外判定時は定型文で即リターン（重量LLMコール節約）
- description の切り詰めを 80 → 150 文字に拡張（根拠の詳細性向上）
"""

from datetime import datetime, timezone

from langchain_core.messages import HumanMessage, SystemMessage

from app.core.llm_client import LLMClient
from app.services.mapping.state import MappingState

_SYSTEM_PROMPT = """\
あなたはSAP S/4 HANA導入プロジェクトの提案書ライターです。
提案書の「貴社システム要求に対するご回答」セクションに直接転記可能な文体で記述してください。
敬語・ビジネス文体で統一し、具体的なSAP標準機能名・モジュール名を含めてください。"""

_USER_PROMPT = """\
以下の判定結果に基づき、提案書テキストを生成してください。

## 機能要件
- 機能名: {function_name}
- 要件詳細: {requirement_detail}
- 重要度: {importance}

## 判定結果
- 判定レベル: {judgment_level}
- 確信度: {confidence} ({confidence_score:.2f})
- ScopeItem適合根拠: {scope_item_analysis}
- ギャップ・課題: {gap_analysis}
- 判定結論: {judgment_reason}

## マッチしたScope Items
{matched_items_text}

## ModuleOverviewコンテキスト
{module_overview_context}

## 生成指示
- 判定レベルに応じた対応方針を明記:
  * 標準対応 → 「標準機能で対応いたします」
  * 標準(業務変更含む) → 「プロセス変更により標準機能で対応いたします」
  * アドオン開発 → 「カスタム開発が必要です」
  * 外部連携 → 「外部システムとの連携で対応いたします」
- Scope Item IDと機能名を引用（例: "SAP-1B4 受注から入金"）
- 200-400文字で簡潔に"""

# 対象外判定時の定型文（LLMコールなし）
_TAISHOGAI_PROPOSAL = (
    "当製品（SAP S/4 HANA Public Edition）の対象範囲外となります。"
    "別途対応方針についてご相談ください。"
)


def build_generate_proposal_node(llm_client: LLMClient):
    """GenerateProposalText ノード関数を生成。"""

    async def generate_proposal_node(state: MappingState) -> dict:
        # 対象外は定型文で即リターン（重量LLMコール節約）
        if state.get("judgment_level") == "対象外":
            return {
                "proposal_text": _TAISHOGAI_PROPOSAL,
                "completed_at": datetime.now(timezone.utc).isoformat(),
            }

        matched_scope_items = state.get("matched_scope_items", [])

        if matched_scope_items:
            matched_items_text = "\n".join(
                # 80 → 150文字に拡張（提案根拠の詳細性向上）
                f"- {m.get('id', '')} | {m.get('function_name', '')} | {m.get('description', '')[:150]}"
                for m in matched_scope_items
            )
        else:
            matched_items_text = "（なし）"

        messages = [
            SystemMessage(content=_SYSTEM_PROMPT),
            HumanMessage(content=_USER_PROMPT.format(
                function_name=state.get("function_name", ""),
                requirement_detail=state.get("requirement_detail", ""),
                importance=state.get("importance", ""),
                judgment_level=state.get("judgment_level", ""),
                confidence=state.get("confidence", ""),
                confidence_score=state.get("confidence_score", 0.0),
                scope_item_analysis=state.get("scope_item_analysis", ""),
                gap_analysis=state.get("gap_analysis", ""),
                judgment_reason=state.get("judgment_reason", ""),
                matched_items_text=matched_items_text,
                module_overview_context=state.get("module_overview_context", ""),
            )),
        ]

        result = await llm_client.call_heavy(messages, temperature=0.3)

        return {
            "proposal_text": result.content.strip(),
            "completed_at": datetime.now(timezone.utc).isoformat(),
        }

    return generate_proposal_node
