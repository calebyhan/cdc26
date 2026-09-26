# 07 · Dashboard

**Stack:** Streamlit + Plotly, reading Parquet marts through DuckDB. An on-demand `make refresh-dashboard` run pulls new complaints from the CCDB API (plus a trailing-30-day re-pull), rebuilds the marts, and re-scores. The dashboard serves a saved snapshot; there are no scheduled refreshes or automatic commits.

**Freshness:** show the CCDB `_meta.last_indexed` timestamp and our last successful refresh. Show a warning if CCDB reports `is_data_stale` or `has_data_issue`.

## Language rules (applies across every view)

- Use "elevated complaint signal", "change tier", and "change score". Model A did not beat 12-month complaint volume in the backtest, so never present its ranking as enforcement risk.
- Never use "violator", "likely guilty", or "will be sued".
- A persistent banner reads: *Screening tool based on public complaint data. Not a finding of wrongdoing.* It links to the limitations page.
- Show probabilities as bands (low / elevated / high) with the numeric value only on hover.
- Label every probability "historical-regime estimate". A second banner notes that CFPB has filed no enforcement action since 2025-08-21.

## View 1: Complaint change monitor

- **Sort:** unusual change (Model A anomaly score, default) or 12-month complaint volume, the strongest backtest baseline. Model B/C probabilities appear as secondary columns.
- **Minimum complaints:** hides companies below 20 complaints in 12 months by default; tiny bases produce extreme self-history scores.
- **Table:** position, company, peer group, change score, change tier, p_6m / p_12m / p_18m, 12-month complaints, normalized rate, top 3 drivers, sparkline of the last 24 months.
- **Filters:** peer group, size band, state, "exclude companies with active actions".
- **Reads:** latest `score_snapshot`, `company_month`.

## View 2: Company detail

- Complaint trend with the peer-group median band, plus change-point markers.
- Complaints per HMDA origination, or per asset, over time.
- Issue mix (stacked area) with severity tiers colored.
- Timely-response and relief shares over time.
- Financial condition panel.
- Ownership tree (NIC/GLEIF parent chain, merger history).
- Enforcement timeline, if any.
- "Why flagged": driver bars with plain-language labels.
- **Reads:** `company_month`, `entity`, `alias`, `stg_enforcement`, `stg_fdic_history`.

## View 3: Enforcement timeline (the narrative view)

- For a selected enforced company: the complaint series with a vertical line at the event date, shading where the company was in our top 20 at a historical cutoff, and an annotated lead time.
- The aggregate event-aligned chart: all enforced companies versus matched peers, from month −48 to +12.
- **Reads:** `company_month`, `score_snapshot`, `stg_enforcement`.

## View 4: Backtest results

- Per-cutoff table: the top 20 at T, and which of them had an event within h. Hits highlighted.
- Metric chart: precision@20 and PR-AUC per cutoff for each model against each baseline, with confidence intervals.
- Lead-time histogram.
- Error review: false positives and misses, each with its category.
- **Reads:** `backtest_results`, `score_snapshot`.

## Limitations page

A condensed version of [10_risks_limitations.md](10_risks_limitations.md).

## Performance

Precompute every chart-ready aggregate into small Parquet files. The app should never scan all 461k complaints on page load.
