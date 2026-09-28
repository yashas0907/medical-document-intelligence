"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { useAuth } from "@/components/auth-context";
import {
  api,
  type AskResult,
  type Citation,
  type ContradictionsResult,
  type DocumentOut,
  type EntityOut,
  type MeasurementOut,
  type PageOut,
  type SectionOut,
  type SummaryResult,
  type TableOut,
  type TimelineEvent,
} from "@/lib/api";
import { AppShell, Card, EmptyState, ErrorBox, Spinner } from "@/components/ui";
import { ENTITY_COLORS, formatDate } from "@/lib/format";

type Tab = "overview" | "sections" | "pages" | "ask" | "summary" | "timeline" | "extract";

const TABS: { id: Tab; label: string }[] = [
  { id: "overview", label: "Overview" },
  { id: "ask", label: "Ask" },
  { id: "summary", label: "Summaries" },
  { id: "extract", label: "Extractions" },
  { id: "sections", label: "Sections" },
  { id: "pages", label: "Pages" },
  { id: "timeline", label: "Timeline" },
];

export default function DocumentPage() {
  const { email, loading: authLoading } = useAuth();
  const [docId, setDocId] = useState<string | null>(null);
  const [doc, setDoc] = useState<DocumentOut | null>(null);
  const [tab, setTab] = useState<Tab>("overview");
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const id = window.location.pathname.split("/").pop() || null;
    setDocId(id);
  }, []);

  useEffect(() => {
    if (!docId) return;
    api.documents
      .get(docId)
      .then(setDoc)
      .catch((e) => setError(e instanceof Error ? e.message : "Failed to load"));
  }, [docId]);

  if (authLoading) return null;
  if (!email) {
    return (
      <AppShell title="Document">
        <EmptyState title="Please sign in" hint="You need an account to view documents."
          action={<Link href="/login" className="rounded-lg bg-teal-600 px-4 py-2 text-sm font-semibold text-white">Sign in</Link>} />
      </AppShell>
    );
  }

  return (
    <AppShell title={doc?.title || "Document"} subtitle={doc ? `Uploaded ${formatDate(doc.created_at)} Â· ${doc.page_count} pages` : undefined}>
      {error && <ErrorBox message={error} />}
      {!doc && !error && <Card className="p-8"><Spinner /></Card>}

      {doc && (
        <>
          {doc.status !== "completed" && (
            <div className="mb-4">
              <ErrorBox
                message={
                  doc.status === "failed"
                    ? `Processing failed: ${doc.status_message || "unknown error"}`
                    : "Processing is still running â€” some features will be unavailable until it completes."
                }
              />
            </div>
          )}
          <div className="mb-6 flex flex-wrap gap-1 border-b border-slate-200">
            {TABS.map((t) => (
              <button
                key={t.id}
                onClick={() => setTab(t.id)}
                className={`-mb-px border-b-2 px-3.5 py-2 text-sm font-medium transition ${
                  tab === t.id
                    ? "border-teal-600 text-teal-700"
                    : "border-transparent text-slate-500 hover:text-slate-800"
                }`}
              >
                {t.label}
              </button>
            ))}
          </div>


          {tab === "overview" && docId && <OverviewTab docId={docId} doc={doc} />}
          {tab === "ask" && docId && <AskTab docId={docId} />}
          {tab === "summary" && docId && <SummaryTab docId={docId} />}
          {tab === "extract" && docId && <ExtractTab docId={docId} />}
          {tab === "sections" && docId && <SectionsTab docId={docId} />}
          {tab === "pages" && docId && <PagesTab docId={docId} />}
          {tab === "timeline" && docId && <TimelineTab docId={docId} />}
        </>
      )}
    </AppShell>
  );
}

// ---------------------------------------------------------------------------

function OverviewTab({ docId, doc }: { docId: string; doc: DocumentOut }) {
  const [status, setStatus] = useState<{
    sections: number; chunks: number; entities: number; measurements: number; tables: number;
  } | null>(null);
  const [contradictions, setContradictions] = useState<ContradictionsResult | null>(null);

  useEffect(() => {
    api.documents.status(docId).then(setStatus).catch(() => {});
    api.contradictions(docId).then(setContradictions).catch(() => {});
  }, [docId]);

  return (
    <div className="space-y-6">
      <div className="grid gap-3 sm:grid-cols-3 lg:grid-cols-6">
        <Info label="Pages" value={doc.page_count} />
        <Info label="Words" value={doc.word_count} />
        <Info label="Sections" value={status?.sections ?? "â€”"} />
        <Info label="Chunks" value={status?.chunks ?? "â€”"} />
        <Info label="Entities" value={status?.entities ?? "â€”"} />
        <Info label="Measurements" value={status?.measurements ?? "â€”"} />
      </div>

      {contradictions && contradictions.contradictions.length > 0 && (
        <Card className="border-amber-300 bg-amber-50 p-4">
          <h3 className="mb-2 text-sm font-semibold text-amber-900">
            Internal inconsistencies detected ({contradictions.contradictions.length})
          </h3>
          <div className="space-y-2">
            {contradictions.contradictions.map((c, i) => (
              <div key={i} className="rounded-lg border border-amber-200 bg-white p-3 text-sm">
                <p className="font-medium text-slate-900">{c.explanation}</p>
                <div className="mt-2 grid gap-2 sm:grid-cols-2">
                  <QuoteSide label="Claim A" claim={c.a.claim} quote={c.a.quote} page={c.a.page_number} />
                  <QuoteSide label="Claim B" claim={c.b.claim} quote={c.b.quote} page={c.b.page_number} />
                </div>
              </div>
            ))}
          </div>
        </Card>
      )}

      <Card className="p-5">
        <h3 className="mb-3 text-sm font-semibold text-slate-900">Document information</h3>
        <dl className="grid grid-cols-1 gap-x-8 gap-y-2 text-sm sm:grid-cols-2">
          <Row label="Document date" value={doc.doc_date || "Not found"} />
          <Row label="File type" value={doc.doc_type.toUpperCase()} />
          <Row label="Filename" value={doc.original_filename} />
          <Row label="Status" value={doc.status} />
        </dl>
      </Card>
    </div>
  );
}

function Info({ label, value }: { label: string; value: number | string }) {
  return (
    <Card className="px-4 py-3">
      <p className="text-xs font-medium uppercase tracking-wide text-slate-400">{label}</p>
      <p className="mt-0.5 text-xl font-semibold text-slate-900">{value}</p>
    </Card>
  );
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex justify-between gap-4 py-0.5">
      <dt className="text-slate-500">{label}</dt>
      <dd className="truncate font-medium text-slate-900">{value}</dd>
    </div>
  );
}

function QuoteSide({ label, claim, quote, page }: { label: string; claim: string; quote: string; page: number | null }) {
  return (
    <div className="rounded-md bg-slate-50 p-2 text-xs">
      <p className="font-semibold text-slate-700">{label}: <span className="font-normal">{claim}</span></p>
      <p className="mt-1 italic text-slate-500">â€œ{quote.slice(0, 140)}{quote.length > 140 ? "â€¦" : ""}â€ {page ? `Â· p.${page}` : ""}</p>
    </div>
  );
}

// ---------------------------------------------------------------------------

function AskTab({ docId }: { docId: string }) {
  const [question, setQuestion] = useState("");
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<AskResult | null>(null);
  const [history, setHistory] = useState<{ q: string; r: AskResult }[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [openEvidence, setOpenEvidence] = useState<string | null>(null);

  async function ask(e: React.FormEvent) {
    e.preventDefault();
    if (!question.trim()) return;
    setBusy(true);
    setError(null);
    try {
      const r = await api.qa.ask(docId, question);
      setResult(r);
      setHistory((h) => [{ q: question, r }, ...h].slice(0, 10));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to get answer");
    } finally {
      setBusy(false);
    }
  }

  const citeMap = useMemo(() => {
    const m = new Map<string, Citation>();
    result?.citations.forEach((c) => m.set(c.ref, c));
    return m;
  }, [result]);

  return (
    <div className="space-y-4">
      <Card className="p-5">
        <form onSubmit={ask} className="flex gap-2">
          <input
            value={question}
            onChange={(e) => setQuestion(e.target.value)}
            placeholder="Ask about this document â€” e.g. â€œWhat medications are mentioned?â€"
            className="flex-1 rounded-lg border border-slate-300 px-3 py-2 text-sm outline-none focus:border-teal-500 focus:ring-1 focus:ring-teal-500"
          />
          <button
            type="submit"
            disabled={busy || !question.trim()}
            className="rounded-lg bg-teal-600 px-5 py-2 text-sm font-semibold text-white hover:bg-teal-700 disabled:opacity-50"
          >
            {busy ? "Searchingâ€¦" : "Ask"}
          </button>
        </form>
        {error && <div className="mt-3"><ErrorBox message={error} /></div>}
      </Card>

      {result && (
        <Card className="p-5">
          {result.insufficient_evidence ? (
            <div className="rounded-lg border border-slate-200 bg-slate-50 p-4">
              <p className="font-medium text-slate-900">{result.answer}</p>
              <p className="mt-2 text-xs text-slate-500">
                The system refuses to answer when retrieved evidence does not support it â€”
                no information is fabricated.
              </p>
            </div>
          ) : (
            <>
              <div className="space-y-2.5">
                {result.answer_sentences.map((s, i) => (
                  <p key={i} className="text-sm leading-relaxed text-slate-900">
                    {s.text}{" "}
                    {s.citation_refs.map((r) => (
                      <button
                        key={r}
                        onClick={() => setOpenEvidence(openEvidence === r ? null : r)}
                        className="mx-0.5 rounded bg-teal-50 px-1.5 py-0.5 text-[11px] font-semibold text-teal-700 hover:bg-teal-100"
                      >
                        {r}
                      </button>
                    ))}
                  </p>
                ))}
              </div>
              {openEvidence && citeMap.get(openEvidence) && (
                <EvidencePopover cite={citeMap.get(openEvidence)!} onClose={() => setOpenEvidence(null)} />
              )}
              <div className="mt-4 flex flex-wrap gap-2 border-t border-slate-100 pt-3 text-xs text-slate-500">
                <span className="rounded-full bg-slate-100 px-2 py-0.5">
                  Method: <strong>{result.method}</strong>
                </span>
                <span className="rounded-full bg-slate-100 px-2 py-0.5">
                  Groundedness: <strong>{(result.groundedness * 100).toFixed(0)}%</strong>
                </span>
                {result.model_meta && (
                  <span className="rounded-full bg-slate-100 px-2 py-0.5">
                    {result.model_meta.provider} / {result.model_meta.model} Â· pipeline {result.model_meta.pipeline_version}
                  </span>
                )}
              </div>
              <details className="mt-3">
                <summary className="cursor-pointer text-xs font-medium text-slate-500 hover:text-slate-700">
                  Retrieved evidence ({result.evidence.length} passages)
                </summary>
                <div className="mt-2 space-y-2">
                  {result.evidence.map((ev, i) => (
                    <div key={ev.chunk_id} className="rounded-lg border border-slate-200 bg-slate-50 p-3">
                      <p className="mb-1 text-[11px] font-semibold uppercase tracking-wide text-slate-400">
                        [{i + 1}] p.{ev.page_number}
                        {ev.section_title ? ` Â· ${ev.section_title}` : ""}
                        {ev.is_table_chunk ? " Â· table" : ""} Â· score {ev.score.toFixed(3)}
                      </p>
                      <p className="text-xs leading-relaxed text-slate-600">{ev.text.slice(0, 400)}</p>
                    </div>
                  ))}
                </div>
              </details>
            </>
          )}
        </Card>
      )}

      {history.length > 0 && (
        <div>
          <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-400">
            Recent questions
          </h3>
          <div className="space-y-1.5">
            {history.map((h, i) => (
              <button
                key={i}
                onClick={() => setResult(h.r)}
                className="block w-full truncate rounded-lg border border-slate-200 bg-white px-3 py-2 text-left text-sm text-slate-700 hover:border-teal-300"
              >
                {h.q}
              </button>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

function EvidencePopover({ cite, onClose }: { cite: Citation; onClose: () => void }) {
  return (
    <div className="relative mt-3">
      <div className="rounded-lg border border-teal-300 bg-teal-50 p-4">
        <div className="mb-1 flex items-start justify-between">
          <p className="text-xs font-semibold text-teal-800">
            Source: {cite.document_title || cite.document_id} Â· Page {cite.page_number}
            {cite.section_title ? ` Â· ${cite.section_title}` : ""}
          </p>
          <button onClick={onClose} className="text-xs text-teal-700 hover:text-teal-900">âœ•</button>
        </div>
        <p className="text-sm italic leading-relaxed text-teal-900">â€œ{cite.quote}â€</p>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------

const SUMMARY_MODES = [
  { id: "quick", label: "Quick", desc: "Brief overview" },
  { id: "detailed", label: "Detailed", desc: "Per-section summary" },
  { id: "key_findings", label: "Key findings", desc: "Explicit findings only" },
  { id: "structured", label: "Structured", desc: "Typed sections incl. not-found" },
  { id: "timeline", label: "Timeline", desc: "Chronological events" },
];

function SummaryTab({ docId }: { docId: string }) {
  const [mode, setMode] = useState("quick");
  const [result, setResult] = useState<SummaryResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function run(m: string) {
    setMode(m);
    setBusy(true);
    setError(null);
    try {
      setResult(await api.summaries.generate(docId, m));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Summary failed");
    } finally {
      setBusy(false);
    }
  }

  useEffect(() => {
    run("quick");
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [docId]);

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap gap-2">
        {SUMMARY_MODES.map((m) => (
          <button
            key={m.id}
            onClick={() => run(m.id)}
            disabled={busy}
            className={`rounded-lg border px-3.5 py-2 text-sm font-medium transition ${
              mode === m.id
                ? "border-teal-600 bg-teal-600 text-white"
                : "border-slate-200 bg-white text-slate-700 hover:border-teal-300"
            } disabled:opacity-60`}
          >
            {m.label}
          </button>
        ))}
      </div>

      {busy && <Card className="p-6"><Spinner label="Generating summaryâ€¦" /></Card>}
      {error && <ErrorBox message={error} />}

      {result && !busy && (
        <Card className="p-6">
          {result.sections.length > 0 ? (
            <div className="space-y-4">
              {result.sections.map((s, i) => (
                <div key={i} className={s.found ? "" : "opacity-70"}>
                  <div className="flex items-center gap-2">
                    <h4 className="text-sm font-semibold text-slate-900">{s.label}</h4>
                    {!s.found && (
                      <span className="rounded-full bg-slate-100 px-2 py-0.5 text-[10px] font-medium uppercase text-slate-400">
                        not found
                      </span>
                    )}
                  </div>
                  <p className="mt-1 text-sm leading-relaxed text-slate-600">{s.content}</p>
                </div>
              ))}
            </div>
          ) : (
            <p className="text-sm leading-relaxed text-slate-700">{result.summary_text}</p>
          )}
        </Card>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------

function ExtractTab({ docId }: { docId: string }) {
  const [entities, setEntities] = useState<EntityOut[] | null>(null);
  const [measurements, setMeasurements] = useState<MeasurementOut[] | null>(null);
  const [tables, setTables] = useState<TableOut[]>([]);
  const [view, setView] = useState<"entities" | "measurements" | "tables">("entities");

  useEffect(() => {
    api.documents.entities(docId).then(setEntities).catch(() => setEntities([]));
    api.documents.measurements(docId).then(setMeasurements).catch(() => setMeasurements([]));
    api.documents.tables(docId).then(setTables).catch(() => setTables([]));
  }, [docId]);

  const grouped = useMemo(() => {
    const g = new Map<string, EntityOut[]>();
    entities?.forEach((e) => {
      const arr = g.get(e.entity_type) || [];
      arr.push(e);
      g.set(e.entity_type, arr);
    });
    return Array.from(g.entries()).sort((a, b) => b[1].length - a[1].length);
  }, [entities]);

  return (
    <div className="space-y-4">
      <div className="flex gap-2">
        {(["entities", "measurements", "tables"] as const).map((v) => (
          <button
            key={v}
            onClick={() => setView(v)}
            className={`rounded-lg border px-3.5 py-2 text-sm font-medium capitalize ${
              view === v ? "border-teal-600 bg-teal-600 text-white" : "border-slate-200 bg-white text-slate-700 hover:border-teal-300"
            }`}
          >
            {v} {v === "entities" && entities ? `(${entities.length})` : v === "measurements" && measurements ? `(${measurements.length})` : v === "tables" ? `(${tables.length})` : ""}
          </button>
        ))}
      </div>

      {view === "entities" && entities && (
        grouped.length === 0 ? (
          <EmptyState title="No entities extracted" hint="This document may not contain recognizable medical terms." />
        ) : (
          <div className="space-y-5">
            {grouped.map(([type, list]) => (
              <div key={type}>
                <h4 className="mb-2 flex items-center gap-2 text-sm font-semibold text-slate-900">
                  <span className={`rounded-full px-2.5 py-0.5 text-xs font-medium ${ENTITY_COLORS[type] || "bg-slate-100 text-slate-700"}`}>
                    {type}
                  </span>
                  <span className="text-xs font-normal text-slate-400">{list.length}</span>
                </h4>
                <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
                  {list.slice(0, 24).map((e) => (
                    <Card key={e.id} className="px-3.5 py-2.5">
                      <p className="text-sm font-medium text-slate-900">{e.raw_text}</p>
                      {e.normalized_text && e.normalized_text !== e.raw_text && (
                        <p className="mt-0.5 text-xs text-slate-500">
                          â†’ {e.normalized_text}
                          {e.normalized_confidence !== null && e.normalized_confidence < 1 && (
                            <span className="ml-1 text-amber-600">(uncertain)</span>
                          )}
                        </p>
                      )}
                      {e.page_number && <p className="mt-1 text-[11px] text-slate-400">page {e.page_number}</p>}
                    </Card>
                  ))}
                </div>
              </div>
            ))}
          </div>
        )
      )}

      {view === "measurements" && measurements && (
        measurements.length === 0 ? (
          <EmptyState title="No measurements extracted" />
        ) : (
          <Card className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-slate-200 text-left text-xs uppercase tracking-wide text-slate-400">
                  <th className="px-4 py-3 font-medium">Test</th>
                  <th className="px-4 py-3 font-medium">Value</th>
                  <th className="px-4 py-3 font-medium">Unit</th>
                  <th className="px-4 py-3 font-medium">Reference</th>
                  <th className="px-4 py-3 font-medium">Flag</th>
                  <th className="px-4 py-3 font-medium">Page</th>
                </tr>
              </thead>
              <tbody>
                {measurements.map((m) => (
                  <tr key={m.id} className="border-b border-slate-100 last:border-0 hover:bg-slate-50">
                    <td className="px-4 py-2.5 font-medium text-slate-900">{m.name}</td>
                    <td className="px-4 py-2.5 text-slate-700">{m.value_raw}</td>
                    <td className="px-4 py-2.5 text-slate-500">{m.unit || "â€”"}</td>
                    <td className="px-4 py-2.5 text-slate-500">{m.reference_range || "â€”"}</td>
                    <td className="px-4 py-2.5">
                      {m.flag ? (
                        <span className={`rounded px-1.5 py-0.5 text-xs font-bold ${
                          m.flag === "H" ? "bg-amber-100 text-amber-800" : "bg-sky-100 text-sky-800"
                        }`}>{m.flag}</span>
                      ) : "â€”"}
                    </td>
                    <td className="px-4 py-2.5 text-slate-400">{m.page_number ?? "â€”"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </Card>
        )
      )}

      {view === "tables" && (
        tables.length === 0 ? (
          <EmptyState title="No tables detected" hint="Tables appear here when a document contains them, with full structure preserved." />
        ) : (
          <div className="space-y-4">
            {tables.map((t) => (
              <Card key={t.id} className="overflow-x-auto">
                <p className="border-b border-slate-100 px-4 py-2.5 text-xs font-semibold uppercase tracking-wide text-slate-400">
                  Page {t.page_number} Â· {t.rows.length} rows
                </p>
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b border-slate-200 bg-slate-50 text-left text-xs font-semibold text-slate-600">
                      {t.header.map((h, i) => <th key={i} className="px-4 py-2">{h}</th>)}
                    </tr>
                  </thead>
                  <tbody>
                    {t.rows.map((r, i) => (
                      <tr key={i} className="border-b border-slate-100 last:border-0">
                        {r.map((c, j) => <td key={j} className="px-4 py-2 text-slate-700">{c}</td>)}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </Card>
            ))}
          </div>
        )
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------

function SectionsTab({ docId }: { docId: string }) {
  const [sections, setSections] = useState<SectionOut[] | null>(null);

  useEffect(() => {
    api.documents.sections(docId).then(setSections).catch(() => setSections([]));
  }, [docId]);

  if (!sections) return <Card className="p-6"><Spinner /></Card>;
  if (sections.length === 0) return <EmptyState title="No sections detected" />;

  return (
    <div className="space-y-2">
      {sections.map((s) => (
        <Card key={s.id} className="flex items-center justify-between px-4 py-3">
          <div>
            <p className="text-sm font-medium text-slate-900">{s.title}</p>
            <p className="text-xs text-slate-400">
              page {s.page_number ?? "?"} Â· {s.char_count.toLocaleString()} chars
            </p>
          </div>
        </Card>
      ))}
    </div>
  );
}

// ---------------------------------------------------------------------------

function PagesTab({ docId }: { docId: string }) {
  const [pages, setPages] = useState<PageOut[] | null>(null);
  const [page, setPage] = useState(0);

  useEffect(() => {
    api.documents.pages(docId).then(setPages).catch(() => setPages([]));
  }, [docId]);

  if (!pages) return <Card className="p-6"><Spinner /></Card>;
  if (pages.length === 0) return <EmptyState title="No pages" />;

  const current = pages[Math.min(page, pages.length - 1)];
  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <div className="flex gap-1">
          <button
            onClick={() => setPage(Math.max(0, page - 1))}
            disabled={page === 0}
            className="rounded-md border border-slate-200 px-3 py-1.5 text-sm text-slate-600 disabled:opacity-40"
          >
            â† Prev
          </button>
          <button
            onClick={() => setPage(Math.min(pages.length - 1, page + 1))}
            disabled={page >= pages.length - 1}
            className="rounded-md border border-slate-200 px-3 py-1.5 text-sm text-slate-600 disabled:opacity-40"
          >
            Next â†’
          </button>
        </div>
        <div className="flex items-center gap-3 text-xs">
          <span className="text-slate-500">
            Page {current.page_number} / {pages.length}
          </span>
          <span className={`rounded-full px-2 py-0.5 font-medium ${
            current.extraction_method === "ocr"
              ? "bg-violet-100 text-violet-700"
              : current.extraction_method === "text"
                ? "bg-emerald-100 text-emerald-700"
                : "bg-red-100 text-red-700"
          }`}>
            {current.extraction_method}
            {current.ocr_confidence !== null ? ` (${current.ocr_confidence.toFixed(1)}%)` : ""}
          </span>
        </div>
      </div>
      <Card className="max-h-[600px] overflow-y-auto p-6">
        <pre className="whitespace-pre-wrap font-sans text-sm leading-relaxed text-slate-700">
          {current.text || "(no text â€” page may be a scanned image that OCR could not read)"}
        </pre>
      </Card>
    </div>
  );
}

// ---------------------------------------------------------------------------

function TimelineTab({ docId }: { docId: string }) {
  const [events, setEvents] = useState<TimelineEvent[] | null>(null);

  useEffect(() => {
    api.timeline(docId).then((r) => setEvents(r.events)).catch(() => setEvents([]));
  }, [docId]);

  if (!events) return <Card className="p-6"><Spinner /></Card>;
  if (events.length === 0) {
    return <EmptyState title="No dated events found" hint="Timeline requires explicit dates in the document." />;
  }

  return (
    <div className="relative pl-6">
      <div className="absolute left-2 top-2 bottom-2 w-px bg-slate-200" />
      {events.map((e, i) => (
        <div key={i} className="relative mb-5">
          <div className="absolute -left-[19px] top-1.5 h-2.5 w-2.5 rounded-full border-2 border-teal-500 bg-white" />
          <Card className="px-4 py-3">
            <div className="flex items-center gap-2">
              <p className="font-mono text-sm font-semibold text-slate-900">{e.date}</p>
              {e.date_confidence === "low" && (
                <span className="rounded-full bg-amber-100 px-2 py-0.5 text-[10px] font-medium text-amber-700">
                  low confidence
                </span>
              )}
            </div>
            <ul className="mt-1.5 space-y-1">
              {e.items.map((it, j) => (
                <li key={j} className="text-xs leading-relaxed text-slate-600">Â· {it}</li>
              ))}
            </ul>
            <p className="mt-1.5 text-[11px] text-slate-400">
              {e.source} Â· page {e.page_number ?? "?"}
            </p>
          </Card>
        </div>
      ))}
    </div>
  );
}
