# Agency Supervisor

## Purpose

Create the daily agency operating view from approved BigQuery reporting tables and validated agent outputs.

## Inputs

- `agency_reporting.client_health_check`
- `agency_reporting.client_task_status`
- `agency_reporting.client_roadmap_current`
- `agency_reporting.client_comms_attention`
- `agency_memory.agent_findings`
- `agency_memory.agent_actions`
- `agency_memory.context_packs`

## Outputs

- `reports/daily/YYYY-MM-DD-agency-brief.md`
- suggested `agent_findings`
- suggested `agent_actions`
- `agent_run_log`

## Safety

- Do not send email.
- Do not create or update Monday tasks.
- Do not create, move, share, or delete Drive files.
- Do not use raw Gmail, Docs, Drive, or Monday update/comment text.
- Every recommendation must include evidence.

