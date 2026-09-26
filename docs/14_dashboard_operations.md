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

Model A sets the snapshot default order. B/C models and training transforms are
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

Public URL: https://unccdc26.streamlit.app.

Streamlit Community Cloud configuration:

- Repository: `calebyhan/cdc26`
- Branch: `main`
- Entrypoint: `streamlit_app.py`
- Python: 3.11
- Dependencies: root `requirements.txt`
- Access: public

The deployment must use the real Streamlit entrypoint, with a Python server and
WebSocket support. A static HTML preview is not an equivalent deployment.
The deployment is public and its app health endpoint is verified. Community
Cloud embeds the app at `/~/+/`, so the root `/_stcore/health` path serves the
HTML wrapper; verification also checks `/~/+/_stcore/health` for a plain `ok`.

## Manual refresh

The app serves the committed snapshot in `data/dashboard`; opening a page does
not call the CCDB API. There is no scheduled workflow or automatic commit.

When you want updated data, run:

```sh
make refresh-dashboard
```

This validates CCDB JSON and `_meta.last_indexed`, pulls new complaints and the
trailing 30 days (plus missed days after downtime), rebuilds reviewed alias links
and both panel marts, rescores Model A and the frozen B/C models, rebuilds chart
aggregates, and tests every view. Coverage below 94% stops publication. After
validation, it records the successful refresh timestamp. The refresh command
saves `reports/latest_refresh.json` atomically after successful ingestion.
Review the updated `data/dashboard` bundle and reports, then commit them normally
under your own Git identity if you want the deployed snapshot updated.

The refresh uses a temporary workspace until ingestion, linking and scoring
checks pass. Failed source refreshes leave the published bundle intact.
Historical backtest results remain the archived M4 evaluation. FDIC/HMDA releases,
ownership and enforcement status retain their separate source/review process.
Between manual updates, the freshness display continues to show the saved source
metadata and last successful refresh rather than suggesting live data.

`make dashboard-marts` rebuilds chart-ready aggregates from existing local data
without fetching new complaints. An optional `refresh-state.tar.gz` checkpoint
on the `dashboard-state` GitHub release can restore the small operational inputs
on another machine; it is not maintained automatically. Create a local checkpoint
with `python -m ews.app.checkpoint --output /tmp/refresh-state.tar.gz`.

## Exit evidence

`reports/dashboard_performance.json` records actual Streamlit AppTest timings.
These cover script execution and charts, not deployment startup, browser assets
or network latency. The tests require each view to render in less than three
seconds and check default pages, filtering, probability hover presentation,
model artifact replay, freshness alerts and complete event-aligned offsets.

Run `python -m ews.app.acceptance --url https://<actual-app>.streamlit.app` to
record public Streamlit health and performance evidence. This check does not
need GitHub access. The exit gate requires public deployment and each deployed
view loading in under three seconds; there is no refresh-streak requirement.

A real-browser switching benchmark is available after opening the app in an
agent-browser session:

```sh
python scripts/benchmark_dashboard.py --session dashboard-qa
python -m ews.app.acceptance --url https://<actual-app>.streamlit.app \
  --browser-report reports/dashboard_browser_performance.json
```

The browser benchmark includes chart rendering and CLI overhead, after initial
assets have loaded. When the session starts with the init script shown below,
the report also captures first-page readiness. Without that script, initial
page load remains unverified. Local localhost results never count as public
deployment evidence.

## Public performance evidence

The fresh-browser measurement includes the Community Cloud wrapper, network,
asset downloads, the first app session and a 150ms readiness stability window.
View switching is measured separately after assets have loaded. The public
benchmark observed all five view switches below three seconds, while initial
navigation took 8.36 seconds; the strict initial-load gate remains unmet.
See `reports/dashboard_browser_performance.json` and
`reports/dashboard_acceptance.json` for measurements and remaining checks.

To reproduce first-load measurement, launch a fresh browser session with the
provided init script before navigation:

```sh
agent-browser --session dashboard-public --init-script scripts/dashboard_initial_load.js \
  open https://unccdc26.streamlit.app
python scripts/benchmark_dashboard.py --session dashboard-public
```
