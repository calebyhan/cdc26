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

## Planned repository layout

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

## Quickstart (planned)

```bash
make setup      # create env, install deps
make ingest     # download bulk files and convert all sources to Parquet
make delta      # daily: pull new + trailing-30-day complaints from the CCDB API and upsert
make resolve    # build canonical company IDs and crosswalk
make features   # build company-month panel
make backtest   # run rolling-cutoff evaluation
make app        # launch dashboard
```
