# CLAUDE.md - ProposalCreation SDD開発ルール

## プロジェクト概要
ERP（GRANDIT / SAP S/4 HANA Public Edition）提案書作成支援システム。
RFP情報をINPUTとし、RAGを活用して提案書・見積書を作成するアプリ。

## 開発手法: CCSDD（仕様駆動開発）

### 基本原則
- **Spec First**: 仕様を書いてから実装する。仕様が唯一の正（SSoT）
- **Read Before Write**: コード生成前に `spec/` 配下の関連仕様を必ず読む
- **承認ゲート**: 各フェーズでレビュー・承認を経てから次へ進む

### 仕様ドキュメント構成
```
spec/
├── overview.md                  ← 仕様概要（全体像のSSoT）★常に参照
├── steering/                    ← プロジェクトコンテキスト
│   ├── product.md               ← プロダクト概要
│   ├── tech.md                  ← 技術スタック（確定）
│   └── structure.md             ← プロジェクト構造
├── phase1-mapping-engine/       ← Phase 1: マッピングエンジン仕様
│   ├── requirements.md          ← 要件定義（EARS形式）
│   ├── design.md                ← 設計（Mermaid図含む）
│   └── tasks.md                 ← 実装タスク
├── templates/                   ← 仕様テンプレート
├── rules/                       ← 開発ルール
└── qa-records/                  ← Q&A記録（全8ラウンド完了）
```

### 仕様策定の流れ
1. `spec/overview.md` に全体像を記載・更新
2. Phase単位で `spec/<phase-name>/requirements.md` → `design.md` → `tasks.md` の順で策定
3. 各ステップでユーザーのレビュー・承認を得る
4. 承認された仕様に基づいて実装

### 実装時のルール
- `backend/` = Python（FastAPI + LangGraph）
- `frontend/` = TypeScript（Next.js + App Router）
- 実装前に必ず対応する `tasks.md` のタスクIDを確認
- テスト（Pytest）を実装と同時に作成
- LangSmithトレーシングを全LLM呼び出しに組み込む

### 禁止事項
- 仕様なしでのコード実装
- 仕様の無断変更
- 依存タスク未完了のタスクへの着手
- 要件IDの再利用

### 仕様変更時
- 必ず `spec/overview.md` の変更履歴を更新
- 関連する requirements.md, design.md, tasks.md も同期更新
- トレーサビリティ（要件ID → 設計 → 実装 → テスト）を維持
