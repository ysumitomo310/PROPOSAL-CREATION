# Round 7: 技術スタック確定 - Q&A記録

> **ステータス**: 完了
> **日付**: 2026-02-17

## Q1. バックエンドフレームワーク

- **決定**: FastAPI（Python）
- **理由**: LangGraph/openpyxl/pdfplumber全てPython → 言語統一。非同期処理（LLM API、Gamma API）にasync/awaitネイティブ対応。Pydanticによるバリデーションがリクエスト/レスポンスとLLM出力の構造化に好相性。

## Q2. フロントエンドフレームワーク

- **決定**: Next.js（React / App Router）
- **理由**: 生成AIベース開発（Claude Code等）との相性が最も良い。学習データが豊富でコード生成精度が高く、「学習コスト」がAI開発ではほぼ消える。ファイルベースルーティングでGate画面・レビュー画面等の構造が明示的。UIライブラリ（shadcn/ui等）のエコシステムが最大。
- **補足**: SSRは社内ツールでは不要だが害もなく、将来の拡張性として残る。

## Q3. 案件管理DB

- **決定**: PostgreSQL
- **理由**: 案件データはリレーショナル構造（案件→ドキュメント→マッピング結果→提案書）。JSON/JSONB型で半構造化データも柔軟に保持。FastAPI + SQLAlchemy + PostgreSQLは定番構成。
- **補足**: Neo4jはERP製品ナレッジ専用、PostgreSQLは案件管理専用で役割分離。

## Q4. インフラ・ホスティング

- **決定**: Docker Compose（初期）→ クラウドマネージド移行
- **構成**: FastAPI + Next.js + PostgreSQL + Neo4j を docker-compose.yml で一元管理
- **理由**: 年間20-30案件の社内ツールではDocker Composeで十分。開発環境≒本番環境でデバッグ・運用がシンプル。需要増加・セキュリティ要件厳格化時にGCP/AWSマネージドへ移行。

## Q5. 開発支援・CI/CD・モニタリング

- **決定**: ミニマル構成で開始、RAG精度モニタリング拡張を見据えた設計
- **初期構成**:
  - GitHub（リポジトリ管理）
  - GitHub Actions（CI/テスト自動化）
  - LangSmith（LLMトレーシング・品質モニタリング）
  - Pytest（バックエンドテスト）
- **将来拡張**: Sentry（エラー監視）、Grafana（メトリクス）、LangSmith評価機能（マッピング精度の定量評価・ドリフト検知）
- **理由**: LangSmithはLangGraph利用でほぼ必須。PoC段階からトレースを蓄積し、精度改善サイクルの基盤とする。
