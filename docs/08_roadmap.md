# 08 · Roadmap

Each milestone ends with a demoable artifact. If time runs out, the project is complete at the last milestone whose exit criterion was met.

**Already done (data spike, 2026-09-26):** CCDB access and limits, enforcement scraper, FDIC roster, and the entity-matching prototype. See [FINDINGS.md](../FINDINGS.md) and `spike/`.

## M0: Setup and ingestion
- [x] Repo, `pyproject.toml`, Makefile, pre-commit (ruff, black). Move `spike/` code into `src/ews/ingest/` and `src/ews/resolve/`
- [x] Convert the bulk `complaints.csv` to Parquet, then filter to mortgage (`stg_complaints`)
- [x] `make delta`: API pull using `search_after`, trailing-30-day re-pull, upsert on `complaint_id`, JSON content-type check
- [x] Fill the issue crosswalk (old and new taxonomy) and the response crosswalk (pre-2017 values) with severity tiers
- [x] **HMDA spike:** file sizes, release date per vintage, Reporter Panel fields, and whether nonbanks carry RSSD. Write it up as a new FINDINGS section

**Exit:** `make ingest` rebuilds complaint staging in under 5 minutes, `make delta` runs cleanly twice in a row, and the HMDA spike is written up.

**Verified 2026-09-26:** full CSV rebuild 6.57 s; two live deltas 13.95 s / 10.21 s, each 1,810 rows fetched and 461,350 staged. See [FINDINGS §9](../FINDINGS.md#9-hmda-spike-and-m0-ingestion-validation-2026-09-26).

## M1: Labels (the riskiest step, so do it first)
- [x] Productionize the enforcement scraper: stop-on-no-new-slugs, check against the 386 total, save raw HTML
- [x] Split captions into parties. Tag individuals and non-entities
- [x] Hand-label `mortgage_related` for every action (product tags, confirmed by reading the summary)
- [x] Build the enforcement ↔ CCDB product crosswalk (about 20 rows)
- [x] **Count mortgage-related events in 2014-01 → 2025-08**, and separately through 2024-12. Record both in ADR-008 and set the feature budget

**Exit:** a labeled event table with event counts. If the primary count is below about 20, choose a fallback immediately (see below).

**Verified 2026-09-26:** 386 archived actions, 386 reviewed labels, 742 reviewed
party rows, and 21 product mappings. Mortgage-related action counts: **86** through
2024-12 and **88** through 2025-08, both starting 2014-01. No M1 fallback applied.
`make enforcement` builds the labeled Parquet tables; use
`ENFORCEMENT_ARGS=--offline` to replay the archive. The initial feature cap and the
required distinction between action counts and eligible company first events are
recorded in ADR-008. Entity resolution and panel eligibility remain M2/M3 work.

## M2: Entity resolution
- [x] `normalize()` from the spike, plus exact-key matching and first-token-blocked `token_sort_ratio`
- [x] Review queue for scores 85–95
- [x] Individually verify the top 150 mortgage names and every mortgage-related enforcement company party (Codex review; independent human audit remains separate)
- [x] FDIC rollup by `RSSDHCR`. Mergers from `/history`, plus a hand-kept nonbank rename list (Nationstar/Mr. Cooper, Ocwen/Onity, Ditech, …)
- [x] Publish `crosswalk.csv`
- [x] Decide whether NIC or GLEIF are needed for the remaining gaps

**Exit:** at least 94% of mortgage complaints map to a reviewed `entity_id`, and 100% of company parties in mortgage-related actions are mapped.

**2026-09-26:** Codex individually reviewed all 150 priority names (149 accepted,
one unresolved CFPB routing placeholder) and all 121 distinct mortgage company-party
strings. Reviewed coverage is **433,967/461,350 (94.0646%)**, with **131/131 company
party rows mapped**. The user accepted this M2 baseline for M3. Independent human adjudication remains
an additional audit, with Codex review provenance preserved. `make resolve RESOLVE_ARGS=--offline`
reproduces the artifacts; `--require-human-review` enforces the additional human
gate. [Details and source gaps](12_entity_resolution_report.md). GLEIF/NIC deferred.

## M3: Panel and features
- [x] FDIC quarterly financials (summed per holding company) and HMDA lender-year counts, each with `available_from`
- [x] `company_month` panel with counting-process fields and horizon labels
- [x] All complaint features (structured fields only), plus exposure and financial features
- [x] Unit tests: point-in-time joins, no future rows, window arithmetic, ordering by `Date received`

**Exit:** the panel builds from scratch, and the leakage tests pass.

**Verified 2026-09-26:** `make pipeline` rebuilt all stages and produced 16,714
company-month rows for 135 companies through 2026-09-26, with 26 first-company
events. Primary: 14,566 rows, 132 companies, 25 first events. Secondary: 15,380
rows, 132 companies, 26 first events. All 81 tests pass, including 18 M3 tests;
Ruff and Black pass. An offline rebuild from an empty output directory reproduced
the panel with zero differing rows. ADR-007 selects option (a). Current revised FDIC/HMDA
versions are not backdated, so exposure features remain null in the primary and
secondary historical windows. [Conventions and limitations](13_panel_features.md);
[recorded build counts](panel_probe_2026-09-26.json).

## M4: Models and backtest
- [x] Model A (transparent anomaly score)
- [x] Model B (discrete-time hazard) and Model C (Cox), time-ordered cross-validation
- [x] Rolling-cutoff backtest: primary window (≤ 2024-12), secondary window (≤ 2025-08), with and without dismissed actions
- [x] Event-aligned chart with matched peers
- [x] Error review
- [x] Auto-generated backtest report

**Exit:** `reports/backtest_*.md` exists with metrics and confidence intervals for every model and baseline.

**Verified 2026-09-26:** `make backtest` produced
[the report](../reports/backtest_2026-09-26.md), 928 metric rows and 74,912
predictions with 400-draw company-cluster bootstrap intervals. Primary: eight
cutoffs per horizon; secondary: ten/six-month and nine/twelve- or eighteen-month
cutoffs. Both windows include and exclude confirmed complete-case dismissals;
first-event counts are 25/23 and 26/23 respectively. There are 11 matched chart
pairs and 126 live Model A rankings. All 98 tests pass, including 17 M4 tests,
plus Ruff and Black. Protected labels and the original M3 panel are unchanged.

The size-normalized baseline and its intervals are explicitly **N/A** because
historical exposure vintages are unavailable under M3's version policy. This is
a remaining data limitation, not a completed exposure-normalization comparison.
All three models have lower point-estimate PR-AUC than raw count in the primary
12-month paired comparison; the report makes no improvement claim. Early B/C
folds with fewer than ten training events are unavailable under ADR-008. Model A
always drives live ranking; B remains the primary statistical output. No
accuracy claims extend beyond 2025-08.

## M5: Dashboard
- [x] Four views, banners (screening tool; historical-regime estimates; enforcement dormant), limitations page
- [x] Data freshness display from CCDB `_meta`
- [x] Manual snapshot refresh (`make refresh-dashboard`); no scheduled job or automatic commits
- [ ] Deployed (Streamlit Community Cloud or similar)

**Exit:** a public URL works and every view loads in under 3 seconds. Refreshes are manual; no multi-day refresh streak is required.

## M6: Presentation
- [ ] Narrative and demo script ([11_presentation.md](11_presentation.md))
- [ ] Backup screenshots or video in case the live demo fails

## Fallbacks if M1 finds too few events

Apply these in order, and record the choice in ADR-008:
1. Use the secondary window (through 2025-08) as the primary.
2. Include non-mortgage CFPB actions against the same mortgage companies (the "any action" target).
3. Add state attorney general and state banking regulator mortgage actions as events.
4. Add OCC, FDIC, and Federal Reserve enforcement actions involving mortgage practices.
5. Present the result as a descriptive event study (event-aligned charts plus a ranking evaluation) rather than a fitted hazard model.

## Stretch goals (only after M5)
- **S1:** Multi-regulator labels, if not already added as a fallback. This also gives the live product events to evaluate against while CFPB is dormant.
- **S2:** Change-point alerts (CUSUM or Bayesian online) with a weekly alert feed.
- **S3:** Expand beyond mortgage to auto lending and debt collection, with proper denominators.
- **S4:** Historical narrative NLP from the frozen FOIA archive (21 zips, 1.43 GB), joined on `Complaint ID`. **Backtest only.** It can never feed the live score, because no new narratives are published. Mortgage narrative coverage was 58.9% in the Jan–Feb 2025 archive file.
- **S5:** Stock event study for publicly traded companies in the crosswalk, presented as exploratory.
- **S6:** Recurrent-event models for companies with multiple actions.
