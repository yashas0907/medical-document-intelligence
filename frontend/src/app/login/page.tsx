"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { useAuth } from "@/components/auth-context";
import { ErrorBox } from "@/components/ui";

export default function LoginPage() {
  const { email, loading, login, register } = useAuth();
  const router = useRouter();
  const [mode, setMode] = useState<"login" | "register">("login");
  const [em, setEm] = useState("");
  const [pw, setPw] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!loading && email) router.replace("/dashboard");
  }, [email, loading, router]);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setBusy(true);
    try {
      if (mode === "login") await login(em, pw);
      else await register(em, pw);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Authentication failed");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-slate-50 px-4">
      <div className="w-full max-w-md">
        <div className="mb-8 text-center">
          <div className="mx-auto mb-3 flex h-12 w-12 items-center justify-center rounded-xl bg-teal-600 text-xl font-bold text-white">
            M
          </div>
          <h1 className="text-2xl font-semibold tracking-tight text-slate-900">MedIntel</h1>
          <p className="mt-1 text-sm text-slate-500">
            Medical document intelligence with evidence, citations, and provenance.
          </p>
        </div>

        <div className="rounded-xl border border-slate-200 bg-white p-6 shadow-sm">
          <div className="mb-4 flex rounded-lg bg-slate-100 p-1 text-sm font-medium">
            <button
              type="button"
              onClick={() => setMode("login")}
              className={`flex-1 rounded-md px-3 py-1.5 transition ${mode === "login" ? "bg-white text-slate-900 shadow" : "text-slate-500"}`}
            >
              Sign in
            </button>
            <button
              type="button"
              onClick={() => setMode("register")}
              className={`flex-1 rounded-md px-3 py-1.5 transition ${mode === "register" ? "bg-white text-slate-900 shadow" : "text-slate-500"}`}
            >
              Create account
            </button>
          </div>

          <form onSubmit={submit} className="space-y-4">
            <div>
              <label htmlFor="email" className="mb-1 block text-sm font-medium text-slate-700">
                Email
              </label>
              <input
                id="email"
                type="email"
                required
                value={em}
                onChange={(e) => setEm(e.target.value)}
                className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm outline-none focus:border-teal-500 focus:ring-1 focus:ring-teal-500"
                placeholder="you@example.com"
              />
            </div>
            <div>
              <label htmlFor="password" className="mb-1 block text-sm font-medium text-slate-700">
                Password
              </label>
              <input
                id="password"
                type="password"
                required
                minLength={8}
                value={pw}
                onChange={(e) => setPw(e.target.value)}
                className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm outline-none focus:border-teal-500 focus:ring-1 focus:ring-teal-500"
                placeholder="At least 8 characters"
              />
            </div>
            {error && <ErrorBox message={error} />}
            <button
              type="submit"
              disabled={busy}
              className="w-full rounded-lg bg-teal-600 px-4 py-2 text-sm font-semibold text-white transition hover:bg-teal-700 disabled:opacity-60"
            >
              {busy ? "Please wait…" : mode === "login" ? "Sign in" : "Create account"}
            </button>
          </form>
        </div>

        <p className="mt-4 text-center text-xs text-slate-400">
          Demo credentials (dev mode): demo@medintel.local / demo-password
        </p>
        <p className="mt-2 text-center text-[11px] text-amber-700">
          Informational document analysis only — not a substitute for professional medical advice.
        </p>
      </div>
    </div>
  );
}
