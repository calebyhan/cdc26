# 01 · Data Sources

Every source gets a **point-in-time rule**: the earliest date its data could have been known publicly. Features at scoring month *t* may only use data available before *t*. This rule is what keeps the backtest honest.

**Spike status.** CCDB, enforcement actions, and FDIC BankFind were tested live on 2026-09-26. Details, limits, and gotchas are in [FINDINGS.md](../FINDINGS.md). The HMDA follow-up measured 2017–2025 snapshot sizes and inspected Reporter Panels; see [FINDINGS §9](../FINDINGS.md#9-hmda-spike-and-m0-ingestion-validation-2026-09-26). GLEIF, FFIEC NIC, and FR Y-9C have **not been spiked yet**.

## Summary

| Source | Role | Grain | Key IDs | Point-in-time rule | Spiked? |
|---|---|---|---|---|---|
| CFPB complaints (CCDB) | Behavioral signal | Complaint | `Company` (text), `Complaint ID` | Use `Date received` plus a 1-month lag, which covers the publication delay and the ~15-day window for company responses | ✅ |
| CFPB enforcement actions | Target (event) | Action × party | Slug; party name (text) | Event date is the filing date shown on the listing | ✅ |
| FDIC BankFind Suite | Bank size, holding company, mergers | CERT × quarter | CERT (int), FED_RSSD, RSSDHCR | Call Report quarter `REPDTE` counts as known about 45 days later. Lag by one full quarter | ✅ |
| HMDA | Mortgage-activity denominator | Loan application | LEI (2018+), Respondent ID + Agency (pre-2018) | Year-Y data counts as known from its public release date in the following year. Record the date per vintage | ✅ (metadata/panels) |
| GLEIF | LEIs, parents | Legal entity | LEI | Relationship validity dates | ❌ |
| FFIEC NIC | Ownership structure, mergers | Entity, relationship | RSSD | Start and end dates | ❌ |
| FR Y-9C | Holding-company financials | BHC × quarter | RSSD | Lag by one quarter | ❌ |

## CFPB Consumer Complaint Database

**Access (verified):**
- **History:** bulk `complaints.csv.zip` (348 MB zipped, 5.46 GB unzipped, regenerated daily). Load it once into Parquet.
- **Daily delta:** the search API at `…/search/api/v1/` (the **trailing slash is required**). Page with `search_after`, since offset paging caps at 10,000. Anonymous use is limited to about 20 requests per minute.
- **Every day, re-pull the trailing 30 days** and upsert on `Complaint ID`. `company_response` changes from "In progress" to its final value after ingestion.
- The JSON bulk file (`complaints.json.zip`) and the `/trends` and `/geo/states` endpoints have been removed. They now return 404 or the HTML search page with HTTP 200. Compute trends from our own tables.

**Fields:** the 15 columns listed in FINDINGS §1.3. The fields `complaint_what_happened` (narrative), `consumer_consent_provided`, and `consumer_disputed` **no longer exist**.

**Known issues:**
- The API and the bulk file encode nulls and dates differently. Normalize both into one staging schema.
- **Always check that the response is `Content-Type: application/json`.** Removed endpoints and URLs without the trailing slash return HTML with a 200 status. Unknown parameters are silently ignored.
- `Complaint ID` is **not chronological**. Sort by `Date received`.
- Issue labels **and** response labels changed in 2017. Mortgage data contains the old values `Closed with relief`, `Closed without relief`, and `Closed`. Both need crosswalks.
- `Company` is holding-company level for most big banks, charter level for others (e.g. `BANK OF AMERICA, NATIONAL ASSOCIATION`). One brand can appear as several strings.
- About 5% of ZIP codes are masked to 3 digits. Use `State` for geography.
- **Backtest caveat:** the bulk file holds each complaint's *current* `company_response`, not the value at the time. Responses settle within about 15 days, so the 1-month lag makes this negligible.

## CFPB enforcement actions

**Access (verified):** there is no JSON API or usable feed. The RSS feed returns only the latest 25 actions and has unreliable categories. We scrape the HTML listing (16 pages, 386 actions) and each detail page, with a 1-second delay between requests.
- **Pagination trap:** an out-of-range page returns a populated page, not an error. Stop when a page contributes no new slugs, and check the total against the "386 filtered results" count shown on the page.

**Fields per action:** name/caption, slug (our action ID), date filed, forum (Administrative Proceeding / Civil Action), docket number, status, products (multi-valued, a 21-value taxonomy), summary text, and document links. Dollar amounts are **not structured**.

**Hand-labeled file:** `data/reference/enforcement_labels.csv`

| Column | Description |
|---|---|
| `slug` | Action ID taken from the URL |
| `party_raw` | One row per party after splitting the caption (see 03) |
| `party_kind` | company / individual / non_entity. "et al." and "45 real estate brokerage affiliates" are dropped from matching |
| `entity_id` | Canonical ID, filled in after resolution |
| `date_filed` | Event date |
| `forum` | |
| `products` | Enforcement taxonomy, as scraped |
| `mortgage_related` | bool. Derived from mortgage-type product tags and confirmed by reading the summary |
| `status`, `status_checked_on` | As shown on the page at scrape time |
| `source_url` | |

**Volume by year:** 8, 27, 32, 55, 42, 37, 11, 22, 48, 18, 20, 29, 28, 9, 0 (2012 → 2026). The last filing was on 2025-08-21.

**Status is not a merit label.** Several early-2025 actions show `Expired/Terminated/Dismissed`, for reasons we have not investigated. The event is the **filing**, regardless of later status (see [05_modeling.md](05_modeling.md)).

## FDIC BankFind Suite

**Access (verified):** `https://api.fdic.gov/banks/…` requires no API key. One call returns the full active roster (4,231 banks) with `limit=10000`. Use `/financials` for quarterly history and `/history` for mergers and name changes.

**Gotchas:**
- Dollar amounts are in **thousands of USD**.
- `EQ`, `FED_RSSD`, and `RSSDHCR` come back as strings, `CERT` as an int. Cast them explicitly.
- **Key on CERT, never on name.** 205 active bank names are shared by more than one bank.
- `NAME` is a keyword field: exact match or wildcard only. Partial phrases return nothing.
- Holding-company names (`NAMEHCR`) use Fed-style abbreviations (`U S BCORP`, `WELLS FARGO&COMPANY`, `…GROUP INC THE`). 683 active banks have no holding company.
- **Banks only.** No credit unions and no nonbanks. For the mortgage scope, that means none of the large nonbank servicers.

**Fields for MVP 1:** `ASSET`, `DEP`, `EQ`, residential real-estate loans, noncurrent loans, provisions (from `/financials`), `REPDTE`, `RSSDHCR`, `NAMEHCR`, and merger history from `/history`.

## HMDA (M0 metadata and Reporter Panel spike complete)

- **Access:** the FFIEC/CFPB HMDA data browser and bulk files. We need the Transmittal Sheet / Reporter Panel (lender identity, parent RSSD) and lender-year counts aggregated from the loan-level LAR data.
- **Aggregate to lender × year:** applications, originations, denial rate, purchase vs. refinance mix, top-state share, number of states.
- **Identifier break:** LEI starts with 2018 data. Earlier years use Respondent ID + Agency Code, bridged through the Reporter Panel and RSSD.
- **Known gap:** HMDA measures originations, not servicing (see ADR-007).
- **Verified in M0:** 2017–2025 snapshot ZIP sizes and panel schemas, plus vintage-specific public-release evidence, are in FINDINGS §9. LAR ZIPs range from 156 MB to 1.52 GB; expanded recent vintages reach 10.2 GB.
- **Identity gaps:** the official snapshot manifest marks the 2024/2025 Reporter Panels unavailable. Nonbank RSSDs are incomplete even in 2023 (e.g. Rocket is populated, Nationstar is missing). Preserve LEI and use reviewed, dated supplementary links.
- **Remaining M3 work:** full LAR aggregation and pre-2017 archive retrieval. Do not equate the snapshot freeze date or S3 Last-Modified with public availability, or backdate revised datasets.

## GLEIF, FFIEC NIC, FR Y-9C (not yet spiked)

The FDIC fields `RSSDHCR` and `/history` already cover holding-company rollup and mergers for banks. Given that, these three sources are **optional** for MVP 1. Add them only if M2 shows gaps: NIC for pre-merger holding-company history, GLEIF for nonbank parents, Y-9C for consolidated capital ratios.

## Storage

All sources land in `data/raw/` untouched, are converted once to typed Parquet in `data/staging/`, and are queried with DuckDB. We never edit raw files.
