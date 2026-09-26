"""Dashboard acceptance checks against real M4 outputs and published aggregates."""

import json
import time
from pathlib import Path

import duckdb
import numpy as np
from streamlit.testing.v1 import AppTest

from ews.app.dashboard import BANNER, REGIME, VIEWS, band, probability_cell
from ews.app.data import BUNDLE
from ews.app.precompute import restore_hazard

ROOT = Path(__file__).resolve().parents[1]


def test_m4_bundle_contract():
    manifest = json.loads((BUNDLE / "manifest.json").read_text())
    assert manifest["event_chart"]["pairs"] > 0
    with duckdb.connect() as con:
        frame = con.read_parquet(str(BUNDLE / "leaderboard.parquet")).df()
        assert frame.anomaly_score.is_monotonic_decreasing
        assert not frame.entity_id.duplicated().any()
        assert frame.sparkline.map(len).le(24).all()
        for column in [f"{m}_{h}" for m in ["B", "C"] for h in [6, 12, 18]]:
            assert frame[column].between(0, 1).all()
        aggregate = con.read_parquet(str(BUNDLE / "event_aggregate.parquet")).df()
        assert set(aggregate.relative_month) == set(range(-48, 13))
        assert (aggregate.low <= aggregate.value).all()
        assert (aggregate.value <= aggregate.high).all()
    assert sum(p.stat().st_size for p in BUNDLE.glob("*.parquet")) < 8_000_000


def test_probability_numbers_only_on_hover():
    assert [band(p) for p in [0, 0.029, 0.03, 0.099, 0.1, 1, np.nan]] == [
        "low",
        "low",
        "elevated",
        "elevated",
        "high",
        "high",
        "unavailable",
    ]
    cell = probability_cell(0.04123)
    assert 'title="historical-regime estimate: 4.12%"' in cell
    assert ">elevated</span>" in cell
    assert "4.12%" not in cell.split(">")[1]


def test_frozen_hazard_replays_saved_m4_predictions():
    from ews.backtest.data import load_grid, previous_rows

    grid = load_grid(ROOT / "data", rebuild=False)
    with duckdb.connect() as con:
        snapshots = con.read_parquet(
            str(ROOT / "data/marts/score_snapshot.parquet")
        ).df()
    for kind in ["B", "C"]:
        path = sorted(
            (ROOT / "reports/models").glob(f"primary_include_*_12m_{kind}.json")
        )[-1]
        cutoff = path.name.split("_")[2]
        source = snapshots[
            (snapshots["window"] == "primary")
            & snapshots.policy.eq("include")
            & snapshots.horizon.eq(12)
            & snapshots.model.eq(kind)
            & snapshots.cutoff.eq(cutoff)
        ].sort_values("entity_id")
        frame = (
            grid[grid.month.eq(cutoff) & grid.entity_id.isin(source.entity_id)]
            .sort_values("entity_id")
            .reset_index(drop=True)
        )
        model = restore_hazard(json.loads(path.read_text())["model"])
        actual = model.predict(
            frame, 12, previous_rows(grid, frame) if kind == "B" else None
        )
        np.testing.assert_allclose(
            actual, source.score.to_numpy(), rtol=1e-10, atol=1e-12
        )


def test_all_views_render_under_three_seconds():
    # Imports/framework startup are excluded; each fresh Streamlit script execution
    # and all chart construction are included. Browser/network timings are separate.
    results = {}
    for view in VIEWS:
        app = AppTest.from_file(str(ROOT / "streamlit_app.py"), default_timeout=15)
        app.query_params["view"] = view
        started = time.perf_counter()
        app.run()
        elapsed = time.perf_counter() - started
        assert not app.exception, [e.message for e in app.exception]
        assert any(BANNER in e.value for e in app.info)
        assert any(REGIME in e.value for e in app.warning)
        assert app.session_state["render_seconds"] < 3, view
        assert elapsed < 3, (view, elapsed)
        results[view] = {
            "script_seconds": app.session_state["render_seconds"],
            "apptest_seconds": elapsed,
        }
    report = {
        "scope": "Local Streamlit AppTest; imports excluded; network/browser/deployed cold start unverified",
        "views": results,
    }
    (ROOT / "reports/dashboard_performance.json").write_text(
        json.dumps(report, indent=2) + "\n"
    )


def test_leaderboard_filters_and_historical_hazard_table():
    app = AppTest.from_file(str(ROOT / "streamlit_app.py"), default_timeout=15).run()
    app.multiselect[0].set_value(["bank"]).run()
    app.checkbox[0].check().run()
    assert not app.exception
    app.sidebar.radio[0].set_value("Backtest results").run()
    # Last selectbox chooses the hit-table model; a historical probability must
    # appear as a band, with its numeric value only in Plotly hover data.
    app.selectbox[3].set_value(app.selectbox[3].options[-1]).run()
    app.selectbox[4].set_value("B").run()
    assert not app.exception
    tables = [e.value for e in app.dataframe]
    table = next(t for t in tables if "historical-regime estimate" in t.columns)
    assert set(table["historical-regime estimate"]) <= set(
        ["low", "elevated", "high", "unavailable"]
    )
    assert "score" not in table.columns


def test_manual_snapshot_acceptance_needs_no_github_access():
    from ews.app.acceptance import audit

    result = audit()
    assert result["refresh_mode"] == "manual"
    assert result["exit_criteria_met"] is False
    assert "consecutive_successful_refresh_dates" not in result
    assert "runs" not in result
    assert not any("refresh" in item.lower() for item in result["remaining"])


def test_freshness_warning_and_missing_data_path(monkeypatch):
    from ews.app import dashboard

    info = dashboard.manifest()
    info["ccdb_meta"] = {
        "last_indexed": "2026-09-26T12:00:00-05:00",
        "is_data_stale": True,
        "has_data_issue": False,
    }
    monkeypatch.setattr(dashboard, "manifest", lambda: info)
    app = AppTest.from_file(str(ROOT / "streamlit_app.py"), default_timeout=15).run()
    assert not app.exception
    assert any("CCDB reports stale data" in e.value for e in app.warning)


def test_navigation_keeps_widget_identity_stable():
    app = AppTest.from_file(str(ROOT / "streamlit_app.py"), default_timeout=15).run()
    for view in VIEWS[1:] + VIEWS[:2]:
        app.sidebar.radio[0].set_value(view).run()
        assert not app.exception
        assert app.sidebar.radio[0].value == view
        assert any(title.value == view for title in app.title)


def test_bank_financial_panel_uses_available_exposures():
    from ews.app.data import read

    banks = read("leaderboard")
    banks = banks[banks.peer_group.eq("bank") & banks.normalized_rate.notna()]
    app = AppTest.from_file(str(ROOT / "streamlit_app.py"), default_timeout=15)
    app.query_params["view"] = "Company detail"
    app.query_params["company"] = banks.entity_id.iloc[0]
    app.run()
    assert not app.exception
    assert any(metric.label == "Assets ($bn)" for metric in app.metric)
    assert any(metric.label == "Equity / assets" for metric in app.metric)


def test_community_cloud_health_checks_app_frame(monkeypatch):
    from types import SimpleNamespace

    from ews.app import acceptance

    requested = []

    def response(url, timeout):
        requested.append(url)
        body = "ok" if "/~/+/" in url else "<!doctype html><html></html>"
        return SimpleNamespace(ok=True, text=body)

    monkeypatch.setattr(acceptance.requests, "get", response)
    result = acceptance.audit("https://unccdc26.streamlit.app")
    assert result["public_streamlit_health_verified"]
    assert requested == [
        "https://unccdc26.streamlit.app/_stcore/health",
        "https://unccdc26.streamlit.app/~/+/_stcore/health",
    ]
    assert not result["exit_criteria_met"]


def test_public_acceptance_separates_initial_load_from_view_switches(
    monkeypatch, tmp_path
):
    from datetime import datetime, timezone
    from types import SimpleNamespace

    from ews.app import acceptance

    monkeypatch.setattr(
        acceptance.requests,
        "get",
        lambda *args, **kwargs: SimpleNamespace(ok=True, text="ok"),
    )
    browser = {
        "public_url": "https://unccdc26.streamlit.app",
        "measured_at": datetime.now(timezone.utc).isoformat(),
        "initial_page_load_verified": True,
        "views": {view: {"seconds": 1.0} for view in VIEWS},
    }
    path = tmp_path / "browser.json"
    for initial_seconds, expected in [(2.0, True), (8.36, False)]:
        browser["initial_page_load_seconds"] = initial_seconds
        path.write_text(json.dumps(browser))
        result = acceptance.audit(browser["public_url"], path)
        assert result["deployed_view_switching_under_three_seconds"]
        assert result["deployed_initial_load_under_three_seconds"] is expected
        assert result["exit_criteria_met"] is expected
