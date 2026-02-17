# Project Structure - ProposalCreation

> **最終更新**: 2026-02-17（Phase 1実装準備に合わせて更新）

## ディレクトリ構成

```
ProposalCreation/
├── CLAUDE.md                        # Claude Code SDD開発ルール
├── spec/                            # 仕様ドキュメント（SSoT）
│   ├── overview.md                  # 仕様概要（全体像のSSoT）
│   ├── steering/                    # プロジェクトコンテキスト
│   │   ├── product.md              # プロダクト概要
│   │   ├── tech.md                 # 技術スタック（Round 7 確定）
│   │   └── structure.md            # プロジェクト構造（本ファイル）
│   ├── phase1-mapping-engine/       # Phase 1: マッピングエンジン仕様
│   │   ├── requirements.md         # 要件定義（EARS形式）
│   │   ├── design.md               # 設計書（Mermaid図含む）
│   │   └── tasks.md                # 実装タスク（依存関係含む）
│   ├── templates/                   # 仕様テンプレート
│   │   ├── requirements.md
│   │   ├── design.md
│   │   └── tasks.md
│   ├── rules/                       # 開発ルール
│   │   └── sdd-rules.md
│   └── qa-records/                  # Q&A進行レコード（全8ラウンド完了）
│       ├── round1-knowledge-design.md
│       ├── round2-mapping-engine.md
│       ├── round3-rag-architecture.md
│       ├── round4-rfp-intake.md
│       ├── round5-proposal-structure.md
│       ├── round6-output-integration.md
│       ├── round7-tech-stack.md
│       └── round8-ui-ux.md
├── ref_doc/                         # 参考ドキュメント
│   └── SDD統合Doc.md               # CCSDD参考資料
├── backend/                         # Python バックエンド（FastAPI + LangGraph）
│   ├── pyproject.toml               # Python依存管理
│   ├── app/
│   │   ├── main.py                  # FastAPIエントリポイント
│   │   ├── api/                     # APIルート定義
│   │   │   ├── cases.py             # 案件管理API
│   │   │   └── mapping.py           # マッピングAPI + SSE
│   │   ├── core/                    # 設定・依存性注入
│   │   │   └── config.py
│   │   ├── models/                  # SQLAlchemyモデル
│   │   ├── schemas/                 # Pydanticスキーマ
│   │   └── services/               # ビジネスロジック
│   │       ├── knowledge/           # Neo4jナレッジ操作
│   │       │   ├── parser.py        # Scope Itemパーサー
│   │       │   ├── loader.py        # Neo4jローダー
│   │       │   └── search.py        # Hybrid検索サービス
│   │       └── mapping/             # LangGraphマッピングエンジン
│   │           ├── agent.py         # LangGraphワークフロー定義
│   │           ├── state.py         # MappingState定義
│   │           └── nodes/           # 各ノード実装
│   ├── scripts/                     # 管理スクリプト
│   │   ├── load_knowledge.py        # ナレッジ投入
│   │   └── evaluate_accuracy.py     # 精度評価
│   ├── tests/                       # Pytestテストスイート
│   └── Dockerfile
├── frontend/                        # TypeScript フロントエンド（Next.js）
│   ├── package.json
│   ├── next.config.ts
│   ├── tsconfig.json
│   ├── src/
│   │   ├── app/                     # App Routerページ
│   │   │   ├── layout.tsx
│   │   │   ├── page.tsx             # ダッシュボード
│   │   │   └── cases/
│   │   │       ├── new/page.tsx     # 案件作成（Excel UP）
│   │   │       └── [id]/
│   │   │           └── mapping/page.tsx  # マッピング結果レビュー
│   │   ├── components/              # UIコンポーネント
│   │   └── lib/                     # ユーティリティ
│   └── Dockerfile
├── docker-compose.yml               # 全サービスオーケストレーション
├── .env.example                     # 環境変数テンプレート
└── .github/
    └── workflows/
        └── ci.yml                   # GitHub Actions CI
```

## 構造上の判断

| 判断 | 理由 |
|------|------|
| `backend/` + `frontend/` 分離（`src/`不使用） | Python/TypeScriptの依存管理が独立。各ディレクトリに独自のパッケージマネージャ |
| `spec/phase1-mapping-engine/` | Phase単位で仕様ディレクトリを作成。全機能名（`proposal-creation`）ではなくスコープを明示 |
| `backend/app/services/` 配下で機能分離 | `knowledge/`（Neo4j操作）と `mapping/`（LangGraphエンジン）の責務分離 |
| `backend/scripts/` | ナレッジ投入・精度評価等の管理操作はAPI非公開のCLIスクリプト |

## 仕様管理方針

- `spec/overview.md` が全体の仕様概要であり、常に最新状態を維持する
- Phase単位で `spec/<phase-name>/` ディレクトリを作成
- 各Phaseは requirements.md → design.md → tasks.md の順で仕様化
- 実装は承認された仕様に基づいてのみ行う
- 仕様変更時は `spec/overview.md` の変更履歴を更新し、関連ドキュメントも同期
