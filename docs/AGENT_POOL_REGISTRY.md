# AgencyOS SEO Agent Pool Registry

Last updated: 2026-06-13.

This registry classifies the AgencyOS SEO agent pool and keeps ownership clear. Agent specs live in `agents/`; prompt versions live in `prompts/`; runnable local wrappers live in `scripts/`.

## Hierarchy

```text
agency_supervisor
→ seo_workflow_router
→ specialist agents
→ qa_guardrail
→ approval/action queue
```

`agency_supervisor` is the SEO lead agent. It receives validated specialist findings, prioritises the operating view, and produces daily or weekly briefs. It does not execute external writes.

`seo_workflow_router` is the intake and workflow-routing agent. It maps requests and operating signals to canonical SEO Automation skills and workflows, then recommends dry-run or research-mode next steps.

`qa_guardrail` is the validation stage before findings/actions are logged, included in briefs, or queued for approval.

## Agent Status

| Agent | Status | Role | Runner |
| --- | --- | --- | --- |
| `agency_supervisor` | lead | SEO lead and operating brief owner | `scripts/run_daily_agency_brief.py` |
| `seo_workflow_router` | active-runner | Routes requests to SEO Automation workflows | `scripts/run_seo_workflow_router.py` |
| `promise_tracker` | active-runner | Reviews summarized comms for commitments | `scripts/run_promise_tracker.py` |
| `seo_opportunity_agent` | active-runner | Reviews SEO opportunity queue | `scripts/run_seo_opportunity_agent.py` |
| `reporting_prep_agent` | active-runner | Reviews reporting prep gaps and missing sources | `scripts/run_reporting_prep_agent.py` |
| `performance_analyst` | active-runner | Reviews GA4/GSC/SE Ranking performance marts | `scripts/run_performance_analyst.py` |
| `se_ranking_hygiene_agent` | active-runner | Reviews SE Ranking route/access/capacity hygiene | `scripts/run_se_ranking_hygiene_agent.py` |
| `drive_filing_readback_agent` | active-runner | Reviews Drive route/readback readiness | `scripts/run_drive_filing_readback_agent.py` |
| `reporting_portal_qa_agent` | active-runner | Reviews static reporting portal QA readiness | `scripts/run_reporting_portal_qa_agent.py` |
| `search_console_opportunity_agent` | docs-only-active | Owns GSC opportunity mining queue | planned runner |
| `client_readiness` | embedded | Generates client setup readiness rows | `agency_bigquery/seo_automation_catalog.py` |
| `monday_hygiene` | embedded | Flags Monday metadata cleanup candidates | `scripts/run_daily_agency_brief.py` |
| `qa_guardrail` | embedded | Validates findings/actions and approval status | `agency_bigquery/agent_ops.py` |
| `delivery_manager` | docs-only-active | Reviews task and roadmap delivery risk | planned runner |
| `seo_maintenance_agent` | docs-only-active | Recommends access, filing, and platform cleanup | planned runner |
| `content_operations_agent` | docs-only-active | Coordinates content workflow readiness | planned runner |
| `technical_audit_agent` | active-runner | Owns monthly and post-task crawl interpretation from Screaming Frog MCP/CLI, SE Ranking, Firecrawl, and crawl evidence | `scripts/run_technical_audit_agent.py` |
| `reporting_agent` | docs-only-active | Drafts client-safe reporting notes | planned runner |
| `client_comms_drafting` | future | Draft-only client comms after approval flow matures | none |
| `technical_seo` | future | Retired compatibility alias for `technical_audit_agent` | none |

## Source Boundaries

- BigQuery is the read-only memory and reporting layer.
- SEO Automation remains the source of truth for client briefs, sidecars, timelines, Drive routes, platform access, and execution workflows.
- Monday remains the source of truth for task state.
- Google Drive remains the source of truth for files and folder contents.
- GA4, Search Console, and SE Ranking live APIs are read-only sources when a workflow explicitly approves live verification.
- Screaming Frog MCP is a technical-audit evidence interface for loaded crawl inspection, progress checks, crawl export, monthly baseline planning, post-task verification planning, and explicitly approved bulk exports.

## Approval Rules

- Every specialist recommendation must include evidence.
- External actions stay `needs_review` until explicit approval exists.
- No agent may send email, create or update Monday tasks, move/share/delete Drive files, publish content, deploy reports, or change SE Ranking without explicit user approval.
- No agent may start, resume, pause, clear, export, upload, or bulk-export Screaming Frog crawl/page content without explicit approval for the site and scope.
- Crawl memory in BigQuery is sanitized summary/URL technical fact storage only and is retained for 18 months.
- Raw Drive/Docs/Sheets contents, Gmail/Outlook bodies, Monday updates/comments, credential values, raw keyword/export dumps, raw Screaming Frog exports, raw HTML, and visible page text must not be stored in BigQuery.
