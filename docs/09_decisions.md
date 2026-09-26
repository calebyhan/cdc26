# 09 · Decision Log

Format: context, decision, consequences. Add a new entry for any decision made after backtest results were seen, and flag it as such.

## ADR-001: Narrow MVP 1 to mortgage
- **Context:** Credit bureaus account for 78% of all complaints, and 84–88% in 2024–2026. Their volume swings dominate any velocity signal. Mortgage complaints are stable at about 21–25k per year since 2018, and HMDA provides a real exposure denominator.
- **Decision:** MVP 1 uses only `Product = Mortgage`. Credit bureaus, collectors, and fintechs are excluded.
- **Consequences:** a cleaner signal, but fewer events. See ADR-008.

## ADR-002: DuckDB + Parquet; bulk history plus on-demand API delta
- **Context:** 18M rows, one team, hackathon timeframe. The spike verified that the bulk CSV is regenerated daily, that the API supports `search_after` at about 20 requests per minute, and that `company_response` changes after ingestion.
- **Decision:** load the bulk CSV once into Parquet. Refresh on demand from the API, re-pulling the trailing 30 days and upserting on `complaint_id`. Compute trends ourselves, since `/trends` has been removed.
- **Consequences:** no database server to run. Ingestion must check the JSON content type, because removed endpoints return HTML with a 200 status.

## ADR-003: Transparent score always ships; discrete-time hazard is the planned primary model
- **Context:** the event count will be small.
- **Decision:** Model A always ships and drives the live ranking. Model B is the primary statistical model, and Model C (Cox) is reported alongside. Which one leads is final after M4.
- **M4 outcome (2026-09-26):** retain B as the primary statistical output and C
  as the comparison. Both fit successfully wherever the event budget permits,
  but neither establishes improvement over raw count in the primary 12-month
  test. B's constant monthly hazard avoids C's additional baseline-tail
  extrapolation assumption. This is an operational choice, not an accuracy-win
  claim. Model A remains the live ranking; its own comparison also does not
  establish predictive improvement. See the
  [backtest report](../reports/backtest_2026-09-26.md).

## ADR-004: Evaluation windows *(amended after the data spike)*
- **Context:** 386 CFPB actions exist from 2012-07-17 to 2025-08-21. 2025 had 9 actions, several later dismissed, and none have been filed since.
- **Decision:** the primary backtest uses outcomes through 2024-12. The secondary window runs through 2025-08, reported with and without dismissed actions. No accuracy claims are made after 2025-08.

## ADR-005: Modeling level
- **Decision:** banks are modeled at the holding company (FDIC `RSSDHCR`), with charter-level aliases mapped to the same entity when CCDB uses the charter name. Nonbanks are modeled at the operating company. See [03_entity_resolution.md](03_entity_resolution.md).

## ADR-006: Never apply bank denominators to nonbanks
- **Decision:** rate features are null where no appropriate exposure measure exists. Nonbanks form their own peer groups and rely on self-normalized features. FDIC covers banks only (verified).

## ADR-007: Servicing-exposure denominator
- **Context:** the companies with the most complaints include servicing-heavy nonbanks (Ocwen, Nationstar/Mr. Cooper, Shellpoint, SPS, Ditech, SLS). HMDA measures originations, and FDIC does not cover nonbanks.
- **Options:**
  - (a) Self-normalized features only for servicers.
  - (b) A proxy from agency loan-level datasets that list large servicers.
  - (c) Ginnie Mae issuer data.
  - (d) Exclude servicers.
- **Decision (2026-09-26, before backtesting):** (a), as explicitly requested for M3. Nonbank servicers receive structured complaint and self-normalized features only; exposure-normalized rates and bank financials stay null, including after peer transformations. (b) remains a stretch goal. (d) is rejected.

## ADR-008: Event count and fallback (panel eligibility verified in M3)
- **Context / evidence (2026-09-26, before any backtest):** the live CFPB listing
  advertised **386 filtered results**. The scraper retrieved 386 unique action
  slugs over 16 listing pages and archived all 386 detail pages. Every action has
  a reviewed boolean `mortgage_related`, a summary-specific rationale, source-text
  fingerprint, and review provenance in
  [`enforcement_labels.csv`](../data/reference/enforcement_labels.csv). Review was
  performed by Codex reading product tags and summary text; this is not an
  independent human adjudication. Across the full 2012–2025 archive, 102 actions
  are mortgage-related. The table grain is one public action, not one party.

| Inclusive filing-date window | Mortgage-related actions | With ≥1 named company | Individual / unspecified-party only |
|---|---:|---:|---:|
| **Primary:** 2014-01-01 → 2024-12-31 | **86** | 84 | 2 |
| **Secondary:** 2014-01-01 → 2025-08-31 | **88** | 86 | 2 |

- **Decision / fallback:** retain ADR-004's primary window through 2024-12.
  **No fallback applied:** 86 exceeds the approximately 20-action M1 threshold.
  The two added secondary-window actions are Vanderbilt (2025-01-06) and
  Draper & Kramer (2025-01-17). All filing events count regardless of later
  status, as specified in §05; these labels do not assert that the agency prevailed.
- **Initial feature budget:** cap fitted models at **two substantive predictor
  degrees of freedom** until panel event counts are verified. In each training
  cutoff, total fitted degrees of freedom (including baseline/time terms) must
  also be ≤ `floor(eligible first-company events / 10)`. This is a conservative
  project constraint, not a statistical guarantee. No model has been built or fit.
- **Consequences / remaining gate:** **86/88 are action counts, not counts of
  events resolving to panel entities.** Company IDs, holding-company rollups,
  alias/merger validity, complaint-panel entry dates, and first-event eligibility
  are not available until M2/M3. Multi-party actions and repeat actions cannot be
  counted as independent model observations. Record those eligible counts here
  before fitting and reduce the budget as needed. If the eligible primary count
  falls below ~20, evaluate the [fallbacks](08_roadmap.md#fallbacks-if-m1-finds-too-few-events)
  in order: secondary window, any-action target, state regulators, federal banking
  regulators, then descriptive event study; record the first adequate choice.
- **Reproduction:** `make enforcement ENFORCEMENT_ARGS=--offline` writes
  `data/staging/enforcement_events.parquet` (386 actions),
  `stg_enforcement.parquet` (742 action-party rows), CSV review copies, and
  `enforcement_counts.json`, with DuckDB views in `ews.duckdb`. References and
  methodology are documented in [`data/reference/README.md`](../data/reference/README.md).
  The source combines expiry, termination and dismissal in one status label;
  do not treat all 53 secondary-window `Expired/Terminated/Dismissed` actions as
  dismissed in a later sensitivity analysis.

- **M3 eligibility update (2026-09-26, before backtesting):** the primary panel
  contains **25 first-company events across 132 eligible companies**; the secondary
  panel contains **26 across 132 companies**. The current full panel has 26 events
  across 135 companies. These are counting-process event flags after entry and
  censoring, not action or party counts. Retain the primary window and the cap of
  **two substantive predictor degrees of freedom**, with the stricter per-fold
  total-degree constraint above still applying. No model has been fit. Current
  revised FDIC/HMDA exposures are unavailable at historical cutoffs under the
  conservative version policy; any backtest must respect those nulls. See
  [M3 conventions](13_panel_features.md) and [build counts](panel_probe_2026-09-26.json).

## ADR-009: rapidfuzz + curated alias table instead of Splink *(new, from the data spike)*
- **Context:** naive fuzzy matching produced 7 false positives among the top 40 names. The improved approach still missed about 15 enforcement matches. The top 150 mortgage names cover 94.1% of complaints.
- **Decision:** normalization, exact-key matching, and first-token-blocked `token_sort_ratio` generate candidates. A human confirms everything that matters. Splink is dropped as overkill for a few hundred entities.
- **Supersedes:** the Splink design in the original 03 and the README stack.

## ADR-010: Live product is an anomaly ranking; enforcement is a historical label *(new)*
- **Context:** CFPB has filed no enforcement action since 2025-08-21.
- **Decision:** the live dashboard is sorted by the anomaly score (Model A plus change-point flags). Hazard-model probabilities are shown as secondary, labeled "historical-regime estimate".

## ADR-011: Structured fields only *(new)*
- **Context:** CFPB stopped publishing narratives on 2026-08-14. The API field was removed and the consent option retired.
- **Decision:** all MVP features use the 15 structured CCDB columns. Narrative NLP from the frozen FOIA archive is stretch goal S4, for the backtest only.

## ADR-012: GLEIF, NIC, Y-9C optional *(new)*
- **Context:** FDIC `RSSDHCR` and `/history` already cover bank holding-company rollup and mergers.
- **Decision:** these three sources are deferred. Add them only if M2 shows gaps that FDIC can't fill.
- **M2 evidence (2026-09-26, before backtesting):** FDIC active/inactive identities,
  `/history` merger events and dated HMDA reporter identities support 94.0646%
  Codex-reviewed complaint coverage and 131/131 mortgage company-party mappings.
  Historical Flagstar ownership is available in dated panels despite missing
  current FDIC holding-company fields. The 129 entities without a reviewed HMDA
  LEI are documented identity/exposure gaps, not fabricated reporters; none blocks
  the measured identity joins. Continue to defer GLEIF/NIC. Reconsider them only
  for a specific required M3 reporter/ownership link that these sources cannot
  supply. Nonbank RSSD absence is not itself a reason to add NIC or infer bank
  denominators. Independent human identity adjudication remains outstanding.
  See [M2 report](12_entity_resolution_report.md).

## ADR-013: M4 protocol fixed before viewing backtest results (2026-09-26)

- **Model A:** equal weights on self-z, acceleration, appropriate exposure rate,
  tier-3 share, untimely rate, issue-mix divergence, and bank financial stress.
  Financial stress averages standardized noncurrent/provision ratios and negative
  equity-to-assets. Structurally unavailable components are omitted; no surrogate
  exposure denominator is invented. Historical peer transforms use training rows
  only, frozen at each cutoff. Live A uses the current public cross-section and
  remains the live ranking regardless of B/C performance.
- **Statistical budget:** reserve one degree of freedom for the baseline, permit
  at most one substantive predictor when a fold has at least 20 first-company
  events, and use baseline-only models otherwise. Candidate predictors are the
  predeclared Model A composite and log(1 + trailing-12m count). No test-period
  feature selection. B uses a constant time baseline because spline/time dummies
  would violate ADR-008's budget. C is a genuine null Cox fit in baseline-only folds.
- **Validation:** expanding time folds entirely inside each outer training
  window, with horizon embargoes. Choose predictor and L2 penalty by mean Brier
  loss, using only observed validation labels. If inner folds cannot identify a
  covariate/penalty, retain the declared anomaly predictor and middle penalty.
  Grids: B ridge total penalties 0.1/1/10; C penalizers 0.001/0.01/0.1.
- **B alignment:** labels are events in the following calendar month. At scoring
  cutoff T, the first forecast month uses the previous month's feature snapshot;
  subsequent months hold the current T snapshot fixed. C uses frozen current
  covariates and conditional baseline increments. Beyond training follow-up, C
  extrapolates the training baseline's average hazard; this assumption is reported.
- **PH diagnostics:** training-only, Efron risk-set Schoenfeld residuals versus
  log duration. If p < .05, replace the linear covariate with a median-split
  stratum and separate baseline hazards, within the two-degree budget. Do not
  change a model after looking at outer outcomes.
- **Windows:** annual January cutoffs 2016–2023 for primary outcomes through
  2024-12; secondary additionally permits 2024/2025 cutoffs whose full horizons
  end by 2025-08. Horizons are 6/12/18 months; outcomes are (T,T+h]. Partial
  horizons after corporate censoring are excluded unless a qualifying event is
  observed. Same eligible population for all available models at a cutoff.
- **Dismissals:** separate evidence-reviewed file, frozen before results. Remove
  only documented complete-case dismissals for the requested sensitivity; do
  not interpret order expiry/termination as dismissal. Unresolved status is
  disclosed. Reconstruct the at-risk panel so dropping a first event does not
  censor the company at that dropped filing. Later-dismissal filtering is a
  retrospective outcome sensitivity, not information known at historic cutoffs.
- **Metrics/uncertainty:** top-10/top-20 precision and recall, average precision
  (stepwise PR-AUC), median lead time, concordance, and probability calibration.
  Company-cluster bootstrap 95% intervals, fixed seed and 400 draws; pooled
  scores are macro averages across cutoffs per horizon. Lead time deduplicates
  events and measures the first annual top-20 alert whose horizon covers the
  event; annual monitoring makes timing coarse. Metric intervals condition on
  the fitted models and do not include training/identity uncertainty. A metric
  with no positives/comparable pairs is undefined, not zero.
- **Baselines:** seeded random ranking, raw 12m count, verified size-normalized
  count, and prior-action flag with raw-count tie-breaking. Size normalization
  is unavailable at historical cutoffs under M3's version policy; report N/A
  and source coverage, never substitute a fictitious denominator. A separately
  named self-normalized-count reference is included for an available comparison.
- **Event chart:** match peers at event month −48 by group and baseline log count,
  plus size where publicly available then; use never-filed peers within the
  evaluation window. Plot complaints relative to each company's pre-event
  baseline (a self-normalized series), retaining +12 months from the unrestricted
  feature grid. This is descriptive; never use post-event values in prediction.
- **Limits:** mappings were retrospectively curated in 2026; validity dates are
  enforced, but historical availability of the mapping versions cannot be
  proven. Current complaint-response versions retain the M3 caveat. No accuracy
  claims or evaluated outcome windows extend beyond 2025-08.

### M4 implementation corrections after the 40-draw smoke run

The initial end-to-end run used 40 draws to verify artifact generation. Before
the final 400-draw run, corrected even-sample median arithmetic, rendered
non-estimable values as N/A, identified baseline-only errors explicitly, and
expanded explanations to frozen training peer-median component contributions.
Compressed prediction output and added measured comparison/error summaries to
the report. These corrections do not change predictors, penalties, weights,
ranking thresholds, outcome labels, or cutoff choices. All cutoffs are rerun.
