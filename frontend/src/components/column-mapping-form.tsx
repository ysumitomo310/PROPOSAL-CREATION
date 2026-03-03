"use client";

import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Separator } from "@/components/ui/separator";

export interface ColumnMappingConfig {
  header_row: number;
  data_start_row: number;
  sheet_name?: string;
  columns: {
    function_name: string;
    business_category?: string[];
    business_name?: string;
    requirement_summary?: string;
    requirement_detail?: string;
    importance?: string;
    importance_mapping?: Record<string, string>;
  };
}

interface Props {
  value: ColumnMappingConfig;
  onChange: (config: ColumnMappingConfig) => void;
}

export function ColumnMappingForm({ value, onChange }: Props) {
  const update = (patch: Partial<ColumnMappingConfig>) => {
    onChange({ ...value, ...patch });
  };

  const updateColumns = (
    patch: Partial<ColumnMappingConfig["columns"]>,
  ) => {
    onChange({ ...value, columns: { ...value.columns, ...patch } });
  };

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-3 gap-4">
        <div>
          <Label htmlFor="header_row">ヘッダー行</Label>
          <Input
            id="header_row"
            type="number"
            min={1}
            value={value.header_row}
            onChange={(e) =>
              update({ header_row: parseInt(e.target.value) || 1 })
            }
          />
        </div>
        <div>
          <Label htmlFor="data_start_row">データ開始行</Label>
          <Input
            id="data_start_row"
            type="number"
            min={1}
            value={value.data_start_row}
            onChange={(e) =>
              update({ data_start_row: parseInt(e.target.value) || 2 })
            }
          />
        </div>
        <div>
          <Label htmlFor="sheet_name">シート名（空 = 先頭シート）</Label>
          <Input
            id="sheet_name"
            value={value.sheet_name || ""}
            onChange={(e) =>
              update({ sheet_name: e.target.value || undefined })
            }
            placeholder="Sheet1"
          />
        </div>
      </div>

      <Separator />

      <p className="text-sm text-muted-foreground">
        Excelヘッダーの列名を入力してください
      </p>

      <div className="grid grid-cols-2 gap-4">
        <div>
          <Label htmlFor="col_function_name">
            機能名 <span className="text-destructive">*</span>
          </Label>
          <Input
            id="col_function_name"
            value={value.columns.function_name}
            onChange={(e) => updateColumns({ function_name: e.target.value })}
            placeholder="例: 機能名"
          />
        </div>
        <div>
          <Label htmlFor="col_business_name">業務名</Label>
          <Input
            id="col_business_name"
            value={value.columns.business_name || ""}
            onChange={(e) =>
              updateColumns({ business_name: e.target.value || undefined })
            }
            placeholder="例: 業務名"
          />
        </div>
        <div>
          <Label htmlFor="col_requirement_summary">要件概要</Label>
          <Input
            id="col_requirement_summary"
            value={value.columns.requirement_summary || ""}
            onChange={(e) =>
              updateColumns({
                requirement_summary: e.target.value || undefined,
              })
            }
            placeholder="例: 要件概要"
          />
        </div>
        <div>
          <Label htmlFor="col_requirement_detail">要件詳細</Label>
          <Input
            id="col_requirement_detail"
            value={value.columns.requirement_detail || ""}
            onChange={(e) =>
              updateColumns({
                requirement_detail: e.target.value || undefined,
              })
            }
            placeholder="例: 要件詳細"
          />
        </div>
        <div>
          <Label htmlFor="col_importance">重要度</Label>
          <Input
            id="col_importance"
            value={value.columns.importance || ""}
            onChange={(e) =>
              updateColumns({ importance: e.target.value || undefined })
            }
            placeholder="例: 重要度"
          />
        </div>
        <div>
          <Label htmlFor="col_business_category">
            業務分類（カンマ区切りで複数列可）
          </Label>
          <Input
            id="col_business_category"
            value={value.columns.business_category?.join(", ") || ""}
            onChange={(e) => {
              const val = e.target.value;
              updateColumns({
                business_category: val
                  ? val.split(/[,、]/).map((s) => s.trim()).filter(Boolean)
                  : undefined,
              });
            }}
            placeholder="例: Lv.1, Lv.2, Lv.3"
          />
        </div>
      </div>
    </div>
  );
}
