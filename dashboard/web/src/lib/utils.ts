import { clsx, type ClassValue } from "clsx";

export const MELBOURNE_TIME_ZONE = "Australia/Melbourne";

export function cn(...inputs: ClassValue[]) {
  return clsx(inputs);
}

export function formatMelbourneDateTime(value: unknown) {
  if (value === null || value === undefined || value === "") return "—";
  const text = String(value);
  const normalized = /^\d{4}-\d{2}-\d{2}T/.test(text) || /^\d{4}-\d{2}-\d{2}\s/.test(text) ? text.replace(" ", "T") : text;
  const date = new Date(normalized);
  if (Number.isNaN(date.getTime())) return text;
  return new Intl.DateTimeFormat("en-AU", {
    timeZone: MELBOURNE_TIME_ZONE,
    year: "numeric",
    month: "short",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
    timeZoneName: "short"
  }).format(date);
}

export function isTimestampColumn(column: string) {
  return column.endsWith("_at") || column === "generated_at" || column === "updated_at" || column === "completed_at" || column === "started_at" || column === "verified_at";
}

export function formatNumber(value: unknown) {
  if (value === null || value === undefined || value === "") return "—";
  const numeric = Number(value);
  if (Number.isFinite(numeric)) return new Intl.NumberFormat().format(Math.round(numeric));
  return String(value);
}

export function formatPercent(value: unknown) {
  if (value === null || value === undefined || value === "") return "—";
  const numeric = Number(value);
  if (!Number.isFinite(numeric)) return String(value);
  const scaled = Math.abs(numeric) <= 1 ? numeric * 100 : numeric;
  return `${scaled.toFixed(1)}%`;
}

export function toneClass(tone: string | undefined) {
  if (tone === "success") return "bg-emerald-50 text-emerald-800 ring-emerald-200";
  if (tone === "warning") return "bg-amber-50 text-amber-800 ring-amber-200";
  if (tone === "danger") return "bg-rose-50 text-rose-800 ring-rose-200";
  if (tone === "critical") return "bg-red-100 text-red-900 ring-red-300";
  return "bg-slate-100 text-slate-700 ring-slate-200";
}

export function statusTone(status: unknown) {
  const value = String(status ?? "").toLowerCase();
  if (["healthy", "ready", "complete", "green", "strong", "succeeded", "success", "ok", "on_track"].includes(value)) return "success";
  if (["watch", "partial", "mixed"].includes(value)) return "warning";
  if (["needs_attention", "amber", "missing", "blocked", "failed", "error"].includes(value)) return "danger";
  if (["critical", "critical_missing", "red"].includes(value)) return "critical";
  return "neutral";
}
