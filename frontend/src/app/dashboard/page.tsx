"use client";

import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";
import { useAuth } from "@/components/auth-context";
import { api, type DocumentOut, type StatsOut } from "@/lib/api";
import { AppShell, Card, EmptyState, ErrorBox, Spinner } from "@/components/ui";
import { formatBytes, formatDate, STATUS_STYLES } from "@/lib/format";

export default function DashboardPage() {
  const { email, loading: authLoading, logout } = useAuth();
  const [docs, setDocs] = useState<DocumentOut[]>([]);
  const [stats, setStats] = useState<StatsOut | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const refresh = useCallback(async () => {
    try {
      const [d, s] = await Promise.all([api.documents.list(), api.stats()]);
      setDocs(d);
      setStats(s);
      setError(null);
      return d.some((x) => x.status === "processing" || x.status === "uploaded");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load documents");
      return false;
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  useEffect(() => {
    const hasActive = docs.some((d) => d.status === "processing" || d.status === "uploaded");
    if (hasActive && !pollRef.current) {
      pollRef.current = setInterval(() => refresh(), 2000);
    } else if (!hasActive && pollRef.current) {
      clearInterval(pollRef.current);
      pollRef.current = null;
    }
    return () => {
      if (pollRef.current) {
        clearInterval(pollRef.current);
        pollRef.current = null;
      }
    };
  }, [docs, refresh]);

  if (authLoading) return null;
  if (!email) {
    return (
      <AppShell title="Dashboard">
        <EmptyState
          title="Please sign in"
          hint="You need an account to view your documents."
          action={<Link href="/login" className="rounded-lg bg-teal-600 px-4 py-2 text-sm font-semibold text-white">Sign in</Link>}
        />
      </AppShell>
    );
  }

  return (
    <AppShell
      title="Dashboard"
      subtitle={`Signed in as ${email}`}
    >
      <div className="mb-2 flex justify-end">
        <button onClick={logout} className="text-xs font-medium text-slate-400 hover:text-slate-600">
          Sign out
        </button>
      </div>

      {error && <div className="mb-4"><ErrorBox message={error} /></div>}

      {stats && (
        <div className="mb-6 grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
          <StatCard label="Documents" value={stats.documents} />
          <StatCard label="Completed" value={stats.completed} accent="text-emerald-600" />
          <StatCard label="Processing" value={stats.processing} accent="text-amber-600" />
          <StatCard label="Pages" value={stats.pages} />
          <StatCard label="Extractions" value={stats.entities + stats.measurements} />
          <StatCard label="Q&A pairs" value={stats.qa_pairs} />
        </div>
      )}

      {loading ? (
        <Card className="p-8"><Spinner label="Loading documents…" /></Card>
      ) : docs.length === 0 ? (
        <EmptyState
          title="No documents yet"
          hint="Upload a PDF, DOCX, or TXT medical report to get started."
          action={<Link href="/upload" className="rounded-lg bg-teal-600 px-4 py-2 text-sm font-semibold text-white">Upload document</Link>}
        />
      ) : (
        <Card>
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-slate-200 text-left text-xs uppercase tracking-wide text-slate-400">
                <th className="px-4 py-3 font-medium">Title</th>
                <th className="px-4 py-3 font-medium">Type</th>
                <th className="px-4 py-3 font-medium">Pages</th>
                <th className="hidden px-4 py-3 font-medium md:table-cell">Size</th>
                <th className="px-4 py-3 font-medium">Status</th>
                <th className="hidden px-4 py-3 font-medium lg:table-cell">Uploaded</th>
                <th className="px-4 py-3" />
              </tr>
            </thead>
            <tbody>
              {docs.map((d) => (
                <tr key={d.id} className="border-b border-slate-100 last:border-0 hover:bg-slate-50">
                  <td className="max-w-xs truncate px-4 py-3 font-medium text-slate-900">{d.title}</td>
                  <td className="px-4 py-3 uppercase text-slate-500">{d.doc_type}</td>
                  <td className="px-4 py-3 text-slate-500">{d.page_count}</td>
                  <td className="hidden px-4 py-3 text-slate-500 md:table-cell">{formatBytes(d.file_size)}</td>
                  <td className="px-4 py-3">
                    <span className={`inline-flex rounded-full border px-2 py-0.5 text-xs font-medium ${STATUS_STYLES[d.status] || ""}`}>
                      {d.status === "uploaded" ? "queued" : d.status}
                    </span>
                  </td>
                  <td className="hidden px-4 py-3 text-slate-500 lg:table-cell">{formatDate(d.created_at)}</td>
                  <td className="px-4 py-3 text-right">
                    {d.status === "completed" && (
                      <Link
                        href={`/documents/${d.id}`}
                        className="rounded-md bg-teal-50 px-3 py-1 text-xs font-semibold text-teal-700 hover:bg-teal-100"
                      >
                        Open
                      </Link>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </Card>
      )}
    </AppShell>
  );
}

function StatCard({ label, value, accent }: { label: string; value: number; accent?: string }) {
  return (
    <Card className="px-4 py-3">
      <p className="text-xs font-medium uppercase tracking-wide text-slate-400">{label}</p>
      <p className={`mt-1 text-2xl font-semibold ${accent || "text-slate-900"}`}>{value}</p>
    </Card>
  );
}
