# 09 · Decision Log

Format: context, decision, consequences. Add a new entry for any decision made after backtest results were seen, and flag it as such.

## ADR-001: Narrow MVP 1 to mortgage
- **Context:** Credit bureaus account for 78% of all complaints, and 84–88% in 2024–2026. Their volume swings dominate any velocity signal. Mortgage complaints are stable at about 21–25k per year since 2018, and HMDA provides a real exposure denominator.
- **Decision:** MVP 1 uses only `Product = Mortgage`. Credit bureaus, collectors, and fintechs are excluded.
- **Consequences:** a cleaner signal, but fewer events. See ADR-008.

## ADR-002: DuckDB + Parquet; bulk history plus daily API delta
- **Context:** 18M rows, one team, hackathon timeframe. The spike verified that the bulk CSV is regenerated daily, that the API supports `search_after` at about 20 requests per minute, and that `company_response` changes after ingestion.
- **Decision:** load the bulk CSV once into Parquet. Refresh daily from the API, re-pulling the trailing 30 days and upserting on `complaint_id`. Compute trends ourselves, since `/trends` has been removed.
- **Consequences:** no database server to run. Ingestion must check the JSON content type, because removed endpoints return HTML with a 200 status.

## ADR-003: Transparent score always ships; discrete-time hazard is the planned primary model
- **Context:** the event count will be small.
- **Decision:** Model A always ships and drives the live ranking. Model B is the primary statistical model, and Model C (Cox) is reported alongside. Which one leads is final after M4.

## ADR-004: Evaluation windows *(amended after the data spike)*
- **Context:** 386 CFPB actions exist from 2012-07-17 to 2025-08-21. 2025 had 9 actions, several later dismissed, and none have been filed since.
- **Decision:** the primary backtest uses outcomes through 2024-12. The secondary window runs through 2025-08, reported with and without dismissed actions. No accuracy claims are made after 2025-08.

## ADR-005: Modeling level
- **Decision:** banks are modeled at the holding company (FDIC `RSSDHCR`), with charter-level aliases mapped to the same entity when CCDB uses the charter name. Nonbanks are modeled at the operating company. See [03_entity_resolution.md](03_entity_resolution.md).

## ADR-006: Never apply bank denominators to nonbanks
- **Decision:** rate features are null where no appropriate exposure measure exists. Nonbanks form their own peer groups and rely on self-normalized features. FDIC covers banks only (verified).

## ADR-007 (OPEN): Servicing-exposure denominator
- **Context:** the companies with the most complaints include servicing-heavy nonbanks (Ocwen, Nationstar/Mr. Cooper, Shellpoint, SPS, Ditech, SLS). HMDA measures originations, and FDIC does not cover nonbanks.
- **Options:**
  - (a) Self-normalized features only for servicers.
  - (b) A proxy from agency loan-level datasets that list large servicers.
  - (c) Ginnie Mae issuer data.
  - (d) Exclude servicers.
- **Leaning toward:** (a) for MVP 1, with (b) as a stretch goal. (d) is rejected.
- **Owner / due:** _TBD_ · before M3.

## ADR-008: M1 event count and fallback (panel eligibility pending M2/M3)
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
