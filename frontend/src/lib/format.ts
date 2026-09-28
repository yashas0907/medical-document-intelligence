export function formatBytes(n: number): string {
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / (1024 * 1024)).toFixed(1)} MB`;
}

export function formatDate(iso: string | null | undefined): string {
  if (!iso) return "—";
  try {
    return new Date(iso).toLocaleString(undefined, {
      year: "numeric",
      month: "short",
      day: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    });
  } catch {
    return iso;
  }
}

export const STATUS_STYLES: Record<string, string> = {
  completed: "bg-emerald-50 text-emerald-700 border-emerald-200",
  processing: "bg-amber-50 text-amber-700 border-amber-200",
  uploaded: "bg-slate-100 text-slate-600 border-slate-200",
  failed: "bg-red-50 text-red-700 border-red-200",
};

export const CHANGE_STYLES: Record<string, string> = {
  changed: "bg-amber-50 text-amber-800 border-amber-200",
  added: "bg-emerald-50 text-emerald-700 border-emerald-200",
  removed: "bg-red-50 text-red-700 border-red-200",
  unchanged: "bg-slate-50 text-slate-500 border-slate-200",
};

export const ENTITY_COLORS: Record<string, string> = {
  date: "bg-sky-100 text-sky-800",
  medication: "bg-violet-100 text-violet-800",
  dose: "bg-fuchsia-100 text-fuchsia-800",
  vitals: "bg-rose-100 text-rose-800",
  organization: "bg-teal-100 text-teal-800",
  person: "bg-indigo-100 text-indigo-800",
  abbreviation: "bg-slate-200 text-slate-700",
  procedure: "bg-cyan-100 text-cyan-800",
};
