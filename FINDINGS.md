# Data Source Spike: CFPB Complaint Early-Warning System

**Investigated:** 2026-09-26 · **Scope:** feasibility, schema, and gotchas for the three sources. Original spike scope; M0 ingestion and HMDA follow-up are recorded in §9.
Every number below comes from live calls made on this date unless marked *(from docs/source)*. Runnable code is in [`spike/`](spike/).

---

## TL;DR: what changes the plan

1. **Complaint narratives are gone from the live API and the bulk file.** On **2026-08-14** the CFPB stopped publishing narratives. The API code that served them was deleted on 2026-08-18 ([ccdb5-api PR #256](https://github.com/cfpb/ccdb5-api/pull/256), "Remove narratives"). **0/1,000 sampled API rows** have a narrative, and `has_narrative=true` is **silently ignored**. Older narratives survive only in a **frozen FOIA archive** (21 zip files, 1.43 GB, Dec 2011 → Aug 14 2026). There, 32.7% of Jan–Feb 2025 complaints have text. **Any live early-warning signal must use structured fields only.** NLP is limited to historical backtesting.
2. **The `/geo/states` and `/trends` endpoints were removed** in the same commit series. They now return the HTML search page with **HTTP 200**. Replace them with aggregations (`size=0`) sliced by date. That works, and the request shape is shown below.
3. **Three credit bureaus account for 84–88% of complaints in 2024–2026** (78% all-time), and volume has exploded: 2.73M in 2024, 5.44M in 2025, and 5.34M already in 2026 YTD. Raw complaint counts are dominated by bureau noise. Model bureaus separately or exclude them.
4. **CFPB enforcement has gone quiet.** The newest action was filed **2025-08-21**, with **zero filings in the last 13 months** and 9 in all of 2025. There is no JSON API, so the data has to be scraped (386 actions total). As a supervised label, enforcement is sparse and the regime has shifted. Use it for **historical backtesting (2012–2025)**, not as a live target.
5. **FDIC BankFind works with no API key.** It returns all 4,231 active banks in one call. It covers **banks only**: no credit unions, nonbanks, or bureaus. CERT is the stable key.
6. **Entity resolution is tractable because the universe is small.** The **top 200 CCDB companies cover 96.3% of complaints.** The core mismatch is that CCDB names **holding companies**, while FDIC and enforcement name **bank charters**. Naive fuzzy matching produced **7 false positives among the top 40 companies**. Recommendation: normalization plus blocked `rapidfuzz` scoring as candidate generation, and a **hand-curated alias table for about the top 150 companies**.

---

## 1. CFPB Consumer Complaint Database (CCDB)

### 1.1 Access method that worked

**Base URL (the trailing slash is mandatory):**
`https://www.consumerfinance.gov/data-research/consumer-complaints/search/api/v1/`

```bash
# 500 most recent complaints received in June 2025 (JSON)
curl 'https://www.consumerfinance.gov/data-research/consumer-complaints/search/api/v1/?size=500&sort=created_date_desc&no_aggs=true&date_received_min=2025-06-01&date_received_max=2025-06-30'
```

```python
# spike/ccdb_sample.py (abridged): deep pagination with search_after
import requests, time
API = "https://www.consumerfinance.gov/data-research/consumer-complaints/search/api/v1/"

def iter_all(page_size=1000, **filters):
    after = None
    while True:
        p = dict(size=page_size, sort="created_date_desc", no_aggs="true", **filters)
        if after: p["search_after"] = after
        hits = requests.get(API, params=p, timeout=180).json()["hits"]["hits"]
        if not hits: return
        yield from (h["_source"] for h in hits)
        after = f"{hits[-1]['sort'][0]}_{hits[-1]['sort'][1]}"   # "<epoch_ms>_<complaint_id>"
        time.sleep(3.1)                                         # anon limit is 20 req/min
```

**Bulk file:** `https://files.consumerfinance.gov/ccdb/complaints.csv.zip`. It is **348 MB zipped** and was regenerated daily (`Last-Modified: Sat, 26 Sep 2026 09:16 GMT`). The JSON variant (`complaints.json.zip`) now returns **404**.

**Recommended ingestion:** load the bulk CSV once into DuckDB/Parquet for history, then pull a daily delta from the API with `date_received_min=<yesterday>` and `search_after`.

### 1.2 Limits: documentation vs. reality

| Limit | Swagger spec says | Live / source code says | Verified how |
|---|---|---|---|
| `size` per request | max 100 | **10,000 accepted** (serializer allows 100,000) | `size=10000` → 10,000 hits, 6.6 MB, 11.6 s |
| `frm` (offset) | max 100,000 | **max 10,000** | `frm=10001` → `400 {"frm": ["Ensure this value is less than or equal to 10000."]}` |
| Beyond 10k rows | not documented | `search_after=<sort0>_<id>` works | page 2 continued correctly from page 1 |
| CSV export (`format=csv`) | "frm/size ignored" | **hard cap 100,000 rows** (`MAX_DOWNLOAD_SIZE`) | 412k-row query → `400`, body is just `size` (unhelpful). 1,476-row query → 200 CSV |
| Rate limit, search | not documented | **20/min anonymous** *(source: `complaint_search/throttling.py`)* | not triggered in ~30 calls spaced over minutes |
| Rate limit, export | not documented | **2/min anonymous** *(source)* | — |
| Rate limit, single doc `/{id}` | not documented | **5/min** *(source)* | — |
| Company aggregation buckets | not documented | **capped at 6,500** (`AGG_COMPANY_DEFAULT`) | all-time query → 6,500 buckets, 1,849 docs in `sum_other_doc_count`. Per-year queries avoid the cap (max 3,968/year) |

**So is the 100k cap real?** Yes, for **CSV export** (`format=csv`). The JSON search API has a different limit: 10k via offset, and **unlimited via `search_after`** at 20 req/min. That is roughly 10k rows × 20 = 200k rows/min in theory, though large pages take about 10 s each.

### 1.3 Confirmed schema

The JSON `_source` always has exactly these 15 keys. The CSV export and bulk file have the same 15 columns in a different order and with display names.

| API key | CSV header | Coverage in 500-row sample (June 2025) | Notes |
|---|---|---|---|
| `date_received` | Date received | 100% | API: `2025-06-30T23:45:02.000Z` (real time of day). Bulk: `2025-06-30` (date only) |
| `product` | Product | 100% | 21 values all-time. "Credit reporting or other personal consumer reports" = 91% of 2026 YTD |
| `sub_product` | Sub-product | 100% | 5% are "I do not know" |
| `issue` | Issue | 100% | |
| `sub_issue` | Sub-issue | 99% | |
| `company_public_response` | Company public response | 58% | 98% of those are boilerplate ("chooses not to provide a public response") |
| `company` | Company | 100% | see §1.6 |
| `state` | State | 100% | includes PR, VI, GU, AS, MP, PW, military AA/AE/AP, and the literal string `"UNITED STATES MINOR OUTLYING ISLANDS"` |
| `zip_code` | ZIP code | 100% present | **4.6% masked to 3 digits**, e.g. `"083XX"` (ZCTA population < 20k) |
| `tags` | Tags | 2.4% | `Servicemember`, `Older American`. Single string, not a list |
| `submitted_via` | Submitted via | 100% | 99.6% "Web" |
| `date_sent_to_company` | Date sent to company | 100% | |
| `company_response` | Company response to consumer | 100% | **98.8% "In progress" for complaints under 1 day old.** Values mutate after ingestion |
| `timely` | Timely response? | 100% | **99.4–99.7% "Yes"**, so a weak signal |
| `complaint_id` | Complaint ID | 100% | string in JSON, int in docs. **Not chronological** (bulk rows from 2023 have IDs around 7.6M, June 2025 around 14.4M, today around 28.3M) |

**Fields that no longer exist:** `complaint_what_happened` (narrative), `consumer_consent_provided`, `has_narrative`, `consumer_disputed`. Using `field=complaint_what_happened` returns `400 "not a valid choice"`.

**Real sample row** (`GET …/v1/?…`, complaint 14383496):

```json
{
  "product": "Credit reporting or other personal consumer reports",
  "sub_product": "Credit reporting",
  "issue": "Incorrect information on your report",
  "sub_issue": "Information belongs to someone else",
  "company": "Experian Information Solutions Inc.",
  "state": "FL",
  "zip_code": "33993",
  "tags": "Servicemember",
  "company_response": "Closed with explanation",
  "company_public_response": "Company has responded to the consumer and the CFPB and chooses not to provide a public response",
  "timely": "Yes",
  "submitted_via": "Web",
  "complaint_id": "14383496",
  "date_received": "2025-06-30T23:45:02.000Z",
  "date_sent_to_company": "2025-07-01T00:52:46.000Z"
}
```

### 1.4 Narratives (free text)

| Where | Narrative available? | Evidence |
|---|---|---|
| Live search API | **No** | 0/500 (Sept 2026) and 0/500 (June 2025). `has_narrative=true` ignored: `hits.total` unchanged at 18,023,390 |
| Bulk `complaints.csv.zip` | **No** | header has 15 columns, no narrative column |
| CSV export (`format=csv`) | **No** | same 15 columns |
| [FOIA Narratives Archive](https://www.consumerfinance.gov/foia-requests/foia-electronic-reading-room/cfpb-consumer-complaint-database-narratives-archive/) | **Yes, frozen** | 21 zips `CCDB_Export_{1..21}_*.zip`, 1.43 GB total, 16 columns (includes `Consumer complaint narrative`) |

Narrative coverage in the archive, measured on two files:

| Archive file | Rows | With narrative | Notes |
|---|---|---|---|
| Jan–Feb 2025 | 811,019 | **265,405 (32.7%)** | **59.1% for non-bureau companies.** Median 660 chars, p90 1,898. 50% contain `XXXX` redactions |
| Aug 2026 | 667,140 | **1 (0.0%)** | Narratives were published with a lag, so recent months are essentially empty |

By product (Jan–Feb 2025): Money transfer 82.8%, Checking/savings 71.7%, Mortgage 58.9%, Credit card 45.5%, Debt collection 37.4%, Credit reporting 25.9%.

Context: [CFPB announcement, 2026-08-14](https://www.consumerfinance.gov/about-us/newsroom/the-cfpb-to-cease-discretionary-publication-of-complaint-narratives-and-visualizations/). The CFPB also removed the consent option, so **no new narratives will be published**.

### 1.5 Geo and trend aggregation (replacing the removed endpoints)

`/geo/states` and `/trends` (with or without a trailing slash) now return the **HTML search UI with HTTP 200**. They were removed in ccdb5-api commit `1bec7b5` ("clean out remaining geo and trends work", 2026-08-18). **Replacement:** `size=0` returns only aggregations over whatever filter set you pass.

```bash
# State counts for 2025 (replaces /geo/states)
curl '…/v1/?size=0&date_received_min=2025-01-01&date_received_max=2025-12-31'

# One company's monthly count + product mix (replaces /trends): loop over months
curl '…/v1/?size=0&company=WELLS%20FARGO%20%26%20COMPANY&date_received_min=2025-01-01&date_received_max=2025-01-31'
```

Response shape. Aggregation keys observed: `product, issue, timely, company_response, submitted_via, company, state, company_public_response, tags`.

```json
{
  "hits": {"total": {"value": 5442963, "relation": "eq"}, "hits": []},
  "aggregations": {
    "state": {
      "doc_count": 5442963,
      "state": {
        "doc_count_error_upper_bound": 0,
        "sum_other_doc_count": 0,
        "buckets": [{"key": "FL", "doc_count": 791234}, {"key": "TX", "doc_count": 789898}]
      }
    }
  },
  "_meta": {"last_indexed": "2026-09-26T12:00:00-05:00", "total_record_count": 18023390,
            "is_data_stale": false, "has_data_issue": false, "license": "CC0"}
}
```

Note the **double nesting**: `aggregations[field][field]["buckets"]`. A full monthly trend for all companies back to 2011 via the API is about 190 calls, roughly 10 minutes at 20/min. **Computing trends from the bulk CSV is simpler.**

### 1.6 Company-name formatting (CCDB)

- **8,130 distinct company strings** all-time (enumerated per year to dodge the 6,500-bucket cap).
- **Mixed casing, with no rule:** 1,409 names are ALL-CAPS, and those carry 65% of complaint volume (the large institutions). Examples: `WELLS FARGO & COMPANY` vs `Experian Information Solutions Inc.` vs `PNC Bank N.A.`
- **Mostly holding-company level for big banks, but inconsistent:** `JPMORGAN CHASE & CO.`, `U.S. BANCORP`, `CAPITAL ONE FINANCIAL CORPORATION`, and `TD BANK US HOLDING COMPANY` are holding companies. `BANK OF AMERICA, NATIONAL ASSOCIATION`, `CITIBANK, N.A.`, `DISCOVER BANK`, and `GOLDMAN SACHS BANK USA` are bank charters.
- Suffix counts: `Inc` 2,730 · `LLC` 2,392 · `&` 722 · `Corp` 680 · `dba` 150 · `L.P.` 42 · `N.A.` only 6.
- Punctuation noise: `National Credit Systems,Inc.` (no space), `Navient Solutions, LLC.` (trailing period), `Global Tel*Link Corporation`, `Populus Financial Group, Inc. (F/K/A Ace Cash Express)`.
- One brand can map to several strings. Santander has 4: `SANTANDER HOLDINGS USA, INC.`, `Santander Consumer USA Holdings Inc.`, `SANTANDER BANK, NATIONAL ASSOCIATION`, `SANTANDER BANCORP`.
- Name changes are not merged: Wise appears as `TransferWise Ltd`, and PHEAA as `AES/PHEAA`.

### 1.7 Volume and update frequency

| Period | Complaints | Bureau share (Equifax + TransUnion + Experian) |
|---|---|---|
| All-time (Dec 2011 → 2026-09-26) | 18,023,390 | 77.9% |
| 2024 | 2,734,269 | 84.1% |
| 2025 | 5,442,963 | 85.8% |
| 2026 YTD (to 09-26) | 5,341,003 | 88.2% |

**Updated daily.** `_meta.last_indexed` was today, and the bulk file was regenerated today. `_meta.is_data_stale` flags loads more than 5 business days old.

### 1.8 Data-quality issues and gotchas

1. **Missing trailing slash (`…/v1?size=1`) returns the HTML search page with HTTP 200**, not an error. Always assert `Content-Type: application/json`.
2. **`format=json` returns 404** (Django REST framework reserves `format`). Omit it, since JSON is the default.
3. **Unknown or removed parameters are silently ignored** (`has_narrative`). Your filter may be doing nothing.
4. **`company_response` mutates** from "In progress" to its final value after ingestion (companies get about 15 days to respond, per CFPB process). Re-pull the trailing 30 days daily (upsert on `complaint_id`) or you will freeze stale labels.
5. **Null encoding differs by channel:** JSON `null`, the bulk CSV uses an empty string, and the **export CSV uses the literal string `"None"`**.
6. **Date formats differ by channel:** API/export use ISO timestamps with time of day, while the bulk file uses `YYYY-MM-DD`.
7. **The bulk file is not sorted by date** (first data row is from 2023).
8. **The export over-cap error body is just `size`** with a 400. Detect it and split the date range.
9. Volume doubled 2024→2025, almost entirely in credit reporting. Cause not investigated; possibly templated or credit-repair-driven filings. Treat as a **structural break**.
10. `timely` is about 99.7% "Yes". Use it only as a rare-event flag ("No" / "Untimely response"), not a continuous feature.

---

## 2. CFPB Enforcement Actions

### 2.1 Access method that worked: HTML scraping

| Tried | Result |
|---|---|
| Wagtail API `/api/v2/pages/…` | 404 |
| `?format=json`, `?format=csv` on the listing | ignored (returns HTML) |
| RSS `https://www.consumerfinance.gov/enforcement/actions/feed/` | **works, but only the latest 25**. `<category>` is unreliable: Synapse is tagged "Reverse mortgages", Wise "Servicemembers" |
| **HTML listing + detail pages** | **works.** 25 per page, 16 pages, 386 actions, about 1 minute with a 1 s delay |

Listing filters (GET params taken from the page's form; **not individually tested**): `title`, `categories` (Administrative Proceeding / Civil Action), `statuses`, `products`, `from_date`, `to_date`, `page`.

```python
# spike/enforcement_scrape.py (abridged)
soup = BeautifulSoup(requests.get(LISTING, params={"page": page}).text, "html.parser")
for card in soup.select("article.o-post-preview"):
    a = card.select_one(".o-post-preview__title a")          # name + /enforcement/actions/<slug>/
    date = card.select_one("time")["datetime"][:10]           # "2025-08-21"
    desc = card.select_one(".o-post-preview__description")    # one-sentence summary
# detail page: key/value blocks
for box in detail.select(".m-related-metadata__item-container"):
    key = box.find("h3").get_text(strip=True)                 # Forum | Docket number | Initial filing date | Status | Products
    tags = [t.get_text(strip=True) for t in box.select(".a-tag-topic__text")]   # Products (multi)
```

**Pagination gotcha:** an out-of-range `?page=99` **returns a populated page, not an empty one or a 404.** My first version looped forever. The fixed scraper stops when a page adds no new slugs and cross-checks against the "386 filtered results" text.

### 2.2 Fields (20 most recent detail pages)

| Field | Source | Coverage | Example |
|---|---|---|---|
| Name (respondent caption) | listing `<h3>` / detail `<h1>` (identical in 20/20) | 20/20 | `Goldman Sachs Bank USA` |
| Slug (use as ID) | URL | 20/20 | `goldman-sachs-bank-usa`. Repeat respondents get suffixes (`td-bank-na-furnishing-2024`) |
| Date filed | listing `<time datetime>` | 20/20 | `2024-10-23` |
| Forum (category) | detail | 20/20 | `Administrative Proceeding` (10) / `Civil Action` (10) |
| Docket number | detail | 20/20 | `2024-CFPB-0011` |
| Status | detail | 20/20 | `Post Order/Post Judgment` 9, `Expired/Terminated/Dismissed` 9, `Pending Litigation` 2 |
| Products (multi-valued) | detail tags | 20/20 | `["Credit Cards", "Furnishing"]` (21-value taxonomy, **different from CCDB's**) |
| Summary text | detail body | 20/20 | 1–4 paragraphs |
| Related documents (PDFs) | detail | 20/20 | consent order + stipulation |
| **Dollar amounts** | **not structured.** Regex over summary only | 14/20 mention `$` | noisy: `$950,000 million` (typo on source page), and penalty vs. redress is not distinguished |

**Real sample record** (from `spike/data/enforcement_details.json`):

```json
{
  "name": "Goldman Sachs Bank USA",
  "slug": "goldman-sachs-bank-usa",
  "date_filed": "2024-10-23",
  "forum": "Administrative Proceeding",
  "docket_number": "2024-CFPB-0011",
  "status": "Post Order/Post Judgment",
  "products": ["Credit Cards", "Furnishing"],
  "summary": "On October 23, 2024, the Bureau issued an order against Goldman Sachs Bank USA (Goldman). In December 2017, Goldman and Apple Inc. entered an agreement to offer Apple Card…",
  "dollar_mentions": ["$19.8 million", "$45 million", "$25 million", "$89 Million"],
  "document_links": ["https://files.consumerfinance.gov/f/documents/cfpb_goldman-sachs-bank-usa-consent-order_2024-10.pdf", "…stipulation_2024-10.pdf"]
}
```

### 2.3 Volume and update frequency

386 actions, from 2012-07-17 to **2025-08-21**. Updates are event-driven, and there has been **no new action in 13 months**.

| 2012 | 2013 | 2014 | 2015 | 2016 | 2017 | 2018 | 2019 | 2020 | 2021 | 2022 | 2023 | 2024 | 2025 | 2026 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 8 | 27 | 32 | 55 | 42 | 37 | 11 | 22 | 48 | 18 | 20 | 29 | 28 | 9 | **0** |

Several early-2025 actions already show `Expired/Terminated/Dismissed`, including Capital One (filed 2025-01-14), Vanderbilt Mortgage, and Walmart/Branch. I did not investigate why. **"Status" is not a clean "company did something wrong" label.**

### 2.4 Name formatting (enforcement) vs. CCDB

- **Legal bank-charter level, mixed case:** `Wells Fargo Bank, N.A.`, `JPMorgan Chase Bank, N.A.`, `TD Bank, N.A.`. CCDB uses the holding company for the same institutions: `WELLS FARGO & COMPANY`, `JPMORGAN CHASE & CO.`, `TD BANK US HOLDING COMPANY`.
- **Multi-party captions:** 131 of 386 contain " and " (nearly all are multi-party; a few are names like "Bank and Trust"). Separators vary: `;`, `, and`, `; and`. Example: `Early Warning Services, LLC; Bank of America, N.A.; JPMorgan Chase Bank, N.A.; Wells Fargo Bank, N.A`
- **Aliases inline:** `d/b/a`, `dba`, `f/k/a`, `a/k/a`, `(N/K/A …)`. Examples: `Nationstar Mortgage, LLC d/b/a Mr. Cooper`, `Synchrony Bank, f/k/a GE Capital Retail Bank`.
- **Individuals and non-entities in captions:** `Jason Mitchell`, `45 real estate brokerage affiliates`, `et al.`, `other subsidiaries`.
- **Inconsistent across the same bank's actions:** `Fifth Third Bank`, `Fifth Third Bank, N.A.`, and `Fifth Third Bank, National Association`. Also `Wells Fargo Bank, N.A` (missing period).
- **Subsidiary names CCDB doesn't use:** `Trans Union LLC` / `TransUnion Interactive, Inc.` vs CCDB's `TRANSUNION INTERMEDIATE HOLDINGS, INC.`, and `Equifax Information Services LLC` vs `EQUIFAX, INC.`

---

## 3. FDIC BankFind Suite API

### 3.1 Access method that worked

**No API key required: confirmed.** Every call in this spike was made without a key. The spec lists `api_key` as an optional query param.

```bash
# Exact-name filter (NAME is an Elasticsearch *keyword* field → exact match)
curl 'https://api.fdic.gov/banks/institutions?filters=NAME:"Truist Bank"&fields=NAME,CERT,ASSET,DEP,EQ,REPDTE,NAMEHCR,RSSDHCR'

# Entire active roster in one call (4,231 rows)
curl 'https://api.fdic.gov/banks/institutions?filters=ACTIVE:1&fields=NAME,CERT,FED_RSSD,ASSET,DEP,EQ,REPDTE,CITY,STALP,NAMEHCR,RSSDHCR,WEBADDR&limit=10000&sort_by=ASSET&sort_order=DESC'

# Mergers / name changes for a CERT (Discover → Capital One)
curl 'https://api.fdic.gov/banks/history?filters=CERT:5649&fields=INSTNAME,CHANGECODE_DESC,EFFDATE,SUR_INSTNAME&sort_by=EFFDATE&sort_order=DESC&limit=5'
```

**Query syntax** (`filters` is Elasticsearch query_string):

| Want | Syntax | Verified result |
|---|---|---|
| Exact name | `NAME:"Truist Bank"` | 1 hit |
| Partial phrase | `NAME:"Wells Fargo"` | **0 hits** (keyword field, not full-text) |
| Wildcard | `NAME:Truist*` or `NAME:TRUIST*` | 1 hit. **Case-insensitive in practice**, although the docs say "must be UPPERCASE" |
| Boolean / range | `STALP:IA AND ACTIVE:1`, `DEP:[50000 TO *]`, `!(STNAME:"Virginia")` | *(from docs)* |
| Fuzzy name search | `search=NAME:TRUIST` (a separate param) | 3,192 hits, relevance-ordered (Truist first, then "Northern **Trust**"). **Combining it with `sort_by=ASSET` put JPMorgan at the top for "TRUIST".** |
| Paging | `limit` (max 10,000), `offset` | |
| Format | JSON by default; CSV via `Accept` header / `format` | |

Endpoints: `/institutions`, `/locations`, `/history`, `/financials`, `/summary`, `/failures`, `/sod`, `/demographics`.

**Rate limits:** responses carry `x-ratelimit-limit: 20`, but `x-ratelimit-remaining` stayed at **19 across about 30 calls**, including an 8-call burst. No 429 was ever returned, and the docs say nothing about a window. **Assumption:** this is a per-second limit. It doesn't matter much here, because the whole roster is one call.

### 3.2 Confirmed fields and units

`ASSET`, `DEP`, `EQ` are in **thousands of USD** *(docs: "`DEP:[50000 TO *]` = deposits over 50,000,000")*. Sanity check: Wells Fargo `ASSET` = 1,907,928,000, i.e. $1.91T.

**Real sample row** (Wells Fargo):

```json
{"NAME": "Wells Fargo Bank, National Association", "CERT": 3511, "FED_RSSD": "451965",
 "ASSET": 1907928000, "DEP": 1563534000, "EQ": "169518000", "REPDTE": "06/30/2026",
 "ACTIVE": 1, "CITY": "Sioux Falls", "STALP": "SD",
 "NAMEHCR": "WELLS FARGO&COMPANY", "RSSDHCR": "1120754", "WEBADDR": "www.wellsfargo.com"}
```

| Bank | CERT | Total assets ($K) | Deposits ($K) | Equity ($K) | NAMEHCR |
|---|---|---|---|---|---|
| JPMorgan Chase Bank, National Association | 628 | 4,091,315,000 | 2,820,284,000 | 341,580,000 | `JPMORGAN CHASE&CO` |
| Bank of America, National Association | 3510 | 2,654,645,000 | 2,121,804,000 | 240,789,000 | `BANK OF AMERICA CORP` |
| Wells Fargo Bank, National Association | 3511 | 1,907,928,000 | 1,563,534,000 | 169,518,000 | `WELLS FARGO&COMPANY` |

### 3.3 Volume and update frequency

- **4,231 active institutions.** Inactive and merged institutions remain queryable with `ACTIVE:0`.
- Financials are **quarterly Call Report data**. `REPDTE` = `06/30/2026` for 4,220 banks (format `MM/DD/YYYY`). The index is rebuilt daily (`institutions_20260925090006`).

### 3.4 Data-quality issues and gotchas

1. **Inconsistent types:** `ASSET`/`DEP` are ints, but **`EQ` is a string**. `FED_RSSD` and `RSSDHCR` are strings, `CERT` is an int. Cast explicitly.
2. **Name is not a key: 205 names are shared by more than one active bank** (`Pinnacle Bank`, `City National Bank`, `United Bank`, …). Always key on `CERT`.
3. **15 names contain double spaces** (`American Express National  Bank`).
4. **683 active banks have an empty `NAMEHCR`** (no holding company, e.g. `Comenity Bank`).
5. **Coverage gaps for this project:** no credit unions (Navy Federal and VyStar are NCUA-insured) and no nonbanks (bureaus, servicers, collectors, fintechs), which together are the bulk of CCDB volume.
6. **M&A:** `Discover Bank` (CERT 5649) merged into Capital One, N.A. on **2025-05-18**. `Comerica Bank` (CERT 983) merged into Fifth Third on **2026-02-01**. CCDB still has 44,503 complaints under `DISCOVER BANK`. Use `/history` to map old CERTs to survivors.
7. A few rows (4) have no `REPDTE`/`ASSET`.

### 3.5 Name formatting (FDIC)

- `NAME` is the legal charter name in mixed case. It says `, National Association` 195 times but `N.A.` only 24 times. Examples: `Citibank, National Association`, `U.S. Bank National Association` (no comma).
- `NAMEHCR` (the holding company, which is **the level CCDB usually uses**) is written in **Fed-style upper-case abbreviations**: `U S BCORP`, `PNC FINL SERVICES GROUP INC`, `WELLS FARGO&COMPANY` (no spaces around `&`), `GOLDMAN SACHS GROUP INC THE` (trailing "THE"), `UNITED SERVICES AUTOMOBILE ASSN`, `TORONTO-DOMINION BANK THE`.

---

## 4. Entity resolution

### 4.1 Raw strings for the same real institution across sources

| # | Institution | CCDB `company` | Enforcement caption | FDIC `NAME` | FDIC `NAMEHCR` |
|---|---|---|---|---|---|
| 1 | Wells Fargo | `WELLS FARGO & COMPANY` | `Wells Fargo Bank, N.A.` / `Wells Fargo Bank, N.A` | `Wells Fargo Bank, National Association` | `WELLS FARGO&COMPANY` |
| 2 | JPMorgan Chase | `JPMORGAN CHASE & CO.` | `JPMorgan Chase Bank, N.A.`; older: `Chase Bank, USA N.A. and Chase BankCard Services, Inc.` | `JPMorgan Chase Bank, National Association` | `JPMORGAN CHASE&CO` |
| 3 | Bank of America | `BANK OF AMERICA, NATIONAL ASSOCIATION` | `Bank of America, N.A.` | `Bank of America, National Association` | `BANK OF AMERICA CORP` |
| 4 | Capital One | `CAPITAL ONE FINANCIAL CORPORATION` | `Capital One, National Association, and Capital One Financial Corporation`; 2012: `Capital One Bank` | `Capital One, National Association` | `CAPITAL ONE FINANCIAL CORP` |
| 5 | U.S. Bank | `U.S. BANCORP` | `U.S. Bank National Association` | `U.S. Bank National Association` | `U S BCORP` |
| 6 | Citi | `CITIBANK, N.A.` | `Citibank, N.A.` | `Citibank, National Association` | `CITIGROUP INC` |
| 7 | TD Bank | `TD BANK US HOLDING COMPANY` | `TD Bank, N.A.` | `TD Bank, National Association` (+ `TD Bank USA, National Association`) | `TORONTO-DOMINION BANK THE` |
| 8 | Fifth Third | `FIFTH THIRD FINANCIAL CORPORATION` | `Fifth Third Bank` / `Fifth Third Bank, N.A.` / `Fifth Third Bank, National Association` | `Fifth Third Bank, National Association` | `FIFTH THIRD BCORP` |
| 9 | Citizens | `CITIZENS FINANCIAL GROUP, INC.` | `Citizens Bank, N.A.`; 2015: `RBS Citizens Financial Group, Inc. ( N/K/A) Citizens Financial Group, Inc.), RBS Citizens, N.A. …` | `Citizens Bank, National Association` (+ unrelated `Citizens Bank` ×N) | `CITIZENS FINANCIAL GROUP INC` |
| 10 | Discover | `DISCOVER BANK` | `Discover Bank, The Student Loan Corporation, and Discover Products, Inc.` | `Discover Bank` (**ACTIVE=0**, merged into Capital One 2025-05-18) | — |
| 11 | TransUnion *(nonbank)* | `TRANSUNION INTERMEDIATE HOLDINGS, INC.` | `TransUnion; Trans Union, LLC; TransUnion Interactive, Inc.; and John T. Danaher` | not in FDIC | — |
| 12 | Navy Federal *(credit union)* | `NAVY FEDERAL CREDIT UNION` | `Navy Federal Credit Union` | not in FDIC (NCUA) | — |

**Patterns:** (a) holding company vs. bank charter; (b) `N.A.` / `National Association` / nothing; (c) casing; (d) `&` spacing; (e) Fed abbreviations (`BCORP`, `FINL`, `ASSN`); (f) trailing `THE`; (g) `TransUnion` vs `Trans Union`; (h) multi-party captions; (i) mergers and renames (`TransferWise Ltd` → `Wise US Inc.`).

### 4.2 What the matching spike measured (`spike/entity_match.py`)

**Naive approach** (strip generic words, then `rapidfuzz.fuzz.token_set_ratio ≥ 88`), top 40 CCDB companies against FDIC: **7 confident false positives**, all scoring 100:

| CCDB | Wrongly matched to FDIC |
|---|---|
| Experian Information Solutions Inc. | Solutions Bank |
| Navient Solutions, LLC. | Solutions Bank |
| Resurgent Capital Services L.P. | Capital Bank, National Association |
| ENCORE CAPITAL GROUP INC. | Capital Bank, National Association |
| NAVY FEDERAL CREDIT UNION | Union Bank |
| Fidelity National Information Services | The Fidelity Bank |
| UNITED SERVICES AUTOMOBILE ASSOCIATION | United Bank |

`token_set_ratio` returns 100 whenever one side's tokens are a subset of the other's, so it is unsafe as a sole scorer.

**v2 approach**, the recommended starting point:

1. ASCII-fold and upper-case.
2. Cut at `d/b/a|f/k/a|a/k/a`.
3. `&` → `AND`; `N.A.` / `NATIONAL ASSOCIATION` → `NA`; `U.S.` / `U S` → `US`.
4. Strip punctuation.
5. Expand Fed abbreviations (`FINL→FINANCIAL`, `BCORP→BANCORP`, …).
6. Drop a leading `THE`.
7. **Strip legal/generic tokens only from the tail** (`INC, LLC, CORP, CO, NA, HOLDINGS, GROUP, FINANCIAL, BANK, BANCORP, US, …`).
8. Look up an exact key, else run `token_sort_ratio ≥ 90` **restricted to candidates sharing the first token**.

Results:

- **CCDB top 40 → FDIC:** 15 institutions linked, **0 false positives**. Misses: Bread Financial (FDIC charter is `Comenity Bank`), USAA (FDIC `USAA Federal Savings Bank`), Discover (merged/inactive), Citigroup holding company (CCDB uses the bank name, so the bank-level link was fine). Nonbanks correctly got no match.
- **Enforcement parties (2020+ captions, split into 215 parties) → CCDB:** 98 matched.
  - Spot check found **3 false positives**: `Apple Inc.`→`APPLE FINANCIAL HOLDINGS, INC.`, `Reliant Holdings, Inc.`→`Reliant Financial Corporation`, `United Holdings Group, LLC`→`United Group Inc.`
  - About **15 false negatives** exist in CCDB under a different string: `Wise US Inc.`/`TransferWise Ltd`, `Trans Union LLC`/`TRANSUNION…`, `Equifax Information Services LLC`/`EQUIFAX, INC.`, `Pennsylvania Higher Education Assistance Agency`/`AES/PHEAA`, `MoneyGram International, Inc.`/`MONEYGRAM PAYMENT SYSTEMS WORLDWIDE INC`, `Acima Holdings, LLC`/`ACIMA CREDIT, LLC`, `MoneyLion Technologies Inc.`/`MoneyLion Inc.`, `Trustmark National Bank`/`TRUSTMARK CORPORATION`, `Atlantic Union Bank`/`Atlantic Union Bankshares, Inc.`, and others.
  - The remaining ~100 misses are individuals and small firms with no CCDB presence, which is correct.

### 4.3 Recommended matching approach

The universe that matters is small: 200 CCDB strings cover 96.3% of complaints, and about 115 enforcement parties since 2020 are plausible matches. Fuzzy matching is not accurate enough to run unattended, but it is fast for **proposing** matches. So:

1. **Tables:**
   - `entity(entity_id, display_name, type ∈ {bank, credit_union, nonbank}, fdic_certs[], rssd_hc)`
   - `alias(raw_string, source, entity_id, method ∈ {exact, fuzzy, manual}, score)`

   Every source joins through `alias` on the **exact raw string**.
2. **Automatic tier:** use the `normalize()` from `spike/entity_match.py` for an exact normalized-key match, then `rapidfuzz` `token_sort_ratio` with first-token blocking.
   - Auto-accept at ≥ 95.
   - Queue 85–95 for review.
   - **Do not use `token_set_ratio` / `WRatio` alone.**
3. **Manual tier:** hand-verify about the top 150 CCDB companies and all enforcement matches. That is roughly 1–2 hours and removes the known false positives and false negatives above. Add known renames (`TransferWise`→`Wise`, `AES/PHEAA`) and subsidiaries (`Trans Union LLC`→TransUnion).
4. **Split enforcement captions first:** on `;`, and on `, and` / ` and ` only after a legal suffix, so `State Street Bank and Trust Company` survives. Strip `d/b/a` aliases but keep them as extra alias rows.
5. **FDIC linking at holding-company granularity:** match CCDB against both `NAME` and `NAMEHCR`, then roll charters up by `RSSDHCR` (one holding company can have several CERTs; TD has 2). Resolve mergers with `/history`.
6. **Library:** `rapidfuzz` (MIT license, C++ backed, v3.14.6 verified here). Splink or dedupe would be overkill for about 300 entities.

---

## 5. Join strategy across the three sources

```
CCDB complaints ──(company raw string)──► alias ──► entity ◄──(split party raw string)── enforcement action
                                                     │
                                                     └──(fdic_certs / rssd_hc)──► FDIC quarterly financials
```

- **Analysis grain:** `entity × month` (or week). Complaint features: volume, growth vs. the entity's own baseline, product/issue mix shift, `Untimely response` count, `Closed with monetary relief` share, `Servicemember`/`Older American` share, and state concentration.
- **Normalization:** for banks, complaints per $B of deposits (`DEP` from FDIC, as-of the latest `REPDTE` ≤ month). Nonbanks and credit unions have no FDIC denominator, so use z-scores against their own history.
- **Credit bureaus:** model separately or exclude. They are 84–88% of recent volume (2024–2026) and would swamp every ranking.
- **Enforcement as the outcome:** events are `(entity, date_filed, products[], forum, status)`. Enforcement uses a different product taxonomy (e.g. `Deposits` vs CCDB `Checking or savings account`, `Consumer Reporting Agencies` vs `Credit reporting or other personal consumer reports`), so build a crosswalk of about 20 rows. With 8–55 actions a year historically and **0 since Aug 2025**, the recommended framing is: *"complaint anomalies that preceded historical enforcement (2012–2025)"* as the backtest, and a live anomaly ranking as the product.
- **Narratives:** only for historical features or backtest NLP, from the FOIA archive. Join on `Complaint ID`. The live pipeline has no text.
- **Point-in-time correctness:** CCDB `company_response` updates after ingestion, and FDIC financials are quarterly with a lag. When backtesting, use only data available as of each month.

---

## 6. Assumptions and open questions

- CCDB rate limits come from the open-source server code (`throttling.py`). I did not trigger a 429, and production config could differ.
- The FDIC rate-limit window is undocumented (header `20`, never decremented in testing).
- Narrative coverage (32.7%) was measured on one archive file (Jan–Feb 2025). It varies by period and product.
- Enforcement listing filter parameter names come from the HTML form and were not individually tested.
- The reason for the 2025 complaint-volume doubling and for the dismissed 2025 enforcement actions was not investigated.
- Enforcement "category" is interpreted as **Forum** (Administrative Proceeding / Civil Action), per the listing's "Category" filter.

## 7. Addendum: mortgage subset (MVP 1 scope)

*Added 2026-09-26 from the bulk file (`Product = Mortgage`, 461,350 rows). These numbers differ from the all-product sample in §1.3 and should be used for MVP 1.*

| Field | All-product sample (§1.3) | Mortgage, all-time |
|---|---|---|
| `Timely response? = No` | 0.3–0.6% | **1.9%** (8,656). Still rare, but usable as a count or rate feature |
| `tags` present | 2.4% | **19.6%** |
| Substantive (non-boilerplate) `company_public_response` | ~1% of rows | **10.0%** |
| Top-N company coverage | top 200 = 96.3% | **top 150 = 94.1%, top 290 = 97.0%** |

`company_response` in the mortgage data mixes the current values with **pre-2017 labels** (`Closed with relief` 1,397, `Closed without relief` 10,630, `Closed` 5,686). The relief-share features need a response crosswalk as well as the issue crosswalk.

## 8. Reproduce

```bash
python3 -m venv .venv && .venv/bin/pip install -r spike/requirements.txt
.venv/bin/python spike/ccdb_sample.py          # ~2 min (rate-limited): sample, state counts, 8,130 company names
.venv/bin/python spike/enforcement_scrape.py   # ~1.5 min: 386-action listing + 20 detail pages
.venv/bin/python spike/fdic_sample.py          # seconds: target banks + 4,231-bank roster
.venv/bin/python spike/entity_match.py         # prints match tables + counts
```

Outputs are written to `spike/data/` (about 2 MB). On macOS with python.org Python, use the venv's `requests` (which bundles certifi); stdlib `urllib` failed TLS verification on this machine.

## 9. HMDA spike and M0 ingestion validation (2026-09-26)

### 9.1 Access, file sizes, and reproducibility

`make hmda-spike` runs [`src/ews/ingest/hmda.py`](src/ews/ingest/hmda.py).
It reads the CFPB frontend's [official snapshot manifest](https://github.com/cfpb/hmda-frontend/blob/master/src/data-publication/constants/snapshot-dataset.jsx),
uses HTTP HEAD for compressed size, and HTTP Range requests for ZIP central-directory
uncompressed sizes. It downloads only the small Reporter Panels, **not the national
LAR files**. The exact URLs, byte counts, Last-Modified headers, panel headers, row
counts, and example records are preserved in
[`docs/hmda_probe_2026-09-26.json`](docs/hmda_probe_2026-09-26.json).
Local downloads and repeat-run output go to `data/raw/hmda/`.

The download pattern is
`https://files.ffiec.cfpb.gov/static-data/snapshot/{year}/{year}_public_{lar|ts|panel}_csv.zip`.
All measurements below are for **snapshot CSV ZIPs**, not dynamic or revised one-/three-year files.
MB and GB are decimal; expanded size comes from ZIP metadata, not a full download.

| Activity vintage | LAR ZIP MB | Expanded LAR GB | TS ZIP KB | Panel ZIP KB | Panel rows |
|---|---:|---:|---:|---:|---:|
| 2017 | 155.9 | 1.791 | 262.8 | 216.6 | 5,852 |
| 2018 | 823.7 | 5.856 | 229.4 | 322.5 | 5,683 |
| 2019 | 980.1 | 6.816 | 221.5 | 317.5 | 5,508 |
| 2020 | 1,460.3 | 10.030 | 183.0 | 228.8 | 4,475 |
| 2021 | 1,517.9 | 10.206 | 178.1 | 221.0 | 4,333 |
| 2022 | 877.7 | 6.058 | 182.6 | 227.6 | 4,467 |
| 2023 | 624.5 | 4.340 | 208.2 | 282.4 | 5,113 |
| 2024 | 664.2 | 4.625 | 199.1 | unavailable | — |
| 2025 | 737.1 | 5.114 | 194.2 | unavailable | — |

**Plan-changing finding:** the official manifest explicitly marks the **2024 and
2025 Reporter Panels unavailable**, while offering LAR and Transmittal Sheet (TS)
files. Do not construct panel URLs blindly or assume annual RSSD/parent mappings
are present. Use TS for reporter identities and LEIs, and dated prior panels or
separately reviewed identity sources for missing links. Never treat carried-forward
ownership information as freshly verified. The [Philadelphia Fed methodology](https://www.philadelphiafed.org/surveys-and-data/consumer-finance-data/hmda-lender-methodology)
is another official source to evaluate for the M2 crosswalk.

The modern download probe covers 2017–2025. Pre-2017 archive sizes were **not
measured**: the former `ffiec.gov/hmda/hmdaflat.htm` URL now returns 404, and the
[current FFIEC HMDA page](https://www.ffiec.gov/data/hmda) redirects users conceptually
to the CFPB platform. Legacy archive retrieval remains separate M3 work; do not
apply the modern URL pattern or schema to those years.

### 9.2 Release date per vintage: availability is not the freeze date

The table records documented national-data publication/announcement dates. Use
these as conservative `available_from` dates for the corresponding original
release, not January 1 of the following year. The 2024 and 2025 announcements say
“recently published,” so they establish availability **by** that date, not necessarily
the exact first upload day. Revised files downloaded today require their own
release provenance; these dates do not make later revisions historically available.

| Activity vintage | Public release / conservative availability | Snapshot freeze (frontend manifest) | Official evidence |
|---|---|---|---|
| 2012 | 2013-09-18 | legacy; not probed | [CFPB report, footnote 90](https://files.consumerfinance.gov/f/201510_cfpb_financial-literacy-annual-report.pdf) |
| 2013 | 2014-09-22 | legacy; not probed | [FFIEC annual report](https://www.ffiec.gov/sites/default/files/data/publications/annrpt14.pdf) |
| 2014 | 2015-09-22 | legacy; not probed | [FFIEC release](https://www.ffiec.gov/news/press-releases/2015/pr-09-22) |
| 2015 | 2016-09-29 | legacy; not probed | [FFIEC release](https://www.ffiec.gov/news/press-releases/2016/pr-09-29) |
| 2016 | 2017-09-28 | legacy; not probed | [FFIEC release](https://www.ffiec.gov/news/press-releases/2017/pr-09-28) |
| 2017 | 2018-05-07 | 2018-04-18 | [Federal Reserve Consumer Compliance Outlook](https://www.consumercomplianceoutlook.org/-/media/cco/2018/second-issue/ccoi22018.pdf) |
| 2018 | 2019-08-30 | 2019-08-07 | [FFIEC release](https://www.ffiec.gov/news/press-releases/2019/pr-08-30) |
| 2019 | 2020-06-24 | 2020-04-27 | [FFIEC release](https://www.ffiec.gov/news/press-releases/2021/pr1-06-24) |
| 2020 | 2021-06-17 | 2021-05-03 | [FFIEC release](https://www.ffiec.gov/news/press-releases/2021/pr-06-17) |
| 2021 | 2022-06-16 | 2022-04-30 | [FFIEC release](https://www.ffiec.gov/news/press-releases/2022/pr-06-16) |
| 2022 | 2023-06-29 | 2023-05-01 | [CFPB fair-lending report, p. 18](https://files.consumerfinance.gov/f/documents/cfpb_fair-lending-report_fy-2023.pdf) |
| 2023 | 2024-07-11 | 2024-05-01 | [FFIEC release (URL year is misleading)](https://www.ffiec.gov/news/press-releases/2015/pr-07-11) |
| 2024 | by 2025-07-07 | 2025-05-19 | [FFIEC announcement](https://www.ffiec.gov/news/press-releases/2025/an-07-07) |
| 2025 | by 2026-06-23 | 2026-06-02 | [FFIEC announcement](https://www.ffiec.gov/news/press-releases/2026/an-06-23) |

There are small source disagreements: the 2021 announcement describes a May 1
freeze while the frontend says April 30; the 2025 announcement says June 1 while
the frontend says June 2. Preserve both source interpretations; neither affects
the later conservative public-availability date. S3 Last-Modified is an object
upload/replacement timestamp and is not evidence of initial public availability.

Institution-level **modified LAR** is a different release: for example, the CFPB
announced 2024 modified LAR on [2025-03-31](https://www.consumerfinance.gov/about-us/newsroom/2024-hmda-data-on-mortgage-lending-now-available/)
and 2025 modified LAR on [2026-03-31](https://www.consumerfinance.gov/about-us/newsroom/2025-hmda-data-on-mortgage-lending-now-available/).
Do not backdate the later national snapshot or Reporter Panel to those dates.

### 9.3 Reporter Panel fields and nonbank RSSDs

The downloaded 2020–2023 CSV panels have these 15 columns (actual headers):

```
activity_year, lei, tax_id, agency_code, id_2017, respondent_rssd,
respondent_name, respondent_state, respondent_city, assets, other_lender_code,
parent_rssd, parent_name, topholder_rssd, topholder_name
```

The 2018–2019 panels also contain `arid_2017`. The 2017 panel is a **headerless,
19-column** CSV; parsing it with an inferred header loses a reporter and invents
column names from the first record. Use its separate [legacy format specification](https://files.ffiec.cfpb.gov/static-data/snapshot/2017/2017_publicstatic_dataformat.pdf).

LEI is the modern join key. Legacy IDs need the agency context and the official
ARID2017-to-LEI crosswalk. Preserve identifiers as strings, including leading zeros.
Treat blank and `-1` RSSDs/assets as missing, never as real identifiers or negative
exposure. Parent and top-holder RSSDs are different from the reporter RSSD.
The [official identifier FAQ](https://ffiec.beta.cfpb.gov/documentation/faq/identifiers-faq)
says `other_lender_code=0` denotes depositories; agency code alone does not identify
bank/nonbank status. Exclude unknown `-1` lender codes from classified counts.

**Nonbanks can carry RSSDs, but coverage is incomplete.** Directly observed in the
[2023 panel](https://files.ffiec.cfpb.gov/static-data/snapshot/2023/2023_public_panel_csv.zip):

| Reporter | LEI | respondent_rssd | other_lender_code |
|---|---|---|---|
| ROCKET MORTGAGE, LLC | 549300FGXN1K3HLB1R50 | 3870679 | 3 |
| UNITED WHOLESALE MORTGAGE, LLC | 549300HW662MN1WU8550 | 3870651 | 3 |
| FREEDOM MORTGAGE CORPORATION | 549300LYRWPSYPK6S325 | 3966116 | 3 |
| NATIONSTAR MORTGAGE LLC | 549300LBCBNR1OT00651 | -1 (missing) | 3 |

Across code 3 reporters, **569/927 (61.4%)** have a positive/nonmissing reporter RSSD;
across known non-depository codes 1, 2, 3, and 5, **668/1,029 (64.9%)** do.
These are panel-file counts, not an assertion that every ID has been independently
validated against NIC. In particular, Nationstar has a populated `id_2017` despite
missing `respondent_rssd`; do not copy one into the other. RSSD presence also does
not imply FDIC coverage or an appropriate bank-asset denominator.

For M3, aggregate LAR with DuckDB to lender-year counts before joining complaints;
count originations using the vintage's action code definition. Budget up to roughly
10 GB expanded LAR for a single recent vintage, while panels are under 1 MB expanded.
HMDA measures origination activity, not servicing exposure: ADR-006/007 still apply.

### 9.4 M0 verification on the full complaint export

Run on macOS / Python 3.11.14 / DuckDB 1.5.5, 2026-09-26:

- `make ingest`: **6.57 seconds**, rebuilding from the local bulk CSV (download time
  excluded). All-product Parquet: **18,023,390 rows**, 141,214,755 bytes. Mortgage
  staging: **461,350 rows and distinct IDs**, 5,116,446 bytes, 2011-12-01–2026-09-25.
- Two consecutive live `make delta` runs: **13.95 s** and **10.21 s**, each fetching
  **1,810 rows**, zero changed rows, and retaining **461,350** unique IDs. Each used
  1,000-row pages followed by `search_after` and a terminal empty page. The first
  daily overlap was 2026-08-27–2026-09-26, including 30 days through the existing
  maximum received date plus the new day.
- Unit tests cover changed responses and new IDs, history preservation, unchanged
  reruns, downtime catch-up, empty deltas, rejected taxonomy/duplicate/product
  payloads, failed pagination, repeated cursors, and HTML-with-200 rejection.
- Crosswalks cover every issue and response observed in the full mortgage file,
  including one blank response (unknown, excluded from response metrics). Severity
  assignments and the separate response tier are documented in
  [`data/reference/README.md`](data/reference/README.md).

Daily deltas cannot discover revisions to complaints older than the overlap or
historical removals/product reclassifications. A fresh bulk download and rebuild
is the reconciliation mechanism. Today's response values are not historical
point-in-time response snapshots; this remains a backtest limitation.

## 10. M1 enforcement labels and feasibility (2026-09-26)

### 10.1 Archived source and production scrape

The live [CFPB enforcement listing](https://www.consumerfinance.gov/enforcement/actions/)
still advertises **386 filtered results**. The production scraper retrieved
**386 unique slugs in 16 pages**, and all 386 action detail pages. Filing dates
span **2012-07-17–2025-08-21**. Raw HTML is saved byte-for-byte in
`data/raw/enforcement/{listing,details}/`, with URL, retrieval timestamp,
HTTP content type/status, Last-Modified and SHA-256 sidecars. The 402 HTML files
total **58,519,606 bytes**. Offline replay verifies these checksums.

Pagination stops on no new slugs or the advertised count, with a 100-page safety
bound. A repeated populated page cannot produce an endless loop or a successful
partial scrape: distinct-slug totals must equal both the advertised total and the
expected 386-action snapshot. A changed count requires deliberate snapshot review.
HTTP requests use retries/backoff and one-second pacing. Detail parsing retains
the summary, product tags, forum, docket, status, filing date and PDF links;
related-news widgets and document-link text are excluded from the summary.
Listing/detail filing dates must agree.

### 10.2 Reviewed labels, captions and product crosswalk

There are **386 action labels**, **742 party rows** (560 company, 159 individual,
23 non-entity), and **21 product-crosswalk rows** in `data/reference/`.
Review was performed by Codex reading tags and summary text for each action;
the CSVs name that reviewer explicitly and do not claim independent human review.
Each action has a rationale and source-summary hash. Party rows identify the
source caption/summary and hash the fuller listing/detail caption. A changed
summary, caption, date or product tag requires re-review; new actions cannot
default to a negative label. All 21 observed enforcement tags are covered, and
every mapped CCDB product string was checked against the all-product export.

The caption splitter supports semicolons, `; and` and `, and`, preserves suffix
commas, parenthetical alias lists and “Bank and Trust,” and generates review
proposals. Reviewed party CSVs are authoritative. Trade names are retained within
one party rather than inflated into independent respondents. Ambiguous bare-comma
lists and personal names were reviewed explicitly. For long captions, the fuller
detail heading can restore names omitted on listing cards. Individuals, unnamed
affiliates/`et al.`, government plaintiffs and non-operating relief trusts do not
enter company matching. These captions do not enumerate unnamed docket defendants.

Mortgage relevance is action-specific. ACI's Payments-only action concerns
unauthorized mortgage-payment withdrawals and is included. Harbour Portfolio's
Furnishing-only action concerns home purchases financed through contracts for
deed and is included. International Land Consultants and 3D Resorts Bluegrass
concern land-development/sale disclosure obligations without identified mortgage
credit conduct and are excluded. Monster Loans concerns student-debt relief;
its later mortgage-industry ban is not a mortgage-product event. Unrelated
deposit/card/auto actions against banks are excluded. Full definitions and
additional examples are in [`data/reference/README.md`](data/reference/README.md).

### 10.3 Window counts and model gate

| Inclusive filing window | Distinct mortgage actions | With named company | No named company |
|---|---:|---:|---:|
| 2014-01-01–2024-12-31 (primary) | **86** | 84 | 2 |
| 2014-01-01–2025-08-31 (secondary) | **88** | 86 | 2 |

Across the entire archive, **102/386 actions** are mortgage-related, including
14 before 2014. Mortgage-action counts by filing year are:
2012: 2; 2013: 12; 2014: 13; 2015: 18; 2016: 5; 2017: 10; 2018: 2;
2019: 3; 2020: 15; 2021: 4; 2022: 3; 2023: 7; 2024: 6; 2025: 2.
The 2025 additions are Vanderbilt and Draper & Kramer. The two actions without
a named company in the reviewed captions are David Eghbali and the Hoffman Law
Group principals / `et al.`; they remain filing events but are not mapped to
companies by inference from the caption.

**No M1 fallback is applied**, because the primary action count exceeds ~20.
[ADR-008](docs/09_decisions.md#adr-008-m1-event-count-and-fallback-panel-eligibility-pending-m2m3)
records both counts, a provisional cap of two substantive predictor degrees of
freedom, and the remaining M2/M3 gate. Action counts are not eligible first-company
events: repeat filings, multiple parties, alias/holding-company rollups and panel
entry still need resolution. No fitted model should use 86 or 88 as its effective
event sample size. Re-evaluate fallbacks if the eligible primary count falls below
~20. Current combined `Expired/Terminated/Dismissed` status is not a precise
dismissal indicator; a dismissal-only sensitivity needs separate review.

### 10.4 Reproduction and verification

`make enforcement` stages **386 rows / distinct action IDs** in
`enforcement_events.parquet` and **742 rows covering all 386 actions** in
`stg_enforcement.parquet`, plus CSVs, DuckDB views and `enforcement_counts.json`.
Filing dates are DATE and mortgage/company flags BOOLEAN. First use retrieves
raw HTML; later runs replay the cache. Use `ENFORCEMENT_ARGS=--refresh` to refetch
or `ENFORCEMENT_ARGS=--offline` to require the local archive. The original
`spike/` was left unchanged.

Two consecutive complete offline scrape/validate/stage runs took **3.96 s** and
**3.85 s**, with identical counts. Tests cover repeated-page termination, count
drift, archive tampering, summary extraction, caption delimiters/aliases, typed
staging and action-level counting, missing reviews, and changed-source rejection
before staging replacement. Ruff and Black checks pass.

## 11. M2 entity resolution (2026-09-26)

`make resolve` publishes [`data/marts/crosswalk.csv`](data/marts/crosswalk.csv),
exact dated alias/entity tables, a top-150 review sheet, a score-85–95 review queue,
and complaint/enforcement entity joins. Inputs are versioned manual decisions;
FDIC and modern HMDA identity downloads have URL/time/checksum sidecars and offline
replay. The complete FDIC roster has **27,834** active/inactive institutions;
the selected history archive has **217** merger/name-change events. Modern
2018–2025 panel/TS identity files have **39,269** rows. No LAR download is needed
for identity resolution.

The individually inspected review set contains **232 entities**, **307 alias
review rows**, **104 dated reporter-LEI links**, and **16 rename/merger/asset-sale
relationships**. **433,967/461,350 mortgage complaints (94.0646%)** map through
accepted reviewed aliases. All 150 priority names have a decision; 149 are
accepted and the 195 complaints labeled `Pending Company Match` remain unresolved.
All **131 company-party rows / 121 distinct party strings** in mortgage-related
actions are mapped. A named respondent without complaint presence receives a
separate identity, rather than a guessed complaint-company match.

**Reviewer qualification:** these are Codex-authored identity/evidence reviews,
not independent human adjudication. The numerical coverage gate passes for this
set; ADR-009's independent human sign-off remains outstanding.
`--require-human-review` fails before publication and retains prior artifacts.
The references and published report disclose the reviewer explicitly.

Exact collisions remain candidates, not arbitrary first-row choices. Fuzzy
matching uses first-token-blocked `token_sort_ratio`, never the unsafe spike
baseline scorers. Scores 85–95 inclusive go to review; unique best scores above
95 are proposals excluded from manual coverage. Bank merger validation uses
FDIC **OUT_CERT → SUR_CERT** and `EFFDATE`. Predecessor IDs survive mergers;
Flagstar's ownership transition is date-bounded. Ditech's selected asset sale does
not establish one legal successor or a dissolution date.

GLEIF/NIC remain deferred. The **129 entities without a reviewed HMDA LEI** are
recorded gaps; some are non-reporters or legacy/parent-branded names requiring a
narrower operating-company link before exposure can be attached. None blocks the
measured identity joins. Current/dated bank identities are sufficient for the
demonstrated bank gaps. These identity observations do not establish historical
financial membership or servicing exposure; M3 must preserve release provenance
and never attach a bank denominator to nonbanks or credit unions.

Verification: **63 tests pass**, Ruff and Black pass, complaint entity joins retain
461,350 distinct complaint IDs, and separate-process offline rebuilds produce
byte-identical CSV and coverage-report artifacts. The alias leave-one-spelling-out
check yields **71/73 correct unique predictions (97.26% precision)** and **0 false
positives at or above 95**; recall is **71/306 (23.20%)**. This is a self-check of
the Codex-reviewed gold aliases, not independent accuracy validation. Regression
tests cover the spike's seven unsafe-scorer false positives. Full definitions,
source gaps and the remaining human/backtest work are in the
[M2 report](docs/12_entity_resolution_report.md).
