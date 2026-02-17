# SDD開発ルール - ProposalCreation

## DO（必ず守ること）

1. **Read Before Write**: コード生成・修正前に、必ず `spec/` 配下の関連仕様を読むこと
2. **Spec Authority**: ユーザー指示と仕様が矛盾する場合、仕様を優先し更新の要否を確認すること
3. **Task Compliance**: `tasks.md` で定義されたタスクのみ実装すること
4. **Spec First**: 新機能追加時は、必ず requirements.md → design.md → tasks.md の順で仕様を策定すること
5. **Traceability**: 要件ID → 設計 → 実装 → テストの追跡可能性を維持すること
6. **Update Spec**: 仕様変更が発生した場合、必ず `spec/overview.md` を更新すること
7. **EARS Format**: 要件はEARS構文で記述すること

## DON'T（禁止事項）

1. **仕様なき実装禁止**: 承認されていない仕様に基づくコード生成は行わない
2. **仕様の無断変更禁止**: 実装の都合で仕様を勝手に変更しない
3. **依存違反禁止**: 依存タスクが完了していないタスクに着手しない
4. **ID再利用禁止**: 一度付与したID（REQ, TASK等）は削除後も再利用しない

## 仕様レビュープロセス

```
requirements.md 作成 → レビュー → 承認
       ↓
design.md 作成 → レビュー → 承認
       ↓
tasks.md 作成 → レビュー → 承認
       ↓
実装開始
```
