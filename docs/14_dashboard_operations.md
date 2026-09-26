# M5 dashboard operations

Run `uv pip install --python .venv/bin/python -e '.[dev,dashboard]'`, then
`make dashboard-marts` and `make dashboard`. M4 A/B/C model JSON artifacts,
score snapshots, backtest metrics and diagnostic reports must already exist.
The published bundle in `data/dashboard` ships with the repository, so the app
starts without downloading raw complaints or training models.

The four views and limitations page use DuckDB to read only the chart-ready
Parquet bundle. Streamlit caches are keyed by manifest modification time.
Company timelines use the uncensored M4 feature grid so post-filing observations
remain visible. Complaint trends use received month; scores use the full
calendar-month complaint buffer. The aggregate matched-peer chart retains M4's
baseline matches, updates trajectories from the feature grid, and reports
company-cluster bootstrap intervals. Excluded early filings are explicitly
listed; the chart does not claim complete coverage of every filed company.

Model A sets the live default order. B/C models and training transforms are
restored from the latest **primary**, pre-2025 artifact for each horizon, and
replayed against saved historical predictions in tests. Current features are
scored without refitting enforcement models after the regime change. The
historical-regime estimates have no present-regime calibration or accuracy claim.
Probability values appear only in hover text; visible cells contain bands.

Size bands use trailing complaint counts because there is no comparable size
exposure for every peer type. State filters use the buffered trailing 12-month
complaint geography, not company domicile. The active-action proxy conservatively
includes `Pending Litigation` and `Post Order/Post Judgment`; current archived
status cannot prove every order remains active. Change-point markers are a
transparent threshold rule, not a fitted segmentation model. NIC/GLEIF parent
chains are absent from M2: the ownership panel shows reviewed relationships and
FDIC history and discloses the missing parent coverage.

## Deployment

Streamlit Community Cloud configuration:

- Repository: `calebyhan/cdc26`
- Branch: `main`
- Entrypoint: `streamlit_app.py`
- Python: 3.11
- Dependencies: root `requirements.txt`
- Access: public

The deployment must use the real Streamlit entrypoint, with a Python server and
WebSocket support. A static HTML preview is not an equivalent deployment.
The account owner must sign in to Community Cloud if no authenticated hosting
session exists. Once deployed, record and verify the actual URL; do not infer it
from a proposed subdomain.

## Daily refresh

`.github/workflows/daily-refresh.yml` runs at 10:17 UTC daily and supports manual
dispatch. It restores the small `refresh-state.tar.gz` operational checkpoint
from the `dashboard-state` GitHub release. The checkpoint contains typed
complaints, frozen exposure sources, reviewed identity marts and archived M4
scores/metrics, not the 13GB raw archive or complaint narratives.

`python -m ews.app.checkpoint --output /tmp/refresh-state.tar.gz` creates the
checkpoint. Initial setup publishes this archive as a release asset named
`refresh-state.tar.gz` on the `dashboard-state` release. After each successful
refresh, the workflow updates that asset for the next run.

The job validates CCDB JSON and `_meta.last_indexed`, pulls new data and the
trailing 30 days (plus missed days after downtime), rebuilds dated reviewed alias
links and both panel marts, rescores Model A and the frozen B/C models, rebuilds
chart aggregates, and tests all views. An unreviewed-name coverage drop below
94% stops publication. Only after these checks does it record the successful
refresh timestamp and commit the published bundle. GitHub must permit
`GITHUB_TOKEN` contents writes on `main`; branch protections may require a
separate publishing branch and matching deployment configuration.

The refresh uses a temporary workspace until all ingestion/linking/scoring
checks pass. Failed source refreshes leave the published dashboard bundle intact.
Historical backtest results remain the archived M4 evaluation rather than being
silently retrained by the daily job. FDIC/HMDA releases, ownership and enforcement
status require their separate source/review process; they are not claimed to be
updated daily by CCDB ingestion.

## Exit evidence

`reports/dashboard_performance.json` records actual Streamlit AppTest timings.
These cover script execution and charts, not deployment startup, browser assets
or network latency. The tests require each view to render in less than three
seconds and check default pages, filtering, probability hover presentation,
model artifact replay, freshness alerts and complete event-aligned offsets.

Run `python -m ews.app.acceptance --url https://<actual-app>.streamlit.app` to
record public Streamlit health and the latest real GitHub run history. Three
successful runs on the same date count as one date. Missing dates or a later
failed attempt break the streak. The exit requirement needs three consecutive
successful dates plus separately measured browser timings at the deployed URL.
The acceptance report deliberately remains incomplete until all this evidence
exists; it does not use local build timestamps as proof of scheduled runs.

A real-browser switching benchmark is available after opening the app in an
agent-browser session:

```sh
python scripts/benchmark_dashboard.py --session dashboard-qa
python -m ews.app.acceptance --url https://<actual-app>.streamlit.app \
  --browser-report reports/dashboard_browser_performance.json
```

The browser benchmark includes chart rendering and CLI overhead, after initial
assets have loaded. It explicitly leaves initial-page-load verification false;
measure and record cold initial page readiness separately before claiming the
full deployment performance gate. Its local localhost results never count as
public deployment evidence.
