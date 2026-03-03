/**
 * API クライアント（TASK-E01）
 *
 * バックエンド FastAPI との通信ラッパー + TypeScript型定義。
 */

const API_BASE =
  process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000/api/v1";

// ─── Error ───

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

// ─── Base fetch ───

async function fetchApi<T>(path: string, options?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      ...options?.headers,
    },
  });
  if (!res.ok) {
    const body = await res.json().catch(() => ({ detail: res.statusText }));
    throw new ApiError(res.status, body.detail || res.statusText);
  }
  return res.json();
}

// ─── Case API ───

export async function createCase(formData: FormData): Promise<CaseResponse> {
  const res = await fetch(`${API_BASE}/cases`, {
    method: "POST",
    body: formData,
  });
  if (!res.ok) {
    const body = await res.json().catch(() => ({ detail: res.statusText }));
    throw new ApiError(res.status, body.detail || res.statusText);
  }
  return res.json();
}

export async function getCases(): Promise<CaseResponse[]> {
  return fetchApi<CaseResponse[]>("/cases");
}

export async function getCase(caseId: string): Promise<CaseResponse> {
  return fetchApi<CaseResponse>(`/cases/${caseId}`);
}

export async function deleteCase(caseId: string): Promise<void> {
  const res = await fetch(`${API_BASE}/cases/${caseId}`, { method: "DELETE" });
  if (!res.ok) {
    const body = await res.json().catch(() => ({ detail: res.statusText }));
    throw new ApiError(res.status, body.detail || res.statusText);
  }
}

// ─── Mapping API ───

export async function startMapping(
  caseId: string,
): Promise<MappingStartResponse> {
  return fetchApi<MappingStartResponse>(`/cases/${caseId}/mapping/start`, {
    method: "POST",
  });
}

export async function getMappingResults(
  caseId: string,
  filters?: MappingFilters,
): Promise<MappingResultsResponse> {
  const params = new URLSearchParams();
  if (filters?.judgment_level) params.set("judgment_level", filters.judgment_level);
  if (filters?.confidence) params.set("confidence", filters.confidence);
  if (filters?.importance) params.set("importance", filters.importance);
  if (filters?.status) params.set("status", filters.status);
  const qs = params.toString();
  return fetchApi<MappingResultsResponse>(
    `/cases/${caseId}/mapping/results${qs ? `?${qs}` : ""}`,
  );
}

export function getMappingStreamUrl(caseId: string): string {
  return `${API_BASE}/cases/${caseId}/mapping/stream`;
}

export async function exportMappingExcel(caseId: string): Promise<void> {
  const res = await fetch(`${API_BASE}/cases/${caseId}/mapping/export`);
  if (!res.ok) {
    const body = await res.json().catch(() => ({ detail: res.statusText }));
    throw new ApiError(res.status, body.detail || res.statusText);
  }
  const blob = await res.blob();
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  const disposition = res.headers.get("Content-Disposition");
  const match = disposition?.match(/filename="(.+)"/);
  a.download = match?.[1] || `mapping_results_${caseId}.xlsx`;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}

// ─── Knowledge API ───

export async function getKnowledgeStats(): Promise<KnowledgeStats> {
  return fetchApi<KnowledgeStats>("/knowledge/stats");
}

export async function getKnowledgeItems(params?: {
  module?: string;
  search?: string;
  item_type?: string;
  limit?: number;
  offset?: number;
}): Promise<KnowledgeItem[]> {
  const sp = new URLSearchParams();
  if (params?.module) sp.set("module", params.module);
  if (params?.search) sp.set("search", params.search);
  if (params?.item_type) sp.set("item_type", params.item_type);
  if (params?.limit) sp.set("limit", String(params.limit));
  if (params?.offset) sp.set("offset", String(params.offset));
  const qs = sp.toString();
  return fetchApi<KnowledgeItem[]>(`/knowledge/items${qs ? `?${qs}` : ""}`);
}

export async function deleteKnowledgeItem(itemId: string): Promise<void> {
  await fetchApi(`/knowledge/items/${encodeURIComponent(itemId)}`, {
    method: "DELETE",
  });
}

export async function scanKnowledgeDir(
  path: string,
): Promise<KnowledgeScanResult> {
  return fetchApi<KnowledgeScanResult>("/knowledge/scan", {
    method: "POST",
    body: JSON.stringify({ path }),
  });
}

export async function startBulkLoad(
  path: string,
  options?: { skip_embedding?: boolean; skip_llm?: boolean },
): Promise<KnowledgeLoadStartResponse> {
  return fetchApi<KnowledgeLoadStartResponse>("/knowledge/load/bulk", {
    method: "POST",
    body: JSON.stringify({ path, ...options }),
  });
}

export function getKnowledgeLoadStreamUrl(taskId: string): string {
  return `${API_BASE}/knowledge/load/stream/${taskId}`;
}

export async function getKnowledgeLoadStatus(
  taskId: string,
): Promise<KnowledgeLoadStatus> {
  return fetchApi<KnowledgeLoadStatus>(`/knowledge/load/status/${taskId}`);
}

export async function uploadKnowledgeFiles(
  files: File[],
): Promise<KnowledgeUploadResponse> {
  const formData = new FormData();
  for (const f of files) {
    formData.append("files", f);
  }
  const res = await fetch(`${API_BASE}/knowledge/upload`, {
    method: "POST",
    body: formData,
  });
  if (!res.ok) {
    const body = await res.json().catch(() => ({ detail: res.statusText }));
    throw new ApiError(res.status, body.detail || res.statusText);
  }
  return res.json();
}

// ─── Types ───

export interface CaseResponse {
  id: string;
  name: string;
  product: string;
  status: string;
  total_requirements: number;
  created_at: string;
}

export interface MappingStartResponse {
  case_id: string;
  message: string;
  total_requirements: number;
}

export interface MappingResultItem {
  id: string;
  requirement_id: string;
  sequence_number: number;
  function_name: string;
  requirement_summary: string | null;
  importance: string | null;
  judgment_level: string | null;
  confidence: string | null;
  confidence_score: number | null;
  proposal_text: string | null;
  rationale: string | null;
  scope_item_analysis: string | null;
  gap_analysis: string | null;
  judgment_reason: string | null;
  matched_scope_items: Record<string, unknown>[] | null;
  langsmith_trace_id: string | null;
  status: string;
}

export interface MappingResultsResponse {
  case_id: string;
  total: number;
  completed: number;
  results: MappingResultItem[];
}

export interface MappingResultDetail extends MappingResultItem {
  business_category: string | null;
  business_name: string | null;
  requirement_detail: string | null;
  related_nodes: Record<string, unknown>[] | null;
  module_overview_context: string | null;
  search_retry_count: number;
  search_history: Record<string, unknown>[] | null;
  started_at: string | null;
  completed_at: string | null;
}

export interface MappingFilters {
  judgment_level?: string;
  confidence?: string;
  importance?: string;
  status?: string;
}

// ─── Knowledge Types ───

export interface KnowledgeStats {
  scope_items: number;
  module_overviews: number;
  modules: Record<string, number>;
}

export interface KnowledgeItem {
  id: string;
  type: string;
  scope_item_id: string | null;
  function_name: string | null;
  module: string | null;
  business_domain: string | null;
  description: string | null;
  module_name: string | null;
  summary: string | null;
  source_doc: string | null;
  has_embedding: boolean;
}

export interface KnowledgeScanResult {
  bpd_sets: { prefix: string; has_en: boolean; has_xlsx: boolean }[];
  pdfs: string[];
  total_bpd: number;
  total_pdf: number;
  existing_scope_items: number;
  new_bpd_count: number;
}

export interface KnowledgeLoadStartResponse {
  task_id: string;
  total_bpd: number;
  total_pdf: number;
  message: string;
}

export interface KnowledgeLoadStatus {
  task_id: string;
  found: boolean;
  phase?: string;
  is_complete?: boolean;
  completed_bpd?: number;
  total_bpd?: number;
  completed_pdf?: number;
  total_pdf?: number;
  errors?: number;
  message?: string;
}

export interface KnowledgeUploadResponse {
  processed: number;
  scope_items: { id: string; function_name: string; module: string }[];
  module_overviews: { id: string; module_name: string; module: string }[];
  errors: string[];
}
