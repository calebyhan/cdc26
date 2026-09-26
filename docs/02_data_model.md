# 02 · Data Model

There are four layers: **raw → staging → entities → marts**. All tables are Parquet, and DuckDB is the query engine.

## Staging (one table per source, typed and cleaned)

| Table | Grain | Notes |
|---|---|---|
| `stg_complaints` | complaint | Mortgage only for MVP 1. Bulk load plus daily API upserts on `complaint_id`. Adds `issue_std`, `response_std`, `severity_tier`, `ingested_at` |
| `stg_enforcement` | action × party | Scraped listing and detail pages, joined to the hand-labeled `enforcement_labels.csv` |
| `stg_hmda_lender_year` | lender × year | Aggregated from LAR, keyed by LEI or legacy respondent ID |
| `stg_fdic_institutions` | cert | Roster, including inactive banks (`ACTIVE:0`) |
| `stg_fdic_financials` | cert × quarter | Includes `available_from` date |
| `stg_fdic_history` | cert × event | Mergers and name changes |
| `stg_nic_*`, `stg_y9c`, `stg_gleif_*` | — | **Optional.** Added only if M2 finds gaps (see 01) |

## Entities

These follow the `entity` + `alias` design from [FINDINGS.md §4.3](../FINDINGS.md), with validity dates added for mergers and renames.

**`entity`**

| Column | Type | Description |
|---|---|---|
| `entity_id` | str | e.g. `E000123` |
| `display_name` | str | |
| `type` | enum | bank, credit_union, nonbank_originator, nonbank_servicer, bureau, other |
| `peer_group` | enum | Used for within-group standardization |
| `fdic_certs` | list[int] | One holding company can have several CERTs (TD has 2) |
| `rssd_hc` | str, nullable | FDIC `RSSDHCR` |
| `lei` | str, nullable | Filled once HMDA is ingested |
| `successor_entity_id` | str, nullable | e.g. Discover → Capital One after 2025-05-18 |

**`alias`**: every source joins to `entity` through this table, on the **exact raw string or ID**.

| Column | Description |
|---|---|
| `raw_string` | Exactly as it appears in the source |
| `source` | ccdb, enforcement, fdic_name, fdic_namehcr, hmda |
| `entity_id` | |
| `method` | exact, fuzzy, manual |
| `score` | rapidfuzz score, when applicable |
| `valid_from`, `valid_to` | Nullable. Used only when a string's meaning changes over time |
| `reviewed_by`, `reviewed_on` | Required when method = manual, or when score is below 95 |

## Marts

**`company_month`** is the modeling panel. It has one row per company per month, covering only months the company was "at risk".

| Column group | Examples |
|---|---|
| Keys | `entity_id`, `month` |
| Counting-process fields (for Cox) | `start`, `stop`, `event` |
| Horizon labels (for the discrete-time model) | `event_next_6m`, `event_next_12m`, `event_next_18m` |
| Complaint features | See [04_features.md](04_features.md) |
| Exposure | `hmda_originations_lag`, `assets_lag`, `deposits_lag` (FDIC values are in $ thousands) |
| Financial | `noncurrent_ratio_lag`, `provision_ratio_lag`, … |
| Meta | `peer_group`, `data_available_flags` |

**Panel rules:**
- A company enters the panel at its first complaint month or first HMDA year, whichever comes first.
- It leaves at the first event (MVP 1 models first events only), when it ceases to exist, or at the end of the window. The latter two are censoring.
- Every `_lag` column is joined using the source's `available_from` date, never the period the data describes.

**`score_snapshot`** stores what the model said at each cutoff.

| Column | Description |
|---|---|
| `cutoff_date` | |
| `model_version` | |
| `entity_id` | |
| `transparent_score`, `rank` | |
| `p_6m`, `p_12m`, `p_18m` | |
| `driver_1..3`, `driver_1..3_value` | Top contributing signals |

**`backtest_results`** has one row per cutoff × model × metric.

## Conventions

- Dates are ISO strings in raw data and DATE type from staging onward. Months are the first day of the month.
- Nothing downstream reads `data/raw/`.
- Hand-maintained inputs live only in `data/reference/` and are version-controlled.
