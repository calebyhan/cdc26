# M3 · Panel and features

M3 uses the M2 crosswalk accepted in this session: 94.0646% reviewed complaint
coverage and all 131 mortgage company-party rows mapped. Review provenance stays
Codex-authored. Independent human adjudication is an additional audit, not a
new prerequisite for this implementation.

## Rebuild

```bash
make pipeline
make pipeline PIPELINE_ARGS=--offline
make pipeline PIPELINE_ARGS='--offline --end 2024-12-31'
make test
make lint
```

The command rebuilds complaint and enforcement staging, reruns reviewed entity
resolution, ingests archived financials and full 2018–2025 HMDA LAR snapshots,
and writes `data/marts/company_month.parquet`. Offline runs require the archived
raw inputs and never download. `--reuse-staging` skips only M1/M2 rebuilding;
exposures and the panel are still rebuilt. An output directory lacking reference
files receives copies of the repository's authoritative CSVs.

The initial run retains about 7.2 GB of compressed HMDA inputs. Only one expanded
LAR is held at a time (up to roughly 10 GB); it is removed automatically after
aggregation. Archives carry URLs, checksums, retrieval dates, and version dates.

## Availability and windows

All exposure joins require `available_from < month` **and** `report_date < month`.
For FDIC, the nominal release policy is quarter end plus 45 days. Current API
values can be revised: the effective availability is the later of that date and
the downloaded index's creation date. This preserves a completed-quarter lag.
Only financial records with quarter-specific `RSSDHCR` matching a reviewed bank
are rolled up; a bank without a holder can use a reviewed CERT. Values are summed
across charters before ratios are calculated. Amounts remain in $ thousands;
complaints per $bn multiply by 1,000,000. Quarterly provisions divided by gross
loans are annualized by multiplying by four. Missing charter inputs propagate
nulls rather than producing a partial holding-company amount.

For HMDA, the effective availability is the later of the documented public
release and the current object's version timestamp; retrieval is the fallback
when a version timestamp is absent. Last-Modified is **not** treated as proof of
the original public release. Current historical objects dated November 2025
therefore cannot supply features to the primary backtest ending in 2024. Obtaining
independently archived original vintages is required before historical exposure
coverage can be expanded. Tests of join arithmetic cannot recover old versions.

The supported LEI vintages are 2018–2025. Pre-2018 legacy Respondent ID / Agency
Code exposure links remain unverified and are not guessed. HMDA totals are
lender-year, joined through reviewed dated LEIs. An identity transition inside a
year cannot assign the entire annual total to either owner; those annual links
are omitted. Multiple linked LEIs can be summed for counts and weighted rates;
geographic context remains null for such aggregates until lender-state rollups
are supplied. Bank HMDA totals cover reviewed reporters, whereas FDIC amounts
cover the holding company's insured-bank charters; their scopes are distinct.

Complaints use `Date received`. At September 1, the publication buffer excludes
August, and `c_3m` counts May, June, and July. All windows include their lower
boundary and exclude their upper boundary. `c_prev6m` immediately precedes the
current six-month window; acceleration compares growth with three months earlier.
The self z-score compares the current three-month count with up to 36 prior,
overlapping three-month counts, requiring at least 12 historical windows and a
nonzero sample standard deviation. It does not invent zeros before entry.
Market share uses three-month counts and the preceding 24 three-month shares;
its denominator includes **all** mortgage complaints, including unresolved names.
Issue/state divergence compares the recent six months with the preceding,
nonoverlapping 24 months. Geography excludes missing states.

Response rates exclude in-progress and unknown responses from both numerator
and denominator. Volume, severity, tags, and geography retain these complaints.
Untimely is the union of `timely = No` and standardized `untimely`, per 100 eligible
responses. Relief includes legacy unspecified relief. No narrative or company
public-response column enters the feature input. The bulk response values are
current values: the calendar buffer addresses ordinary response delay, but does
not prove historical responses were identical. This source limitation remains.

## Panel, labels, and missingness

Eligible company types are bank, credit union, nonbank originator, and nonbank
servicer. Bureau and other entities remain in M2 but are outside the mortgage
model universe. Entry is the first complaint month or HMDA entry, whichever is
earlier, bounded by the requested window and reviewed identity validity. HMDA-only
entry waits until the first scoring month after public availability to avoid
creating a historical company universe from a future release.

An entity exits at its first mortgage filing after entry, its reviewed validity
end or bank merger, or the observation cutoff. Older filings set `prior_action`.
Counting-process intervals use days since entry. `interval_stop` is exclusive;
a filing day's event is observed at that day's end, allowing a positive interval
for first-day filings. Merger censoring excludes the effective merger day. The
last observation day is included and no panel month is after the observation date.

For a score at month `t`, `event_next_Hm` covers `[t, t + H calendar months)`.
A filing in that range makes the label 1; otherwise it is 0 only when the whole
horizon is observed before censoring, and null when censored. This includes the
current scoring month, whose complaint inputs are already lagged. Event dates,
censoring dates, horizon labels, and prior-action metadata are separate from the
explicit `NUMERIC_FEATURES` allowlist used for transformations.

ADR-007 selects option (a): servicers receive complaint features only. HMDA and
FDIC exposure/financial columns and all exposure-normalized rates remain null
for nonbank servicers. FDIC columns are null for every nonbank. Availability flags
remain in the panel. Raw feature nulls are retained; `_peer_z` companions impute
with the same scoring month's peer median and standardize within that peer group.
Structural nulls stay null through this step. M4 must fit any alternative
imputation/selection transforms inside training folds and enforce its event-based
feature budget.

FDIC stale observations expire after 200 days; HMDA observations after 1,100 days.
Source period, effective availability, and HMDA year are retained beside values.
`panel_report.json` records the build window, event counts, source coverage, and
mapped enforcement companies with no observable panel entry.


## Recorded validation (2026-09-26)

The full rebuild produced 16,714 rows, 135 companies, and 26 first-company events.
The primary window ending 2024-12-31 has 14,566 rows / 132 companies / 25 events;
the secondary ending 2025-08-31 has 15,380 rows / 132 companies / 26 events.
There are 5,227 ingested FDIC bank-quarter records and eight full LAR vintages.
Current source versions support 40 FDIC and 668 HMDA observations in the full
at-risk panel; both exposure sources are null throughout the historical primary
and secondary windows. All 81 tests pass, including 18 M3 tests, plus Ruff and
Black. Counts are recorded in [the build probe](panel_probe_2026-09-26.json).

An offline pipeline run starting with only raw archives and no staging, marts, or
reference tables reproduced the published panel with **zero differing rows**.
