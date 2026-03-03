"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { useParams } from "next/navigation";
import {
  type ColumnDef,
  flexRender,
  getCoreRowModel,
  useReactTable,
} from "@tanstack/react-table";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Skeleton } from "@/components/ui/skeleton";
import { MappingDetailPanel } from "@/components/mapping-detail-panel";
import { MappingProgressBar } from "@/components/mapping-progress-bar";
import { useMappingSSE } from "@/lib/use-mapping-sse";
import {
  exportMappingExcel,
  getCase,
  getMappingResults,
  startMapping,
  type CaseResponse,
  type MappingResultItem,
} from "@/lib/api";

// ─── Badge Components ───

function JudgmentBadge({ level }: { level: string | null }) {
  if (!level) return <span className="text-muted-foreground">-</span>;
  const colors: Record<string, string> = {
    "標準対応": "bg-green-100 text-green-800",
    "標準(業務変更含む)": "bg-blue-100 text-blue-800",
    "アドオン開発": "bg-orange-100 text-orange-800",
    "外部連携": "bg-purple-100 text-purple-800",
    "対象外": "bg-gray-100 text-gray-800",
  };
  return (
    <span
      className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium whitespace-nowrap ${colors[level] || "bg-gray-100 text-gray-800"}`}
    >
      {level}
    </span>
  );
}

function ImportanceBadge({ importance }: { importance: string | null }) {
  if (!importance) return <span className="text-muted-foreground">-</span>;
  const colors: Record<string, string> = {
    Must: "bg-red-100 text-red-800",
    Should: "bg-yellow-100 text-yellow-800",
    Could: "bg-gray-100 text-gray-800",
  };
  return (
    <span
      className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium ${colors[importance] || "bg-gray-100 text-gray-800"}`}
    >
      {importance}
    </span>
  );
}

function StatusBadge({ status }: { status: string }) {
  const labels: Record<string, string> = {
    pending: "待機",
    processing: "処理中",
    completed: "完了",
    error: "エラー",
  };
  const colors: Record<string, string> = {
    pending: "bg-gray-100 text-gray-600",
    processing: "bg-blue-100 text-blue-800",
    completed: "bg-green-100 text-green-800",
    error: "bg-red-100 text-red-800",
  };
  return (
    <span
      className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium ${colors[status] || ""}`}
    >
      {labels[status] || status}
    </span>
  );
}

// ─── Confidence cell (確信度 + スコア統合) ───

function ConfidenceCell({
  confidence,
  score,
}: {
  confidence: string | null;
  score: number | null;
}) {
  if (!confidence) return <span className="text-muted-foreground">-</span>;
  const colors: Record<string, string> = {
    High: "text-green-700",
    Medium: "text-yellow-700",
    Low: "text-red-700",
  };
  return (
    <span className={`text-xs font-medium ${colors[confidence] || ""}`}>
      {confidence}
      {score != null && (
        <span className="text-muted-foreground ml-1">
          {(score * 100).toFixed(0)}%
        </span>
      )}
    </span>
  );
}

// ─── Column widths (%) ───
// No(3) + 機能名(10) + 判定(9) + 確信度(8) + 重要度(5) + 判定根拠(auto) + マッチ(4) + 状態(5) = 44% fixed, 56% for rationale
const COL_WIDTHS = ["3%", "10%", "9%", "8%", "5%", undefined, "4%", "5%"];

// ─── Columns ───

const columns: ColumnDef<MappingResultItem>[] = [
  {
    accessorKey: "sequence_number",
    header: "No.",
  },
  {
    accessorKey: "function_name",
    header: "機能名",
    cell: ({ row }) => (
      <span className="text-sm font-medium">{row.original.function_name}</span>
    ),
  },
  {
    accessorKey: "judgment_level",
    header: "判定レベル",
    cell: ({ row }) => (
      <JudgmentBadge level={row.original.judgment_level} />
    ),
  },
  {
    id: "confidence_combined",
    header: "確信度",
    cell: ({ row }) => (
      <ConfidenceCell
        confidence={row.original.confidence}
        score={row.original.confidence_score}
      />
    ),
  },
  {
    accessorKey: "importance",
    header: "重要度",
    cell: ({ row }) => (
      <ImportanceBadge importance={row.original.importance} />
    ),
  },
  {
    id: "judgment_reason",
    header: "判定根拠",
    cell: ({ row }) => {
      const reason = row.original.judgment_reason || row.original.rationale || "";
      const analysis = row.original.scope_item_analysis || "";
      return (
        <div className="space-y-1">
          {reason && (
            <p className="text-xs font-medium leading-5 line-clamp-1">
              {reason}
            </p>
          )}
          {analysis && (
            <p className="text-xs text-muted-foreground leading-4 line-clamp-2">
              {analysis}
            </p>
          )}
          {!reason && !analysis && (
            <span className="text-muted-foreground">-</span>
          )}
        </div>
      );
    },
  },
  {
    id: "scope_count",
    header: "マッチ",
    cell: ({ row }) => {
      const count = row.original.matched_scope_items?.length ?? 0;
      return (
        <span className={`text-xs tabular-nums ${count > 0 ? "" : "text-muted-foreground"}`}>
          {count > 0 ? `${count}件` : "-"}
        </span>
      );
    },
  },
  {
    accessorKey: "status",
    header: "状態",
    cell: ({ row }) => <StatusBadge status={row.original.status} />,
  },
];

// ─── Filter Presets ───

interface FilterPreset {
  label: string;
  filters: {
    judgment_level?: string;
    confidence?: string;
    importance?: string;
    status?: string;
  };
}

const FILTER_PRESETS: FilterPreset[] = [
  { label: "全件", filters: {} },
  { label: "要レビュー (Must x Low)", filters: { importance: "Must", confidence: "Low" } },
  { label: "処理完了", filters: { status: "completed" } },
  { label: "エラー", filters: { status: "error" } },
];

// ─── Page Component ───

export default function MappingPage() {
  const params = useParams();
  const caseId = params.id as string;

  const [caseData, setCaseData] = useState<CaseResponse | null>(null);
  const [results, setResults] = useState<MappingResultItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [selectedResult, setSelectedResult] = useState<MappingResultItem | null>(null);
  const [panelOpen, setPanelOpen] = useState(false);
  const [activePreset, setActivePreset] = useState("全件");
  const [exporting, setExporting] = useState(false);

  const sse = useMappingSSE(caseId);

  // 初回データ取得
  useEffect(() => {
    async function load() {
      try {
        const [c, r] = await Promise.all([
          getCase(caseId),
          getMappingResults(caseId),
        ]);
        setCaseData(c);
        setResults(r.results);

        // マッピング中ならSSE接続
        if (c.status === "mapping") {
          sse.connect();
        }
      } catch {
        // API未接続時は空で表示
      } finally {
        setLoading(false);
      }
    }
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [caseId]);

  // SSE結果をマージ
  useEffect(() => {
    if (sse.results.length > 0) {
      setResults((prev) => {
        const existingIds = new Set(prev.map((r) => r.requirement_id));
        const newResults = sse.results.filter(
          (r) => !existingIds.has(r.requirement_id),
        );
        return [...prev, ...newResults];
      });
    }
  }, [sse.results]);

  // フィルタ変更
  const handleFilterChange = useCallback(
    async (preset: FilterPreset) => {
      setActivePreset(preset.label);
      try {
        const r = await getMappingResults(caseId, preset.filters);
        setResults(r.results);
      } catch {
        // ignore
      }
    },
    [caseId],
  );

  // マッピング開始
  const handleStartMapping = useCallback(async () => {
    try {
      await startMapping(caseId);
      setCaseData((prev) => (prev ? { ...prev, status: "mapping" } : prev));
      sse.connect();
    } catch {
      // ignore
    }
  }, [caseId, sse]);

  // Excelエクスポート
  const handleExport = useCallback(async () => {
    setExporting(true);
    try {
      await exportMappingExcel(caseId);
    } catch {
      // ignore
    } finally {
      setExporting(false);
    }
  }, [caseId]);

  // 行クリック
  const handleRowClick = useCallback((result: MappingResultItem) => {
    setSelectedResult(result);
    setPanelOpen(true);
  }, []);

  const table = useReactTable({
    data: results,
    columns,
    getCoreRowModel: getCoreRowModel(),
  });

  const isMapping = caseData?.status === "mapping" && !sse.isComplete;
  const canStartMapping = caseData?.status === "created";

  if (loading) {
    return (
      <div className="space-y-4">
        <Skeleton className="h-8 w-48" />
        <Skeleton className="h-64 w-full" />
      </div>
    );
  }

  return (
    <div className="space-y-4">
      {/* ヘッダー */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold">マッピング結果</h1>
          {caseData && (
            <p className="text-sm text-muted-foreground">
              {caseData.name} ({caseData.product})
            </p>
          )}
        </div>
        <div className="flex items-center gap-2">
          {canStartMapping && (
            <Button onClick={handleStartMapping}>マッピング開始</Button>
          )}

          {results.length > 0 && (
            <Button
              variant="outline"
              size="sm"
              onClick={handleExport}
              disabled={exporting}
            >
              {exporting ? "出力中..." : "Excel出力"}
            </Button>
          )}

          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button variant="outline" size="sm">
                フィルタ: {activePreset}
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent>
              {FILTER_PRESETS.map((preset) => (
                <DropdownMenuItem
                  key={preset.label}
                  onClick={() => handleFilterChange(preset)}
                >
                  {preset.label}
                </DropdownMenuItem>
              ))}
            </DropdownMenuContent>
          </DropdownMenu>
        </div>
      </div>

      {/* 進捗バー */}
      {(isMapping || sse.isComplete) && (
        <MappingProgressBar
          completedCount={sse.completedCount || results.filter((r) => r.status === "completed").length}
          totalCount={sse.totalCount || caseData?.total_requirements || 0}
          errorCount={sse.errorCount}
          isComplete={sse.isComplete}
        />
      )}

      {/* テーブル */}
      <div className="rounded-md border">
        <Table className="table-fixed w-full">
          <colgroup>
            {COL_WIDTHS.map((w, i) => (
              <col key={i} style={w ? { width: w } : undefined} />
            ))}
          </colgroup>
          <TableHeader>
            {table.getHeaderGroups().map((headerGroup) => (
              <TableRow key={headerGroup.id}>
                {headerGroup.headers.map((header) => (
                  <TableHead key={header.id} className="text-xs">
                    {header.isPlaceholder
                      ? null
                      : flexRender(
                          header.column.columnDef.header,
                          header.getContext(),
                        )}
                  </TableHead>
                ))}
              </TableRow>
            ))}
          </TableHeader>
          <TableBody>
            {table.getRowModel().rows.length ? (
              table.getRowModel().rows.map((row) => (
                <TableRow
                  key={row.id}
                  className="cursor-pointer hover:bg-muted/50"
                  onClick={() => handleRowClick(row.original)}
                >
                  {row.getVisibleCells().map((cell) => (
                    <TableCell key={cell.id} className="align-top py-3 overflow-hidden">
                      {flexRender(
                        cell.column.columnDef.cell,
                        cell.getContext(),
                      )}
                    </TableCell>
                  ))}
                </TableRow>
              ))
            ) : (
              <TableRow>
                <TableCell
                  colSpan={columns.length}
                  className="h-24 text-center"
                >
                  {canStartMapping
                    ? "マッピングを開始してください"
                    : "結果がありません"}
                </TableCell>
              </TableRow>
            )}
          </TableBody>
        </Table>
      </div>

      <p className="text-xs text-muted-foreground">
        {results.length}件表示
      </p>

      {/* 詳細サイドパネル */}
      <MappingDetailPanel
        result={selectedResult}
        open={panelOpen}
        onOpenChange={setPanelOpen}
      />
    </div>
  );
}
