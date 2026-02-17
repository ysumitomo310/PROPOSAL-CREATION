# Requirements: Phase 1 - 機能要件マッピングエンジン

> **ステータス**: Draft
> **対象Phase**: Phase 1
> **参照**: spec/overview.md Section 3.1, 4.x, 6.x / qa-records/round1〜3

## プロジェクト概要

Phase 1では、ERP製品ナレッジ（SAP Scope Item + モジュール紹介資料）をGraph RAGとして構築し、顧客RFPの機能要件一覧に対してAgentic RAGで自動マッピングを行うエンジンを構築・検証する。

**PoC目標**: 過去の実RFP 1案件分（SAP）をフル処理し、人間の判定結果との精度比較で有効性を実証する。

**スコープ外（Phase 2以降）**:
- RFPドキュメント（PDF）の取込・分析（Phase 2）
- 提案骨子・構成生成（Phase 2）
- Gamma APIスライド生成（Phase 3）
- 顧客フォーマットExcel書き戻し（Phase 3）
- 見積書作成（スコープ外）

---

## ナレッジ設計決定事項

サンプルドキュメント分析に基づき、以下の設計方針を確定した。

### ナレッジソースの種類

| ソース | 形式 | 内容 | ファイル構成 |
|--------|------|------|-------------|
| **Scope Item BPD** | docx × 2 + xlsx × 1 | テスト手順書（Purpose, Prerequisites, Business Conditions, Procedure Tables） | 3ファイル1セット × 数百セット |
| **モジュール紹介資料** | PDF（Discovery WS用スライド） | モジュール機能概要、プロセスフロー、マスタデータ解説、画面キャプチャ | モジュール別PDF（39〜122ページ） |

### 確定方針

| 項目 | 決定 | 根拠 |
|------|------|------|
| ノード粒度 | **1 Scope Item = 1ノード** | BPDのScope Item IDが一意キー。モジュール紹介資料も同一Scope Itemに紐付く |
| 言語戦略 | **JA版を主、EN版を補完** | RFPは日本語。JA BPDのPurpose/Procedureを主テキスト、EN版で略語・正式名称を補完 |
| description生成 | **LLMによるPurpose + Activity要約 + モジュール紹介資料エンリッチ** | BPDのPurpose + Procedure Tableから機能要約をLLM生成し、該当するモジュール紹介資料の機能説明で補強 |
| モジュール分類 | **マスターテーブル管理** | Scope Item IDプレフィクスとモジュールの対応表を管理。必要に応じ更新可能 |
| リレーション抽出 | **Business Conditionsから自動抽出** | BPDのPrerequisites/Business Conditionsに記載された他Scope Item IDを正規表現で自動抽出 |

### RFP機能要件一覧Excelのフォーマット

顧客ごとにExcelフォーマットは異なるが、以下の共通パターンが確認された（5案件分のサンプル分析）。

**共通構造:**
```
[階層分類（2〜4レベル）] + [要件記述] + [重要度] + [ベンダー回答欄]
```

| 要素 | バリエーション例 |
|------|----------------|
| 階層分類 | Lv.1〜Lv.4 / 大分類・中分類・小分類 / 部門・プロセス・DF |
| 要件記述 | 機能内容 / システム要件 / 業務要件+機能要件 / 課題内容 |
| 重要度 | 1〜3 / 必須・OP / MUST・WANT / なし |
| 回答形式 | 標準・アドオン・カスタマイズ・代替案 / A〜D / 自由記述 |

**設計方針:**
- Excelパーサーはカラムマッピング設定で柔軟に対応する（案件作成時にUIでマッピング指定、またはプリセット選択）
- 最低限の正規化として `業務分類` / `業務名` / `機能名` / `要件概要` / `要件詳細` / `重要度` にマッピング
- ベンダー回答欄は初回は空として取り込み、マッピング結果で自動充填

### 判定レベル定義

| レベル | 定義 | SAP | GRANDIT |
|--------|------|-----|---------|
| **標準対応** | パッケージ標準機能でそのまま実現可能 | Scope Itemに含まれる機能で対応 | 標準モジュールで対応 |
| **標準（業務変更含む）** | 標準機能＋設定変更または業務運用変更で対応可能 | Scope Itemの設定パラメータ変更、業務フロー調整 | 標準機能の設定変更、業務フロー調整 |
| **アドオン開発** | 標準機能外のプログラム追加が必要 | Public Editionはコア改修不可のため外付け開発（BTP等） | - |
| **カスタマイズ** | 標準機能にプログラム変更を行い実現 | -（SAP Public Editionでは不可） | コアロジックのカスタマイズ開発が可能 |
| **外部連携** | 外部システムとの連携で実現 | API/IF連携 | API/IF連携 |
| **対象外** | 当該ERPのスコープ外 | - | - |

**注記:**
- SAP Public Editionでは「アドオン開発」、GRANDITでは「カスタマイズ」が使用される。製品によって利用可能な判定レベルが異なる
- 将来的にケースが増えた際にレベルを追加・調整可能な拡張設計とする
- Phase 1 PoCではSAP対象のため、判定レベルは「標準対応 / 標準（業務変更含む）/ アドオン開発 / 外部連携 / 対象外」の5段階

### モジュール紹介資料の取扱い

Discovery WS用PDF（SD在庫販売、SD受注生産販売、プロフェッショナルサービス、購買ソリューション等）は以下の特徴を持つ：

- **Scope Item IDが明示的に参照されている**（例: 「BD9 在庫からの販売」「J11 得意先プロジェクト管理」）
- **BPDにはない豊富な機能説明**（プロセスフロー、マスタデータ概念、業務連携、画面例）
- **モジュール横断的なコンテンツ**（アーキテクチャ概要、他モジュール連携）

**処理方針**: モジュール紹介資料を `:ModuleOverview` ノードとしてNeo4jに投入し、`-[:COVERS]->` リレーションで該当する `:ScopeItem` ノードにリンクする。マッピングエンジンのグラフ探索時にModuleOverviewの文脈も活用する。

---

## A. ナレッジベース構築

| ID | EARS記述 | 優先度 | ステータス |
|----|----------|--------|-----------|
| REQ-MAP-001 | **WHEN** SAP Scope Item BPDドキュメント（JA版docx + EN版docx + 翻訳パラメータxlsx の3ファイルセット）が提供されたとき、**THE SYSTEM SHALL** JA版を主としてドキュメントを解析し、overview.md Section 4.3で定義されたスキーマに従い構造化 `:ScopeItem` ナレッジノードを生成する。description フィールドはLLMによりPurpose + Procedure Tableの主要Activityから要約生成する | Must | Draft |
| REQ-MAP-001a | **WHEN** モジュール紹介資料（Discovery WS用PDF）が提供されたとき、**THE SYSTEM SHALL** PDFからテキストを抽出し、モジュール別の `:ModuleOverview` ナレッジノードを生成する。PDFに含まれるScope Item ID参照を検出し、該当する `:ScopeItem` ノードへの `-[:COVERS]->` リレーションを作成する | Must | Draft |
| REQ-MAP-002 | **THE SYSTEM SHALL** ナレッジノード（`:ScopeItem` および `:ModuleOverview`）をNeo4jにグラフ構造として格納する。`:ScopeItem` 間には prerequisite/related/follow_on リレーション（BPD Business Conditionsから自動抽出）を、`:ModuleOverview` から `:ScopeItem` へは COVERS リレーションを設定し、各ノードにベクトルEmbedding（text-embedding-3-large, 3,072次元）を付与する | Must | Draft |
| REQ-MAP-003 | **THE SYSTEM SHALL** Neo4j上でHybrid Search（ベクトル類似度 + キーワード検索）を単一のCypherクエリで実行可能な検索サービスを提供する。検索対象は `:ScopeItem` ノードを主とし、`:ModuleOverview` ノードはグラフ探索で補完する | Must | Draft |
| REQ-MAP-004 | **WHEN** `:ScopeItem` ノードが作成されるとき、**THE SYSTEM SHALL** function_name + description + keywordsの結合テキストからEmbeddingを生成する。**WHEN** `:ModuleOverview` ノードが作成されるとき、module_name + summaryの結合テキストからEmbeddingを生成する。いずれもNeo4jベクトルインデックスに格納する | Must | Draft |
| REQ-MAP-005 | **THE SYSTEM SHALL** 製品別スキーマ（SAP名前空間）でナレッジを管理し、将来的にGRANDIT名前空間の追加が可能な設計とする | Should | Draft |
| REQ-MAP-006 | **THE SYSTEM SHALL** 200〜400件のScopeItemノード + 10〜30件のModuleOverviewノードに対し、1秒以内の検索レスポンスを実現する | Must | Draft |
| REQ-MAP-007 | **THE SYSTEM SHALL** Scope Item IDとモジュール分類の対応をマスターテーブルとして管理する。マスターテーブルは管理者が更新可能とする | Must | Draft |

---

## B. マッピングエンジンコア

| ID | EARS記述 | 優先度 | ステータス |
|----|----------|--------|-----------|
| REQ-MAP-010 | **WHEN** 機能要件が入力されたとき、**THE SYSTEM SHALL** LangGraphベースのAgentic RAGパイプラインを実行する。パイプラインは「要件分析→検索クエリ生成→Hybrid Search→結果評価→（必要に応じ再検索）→グラフ探索→最終判定→提案文生成」のステートマシンで構成される | Must | Draft |
| REQ-MAP-011 | **THE SYSTEM SHALL** 各要件に対し製品別の判定レベルを出力する。SAP: 標準対応 / 標準（業務変更含む）/ アドオン開発 / 外部連携 / 対象外 の5段階。GRANDIT（将来）: カスタマイズレベルを追加。判定レベルは拡張可能な設計とする | Must | Draft |
| REQ-MAP-012 | **THE SYSTEM SHALL** 検索スコアとLLM自己評価の複合により、確信度スコア（High / Medium / Low）を算出する | Must | Draft |
| REQ-MAP-013 | **THE SYSTEM SHALL** 各マッピング結果に対し、提案書にそのまま転記可能なレベルの提案文（proposal_text）を生成する | Must | Draft |
| REQ-MAP-014 | **THE SYSTEM SHALL** 各マッピング結果に対し、根拠（rationale）として具体的なScope Item IDと関連する機能内容を引用する | Must | Draft |
| REQ-MAP-015 | **THE SYSTEM SHALL** LLMを段階的に使い分ける。検索クエリ生成・関連性判定には軽量モデル（Claude Haiku / GPT-4o-mini）を、最終判定・提案文生成には高性能モデル（Claude Sonnet / GPT-4o）を使用する | Must | Draft |
| REQ-MAP-016 | **WHEN** 初回検索の結果が不十分と評価されたとき、**THE SYSTEM SHALL** クエリを再構成し再検索する（最大3回まで） | Must | Draft |
| REQ-MAP-017 | **WHEN** マッチするScope Itemが見つかったとき、**THE SYSTEM SHALL** グラフリレーション（prerequisite / related / follow_on / COVERS）を探索し、関連ScopeItemノードおよびModuleOverviewノードのコンテキストを最終判定LLMに提供する | Must | Draft |
| REQ-MAP-018 | **THE SYSTEM SHALL** 複数の機能要件（通常100〜300件/案件）をバッチ処理し、個別に完了した結果から順次返却する | Must | Draft |

---

## C. APIレイヤー

| ID | EARS記述 | 優先度 | ステータス |
|----|----------|--------|-----------|
| REQ-MAP-020 | **THE SYSTEM SHALL** 案件作成エンドポイント（POST）を提供し、機能要件一覧のExcelファイルをアップロード・パースして案件と要件レコードを作成する。Excelフォーマットは顧客ごとに異なるため、カラムマッピング設定（階層分類・要件記述・重要度の列指定）を受け付け、正規化して取り込む | Must | Draft |
| REQ-MAP-021 | **THE SYSTEM SHALL** マッピング開始エンドポイント（POST）を提供し、非同期でバッチマッピング処理を開始する（202 Accepted返却） | Must | Draft |
| REQ-MAP-022 | **THE SYSTEM SHALL** SSE（Server-Sent Events）エンドポイントを提供し、マッピング完了した要件の結果をリアルタイムにストリーミング配信する | Must | Draft |
| REQ-MAP-023 | **THE SYSTEM SHALL** マッピング結果取得エンドポイント（GET）を提供し、判定レベル・確信度・重要度によるフィルタリングをサポートする | Must | Draft |
| REQ-MAP-024 | **THE SYSTEM SHALL** マッピング結果をPostgreSQLに永続化する（案件→機能要件→マッピング結果のリレーション） | Must | Draft |
| REQ-MAP-025 | **THE SYSTEM SHALL** 全LLM呼び出しとLangGraphステップ実行にLangSmithトレーシングを組み込み、各マッピング結果からトレースIDで実行詳細を参照可能とする | Should | Draft |

---

## D. PoC用レビューUI

| ID | EARS記述 | 優先度 | ステータス |
|----|----------|--------|-----------|
| REQ-MAP-030 | **THE SYSTEM SHALL** 機能要件一覧のExcelファイルをアップロードし案件を作成するWebページを提供する | Must | Draft |
| REQ-MAP-031 | **THE SYSTEM SHALL** マッピング結果を一覧テーブル（要件名 / 判定 / 確信度 / 重要度 / ステータス）で表示する | Must | Draft |
| REQ-MAP-032 | **WHEN** テーブルの行が選択されたとき、**THE SYSTEM SHALL** サイドパネルに詳細情報（判定・根拠・proposal_text・関連ノード・LangSmithトレースリンク）を表示する | Must | Draft |
| REQ-MAP-033 | **WHEN** マッピング処理が実行中のとき、**THE SYSTEM SHALL** 全体進捗バー（N/M件処理中）を表示し、完了した要件を順次テーブルに追加する | Must | Draft |
| REQ-MAP-034 | **THE SYSTEM SHALL** フィルタプリセット（「要レビュー: Must×Low」「承認済み」「全件」）を提供する | Should | Draft |

---

## E. 非機能要件

| ID | 記述 | カテゴリ | 優先度 |
|----|------|---------|--------|
| NFR-MAP-001 | 1機能要件あたりの処理時間が平均30秒以内であること（全LLM呼び出し含む） | 性能 | Must |
| NFR-MAP-002 | 200機能要件の一括処理にかかるLLM APIコストが$50以内であること | コスト | Must |
| NFR-MAP-003 | 過去実案件の正解データとの判定一致率が70%以上であること（判定レベルでの一致） | 精度 | Must |
| NFR-MAP-004 | 全マッピング結果に対し、根拠となるScope Item IDおよびLangSmithトレースIDが紐付くこと | トレーサビリティ | Must |
| NFR-MAP-005 | 同一入力要件・同一ナレッジベースに対して一貫した結果を返すこと（判定LLMはtemperature=0） | 再現性 | Should |

---

## 受け入れ基準（BDD形式）

```gherkin
Feature: 機能要件マッピング
  As a 提案チームメンバー
  I want RFPの機能要件をSAP Scope Itemに自動マッピングしたい
  So that Fit&Gap分析を高速かつ高品質に行える

  Scenario: 単一要件のマッピング
    Given SAP Scope ItemがNeo4jに投入済みである
    And 機能要件「受注登録機能」が入力される
    When マッピングエンジンが要件を処理する
    Then 判定レベル（標準対応/標準（業務変更含む）/アドオン開発/外部連携/対象外）のいずれかが返却される
    And 確信度（High/Medium/Low）が返却される
    And proposal_text（提案書転記可能レベルの文章）が返却される
    And 根拠として具体的なScope Item IDが引用される

  Scenario: バッチマッピング + SSEストリーミング
    Given 200件の機能要件がExcelから読み込まれている
    When バッチマッピングが開始される
    Then SSEエンドポイントから完了した要件の結果が順次ストリーミングされる
    And UIの進捗バーが「N/200件処理中」と表示される
    And ユーザーは処理中でも完了分のレビューを開始できる

  Scenario: PoC精度検証
    Given 過去実案件の正解マッピングデータ（人間の判定結果）がある
    And 同案件の機能要件に対してマッピングエンジンが処理を完了している
    When 精度評価スクリプトが実行される
    Then 判定レベルの一致率が算出される
    And 確信度レベル別の精度内訳が出力される
    And 不一致件の詳細リスト（自動判定 vs 人間判定）が出力される
```

---

## トレーサビリティ

| 要件ID | 設計 | 実装 | テスト | ステータス |
|--------|------|------|--------|-----------|
| REQ-MAP-001 | COMP-PARSER-BPD | - | - | 未着手 |
| REQ-MAP-001a | COMP-PARSER-PDF | - | - | 未着手 |
| REQ-MAP-002 | COMP-LOADER | - | - | 未着手 |
| REQ-MAP-003 | COMP-SEARCH | - | - | 未着手 |
| REQ-MAP-004 | COMP-LOADER | - | - | 未着手 |
| REQ-MAP-005 | COMP-LOADER | - | - | 未着手 |
| REQ-MAP-006 | COMP-SEARCH | - | - | 未着手 |
| REQ-MAP-007 | COMP-MASTER | - | - | 未着手 |
| REQ-MAP-010 | COMP-AGENT | - | - | 未着手 |
| REQ-MAP-011 | COMP-JUDGE | - | - | 未着手 |
| REQ-MAP-012 | COMP-JUDGE | - | - | 未着手 |
| REQ-MAP-013 | COMP-GENERATE | - | - | 未着手 |
| REQ-MAP-014 | COMP-JUDGE | - | - | 未着手 |
| REQ-MAP-015 | COMP-AGENT | - | - | 未着手 |
| REQ-MAP-016 | COMP-EVALUATE | - | - | 未着手 |
| REQ-MAP-017 | COMP-TRAVERSE | - | - | 未着手 |
| REQ-MAP-018 | COMP-AGENT | - | - | 未着手 |
| REQ-MAP-020 | COMP-API-CASE | - | - | 未着手 |
| REQ-MAP-021 | COMP-API-MAP | - | - | 未着手 |
| REQ-MAP-022 | COMP-API-MAP | - | - | 未着手 |
| REQ-MAP-023 | COMP-API-MAP | - | - | 未着手 |
| REQ-MAP-024 | COMP-API-CASE | - | - | 未着手 |
| REQ-MAP-025 | COMP-TRACING | - | - | 未着手 |
| REQ-MAP-030 | COMP-UI-UPLOAD | - | - | 未着手 |
| REQ-MAP-031 | COMP-UI-TABLE | - | - | 未着手 |
| REQ-MAP-032 | COMP-UI-DETAIL | - | - | 未着手 |
| REQ-MAP-033 | COMP-UI-SSE | - | - | 未着手 |
| REQ-MAP-034 | COMP-UI-FILTER | - | - | 未着手 |
| NFR-MAP-001 | - | - | PERF-001 | 未着手 |
| NFR-MAP-002 | - | - | COST-001 | 未着手 |
| NFR-MAP-003 | - | - | ACC-001 | 未着手 |
| NFR-MAP-004 | - | - | TRACE-001 | 未着手 |
| NFR-MAP-005 | - | - | REPRO-001 | 未着手 |
