# Mortgage Complaint Early-Warning System (MVP 1)

A transparent system that ranks mortgage lenders and servicers by **abnormal complaint activity**, using public complaints, mortgage activity, corporate identity, and financial-condition data. It is validated by backtesting against historical CFPB enforcement actions (2012–2025).

The product has two halves, because CFPB enforcement has been dormant since August 2025 (see [FINDINGS.md](FINDINGS.md)):
- **Live:** a daily-refreshed anomaly ranking built only from structured complaint fields.
- **Historical:** a backtest showing whether the same signals preceded the enforcement actions that did happen.

> **This is a regulatory-risk screening tool.** A high score means a company shows an unusual complaint signal relative to its size and peers. It is not evidence or a finding that the company violated any law.

## Core question

Among mortgage lenders, mortgage servicers, and bank-affiliated mortgage companies, does an unusual rise in *normalized* CFPB complaints predict a CFPB enforcement action within the next 6–18 months?

## What we know from the data so far

Profiled from the CFPB complaint export (`complaints.csv`, pulled 2026-09-26):

| Fact | Value | Implication |
|---|---|---|
| Total complaints (all products) | 18.0M, Dec 2011 – Sep 2026 | Store as Parquet and query with DuckDB |
| `Product = Mortgage` | 461,350 complaints | This is the MVP 1 universe |
| Distinct mortgage company names | 2,524 | Entity resolution is required |
| Names with ≥50 mortgage complaints | 290 | Realistic modeling universe is a few hundred entities |
| Mortgage volume per year since 2018 | ~21k–25k, stable | No credit-bureau-style volume distortion in this product |
| Top names | Wells Fargo, BofA, Ocwen, Chase, Nationstar, Shellpoint, SPS, Ditech, Mr. Cooper | Several are **nonbank servicers** with no FDIC data and little HMDA origination volume |
| Issue taxonomy | Old labels (e.g. "Loan modification,collection,foreclosure") and new labels (e.g. "Struggling to pay mortgage") both present | The complaint form changed in 2017, so severity mapping needs a crosswalk |
| Narrative text | CFPB stopped publishing narratives on 2026-08-14. Old ones survive only in a frozen FOIA archive | No live NLP, ever. Historical NLP is a stretch goal |
| Enforcement actions | 386 total, 2012-07-17 → 2025-08-21, none filed in the 13 months since | Enforcement is a historical label, not a live target |
| Top mortgage companies | Top 150 names = 94.1% of mortgage complaints | A hand-curated alias table is feasible |
| `Timely response? = No` (mortgage) | 1.9% | Rare-event feature only |

## Documentation map

| Doc | Purpose |
|---|---|
| [FINDINGS.md](FINDINGS.md) | Data-source spike: live API behavior, limits, schemas, gotchas |
| [00_project_spec.md](docs/00_project_spec.md) | Question, hypotheses, scope, success criteria |
| [01_data_sources.md](docs/01_data_sources.md) | Every dataset: role, access, fields, point-in-time availability |
| [02_data_model.md](docs/02_data_model.md) | Table schemas from raw data to model panel to score snapshots |
| [03_entity_resolution.md](docs/03_entity_resolution.md) | Canonical company IDs across all sources |
| [04_features.md](docs/04_features.md) | Feature catalog, severity map, normalization rules |
| [05_modeling.md](docs/05_modeling.md) | Target definition, transparent score, hazard models |
| [06_backtesting.md](docs/06_backtesting.md) | Rolling-cutoff protocol, metrics, baselines, leakage checks |
| [07_dashboard.md](docs/07_dashboard.md) | The four dashboard views and their data contracts |
| [08_roadmap.md](docs/08_roadmap.md) | Milestones, tasks, exit criteria, stretch goals |
| [09_decisions.md](docs/09_decisions.md) | Architecture decision log and open questions |
| [10_risks_limitations.md](docs/10_risks_limitations.md) | Methodological, ethical, and data caveats |
| [11_presentation.md](docs/11_presentation.md) | Narrative arc, demo script, rubric mapping |

## Repository layout

```
cfpb-ews/
├── README.md
├── Makefile                 # make ingest | resolve | features | train | backtest | app
├── pyproject.toml
├── data/
│   ├── raw/                 # untouched downloads (gitignored)
│   ├── staging/             # typed, cleaned Parquet
│   ├── reference/           # hand-maintained CSVs: severity_map, overrides, enforcement_labels
│   └── marts/               # company_month panel, score snapshots
├── src/ews/
│   ├── ingest/              # complaints, enforcement scraper, hmda, fdic, ffiec, gleif
│   ├── resolve/             # normalization, rapidfuzz candidates, alias table, rollup
│   ├── features/
│   ├── models/              # transparent score, discrete-time hazard, cox
│   ├── backtest/
│   └── app/                 # Streamlit dashboard
├── spike/                 # feasibility scripts from the data spike (see FINDINGS.md)
├── notebooks/               # exploration only; nothing the pipeline depends on
├── tests/
└── docs/
```

## Stack

Python 3.11+ · DuckDB + Parquet · Polars · requests + BeautifulSoup · rapidfuzz + a hand-curated alias table · statsmodels · lifelines · scikit-survival · Streamlit + Plotly · GitHub Actions (daily refresh)

## Quickstart (M0 and M1 implemented)

Requires Python 3.11+, `uv`, and `make` (macOS/Linux).

```bash
make setup      # create .venv and install the editable package + dev tools
make ingest     # download CSV if absent; rebuild all-product Parquet and mortgage staging
make delta      # new complaints + 30-day overlap, upsert by complaint_id
make enforcement # archive CFPB actions, validate reviewed labels, stage events + parties
make test
make lint       # ruff + black
```

Run commands from the repository root. For an existing export:
`make ingest CSV=/absolute/path/complaints.csv`. `DATA_DIR=/path/to/data` overrides
the output root; crosswalks remain in this repository's `data/reference/`.
A first download needs network access and about 6 GB of free space. Subsequent
`make ingest` runs reuse the raw CSV but **rebuild both Parquet files**; to reconcile
against a newer bulk export, replace the CSV with a fresh download first.

Outputs are `data/staging/complaints_all.parquet` (all products) and
`data/staging/stg_complaints.parquet` (Mortgage only). `data/staging/ews.duckdb`
exposes `stg_complaints` as a SQL view over its Parquet file, avoiding two mutable
copies. The view stores an absolute path; rerun ingestion after relocating data.
Dates are typed DATE, IDs BIGINT, ZIP codes strings, and `ingested_at` is UTC.
Issue and response crosswalks add severity and response eligibility columns;
in-progress/unknown responses remain available for future updates.

Delta pulls use JSON content-type checks, `search_after`, and 3.1-second pacing.
The overlap starts 29 days before the existing maximum received date (or today,
whichever is earlier), so missed days are included after downtime. Raw delta
JSONL is retained under `data/raw/deltas/`. A file lock prevents concurrent writers; complete
validation precedes atomic staging-file replacement. Failed pulls leave staging
unchanged; repeated unchanged payloads preserve ingestion timestamps.

Additional source tools: `make fdic`, `make hmda-spike`.
`make enforcement` caches raw HTML and SHA-256/URL/retrieval-time sidecars under
`data/raw/enforcement/`. It requires exactly 386 unique slugs matching the listing
count, stops repeated pagination, and validates every action label, party review,
and product mapping before staging. Missing or changed labels fail the build.
`make enforcement ENFORCEMENT_ARGS=--offline` rebuilds from that archive;
`ENFORCEMENT_ARGS=--refresh` fetches a new live snapshot that may require reference
reviews. `DATA_DIR` also applies to enforcement. Raw HTML and staging are ignored
by Git; the reviewed references are committed source data.
The action-grain `enforcement_events` and party-grain `stg_enforcement` are Parquet
files with DuckDB views, accompanied by CSVs and `enforcement_counts.json`.
See [ADR-008](docs/09_decisions.md#adr-008-m1-event-count-and-fallback-panel-eligibility-pending-m2m3)
for the 86/88 window counts and the remaining panel-eligibility gate.
Normalization and blocked candidate matching are in `ews.resolve.matching`.
`make format` applies formatting. To enable Git hooks, run
`.venv/bin/pre-commit install`. The original `spike/` remains unchanged.

`make resolve` publishes [crosswalk.csv](data/marts/crosswalk.csv), a review queue,
typed entity/alias tables and complaint/enforcement entity joins. Replay with
`make resolve RESOLVE_ARGS=--offline`. The current Codex-reviewed aliases cover
94.0646% of mortgage complaints and all 131 named company-party rows in mortgage
actions. Independent human adjudication remains outstanding; enable its separate
gate with `RESOLVE_ARGS='--offline --require-human-review'`. Review inputs and
merger/rename decisions live in `data/reference/`; see the
[resolution report](docs/12_entity_resolution_report.md) for source gaps and
identifier/ownership limits. GLEIF and NIC remain deferred under ADR-012.

Features, models, backtesting, and the app are later milestones;
the corresponding package directories are scaffolded, not yet implemented.
See [FINDINGS §9](FINDINGS.md#9-hmda-spike-and-m0-ingestion-validation-2026-09-26)
for measured M0 results and HMDA constraints.
