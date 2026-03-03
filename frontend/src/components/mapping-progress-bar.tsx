"use client";

import { Progress } from "@/components/ui/progress";

interface Props {
  completedCount: number;
  totalCount: number;
  errorCount?: number;
  isComplete: boolean;
}

export function MappingProgressBar({
  completedCount,
  totalCount,
  errorCount = 0,
  isComplete,
}: Props) {
  const percentage =
    totalCount > 0 ? Math.round((completedCount / totalCount) * 100) : 0;

  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between text-sm">
        <span>
          {isComplete ? "処理完了" : "処理中..."} {completedCount}/{totalCount}件
          {errorCount > 0 && (
            <span className="ml-2 text-destructive">
              ({errorCount}件エラー)
            </span>
          )}
        </span>
        <span className="font-mono">{percentage}%</span>
      </div>
      <Progress value={percentage} className="h-2" />
    </div>
  );
}
