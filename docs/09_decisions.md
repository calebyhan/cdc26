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

## ADR-008 (OPEN): Event count and fallback
- **To fill after M1:** number of mortgage-related events resolving to panel entities, both through 2024-12 and through 2025-08, and which fallback from [08_roadmap.md](08_roadmap.md), if any, was applied.

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
