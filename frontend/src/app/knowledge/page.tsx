"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Progress } from "@/components/ui/progress";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Separator } from "@/components/ui/separator";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import {
  getKnowledgeStats,
  getKnowledgeItems,
  deleteKnowledgeItem,
  scanKnowledgeDir,
  startBulkLoad,
  getKnowledgeLoadStatus,
  uploadKnowledgeFiles,
  type KnowledgeStats,
  type KnowledgeItem,
  type KnowledgeScanResult,
} from "@/lib/api";

// ─── Stats Card ───

function StatsCard({ stats }: { stats: KnowledgeStats | null }) {
  if (!stats) return null;
  const topModules = Object.entries(stats.modules)
    .sort(([, a], [, b]) => b - a)
    .slice(0, 8);

  return (
    <div className="grid grid-cols-3 gap-4">
      <Card>
        <CardContent className="pt-6">
          <div className="text-2xl font-bold">{stats.scope_items}</div>
          <p className="text-xs text-muted-foreground">ScopeItem</p>
        </CardContent>
      </Card>
      <Card>
        <CardContent className="pt-6">
          <div className="text-2xl font-bold">{stats.module_overviews}</div>
          <p className="text-xs text-muted-foreground">ModuleOverview</p>
        </CardContent>
      </Card>
      <Card>
        <CardContent className="pt-6">
          <div className="text-2xl font-bold">
            {Object.keys(stats.modules).length}
          </div>
          <p className="text-xs text-muted-foreground">Modules</p>
        </CardContent>
      </Card>
      {topModules.length > 0 && (
        <Card className="col-span-3">
          <CardContent className="pt-6">
            <div className="flex flex-wrap gap-2">
              {topModules.map(([mod, count]) => (
                <span
                  key={mod}
                  className="inline-flex items-center rounded-full bg-blue-100 px-2.5 py-0.5 text-xs font-medium text-blue-800"
                >
                  {mod}: {count}
                </span>
              ))}
            </div>
          </CardContent>
        </Card>
      )}
    </div>
  );
}

// ─── Bulk Load State (親で管理) ───

interface BulkLoadProgress {
  phase: string;
  completed: number;
  total: number;
  current: string;
  errors: number;
}

interface BulkLoadComplete {
  scope_items: number;
  module_overviews: number;
  errors: number;
  duration: number;
}

interface BulkLoadState {
  loading: boolean;
  progress: BulkLoadProgress | null;
  loadComplete: BulkLoadComplete | null;
  error: string | null;
}

// ─── Bulk Load Tab ───

function BulkLoadTab({
  state,
  setState,
  pollingRef,
  onComplete,
}: {
  state: BulkLoadState;
  setState: React.Dispatch<React.SetStateAction<BulkLoadState>>;
  pollingRef: React.MutableRefObject<ReturnType<typeof setInterval> | null>;
  onComplete: () => void;
}) {
  const [dirPath, setDirPath] = useState("/Users/ktkrr/root/10_dev/ProposalCreation/product_doc");
  const [scanResult, setScanResult] = useState<KnowledgeScanResult | null>(
    null,
  );
  const [scanning, setScanning] = useState(false);

  const handleScan = useCallback(async () => {
    setScanning(true);
    setState((s) => ({ ...s, error: null, loadComplete: null }));
    setScanResult(null);
    try {
      const result = await scanKnowledgeDir(dirPath);
      setScanResult(result);
    } catch (e) {
      setState((s) => ({
        ...s,
        error: e instanceof Error ? e.message : "スキャンに失敗しました",
      }));
    } finally {
      setScanning(false);
    }
  }, [dirPath, setState]);

  const handleLoad = useCallback(async () => {
    setState({ loading: true, error: null, progress: null, loadComplete: null });
    try {
      const result = await startBulkLoad(dirPath);
      const totalItems = result.total_bpd + result.total_pdf;

      // ポーリングで進捗確認（2秒間隔）
      pollingRef.current = setInterval(async () => {
        try {
          const status = await getKnowledgeLoadStatus(result.task_id);

          if (!status.found) {
            if (pollingRef.current) clearInterval(pollingRef.current);
            pollingRef.current = null;
            const stats = await getKnowledgeStats();
            setState({
              loading: false,
              progress: null,
              loadComplete: {
                scope_items: stats.scope_items,
                module_overviews: stats.module_overviews,
                errors: 0,
                duration: 0,
              },
              error: null,
            });
            onComplete();
            return;
          }

          const completedTotal =
            (status.completed_bpd || 0) + (status.completed_pdf || 0);
          let phase = "初期化中...";
          if (status.phase === "bpd_parsing") phase = "BPD パース";
          else if (status.phase === "pdf_parsing") phase = "PDF パース";
          else if (status.phase === "neo4j_load") phase = "Neo4j 投入中...";
          else if (status.phase === "complete") phase = "完了";

          setState((s) => ({
            ...s,
            progress: {
              phase,
              completed: completedTotal,
              total: totalItems,
              current: `BPD: ${status.completed_bpd}/${status.total_bpd}  PDF: ${status.completed_pdf}/${status.total_pdf}`,
              errors: status.errors || 0,
            },
          }));

          if (status.is_complete) {
            if (pollingRef.current) clearInterval(pollingRef.current);
            pollingRef.current = null;
            const stats = await getKnowledgeStats();
            setState({
              loading: false,
              progress: null,
              loadComplete: {
                scope_items: stats.scope_items,
                module_overviews: stats.module_overviews,
                errors: status.errors || 0,
                duration: 0,
              },
              error: null,
            });
            onComplete();
          }
        } catch {
          // ポーリングエラーは無視
        }
      }, 2000);
    } catch (e) {
      setState((s) => ({
        ...s,
        loading: false,
        error: e instanceof Error ? e.message : "投入開始に失敗しました",
      }));
    }
  }, [dirPath, onComplete, setState, pollingRef]);

  const { loading, progress, loadComplete, error } = state;
  const progressPercent = progress
    ? Math.round((progress.completed / Math.max(progress.total, 1)) * 100)
    : 0;

  return (
    <div className="space-y-4">
      <div className="flex items-end gap-2">
        <div className="flex-1">
          <Label htmlFor="dir-path">サーバーディレクトリパス</Label>
          <Input
            id="dir-path"
            value={dirPath}
            onChange={(e) => setDirPath(e.target.value)}
            placeholder="/path/to/product_doc"
            disabled={loading}
          />
        </div>
        <Button onClick={handleScan} disabled={scanning || loading}>
          {scanning ? "スキャン中..." : "スキャン"}
        </Button>
      </div>

      {scanResult && (
        <Card>
          <CardContent className="pt-6 space-y-3">
            <div className="grid grid-cols-2 gap-4 text-sm">
              <div>
                <span className="text-muted-foreground">BPDセット: </span>
                <span className="font-medium">{scanResult.total_bpd}件</span>
              </div>
              <div>
                <span className="text-muted-foreground">PDF: </span>
                <span className="font-medium">{scanResult.total_pdf}件</span>
              </div>
              <div>
                <span className="text-muted-foreground">既存登録: </span>
                <span className="font-medium">
                  {scanResult.existing_scope_items}件
                </span>
              </div>
              <div>
                <span className="text-muted-foreground">新規: </span>
                <span className="font-bold text-green-600">
                  {scanResult.new_bpd_count}件
                </span>
              </div>
            </div>
            <Separator />
            <Button
              onClick={handleLoad}
              disabled={loading}
              className="w-full"
            >
              {loading ? "投入中..." : "一括投入開始"}
            </Button>
          </CardContent>
        </Card>
      )}

      {progress && (
        <Card>
          <CardContent className="pt-6 space-y-2">
            <div className="flex justify-between text-sm">
              <span>{progress.phase}</span>
              <span>
                {progress.completed} / {progress.total}
              </span>
            </div>
            <Progress value={progressPercent} />
            <p className="truncate text-xs text-muted-foreground">
              {progress.current}
            </p>
          </CardContent>
        </Card>
      )}

      {loadComplete && (
        <Card className="border-green-200 bg-green-50">
          <CardContent className="pt-6 space-y-1">
            <p className="font-medium text-green-800">投入完了</p>
            <p className="text-sm text-green-700">
              ScopeItem: {loadComplete.scope_items}件 / ModuleOverview:{" "}
              {loadComplete.module_overviews}件 / エラー: {loadComplete.errors}件
              / 所要時間: {loadComplete.duration}秒
            </p>
          </CardContent>
        </Card>
      )}

      {error && (
        <p className="text-sm text-destructive">{error}</p>
      )}
    </div>
  );
}

// ─── Upload Tab ───

function UploadTab({ onComplete }: { onComplete: () => void }) {
  const [files, setFiles] = useState<File[]>([]);
  const [uploading, setUploading] = useState(false);
  const [result, setResult] = useState<{
    processed: number;
    errors: string[];
  } | null>(null);
  const [error, setError] = useState<string | null>(null);

  const handleDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    const dropped = Array.from(e.dataTransfer.files).filter(
      (f) =>
        f.name.endsWith(".docx") ||
        f.name.endsWith(".xlsx") ||
        f.name.endsWith(".pdf"),
    );
    setFiles((prev) => [...prev, ...dropped]);
  }, []);

  const handleFileSelect = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      if (e.target.files) {
        setFiles((prev) => [...prev, ...Array.from(e.target.files!)]);
      }
    },
    [],
  );

  const handleUpload = useCallback(async () => {
    if (files.length === 0) return;
    setUploading(true);
    setError(null);
    setResult(null);
    try {
      const res = await uploadKnowledgeFiles(files);
      setResult({ processed: res.processed, errors: res.errors });
      setFiles([]);
      onComplete();
    } catch (e) {
      setError(
        e instanceof Error ? e.message : "アップロードに失敗しました",
      );
    } finally {
      setUploading(false);
    }
  }, [files, onComplete]);

  // ファイルをBPDセットとPDFに分類
  const bpdPrefixes = new Set<string>();
  const pdfFiles: string[] = [];
  for (const f of files) {
    if (f.name.includes("_BPD_") && f.name.includes("_S4CLD")) {
      bpdPrefixes.add(f.name.split("_S4CLD")[0]);
    } else if (f.name.endsWith(".pdf")) {
      pdfFiles.push(f.name);
    }
  }

  return (
    <div className="space-y-4">
      <div
        className="flex min-h-40 cursor-pointer flex-col items-center justify-center rounded-lg border-2 border-dashed border-muted-foreground/25 transition hover:border-muted-foreground/50"
        onDragOver={(e) => e.preventDefault()}
        onDrop={handleDrop}
        onClick={() => document.getElementById("knowledge-file-input")?.click()}
      >
        <input
          id="knowledge-file-input"
          type="file"
          accept=".docx,.xlsx,.pdf"
          multiple
          className="hidden"
          onChange={handleFileSelect}
        />
        <p className="text-sm text-muted-foreground">
          ドラッグ＆ドロップ、またはクリックで選択
        </p>
        <p className="text-xs text-muted-foreground">
          .docx / .xlsx / .pdf
        </p>
      </div>

      {files.length > 0 && (
        <Card>
          <CardContent className="pt-6 space-y-3">
            <p className="text-sm font-medium">{files.length}件のファイル</p>
            {bpdPrefixes.size > 0 && (
              <div className="text-sm">
                <span className="text-muted-foreground">BPDセット: </span>
                {Array.from(bpdPrefixes).map((p) => (
                  <span
                    key={p}
                    className="mr-1 inline-flex items-center rounded bg-blue-100 px-1.5 py-0.5 text-xs text-blue-800"
                  >
                    {p}
                  </span>
                ))}
              </div>
            )}
            {pdfFiles.length > 0 && (
              <div className="text-sm">
                <span className="text-muted-foreground">PDF: </span>
                {pdfFiles.map((p) => (
                  <span
                    key={p}
                    className="mr-1 inline-flex items-center rounded bg-purple-100 px-1.5 py-0.5 text-xs text-purple-800"
                  >
                    {p.slice(0, 30)}
                  </span>
                ))}
              </div>
            )}
            <div className="flex gap-2">
              <Button
                onClick={handleUpload}
                disabled={uploading}
                className="flex-1"
              >
                {uploading ? "処理中..." : "アップロード＆投入"}
              </Button>
              <Button
                variant="outline"
                onClick={() => setFiles([])}
                disabled={uploading}
              >
                クリア
              </Button>
            </div>
          </CardContent>
        </Card>
      )}

      {result && (
        <Card className="border-green-200 bg-green-50">
          <CardContent className="pt-6">
            <p className="font-medium text-green-800">
              {result.processed}件処理完了
            </p>
            {result.errors.length > 0 && (
              <div className="mt-2 text-sm text-red-600">
                {result.errors.map((e, i) => (
                  <p key={i}>{e}</p>
                ))}
              </div>
            )}
          </CardContent>
        </Card>
      )}

      {error && <p className="text-sm text-destructive">{error}</p>}
    </div>
  );
}

// ─── Browse Tab ───

function BrowseTab({
  items,
  onRefresh,
  loading,
}: {
  items: KnowledgeItem[];
  onRefresh: (params?: { module?: string; search?: string }) => void;
  loading: boolean;
}) {
  const [moduleFilter, setModuleFilter] = useState<string>("all");
  const [searchText, setSearchText] = useState("");
  const [deleting, setDeleting] = useState<string | null>(null);

  const handleFilterChange = useCallback(
    (module: string) => {
      setModuleFilter(module);
      onRefresh({
        module: module === "all" ? undefined : module,
        search: searchText || undefined,
      });
    },
    [onRefresh, searchText],
  );

  const handleSearch = useCallback(() => {
    onRefresh({
      module: moduleFilter === "all" ? undefined : moduleFilter,
      search: searchText || undefined,
    });
  }, [onRefresh, moduleFilter, searchText]);

  const handleDelete = useCallback(
    async (id: string) => {
      if (!confirm(`${id} を削除しますか？`)) return;
      setDeleting(id);
      try {
        await deleteKnowledgeItem(id);
        onRefresh({
          module: moduleFilter === "all" ? undefined : moduleFilter,
          search: searchText || undefined,
        });
      } catch {
        // ignore
      } finally {
        setDeleting(null);
      }
    },
    [onRefresh, moduleFilter, searchText],
  );

  // ユニークなモジュール一覧
  const modules = Array.from(new Set(items.map((i) => i.module).filter(Boolean))) as string[];

  return (
    <div className="space-y-4">
      <div className="flex items-end gap-2">
        <div className="w-40">
          <Label>モジュール</Label>
          <Select value={moduleFilter} onValueChange={handleFilterChange}>
            <SelectTrigger>
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">全モジュール</SelectItem>
              {modules.map((m) => (
                <SelectItem key={m} value={m}>
                  {m}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
        <div className="flex-1">
          <Label>検索</Label>
          <Input
            value={searchText}
            onChange={(e) => setSearchText(e.target.value)}
            placeholder="機能名・説明で検索"
            onKeyDown={(e) => e.key === "Enter" && handleSearch()}
          />
        </div>
        <Button variant="outline" onClick={handleSearch} disabled={loading}>
          検索
        </Button>
      </div>

      <div className="rounded-md border">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead className="w-16">種別</TableHead>
              <TableHead className="w-16">Module</TableHead>
              <TableHead>機能名 / モジュール名</TableHead>
              <TableHead className="w-20">Embed</TableHead>
              <TableHead className="w-16" />
            </TableRow>
          </TableHeader>
          <TableBody>
            {items.length > 0 ? (
              items.map((item) => (
                <TableRow key={item.id}>
                  <TableCell>
                    <span
                      className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium ${
                        item.type === "ScopeItem"
                          ? "bg-blue-100 text-blue-800"
                          : "bg-purple-100 text-purple-800"
                      }`}
                    >
                      {item.type === "ScopeItem" ? "SI" : "MO"}
                    </span>
                  </TableCell>
                  <TableCell className="text-xs">{item.module}</TableCell>
                  <TableCell>
                    <div className="text-sm font-medium">
                      {item.function_name || item.module_name || "-"}
                    </div>
                    <div className="max-w-md truncate text-xs text-muted-foreground">
                      {item.description || item.summary || "-"}
                    </div>
                  </TableCell>
                  <TableCell>
                    {item.has_embedding ? (
                      <span className="text-green-600 text-xs">OK</span>
                    ) : (
                      <span className="text-red-500 text-xs">-</span>
                    )}
                  </TableCell>
                  <TableCell>
                    <Button
                      variant="ghost"
                      size="sm"
                      className="text-xs text-destructive"
                      onClick={() => handleDelete(item.id)}
                      disabled={deleting === item.id}
                    >
                      削除
                    </Button>
                  </TableCell>
                </TableRow>
              ))
            ) : (
              <TableRow>
                <TableCell colSpan={5} className="h-24 text-center">
                  {loading ? "読込中..." : "データがありません"}
                </TableCell>
              </TableRow>
            )}
          </TableBody>
        </Table>
      </div>
      <p className="text-xs text-muted-foreground">{items.length}件表示</p>
    </div>
  );
}

// ─── Page ───

export default function KnowledgePage() {
  const [stats, setStats] = useState<KnowledgeStats | null>(null);
  const [items, setItems] = useState<KnowledgeItem[]>([]);
  const [itemsLoading, setItemsLoading] = useState(false);

  // BulkLoad の状態を親で管理（タブ切替でも消えない）
  const [bulkLoadState, setBulkLoadState] = useState<BulkLoadState>({
    loading: false,
    progress: null,
    loadComplete: null,
    error: null,
  });
  const bulkPollingRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // ページ離脱時のみポーリング停止
  useEffect(() => {
    return () => {
      if (bulkPollingRef.current) clearInterval(bulkPollingRef.current);
    };
  }, []);

  const loadStats = useCallback(async () => {
    try {
      const s = await getKnowledgeStats();
      setStats(s);
    } catch {
      // API未接続
    }
  }, []);

  const loadItems = useCallback(
    async (params?: { module?: string; search?: string }) => {
      setItemsLoading(true);
      try {
        const result = await getKnowledgeItems({
          ...params,
          limit: 500,
        });
        setItems(result);
      } catch {
        // ignore
      } finally {
        setItemsLoading(false);
      }
    },
    [],
  );

  useEffect(() => {
    loadStats();
    loadItems();
  }, [loadStats, loadItems]);

  const handleLoadComplete = useCallback(() => {
    loadStats();
    loadItems();
  }, [loadStats, loadItems]);

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-bold">ナレッジ管理</h1>

      <StatsCard stats={stats} />

      <Tabs defaultValue="bulk">
        <TabsList>
          <TabsTrigger value="bulk">一括投入</TabsTrigger>
          <TabsTrigger value="upload">個別追加</TabsTrigger>
          <TabsTrigger value="browse">登録済み一覧</TabsTrigger>
        </TabsList>

        <TabsContent value="bulk" className="mt-4">
          <BulkLoadTab
            state={bulkLoadState}
            setState={setBulkLoadState}
            pollingRef={bulkPollingRef}
            onComplete={handleLoadComplete}
          />
        </TabsContent>

        <TabsContent value="upload" className="mt-4">
          <UploadTab onComplete={handleLoadComplete} />
        </TabsContent>

        <TabsContent value="browse" className="mt-4">
          <BrowseTab
            items={items}
            onRefresh={loadItems}
            loading={itemsLoading}
          />
        </TabsContent>
      </Tabs>
    </div>
  );
}
