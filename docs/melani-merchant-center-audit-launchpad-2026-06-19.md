# Melani Merchant Center And Google Shopping Audit Launchpad

Date created: 2026-06-19

Purpose: reusable handoff for future Melani the Label Google Shopping, Merchant Center, and Organic Search audits. This note is based on read-only GA4, Search Console access checks, Merchant Center screenshots, and local CSV/TSV exports supplied by Laurence. It intentionally avoids credential values, raw tokens, and private mailbox content.

## Client And Access Context

- Client: Melani the Label
- Domain: `https://melanithelabel.com`
- GA4 property: `properties/369346274`
- Analytics subject used for read-only checks: `seo@agents.digital`
- Search Console property available: `https://melanithelabel.com/`
- Merchant Center API status:
  - Domain-wide delegation for `https://www.googleapis.com/auth/content` was fixed.
  - Token generation succeeded for `seo@agents.digital` and `hello@agents.digital`.
  - API account listing remained blocked because Google Cloud project `seo-agency-work` / project number `310811582156` is not registered with the Merchant Center account.
  - Treat current Merchant Center review as manual unless registration is explicitly approved later.

## Performance Timeline

GA4 showed the drop started before the April 2026 client email. The first major break appears in June 2025, with a second sustained weakening from August to November 2025.

### Organic Search And Organic Shopping Monthly Trend

| Period | Organic Search revenue | Organic Shopping revenue | Total organic revenue | Notes |
| --- | ---: | ---: | ---: | --- |
| 2025-03 | A$148,772 | A$34,341 | A$183,113 | Peak period starts. |
| 2025-04 | A$188,252 | A$22,198 | A$210,451 | Strongest observed month. |
| 2025-05 | A$154,911 | A$8,531 | A$163,442 | Still strong. |
| 2025-06 | A$66,181 | A$4,101 | A$70,281 | First major break. |
| 2025-08 | A$49,210 | A$3,764 | A$52,974 | Sustained weaker level. |
| 2025-10 | A$36,925 | A$2,705 | A$39,630 | Second deterioration underway. |
| 2025-11 | A$22,208 | A$2,434 | A$24,642 | Severe low point. |
| 2026-05 | A$38,749 | A$3,132 | A$41,881 | Not recovered to early 2025 levels. |

### Weekly Breakpoint

- May 2025 weeks 19-22 were very strong.
- Week 23 of 2025 onward drops materially.
- September to November 2025 confirms the second weakening:
  - 2025 week 36: total organic revenue about A$10,046.
  - 2025 week 40: total organic revenue about A$12,430.
  - 2025 week 44: total organic revenue about A$6,303.
  - 2025 week 46: total organic revenue about A$4,754.

## Organic Search Findings

Organic Search is the larger commercial problem, even though Organic Shopping also weakened. The decline is heavily collection-led.

Strong window, 2025-03-01 to 2025-05-31:

| Landing page | Organic Search sessions | Purchases | Revenue |
| --- | ---: | ---: | ---: |
| `/` | 70,523 | 1,026 | A$245,564 |
| `/collections/dresses` | 8,300 | 75 | A$18,728 |
| `/collections/all-dresses` | 6,119 | 47 | A$12,549 |
| `/collections/new-arrivals` | 1,182 | 15 | A$3,977 |
| `/collections/maxis` | 1,031 | 5 | A$1,640 |
| `/collections/sets` | 625 | 7 | A$1,607 |

Weak window, 2025-09-01 to 2025-11-30:

| Landing page | Organic Search sessions | Purchases | Revenue |
| --- | ---: | ---: | ---: |
| `/` | 31,867 | 273 | A$70,077 |
| `/collections/dresses` | 2,865 | 12 | A$2,781 |
| `/collections/all-dresses` | 2,780 | 17 | A$4,732 |
| `/collections/maxis` | 615 | 4 | A$837 |
| `/collections/sale` | 363 | 5 | A$710 |
| `/collections/gowns` | 50 | 0 | A$0 |

Audit implication: future work should check collection visibility, indexability, titles/H1s, internal links, category content, product availability on collection pages, and Search Console query/page loss around dresses, all dresses, maxis, sets, gowns/formal, bridal, and resort.

## Merchant Center Export Inventory

The following Merchant Center performance CSVs were supplied from `/Users/laurencedeer/Downloads/`. The files are safe to use as local audit evidence, but future agents should not assume they remain present unless the user confirms.

### All Traffic Exports

| Date range | Day | Country | Title |
| --- | --- | --- | --- |
| 2025-03-01 to 2025-05-31 | Yes | Yes | Yes |
| 2025-06-01 to 2025-08-31 | Yes | Yes | No |
| 2025-09-01 to 2025-11-30 | Yes | Yes | Yes |
| 2026-03-01 to 2026-05-31 | Yes | Yes | Yes |

Missing All Traffic item: title-level export for 2025-06-01 to 2025-08-31.

### Organic-Only Exports

| Date range | Day | Title |
| --- | --- | --- |
| 2025-03-01 to 2025-05-31 | Yes | Yes |
| 2025-06-01 to 2025-08-31 | Yes | Yes |
| 2025-09-01 to 2025-11-30 | Yes | Yes |
| 2026-03-01 to 2026-05-31 | Yes | Yes |

Organic-only Merchant Center totals from supplied files:

| Date range | Export type | Impressions | Clicks | Purchases | Weighted CTR |
| --- | --- | ---: | ---: | ---: | ---: |
| 2025-03-01 to 2025-05-31 | Day | 275,281 | 4,524 | 0.00 | 1.64% |
| 2025-03-01 to 2025-05-31 | Title | 252,690 | 4,524 | 0.00 | 1.79% |
| 2025-06-01 to 2025-08-31 | Day | 144,862 | 2,713 | 0.00 | 1.87% |
| 2025-06-01 to 2025-08-31 | Title | 120,822 | 2,713 | 0.00 | 2.25% |
| 2025-09-01 to 2025-11-30 | Day | 193,708 | 1,929 | 0.00 | 1.00% |
| 2025-09-01 to 2025-11-30 | Title | 162,225 | 1,929 | 0.00 | 1.19% |
| 2026-03-01 to 2026-05-31 | Day | 360,021 | 2,237 | 13.21 | 0.62% |
| 2026-03-01 to 2026-05-31 | Title | 324,578 | 2,237 | 13.21 | 0.69% |

Audit implication: Organic Merchant Center clicks declined sharply after the strong 2025 window. 2026 impressions improved versus late 2025, but CTR fell below 1%, supporting a feed/title/offer appeal issue as well as visibility loss.

## Products Export Findings

Supplied ZIP: `/Users/laurencedeer/Downloads/products_2026-06-19_13-48-06.zip`

Contained file: `products_2026-06-19_13-48-06.tsv`

Summary:

- Total product/variant rows: 3,083
- In stock: 1,984
- Out of stock: 1,099
- Feed labels:
  - AU: 1,594 rows
  - US: 1,489 rows
- Brand values are inconsistent:
  - `MELANI LABEL`: 1,764 rows
  - `Melani label`: 1,319 rows
- Google product category:
  - `Apparel & Accessories > Clothing > Dresses`: 1,107 rows
  - `Apparel & Accessories > Clothing > Shirts & Tops`: 600 rows
  - `Apparel & Accessories > Clothing > Skirts`: 545 rows
  - `Apparel & Accessories > Clothing Outfit Sets`: 260 rows
  - Blank: 208 rows
- Identifier exists:
  - `yes`: 2,878 rows
  - blank: 185 rows
  - `no`: 20 rows
- Title quality issues observed:
  - Overstuffed product titles.
  - Repeated brand/category wording in some top clicked items.
  - Generic formal/resort suffix applied broadly, including non-dress products.

Example title problem from top clicked products:

```text
MELANI LABEL Women's TOP LABEL Women's TOP ELLA CROP - SAGE / L, Women's Formal Dresses & Resort Wear
```

## Merchant Center Data Source Findings

Screenshots supplied in chat showed two Content API sources.

### AU Source

- Source name: `Simprosys Feed (Merchant API)`
- Source ID: `10364633832`
- Type: API
- Products: 1,594
- Last updated: `-`
- Countries: Australia, New Zealand, United States
- Language: English
- Feed label: AU
- Marketing methods: Free listings, Shopping ads

Important note: the AU feed label targets Australia, New Zealand, and United States. Since a separate US source also exists, future audit should check whether US products are duplicated or competing across AU and US feed labels.

AU attribute rules:

- Age group: set to `adult`.
- Gender: set to `female`.
- Title rule:

```text
brand + " Womens' " + product type + " " + title
Append: ", Women's Formal Dresses & Resort Wear"
```

### US Source

- Source name: `Content API`
- Source ID: `10592979531`
- Type: API
- Products: 1,489
- Last updated: `-`
- Countries: no additional countries shown
- Language: English
- Feed label: US
- Marketing methods: Free listings, Shopping ads

US attribute rules:

- Age group: set to `adult`.
- Gender: set to `female`.
- Title rule:

```text
"MELANI THE LABEL" + " Women's " + product type + " " + title
Append: ", Women's Formal Dresses & Resort Wear"
```

## Main Working Hypotheses

1. Organic Search decline began around June 2025 and is collection-led.
2. Organic Shopping decline also began after the March-May 2025 high point, with clicks weakening materially by June-August 2025 and again by September-November 2025.
3. Merchant Center title rules are a confirmed cross-feed issue affecting AU and US sources.
4. Feed title rewriting likely contributes to low CTR, poor query matching, and category mismatch.
5. The generic suffix `Women's Formal Dresses & Resort Wear` is applied to all product types, including tops, skirts, swimwear, blazers, gift cards, and other non-dress products.
6. Google product category and brand normalization need cleanup.
7. Large out-of-stock share may be suppressing product performance and should be compared against top historical click products.
8. Purchase data inside Merchant Center performance exports appears unreliable or absent before 2026; use GA4 for revenue and purchase analysis.

## Recommended Next Audit Steps

1. Build a product-title audit from the products TSV:
   - Detect duplicated brand/product-type terms.
   - Flag titles with generic dress/resort suffix on non-dress categories.
   - Compare title length and click/CTR performance by period.
2. Compare Organic-only title exports across periods:
   - 2025-03 to 2025-05 as strong baseline.
   - 2025-06 to 2025-08 as first drop window.
   - 2025-09 to 2025-11 as second drop window.
   - 2026-03 to 2026-05 as current recovery/non-recovery window.
3. Join products TSV to Merchant Center title exports where possible:
   - Use exact title only as a fallback because feed titles may change.
   - Prefer `id` if future exports include item ID.
4. Check whether top-click products from 2025 became out of stock, retitled, recategorized, or duplicated by country/feed label.
5. Use GA4 landing-page evidence to prioritize SEO fixes:
   - `/collections/dresses`
   - `/collections/all-dresses`
   - `/collections/maxis`
   - `/collections/sets`
   - `/collections/gowns`
   - `/collections/new-arrivals`
6. If Merchant Center UI allows it, export or screenshot:
   - Products > Needs attention. User indicated no needs-attention issues; screenshot would be useful proof.
   - Data source processing/latest update details for both AU and US sources.
   - Any source-level diagnostics or account-level issues.

## Guardrails For Future Agents

- Do not register the Google Cloud project with Merchant Center or make API/write changes unless Laurence explicitly approves that action.
- Do not change feed rules, attribute rules, product data, Shopify settings, countries, or marketing methods without explicit approval.
- Treat all Merchant Center edits as write-side/high-risk.
- Keep analysis read-only by default.
- Use GA4 for revenue/purchase truth where Merchant Center purchase data is absent or inconsistent.
- Use Merchant Center for impressions/clicks/CTR/feed-health/product-eligibility evidence.
- Do not expose credentials, OAuth tokens, service account JSON, private keys, or `.env` values.
