from copy import deepcopy

import numpy as np
import pandas as pd
import pytest
from sklearn.metrics import average_precision_score

from ews.backtest.data import (
    evaluation_rows,
    previous_rows,
    risk_panel,
    training_rows,
    validate_grid,
)
from ews.backtest.metrics import MetricSample, evaluate, weighted_median
from ews.backtest.pipeline import cutoff_dates
from ews.backtest.report import estimate, number
from ews.backtest.validation import tune
from ews.features.panel import NUMERIC_FEATURES
from ews.models.anomaly import RAW_COMPONENTS, AnomalyModel, PeerTransform
from ews.models.hazard import (
    CoxHazard,
    LogisticHazard,
    Predictors,
    feature_budget,
    schoenfeld,
)


@pytest.fixture
def grid():
    records = []
    for entity, kind in [("a", "bank"), ("b", "nonbank_servicer"), ("c", "bank")]:
        for month in pd.date_range("2014-01-01", "2025-08-01", freq="MS"):
            stop = month + pd.DateOffset(months=1)
            values = {f: np.nan for f in NUMERIC_FEATURES}
            values.update(
                c_12m=12.0,
                c_selfz_12m=float(month.month % 3),
                c_accel=float(month.month % 4),
                sev3_share_12m=0.2,
                untimely_rate_12m=0.01,
                issue_mix_jsd=0.1,
            )
            records.append(
                dict(
                    values,
                    entity_id=entity,
                    month=month,
                    type=kind,
                    peer_group=kind,
                    entry_date=pd.Timestamp("2014-01-01"),
                    censor_date=pd.Timestamp("2025-08-31"),
                    interval_start=month,
                    interval_stop=stop,
                    start=(month - pd.Timestamp("2014-01-01")).days,
                    stop=(stop - pd.Timestamp("2014-01-01")).days,
                    fdic_available_from=pd.NaT,
                    hmda_available_from=pd.NaT,
                    complaints_received_before=month - pd.DateOffset(months=1),
                )
            )
    return pd.DataFrame(records)


@pytest.fixture
def actions():
    return pd.DataFrame(
        {
            "entity_id": ["a", "a", "b"],
            "date_filed": pd.to_datetime(["2016-06-15", "2018-03-15", "2020-05-15"]),
            "action_id": ["dismissed", "later", "retained"],
            "dismissal": ["confirmed", "not_documented", "not_documented"],
        }
    )


def test_dismissal_exclusion_reconstructs_followup(grid, actions):
    included = risk_panel(grid, actions, "2024-12-31", "include")
    excluded = risk_panel(grid, actions, "2024-12-31", "exclude_confirmed")
    assert included.loc[included.entity_id.eq("a"), "month"].max() == pd.Timestamp(
        "2016-06-01"
    )
    assert excluded.loc[excluded.entity_id.eq("a"), "month"].max() == pd.Timestamp(
        "2018-03-01"
    )
    assert included.loc[
        included.entity_id.eq("a") & included.event.eq(1), "event_date"
    ].iloc[0] == pd.Timestamp("2016-06-15")
    assert excluded.loc[
        excluded.entity_id.eq("a") & excluded.event.eq(1), "event_date"
    ].iloc[0] == pd.Timestamp("2018-03-15")


def test_training_embargo_and_next_month_label(grid, actions):
    panel = risk_panel(grid, actions, "2024-12-31")
    train = training_rows(panel, "2017-01-01", 6, "B")
    assert train.month.max() <= pd.Timestamp("2016-07-01")
    assert (train.month + pd.DateOffset(months=2) <= pd.Timestamp("2017-01-01")).all()
    row = train[train.entity_id.eq("a") & train.month.eq(pd.Timestamp("2016-05-01"))]
    assert row.next_event.tolist() == [1.0]
    cox = training_rows(panel, "2016-01-01", 6, "C")
    assert cox.event.sum() == 0
    assert cox.interval_stop.max() <= pd.Timestamp("2015-08-01")


def test_future_outcomes_cannot_change_training_targets(grid, actions):
    before = risk_panel(grid, actions, "2024-12-31")
    after_actions = pd.concat(
        [
            actions,
            pd.DataFrame(
                {
                    "entity_id": ["c"],
                    "date_filed": pd.to_datetime(["2024-08-01"]),
                    "action_id": ["future"],
                    "dismissal": ["not_documented"],
                }
            ),
        ]
    )
    after = risk_panel(grid, after_actions, "2024-12-31")
    for kind in ["B", "C"]:
        cols = (
            ["entity_id", "month", "start", "stop", "next_event"]
            if kind == "B"
            else ["entity_id", "month", "start", "stop", "event"]
        )
        a = training_rows(before, "2018-01-01", 12, kind)[cols].reset_index(drop=True)
        b = training_rows(after, "2018-01-01", 12, kind)[cols].reset_index(drop=True)
        pd.testing.assert_frame_equal(a, b)


def test_frozen_peer_transform_ignores_future_values_and_outcomes(grid):
    train = grid[grid.month.lt(pd.Timestamp("2017-01-01"))].copy()
    model = AnomalyModel().fit(train)
    artifact = deepcopy(model.artifact())
    test = grid[grid.month.eq(pd.Timestamp("2018-01-01"))].copy()
    a = model.score(test)
    test["event_next_12m"] = 9999
    test["c_selfz_12m_peer_z"] = 1e12
    assert np.array_equal(a, model.score(test))
    test["c_selfz_12m"] = 1e12
    model.score(test)
    assert model.artifact() == artifact
    own = PeerTransform().fit(train, ["c_selfz_12m"])
    assert own.stats["bank"]["c_selfz_12m"][0] == 1.0


def test_servicers_never_receive_anomaly_financial_components(grid):
    f = grid[grid.type.eq("nonbank_servicer")].head(3).copy()
    for column in [
        "c_per_bn_assets",
        "c_per_1k_orig",
        "noncurrent_ratio_lag",
        "provision_ratio_lag",
        "equity_to_assets_lag",
    ]:
        f[column] = [1.0, 2.0, 3.0]
    model = AnomalyModel().fit(f)
    assert model.components(f).normalized_rate.isna().all()
    assert model.components(f).financial_stress.isna().all()
    assert all(len(d) <= 3 for d in model.drivers(f))


def test_complete_horizons_and_no_post_august_accuracy(grid, actions):
    panel = risk_panel(grid, actions, "2025-08-31")
    with pytest.raises(ValueError, match="horizon"):
        evaluation_rows(panel, "2025-01-01", 12, "2025-08-31")
    with pytest.raises(ValueError, match="past 2025"):
        risk_panel(grid, actions, "2026-01-01")
    for window in ["primary", "secondary"]:
        end = pd.Timestamp("2024-12-31" if window == "primary" else "2025-08-31")
        for h in [6, 12, 18]:
            assert len(cutoff_dates(window, h)) >= 4
            assert all(
                t + pd.DateOffset(months=h) <= end for t in cutoff_dates(window, h)
            )


def test_corporate_censoring_and_first_day_boundary(grid, actions):
    g = grid.copy()
    g.loc[g.entity_id.eq("c"), "censor_date"] = pd.Timestamp("2017-02-15")
    p = risk_panel(g, actions, "2024-12-31")
    f = evaluation_rows(p, "2017-01-01", 6, "2024-12-31")
    assert "c" not in set(f.entity_id)
    a = actions.copy()
    a.loc[a.entity_id.eq("b"), "date_filed"] = pd.Timestamp("2017-01-01")
    f = evaluation_rows(
        risk_panel(grid, a, "2024-12-31"), "2017-01-01", 6, "2024-12-31"
    )
    assert "b" not in set(f.entity_id)


def sample(scores=(0.9, 0.8, 0.2, 0.1), outcomes=(1, 0, 1, 0)):
    f = pd.DataFrame(
        {
            "entity_id": ["a", "b", "c", "d"],
            "score": scores,
            "outcome": outcomes,
            "lead_months": [6.0, np.nan, 12.0, np.nan],
            "duration": [180, 365, 365, 365],
        }
    )
    return MetricSample(f)


def test_metrics_ties_short_lists_and_undefined_values():
    values = sample().compute()
    assert values["pr_auc"] == pytest.approx(
        average_precision_score([1, 0, 1, 0], [0.9, 0.8, 0.2, 0.1])
    )
    assert values["precision_10"] == 0.5
    assert values["recall_20"] == 1
    assert values["median_lead_months"] == 9
    assert sample(scores=(1, 1, 1, 1)).compute()["pr_auc"] == 0.5
    missing = sample(outcomes=(0, 0, 0, 0)).compute()
    assert np.isnan(missing["pr_auc"]) and np.isnan(missing["recall_20"])
    assert missing["precision_20"] == 0
    assert weighted_median(np.array([2.0, 8.0]), np.array([1, 1])) == 5


def test_cluster_bootstrap_reproducibility_and_paired_comparisons():
    samples = {
        ("2018-01-01", "A"): sample(),
        ("2019-01-01", "A"): sample(),
        ("2018-01-01", "raw_count"): sample(scores=(0.2, 0.8, 0.9, 0.1)),
        ("2019-01-01", "raw_count"): sample(scores=(0.2, 0.8, 0.9, 0.1)),
    }
    a = evaluate(samples, draws=40, seed=12)
    b = evaluate(samples, draws=40, seed=12)
    assert a == b
    assert len(a[0]) == 4
    assert a[1]["A"]["median_lead_months"]["value"] == 9
    row = next(r for r in a[2] if r["model"] == "A" and r["baseline"] == "raw_count")
    assert row["n_cutoffs"] == 2 and row["pr_auc_difference"] is not None


def test_previous_snapshot_never_falls_back_to_current(grid):
    scoring = (
        grid[grid.month.eq(pd.Timestamp("2017-01-01"))].copy().reset_index(drop=True)
    )
    scoring["c_12m"] = 99999
    previous = previous_rows(grid, scoring)
    assert previous.c_12m.tolist() == [12.0, 12.0, 12.0]
    new = scoring.iloc[[0]].copy()
    new["entity_id"] = "new"
    previous = previous_rows(grid, new)
    assert previous.c_12m.tolist() == [0.0]
    assert previous.c_selfz_12m.isna().all()


def test_source_availability_guard(grid):
    validate_grid(grid)
    grid.loc[0, "hmda_available_from"] = pd.Timestamp("2030-01-01")
    with pytest.raises(ValueError, match="Future"):
        validate_grid(grid)


def test_parameter_budget_and_fit_probabilities(grid, actions):
    assert [feature_budget(n) for n in [0, 9, 10, 19, 20, 25, 90]] == [
        0,
        0,
        1,
        1,
        2,
        2,
        2,
    ]
    panel = risk_panel(grid, actions, "2024-12-31")
    training = training_rows(panel, "2021-01-01", 6, "B")
    b = LogisticHazard().fit(training, allow_feature=False)
    assert b.artifact()["degrees_of_freedom"] == 1
    assert np.isfinite(b.cluster_se).all()
    scoring = evaluation_rows(panel, "2017-01-01", 6, "2024-12-31")
    one = b.predict(scoring, 6)
    two = b.predict(scoring, 12)
    assert ((one >= 0) & (two >= one) & (two <= 1)).all()
    ctrain = training_rows(panel, "2021-01-01", 6, "C")
    c = CoxHazard().fit(ctrain, allow_feature=False)
    assert c.artifact()["degrees_of_freedom"] == 1
    assert len(c.fitter.params_) == 0
    one = c.predict(scoring, 6)
    two = c.predict(scoring, 12)
    assert ((one >= 0) & (two >= one) & (two <= 1)).all()


def test_schoenfeld_sparse_training_and_report_na():
    f = pd.DataFrame(
        {"start": [0, 0], "stop": [1, 2], "event": [1, 0], "x": [0.0, 1.0]}
    )
    assert schoenfeld(f, 1.0)["p_value"] is None
    assert number(np.nan) == "N/A"
    assert estimate({"pr_auc": np.nan}, "pr_auc") == "N/A"
    assert "NaN" not in number(None)


def test_feature_allowlist_has_no_outcome_or_peer_z():
    assert not set(RAW_COMPONENTS) & {
        "event",
        "event_date",
        "event_next_12m",
        "prior_action",
    }
    assert not any(f.endswith("_peer_z") for f in RAW_COMPONENTS)


def test_inner_validation_is_embargoed_inside_outer_training(grid, actions):
    panel = risk_panel(grid, actions, "2025-08-31")
    for kind in ["B", "C"]:
        choice, audit = tune(panel, grid, pd.Timestamp("2023-01-01"), 12, kind)
        assert choice[0] == "anomaly"
        assert len(audit["folds"]) == 2
        for fold in audit["folds"]:
            validation = pd.Timestamp(fold["cutoff"])
            assert pd.Timestamp(
                fold["max_training_month"]
            ) <= validation - pd.DateOffset(months=12)
            assert pd.Timestamp(fold["validation_end"]) <= pd.Timestamp("2022-02-01")
            assert pd.Timestamp(fold["validation_end"]) < pd.Timestamp("2023-01-01")
        assert not audit["losses"]  # Three-company fixture cannot identify covariates.


def test_cox_ph_remedy_has_two_baselines_and_no_linear_effect(
    grid, actions, monkeypatch
):
    grid = grid.copy()
    grid["c_12m"] = grid.entity_id.map({"a": 12.0, "b": 48.0, "c": 96.0})
    panel = risk_panel(grid, actions, "2024-12-31")
    training = training_rows(panel, "2021-01-01", 6, "C")
    monkeypatch.setattr(
        "ews.models.hazard.schoenfeld", lambda *args: {"p_value": 0.001}
    )
    model = CoxHazard().fit(training, predictor="log_count")
    assert model.stratified and model.beta == 0
    assert model.artifact()["degrees_of_freedom"] == 2
    assert set(model.baselines) == {0, 1}
    scoring = evaluation_rows(panel, "2017-01-01", 6, "2024-12-31")
    predicted = model.predict(scoring, 6)
    assert np.isfinite(predicted).all()
    assert ((predicted >= 0) & (predicted <= 1)).all()


def test_statistical_driver_attributions_use_frozen_peer_medians(grid):
    training = grid[grid.month.lt(pd.Timestamp("2016-01-01"))].copy()
    training["c_12m"] = 10 + training.month.dt.month
    transform = Predictors().fit(training)
    scoring = grid[grid.month.eq(pd.Timestamp("2018-01-01"))].copy()
    scoring["c_12m"] = 100
    values = transform.values(scoring, "log_count")
    drivers = transform.drivers(scoring, "log_count", 2.0)
    for i, (group, driver) in enumerate(zip(scoring.peer_group, drivers)):
        median = transform.explanation_medians[group]["log_count"]
        assert driver[0]["contribution"] == pytest.approx(2 * (values[i] - median))
    assert all(len(d) == 3 for d in transform.drivers(scoring, "anomaly", 2.0))
    assert transform.drivers(scoring, None, 0) == [[], [], []]
