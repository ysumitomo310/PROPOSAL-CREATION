"""FinalJudgment ノード（TASK-C07）

LLM(高性能) Structured Outputで判定レベル・3軸評価・rationale・matched_items出力。
confidence_score = 0.2 * search_score + 0.8 * llm_confidence（3軸加重平均）。temperature=0。
search_score=0.0 時は llm_confidence * 0.7（検索根拠なしペナルティ）。
閾値: High ≥ 0.65、Medium ≥ 0.40、Low < 0.40。

改善点:
- requirement_summary をプロンプトに追加（判定精度向上）
- judgment_level バリデーション（幻覚値を"アドオン開発"に補正）
- matched_items ID バリデーション（存在しないIDを除外、top-1で補填）
- 対象外判定時のconfidence上限（High 対象外はUX混乱を招くためMedium以下に制限）
- [UPGRADE] matched_items_text に module/domain/keywords を追加（判定精度向上）
- [UPGRADE] traversed_text に関連ノードの description を追加（業務コンテキスト強化）
- [UPGRADE] Few-Shot例を判定レベル定義に追加（境界ケース精度向上）
"""

import logging

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field

from app.core.llm_client import LLMClient
from app.services.mapping.state import MappingState

logger = logging.getLogger(__name__)

# SAP判定レベル定義
SAP_JUDGMENT_LEVELS = [
    "標準対応",
    "標準(業務変更含む)",
    "アドオン開発",
    "外部連携",
    "対象外",
]

_SYSTEM_PROMPT = """\
あなたはSAP S/4 HANA Cloud Public Edition導入プロジェクトの上級コンサルタントです。
機能要件とScope Itemのマッチング結果に基づき、Fit & Gap分析の最終判定を行ってください。
判定は客観的な根拠に基づき、Scope Item IDを必ず引用してください。
モジュール情報（SD/MM/FI等）と業務ドメインを考慮し、要件とScopeItemの機能的一致を正確に評価してください。"""

_USER_PROMPT = """\
以下の機能要件に対するFit & Gap判定を行ってください。

## 機能要件
- 機能名: {function_name}
- 要件概要: {requirement_summary}
- 要件詳細: {requirement_detail}
- 重要度: {importance}

## マッチしたScope Items（スコア順）
{matched_items_text}

## グラフ探索で見つかった関連ノード
{traversed_text}

## ModuleOverviewコンテキスト
{module_overview_context}

## 判定レベル定義と具体例

### 標準対応
定義: SAP S/4 HANA Cloud Public Editionの標準機能でそのまま対応可能。設定のみで実現。
例: 「販売注文の登録・変更・照会ができること」
→ SAP-1B4「受注から入金」が高スコアでマッチ。VA01/VA02/VA03の標準トランザクションで対応可能。
追加例: 「品目マスタの一括登録・変更管理機能」
→ SAPのMM品目マスタ（MM01/MM02/MM03）+ LSMW/LTMC標準移行ツールで対応。標準対応。
追加例: 「購買実績の集計・分析レポート出力」
→ SAPのMM標準レポート（ME2M等）で購買実績分析は対応可能。標準対応。

### 標準(業務変更含む)
定義: SAP標準機能で対応可能だが、SAP標準の業務プロセスに合わせた業務変更が必要。
例: 「購買申請に対して3段階の決裁承認を行ってから発注書を発行すること」
→ SAP-2EL「購買から支払」は対応可能だが、SAPのリリース戦略（承認ワークフロー）を使うために
   業務フローの変更（承認段階数・権限設計）が必要。
追加例: 「棚卸結果を入力し、差異を自動で会計計上すること」
→ SAP MM棚卸機能（MI01/MI04/MI07）は標準で存在。差異転記も標準。
  ただし棚卸頻度・対象範囲などSAP標準プロセスへの業務変更が必要。標準(業務変更含む)。
追加例: 「支給品の出庫・入庫・実績管理ができること」
→ SAP MM外注管理（ME21N + 543/544移動タイプ）で支給品管理は標準対応可能。
  業務フローの調整が必要なため標準(業務変更含む)。

### アドオン開発
定義: SAP標準機能では実現できず、カスタム開発（RICEF: レポート・インターフェース・帳票・拡張・フォーム）が必要。
例: 「得意先ごとに独自レイアウトのPDF請求書を自動生成してメール送付すること」
→ 請求処理自体（SAP-1G6）は標準だが、得意先別の独自PDF帳票生成と自動メール送付は
   標準機能にないため、カスタム帳票開発（スマートフォーム等）が必要。

### 外部連携
定義: SAP内部では対応できず、外部システムとのAPI/IDocインターフェース開発が必要。
例: 「既存の倉庫管理システム（WMS）とのリアルタイム在庫データ連携」
→ SAPのMM/WM機能は在庫管理可能だが、既存WMSとのリアルタイム双方向連携には
   IDoc/REST API連携の設計・開発が別途必要。

### 対象外
定義: SAP S/4 HANA Cloud Public Editionの製品スコープ外。ERP以外の専門ツールの領域。
例: 「従業員のスキルマップと案件最適アサイン機能」
→ 人事基本マスタはSAP対応だが、スキルマップ管理と最適アサインはSuccessFactors等の
   別製品の領域であり、S/4 HANA Cloud Public Editionの対象範囲外。

## 判定上の注意点（誤判定しやすい典型ケース）

### 銀行・支払連携は「外部連携」ではなく「標準対応」
以下はSAP S/4 HANA Cloud Public Editionの**標準FI機能**であり、「外部連携」と判定しないこと:
- 全銀データ形式（総合振込・給与振込データ作成）: F110（自動支払プログラム）+ 支払メディアの標準機能
- DME（Data Medium Exchange）: SAP標準の支払ファイル作成
- 振込データの銀行送信: 標準支払ラン後のファイル出力（外部API連携ではない）
- 口座振替・直接引き落とし: AR標準の自動引落機能
→ 銀行との実際のオンラインAPI接続（REST/SWIFT）が要件の場合のみ「外部連携」

### SAP内モジュール間連携は「標準対応」
SAP内部のモジュール間データ連携（SD-FI、MM-FI、PP-CO等）は**標準の統合機能**であり「外部連携」ではない:
- 受注→売上自動計上（SD-FI）、購買→買掛金計上（MM-FI）、在庫→会計転記（MM-FI）はすべて標準
→ SAP外部の他社システム（WMS・CRM・EDI等）との連携のみ「外部連携」

### マスタデータ管理は「標準対応」
顧客マスタ・仕入先マスタ・勘定科目マスタ・品目マスタの登録・変更・照会・管理は**標準対応**:
- マスタデータの一括登録（初期データ移行）はLSMW/LTMCなどSAP標準移行ツールで対応
- マスタデータの変更履歴管理は標準の変更ドキュメント機能で対応
- 「マスタ管理」「マスタ登録」「マスタ変更」等の機能は原則として標準対応と判定すること
→ 得意先固有の独自属性項目追加（Customer Enhancement）が必要な場合のみ「アドオン開発」

### 判定の粒度ルール（最重要）
判定は「業務プロセス単位」で行うこと。要件の中核となる業務プロセスがSAP標準に存在するかを最優先で評価する。
- 中核プロセスが標準で存在 → 細部（帳票レイアウト、特殊承認フロー等）の差異だけでは「アドオン開発」にしない
- 中核プロセスが標準で存在 + 細部に差異あり → 「標準(業務変更含む)」
- 中核プロセスが標準で存在 + 細部にカスタム開発が必要 → 「アドオン開発」は細部のみ。判定は「標準(業務変更含む)」寄りに
- 例: 「購買申請から発注まで」→ MM標準プロセス存在 = 最低でも「標準(業務変更含む)」。特殊な承認3段階は業務変更の範囲

誤判定パターン（避けるべき）:
- NG: 「棚卸の結果入力」→ 棚卸はMM標準(MI01/MI04)にあるのに「アドオン開発」と判定
- NG: 「支給品の実績入力」→ 外注管理はMM標準にあるのに「対象外」と判定
- NG: 「会計仕訳入力」→ FI標準(FB50/F-02)にあるのに「外部連携」と判定

### 対象外判定の厳格ルール
「対象外」は以下の条件をすべて満たす場合のみ使用すること:
1. 要件がERP（会計・販売・購買・生産・在庫・人事）の領域に含まれない
2. SAP S/4 HANA Cloud Public Editionのどのモジュールにも関連しない
3. 具体的に「これはXXX製品の領域である」と明言できる（例: SuccessFactors, Ariba, CRM専用ツール）

以下の場合は「対象外」にしてはならない:
- 検索結果のスコアが低い → 「対象外」ではなく「アドオン開発」または「標準(業務変更含む)」
- 業務ドメインが 販売/購買/財務/生産/倉庫/管理会計 のいずれか → SAP標準モジュールの範囲内
- マスタデータ管理に関する要件 → 標準対応
- モジュール間連携に関する要件 → 標準対応

## 出力指示（3軸評価）
以下をそれぞれ独立に0.0-1.0で評価してください。各軸は独立に評価し、安易に同じ値にしないこと。
モジュール（SD/MM/FI等）が要件の業務ドメインと一致しているかも考慮してください。

A. match_quality（機能一致度）
   0.90-1.0: 機能名・業務内容が完全一致。Scope Itemの説明が要件をそのまま記述している
   0.70-0.89: 主要機能が一致するが、要件の細部（帳票形式、承認フロー等）に差異あり
   0.45-0.69: 関連する業務領域だが直接的な機能一致ではない。類似機能の応用が必要
   0.20-0.44: 弱い関連。同じモジュール内だが異なる業務プロセス
   0.00-0.19: ほぼ無関係。対象外の可能性が高い

B. coverage（カバー率）
   0.90-1.0: 要件の全要素をScope Item群でカバー
   0.70-0.89: 主要要素はカバーするが補足的な要素（例: レポート出力、承認）は未対応
   0.45-0.69: 一部の主要要素のみカバー。残りはアドオンまたは業務変更が必要
   0.20-0.44: カバーできるのはごく一部
   0.00-0.19: ほぼカバーしていない

C. certainty（判定確からしさ）
   0.90-1.0: Scope Itemの説明文から直接判断可能。根拠が明確
   0.70-0.89: Scope ItemとModuleOverviewを総合して判断可能
   0.45-0.69: 間接的な情報からの推論を含む
   0.20-0.44: 推測に依存。根拠が薄い
   0.00-0.19: 根拠がほぼない。推測のみ

1. judgment_level: 5レベルから選択
2. match_quality: 上記基準A
3. coverage: 上記基準B
4. certainty: 上記基準C
5. scope_item_analysis: マッチしたScope Itemが要件のどの機能をカバーするかの詳細分析。
   各Scope Item（SAP-XXX）が要件のどの部分に対応するかを具体的に説明すること。
   モジュール名（SD/MM/FI等）と機能説明を必ず引用すること。
6. gap_analysis: 標準機能でカバーできない部分・業務変更が必要な理由・追加対応が必要な点を説明。
   ギャップが存在しない場合は「なし」と記載。
   **アドオン開発・外部連携の場合は必ず差分ベースで記述すること**:
   「最も近いScope Item（SAP-XXX: 機能名）は○○に対応するが、要件の△△は標準では対応不可」の形式で、
   どこまで標準でカバーでき、どこからがギャップかを明示する。単に「標準にない」とだけ書かないこと。
7. judgment_reason: 上記の分析を踏まえ、なぜこの判定レベルを選んだかを1〜2文で端的に説明。
8. matched_items: 引用したScope Item IDのリスト"""


class JudgmentOutput(BaseModel):
    """判定結果の構造化出力（3軸評価 + 根拠3分割）。"""

    judgment_level: str = Field(description="標準対応/標準(業務変更含む)/アドオン開発/外部連携/対象外")
    match_quality: float = Field(ge=0.0, le=1.0, description="検索結果と要件の機能的一致度")
    coverage: float = Field(ge=0.0, le=1.0, description="要件の主要機能に対するカバー率")
    certainty: float = Field(ge=0.0, le=1.0, description="判定根拠の明確さ")
    scope_item_analysis: str = Field(description="マッチしたScope Itemが要件のどの機能をカバーするかの詳細分析")
    gap_analysis: str = Field(description="標準機能でカバーできない部分・業務変更が必要な理由（ない場合は「なし」）")
    judgment_reason: str = Field(description="この判定レベルを選んだ理由（1〜2文）")
    matched_items: list[str] = Field(description="引用Scope Item IDリスト")


def build_final_judgment_node(llm_client: LLMClient):
    """FinalJudgment ノード関数を生成。"""

    async def final_judgment_node(state: MappingState) -> dict:
        search_results = state.get("search_results", [])
        traversed_nodes = state.get("traversed_nodes", [])

        # [UPGRADE-A] マッチしたScope Items テキスト — module/domain/keywords を追加
        if search_results:
            matched_items_text = "\n".join(
                f"- [{r.get('score', 0):.2f}] {r.get('node_id', '')} | "
                f"モジュール:{r.get('module', '')} | 業務:{r.get('business_domain', '')} | "
                f"{r.get('function_name', '')} | {r.get('description', '')} | "
                f"キーワード: {', '.join((r.get('keywords') or [])[:5])}"
                for r in search_results[:5]
            )
        else:
            matched_items_text = "（マッチなし）"

        # [UPGRADE-B] グラフ探索結果テキスト — 関連ノードの description を追加
        traversed_parts = []
        for tn in traversed_nodes:
            source = tn.get("source_id", "")
            for node in tn.get("related", []):
                if node.get("id"):
                    desc_snippet = (node.get("description") or "")[:100]
                    traversed_parts.append(
                        f"- {source} →[RELATED]→ {node['id']} | "
                        f"{node.get('function_name', '')} | {desc_snippet}"
                    )
        traversed_text = "\n".join(traversed_parts) if traversed_parts else "（関連ノードなし）"

        messages = [
            SystemMessage(content=_SYSTEM_PROMPT),
            HumanMessage(content=_USER_PROMPT.format(
                function_name=state.get("function_name", ""),
                requirement_summary=state.get("requirement_summary", ""),
                requirement_detail=state.get("requirement_detail", ""),
                importance=state.get("importance", ""),
                matched_items_text=matched_items_text,
                traversed_text=traversed_text,
                module_overview_context=state.get("module_overview_context", ""),
            )),
        ]

        result = await llm_client.call_heavy_structured(
            messages, JudgmentOutput, temperature=0
        )

        # judgment_level バリデーション（LLM幻覚値を保守的デフォルトに補正）
        if result.judgment_level not in SAP_JUDGMENT_LEVELS:
            logger.warning(
                "Unexpected judgment_level: '%s' → fallback to 'アドオン開発'",
                result.judgment_level,
            )
            result.judgment_level = "アドオン開発"

        # 3軸から llm_confidence を算出
        llm_confidence = (
            0.40 * result.match_quality
            + 0.35 * result.coverage
            + 0.25 * result.certainty
        )

        # confidence_score 複合算出（search:0.2 + llm:0.8）
        search_score = state.get("search_score", 0.0)
        if search_score == 0.0:
            # 検索結果なし: LLMの判定のみで評価（最大0.7に制限）
            confidence_score = llm_confidence * 0.7
        else:
            confidence_score = 0.2 * search_score + 0.8 * llm_confidence

        if confidence_score >= 0.65:
            confidence = "High"
        elif confidence_score >= 0.40:
            confidence = "Medium"
        else:
            confidence = "Low"

        # 対象外判定時はconfidenceをMedium以下に制限（"High 対象外"はUX上混乱を招く）
        if result.judgment_level == "対象外":
            if confidence == "High":
                confidence = "Medium"

        # matched_items IDバリデーション（存在しないIDを除外）
        valid_node_ids = {sr.get("node_id") for sr in search_results}
        validated_item_ids = [
            item_id for item_id in result.matched_items
            if item_id in valid_node_ids
        ]
        # 有効IDが0件かつ検索結果あり → top-1で補填
        if not validated_item_ids and search_results:
            validated_item_ids = [search_results[0].get("node_id", "")]
            logger.debug(
                "matched_items 全件無効 → top-1 で補填: %s", validated_item_ids
            )

        # matched_scope_items 構築
        matched_scope_items = []
        for item_id in validated_item_ids:
            for sr in search_results:
                if sr.get("node_id") == item_id:
                    matched_scope_items.append({
                        "id": item_id,
                        "function_name": sr.get("function_name", ""),
                        "description": sr.get("description", ""),
                        "search_score": sr.get("score", 0),
                    })
                    break
            else:
                matched_scope_items.append({"id": item_id})

        # ─── ドメインセーフティネット ───
        # SAP標準モジュール領域なのに「対象外」は誤判定の可能性が極めて高い
        _STANDARD_SAP_DOMAINS = {"販売", "購買", "財務", "生産", "倉庫", "管理会計", "人事"}
        analyzed_domain = state.get("analyzed_domain", "")

        if result.judgment_level == "対象外" and analyzed_domain in _STANDARD_SAP_DOMAINS:
            logger.warning(
                "ドメインセーフティネット発動: domain='%s' で対象外 → アドオン開発に補正",
                analyzed_domain,
            )
            result.judgment_level = "アドオン開発"
            result.judgment_reason = (
                f"[自動補正] 業務ドメイン「{analyzed_domain}」はSAP標準モジュール範囲内。"
                f"元の判定: 対象外 → アドオン開発に補正。{result.judgment_reason}"
            )

        return {
            "judgment_level": result.judgment_level,
            "confidence": confidence,
            "confidence_score": confidence_score,
            "scope_item_analysis": result.scope_item_analysis,
            "gap_analysis": result.gap_analysis,
            "judgment_reason": result.judgment_reason,
            "matched_scope_items": matched_scope_items,
        }

    return final_judgment_node
