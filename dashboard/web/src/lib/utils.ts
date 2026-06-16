import { clsx, type ClassValue } from "clsx";

export const MELBOURNE_TIME_ZONE = "Australia/Melbourne";

const LABEL_OVERRIDES: Record<string, string> = {
  abn: "ABN",
  ai: "AI",
  api: "API",
  bq: "BigQuery",
  cta: "CTA",
  ctr: "CTR",
  cvr: "CVR",
  ga4: "GA4",
  gsc: "Search Console",
  h1: "H1",
  id: "ID",
  json: "JSON",
  mom: "MoM",
  seo: "SEO",
  se: "SE",
  url: "URL",
  urls: "URLs",
  yoy: "YoY",
  client_slug: "Client",
  client_name: "Client",
  source_id: "Source ID",
  run_id: "Run ID",
  agent_id: "Agent",
  ga4_property: "GA4 property",
  gsc_clicks: "Search Console clicks",
  gsc_impressions: "Search Console impressions",
  gsc_ctr: "Search Console CTR",
  gsc_avg_position: "Search Console average position",
  se_visibility_end: "SE Ranking visibility",
  se_avg_position_end: "SE Ranking average position",
  se_top10_end: "SE Ranking top 10",
  organic_cvr: "Organic CVR"
};

const VALUE_OVERRIDES: Record<string, string> = {
  api_smoke: "API smoke",
  blocked: "Blocked",
  bounded_content_validated: "Bounded content validated",
  client_comms_attention: "Client comms attention",
  client_monthly_comparison: "Client monthly comparison",
  client_monthly_performance_history: "Client monthly performance history",
  client_task_status: "Client task status",
  critical_missing: "Critical",
  drive_mcp_file_metadata: "Drive file metadata",
  drive_mcp_folder_metadata: "Drive folder metadata",
  in_progress: "In progress",
  local_content: "Local content",
  metadata_verified: "Metadata verified",
  missing_core_metrics: "Missing core metrics",
  needs_attention: "Needs attention",
  not_started: "Not started",
  on_track: "On track",
  partial_scope: "Partial scope",
  route_config: "Route configured",
  seo_workflow: "SEO workflow",
  sidecar_or_reporting_board_id: "Sidecar or reporting board ID",
  sidecar_or_reporting_property: "Sidecar or reporting property",
  sidecar_or_reporting_se_ranking_project: "Sidecar or reporting SE Ranking project",
  warehouse_derived: "Warehouse derived"
};

export function cn(...inputs: ClassValue[]) {
  return clsx(inputs);
}

function titleCaseToken(token: string) {
  const lower = token.toLowerCase();
  if (LABEL_OVERRIDES[lower]) return LABEL_OVERRIDES[lower];
  return lower.charAt(0).toUpperCase() + lower.slice(1);
}

export function humanizeLabel(value: unknown) {
  const raw = String(value ?? "").trim();
  if (!raw) return "—";
  const override = LABEL_OVERRIDES[raw.toLowerCase()] ?? VALUE_OVERRIDES[raw.toLowerCase()];
  if (override) return override;
  return raw
    .replace(/([a-z0-9])([A-Z])/g, "$1 $2")
    .replace(/[_-]+/g, " ")
    .split(/\s+/)
    .filter(Boolean)
    .map(titleCaseToken)
    .join(" ");
}

export function humanizeValue(value: unknown) {
  if (value === null || value === undefined || value === "") return "—";
  if (typeof value === "boolean") return value ? "Yes" : "No";
  const raw = String(value);
  const lower = raw.toLowerCase();
  if (VALUE_OVERRIDES[lower] || LABEL_OVERRIDES[lower]) return VALUE_OVERRIDES[lower] ?? LABEL_OVERRIDES[lower];
  if (/^\d{4}-\d{2}(?:-\d{2})?$/.test(raw)) return raw;
  if (/^https?:\/\//i.test(raw) || raw.includes("/") || raw.includes("@")) return raw;
  if (/^[a-z_]+\.[a-z0-9_]+$/i.test(raw)) {
    return raw.split(".").map(humanizeLabel).join(" · ");
  }
  if (/^[a-z0-9]+(?:[_-][a-z0-9]+)+$/i.test(raw)) return humanizeLabel(raw);
  return raw;
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

export function toneLabel(tone: string | undefined) {
  if (!tone || tone === "neutral") return "Info";
  return humanizeValue(tone);
}

export function statusTone(status: unknown) {
  const value = String(status ?? "").toLowerCase();
  if (["healthy", "ready", "complete", "green", "strong", "succeeded", "success", "ok", "on_track"].includes(value)) return "success";
  if (["watch", "partial", "mixed"].includes(value)) return "warning";
  if (["needs_attention", "amber", "missing", "blocked", "failed", "error"].includes(value)) return "danger";
  if (["critical", "critical_missing", "red"].includes(value)) return "critical";
  return "neutral";
}
