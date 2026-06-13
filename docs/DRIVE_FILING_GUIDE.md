# Google Drive Filing Guide

This guide tells future agents how to route client reports and delivery files without turning BigQuery into a Drive writer or raw document store.

## Canonical Drive Model

The canonical client tree is:

```text
My Drive / Agents Digital / Clients
```

Default identities:

- Output owner for new Docs/Sheets: `hello@agents.digital`.
- Primary working account for most client access: `seo@agents.digital`.
- Acorn Rentals and Agents Digital have `hello@agents.digital`-owned analytics/access details.

BigQuery should remember approved routes and report metadata, but SEO Automation remains the source of truth for Drive access and folder structure.

## Sources To Check Before Filing

Check these in order:

1. `/Users/laurencedeer/Projects/Codex/SEO Automation/AGENTS.md`
2. `/Users/laurencedeer/Projects/Codex/SEO Automation/docs/agent/areas.md`
3. `/Users/laurencedeer/Projects/Codex/SEO Automation/docs/agent/clients/<client>.md`
4. `/Users/laurencedeer/Projects/Codex/SEO Automation/docs/agent/clients/<client>.json`
5. `/Users/laurencedeer/Projects/Codex/SEO Automation/config/drive_filing_rules.json`
6. `/Users/laurencedeer/Projects/Codex/seo-reporting-platform/config/clients.json` for reporting client slugs and labels.

The SEO Automation client brief and sidecar should define the client root folder and any known subfolders such as audits, content, reports, blogs, or on-page SEO.

## Standard Folder Meanings

Use the canonical filing rules from SEO Automation. Common folders are:

- `00 Proposals`
- `01 Onboarding`
- `02 Roadmap`
- `03 Audits`
- `04 Keyword Research`
- `05 Content`
- `06 Links`
- `07 Reports`
- `08 Invoices`
- `On-page SEO`

Important routing notes:

- Monthly performance reports normally belong in `07 Reports`.
- Technical crawl exports, audit reports, issue exports, and GSC/GA4 evidence normally belong in `03 Audits`.
- Page titles, metadata, H1, schema, and structured data work belong in `On-page SEO`.
- Content briefs, blog drafts, article drafts, and page copy belong in `05 Content`.
- Keyword, ranking, SERP, benchmark, and link-gap research belong in `04 Keyword Research`.
- Do not auto-file security-sensitive credential, access, login, token, password, or API-key files; mark them for review.
- Do not auto-merge duplicate destination folders.

## Folder Verification

For folder truth, prefer the Google Drive MCP with a parent-folder query:

```text
parentId = '<folder_id>'
```

Do not rely on service-account folder listing results as proof that a folder is empty. SEO Automation documents note that service-account checks can produce false-empty folder results.

If Drive MCP is unavailable, stop and explain the limitation before making filing decisions that depend on folder contents.

For roadmap inventory, a configured `02 Roadmap` folder route is only routing evidence. Mark the folder/file metadata assets present only after Drive MCP verifies the folder and one or more populated files in that folder, using metadata such as file count, MIME type, modified time, and Sheet grid dimensions.

For roadmap correctness checks, use bounded content validation only: headers plus the first 10-20 non-empty rows for Sheets, or small headings/snippets for Docs when needed. Store only validation metadata such as detected headers, non-empty row count, latest planned/report month, client-title match, status, freshness, and short notes. Do not store raw Docs/Sheets contents for inventory or health checks.

## Write Approval Rules

Explicit user approval is required before:

- Creating a Drive folder.
- Moving or renaming a Drive file.
- Deleting or archiving a Drive file.
- Changing sharing or permissions.
- Filing a report into a folder when the destination is ambiguous.
- Writing client-facing Docs/Sheets from generated content.

Read-only Drive checks are allowed when needed to verify a route, but keep inspection metadata-first and avoid opening private document bodies unless the task requires it.

## BigQuery Boundary

Allowed BigQuery metadata:

- `client_slug`
- `client_name`
- Folder labels and folder IDs sourced from approved SEO Automation docs.
- Created report title, file ID, URL, folder route, created timestamp, and readback status for files this workflow created.
- Source path and last verified timestamp.

Forbidden BigQuery data:

- Raw Google Doc text.
- Raw Sheet contents unless a separate approved reporting workflow scopes specific metrics.
- Drive comments.
- Permission payloads.
- Credential, token, cookie, or secret values.
- Private email bodies, raw Monday comments/updates, or private conversation text. Only validated weekly comms summaries may enter BigQuery through `scripts/load_comms_digest.py`.

## Future Metadata Table

A future metadata-only table may be added:

```text
agency_memory.client_drive_routes
```

Recommended purpose:

- Help agents locate the approved Drive destination for reports, audits, content, and on-page SEO files.
- Join client routing with reporting readiness without reading Drive contents.

Recommended fields:

- `client_slug`
- `client_name`
- `folder_key`
- `folder_label`
- `folder_id`
- `source_path`
- `last_verified_at`
- `routing_status`
- `notes`

Do not implement this table by crawling Drive contents. Build it from SEO Automation client briefs, sidecars, and `drive_filing_rules.json`, then verify selected folders with Drive MCP when a workflow needs to file output.

## Report Filing Workflow

1. Confirm the client slug and report type.
2. Read the client brief and sidecar in SEO Automation.
3. Check `drive_filing_rules.json` for the correct destination folder class.
4. Verify the target folder with Google Drive MCP when folder contents or exact destination matter.
5. Ask Laurence for explicit approval before creating or moving files.
6. Create the report using the approved SEO Automation or Google Drive workflow.
7. Read back the created file metadata.
8. Record only safe metadata in BigQuery or handover notes if the workflow calls for it.
