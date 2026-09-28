"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { useAuth } from "@/components/auth-context";
import { api, ApiError } from "@/lib/api";
import { AppShell, Card, ErrorBox } from "@/components/ui";
import { formatBytes } from "@/lib/format";

const ACCEPTED = ".pdf,.docx,.txt";
const MAX_MB = 30;

export default function UploadPage() {
  const { email, loading } = useAuth();
  const [dragging, setDragging] = useState(false);
  const [items, setItems] = useState<
    { key: string; name: string; size: number; status: "uploading" | "queued" | "error"; error?: string }[]
  >([]);
  const [error, setError] = useState<string | null>(null);

  const upload = useCallback(async (files: FileList | File[]) => {
    setError(null);
    const fileArr = Array.from(files);
    // key each upload by a unique id so status updates can't land on wrong rows
    const entries = fileArr.map((f) => ({
      key: `${f.name}-${f.size}-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`,
      name: f.name,
      size: f.size,
      status: "uploading" as const,
    }));
    setItems((prev) => [...entries, ...prev]);
    for (let i = 0; i < fileArr.length; i++) {
      const f = fileArr[i];
      const key = entries[i].key;
      const setItem = (patch: { status: "queued" | "error"; error?: string }) =>
        setItems((prev) => prev.map((it) => (it.key === key ? { ...it, ...patch } : it)));
      try {
        if (f.size > MAX_MB * 1024 * 1024) throw new Error(`File exceeds ${MAX_MB} MB limit`);
        const ext = "." + (f.name.split(".").pop() || "").toLowerCase();
        if (![".pdf", ".docx", ".txt"].includes(ext)) {
          throw new Error(`File type "${ext}" is not allowed (PDF, DOCX, TXT only)`);
        }
        await api.documents.upload(f);
        setItem({ status: "queued" });
      } catch (err) {
        const msg =
          err instanceof ApiError ? err.message : err instanceof Error ? err.message : "Upload failed";
        setItem({ status: "error", error: msg });
      }
    }
  }, []);

  useEffect(() => {
    // prevent browser default for drag events on window
    const prevent = (e: DragEvent) => e.preventDefault();
    window.addEventListener("dragover", prevent);
    window.addEventListener("drop", prevent);
    return () => {
      window.removeEventListener("dragover", prevent);
      window.removeEventListener("drop", prevent);
    };
  }, []);

  if (!loading && !email) {
    return (
      <AppShell title="Upload">
        <ErrorBox message="Please sign in to upload documents." />
      </AppShell>
    );
  }

  return (
    <AppShell
      title="Upload documents"
      subtitle="PDF, DOCX, or TXT. Scanned PDFs are OCR-processed when available. Files are private to your account."
    >
      <div
        onDragEnter={() => setDragging(true)}
        onDragLeave={() => setDragging(false)}
        onDragOver={(e) => {
          e.preventDefault();
          setDragging(true);
        }}
        onDrop={(e) => {
          e.preventDefault();
          setDragging(false);
          if (e.dataTransfer.files.length) upload(e.dataTransfer.files);
        }}
        className={`relative flex flex-col items-center justify-center rounded-2xl border-2 border-dashed px-6 py-16 transition ${
          dragging ? "border-teal-500 bg-teal-50" : "border-slate-300 bg-white"
        }`}
      >
        <svg className="mb-4 h-10 w-10 text-slate-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
          <path strokeLinecap="round" strokeLinejoin="round"
            d="M12 16.5V9.75m0 0l3 3m-3-3l-3 3M6.75 19.5a4.5 4.5 0 01-1.41-8.775 5.25 5.25 0 0110.233-2.33 3 3 0 013.758 3.848A3.752 3.752 0 0118 19.5H6.75z" />
        </svg>
        <p className="text-sm font-medium text-slate-900">
          Drag &amp; drop files here
        </p>
        <p className="mt-1 text-xs text-slate-500">or</p>
        <label className="mt-3 cursor-pointer rounded-lg bg-teal-600 px-4 py-2 text-sm font-semibold text-white hover:bg-teal-700">
          Browse files
          <input
            type="file"
            multiple
            accept={ACCEPTED}
            className="hidden"
            onChange={(e) => e.target.files && upload(e.target.files)}
          />
        </label>
        <p className="mt-4 text-xs text-slate-400">
          Max {MAX_MB} MB per file Â· Your documents are never shared with other accounts
        </p>
      </div>

      {error && <div className="mt-4"><ErrorBox message={error} /></div>}

      {items.length > 0 && (
        <div className="mt-6 space-y-2">
          {items.map((it) => (
            <Card key={it.key} className="flex items-center justify-between px-4 py-3">
              <div className="min-w-0">
                <p className="truncate text-sm font-medium text-slate-900">{it.name}</p>
                <p className="text-xs text-slate-400">{formatBytes(it.size)}</p>
              </div>
              {it.status === "uploading" && (
                <span className="flex items-center gap-2 text-xs text-slate-500">
                  <span className="h-3.5 w-3.5 animate-spin rounded-full border-2 border-slate-300 border-t-teal-600" />
                  Uploadingâ€¦
                </span>
              )}
              {it.status === "queued" && (
                <span className="rounded-full border border-amber-200 bg-amber-50 px-2.5 py-0.5 text-xs font-medium text-amber-700">
                  Queued for processing
                </span>
              )}
              {it.status === "error" && (
                <span className="text-xs font-medium text-red-600">{it.error}</span>
              )}
            </Card>
          ))}
        </div>
      )}

      <p className="mt-6 text-sm text-slate-500">
        After upload, processing runs asynchronously (extraction, OCR, structure detection,
        entity extraction, chunking, indexing). Track progress on the{" "}
        <Link href="/dashboard" className="font-medium text-teal-600 hover:underline">
          dashboard
        </Link>
        .
      </p>
    </AppShell>
  );
}
