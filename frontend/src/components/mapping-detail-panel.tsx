"use client";

import { Separator } from "@/components/ui/separator";
import {
  Sheet,
  SheetContent,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import type { MappingResultItem } from "@/lib/api";

interface Props {
  result: MappingResultItem | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

function JudgmentBadge({ level }: { level: string | null }) {
  if (!level) return null;
  const variants: Record<string, string> = {
    "標準対応": "bg-green-100 text-green-800",
    "標準(業務変更含む)": "bg-blue-100 text-blue-800",
    "アドオン開発": "bg-orange-100 text-orange-800",
    "外部連携": "bg-purple-100 text-purple-800",
    "対象外": "bg-gray-100 text-gray-800",
  };
  return (
    <span
      className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium ${variants[level] || "bg-gray-100 text-gray-800"}`}
    >
      {level}
    </span>
  );
}

function ConfidenceBadge({ confidence }: { confidence: string | null }) {
  if (!confidence) return null;
  const variants: Record<string, string> = {
    High: "bg-green-100 text-green-800",
    Medium: "bg-yellow-100 text-yellow-800",
    Low: "bg-red-100 text-red-800",
  };
  return (
    <span
      className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium ${variants[confidence] || ""}`}
    >
      {confidence}
    </span>
  );
}

function Section({
  title,
  children,
}: {
  title: string;
  children: React.ReactNode;
}) {
  return (
    <div className="space-y-1">
      <h3 className="text-sm font-medium">{title}</h3>
      <div className="text-sm text-muted-foreground">{children}</div>
    </div>
  );
}

export function MappingDetailPanel({ result, open, onOpenChange }: Props) {
  if (!result) return null;

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent className="w-[600px] overflow-y-auto sm:max-w-[600px]">
        <SheetHeader>
          <SheetTitle className="text-left">
            {result.function_name}
          </SheetTitle>
        </SheetHeader>

        <div className="mt-4 space-y-4">
          {/* 判定 + 確信度 */}
          <div className="flex items-center gap-2">
            <JudgmentBadge level={result.judgment_level} />
            <ConfidenceBadge confidence={result.confidence} />
            {result.confidence_score != null && (
              <span className="text-xs text-muted-foreground">
                スコア: {result.confidence_score.toFixed(2)}
              </span>
            )}
          </div>

          <Separator />

          {/* 判定根拠（新形式：3フィールド） */}
          {result.scope_item_analysis && (
            <Section title="ScopeItem適合根拠">
              <p className="whitespace-pre-wrap">{result.scope_item_analysis}</p>
            </Section>
          )}
          {result.gap_analysis && result.gap_analysis !== "なし" && (
            <Section title="ギャップ・課題">
              <p className="whitespace-pre-wrap">{result.gap_analysis}</p>
            </Section>
          )}
          {result.judgment_reason && (
            <Section title="判定結論">
              <p className="whitespace-pre-wrap">{result.judgment_reason}</p>
            </Section>
          )}
          {/* 判定根拠（旧形式：後方互換） */}
          {!result.scope_item_analysis && result.rationale && (
            <Section title="判定根拠">
              <p className="whitespace-pre-wrap">{result.rationale}</p>
            </Section>
          )}

          {/* 提案文 */}
          {result.proposal_text && (
            <Section title="提案文 (proposal_text)">
              <p className="whitespace-pre-wrap">{result.proposal_text}</p>
            </Section>
          )}

          {/* マッチScope Items */}
          {result.matched_scope_items &&
            result.matched_scope_items.length > 0 && (
              <Section title="マッチしたScope Items">
                <div className="space-y-1">
                  {result.matched_scope_items.map((item, i) => (
                    <div key={i} className="text-xs">
                      <span className="font-medium">
                        {(item as Record<string, string>).id}
                      </span>
                      {" "}
                      {(item as Record<string, string>).function_name}
                    </div>
                  ))}
                </div>
              </Section>
            )}

          {/* LangSmith トレース */}
          {result.langsmith_trace_id && (
            <Section title="トレース">
              <a
                href={`https://smith.langchain.com/runs/${result.langsmith_trace_id}`}
                target="_blank"
                rel="noopener noreferrer"
                className="text-blue-500 underline"
              >
                LangSmith で表示
              </a>
            </Section>
          )}

          {/* メタデータ */}
          <Section title="メタデータ">
            <div className="space-y-1 text-xs">
              <div>ステータス: {result.status}</div>
              <div>重要度: {result.importance || "未設定"}</div>
              <div>要件概要: {result.requirement_summary || "なし"}</div>
            </div>
          </Section>
        </div>
      </SheetContent>
    </Sheet>
  );
}
