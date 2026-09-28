const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000/api/v1";

export class ApiError extends Error {
  code: string;
  details: Record<string, unknown>;
  status: number;

  constructor(status: number, code: string, message: string, details: Record<string, unknown> = {}) {
    super(message);
    this.status = status;
    this.code = code;
    this.details = details;
  }
}

function token(): string | null {
  if (typeof window === "undefined") return null;
  return localStorage.getItem("medintel_token");
}

export function setToken(t: string | null) {
  if (typeof window === "undefined") return;
  if (t) localStorage.setItem("medintel_token", t);
  else localStorage.removeItem("medintel_token");
}

async function handle<T>(res: Response): Promise<T> {
  if (res.ok) {
    if (res.status === 204) return undefined as T;
    return (await res.json()) as T;
  }
  let body: { error?: { code?: string; message?: string; details?: Record<string, unknown> } } = {};
  try {
    body = await res.json();
  } catch {
    /* non-JSON error body */
  }
  throw new ApiError(
    res.status,
    body.error?.code || "http_error",
    body.error?.message || res.statusText,
    body.error?.details || {}
  );
}

async function req<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  const t = token();
  if (t) headers.set("Authorization", `Bearer ${t}`);
  if (init.body && !(init.body instanceof FormData)) {
    headers.set("Content-Type", "application/json");
  }
  const res = await fetch(`${API_BASE}${path}`, { ...init, headers });
  return handle<T>(res);
}

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------
export interface TokenOut {
  access_token: string;
  token_type: string;
  expires_in: number;
}

export interface DocumentOut {
  id: string;
  title: string;
  original_filename: string;
  doc_type: string;
  status: "uploaded" | "processing" | "completed" | "failed";
  status_message: string | null;
  page_count: number;
  word_count: number;
  doc_date: string | null;
  file_size: number;
  created_at: string;
}

export interface ProcessingStatus {
  document_id: string;
  status: string;
  status_message: string | null;
  page_count: number;
  sections: number;
  chunks: number;
  entities: number;
  measurements: number;
  tables: number;
}

export interface SectionOut {
  id: string;
  title: string;
  section_type: string;
  page_number: number | null;
  order_index: number;
  char_count: number;
}

export interface EntityOut {
  id: string;
  entity_type: string;
  raw_text: string;
  normalized_text: string | null;
  normalized_confidence: number | null;
  page_number: number | null;
  source_snippet: string;
}

export interface MeasurementOut {
  id: string;
  name: string;
  value_raw: string;
  value_num: number | null;
  unit: string | null;
  reference_range: string | null;
  flag: string | null;
  page_number: number | null;
  source_snippet: string;
}

export interface TableOut {
  id: string;
  page_number: number;
  table_index: number;
  header: string[];
  rows: string[][];
}

export interface PageOut {
  page_number: number;
  extraction_method: string;
  ocr_confidence: number | null;
  text: string;
}

export interface Citation {
  ref: string;
  document_id: string;
  document_title: string | null;
  chunk_id: string | null;
  page_number: number | null;
  section_title: string | null;
  quote: string;
}

export interface Evidence {
  chunk_id: string;
  document_id: string;
  page_number: number;
  section_title: string | null;
  text: string;
  score: number;
  is_table_chunk: boolean;
}

export interface AskResult {
  question: string;
  answer: string;
  answer_sentences: { text: string; citation_refs: string[] }[];
  citations: Citation[];
  evidence: Evidence[];
  groundedness: number;
  evidence_coverage: number;
  method: string;
  insufficient_evidence: boolean;
  model_meta: { provider: string; model: string; prompt_version: string; pipeline_version: string } | null;
  conversation_id?: string;
}

export interface SummarySection {
  label: string;
  content: string;
  citation_refs: string[];
  found: boolean;
}

export interface SummaryResult {
  document_id: string;
  mode: string;
  title: string;
  summary_text: string;
  sections: SummarySection[];
  citations: Citation[];
}

export interface ComparisonRow {
  category: string;
  item: string | null;
  a: { doc_id: string; doc_title: string; value: string; citation_ref: string | null } | null;
  b: { doc_id: string; doc_title: string; value: string; citation_ref: string | null } | null;
  change_type: "added" | "removed" | "changed" | "unchanged";
  change_note: string | null;
}

export interface ComparisonResult {
  doc_a_id: string;
  doc_b_id: string;
  doc_a_title: string;
  doc_b_title: string;
  doc_a_date: string | null;
  doc_b_date: string | null;
  rows: ComparisonRow[];
  citations: { ref: string; document_id: string; document_title: string; page_number: number | null; quote: string }[];
  summary: string;
}

export interface TimelineEvent {
  date: string | null;
  date_confidence: string;
  source: string;
  document_id: string;
  page_number: number | null;
  items: string[];
}

export interface Contradiction {
  type: string;
  severity: "high" | "medium" | "low";
  confidence: number;
  explanation: string;
  a: { claim: string; document_title: string; page_number: number | null; quote: string };
  b: { claim: string; document_title: string; page_number: number | null; quote: string };
}

export interface ContradictionsResult {
  document_id: string;
  compared_with: string | null;
  contradictions: Contradiction[];
  notes: string[];
}

export interface StatsOut {
  documents: number;
  completed: number;
  processing: number;
  failed: number;
  pages: number;
  chunks: number;
  entities: number;
  measurements: number;
  qa_pairs: number;
  comparisons: number;
}

// ---------------------------------------------------------------------------
// API
// ---------------------------------------------------------------------------
export const api = {
  auth: {
    register: (email: string, password: string) =>
      req<{ id: string }>("/auth/register", {
        method: "POST",
        body: JSON.stringify({ email, password }),
      }),
    login: (email: string, password: string) =>
      req<TokenOut>("/auth/login", {
        method: "POST",
        body: JSON.stringify({ email, password }),
      }),
  },
  documents: {
    list: () => req<DocumentOut[]>("/documents"),
    get: (id: string) => req<DocumentOut>(`/documents/${id}`),
    status: (id: string) => req<ProcessingStatus>(`/documents/${id}/status`),
    remove: (id: string) => req<void>(`/documents/${id}`, { method: "DELETE" }),
    upload: (file: File) => {
      const fd = new FormData();
      fd.append("file", file);
      return req<DocumentOut>("/documents", { method: "POST", body: fd });
    },
    sections: (id: string) => req<SectionOut[]>(`/documents/${id}/sections`),
    entities: (id: string) => req<EntityOut[]>(`/documents/${id}/entities`),
    measurements: (id: string) => req<MeasurementOut[]>(`/documents/${id}/measurements`),
    tables: (id: string) => req<TableOut[]>(`/documents/${id}/tables`),
    pages: (id: string) => req<PageOut[]>(`/documents/${id}/pages?limit=100`),
  },
  qa: {
    ask: (docId: string, question: string) =>
      req<AskResult>(`/documents/${docId}/ask`, {
        method: "POST",
        body: JSON.stringify({ question }),
      }),
  },
  summaries: {
    generate: (docId: string, mode: string) =>
      req<SummaryResult>(`/documents/${docId}/summarize`, {
        method: "POST",
        body: JSON.stringify({ mode }),
      }),
  },
  compare: {
    run: (a: string, b: string) =>
      req<ComparisonResult>("/documents/compare", {
        method: "POST",
        body: JSON.stringify({ document_a_id: a, document_b_id: b }),
      }),
  },
  timeline: (docId: string) =>
    req<{ document_id: string; events: TimelineEvent[]; unpositioned: string[] }>(
      `/documents/${docId}/timeline`
    ),
  contradictions: (docId: string, compareWith?: string) =>
    req<ContradictionsResult>(
      `/documents/${docId}/contradictions${compareWith ? `?compare_with=${compareWith}` : ""}`,
      { method: "POST" }
    ),
  stats: () => req<StatsOut>("/documents/stats"),
};
