# Tech Stack - ProposalCreation（Round 7 確定）

> **ステータス**: 確定（2026-02-17 Round 7 Q&Aで全項目決定）

## 技術スタック総覧

| レイヤー | 技術 | 選定理由 |
|---------|------|---------|
| **バックエンド** | FastAPI（Python 3.12+） | LangGraph/openpyxl/pdfplumberとPython統一。async/awaitネイティブ。Pydanticバリデーション |
| **フロントエンド** | Next.js 15（React / App Router） | 生成AI開発との相性が最良。ファイルベースルーティング。shadcn/ui等UIエコシステムが最大 |
| **案件管理DB** | PostgreSQL 16 + SQLAlchemy | リレーショナル構造（案件→ドキュメント→マッピング→提案書）。JSON/JSONB型で半構造化データ対応 |
| **ナレッジDB** | Neo4j 5.x（ベクトルインデックス内蔵） | ERP製品ナレッジ専用。グラフ探索+ベクトル検索をCypherワンクエリで実行 |
| **Embedding** | OpenAI text-embedding-3-large（3,072次元） | 日本語+英語+ERP略語の多言語対応。差し替え可能設計 |
| **Agentic RAG** | LangGraph（LangChain系） | ステートマシンベースのエージェント制御。デバッグ・拡張が容易 |
| **LLM（軽量）** | Claude Haiku / GPT-4o-mini | 検索クエリ生成、関連性判定 |
| **LLM（高性能）** | Claude Sonnet / GPT-4o | 最終マッピング判定、提案文生成 |
| **スライド生成** | Gamma API v1.0 | JSON/Markdown → PPTX/PDF（Phase 3） |
| **Excel処理** | openpyxl | 読込・書き戻し（書式保持） |
| **PDF解析** | pdfplumber | テキスト+表抽出 |
| **インフラ（初期）** | Docker Compose | 全コンポーネントを1つのdocker-compose.ymlで管理 |
| **インフラ（将来）** | GCP or AWS マネージド | 需要増加・セキュリティ要件に応じて移行 |
| **CI/CD** | GitHub Actions | テスト自動化 |
| **LLMモニタリング** | LangSmith | 実行トレーシング・マッピング精度評価・ドリフト検知 |
| **バックエンドテスト** | Pytest | ユニット + インテグレーションテスト |
| **UIライブラリ** | shadcn/ui + Tailwind CSS | ベースコンポーネント |
| **テーブル** | TanStack Table | フィルタ・ソート・仮想化 |
| **D&D** | dnd-kit | セクション並替（Phase 2以降） |

## 設計原則

1. **Python統一（バックエンド）**: LangGraph、openpyxl、pdfplumber全てPython → 言語統一で複雑さを排除
2. **DB役割分離**: Neo4j = ERP製品ナレッジ（グラフ+ベクトル）、PostgreSQL = 案件管理（リレーショナル）
3. **LLM段階的使い分け**: 数千回のLLM呼び出しに対し、軽量/高性能モデルを処理ステップごとに最適配置
4. **開発環境≒本番環境**: Docker Composeで全サービスを一元管理、PoC→本番の移行を最小コストに
5. **生成AI開発前提**: Next.js + shadcn/uiはAIコード生成の学習データが最も豊富な組合せ

## セキュリティ

| 項目 | 方針 |
|------|------|
| LLM API | クラウドAPI（Claude / OpenAI）で開始 |
| 通信 | TLS暗号化 |
| 認証 | APIキー管理（環境変数 / Secret Manager） |
| 移行 | 顧客機密情報要件が厳格化した場合、Azure OpenAI等プライベートエンドポイントへ |
