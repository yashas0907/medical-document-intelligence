"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { useAuth } from "@/components/auth-context";
import { api, ApiError, type ComparisonResult, type DocumentOut } from "@/lib/api";
import { AppShell, Card, EmptyState, ErrorBox, Spinner } from "@/components/ui";
import { CHANGE_STYLES, formatDate } from "@/lib/format";

export default function ComparePage() {
  const { email, loading } = useAuth();
  const [docs, setDocs] = useState<DocumentOut[]>([]);
  const [a, setA] = useState("");
  const [b, setB] = useState("");
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<ComparisonResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [filter, setFilter] = useState<"all" | "changed" | "added" | "removed">("all");

  useEffect(() => {
    if (email) {
      api.documents
        .list()
        .then((d) => {
          const completed = d.filter((x) => x.status === "completed");
          setDocs(completed);
          if (completed.length >= 2) {
            setA(completed[0].id);
            setB(completed[1].id);
          }
        })
        .catch((e) => setError(e.message));
    }
  }, [email]);

  async function run() {
    setBusy(true);
    setError(null);
    setResult(null);
    try {
      setResult(await api.compare.run(a, b));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Comparison failed");
    } finally {
      setBusy(false);
    }
  }

  if (!loading && !email) {
    return (
      <AppShell title="Compare documents">
        <EmptyState title="Please sign in"
          action={<Link href="/login" className="rounded-lg bg-teal-600 px-4 py-2 text-sm font-semibold text-white">Sign in</Link>} />
      </AppShell>
    );
  }

  const rows = result
    ? result.rows.filter((r) => filter === "all" || r.change_type === filter)
    : [];

  const counts = result
    ? {
        changed: result.rows.filter((r) => r.change_type === "changed").length,
        added: result.rows.filter((r) => r.change_type === "added").length,
        removed: result.rows.filter((r) => r.change_type === "removed").length,
        unchanged: result.rows.filter((r) => r.change_type === "unchanged").length,
      }
    : null;

  return (
    <AppShell
      title="Compare documents"
      subtitle="Side-by-side structured comparison of two processed reports. Differences are stated as recorded-value changes — no clinical interpretation."
    >
      {error && <div className="mb-4"><ErrorBox message={error} /></div>}

      {docs.length < 2 ? (
        <EmptyState
          title="Need at least two processed documents"
          hint="Upload two related reports (e.g. lab results from different dates) to compare them."
          action={<Link href="/upload" className="rounded-lg bg-teal-600 px-4 py-2 text-sm font-semibold text-white">Upload documents</Link>}
        />
      ) : (
        <>
          <Card className="mb-6 flex flex-wrap items-end gap-4 p-5">
            <div className="min-w-56 flex-1">
              <label className="mb-1 block text-xs font-medium text-slate-500">Document A</label>
              <select
                value={a}
                onChange={(e) => setA(e.target.value)}
                className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm outline-none focus:border-teal-500"
              >
                {docs.map((d) => (
                  <option key={d.id} value={d.id}>{d.title} {d.doc_date ? `(${d.doc_date})` : ""}</option>
                ))}
              </select>
            </div>
            <div className="min-w-56 flex-1">
              <label className="mb-1 block text-xs font-medium text-slate-500">Document B</label>
              <select
                value={b}
                onChange={(e) => setB(e.target.value)}
                className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm outline-none focus:border-teal-500"
              >
                {docs.map((d) => (
                  <option key={d.id} value={d.id}>{d.title} {d.doc_date ? `(${d.doc_date})` : ""}</option>
                ))}
              </select>
            </div>
            <button
              onClick={run}
              disabled={busy || !a || !b || a === b}
              className="rounded-lg bg-teal-600 px-5 py-2 text-sm font-semibold text-white hover:bg-teal-700 disabled:opacity-50"
            >
              {busy ? "Comparing…" : "Compare"}
            </button>
          </Card>

          {busy && <Card className="p-8"><Spinner label="Running deterministic comparison…" /></Card>}

          {result && !busy && (
            <>
              <Card className="mb-4 p-4">
                <p className="text-sm text-slate-700">{result.summary}</p>
                <p className="mt-1 text-xs text-slate-400">
                  {result.doc_a_title} {result.doc_a_date ? `(${formatDate(result.doc_a_date)})` : ""} vs{" "}
                  {result.doc_b_title} {result.doc_b_date ? `(${formatDate(result.doc_b_date)})` : ""}
                </p>
              </Card>

              <div className="mb-4 flex gap-2">
                {(["all", "changed", "added", "removed"] as const).map((f) => (
                  <button
                    key={f}
                    onClick={() => setFilter(f)}
                    className={`rounded-lg border px-3 py-1.5 text-xs font-medium capitalize ${
                      filter === f ? "border-teal-600 bg-teal-600 text-white" : "border-slate-200 bg-white text-slate-600"
                    }`}
                  >
                    {f}
                    {f !== "all" && counts ? ` (${counts[f]})` : ` (${result.rows.length})`}
                  </button>
                ))}
              </div>

              {rows.length === 0 ? (
                <EmptyState title="No rows match this filter" />
              ) : (
                <Card className="overflow-x-auto">
                  <table className="w-full text-sm">
                    <thead>
                      <tr className="border-b border-slate-200 text-left text-xs uppercase tracking-wide text-slate-400">
                        <th className="px-4 py-3 font-medium">Category</th>
                        <th className="px-4 py-3 font-medium">Item</th>
                        <th className="px-4 py-3 font-medium">Document A</th>
                        <th className="px-4 py-3 font-medium">Document B</th>
                        <th className="px-4 py-3 font-medium">Change</th>
                      </tr>
                    </thead>
                    <tbody>
                      {rows.map((r, i) => (
                        <tr key={i} className="border-b border-slate-100 last:border-0 hover:bg-slate-50">
                          <td className="px-4 py-2.5 text-slate-500">{r.category}</td>
                          <td className="px-4 py-2.5 font-medium text-slate-900">{r.item || "—"}</td>
                          <td className="px-4 py-2.5 text-slate-700">
                            {r.a ? r.a.value : <span className="text-slate-300">—</span>}
                          </td>
                          <td className="px-4 py-2.5 text-slate-700">
                            {r.b ? r.b.value : <span className="text-slate-300">—</span>}
                          </td>
                          <td className="px-4 py-2.5">
                            <span className={`inline-flex items-center gap-1.5 rounded-full border px-2 py-0.5 text-xs font-medium ${CHANGE_STYLES[r.change_type]}`}>
                              {r.change_type}
                            </span>
                            {r.change_note && (
                              <p className="mt-1 text-xs text-slate-400">{r.change_note}</p>
                            )}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </Card>
              )}
            </>
          )}
        </>
      )}
    </AppShell>
  );
}
