export type Tone = "success" | "warning" | "danger" | "critical" | "neutral";

export interface Overview {
  score: number;
  status: string;
  tone: Tone;
  components: Record<string, number>;
  component_details?: {
    roadmaps?: Record<string, number>;
    finance?: Record<string, number>;
  };
}

export type Row = Record<string, unknown>;

export interface ClientDetail {
  profile: Row;
  context?: Row;
  health: Row;
  missing_required: string[];
  missing_optional: string[];
  missing_assets: Row[];
  health_assets: Row[];
  reporting?: Row;
  reports: Row[];
  report_narratives: Row[];
  roadmaps: Row[];
  roadmap_missing: boolean;
  roadmap_evidence_missing: boolean;
  performance_history: Row[];
  finance: Row[];
  delivery: Row[];
  comms: Row[];
  comms_history: Row[];
  timeline: Row[];
  agent_work: Row[];
  drive_evidence: Row[];
  seo_opportunities: Row[];
  workflow_readiness: Row[];
  crawl_latest: Row[];
  api_smoke_checks: Row[];
}

export interface AgentActivitySummary {
  agent_id: string;
  agent_name: string;
  last_completed_at?: string;
  recent_runs: Row[];
  succeeded: number;
  failed: number;
}

export interface DashboardPayload {
  meta: {
    generated_at: string;
    environment: string;
    data_source_status: string;
    message?: string;
    source_tables?: string[];
  };
  overview: Overview;
  overview_details?: {
    missing_assets_by_type?: Array<{ name: string; value: number }>;
    roadmap_gap_clients?: string[];
    roadmap_coverage?: {
      clients_total: number;
      clients_with_items: number;
      clients_with_validated_content: number;
      current_items: number;
      monthly_rollups: number;
      missing_evidence_items: number;
      overdue_items: number;
    };
    report_gap_clients?: string[];
    performance_months?: string[];
    finance_current_period?: string;
    recent_agent_runs?: number;
    source_tables?: string[];
  };
  needs_attention: Row[];
  clients: Row[];
  client_profiles?: Row[];
  client_context?: Row[];
  client_details?: Record<string, ClientDetail>;
  health_assets?: Row[];
  delivery: Row[];
  task_summary?: Row;
  task_status_by_client?: Row[];
  task_status_distribution?: Row[];
  task_client_detail?: Row[];
  ops_drift?: Row[];
  performance: Row[];
  performance_history?: Row[];
  finance?: Row[];
  finance_monthly?: Row[];
  finance_clients?: Row[];
  finance_expenses?: Row[];
  finance_health?: Row;
  comms: Row[];
  roadmaps: Row[];
  roadmap_items?: Row[];
  reporting: Row[];
  report_links?: Row[];
  report_narratives?: Row[];
  client_timeline?: Row[];
  unified_timeline?: Row[];
  comms_history?: Row[];
  drive_evidence?: Row[];
  seo_opportunities?: Row[];
  workflow_readiness?: Row[];
  crawl_latest?: Row[];
  api_smoke_checks?: Row[];
  agents: Row[];
  agent_run_log?: Row[];
  workflow_runs?: Row[];
  agent_activity_summary?: AgentActivitySummary[];
  agent_work_completed?: Row[];
  briefs?: Row[];
  data_health: {
    ingestion_runs?: Row[];
    cost_checks?: Row[];
    cost_failures?: number;
    ingestion_failures?: number;
    stale_tables?: number;
    agent_failures?: number;
  };
}

export interface SyncRunState {
  run_id: string;
  command_id: string;
  sync_id: string;
  mode: string;
  status: string;
  started_at?: string;
  completed_at?: string;
  exit_code?: number | null;
  command_display?: string[];
  stdout?: string;
  stderr?: string;
  step_results?: Row[];
}

export interface SyncCommandState {
  command_id: string;
  run_id: string;
  sync_id: string;
  label: string;
  category: string;
  mode: string;
  status: string;
  queued_at: string;
  started_at?: string | null;
  completed_at?: string | null;
  exit_code?: number | null;
  cwd: string;
  command_display: string[];
  options?: Row;
  expected_logs?: string[];
  history?: Row[];
  run?: SyncRunState | null;
}

export interface SyncDefinition {
  sync_id: string;
  label: string;
  category: string;
  risk_level: string;
  source_system: string;
  destination_layer: string;
  cadence: string;
  supports_dry_run: boolean;
  supports_live_run: boolean;
  supports_client_scope: boolean;
  supports_table_scope: boolean;
  supports_ensure_tables: boolean;
  requires_input_path: boolean;
  confirmation_text: string;
  expected_logs: string[];
  notes: string;
  plain_english: string;
  simple_group: string;
  master_step_ids: string[];
  last_run?: SyncCommandState | null;
  last_success_at?: string | null;
  last_failure_at?: string | null;
  freshness_status?: string;
}

export interface SyncPayload {
  meta: {
    generated_at: string;
    state_root: string;
    poll_seconds: number;
  };
  summary: {
    running_syncs: number;
    failed_syncs: number;
    last_successful_monday_state_update?: string | null;
    last_successful_bigquery_push?: string | null;
    oldest_stale_sync?: string | null;
    recent_cost_guardrail_failures: number;
  };
  syncs: SyncDefinition[];
  commands: SyncCommandState[];
  timeline: SyncCommandState[];
}
