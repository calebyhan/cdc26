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
- [ ] Productionize the enforcement scraper: stop-on-no-new-slugs, check against the 386 total, save raw HTML
- [ ] Split captions into parties. Tag individuals and non-entities
- [ ] Hand-label `mortgage_related` for every action (product tags, confirmed by reading the summary)
- [ ] Build the enforcement ↔ CCDB product crosswalk (about 20 rows)
- [ ] **Count mortgage-related events in 2014-01 → 2025-08**, and separately through 2024-12. Record both in ADR-008 and set the feature budget

**Exit:** a labeled event table with event counts. If the primary count is below about 20, choose a fallback immediately (see below).

## M2: Entity resolution
- [ ] `normalize()` from the spike, plus exact-key matching and first-token-blocked `token_sort_ratio`
- [ ] Review queue for scores 85–95
- [ ] Hand-verify the top 150 mortgage names and every mortgage-related enforcement party (budget: half a day)
- [ ] FDIC rollup by `RSSDHCR`. Mergers from `/history`, plus a hand-kept nonbank rename list (Nationstar/Mr. Cooper, Ocwen/Onity, Ditech, …)
- [ ] Publish `crosswalk.csv`
- [ ] Decide whether NIC or GLEIF are needed for the remaining gaps

**Exit:** at least 94% of mortgage complaints map to a reviewed `entity_id`, and 100% of company parties in mortgage-related actions are mapped.

## M3: Panel and features
- [ ] FDIC quarterly financials (summed per holding company) and HMDA lender-year counts, each with `available_from`
- [ ] `company_month` panel with counting-process fields and horizon labels
- [ ] All complaint features (structured fields only), plus exposure and financial features
- [ ] Unit tests: point-in-time joins, no future rows, window arithmetic, ordering by `Date received`

**Exit:** the panel builds from scratch, and the leakage tests pass.

## M4: Models and backtest
- [ ] Model A (transparent anomaly score)
- [ ] Model B (discrete-time hazard) and Model C (Cox), time-ordered cross-validation
- [ ] Rolling-cutoff backtest: primary window (≤ 2024-12), secondary window (≤ 2025-08), with and without dismissed actions
- [ ] Event-aligned chart with matched peers
- [ ] Error review
- [ ] Auto-generated backtest report

**Exit:** `reports/backtest_*.md` exists with metrics and confidence intervals for every model and baseline.

## M5: Dashboard
- [ ] Four views, banners (screening tool; historical-regime estimates; enforcement dormant), limitations page
- [ ] Data freshness display from CCDB `_meta`
- [ ] Daily GitHub Actions refresh
- [ ] Deployed (Streamlit Community Cloud or similar)

**Exit:** a public URL works, the daily refresh has succeeded at least 3 days in a row, and every view loads in under 3 seconds.

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
