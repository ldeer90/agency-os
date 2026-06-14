import { useEffect, useMemo, useState } from "react";
import {
  Activity,
  BarChart3,
  Bot,
  BriefcaseBusiness,
  CalendarClock,
  DatabaseZap,
  ExternalLink,
  FileCheck2,
  HeartPulse,
  MessageSquareWarning,
  RefreshCw,
  Route,
  Users
} from "lucide-react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Legend,
  Line,
  LineChart,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis
} from "recharts";
import { DataTable } from "./components/DataTable";
import { Badge, Button, MetricCard, Panel } from "./components/Ui";
import { formatMelbourneDateTime, formatNumber, formatPercent, MELBOURNE_TIME_ZONE, statusTone } from "./lib/utils";
import type { AgentActivitySummary, ClientDetail, DashboardPayload, Row } from "./types/dashboard";

const API_URL = "http://127.0.0.1:8787/api/dashboard";

const nav = [
  { id: "overview", label: "Overview", icon: HeartPulse },
  { id: "clients", label: "Clients", icon: Users },
  { id: "timeline", label: "Timeline", icon: CalendarClock },
  { id: "delivery", label: "Delivery", icon: BriefcaseBusiness },
  { id: "performance", label: "Performance", icon: BarChart3 },
  { id: "comms", label: "Comms", icon: MessageSquareWarning },
  { id: "roadmaps", label: "Roadmaps", icon: Route },
  { id: "reporting", label: "Reporting", icon: FileCheck2 },
  { id: "agents", label: "Agents", icon: Bot },
  { id: "data", label: "Data Health", icon: DatabaseZap }
];

type Drilldown = {
  view: string;
  focus?: string;
  label?: string;
  clientSlug?: string;
  filters?: Record<string, string>;
};

function colorForStatus(status: unknown) {
  const tone = statusTone(status);
  if (tone === "success") return "#059669";
  if (tone === "warning") return "#d97706";
  if (tone === "danger") return "#e11d48";
  if (tone === "critical") return "#b91c1c";
  return "#64748b";
}

function countBy(rows: Row[], key: string) {
  const counts = new Map<string, number>();
  rows.forEach((row) => {
    const label = String(row[key] ?? "unknown");
    counts.set(label, (counts.get(label) ?? 0) + 1);
  });
  return Array.from(counts, ([name, value]) => ({ name, value }));
}

function uniqueValues(rows: Row[], key: string) {
  return Array.from(new Set(rows.map((row) => String(row[key] ?? "")).filter(Boolean))).sort();
}

function text(value: unknown) {
  if (value === null || value === undefined || value === "") return "—";
  if (typeof value === "boolean") return value ? "Yes" : "No";
  return String(value);
}

function drilldownLabel(drilldown?: Drilldown | null) {
  if (!drilldown) return "";
  if (drilldown.label) return drilldown.label;
  const focus = String(drilldown.focus ?? "details").replaceAll("_", " ");
  return `Showing: ${focus}`;
}

function monthKey(row: Row) {
  const explicit = String(row.month_tab ?? row.period_id ?? "").slice(0, 7);
  if (/^\d{4}-\d{2}$/.test(explicit)) return explicit;
  const fromMonth = String(row.report_month ?? "").slice(0, 7);
  return /^\d{4}-\d{2}$/.test(fromMonth) ? fromMonth : "";
}

function monthLabel(key: string) {
  if (!/^\d{4}-\d{2}$/.test(key)) return text(key);
  const [year, month] = key.split("-");
  const date = new Date(Number(year), Number(month) - 1, 1);
  return date.toLocaleDateString("en-AU", { month: "long", year: "numeric", timeZone: MELBOURNE_TIME_ZONE });
}

function numberValue(value: unknown) {
  const numeric = Number(value);
  return Number.isFinite(numeric) ? numeric : 0;
}

const chartColors = ["#2563eb", "#059669", "#d97706", "#dc2626", "#7c3aed", "#0891b2", "#65a30d", "#db2777", "#475569"];

const performanceMetricDefs = [
  { key: "organic_sessions", label: "Organic sessions", kind: "number" },
  { key: "organic_users", label: "Organic users", kind: "number" },
  { key: "organic_revenue", label: "Organic revenue", kind: "currency" },
  { key: "organic_conversion_rate", label: "Organic CVR", kind: "percent" },
  { key: "ai_sessions", label: "AI sessions", kind: "number" },
  { key: "gsc_clicks", label: "GSC clicks", kind: "number" },
  { key: "gsc_impressions", label: "GSC impressions", kind: "number" },
  { key: "gsc_ctr", label: "GSC CTR", kind: "percent" },
  { key: "gsc_avg_position", label: "GSC avg position", kind: "decimal" },
  { key: "se_visibility_end", label: "SE visibility", kind: "decimal" },
  { key: "se_top10_end", label: "SE top 10", kind: "number" },
  { key: "se_avg_position_end", label: "SE avg position", kind: "decimal" }
] as const;

function clientPerformanceHistory(rows: Row[]): Row[] {
  const byPeriod = new Map<string, Row>();
  rows.forEach((row) => {
    const period = String(row.period_id ?? "");
    const slug = String(row.client_slug ?? "");
    if (!period) return;
    const current = byPeriod.get(period) ?? { period_id: period };
    if (slug) current[slug] = numberValue(row.organic_sessions);
    byPeriod.set(period, current);
  });
  return Array.from(byPeriod.values()).sort((a, b) => String(a.period_id).localeCompare(String(b.period_id)));
}

function clientRows(rows: Row[], clientSlug: string) {
  return rows
    .filter((row) => row.client_slug === clientSlug)
    .sort((a, b) => String(a.period_id ?? "").localeCompare(String(b.period_id ?? "")));
}

function samePeriodLastYear(period: string) {
  const [year, month] = period.split("-");
  const numericYear = Number(year);
  if (!Number.isFinite(numericYear) || !month) return "";
  return `${numericYear - 1}-${month}`;
}

function hasMetricValue(value: unknown) {
  return value !== null && value !== undefined && value !== "" && Number.isFinite(Number(value));
}

function formatMetricValue(value: unknown, kind: string) {
  if (!hasMetricValue(value)) return "—";
  const numeric = Number(value);
  if (kind === "currency") {
    return new Intl.NumberFormat(undefined, { style: "currency", currency: "AUD", maximumFractionDigits: 0 }).format(numeric);
  }
  if (kind === "percent") return formatPercent(numeric);
  if (kind === "decimal") return numeric.toFixed(1);
  return formatNumber(numeric);
}

function formatChange(current: unknown, comparison: unknown) {
  if (!hasMetricValue(current) || !hasMetricValue(comparison)) return "—";
  const currentValue = Number(current);
  const comparisonValue = Number(comparison);
  if (comparisonValue === 0) return currentValue === 0 ? "0.0%" : "new";
  const delta = ((currentValue - comparisonValue) / Math.abs(comparisonValue)) * 100;
  const sign = delta > 0 ? "+" : "";
  return `${sign}${delta.toFixed(1)}%`;
}

function performanceSummaryForClient(client: Row, rows: Row[]) {
  const sortedRows = clientRows(rows, String(client.client_slug ?? ""));
  const latest = sortedRows[sortedRows.length - 1];
  const previous = sortedRows[sortedRows.length - 2];
  const yoy = latest ? sortedRows.find((row) => row.period_id === samePeriodLastYear(String(latest.period_id ?? ""))) : undefined;
  const summary: Row = {
    client_slug: client.client_slug,
    client_name: client.client_name,
    favicon_url: client.favicon_url,
    favicon_source: client.favicon_source,
    favicon_candidates_json: client.favicon_candidates_json,
    latest_month: latest?.period_id ?? "—"
  };
  performanceMetricDefs.forEach((metric) => {
    summary[metric.key] = formatMetricValue(latest?.[metric.key], metric.kind);
    summary[`${metric.key}_mom`] = formatChange(latest?.[metric.key], previous?.[metric.key]);
    summary[`${metric.key}_yoy`] = formatChange(latest?.[metric.key], yoy?.[metric.key]);
  });
  return summary;
}

function performanceMetricSummaryRows(rows: Row[]) {
  const sortedRows = [...rows].sort((a, b) => String(a.period_id ?? "").localeCompare(String(b.period_id ?? "")));
  const latest = sortedRows[sortedRows.length - 1];
  const previous = sortedRows[sortedRows.length - 2];
  const yoy = latest ? sortedRows.find((row) => row.period_id === samePeriodLastYear(String(latest.period_id ?? ""))) : undefined;
  return performanceMetricDefs.map((metric) => ({
    metric: metric.label,
    latest_month: latest?.period_id ?? "—",
    latest: formatMetricValue(latest?.[metric.key], metric.kind),
    mom: formatChange(latest?.[metric.key], previous?.[metric.key]),
    yoy: formatChange(latest?.[metric.key], yoy?.[metric.key]),
    source: "client_monthly_performance_history"
  }));
}

function latestPeriod(rows: Row[]) {
  return rows.reduce((latest, row) => {
    const period = String(row.period_id ?? "");
    return period > latest ? period : latest;
  }, "");
}

function percentScore(value: unknown) {
  if (value === null || value === undefined || value === "") return "—";
  const numeric = Number(value);
  if (!Number.isFinite(numeric)) return "—";
  return `${Math.round(numeric)}/100`;
}

function faviconCandidates(row?: Row) {
  const candidates = row?.favicon_candidates_json;
  const output: string[] = [];
  const push = (candidate: unknown) => {
    if (typeof candidate === "string" && candidate.trim()) output.push(candidate.trim());
  };
  if (Array.isArray(candidates)) {
    candidates.forEach(push);
  } else if (typeof candidates === "string" && candidates.trim()) {
    try {
      const parsed = JSON.parse(candidates);
      if (Array.isArray(parsed)) {
        parsed.forEach(push);
      }
    } catch {
      push(candidates);
    }
  }
  const primary = String(row?.favicon_url ?? "");
  if (primary.trim()) output.unshift(primary.trim());
  const canonicalHost = String(row?.canonical_host ?? "").replace(/^https?:\/\//, "").split("/")[0].trim();
  if (canonicalHost) {
    output.push(`https://www.google.com/s2/favicons?domain=${canonicalHost}&sz=64`);
    output.push(`https://icons.duckduckgo.com/ip3/${canonicalHost}.ico`);
  }
  return Array.from(new Set(output));
}

function FaviconMark({ row, className = "" }: { row?: Row; className?: string }) {
  const candidates = faviconCandidates(row);
  const [candidateIndex, setCandidateIndex] = useState(0);
  const src = candidates[candidateIndex] ?? "";
  const name = String(row?.client_name ?? row?.client_slug ?? "Client");
  const initial = name.trim().charAt(0).toUpperCase() || "C";
  if (!src) {
    return <span className={`flex h-7 w-7 shrink-0 items-center justify-center rounded-md bg-slate-100 text-xs font-semibold text-slate-600 ring-1 ring-slate-200 ${className}`}>{initial}</span>;
  }
  return (
    <span className={`flex h-7 w-7 shrink-0 items-center justify-center rounded-md bg-slate-100 ring-1 ring-slate-200 ${className}`}>
      <img
        src={src}
        alt=""
        className="h-5 w-5 rounded-sm object-contain"
        loading="lazy"
        onError={() => setCandidateIndex((index) => Math.min(index + 1, candidates.length))}
      />
    </span>
  );
}

function FocusBanner({ drilldown, onClear }: { drilldown?: Drilldown | null; onClear: () => void }) {
  if (!drilldown) return null;
  return (
    <div className="flex flex-col gap-2 rounded-md border border-blue-200 bg-blue-50 px-3 py-2 text-sm text-blue-900 sm:flex-row sm:items-center sm:justify-between">
      <span className="font-medium">{drilldownLabel(drilldown)}</span>
      <Button className="h-8 border-blue-200 bg-white text-blue-800 hover:bg-blue-50" onClick={onClear}>Clear filter</Button>
    </div>
  );
}

function App() {
  const [payload, setPayload] = useState<DashboardPayload | null>(null);
  const [active, setActive] = useState("overview");
  const [selectedClient, setSelectedClient] = useState<string | null>(null);
  const [drilldown, setDrilldown] = useState<Drilldown | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  function selectNav(view: string) {
    setActive(view);
    setDrilldown(null);
  }

  function navigateToDrilldown(nextDrilldown: Drilldown) {
    setActive(nextDrilldown.view);
    setDrilldown(nextDrilldown);
    if (nextDrilldown.clientSlug) setSelectedClient(nextDrilldown.clientSlug);
  }

  async function load(forceRefresh = false) {
    setLoading(true);
    setError(null);
    try {
      const response = await fetch(forceRefresh ? `${API_URL}?refresh=1` : API_URL);
      if (!response.ok) {
        const body = await response.json().catch(() => null);
        throw new Error(body?.error ?? `API returned ${response.status}`);
      }
      const nextPayload = await response.json();
      setPayload(nextPayload);
      const firstClient = nextPayload.clients?.[0]?.client_slug;
      if (!selectedClient && firstClient) setSelectedClient(String(firstClient));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Dashboard API unavailable");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void load();
  }, []);

  const healthDistribution = useMemo(() => countBy(payload?.clients ?? [], "health_status"), [payload]);
  const componentRows = useMemo(
    () => Object.entries(payload?.overview.components ?? {}).map(([name, score]) => ({ name: name.replaceAll("_", " "), score })),
    [payload]
  );

  if (error) {
    return (
      <main className="flex min-h-screen items-center justify-center bg-slate-50 p-6">
        <Panel className="max-w-xl">
          <h1 className="text-lg font-semibold text-slate-950">Dashboard API unavailable</h1>
          <p className="mt-2 text-sm text-slate-600">{error}</p>
          <p className="mt-2 text-sm text-slate-600">Run `.venv/bin/python -m dashboard.api.server` from the project root, then refresh.</p>
          <Button className="mt-4" onClick={() => load()}>Retry</Button>
        </Panel>
      </main>
    );
  }

  return (
    <div className="min-h-screen bg-slate-50 text-slate-950">
      <aside className="fixed inset-y-0 left-0 hidden w-60 border-r border-slate-200 bg-white p-3 lg:block">
        <div className="flex h-12 items-center gap-2 px-2 font-semibold">
          <Activity className="h-5 w-5 text-blue-700" />
          Agency Health
        </div>
        <nav className="mt-4 space-y-1">
          {nav.map((item) => {
            const Icon = item.icon;
            return (
              <button key={item.id} onClick={() => selectNav(item.id)} className={`flex w-full items-center gap-2 rounded-md px-3 py-2 text-left text-sm font-medium ${active === item.id ? "bg-blue-50 text-blue-800" : "text-slate-700 hover:bg-slate-100"}`}>
                <Icon className="h-4 w-4" />
                {item.label}
              </button>
            );
          })}
        </nav>
      </aside>

      <div className="lg:pl-60">
        <header className="sticky top-0 z-10 border-b border-slate-200 bg-white/95 px-4 py-3 backdrop-blur">
          <div className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
            <div>
              <h1 className="text-xl font-semibold">Agency Health Dashboard</h1>
              <p className="text-sm text-slate-500">
                {payload?.meta.environment ?? "Loading"} · {formatMelbourneDateTime(payload?.meta.generated_at)}
              </p>
            </div>
            <div className="flex flex-wrap items-center gap-2">
              {payload && <Badge tone="success">{payload.meta.data_source_status}</Badge>}
              <Button onClick={() => load(true)} disabled={loading}><RefreshCw className="mr-2 h-4 w-4" />Refresh</Button>
            </div>
          </div>
        </header>

        <main className="p-4 md:p-6">
          {loading || !payload ? <Panel>Loading dashboard…</Panel> : (
            <>
              <div className="mb-4 grid grid-cols-2 gap-2 lg:hidden">
                {nav.map((item) => <Button key={item.id} onClick={() => selectNav(item.id)} className={active === item.id ? "bg-blue-50 text-blue-800" : ""}>{item.label}</Button>)}
              </div>
              {active === "overview" && <Overview payload={payload} healthDistribution={healthDistribution} componentRows={componentRows} onDrilldown={navigateToDrilldown} />}
              {active === "clients" && <ClientsView payload={payload} selectedClient={selectedClient} onSelectClient={setSelectedClient} drilldown={drilldown?.view === "clients" ? drilldown : null} onClearDrilldown={() => setDrilldown(null)} />}
              {active === "timeline" && <TimelineView payload={payload} />}
              {active === "delivery" && <DeliveryView payload={payload} drilldown={drilldown?.view === "delivery" ? drilldown : null} onClearDrilldown={() => setDrilldown(null)} />}
              {active === "performance" && <PerformanceView payload={payload} />}
              {active === "comms" && <div className="space-y-4"><FocusBanner drilldown={drilldown?.view === "comms" ? drilldown : null} onClear={() => setDrilldown(null)} /><TableView title="Comms Attention" rows={payload.comms} columns={["week_start", "client_slug", "signal_type", "severity", "channel", "category", "summary", "recommended_action", "owner_hint"]} clientRows={payload.clients} /></div>}
              {active === "roadmaps" && <RoadmapsView payload={payload} drilldown={drilldown?.view === "roadmaps" ? drilldown : null} onClearDrilldown={() => setDrilldown(null)} />}
              {active === "reporting" && <ReportingView payload={payload} drilldown={drilldown?.view === "reporting" ? drilldown : null} onClearDrilldown={() => setDrilldown(null)} />}
              {active === "agents" && <AgentsView summaries={payload.agent_activity_summary ?? []} completedWork={payload.agent_work_completed ?? []} rawRuns={payload.agents} clientRows={payload.clients} drilldown={drilldown?.view === "agents" ? drilldown : null} onClearDrilldown={() => setDrilldown(null)} />}
              {active === "data" && <DataHealth payload={payload} drilldown={drilldown?.view === "data" ? drilldown : null} onClearDrilldown={() => setDrilldown(null)} />}
            </>
          )}
        </main>
      </div>
    </div>
  );
}

function componentDrilldown(name: unknown): Drilldown {
  const normalized = String(name ?? "").toLowerCase().replaceAll(" ", "_");
  if (normalized.includes("delivery")) return { view: "delivery", focus: "open_tasks", label: "Showing: Delivery details" };
  if (normalized.includes("comms")) return { view: "comms", focus: "attention", label: "Showing: Comms attention" };
  if (normalized.includes("roadmap")) return { view: "roadmaps", focus: "health", label: "Showing: Roadmap health details" };
  if (normalized.includes("report")) return { view: "reporting", focus: "readiness", label: "Showing: Reporting details" };
  if (normalized.includes("performance")) return { view: "performance", focus: "summary", label: "Showing: Performance details" };
  if (normalized.includes("data")) return { view: "data", focus: "health", label: "Showing: Data health details" };
  return { view: "clients", focus: "all", label: "Showing: Client health details" };
}

function actionRowDrilldown(row: Row): Drilldown {
  const area = String(row.area ?? "").toLowerCase();
  const clientSlug = String(row.client_slug ?? "");
  if (area.includes("delivery")) return { view: "delivery", focus: "open_tasks", clientSlug, label: clientSlug ? `Showing: Delivery tasks for ${clientSlug}` : "Showing: Delivery tasks" };
  if (area.includes("drive") || area.includes("roadmap")) return { view: "roadmaps", focus: area.includes("drive") ? "drive_evidence" : "missing_roadmaps", clientSlug, label: clientSlug ? `Showing: Roadmap evidence for ${clientSlug}` : "Showing: Roadmap evidence" };
  if (area.includes("workflow")) return { view: "roadmaps", focus: "workflow_gaps", clientSlug, label: clientSlug ? `Showing: Workflow readiness for ${clientSlug}` : "Showing: Workflow readiness gaps" };
  if (area.includes("crawl")) return { view: "data", focus: "crawl_latest", clientSlug, label: clientSlug ? `Showing: Crawl data for ${clientSlug}` : "Showing: Technical crawl data" };
  if (area.includes("comms")) return { view: "comms", focus: "attention", clientSlug, label: clientSlug ? `Showing: Comms for ${clientSlug}` : "Showing: Comms attention" };
  return { view: "clients", focus: "health", clientSlug, label: clientSlug ? `Showing: Client health for ${clientSlug}` : "Showing: Client health details" };
}

function Overview({ payload, healthDistribution, componentRows, onDrilldown }: { payload: DashboardPayload; healthDistribution: Array<{ name: string; value: number }>; componentRows: Array<{ name: string; score: number }>; onDrilldown: (drilldown: Drilldown) => void }) {
  const details = payload.overview_details;
  const missingAssetRows = details?.missing_assets_by_type ?? [];
  const latestReports = payload.report_links?.slice(0, 6) ?? [];
  const agentRuns = details?.recent_agent_runs ?? 0;
  const roadmapCoverage = details?.roadmap_coverage;
  const roadmapScores = payload.overview.component_details?.roadmaps ?? {};
  const blockedWorkflows = payload.workflow_readiness?.filter((row) => ["blocked", "needs_attention", "partial"].includes(String(row.readiness_status ?? "").toLowerCase())).length ?? 0;
  const crawlRows = payload.crawl_latest?.length ?? 0;
  return (
    <div className="space-y-4">
      <section className="grid gap-4 xl:grid-cols-[1.1fr_1fr]">
        <Panel>
          <div className="flex flex-col gap-4 md:flex-row md:items-center md:justify-between">
            <div>
              <p className="text-sm font-medium text-slate-500">Overall agency health</p>
              <div className="mt-2 flex items-end gap-3">
                <span className="text-6xl font-semibold tracking-normal">{payload.overview.score}</span>
                <span className="pb-2 text-lg text-slate-500">/100</span>
              </div>
              <div className="mt-3"><Badge tone={payload.overview.tone}>{payload.overview.status}</Badge></div>
            </div>
            <div className="h-56 min-w-0 flex-1">
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={componentRows} margin={{ top: 14, right: 10, bottom: 0, left: 0 }}>
                  <CartesianGrid strokeDasharray="3 3" vertical={false} />
                  <XAxis dataKey="name" tick={{ fontSize: 11 }} interval={0} angle={-18} textAnchor="end" height={70} />
                  <YAxis domain={[0, 100]} />
                  <Tooltip />
                  <Bar dataKey="score" radius={[4, 4, 0, 0]} fill="#2563eb" cursor="pointer" onClick={(entry: { name?: unknown }) => onDrilldown(componentDrilldown(entry.name))} />
                </BarChart>
              </ResponsiveContainer>
            </div>
          </div>
        </Panel>
        <Panel>
          <div className="flex items-center justify-between">
            <h2 className="font-semibold">Client Health Distribution</h2>
            <span className="text-sm text-slate-500">client_health_check</span>
          </div>
          <div className="mt-3 h-56">
            <ResponsiveContainer width="100%" height="100%">
              <PieChart>
                <Pie data={healthDistribution} dataKey="value" nameKey="name" innerRadius={55} outerRadius={88} paddingAngle={3} cursor="pointer" onClick={(entry: { name?: unknown }) => onDrilldown({ view: "clients", focus: "health_status", filters: { health_status: String(entry.name ?? "") }, label: `Showing: ${String(entry.name ?? "Client")} clients` })}>
                  {healthDistribution.map((entry) => <Cell key={entry.name} fill={colorForStatus(entry.name)} />)}
                </Pie>
                <Tooltip />
              </PieChart>
            </ResponsiveContainer>
          </div>
        </Panel>
      </section>

      <section className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
        <MetricCard label="Clients" value={payload.clients.length} tone="neutral" source="agency_reporting.client_health_check" onClick={() => onDrilldown({ view: "clients", focus: "all", label: "Showing: All clients" })} />
        <MetricCard label="Missing Health Checks" value={payload.health_assets?.filter((row) => row.expected && row.presence_status !== "present").length ?? 0} tone={missingAssetRows.length ? "warning" : "success"} source="agency_memory.client_health_assets" onClick={() => onDrilldown({ view: "clients", focus: "missing_assets", label: "Showing: Missing health assets" })} />
        <MetricCard label="Roadmap Score" value={percentScore(payload.overview.components.roadmaps)} tone={payload.overview.components.roadmaps >= 70 ? "success" : payload.overview.components.roadmaps >= 45 ? "warning" : "danger"} source="coverage + evidence + completion + risk" onClick={() => onDrilldown({ view: "roadmaps", focus: "health", label: "Showing: Roadmap health score" })} />
        <MetricCard label="Roadmap Gaps" value={details?.roadmap_gap_clients?.length ?? 0} tone={(details?.roadmap_gap_clients?.length ?? 0) ? "warning" : "success"} source="missing evidence or validation" onClick={() => onDrilldown({ view: "roadmaps", focus: "missing_roadmaps", label: "Showing: Missing or unverified roadmaps" })} />
        <MetricCard label="Report Gaps" value={details?.report_gap_clients?.length ?? 0} tone={(details?.report_gap_clients?.length ?? 0) ? "warning" : "success"} source="agency_memory.monthly_report_snapshots" onClick={() => onDrilldown({ view: "reporting", focus: "missing_reports", label: "Showing: Missing report links" })} />
        <MetricCard label="Open Delivery" value={payload.delivery.length} tone={payload.delivery.length > 10 ? "warning" : "neutral"} source="agency_reporting.client_task_status" onClick={() => onDrilldown({ view: "delivery", focus: "open_tasks", label: "Showing: Open delivery tasks" })} />
        <MetricCard label="Comms Queue" value={payload.comms.length} tone={payload.comms.length ? "warning" : "success"} source="agency_reporting.client_comms_attention" onClick={() => onDrilldown({ view: "comms", focus: "attention", label: "Showing: Comms attention queue" })} />
        <MetricCard label="Recent Agent Runs" value={agentRuns} tone="neutral" source="agent run logs" onClick={() => onDrilldown({ view: "agents", focus: "recent_runs", label: "Showing: Recent agent runs" })} />
        <MetricCard label="Agent Work Done" value={payload.agent_work_completed?.length ?? 0} tone="success" source="completed agent runs" onClick={() => onDrilldown({ view: "agents", focus: "completed", label: "Showing: Completed agent work" })} />
        <MetricCard label="SEO Opportunities" value={payload.seo_opportunities?.length ?? 0} tone={(payload.seo_opportunities?.length ?? 0) ? "warning" : "neutral"} source="agency_reporting.seo_opportunity_queue" onClick={() => onDrilldown({ view: "roadmaps", focus: "seo_opportunities", label: "Showing: SEO opportunities" })} />
        <MetricCard label="Workflow Gaps" value={blockedWorkflows} tone={blockedWorkflows ? "warning" : "success"} source="agency_reporting.seo_workflow_readiness" onClick={() => onDrilldown({ view: "roadmaps", focus: "workflow_gaps", label: "Showing: Workflow readiness gaps" })} />
        <MetricCard label="Crawled Clients" value={`${crawlRows}/${payload.clients.length}`} tone={crawlRows >= payload.clients.length ? "success" : "warning"} source="agency_reporting.client_crawl_latest" onClick={() => onDrilldown({ view: "data", focus: "crawl_latest", label: "Showing: Latest technical crawls" })} />
        <MetricCard label="Cost Failures" value={payload.data_health.cost_failures ?? 0} tone={(payload.data_health.cost_failures ?? 0) ? "danger" : "success"} source="agency_control.cost_checks" onClick={() => onDrilldown({ view: "data", focus: "cost_failures", label: "Showing: Cost check failures" })} />
      </section>

      <section className="grid gap-4 xl:grid-cols-2">
        <Panel>
          <div className="mb-3 flex items-center justify-between">
            <h2 className="font-semibold">Roadmap Health Explained</h2>
            <span className="text-sm text-slate-500">balanced score</span>
          </div>
          <div className="grid gap-3 sm:grid-cols-2">
            <MiniStat label="Coverage" value={percentScore(roadmapScores.coverage)} detail={`${roadmapCoverage?.clients_with_items ?? 0}/${roadmapCoverage?.clients_total ?? 0} clients have items`} tone={statusTone((roadmapScores.coverage ?? 0) >= 85 ? "healthy" : "watch")} onClick={() => onDrilldown({ view: "roadmaps", focus: "all_items", label: "Showing: All roadmap items" })} />
            <MiniStat label="Evidence" value={percentScore(roadmapScores.evidence)} detail={`${roadmapCoverage?.clients_with_validated_content ?? 0}/${roadmapCoverage?.clients_total ?? 0} clients validated`} tone={statusTone((roadmapScores.evidence ?? 0) >= 85 ? "healthy" : "needs_attention")} onClick={() => onDrilldown({ view: "roadmaps", focus: "drive_evidence", label: "Showing: Drive evidence metadata" })} />
            <MiniStat label="Completion" value={percentScore(roadmapScores.completion)} detail={`${roadmapCoverage?.monthly_rollups ?? 0} monthly rollups`} tone={statusTone((roadmapScores.completion ?? 0) >= 70 ? "healthy" : "needs_attention")} onClick={() => onDrilldown({ view: "roadmaps", focus: "monthly_rollup", label: "Showing: Monthly roadmap rollup" })} />
            <MiniStat label="Risk" value={percentScore(roadmapScores.risk)} detail={`${roadmapCoverage?.missing_evidence_items ?? 0} missing evidence, ${roadmapCoverage?.overdue_items ?? 0} overdue`} tone={statusTone((roadmapScores.risk ?? 0) >= 85 ? "healthy" : "watch")} onClick={() => onDrilldown({ view: "roadmaps", focus: "missing_roadmaps", label: "Showing: Roadmap risk details" })} />
          </div>
        </Panel>
        <Panel>
          <div className="mb-3 flex items-center justify-between">
            <h2 className="font-semibold">Today Action Queue</h2>
            <span className="text-sm text-slate-500">health, delivery, Drive, workflow, crawl</span>
          </div>
          <DataTable rows={payload.needs_attention} columns={["severity", "area", "client_slug", "summary", "source"]} emptyLabel="No attention items." clientRows={payload.clients} onRowClick={(row) => onDrilldown(actionRowDrilldown(row))} rowAriaLabel={(row) => `Open ${text(row.area)} details for ${text(row.client_slug)}`} />
        </Panel>
        <Panel>
          <div className="mb-3 flex items-center justify-between">
            <h2 className="font-semibold">Missing Health Assets</h2>
            <span className="text-sm text-slate-500">by asset type</span>
          </div>
          <DataTable rows={missingAssetRows} columns={["name", "value"]} emptyLabel="No missing expected assets." />
        </Panel>
      </section>

      <Panel>
        <div className="mb-3 flex items-center justify-between">
          <h2 className="font-semibold">Latest Report Records</h2>
          <span className="text-sm text-slate-500">agency_memory.monthly_report_snapshots</span>
        </div>
        <DataTable rows={latestReports} columns={["report_month", "client_slug", "share_id", "report_path", "generated_at", "template"]} emptyLabel="No report records." clientRows={payload.clients} onRowClick={(row) => onDrilldown({ view: "reporting", focus: "report_records", clientSlug: String(row.client_slug ?? ""), filters: { month: monthKey(row) }, label: `Showing: Report record for ${text(row.client_slug)}` })} rowAriaLabel={(row) => `Open report details for ${text(row.client_slug)}`} />
      </Panel>
    </div>
  );
}

function MiniStat({ label, value, detail, tone, onClick }: { label: string; value: React.ReactNode; detail: string; tone?: string; onClick?: () => void }) {
  const content = (
    <>
      <div className="flex items-center justify-between gap-2">
        <p className="text-sm font-medium text-slate-600">{label}</p>
        <Badge tone={tone}>{tone === "success" ? "ok" : "watch"}</Badge>
      </div>
      <p className="mt-2 text-2xl font-semibold text-slate-950">{value}</p>
      <p className="mt-1 text-xs text-slate-500">{detail}</p>
    </>
  );
  if (onClick) {
    return (
      <button type="button" className="rounded-md border border-slate-200 bg-slate-50 p-3 text-left transition hover:border-blue-300 hover:bg-blue-50 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:ring-offset-2" onClick={onClick} aria-label={`Open ${label} details`}>
        {content}
      </button>
    );
  }
  return (
    <div className="rounded-md border border-slate-200 bg-slate-50 p-3">
      {content}
    </div>
  );
}

function ClientsView({ payload, selectedClient, onSelectClient, drilldown, onClearDrilldown }: { payload: DashboardPayload; selectedClient: string | null; onSelectClient: (slug: string) => void; drilldown?: Drilldown | null; onClearDrilldown: () => void }) {
  const visibleClients = payload.clients.filter((client) => {
    if (drilldown?.clientSlug && client.client_slug !== drilldown.clientSlug) return false;
    if (drilldown?.focus === "health_status" && drilldown.filters?.health_status && String(client.health_status ?? "") !== drilldown.filters.health_status) return false;
    if (drilldown?.focus === "missing_assets" && !numberValue(client.missing_required_assets) && !numberValue(client.critical_missing_assets)) return false;
    return true;
  });
  const details = selectedClient ? payload.client_details?.[selectedClient] : undefined;
  return (
    <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_390px]">
      <Panel>
        <div className="mb-3 flex items-center justify-between">
          <h2 className="text-lg font-semibold">Clients</h2>
          <span className="text-sm text-slate-500">{formatNumber(visibleClients.length)} clients</span>
        </div>
        <FocusBanner drilldown={drilldown} onClear={onClearDrilldown} />
        <div className="grid gap-1.5 sm:grid-cols-2 2xl:grid-cols-3">
          {visibleClients.map((client) => {
            const slug = String(client.client_slug);
            return (
              <button key={slug} onClick={() => onSelectClient(slug)} className={`min-h-[74px] rounded-md border px-2.5 py-2 text-left transition ${selectedClient === slug ? "border-blue-300 bg-blue-50" : "border-slate-200 bg-white hover:bg-slate-50"}`}>
                <div className="flex items-start gap-2">
                  <FaviconMark row={client} />
                  <div className="min-w-0 flex-1">
                    <div className="flex items-start justify-between gap-2">
                      <p className="truncate text-sm font-medium text-slate-950" title={text(client.client_name)}>{text(client.client_name)}</p>
                      <Badge tone={statusTone(client.health_status)}>{text(client.health_status).replace("critical_missing", "critical").replace("needs_attention", "watch")}</Badge>
                    </div>
                    <p className="truncate text-xs text-slate-500" title={slug}>{slug}</p>
                    <div className="mt-1 grid grid-cols-3 gap-1 text-[11px] leading-4 text-slate-600">
                      <span className="truncate">Score {formatPercent(client.health_score)}</span>
                      <span className="truncate">Missing {text(client.missing_required_assets)}</span>
                      <span className="truncate">Report {text(client.latest_report_month)}</span>
                    </div>
                  </div>
                </div>
              </button>
            );
          })}
        </div>
      </Panel>
      <ClientDetailPanel detail={details} />
    </div>
  );
}

function ClientDetailPanel({ detail }: { detail?: ClientDetail }) {
  if (!detail) return <Panel>Select a client to see health, profile, roadmap, report, performance, delivery, and comms detail.</Panel>;
  const profile = detail.profile;
  const context = detail.context;
  return (
    <Panel className="space-y-4">
      <div>
        <div className="flex items-start justify-between gap-3">
          <div className="flex min-w-0 items-start gap-2">
            <FaviconMark row={profile} className="mt-0.5" />
            <div className="min-w-0">
              <h2 className="truncate text-lg font-semibold">{text(profile.client_name)}</h2>
              <p className="text-sm text-slate-500">{text(profile.client_slug)}</p>
            </div>
          </div>
          <Badge tone={statusTone(detail.health.health_status)}>{text(detail.health.health_status)}</Badge>
        </div>
        <dl className="mt-4 grid grid-cols-2 gap-3 text-sm">
          <Info label="ABN" value={profile.abn} />
          <Info label="Contact" value={profile.primary_contact_name} />
          <Info label="Role" value={profile.primary_contact_role} />
          <Info label="Domain" value={profile.canonical_host} />
          <Info label="Monday board" value={profile.monday_board_id} />
          <Info label="GA4" value={profile.ga4_property} />
        </dl>
      </div>
      <ClientContextBlock context={context} />
      <DetailSection title="Missing Required Health Assets" rows={detail.missing_assets} columns={["asset_type", "asset_label", "presence_status", "criticality", "verification_level", "notes"]} empty="No missing expected health assets." />
      <DetailSection title="Recent Timeline" rows={detail.timeline.slice(0, 12)} columns={["event_date", "event_type", "title", "status", "summary", "agent_name", "source_table"]} empty="No timeline events found." />
      <DetailSection title="Agent Work Completed" rows={detail.agent_work.slice(0, 8)} columns={["agent_name", "task_name", "completed_at", "status", "findings_count", "actions_count", "workflow_id"]} empty="No completed agent work found for this client." />
      <DetailSection title="Reports" rows={detail.reports.slice(0, 6)} columns={["report_month", "share_id", "report_path", "generated_at", "template"]} empty="No reports found." />
      <DetailSection title="Report Narratives" rows={detail.report_narratives.slice(0, 4)} columns={["period_id", "summary", "completed_work", "next_focus", "caveats"]} empty="No report narrative rows found." />
      <DetailSection title="Roadmaps" rows={detail.roadmaps.slice(0, 8)} columns={["planned_month", "item_title", "priority", "delivery_status", "owner_hint", "due_date"]} empty={detail.roadmap_missing ? "No roadmap rows found for this client." : "No current roadmap rows."} />
      <DetailSection title="Drive Evidence" rows={detail.drive_evidence} columns={["folder_role", "verified_at", "file_count", "populated_file_count", "content_validated_file_count", "content_validation_status", "latest_modified_date"]} empty="No Drive verification metadata found." />
      <DetailSection title="Performance Trend" rows={detail.performance_history.slice(-6)} columns={["period_id", "organic_sessions", "gsc_clicks", "organic_revenue", "se_visibility_end"]} empty="No performance history." />
      <DetailSection title="SEO Opportunities And Readiness" rows={[...detail.seo_opportunities.slice(0, 4), ...detail.workflow_readiness.slice(0, 4)]} columns={["priority", "readiness_status", "workflow_id", "recommended_workflow_id", "recommended_agent_id", "summary", "recommended_action", "missing_inputs_json"]} empty="No SEO opportunity or workflow readiness rows." />
      <DetailSection title="Crawl And API Smoke" rows={[...detail.crawl_latest.slice(0, 2), ...detail.api_smoke_checks.slice(0, 6)]} columns={["crawl_date", "source", "status", "crawl_status", "pages_crawled", "rows_returned", "checked_at", "error_class"]} empty="No crawl or API smoke rows." />
      <DetailSection title="Delivery And Comms" rows={[...detail.delivery.slice(0, 4), ...detail.comms.slice(0, 4)]} columns={["item_name", "summary", "status", "severity", "owner", "due_date"]} empty="No delivery or comms items." />
    </Panel>
  );
}

function jsonList(value: unknown): string[] {
  if (Array.isArray(value)) return value.map((item) => String(item)).filter(Boolean);
  if (typeof value === "string" && value.trim()) {
    try {
      const parsed = JSON.parse(value);
      if (Array.isArray(parsed)) return parsed.map((item) => String(item)).filter(Boolean);
    } catch {
      return [value];
    }
  }
  return [];
}

function ClientContextBlock({ context }: { context?: Row }) {
  const goals = jsonList(context?.primary_goals_json);
  const priorities = jsonList(context?.seo_priorities_json);
  const products = jsonList(context?.key_products_or_services_json);
  const pages = jsonList(context?.important_pages_json);
  const risks = jsonList(context?.constraints_or_risks_json);
  if (!context) {
    return (
      <div className="rounded-md border border-dashed border-slate-300 p-4 text-sm text-slate-500">
        No reviewed client goals or priorities profile found.
      </div>
    );
  }
  return (
    <div className="rounded-md border border-slate-200 bg-slate-50 p-4">
      <div className="mb-3 flex items-start justify-between gap-3">
        <div>
          <h3 className="text-sm font-semibold text-slate-950">Client Context</h3>
          <p className="mt-1 text-sm text-slate-700">{text(context.agent_context_summary ?? context.business_summary)}</p>
        </div>
        <Badge tone={String(context.review_status) === "approved" ? "success" : "neutral"}>{text(context.review_status)}</Badge>
      </div>
      <div className="grid gap-3 text-sm">
        <ContextList title="Goals" values={goals} />
        <ContextList title="SEO Priorities" values={priorities} />
        <ContextList title="Products / Services" values={products} />
        <ContextList title="Important Pages" values={pages} />
        <ContextList title="Constraints / Risks" values={risks} />
        <dl className="grid grid-cols-2 gap-3">
          <Info label="Audience" value={context.target_audience} />
          <Info label="Brand tone" value={context.brand_tone} />
          <Info label="Approval" value={context.approval_preferences} />
          <Info label="Reporting" value={context.reporting_expectations} />
        </dl>
      </div>
    </div>
  );
}

function ContextList({ title, values }: { title: string; values: string[] }) {
  if (!values.length) return null;
  return (
    <div>
      <h4 className="text-xs font-medium uppercase text-slate-500">{title}</h4>
      <ul className="mt-1 space-y-1 text-slate-800">
        {values.map((value) => <li key={value}>{value}</li>)}
      </ul>
    </div>
  );
}

function Info({ label, value }: { label: string; value: unknown }) {
  return (
    <div>
      <dt className="text-xs font-medium uppercase text-slate-500">{label}</dt>
      <dd className="mt-1 break-words text-slate-900">{text(value)}</dd>
    </div>
  );
}

function DetailSection({ title, rows, columns, empty }: { title: string; rows: Row[]; columns: string[]; empty: string }) {
  return (
    <div>
      <h3 className="mb-2 text-sm font-semibold text-slate-900">{title}</h3>
      <DataTable rows={rows} columns={columns} emptyLabel={empty} />
    </div>
  );
}

function TimelineView({ payload }: { payload: DashboardPayload }) {
  const rows = payload.unified_timeline ?? payload.client_timeline ?? [];
  const [client, setClient] = useState("");
  const [eventType, setEventType] = useState("");
  const [status, setStatus] = useState("");
  const [fromDate, setFromDate] = useState("");
  const [toDate, setToDate] = useState("");
  const clientOptions = useMemo(() => uniqueValues(rows, "client_slug"), [rows]);
  const eventTypeOptions = useMemo(() => uniqueValues(rows, "event_type"), [rows]);
  const statusOptions = useMemo(() => uniqueValues(rows, "status"), [rows]);
  const filteredRows = rows.filter((row) => {
    const eventDate = String(row.event_date ?? "");
    if (client && row.client_slug !== client) return false;
    if (eventType && row.event_type !== eventType) return false;
    if (status && String(row.status ?? "") !== status) return false;
    if (fromDate && eventDate < fromDate) return false;
    if (toDate && eventDate > toDate) return false;
    return true;
  });
  const recentRows = rows.slice(0, 12);
  const completedCount = rows.filter((row) => String(row.event_type ?? "").includes("done") || String(row.status ?? "").toLowerCase() === "done").length;
  return (
    <div className="space-y-4">
      <section className="grid gap-4 md:grid-cols-4">
        <MetricCard label="Timeline events" value={formatNumber(rows.length)} tone="neutral" source="unified client ops timeline" />
        <MetricCard label="Clients covered" value={formatNumber(clientOptions.length)} tone="neutral" source="active client timeline rows" />
        <MetricCard label="Completed signals" value={formatNumber(completedCount)} tone={completedCount ? "success" : "neutral"} source="event type/status" />
        <MetricCard label="Filtered rows" value={formatNumber(filteredRows.length)} tone="neutral" source="current filters" />
      </section>
      <Panel>
        <div className="flex flex-col gap-3 lg:flex-row lg:items-end lg:justify-between">
          <div>
            <h2 className="text-lg font-semibold">Client Timeline Of Events</h2>
            <p className="text-sm text-slate-500">Delivery, crawls, reports, Drive evidence, agents, workflow readiness, and API checks.</p>
          </div>
          <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-5">
            <select className="h-9 rounded-md border border-slate-200 bg-white px-3 text-sm" value={client} onChange={(event) => setClient(event.target.value)}>
              <option value="">All clients</option>
              {clientOptions.map((value) => <option key={value} value={value}>{value}</option>)}
            </select>
            <select className="h-9 rounded-md border border-slate-200 bg-white px-3 text-sm" value={eventType} onChange={(event) => setEventType(event.target.value)}>
              <option value="">All event types</option>
              {eventTypeOptions.map((value) => <option key={value} value={value}>{value}</option>)}
            </select>
            <select className="h-9 rounded-md border border-slate-200 bg-white px-3 text-sm" value={status} onChange={(event) => setStatus(event.target.value)}>
              <option value="">Any status</option>
              {statusOptions.map((value) => <option key={value} value={value}>{value}</option>)}
            </select>
            <input className="h-9 rounded-md border border-slate-200 bg-white px-3 text-sm" type="date" value={fromDate} onChange={(event) => setFromDate(event.target.value)} aria-label="From date" />
            <input className="h-9 rounded-md border border-slate-200 bg-white px-3 text-sm" type="date" value={toDate} onChange={(event) => setToDate(event.target.value)} aria-label="To date" />
          </div>
        </div>
        <div className="mt-4">
          <DataTable rows={filteredRows} columns={["event_date", "client_slug", "client_name", "event_type", "title", "status", "summary", "agent_name", "source_table", "source_id"]} emptyLabel="No timeline events match the current filters." clientRows={payload.clients} />
        </div>
      </Panel>
      <TableView title="Recent Timeline Events" rows={recentRows} columns={["event_date", "client_slug", "event_type", "title", "status", "summary", "source_table"]} emptyLabel="No recent timeline events." clientRows={payload.clients} />
    </div>
  );
}

const taskStatusColors: Record<string, string> = {
  not_started_tasks: "#64748b",
  in_progress_tasks: "#2563eb",
  approval_tasks: "#d97706",
  brief_tasks: "#7c3aed",
  other_open_tasks: "#e11d48",
  done_tasks: "#059669"
};

const taskStatusLabels: Record<string, string> = {
  not_started_tasks: "Not started",
  in_progress_tasks: "In progress",
  approval_tasks: "Approval",
  brief_tasks: "Brief",
  other_open_tasks: "Other open",
  done_tasks: "Done"
};

function shortClientName(value: unknown) {
  const label = text(value);
  return label.length > 18 ? `${label.slice(0, 16)}...` : label;
}

function statusColor(label: unknown, index: number) {
  const normalized = String(label ?? "").toLowerCase();
  if (normalized.includes("done")) return "#059669";
  if (normalized.includes("progress")) return "#2563eb";
  if (normalized.includes("approval")) return "#d97706";
  if (normalized.includes("brief")) return "#7c3aed";
  if (normalized.includes("not started")) return "#64748b";
  return chartColors[index % chartColors.length];
}

function isDoneTask(row: Row) {
  const status = String(row.status_label ?? row.status ?? row.normalized_status ?? "").toLowerCase();
  return status.includes("done") || status.includes("complete");
}

function taskStatus(row: Row) {
  return String(row.status_label ?? row.status ?? row.normalized_status ?? "Not Started");
}

function taskStatusMatches(row: Row, focus?: string, statusLabel?: string) {
  const status = taskStatus(row).toLowerCase();
  if (focus === "not_started_tasks") return status === "not started";
  if (focus === "in_progress_tasks") return status === "in progress" || status.includes("working");
  if (focus === "approval_tasks") return status.includes("approval");
  if (focus === "brief_tasks") return status.includes("brief");
  if (focus === "done_tasks") return isDoneTask(row);
  if (focus === "other_open_tasks") {
    return !isDoneTask(row) && status !== "not started" && status !== "in progress" && !status.includes("working") && !status.includes("approval") && !status.includes("brief");
  }
  if (statusLabel) return status === statusLabel.toLowerCase();
  return true;
}

function deliveryFocusLabel(focus?: string, statusLabel?: string) {
  if (statusLabel) return statusLabel;
  if (!focus) return "Task";
  if (focus === "open_tasks") return "Open";
  if (focus === "overdue") return "Overdue";
  if (focus === "missing_owner") return "Missing owner";
  if (focus === "missing_due_date") return "Missing due date";
  return taskStatusLabels[focus] ?? focus.replaceAll("_", " ");
}

function chartEventRow(entry: Row) {
  return (entry?.payload as Row | undefined) ?? entry;
}

function DeliveryView({ payload, drilldown, onClearDrilldown }: { payload: DashboardPayload; drilldown?: Drilldown | null; onClearDrilldown: () => void }) {
  const [deliveryClient, setDeliveryClient] = useState("");
  const [localDrilldown, setLocalDrilldown] = useState<Drilldown | null>(null);
  const activeDrilldown = localDrilldown ?? drilldown;
  useEffect(() => {
    if (drilldown?.clientSlug) setDeliveryClient(drilldown.clientSlug);
  }, [drilldown?.clientSlug]);
  useEffect(() => {
    setLocalDrilldown(null);
  }, [drilldown]);
  function focusTasks(next: { focus: string; label: string; clientSlug?: string; statusLabel?: string }) {
    setLocalDrilldown({
      view: "delivery",
      focus: next.focus,
      clientSlug: next.clientSlug,
      filters: next.statusLabel ? { status_label: next.statusLabel } : undefined,
      label: next.label,
    });
    if (next.clientSlug) setDeliveryClient(next.clientSlug);
  }
  function clearDeliveryFocus() {
    setLocalDrilldown(null);
    onClearDrilldown();
  }
  const summary = payload.task_summary ?? {};
  const byClient = payload.task_status_by_client ?? [];
  const distribution = payload.task_status_distribution ?? [];
  const detailRows = payload.task_client_detail ?? payload.delivery;
  const visibleDetailRows = detailRows.filter((row) => {
    if (deliveryClient && row.client_slug !== deliveryClient) return false;
    if (activeDrilldown?.focus === "open_tasks" && isDoneTask(row)) return false;
    if (activeDrilldown?.focus === "overdue" && !row.is_overdue) return false;
    if (activeDrilldown?.focus === "missing_owner" && !row.owner_missing) return false;
    if (activeDrilldown?.focus === "missing_due_date" && String(row.due_state ?? "") !== "missing_due_date" && row.due_date) return false;
    if (!["open_tasks", "overdue", "missing_owner", "missing_due_date"].includes(String(activeDrilldown?.focus ?? "")) && !taskStatusMatches(row, activeDrilldown?.focus, activeDrilldown?.filters?.status_label)) return false;
    return true;
  });
  const selectedClient = payload.clients.find((client) => client.client_slug === deliveryClient);
  const overdueRows = byClient.map((row) => ({
    client_slug: row.client_slug,
    client_name: row.client_name,
    overdue_tasks: numberValue(row.overdue_tasks)
  }));
  const tableTitle = activeDrilldown ? `${deliveryFocusLabel(activeDrilldown.focus, activeDrilldown.filters?.status_label)} Task Detail` : deliveryClient ? `${text(selectedClient?.client_name)} Task Detail` : "All Client Task Detail";

  return (
    <div className="space-y-4">
      <FocusBanner drilldown={activeDrilldown} onClear={clearDeliveryFocus} />
      <section className="grid gap-4 md:grid-cols-3 xl:grid-cols-6">
        <MetricCard label="Open tasks" value={formatNumber(summary.open_tasks)} tone={numberValue(summary.open_tasks) ? "warning" : "success"} source="agency_reporting.client_task_status" onClick={() => focusTasks({ focus: "open_tasks", label: "Showing: Open delivery tasks" })} />
        <MetricCard label="Overdue" value={formatNumber(summary.overdue_tasks)} tone={numberValue(summary.overdue_tasks) ? "danger" : "success"} source="due date + non-done status" onClick={() => focusTasks({ focus: "overdue", label: "Showing: Overdue delivery tasks" })} />
        <MetricCard label="Done" value={formatNumber(summary.done_tasks)} tone="success" source="agency_reporting.client_task_status" onClick={() => focusTasks({ focus: "done_tasks", label: "Showing: Done delivery tasks" })} />
        <MetricCard label="Missing owner" value={formatNumber(summary.missing_owner_tasks)} tone={numberValue(summary.missing_owner_tasks) ? "warning" : "success"} source="owner is blank" onClick={() => focusTasks({ focus: "missing_owner", label: "Showing: Tasks missing owner" })} />
        <MetricCard label="Missing due date" value={formatNumber(summary.missing_due_date_tasks)} tone={numberValue(summary.missing_due_date_tasks) ? "warning" : "success"} source="due date is blank" onClick={() => focusTasks({ focus: "missing_due_date", label: "Showing: Tasks missing due date" })} />
        <MetricCard label="Drift issues" value={formatNumber(summary.drift_issues)} tone={numberValue(summary.drift_issues) ? "warning" : "success"} source="agency_reporting.ops_drift_summary" />
      </section>

      <Panel>
        <div className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
          <div>
            <h2 className="text-lg font-semibold">Monday Ops By Client</h2>
            <p className="text-sm text-slate-500">Active reporting clients only · BigQuery snapshots</p>
          </div>
          <div className="flex items-center gap-2">
            {selectedClient && <FaviconMark row={selectedClient} />}
            <select className="h-9 rounded-md border border-slate-200 bg-white px-3 text-sm" value={deliveryClient} onChange={(event) => setDeliveryClient(event.target.value)}>
              <option value="">All clients</option>
              {payload.clients.map((client) => <option key={String(client.client_slug)} value={String(client.client_slug)}>{text(client.client_name)}</option>)}
            </select>
          </div>
        </div>
        <div className="mt-4 grid gap-4 xl:grid-cols-[minmax(0,1.35fr)_minmax(320px,0.65fr)]">
          <div className="h-80 min-w-0">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={byClient} margin={{ top: 42, right: 18, left: 0, bottom: 66 }}>
                <CartesianGrid strokeDasharray="3 3" vertical={false} />
                <XAxis dataKey="client_name" tickFormatter={shortClientName} tick={{ fontSize: 11 }} angle={-22} textAnchor="end" interval={0} />
                <YAxis />
                <Tooltip />
                <Legend verticalAlign="top" height={28} wrapperStyle={{ fontSize: 12 }} />
                {Object.entries(taskStatusLabels).map(([key, label]) => (
                  <Bar key={key} dataKey={key} name={label} stackId="tasks" fill={taskStatusColors[key]} radius={key === "done_tasks" ? [4, 4, 0, 0] : [0, 0, 0, 0]} cursor="pointer" onClick={(entry: Row) => {
                    const row = chartEventRow(entry);
                    focusTasks({ focus: key, clientSlug: String(row.client_slug ?? ""), label: `Showing: ${label} tasks${row.client_name ? ` for ${text(row.client_name)}` : ""}` });
                  }} />
                ))}
              </BarChart>
            </ResponsiveContainer>
          </div>
          <div className="h-80 min-w-0">
            <ResponsiveContainer width="100%" height="100%">
              <PieChart>
                <Pie data={distribution} dataKey="task_count" nameKey="status_label" innerRadius={58} outerRadius={105} paddingAngle={2} cursor="pointer" onClick={(entry: Row) => focusTasks({ focus: "status_label", statusLabel: String(entry.status_label ?? ""), label: `Showing: ${text(entry.status_label)} tasks` })}>
                  {distribution.map((entry, index) => <Cell key={String(entry.status_label)} fill={statusColor(entry.status_label, index)} />)}
                </Pie>
                <Tooltip />
                <Legend verticalAlign="bottom" height={32} wrapperStyle={{ fontSize: 12 }} />
              </PieChart>
            </ResponsiveContainer>
          </div>
        </div>
      </Panel>

      <section className="grid gap-4 xl:grid-cols-2">
        <Panel>
          <div className="mb-3 flex items-center justify-between">
            <h2 className="text-lg font-semibold">Overdue By Client</h2>
            <span className="text-sm text-slate-500">non-done tasks past due</span>
          </div>
          <div className="h-72">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={overdueRows} margin={{ top: 12, right: 18, left: 0, bottom: 48 }}>
                <CartesianGrid strokeDasharray="3 3" vertical={false} />
                <XAxis dataKey="client_name" tickFormatter={shortClientName} tick={{ fontSize: 11 }} angle={-22} textAnchor="end" interval={0} />
                <YAxis allowDecimals={false} />
                <Tooltip />
                <Bar dataKey="overdue_tasks" name="Overdue tasks" fill="#dc2626" radius={[4, 4, 0, 0]} cursor="pointer" onClick={(entry: Row) => {
                  const row = chartEventRow(entry);
                  focusTasks({ focus: "overdue", clientSlug: String(row.client_slug ?? ""), label: `Showing: Overdue tasks${row.client_name ? ` for ${text(row.client_name)}` : ""}` });
                }} />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </Panel>
        <TableView title="Task Status By Client" rows={byClient} columns={["client_name", "total_tasks", "open_tasks", "done_tasks", "overdue_tasks", "missing_owner_tasks", "missing_due_date_tasks", "latest_update_at"]} emptyLabel="No task status rows found." clientRows={payload.clients} onRowClick={(row) => focusTasks({ focus: "open_tasks", clientSlug: String(row.client_slug ?? ""), label: `Showing: Open tasks${row.client_name ? ` for ${text(row.client_name)}` : ""}` })} rowAriaLabel={(row) => `Show open delivery tasks for ${text(row.client_name ?? row.client_slug)}`} />
      </section>

      <TableView title={tableTitle} rows={visibleDetailRows} columns={["client_name", "item_name", "status_label", "owner", "due_date", "due_state", "is_overdue", "board_name", "group_title", "updated_at"]} emptyLabel="No task rows found for this selection." clientRows={payload.clients} />
      <TableView title="Ops Drift" rows={payload.ops_drift ?? []} columns={["client_slug", "client_name", "alignment_rows", "status_mismatches", "owner_mismatches", "due_date_mismatches", "stale_client_updates", "drift_issues"]} emptyLabel="No ops drift rows found." clientRows={payload.clients} />
      <TableView title="Legacy Open Delivery Rows" rows={payload.delivery} columns={["client_slug", "item_name", "status", "owner", "due_date", "due_state", "is_overdue", "owner_missing"]} emptyLabel="No open delivery rows found." clientRows={payload.clients} />
    </div>
  );
}

function PerformanceView({ payload }: { payload: DashboardPayload }) {
  const [performanceClient, setPerformanceClient] = useState("");
  const history = payload.performance_history ?? [];
  const visibleClientSlugs = useMemo(() => new Set(payload.clients.map((client) => String(client.client_slug ?? "")).filter(Boolean)), [payload.clients]);
  const selectPerformanceClient = (slug: unknown) => {
    const nextSlug = String(slug ?? "");
    if (visibleClientSlugs.has(nextSlug)) setPerformanceClient(nextSlug);
  };
  const selectedHistory = performanceClient ? history.filter((row) => row.client_slug === performanceClient) : history;
  const latestRows = performanceClient ? payload.performance.filter((row) => row.client_slug === performanceClient) : payload.performance;
  const selectedLatest = latestRows[0];
  const selectedClient = payload.clients.find((client) => client.client_slug === performanceClient);
  const allClientChartRows = clientPerformanceHistory(selectedHistory);
  const allClientSummaryRows = payload.clients.map((client) => performanceSummaryForClient(client, history));
  const selectedMetricSummaryRows = performanceMetricSummaryRows(selectedHistory);
  const singleClientChartRows = selectedHistory.map((row) => ({
    period_id: row.period_id,
    organic_sessions: numberValue(row.organic_sessions),
    gsc_clicks: numberValue(row.gsc_clicks),
    organic_revenue: numberValue(row.organic_revenue),
    se_visibility_end: numberValue(row.se_visibility_end)
  }));
  const chartRows = performanceClient ? singleClientChartRows : allClientChartRows;
  const summaryColumns = [
    "client_name",
    "latest_month",
    "organic_sessions",
    "organic_sessions_mom",
    "organic_sessions_yoy",
    "organic_users",
    "organic_users_mom",
    "organic_users_yoy",
    "organic_revenue",
    "organic_revenue_mom",
    "organic_revenue_yoy",
    "organic_conversion_rate",
    "organic_conversion_rate_mom",
    "organic_conversion_rate_yoy",
    "ai_sessions",
    "ai_sessions_mom",
    "ai_sessions_yoy",
    "gsc_clicks",
    "gsc_clicks_mom",
    "gsc_clicks_yoy",
    "gsc_impressions",
    "gsc_impressions_mom",
    "gsc_impressions_yoy",
    "gsc_ctr",
    "gsc_ctr_mom",
    "gsc_ctr_yoy",
    "gsc_avg_position",
    "gsc_avg_position_mom",
    "gsc_avg_position_yoy",
    "se_visibility_end",
    "se_visibility_end_mom",
    "se_visibility_end_yoy",
    "se_top10_end",
    "se_top10_end_mom",
    "se_top10_end_yoy",
    "se_avg_position_end",
    "se_avg_position_end_mom",
    "se_avg_position_end_yoy"
  ];
  return (
    <div className="space-y-4">
      <Panel>
        <div className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
          <h2 className="text-lg font-semibold">Monthly Performance Trend</h2>
          <div className="flex items-center gap-2">
            {selectedClient && <FaviconMark row={selectedClient} />}
            <select className="h-9 rounded-md border border-slate-200 bg-white px-3 text-sm" value={performanceClient} onChange={(event) => setPerformanceClient(event.target.value)}>
              <option value="">All clients</option>
              {payload.clients.map((client) => <option key={String(client.client_slug)} value={String(client.client_slug)}>{text(client.client_name)}</option>)}
            </select>
          </div>
        </div>
        <div className="mt-4 h-80">
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={chartRows} margin={{ top: 12, right: 18, left: 0, bottom: 0 }}>
              <CartesianGrid strokeDasharray="3 3" vertical={false} />
              <XAxis dataKey="period_id" tick={{ fontSize: 12 }} />
              <YAxis />
              <Tooltip />
              <Legend
                onClick={(entry: { dataKey?: unknown }) => selectPerformanceClient(entry.dataKey)}
                wrapperStyle={!performanceClient ? { cursor: "pointer" } : undefined}
              />
              {performanceClient ? (
                <>
                  <Line type="monotone" dataKey="organic_sessions" stroke="#2563eb" dot={false} strokeWidth={2} />
                  <Line type="monotone" dataKey="gsc_clicks" stroke="#059669" dot={false} strokeWidth={2} />
                  <Line type="monotone" dataKey="se_visibility_end" stroke="#d97706" dot={false} strokeWidth={2} />
                </>
              ) : (
                payload.clients.map((client, index) => {
                  const slug = String(client.client_slug);
                  return (
                    <Line
                      key={slug}
                      type="monotone"
                      dataKey={slug}
                      name={String(client.client_name ?? slug)}
                      stroke={chartColors[index % chartColors.length]}
                      dot={false}
                      strokeWidth={2}
                      style={{ cursor: "pointer" }}
                      onClick={() => selectPerformanceClient(slug)}
                    />
                  );
                })
              )}
            </LineChart>
          </ResponsiveContainer>
        </div>
      </Panel>
      <section className="grid gap-4 md:grid-cols-3">
        {performanceClient ? (
          <>
            <MetricCard label="Latest sessions" value={formatNumber(selectedLatest?.organic_sessions)} tone="neutral" source="client_monthly_comparison" />
            <MetricCard label="Latest clicks" value={formatNumber(selectedLatest?.gsc_clicks)} tone="neutral" source="client_monthly_comparison" />
            <MetricCard label="Status" value={text(selectedLatest?.performance_status)} tone={statusTone(selectedLatest?.performance_status)} source="client_benchmark_summary" />
          </>
        ) : (
          <>
            <MetricCard label="Clients shown" value={payload.performance.length} tone="neutral" source="client_monthly_comparison" />
            <MetricCard label="History rows" value={selectedHistory.length} tone="neutral" source="client_monthly_performance_history" />
            <MetricCard label="Latest month" value={latestPeriod(selectedHistory)} tone="neutral" source="client_monthly_performance_history" />
          </>
        )}
      </section>
      {performanceClient ? (
        <TableView title="Key Metric Summary" rows={selectedMetricSummaryRows} columns={["metric", "latest_month", "latest", "mom", "yoy", "source"]} emptyLabel="No performance metrics found for this client." />
      ) : (
        <TableView title="Client Performance Summary" rows={allClientSummaryRows} columns={summaryColumns} emptyLabel="No client performance summary rows found." clientRows={payload.clients} />
      )}
    </div>
  );
}

function RoadmapsView({ payload, drilldown, onClearDrilldown }: { payload: DashboardPayload; drilldown?: Drilldown | null; onClearDrilldown: () => void }) {
  const roadmapCoverage = payload.overview_details?.roadmap_coverage;
  const roadmapScores = payload.overview.component_details?.roadmaps ?? {};
  const missingRows = payload.clients
    .filter((client) => !client.has_roadmap_items || !client.has_roadmap_content_validated)
    .map((client) => ({
      client_slug: client.client_slug,
      client_name: client.client_name,
      favicon_url: client.favicon_url,
      favicon_source: client.favicon_source,
      favicon_candidates_json: client.favicon_candidates_json,
      has_roadmap_items: client.has_roadmap_items,
      has_roadmap_content_validated: client.has_roadmap_content_validated,
      has_roadmap_files: client.has_roadmap_files
    }));
  const filterClientRows = (rows: Row[]) => drilldown?.clientSlug ? rows.filter((row) => row.client_slug === drilldown.clientSlug) : rows;
  const filteredMissingRows = filterClientRows(missingRows);
  const filteredDriveEvidence = filterClientRows(payload.drive_evidence ?? []);
  const filteredRoadmapItems = filterClientRows(payload.roadmap_items ?? []);
  const filteredRoadmaps = filterClientRows(payload.roadmaps);
  const filteredSeoOpportunities = filterClientRows(payload.seo_opportunities ?? []);
  const filteredWorkflowReadiness = filterClientRows(payload.workflow_readiness ?? []).filter((row) => {
    if (drilldown?.focus !== "workflow_gaps") return true;
    return ["blocked", "needs_attention", "partial"].includes(String(row.readiness_status ?? "").toLowerCase());
  });
  return (
    <div className="space-y-4">
      <FocusBanner drilldown={drilldown} onClear={onClearDrilldown} />
      <section className="grid gap-4 md:grid-cols-4">
        <MetricCard label="Roadmap items" value={payload.roadmap_items?.length ?? 0} tone="neutral" source="agency_reporting.client_roadmap_current" />
        <MetricCard label="Coverage" value={`${roadmapCoverage?.clients_with_items ?? 0}/${roadmapCoverage?.clients_total ?? 0}`} tone={(roadmapScores.coverage ?? 0) >= 85 ? "success" : "warning"} source="clients with roadmap items" />
        <MetricCard label="Evidence" value={`${roadmapCoverage?.clients_with_validated_content ?? 0}/${roadmapCoverage?.clients_total ?? 0}`} tone={(roadmapScores.evidence ?? 0) >= 85 ? "success" : "warning"} source="validated roadmap content" />
        <MetricCard label="Monthly rollups" value={payload.roadmaps.length} tone="neutral" source="client_roadmap_monthly_completion" />
      </section>
      <section className="grid gap-4 md:grid-cols-4">
        <MetricCard label="Roadmap score" value={percentScore(payload.overview.components.roadmaps)} tone={payload.overview.components.roadmaps >= 70 ? "success" : payload.overview.components.roadmaps >= 45 ? "warning" : "danger"} source="balanced roadmap health" />
        <MetricCard label="Completion" value={percentScore(roadmapScores.completion)} tone={(roadmapScores.completion ?? 0) >= 70 ? "success" : "warning"} source="monthly completion rate" />
        <MetricCard label="Risk" value={percentScore(roadmapScores.risk)} tone={(roadmapScores.risk ?? 0) >= 85 ? "success" : "warning"} source="missing evidence + overdue + high priority open" />
        <MetricCard label="Clients flagged" value={missingRows.length} tone={missingRows.length ? "warning" : "success"} source="missing evidence or validation" />
      </section>
      <TableView title={drilldown?.focus === "missing_roadmaps" ? "Focused: Missing Or Unverified Roadmaps" : "Missing Or Unverified Roadmaps"} rows={filteredMissingRows} columns={["client_slug", "client_name", "has_roadmap_items", "has_roadmap_files", "has_roadmap_content_validated"]} emptyLabel="All visible clients have roadmap rows and validated roadmap content." clientRows={payload.clients} />
      <TableView title={drilldown?.focus === "drive_evidence" ? "Focused: Drive Evidence Metadata" : "Drive Evidence Metadata"} rows={filteredDriveEvidence} columns={["client_slug", "client_name", "folder_role", "verified_at", "file_count", "populated_file_count", "content_validated_file_count", "content_validation_status", "latest_modified_date"]} emptyLabel="No Drive evidence metadata found." clientRows={payload.clients} />
      <TableView title={drilldown?.focus === "all_items" ? "Focused: All Roadmap Items" : "All Roadmap Items"} rows={filteredRoadmapItems} columns={["planned_month", "client_slug", "item_title", "work_type", "priority", "delivery_status", "owner_hint", "due_date", "completion_summary"]} clientRows={payload.clients} />
      <TableView title={drilldown?.focus === "monthly_rollup" ? "Focused: Monthly Roadmap Rollup" : "Monthly Roadmap Rollup"} rows={filteredRoadmaps} columns={["planned_month", "client_slug", "planned_items", "completed_items", "missing_evidence_items", "overdue_items", "completion_rate", "status_summary"]} clientRows={payload.clients} />
      <TableView title={drilldown?.focus === "seo_opportunities" ? "Focused: SEO Opportunities" : "SEO Opportunities"} rows={filteredSeoOpportunities} columns={["generated_at", "client_slug", "client_name", "opportunity_type", "workflow_id", "priority", "summary", "recommended_action"]} emptyLabel="No SEO opportunity rows found." clientRows={payload.clients} />
      <TableView title={drilldown?.focus === "workflow_gaps" ? "Focused: Workflow Readiness Gaps" : "Workflow Readiness"} rows={filteredWorkflowReadiness} columns={["generated_at", "client_slug", "client_name", "readiness_status", "recommended_workflow_id", "recommended_agent_id", "missing_inputs_json"]} emptyLabel="No workflow readiness rows found." clientRows={payload.clients} />
    </div>
  );
}

function ReportingView({ payload, drilldown, onClearDrilldown }: { payload: DashboardPayload; drilldown?: Drilldown | null; onClearDrilldown: () => void }) {
  const links = payload.report_links ?? [];
  const months = useMemo(() => Array.from(new Set(links.map(monthKey).filter(Boolean))).sort().reverse(), [links]);
  const [selectedMonth, setSelectedMonth] = useState("");
  useEffect(() => {
    if (drilldown?.filters?.month) setSelectedMonth(drilldown.filters.month);
  }, [drilldown?.filters?.month]);
  const activeMonth = selectedMonth && months.includes(selectedMonth) ? selectedMonth : months[0] ?? "";
  const monthLinks = links.filter((row) => monthKey(row) === activeMonth);
  const reportsByClient = new Map(monthLinks.map((row) => [String(row.client_slug), row]));
  const readinessByClient = new Map(payload.reporting.map((row) => [String(row.client_slug), row]));
  const monthRows = payload.clients.map((client) => {
    const slug = String(client.client_slug ?? "");
    const report = reportsByClient.get(slug);
    const readiness = readinessByClient.get(slug);
    return {
      client_slug: slug,
      client_name: client.client_name ?? report?.client_name,
      favicon_url: client.favicon_url ?? report?.favicon_url,
      favicon_source: client.favicon_source ?? report?.favicon_source,
      favicon_candidates_json: client.favicon_candidates_json ?? report?.favicon_candidates_json,
      readiness_status: readiness?.readiness_status,
      coverage_status: readiness?.coverage_status,
      latest_report_month: readiness?.latest_report_month,
      has_report: Boolean(report),
      report_url: report?.report_url,
      compact_report_url: report?.compact_report_url,
      report_public_path: report?.report_public_path,
      share_id: report?.share_id,
      generated_at: report?.generated_at,
      template: report?.template,
      report_path: report?.report_path
    };
  });
  const linkedRows = monthRows.filter((row) => row.has_report);
  const missingRows = monthRows.filter((row) => !row.has_report);
  const filteredLinks = links.filter((row) => {
    if (drilldown?.clientSlug && row.client_slug !== drilldown.clientSlug) return false;
    if (drilldown?.filters?.month && monthKey(row) !== drilldown.filters.month) return false;
    return true;
  });
  return (
    <div className="space-y-4">
      <FocusBanner drilldown={drilldown} onClear={onClearDrilldown} />
      <section className="grid gap-4 md:grid-cols-3">
        <MetricCard label="Report records" value={links.length} tone="neutral" source="agency_memory.monthly_report_snapshots" />
        <MetricCard label={`${monthLabel(activeMonth)} links`} value={`${linkedRows.length}/${monthRows.length}`} tone={missingRows.length ? "warning" : "success"} source="latest monthly report snapshots" />
        <MetricCard label="Ready clients" value={payload.reporting.filter((row) => statusTone(row.readiness_status) === "success").length} tone="success" source="agency_reporting.reporting_readiness" />
      </section>
      <Panel>
        <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
          <div>
            <h2 className="text-lg font-semibold">Client Reports</h2>
            <p className="text-sm text-slate-500">{activeMonth ? `${monthLabel(activeMonth)} reports by active client` : "No report months found"}</p>
          </div>
          <div className="flex max-w-full gap-2 overflow-x-auto pb-1">
            {months.map((month) => (
              <Button
                key={month}
                className={month === activeMonth ? "border-blue-600 bg-blue-50 text-blue-800" : ""}
                onClick={() => setSelectedMonth(month)}
              >
                {monthLabel(month)}
              </Button>
            ))}
          </div>
        </div>
        <div className="mt-4 overflow-hidden rounded-md border border-slate-200">
          <div className="max-h-[620px] overflow-auto">
            <table className="min-w-full divide-y divide-slate-200 text-sm">
              <thead className="sticky top-0 bg-slate-50">
                <tr>
                  <th className="whitespace-nowrap px-3 py-2 text-left font-semibold text-slate-700">Client</th>
                  <th className="whitespace-nowrap px-3 py-2 text-left font-semibold text-slate-700">Status</th>
                  <th className="whitespace-nowrap px-3 py-2 text-left font-semibold text-slate-700">Report</th>
                  <th className="whitespace-nowrap px-3 py-2 text-left font-semibold text-slate-700">Compact</th>
                  <th className="whitespace-nowrap px-3 py-2 text-left font-semibold text-slate-700">Share ID</th>
                  <th className="whitespace-nowrap px-3 py-2 text-left font-semibold text-slate-700">Generated</th>
                  <th className="whitespace-nowrap px-3 py-2 text-left font-semibold text-slate-700">Template</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100 bg-white">
                {monthRows.map((row) => (
                  <tr key={row.client_slug} className="hover:bg-slate-50">
                    <td className="px-3 py-2">
                      <div className="flex min-w-0 items-center gap-2">
                        <FaviconMark row={row} />
                        <div className="min-w-0">
                          <div className="truncate font-medium text-slate-950">{text(row.client_name)}</div>
                          <div className="truncate text-xs text-slate-500">{row.client_slug}</div>
                        </div>
                      </div>
                    </td>
                    <td className="px-3 py-2">
                      <Badge tone={row.has_report ? "success" : "warning"}>{row.has_report ? "linked" : "missing"}</Badge>
                    </td>
                    <td className="px-3 py-2">
                      {row.report_url ? (
                        <a className="inline-flex max-w-[320px] items-center gap-1 truncate font-medium text-blue-700 hover:text-blue-900" href={String(row.report_url)} target="_blank" rel="noreferrer" title={String(row.report_url)}>
                          <span className="truncate">{String(row.report_url)}</span> <ExternalLink className="h-3.5 w-3.5 shrink-0" />
                        </a>
                      ) : (
                        <span className="text-slate-400">—</span>
                      )}
                    </td>
                    <td className="px-3 py-2">
                      {row.compact_report_url ? (
                        <a className="inline-flex max-w-[320px] items-center gap-1 truncate font-medium text-blue-700 hover:text-blue-900" href={String(row.compact_report_url)} target="_blank" rel="noreferrer" title={String(row.compact_report_url)}>
                          <span className="truncate">{String(row.compact_report_url)}</span> <ExternalLink className="h-3.5 w-3.5 shrink-0" />
                        </a>
                      ) : (
                        <span className="text-slate-400">—</span>
                      )}
                    </td>
                    <td className="max-w-[180px] truncate px-3 py-2 text-slate-700" title={text(row.share_id)}>{text(row.share_id)}</td>
                    <td className="whitespace-nowrap px-3 py-2 text-slate-700">{formatMelbourneDateTime(row.generated_at)}</td>
                    <td className="whitespace-nowrap px-3 py-2 text-slate-700">{text(row.template)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
        {missingRows.length > 0 && (
          <p className="mt-3 text-sm text-amber-700">
            Missing for {monthLabel(activeMonth)}: {missingRows.map((row) => text(row.client_name)).join(", ")}
          </p>
        )}
      </Panel>
      <TableView title="Report Narratives" rows={payload.report_narratives ?? []} columns={["period_id", "client_slug", "client_name", "summary", "completed_work", "next_focus", "caveats", "generated_at"]} emptyLabel="No report narrative rows found." clientRows={payload.clients} />
      <TableView title={drilldown?.focus === "report_records" ? "Focused: Report Records" : "All Report Records"} rows={filteredLinks} columns={["period_id", "client_slug", "client_name", "report_url", "compact_report_url", "share_id", "generated_at", "template"]} clientRows={payload.clients} />
      <TableView title="Reporting Readiness" rows={payload.reporting} columns={["client_slug", "client_name", "readiness_status", "coverage_status", "latest_report_month", "has_ga4", "has_search_console", "has_se_ranking"]} clientRows={payload.clients} />
    </div>
  );
}

function AgentsView({ summaries, completedWork, rawRuns, clientRows, drilldown, onClearDrilldown }: { summaries: AgentActivitySummary[]; completedWork: Row[]; rawRuns: Row[]; clientRows: Row[]; drilldown?: Drilldown | null; onClearDrilldown: () => void }) {
  const completedByAgent = countBy(completedWork, "agent_name");
  return (
    <div className="space-y-4">
      <FocusBanner drilldown={drilldown} onClear={onClearDrilldown} />
      <section className="grid gap-4 md:grid-cols-4">
        <MetricCard label="Completed work rows" value={formatNumber(completedWork.length)} tone="success" source="agent_run_log + local index + workflow summaries" />
        <MetricCard label="Agents with work" value={formatNumber(completedByAgent.length)} tone="neutral" source="completed agent rows" />
        <MetricCard label="Failed recent runs" value={formatNumber(summaries.reduce((total, agent) => total + Number(agent.failed || 0), 0))} tone={summaries.some((agent) => agent.failed) ? "warning" : "success"} source="agent activity summary" />
        <MetricCard label="Raw local runs" value={formatNumber(rawRuns.length)} tone="neutral" source="data/agent_runs/index.json" />
      </section>
      <section className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
        {summaries.map((agent) => (
          <Panel key={agent.agent_id}>
            <div className="flex items-start justify-between gap-3">
              <div>
                <h2 className="font-semibold">{agent.agent_name}</h2>
                <p className="text-xs text-slate-500">{agent.agent_id}</p>
              </div>
              <Badge tone={agent.failed ? "warning" : "success"}>{agent.failed ? `${agent.failed} failed` : "ok"}</Badge>
            </div>
            <p className="mt-3 text-sm text-slate-600">Last completed: {formatMelbourneDateTime(agent.last_completed_at)}</p>
            <div className="mt-3 space-y-2">
              {agent.recent_runs.map((run) => (
                <div key={String(run.run_id)} className="rounded-md border border-slate-200 bg-slate-50 p-2 text-sm">
                  <div className="flex items-start justify-between gap-2">
                    <div className="min-w-0">
                      <p className="truncate font-medium text-slate-950">{text(run.task_name)}</p>
                      <p className="mt-1 line-clamp-2 text-xs leading-5 text-slate-600">{text(run.task_summary)}</p>
                    </div>
                    <Badge tone={statusTone(run.status)}>{text(run.status)}</Badge>
                  </div>
                  <div className="mt-2 flex flex-wrap gap-x-3 gap-y-1 text-xs text-slate-500">
                    <span>{formatMelbourneDateTime(run.completed_at ?? run.started_at)}</span>
                    <span>{text(run.mode)}</span>
                    <span>{formatNumber(run.findings_count)} findings</span>
                    <span>{formatNumber(run.actions_count)} actions</span>
                  </div>
                </div>
              ))}
            </div>
          </Panel>
        ))}
      </section>
      <TableView title={drilldown?.focus === "completed" ? "Focused: Agent Work Completed" : "Agent Work Completed"} rows={completedWork} columns={["agent_name", "task_name", "client_slug", "completed_at", "status", "findings_count", "actions_count", "workflow_id", "output_path", "task_summary", "source"]} emptyLabel="No completed agent work rows found." clientRows={clientRows} />
      <TableView title="Completed Work By Agent" rows={completedByAgent} columns={["name", "value"]} emptyLabel="No completed agent counts found." />
      <TableView title="Local Agent Runs" rows={rawRuns} columns={["run_id", "agent_id", "status", "mode", "started_at", "completed_at", "findings_count", "actions_count", "output_path"]} emptyLabel="No local agent run index rows found." />
    </div>
  );
}

function TableView({ title, rows, columns, emptyLabel, clientRows = [], onRowClick, rowAriaLabel }: { title: string; rows: Row[]; columns: string[]; emptyLabel?: string; clientRows?: Row[]; onRowClick?: (row: Row) => void; rowAriaLabel?: (row: Row) => string }) {
  return (
    <Panel>
      <div className="mb-3 flex items-center justify-between">
        <h2 className="text-lg font-semibold">{title}</h2>
        <span className="text-sm text-slate-500">{formatNumber(rows.length)} rows</span>
      </div>
      <DataTable rows={rows} columns={columns} emptyLabel={emptyLabel} clientRows={clientRows} onRowClick={onRowClick} rowAriaLabel={rowAriaLabel} />
    </Panel>
  );
}

function DataHealth({ payload, drilldown, onClearDrilldown }: { payload: DashboardPayload; drilldown?: Drilldown | null; onClearDrilldown: () => void }) {
  const smokeFailures = payload.api_smoke_checks?.filter((row) => !["succeeded", "success", "ok"].includes(String(row.status ?? "").toLowerCase())).length ?? 0;
  const crawlIssueRows = payload.crawl_latest?.filter((row) =>
    numberValue(row.status_4xx_urls) ||
    numberValue(row.status_5xx_urls) ||
    numberValue(row.missing_title_urls) ||
    numberValue(row.missing_meta_description_urls) ||
    numberValue(row.missing_h1_urls) ||
    numberValue(row.canonical_issue_urls)
  ).length ?? 0;
  const filteredSmokeChecks = drilldown?.clientSlug ? (payload.api_smoke_checks ?? []).filter((row) => row.client_slug === drilldown.clientSlug) : (payload.api_smoke_checks ?? []);
  const filteredCrawls = (payload.crawl_latest ?? []).filter((row) => {
    if (drilldown?.clientSlug && row.client_slug !== drilldown.clientSlug) return false;
    return true;
  });
  const filteredCostChecks = (payload.data_health.cost_checks ?? []).filter((row) => {
    if (drilldown?.focus !== "cost_failures") return true;
    return !["succeeded", "success", "ok", "passed"].includes(String(row.status ?? "").toLowerCase());
  });
  return (
    <div className="space-y-4">
      <FocusBanner drilldown={drilldown} onClear={onClearDrilldown} />
      <section className="grid gap-4 md:grid-cols-4">
        <MetricCard label="Cost failures" value={payload.data_health.cost_failures ?? 0} tone={(payload.data_health.cost_failures ?? 0) ? "danger" : "success"} source="agency_control.cost_checks" />
        <MetricCard label="Ingestion failures" value={payload.data_health.ingestion_failures ?? 0} tone={(payload.data_health.ingestion_failures ?? 0) ? "danger" : "success"} source="agency_control.ingestion_runs" />
        <MetricCard label="Stale tables" value={payload.data_health.stale_tables ?? 0} tone={(payload.data_health.stale_tables ?? 0) ? "warning" : "success"} source="latest dashboard read" />
        <MetricCard label="Agent failures" value={payload.data_health.agent_failures ?? 0} tone={(payload.data_health.agent_failures ?? 0) ? "warning" : "success"} source="data/agent_runs/index.json" />
        <MetricCard label="API smoke failures" value={smokeFailures} tone={smokeFailures ? "danger" : "success"} source="agency_control.api_smoke_checks" />
        <MetricCard label="Latest crawl rows" value={payload.crawl_latest?.length ?? 0} tone={(payload.crawl_latest?.length ?? 0) ? "neutral" : "warning"} source="agency_reporting.client_crawl_latest" />
        <MetricCard label="Crawl issue rows" value={crawlIssueRows} tone={crawlIssueRows ? "warning" : "success"} source="crawl issue summary columns" />
      </section>
      <TableView title={drilldown?.focus === "api_smoke" ? "Focused: API Smoke Checks" : "Latest API Smoke Checks"} rows={filteredSmokeChecks} columns={["client_slug", "source", "checked_at", "status", "rows_returned", "date_start", "date_end", "error_class"]} emptyLabel="No API smoke check rows found." clientRows={payload.clients} />
      <TableView title={drilldown?.focus === "crawl_latest" ? "Focused: Latest Technical Crawls" : "Latest Technical Crawls"} rows={filteredCrawls} columns={["crawl_date", "crawl_id", "source_id", "client_slug", "client_name", "crawl_status", "pages_crawled", "indexable_html_urls", "status_4xx_urls", "status_5xx_urls", "missing_title_urls", "missing_meta_description_urls", "missing_h1_urls", "canonical_issue_urls", "low_content_urls"]} emptyLabel="No crawl summary rows found." clientRows={payload.clients} />
      <TableView title="Latest Ingestion Runs" rows={payload.data_health.ingestion_runs ?? []} columns={["started_at", "source_id", "status", "destination_table", "rows_loaded", "error_message"]} />
      <TableView title={drilldown?.focus === "cost_failures" ? "Focused: Cost Check Failures" : "Latest Cost Checks"} rows={filteredCostChecks} columns={["logged_at", "purpose", "status", "estimated_bytes", "cap_bytes", "job_id"]} />
    </div>
  );
}

export default App;
