"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { getCases, deleteCase, type CaseResponse } from "@/lib/api";

const STATUS_LABEL: Record<string, { text: string; className: string }> = {
  created: { text: "作成済み", className: "bg-gray-100 text-gray-800" },
  mapping: { text: "マッピング中", className: "bg-blue-100 text-blue-800" },
  completed: { text: "完了", className: "bg-green-100 text-green-800" },
  error: { text: "エラー", className: "bg-red-100 text-red-800" },
};

export default function DashboardPage() {
  const [cases, setCases] = useState<CaseResponse[]>([]);
  const [loading, setLoading] = useState(true);
  const [deleting, setDeleting] = useState<string | null>(null);

  const loadCases = useCallback(async () => {
    try {
      const data = await getCases();
      setCases(data);
    } catch {
      // API未接続
    } finally {
      setLoading(false);
    }
  }, []);

  const handleDelete = useCallback(async (c: CaseResponse) => {
    if (!confirm(`案件「${c.name}」を削除しますか？\n要件・マッピング結果もすべて削除されます。`)) {
      return;
    }
    setDeleting(c.id);
    try {
      await deleteCase(c.id);
      setCases((prev) => prev.filter((x) => x.id !== c.id));
    } catch {
      alert("削除に失敗しました");
    } finally {
      setDeleting(null);
    }
  }, []);

  useEffect(() => {
    loadCases();
  }, [loadCases]);

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold">案件一覧</h1>
        <Link href="/cases/new">
          <Button>新規案件作成</Button>
        </Link>
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">登録案件</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="rounded-md border">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>案件名</TableHead>
                  <TableHead className="w-24">製品</TableHead>
                  <TableHead className="w-24">要件数</TableHead>
                  <TableHead className="w-32">ステータス</TableHead>
                  <TableHead className="w-40">作成日時</TableHead>
                  <TableHead className="w-20" />
                </TableRow>
              </TableHeader>
              <TableBody>
                {loading ? (
                  <TableRow>
                    <TableCell colSpan={6} className="h-24 text-center">
                      読込中...
                    </TableCell>
                  </TableRow>
                ) : cases.length === 0 ? (
                  <TableRow>
                    <TableCell colSpan={6} className="h-24 text-center">
                      案件がありません
                    </TableCell>
                  </TableRow>
                ) : (
                  cases.map((c) => {
                    const st = STATUS_LABEL[c.status] || {
                      text: c.status,
                      className: "bg-gray-100 text-gray-800",
                    };
                    return (
                      <TableRow key={c.id}>
                        <TableCell className="font-medium">
                          <Link
                            href={`/cases/${c.id}/mapping`}
                            className="hover:underline"
                          >
                            {c.name}
                          </Link>
                        </TableCell>
                        <TableCell className="text-sm">{c.product}</TableCell>
                        <TableCell className="text-sm">
                          {c.total_requirements}
                        </TableCell>
                        <TableCell>
                          <span
                            className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium ${st.className}`}
                          >
                            {st.text}
                          </span>
                        </TableCell>
                        <TableCell className="text-xs text-muted-foreground">
                          {new Date(c.created_at).toLocaleString("ja-JP")}
                        </TableCell>
                        <TableCell className="space-x-1">
                          <Link href={`/cases/${c.id}/mapping`}>
                            <Button variant="ghost" size="sm" className="text-xs">
                              詳細
                            </Button>
                          </Link>
                          <Button
                            variant="ghost"
                            size="sm"
                            className="text-xs text-red-600 hover:text-red-800 hover:bg-red-50"
                            disabled={deleting === c.id}
                            onClick={() => handleDelete(c)}
                          >
                            {deleting === c.id ? "削除中..." : "削除"}
                          </Button>
                        </TableCell>
                      </TableRow>
                    );
                  })
                )}
              </TableBody>
            </Table>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
