"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Separator } from "@/components/ui/separator";
import {
  ColumnMappingForm,
  type ColumnMappingConfig,
} from "@/components/column-mapping-form";
import { createCase } from "@/lib/api";

const DEFAULT_MAPPING: ColumnMappingConfig = {
  header_row: 1,
  data_start_row: 2,
  columns: {
    function_name: "機能名",
  },
};

export default function NewCasePage() {
  const router = useRouter();
  const [step, setStep] = useState(1);
  const [name, setName] = useState("");
  const [product, setProduct] = useState("SAP");
  const [file, setFile] = useState<File | null>(null);
  const [columnMapping, setColumnMapping] =
    useState<ColumnMappingConfig>(DEFAULT_MAPPING);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [dragOver, setDragOver] = useState(false);

  const canProceedStep1 = name.trim().length > 0;
  const canProceedStep2 = file !== null;
  const canSubmit = columnMapping.columns.function_name.trim().length > 0;

  async function handleSubmit() {
    if (!file) return;
    setLoading(true);
    setError(null);
    try {
      const formData = new FormData();
      formData.append("file", file);
      formData.append("name", name);
      formData.append("product", product);
      formData.append("column_mapping", JSON.stringify(columnMapping));

      const result = await createCase(formData);
      router.push(`/cases/${result.id}/mapping`);
    } catch (e) {
      setError(e instanceof Error ? e.message : "案件作成に失敗しました");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="mx-auto max-w-2xl space-y-6">
      <h1 className="text-2xl font-bold">新規案件作成</h1>

      {/* Step 1: 基本情報 */}
      <Card>
        <CardHeader>
          <CardTitle className="text-base">Step 1: 基本情報</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <div>
            <Label htmlFor="case-name">案件名</Label>
            <Input
              id="case-name"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="例: XX社 SAP導入プロジェクト"
              disabled={step > 1}
            />
          </div>
          <div>
            <Label>製品</Label>
            <Select
              value={product}
              onValueChange={setProduct}
              disabled={step > 1}
            >
              <SelectTrigger>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="SAP">SAP S/4 HANA</SelectItem>
                <SelectItem value="GRANDIT">GRANDIT</SelectItem>
              </SelectContent>
            </Select>
          </div>
          {step === 1 && (
            <Button onClick={() => setStep(2)} disabled={!canProceedStep1}>
              次へ
            </Button>
          )}
        </CardContent>
      </Card>

      {/* Step 2: ファイルアップロード */}
      {step >= 2 && (
        <Card>
          <CardHeader>
            <CardTitle className="text-base">
              Step 2: RFP Excel アップロード
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            <div
              className={`flex min-h-32 cursor-pointer items-center justify-center rounded-lg border-2 border-dashed transition ${
                dragOver
                  ? "border-primary bg-primary/5"
                  : "border-muted-foreground/25 hover:border-muted-foreground/50"
              }`}
              onClick={() => document.getElementById("file-input")?.click()}
              onDragOver={(e) => {
                e.preventDefault();
                e.stopPropagation();
                if (step <= 2) setDragOver(true);
              }}
              onDragLeave={(e) => {
                e.preventDefault();
                e.stopPropagation();
                setDragOver(false);
              }}
              onDrop={(e) => {
                e.preventDefault();
                e.stopPropagation();
                setDragOver(false);
                if (step > 2) return;
                const f = e.dataTransfer.files?.[0];
                if (f && f.name.endsWith(".xlsx")) {
                  setFile(f);
                } else if (f) {
                  setError(".xlsx ファイルのみ対応しています");
                }
              }}
            >
              <input
                id="file-input"
                type="file"
                accept=".xlsx"
                className="hidden"
                onChange={(e) => {
                  const f = e.target.files?.[0];
                  if (f) setFile(f);
                }}
                disabled={step > 2}
              />
              {file ? (
                <span className="text-sm">{file.name}</span>
              ) : (
                <span className="text-sm text-muted-foreground">
                  クリックまたはドラッグ＆ドロップで .xlsx を選択
                </span>
              )}
            </div>
            {step === 2 && (
              <Button onClick={() => setStep(3)} disabled={!canProceedStep2}>
                次へ
              </Button>
            )}
          </CardContent>
        </Card>
      )}

      {/* Step 3: カラムマッピング */}
      {step >= 3 && (
        <Card>
          <CardHeader>
            <CardTitle className="text-base">
              Step 3: カラムマッピング設定
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            <ColumnMappingForm
              value={columnMapping}
              onChange={setColumnMapping}
            />

            <Separator />

            {error && <p className="text-sm text-destructive">{error}</p>}

            <Button
              onClick={handleSubmit}
              disabled={!canSubmit || loading}
              className="w-full"
            >
              {loading ? "作成中..." : "案件を作成"}
            </Button>
          </CardContent>
        </Card>
      )}
    </div>
  );
}
