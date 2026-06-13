# BigQuery Data Warehouse Plan

Generated: 2026-06-12

Scope: read-only inventory of local storage and monday.com structures, then a low-cost BigQuery organisation plan for SEO Automation and lead-generation work.

This inventory deliberately avoids reading or exposing raw secrets, `.env` values, private service-account JSON contents, or the private credential vault.

## Executive Summary

BigQuery should become the clean reporting and analysis layer, not the only place data lives.

Keep these roles separate:

| Layer | Best role | Why |
| --- | --- | --- |
| Local SQLite/CSV files | Operational working data and app state | Existing tools already depend on these files, and local-first is safer while workflows are still changing. |
| monday.com | Workflow/status source of truth | Monday is good for task ownership, review status, client-facing delivery, and manual approval states. |
| Google Drive/Docs/Sheets | Client files and report artifacts | Drive remains the client deliverable archive. |
| BigQuery | Central warehouse for reporting, dedupe, trend analysis, and cross-project joins | BigQuery is best once data needs to be queried across projects, clients, time periods, and lead sources. |

Recommended starting approach:

1. Do not migrate everything at once.
2. Start with batch uploads from the largest and most reused local stores.
3. Use BigQuery datasets split by raw, staging, and reporting marts.
4. Query mostly small reporting tables, not raw exports.
5. Let Codex manage exports, schemas, query dry-runs, cost caps, and monthly refreshes.

## Implemented Cost Guardrails

The v1 capped-pricing guardrails are implemented locally in this project.

| File | Purpose |
| --- | --- |
| `config/bigquery_cost_guardrails.json` | Local cost config: `AUD 10` monthly budget target, `1 GB/query` normal cap, `10 GB/query` admin override cap, `australia-southeast1` location. |
| `agency_bigquery/capped_query_runner.py` | Shared Python runner that dry-runs SQL, blocks estimates above cap, executes with `maximum_bytes_billed`, and logs to `agency_control.cost_checks`. |
| `scripts/bq_capped_query.py` | CLI for future ad hoc Codex queries; requires `--purpose` and optional `--admin-cap-10gb`. |
| `docs/BIGQUERY_BUDGET_SETUP.md` | Manual Google Cloud budget setup instructions for the `seo-agency-work` project. |
| `tests/test_capped_query_runner.py` | Fake-client unit tests proving blocked queries do not execute and allowed queries set `maximum_bytes_billed`. |

All future Codex-created BigQuery scripts should call the shared capped runner rather than the BigQuery client directly.

## Current Local Data Storage

### SEO Automation

Root: `/Users/laurencedeer/Projects/Codex/SEO Automation`

Main role: SEO MCP server, client reporting inputs, GA4 reads, Drive/Docs/Sheets output, Firecrawl, SE Ranking evidence, Search Console style reports, and local report artifacts.

Important storage:

| Path | Size observed | Type | Contents |
| --- | ---: | --- | --- |
| `/Users/laurencedeer/Projects/Codex/SEO Automation/var` | 799 MB | JSON, CSV, XLSX, token/cache/report artifacts | Client report packs, GA4/GSC style exports, SE Ranking caches, sitemap/crawl outputs, invoice migration evidence, content validation artifacts. |
| `/Users/laurencedeer/Projects/Codex/SEO Automation/outputs` | 1.9 MB | XLSX/report output | Small generated reporting outputs. |
| `/Users/laurencedeer/Projects/Codex/SEO Automation/docs/agent/clients` | n/a | Markdown/JSON config | Client briefs, GA4 IDs, Drive folders, Monday boards, timelines. |
| `/Users/laurencedeer/Projects/Codex/SEO Automation/config` | n/a | JSON config | Site access routing, reporting profiles, category overrides, Drive filing rules. |

Known pull sources:

| Source | Current use |
| --- | --- |
| GA4 | Organic landing page reporting, comparison ranges, ecommerce reporting, client monthly reports. |
| Native Search Console / GSC | Opportunity mining, query/page support, report evidence where available. |
| SE Ranking MCP | Keyword research, ranking checks, backlink/competitor research, technical SEO evidence. |
| Firecrawl | Bounded site/page crawling and scraping for audit/report evidence. |
| Google Drive/Docs/Sheets | Client deliverables, report docs, working sheets, file inventory. |
| monday.com | Client-facing task boards, SEO task board, delivery proof/status. |
| Sitemaps/live sites | URL discovery, collection discovery, internal-link inputs. |

### SEO Reporting Platform

Root: `/Users/laurencedeer/Projects/Codex/seo-reporting-platform`

Main role: private local exporter plus static client reporting portal. The frontend does not call live APIs.

Important storage:

| Path | Size observed | Type | Contents |
| --- | ---: | --- | --- |
| `/Users/laurencedeer/Projects/Codex/seo-reporting-platform/content` | 6.5 MB | JSON | Normalized report snapshots and report index. |
| `/Users/laurencedeer/Projects/Codex/seo-reporting-platform/var` | 22 MB | JSON/Markdown batch files | Private monthly batch caches, Codex context files, validations, Monday scans. |
| `/Users/laurencedeer/Projects/Codex/seo-reporting-platform/config` | n/a | JSON config | Client registry, profiles, category overrides. |

Known pull sources:

| Source | Current use |
| --- | --- |
| GA4 | Monthly report metrics. |
| Native Search Console | Monthly report query/page data. |
| SE Ranking | Ranking, visibility, and keyword summaries. |
| monday.com | Optional evidence/status inputs. |
| Drive | Report/file context and artifacts. |

### BuiltWith Lead Console

Root: `/Users/laurencedeer/Projects/Codex/BuiltWith`

Main role: large lead-generation store for technology/CMS/ecommerce signals, contact enrichment, proof layers, Instantly campaign prep, and local lead-console app.

Important storage:

| Path | Size observed | Type | Contents |
| --- | ---: | --- | --- |
| `/Users/laurencedeer/Projects/Codex/BuiltWith/BuiltWith Exports` | 3.9 GB | CSV | Raw BuiltWith exports by platform, market, recently added, no longer detected, domain migration. |
| `/Users/laurencedeer/Projects/Codex/BuiltWith/processed` | 6.6 GB | SQLite, CSV, JSON | Canonical lead database, lead console state, processed events, migrations, lifecycle cache. |
| `/Users/laurencedeer/Projects/Codex/BuiltWith/exports` | 1.7 GB | CSV, SQLite | Prospecting stocktakes, NDIS/My Aged Care/public-directory provider collections, enrichment outputs. |
| `/Users/laurencedeer/Projects/Codex/BuiltWith/generated` | 3.1 GB | CSV, JSONL | Campaign audits, Instantly uploads, sequence patch payloads, prospecting intelligence, generated import files. |

Key SQLite tables:

| Database | Key tables | Row counts observed |
| --- | --- | ---: |
| `processed/builtwith.db` | `leads`, `platform_events`, `technology_timelines`, `migration_pairs`, `cms_migration_pairs_v2` | `leads`: 1,179,779; `platform_events`: 1,625,098; `technology_timelines`: 1,440,696; `cms_migration_pairs_v2`: 509,217; `migration_pairs`: 4,417 |
| `processed/lead_console_state.db` | `prospecting_lifecycle_cache`, `enriched_contacts`, `fallback_contacts`, `instantly_outreach_leads`, `screamingfrog_audit_snapshots`, `seranking_analysis_snapshots`, `external_lead_sources` | `prospecting_lifecycle_cache`: 1,177,375; `fallback_contacts`: 46,297; `enriched_contacts`: 17,113; `instantly_outreach_leads`: 13,621; `external_lead_sources`: 10,503; `screamingfrog_audit_snapshots`: 6,936; `seranking_analysis_snapshots`: 852 |

Known pull sources:

| Source | Current use |
| --- | --- |
| BuiltWith CSV exports | Main technology/company/domain universe. |
| Apify | Person-level enrichment, Google Business Profile/Maps style data, public directory collection. |
| Website scraping | Fallback emails, contact pages, proof/evidence. |
| Instantly | Campaign drafts, uploaded leads, verification, outreach state, reply sync. |
| SE Ranking | Domain/traffic/keyword proof and migration outcome checks. |
| Screaming Frog | Audit proof snapshots and website issue evidence. |
| Public directories | NDIS Commission, My Aged Care, Support NDIS Directory, NDIS Verify. |
| Cloudflare R2 | Audit preview image URLs where used. |

### Guest Post Outreach

Root: `/Users/laurencedeer/Projects/Codex/Guest Post Outreach`

Main role: publisher/guest-post prospecting, referral partner prospecting, search discovery, contact scraping, reply sync, and local-to-Monday mapping.

Important storage:

| Path | Size observed | Type | Contents |
| --- | ---: | --- | --- |
| `/Users/laurencedeer/Projects/Codex/Guest Post Outreach/data` | 2.3 GB | SQLite and working data | Guest post prospecting DB and referral partner prospecting DB. |

Key SQLite tables:

| Database | Key tables | Row counts observed |
| --- | --- | ---: |
| `data/guest_post_prospecting.db` | `candidate_domains`, `candidate_urls`, `domain_evidence`, `guest_post_prospects`, `guest_post_contact_emails`, `instantly_reply_sync`, `referral_partner_monday_item_map` | `candidate_urls`: 1,507; `domain_evidence`: 168; `candidate_domains`: 42; `guest_post_contact_emails`: 22 |
| `data/referral_partner_prospecting.db` | `referral_candidate_domains`, `referral_candidate_urls`, `referral_contact_emails`, `referral_search_results`, `referral_crawl_pages` | `referral_crawl_pages`: 9,422; `referral_search_results`: 8,002; `referral_candidate_urls`: 4,165; `referral_candidate_domains`: 1,558; `referral_contact_emails`: 1,155 |

Known pull sources:

| Source | Current use |
| --- | --- |
| Search operators | Publisher/referral discovery. |
| Competitor backlink exports | Link opportunity discovery. |
| Website scraping | Contact page and email extraction. |
| Instantly | Outreach imports and reply sync. |
| monday.com | Referral partner board mapping and review workflows. |
| SE Ranking, Ahrefs, Semrush, CSVs | Backlink/provider inputs when available. |

### Guest Post Deal Tracker and Link OS

Roots:

- `/Users/laurencedeer/Projects/Codex/Guest Post Deal Tracker`
- `/Users/laurencedeer/Projects/Codex/link-os`

Main role: paid-link/publisher inventory, Instantly reply-to-deal sync, publisher entities, agency catalogue, user visibility tiers, and Monday sync.

Important storage:

| Path | Size observed | Type | Contents |
| --- | ---: | --- | --- |
| `/Users/laurencedeer/Projects/Codex/Guest Post Deal Tracker/data` | 28 MB | SQLite backups and live DBs | Link deals, publisher entities, users, sync logs, Monday maps. |
| `/Users/laurencedeer/Projects/Codex/link-os/deal-tracker/data` | 3 MB | SQLite | Newer packaged AU Link Desk deal tracker DB. |

Key SQLite tables:

| Database | Key tables | Row counts observed |
| --- | --- | ---: |
| `Guest Post Deal Tracker/data/link_deals.db` | `link_deals`, `publisher_entities`, `instantly_reply_sync`, `sync_runs`, `monday_item_map`, `monday_thread_comments` | `link_deals`: 145; `publisher_entities`: 42; `instantly_reply_sync`: 60; `sync_runs`: 30; `monday_item_map`: 454 |
| `link-os/deal-tracker/data/link_deals.db` | `link_deals`, `publisher_entities`, `instantly_reply_sync`, `sync_runs`, `users` | Smaller packaged copy of same system shape. |

Known pull sources:

| Source | Current use |
| --- | --- |
| Instantly | Reply sync and campaign checkpoints. |
| monday.com | Publisher inventory, reply review, sync logs, catalogue snapshots. |
| Local prospecting outputs | Approved publishers and pricing data. |
| SE Ranking/manual metrics | Domain Trust and quality notes. |

### Content Analysis

Root: `/Users/laurencedeer/Projects/Codex/Content Analysis`

Main role: job-based page/content analysis with page-level results.

Important storage:

| Path | Type | Contents |
| --- | --- | --- |
| `/Users/laurencedeer/Projects/Codex/Content Analysis/backend/seo_jobs.db` | SQLite | Job metadata and page results. |

Key tables:

| Database | Key tables | Row counts observed |
| --- | --- | ---: |
| `backend/seo_jobs.db` | `jobs`, `page_results` | `jobs`: 1; `page_results`: 1,218 |

Known pull sources:

| Source | Current use |
| --- | --- |
| Uploaded URL lists | Job inputs. |
| Live page fetches | Titles, descriptions, headings, text extracts, status codes. |

### LinkedIn Automation

Root: `/Users/laurencedeer/Projects/Codex/Linkedin Automation`

Main role: local LinkedIn publishing/connection/pipeline state.

Important storage:

| Path | Type | Contents |
| --- | --- | --- |
| `/Users/laurencedeer/Projects/Codex/Linkedin Automation/data/local.sqlite` | SQLite | `linkedin_connection`, `pipeline_state`, both JSON-backed state tables. |

This is not a first-priority BigQuery candidate unless you want cross-channel sales attribution later.

### monday-agency-hub

Root: `/Users/laurencedeer/Projects/Codex/monday-agency-hub`

Main role: local monday.com workspace snapshots, board indexes, client board matrix, task alignment reports, planning/digest outputs.

Important storage:

| Path | Size observed | Type | Contents |
| --- | ---: | --- | --- |
| `/Users/laurencedeer/Projects/Codex/monday-agency-hub/data` | 428 KB | CSV/JSON snapshots | Board index, client board matrix, task alignment, aliases, hygiene outputs. |

Useful seed files:

| File | Use in BigQuery |
| --- | --- |
| `data/derived/board_index.csv` | Monday board registry and roles. |
| `data/derived/client_board_matrix.csv` | Client-to-board mapping. |
| `data/derived/task_alignment_report.csv` | SEO task vs client board drift. |
| `data/derived/board_aliases.csv` | Board-name safety map. |

## Current monday.com Storage

monday.com has three workspaces visible through the connector.

| Workspace | ID | Boards observed | Role |
| --- | --- | ---: | --- |
| Lead Management | `3114296` | 1 | Early lead-management workspace. |
| Agency Ops | `2767329` | 5 | Expenses, client registry, sales pipeline, agency operations. |
| Main workspace | `2556079` | 35 root boards observed | Client SEO delivery boards, SEO task board, Link OS boards, content/link-building boards. |

### Important Monday Boards

| Board | ID | Items observed | Current role |
| --- | ---: | ---: | --- |
| `SEO Tasks` | `5026765957` | 103 | Internal SEO execution board. |
| `Client Board` | `5026765711` | 10 | Commercial client registry: risk, start/renewal, retainer, invoice metadata. |
| `Sales` | `5025423034` | 25 | Sales pipeline: deal status, priority, deal size, company/contact fields. |
| `Content Board` | `5026765469` | 3 | Content workflow. |
| `Link Building` | `5026765647` | 0 | Link-building workflow shell. |
| `Acorn Car Rentals` | `5026665037` | 30 | Client-facing SEO delivery board. |
| Other client boards | various | varied | AVENUE Hampers, Little Shop of Happiness, Shop Rongrong, TravelKon, Salad Servers, Melani, MrGadget, Joe Rascal, Joe Rascal Ducati, Joe Rascal Harley. |
| `Link OS - Publisher Inventory` | `5029008129` | 145 | Publisher inventory, pricing, deal status, Instantly IDs, review status. |
| `Link OS - Publisher Entities` | `5029008131` | 42 | Publisher/entity rollup. |
| `Link OS - Reply Review` | `5029008134` | 61 | Instantly reply review and classification. |
| `Link OS - Sync Log` | `5029008135` | 33 | Sync runs and errors. |
| `Link OS - Agency Catalogue Snapshot` | `5029010339` | 105 | Agency-visible publisher catalogue. |
| `Link OS - Dashboard Metrics` | `5029010315` | 52 | Precomputed portfolio metrics. |

### monday.com Data Types Worth Warehousing

| Category | BigQuery use |
| --- | --- |
| Board/item metadata | Track operational load and project drift over time. |
| Client board tasks | Monthly delivery reporting and stale/blocked work detection. |
| SEO Tasks | Internal execution queue and capacity planning. |
| Sales board | Lead pipeline reporting and revenue attribution. |
| Client Board | Client registry, retainer, renewal, risk. |
| Link OS boards | Publisher inventory, reply funnel, pricing, catalogue health, sync health. |
| Monday to Drive links | File governance and "two-copy problem" detection. |

## Key Data Source Map

| Source system | Data pulled today | Main local landing zone | Best BigQuery dataset |
| --- | --- | --- | --- |
| BuiltWith | Domain/company/technology/platform exports | `BuiltWith/BuiltWith Exports`, `BuiltWith/processed` | `leadgen_raw`, `leadgen_marts` |
| Apify | Person contacts, Google Maps/GBP, public directory extraction | `BuiltWith/exports`, `BuiltWith/generated` | `leadgen_raw` |
| Instantly | Campaign drafts, uploads, verification, replies, campaign checkpoints | BuiltWith, Guest Post, Deal Tracker DBs/CSVs | `leadgen_raw`, `leadgen_marts` |
| Website scraping | Contact emails, page evidence, SEO evidence | BuiltWith, Guest Post, Content Analysis DBs | `leadgen_raw`, `seo_raw` |
| Screaming Frog | Crawl/audit snapshots | BuiltWith state DB, SEO outputs, Drive/SF folders | `seo_raw`, `leadgen_raw` |
| SE Ranking | Keyword, rank, backlink, domain metrics, migration proof | SEO var reports, BuiltWith state DB, reporting platform caches | `seo_raw`, `leadgen_raw` |
| GA4 | Organic/ecommerce performance | SEO Automation, SEO Reporting Platform | `seo_raw`, `seo_marts` |
| Search Console | Query/page data and opportunities | SEO Automation, SEO Reporting Platform | `seo_raw`, `seo_marts` |
| Google Drive/Docs/Sheets | Client files and report artifacts | Drive, SEO docs/manifests | `ops_raw`, `seo_marts` |
| monday.com | Tasks, client registry, sales, Link OS workflow state | monday live connector, monday-agency-hub snapshots | `ops_raw`, `ops_marts` |
| Public directories | NDIS, My Aged Care, Support NDIS, NDIS Verify | BuiltWith exports/DBs | `leadgen_raw` |
| LinkedIn | Local publishing/connection state | `Linkedin Automation/data/local.sqlite` | Later, if attribution is needed |

## BigQuery Organisation Plan

### Project and Dataset Layout

Use one Google Cloud project to start, with clear datasets:

| Dataset | Purpose |
| --- | --- |
| `control` | Source registry, ingestion run logs, schema versions, data quality checks, cost estimates. |
| `staging` | Temporary loaded CSV/SQLite exports. Short expiry. |
| `ops_raw` | Raw monday.com board/item snapshots, Drive file metadata, local registry snapshots. |
| `ops_marts` | Clean operational reporting tables: active tasks, client registry, board health, sync health. |
| `seo_raw` | Raw GA4, GSC, SE Ranking, Firecrawl/Screaming Frog, sitemap, page audit snapshots. |
| `seo_marts` | Client/month/page/query reporting tables, opportunity tables, delivery evidence. |
| `leadgen_raw` | Raw BuiltWith, Apify, Instantly, website scrape, public directory, publisher/reply data. |
| `leadgen_marts` | Domain master, contact master, campaign readiness, outreach funnel, publisher inventory, suppression master. |

Keep names lowercase with underscores.

### Core Keys

Use these as stable joining keys:

| Entity | Primary key idea |
| --- | --- |
| Domain/company | `root_domain` |
| Client | `client_slug` |
| Website/page | `canonical_url` or normalized `url` plus `client_slug` |
| Month | `report_month` as `YYYY-MM-01` |
| Campaign | `source_system`, `campaign_id` |
| Contact | hashed email key plus `root_domain` where privacy is needed |
| Monday item | `board_id`, `item_id` |
| Drive file | `file_id` |
| Ingestion run | generated `ingestion_run_id` |

### Recommended Tables

#### Control

| Table | Purpose |
| --- | --- |
| `control.data_sources` | Registry of source systems, paths, owners, refresh cadence, risk level. |
| `control.ingestion_runs` | Every Codex import/export run with counts, timestamps, source path, destination table, status. |
| `control.schema_versions` | Tracks table schema changes. |
| `control.cost_checks` | Dry-run bytes processed and query caps before expensive queries run. |

#### Operations

| Table | Source |
| --- | --- |
| `ops_raw.monday_boards_snapshot` | monday connector or monday-agency-hub `board_index.csv`. |
| `ops_raw.monday_items_snapshot` | monday connector, one snapshot per run. |
| `ops_raw.drive_file_inventory_snapshot` | Drive metadata only, no file contents by default. |
| `ops_marts.client_registry` | Monday Client Board plus SEO client configs. |
| `ops_marts.task_delivery_status` | SEO Tasks and client boards normalized to `Not Started`, `In Progress`, `Done`, `Blocked`. |
| `ops_marts.workflow_drift` | monday-agency-hub task alignment report over time. |
| `ops_marts.link_os_sync_health` | Link OS Sync Log and local sync runs. |

#### SEO

| Table | Source |
| --- | --- |
| `seo_raw.ga4_landing_page_daily` | GA4 exports. |
| `seo_raw.gsc_query_page_daily` | Native Search Console exports or Search Console bulk export later. |
| `seo_raw.seranking_keyword_snapshot` | SE Ranking MCP/API snapshots. |
| `seo_raw.seranking_backlink_snapshot` | SE Ranking backlink exports. |
| `seo_raw.crawl_page_snapshot` | Firecrawl/Screaming Frog/page audit data. |
| `seo_raw.sitemap_url_snapshot` | Sitemap discovery and URL state. |
| `seo_marts.client_month_summary` | Monthly reporting table for portal/client reports. |
| `seo_marts.page_opportunities` | Joined GSC, GA4, ranking, crawl issue, and task status. |
| `seo_marts.content_brief_inputs` | Clean page/keyword/query/link inputs for briefs. |

#### Lead Generation

| Table | Source |
| --- | --- |
| `leadgen_raw.builtwith_leads` | `BuiltWith/processed/builtwith.db:leads`. |
| `leadgen_raw.builtwith_platform_events` | `platform_events`. |
| `leadgen_raw.builtwith_technology_timelines` | `technology_timelines`. |
| `leadgen_raw.cms_migration_pairs` | `cms_migration_pairs_v2` and `migration_pairs`. |
| `leadgen_raw.enriched_contacts` | `lead_console_state.db:enriched_contacts`. |
| `leadgen_raw.fallback_contacts` | `fallback_contacts`. |
| `leadgen_raw.external_lead_sources` | `external_lead_sources`. |
| `leadgen_raw.instantly_outreach_leads` | `instantly_outreach_leads` from BuiltWith and deal trackers. |
| `leadgen_raw.instantly_replies` | `instantly_reply_sync`. |
| `leadgen_raw.screamingfrog_audit_snapshots` | Lead Console state DB. |
| `leadgen_raw.seranking_analysis_snapshots` | Lead Console state DB. |
| `leadgen_raw.gbp_snapshots` | `google_business_profiles`. |
| `leadgen_raw.guest_post_candidates` | Guest Post Outreach DB. |
| `leadgen_raw.referral_partner_candidates` | Referral Partner Prospecting DB. |
| `leadgen_raw.publisher_inventory` | Deal tracker `link_deals` and Monday Link OS Publisher Inventory. |
| `leadgen_marts.domain_master` | Best combined row per `root_domain`. |
| `leadgen_marts.contact_master` | Deduped emails/people per `root_domain`, with source and confidence. |
| `leadgen_marts.campaign_readiness` | Suppression, enrichment, scraped fallback, Instantly status, proof status. |
| `leadgen_marts.outreach_funnel` | Uploaded, verified, contacted, replied, deal terms, rejected, won/listed. |
| `leadgen_marts.publisher_catalogue` | Approved/listed publisher inventory for agency use. |
| `leadgen_marts.suppression_master` | Cross-project domain/email suppression table. |

## Low-Cost Implementation Strategy

### Start With Batch Loads

Avoid live streaming at the beginning. Batch uploads are simpler and cheaper:

1. Export SQLite tables to CSV or Parquet locally.
2. Upload to BigQuery raw tables.
3. Build smaller reporting tables with scheduled SQL.
4. Use those reporting tables for dashboards and Codex analysis.

### Partition and Cluster

Use partitioning:

| Table type | Partition by |
| --- | --- |
| GA4/GSC/SE Ranking daily rows | `date` |
| Monday snapshots | `snapshot_date` |
| BuiltWith/platform events | `last_found`, `first_detected`, or `ingested_at` depending on cleanliness |
| Instantly replies/uploads | `received_at`, `uploaded_at`, or `ingested_at` |
| Crawl snapshots | `checked_at` |
| Reporting marts | `report_month` |

Use clustering:

| Table type | Cluster by |
| --- | --- |
| SEO tables | `client_slug`, `root_domain`, `url` |
| Lead-gen tables | `root_domain`, `country`, `priority_tier`, `campaign_id` |
| Monday tables | `board_id`, `client_slug`, `status` |
| Publisher tables | `root_domain`, `publisher_entity_id`, `placement_type` |

### Cost Guardrails

Codex should follow these rules:

1. Run BigQuery dry-runs before new or broad queries.
2. Set maximum bytes billed on every exploratory query.
3. Avoid `SELECT *` on large raw tables.
4. Query marts first; raw tables only when debugging.
5. Create small summary tables for dashboards.
6. Add expiration to staging tables.
7. Keep raw CSV backups local until BigQuery refreshes are proven.
8. Start with a billing alert around `$5-$10/month`.

## Implementation Phases

### Phase 1: Warehouse Skeleton

Goal: create the safe structure without moving everything.

Tasks:

1. Create BigQuery project/datasets.
2. Create `control.data_sources` and `control.ingestion_runs`.
3. Register local source paths and Monday board IDs.
4. Add query guardrails and Codex runbook.
5. Load only monday-agency-hub derived CSVs and small Link OS tables as a pilot.

Success criteria:

- Codex can load one CSV snapshot.
- Codex records row counts and source path.
- A simple query joins client registry to board/task health.
- No expensive raw BuiltWith query is needed.

### Phase 2: Lead-Gen Core

Goal: make the largest local data useful across projects.

Load:

1. `BuiltWith/processed/builtwith.db:leads`
2. `platform_events`
3. `technology_timelines`
4. `cms_migration_pairs_v2`
5. `lead_console_state.db:prospecting_lifecycle_cache`
6. `enriched_contacts`
7. `fallback_contacts`
8. `instantly_outreach_leads`
9. `screamingfrog_audit_snapshots`
10. `seranking_analysis_snapshots`

Build marts:

| Mart | Purpose |
| --- | --- |
| `leadgen_marts.domain_master` | One best row per domain with company, country, platforms, score, lifecycle state. |
| `leadgen_marts.contact_master` | Deduped contacts and fallback emails. |
| `leadgen_marts.campaign_readiness` | Exactly what is safe/ready/suppressed/already contacted. |

Success criteria:

- Can answer: "Which AU Shopify domains have not been contacted, have good contact data, and have a CMS migration/audit hook?"
- Can dedupe new CSV imports against all previous exports and Instantly uploads.

### Phase 3: Link OS and Guest Post System

Goal: centralize publisher inventory and outreach replies.

Load:

1. Deal tracker `link_deals`
2. Deal tracker `publisher_entities`
3. Deal tracker `instantly_reply_sync`
4. Guest Post Outreach candidate/prospect/contact tables
5. Monday Link OS board snapshots

Build marts:

| Mart | Purpose |
| --- | --- |
| `leadgen_marts.publisher_catalogue` | Approved/listed publisher inventory. |
| `leadgen_marts.publisher_reply_funnel` | Replies by classification, deal status, pricing completeness. |
| `leadgen_marts.link_margin_analysis` | Publisher cost, reseller price, margin, placement type. |

Success criteria:

- Can spot duplicate publishers across local DB, Monday, and new outreach replies.
- Can report catalogue health: missing price, missing DT, needs review, high margin, listed/private.

### Phase 4: SEO Reporting Warehouse

Goal: make client SEO reporting repeatable and cheaper to run.

Load:

1. Reporting Platform content snapshots.
2. GA4 landing page exports by client/month.
3. GSC query/page exports by client/month.
4. SE Ranking keyword/backlink snapshots where already cached.
5. Crawl/page audit snapshots.
6. Monday client board/task snapshots.

Build marts:

| Mart | Purpose |
| --- | --- |
| `seo_marts.client_month_summary` | One row per client/month. |
| `seo_marts.page_opportunities` | Join GA4, GSC, SE Ranking, crawl issues, and Monday task state. |
| `seo_marts.reporting_readiness` | Missing data checks before client report generation. |

Success criteria:

- Reporting Platform can eventually read from BigQuery marts or exported JSON generated from BigQuery.
- Codex can answer: "Which pages have impressions but poor CTR, declining GA4 sessions, and no current Monday task?"

### Phase 5: Automate Refreshes

Goal: let Codex manage repeatable refreshes safely.

Automations:

| Cadence | Job |
| --- | --- |
| Daily | Monday board/item snapshots, Link OS sync health. |
| Weekly | BuiltWith/leadgen new CSV import, suppression/dedupe refresh, publisher catalogue health. |
| Monthly | SEO reporting marts after GA4/GSC/SE Ranking exports. |
| On demand | Large BuiltWith raw reloads, public directory refreshes, deep Screaming Frog exports. |

Each job should:

1. Estimate load/query cost.
2. Write a row to `control.ingestion_runs`.
3. Produce row counts and quality checks.
4. Avoid write-side API actions unless explicitly approved.

## What Not To Move First

Do not prioritise these until the main warehouse is useful:

| Data | Reason |
| --- | --- |
| Raw private email bodies | Higher privacy risk; use extracted classifications and metadata first. |
| Full Google Docs contents | Drive should remain the artifact store; warehouse metadata and links only at first. |
| All screenshots/images | Store URLs/metadata, not image binaries. |
| Local app user/session/password tables | Security risk and low analytical value. |
| Every generated CSV backup | Load canonical outputs, not every intermediate unless needed for auditability. |

## Beginner-Friendly Operating Model

Think of it like this:

- Local projects are your workshops.
- Monday is your task board.
- Drive is your filing cabinet.
- BigQuery is the clean spreadsheet brain across everything.

At first, BigQuery should only receive clean copies of important tables. If something goes wrong, your local systems still work.

Codex should be responsible for:

1. Finding the right source file/table.
2. Exporting it safely.
3. Loading it into the correct BigQuery table.
4. Checking row counts.
5. Running only capped/dry-run SQL.
6. Producing small summary tables you can understand.
7. Telling you before any write-side action, campaign upload, Monday mutation, or file move.

## Immediate Next Actions

1. Confirm the Google Cloud project name to use for BigQuery.
2. Decide whether the first pilot is `monday -> ops_marts` or `BuiltWith -> leadgen_marts`.
3. Create a sanitized source registry file for this BigQuery project.
4. Build a local exporter script that can export selected SQLite tables to CSV or Parquet.
5. Create the BigQuery datasets and first three tables:
   - `control.data_sources`
   - `control.ingestion_runs`
   - `leadgen_raw.builtwith_leads` or `ops_raw.monday_boards_snapshot`
6. Add cost controls before loading large BuiltWith tables.

My recommended first pilot:

1. Load `monday-agency-hub/data/derived/board_index.csv`.
2. Load `monday-agency-hub/data/derived/client_board_matrix.csv`.
3. Load `monday-agency-hub/data/derived/task_alignment_report.csv`.
4. Build `ops_marts.workflow_drift`.
5. Then load BuiltWith `leads` and `prospecting_lifecycle_cache`.

That gives a small safe win before touching the 6.6 GB BuiltWith processed store.
