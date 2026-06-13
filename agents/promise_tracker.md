# Promise Tracker

## Purpose

Detect likely agency commitments from approved summarized communication rows and suggest reviewable follow-up actions.

## Inputs

- `agency_reporting.client_comms_attention`
- `agency_reporting.client_comms_history`
- optional local staged summary JSONL from `data/comms_memory/staging`
- Monday-derived task status only as supporting metadata

## Outputs

- promise findings
- suggested follow-up actions
- `needs_review` rows for uncertain commitments

## Safety

- Use summarized comms only.
- Never store raw email bodies, raw addresses, attachments, Monday comments, or Doc contents.
- Never create live Monday tasks.
- Mark uncertain promises as `needs_review`.
- Require summarized evidence for every promise finding and follow-up action.
