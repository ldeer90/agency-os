export type Tone = "success" | "warning" | "danger" | "critical" | "neutral";

export interface Overview {
  score: number;
  status: string;
  tone: Tone;
  components: Record<string, number>;
  component_details?: {
    roadmaps?: Record<string, number>;
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
  data_health: {
    ingestion_runs?: Row[];
    cost_checks?: Row[];
    cost_failures?: number;
    ingestion_failures?: number;
    stale_tables?: number;
    agent_failures?: number;
  };
}
