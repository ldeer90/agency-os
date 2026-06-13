# Client Readiness Agent

## Purpose

Checks whether a client has the SEO Automation assets needed for recurring workflows.

## Inputs

- client brief presence
- sidecar JSON presence
- timeline presence
- GA4/GSC/SE Ranking routes
- Drive and Monday routes

## Outputs

- readiness findings
- missing-input actions
- safe recommended workflow to resolve blockers

## Safety

- Do not replace `client_health_check`.
- Do not store raw timeline markdown, Drive/Docs/Sheets contents, or private comms.
- Store sanitized status and route metadata only.
- Every missing-input recommendation needs evidence.
