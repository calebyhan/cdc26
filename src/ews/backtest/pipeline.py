"""Fit transparent/hazard models, rolling evaluations, diagnostics, and report artifacts."""

import argparse
import json
import tempfile
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

from ews.backtest.analysis import calibration, error_review, event_chart, write_json
from ews.backtest.data import (
    PRIMARY_END,
    SECONDARY_END,
    evaluation_rows,
    fingerprint,
    load_actions,
    load_grid,
    previous_rows,
    read_frame,
    risk_panel,
    training_rows,
)
from ews.backtest.metrics import METRICS, MetricSample, evaluate, seeded_score
from ews.backtest.report import generate
from ews.backtest.validation import tune
from ews.models.anomaly import AnomalyModel, PeerTransform, raw_components
from ews.models.hazard import CoxHazard, LogisticHazard, feature_budget

MODEL_NAMES = [
    "A",
    "B",
    "C",
    "raw_count",
    "size_normalized",
    "prior_action",
    "random",
    "self_normalized",
]


def cutoff_dates(window, horizon):
    end = PRIMARY_END if window == "primary" else SECONDARY_END
    final = 2023 if window == "primary" else 2025
    return [
        pd.Timestamp(year, 1, 1)
        for year in range(2016, final + 1)
        if pd.Timestamp(year, 1, 1) + pd.DateOffset(months=horizon) <= end
    ]


def empty_metrics(row):
    for metric in METRICS:
        row.update(
            {
                metric: None,
                metric + "_low": None,
                metric + "_high": None,
                metric + "_valid_bootstraps": 0,
            }
        )
    return row


def unpack_metrics(row, values):
    for name, value in values.items():
        row.update(
            {
                name: value["value"],
                name + "_low": value["low"],
                name + "_high": value["high"],
                name + "_valid_bootstraps": value["valid_bootstraps"],
            }
        )
    return row


def run(
    data_dir=Path("data"),
    reports=Path("reports"),
    draws=400,
    seed=20260926,
    rebuild_grid=True,
):
    data_dir, reports = Path(data_dir), Path(reports)
    if draws < 20:
        raise ValueError("At least 20 bootstrap draws required")
    reference = data_dir / "reference"
    provenance_files = [
        reference / "enforcement_labels.csv",
        reference / "enforcement_dismissals.csv",
        reference / "entity_manual.csv",
        reference / "alias_manual.csv",
        data_dir / "marts/company_month.parquet",
    ]
    hashes = {str(p): fingerprint(p) for p in provenance_files}
    grid = load_grid(data_dir, rebuild_grid)
    actions, reviewed = load_actions(data_dir)
    entities = read_frame(data_dir / "marts/entity.parquet")
    panels = {
        (window, policy): risk_panel(grid, actions, end, policy)
        for window, end in [("primary", PRIMARY_END), ("secondary", SECONDARY_END)]
        for policy in ["include", "exclude_confirmed"]
    }
    results, comparisons, diagnostics, predictions = [], [], [], []
    reports.mkdir(parents=True, exist_ok=True)
    # Publish the complete output set only after models, checks, and report generation succeed.
    with tempfile.TemporaryDirectory(prefix=".backtest-", dir=reports) as temporary:
        output = Path(temporary)
        artifacts = output / "models"
        artifacts.mkdir()
        for (window, policy), panel in panels.items():
            end = PRIMARY_END if window == "primary" else SECONDARY_END
            print(
                f"Backtest {window}/{policy}: {int(panel.event.sum())} first-company events",
                flush=True,
            )
            for horizon in [6, 12, 18]:
                samples, metadata = {}, {}
                for cutoff in cutoff_dates(window, horizon):
                    scoring = evaluation_rows(panel, cutoff, horizon, end)
                    if scoring.empty:
                        continue
                    maximum = cutoff - pd.DateOffset(months=horizon)
                    transform_rows = panel[panel.month <= maximum].copy()
                    anomaly = AnomalyModel().fit(transform_rows)
                    scores = {
                        "A": anomaly.score(scoring),
                        "raw_count": scoring.c_12m.to_numpy(),
                        "random": np.array(
                            [seeded_score(e, seed) for e in scoring.entity_id]
                        ),
                        "prior_action": scoring.prior_action.to_numpy() * 1e6
                        + np.log1p(scoring.c_12m.to_numpy()),
                    }
                    own = PeerTransform().fit(transform_rows, ["c_selfz_12m"])
                    scores["self_normalized"] = own.transform(scoring)[
                        "c_selfz_12m"
                    ].to_numpy()
                    size_fit = PeerTransform().fit(
                        raw_components(transform_rows), ["normalized_rate"]
                    )
                    normalized = raw_components(scoring)
                    scores["size_normalized"] = (
                        size_fit.transform(normalized)["normalized_rate"]
                        .where(normalized.normalized_rate.notna())
                        .to_numpy()
                    )
                    driver_values = {"A": anomaly.drivers(scoring)}
                    status = {}
                    for kind, cls in [("B", LogisticHazard), ("C", CoxHazard)]:
                        training = training_rows(panel, cutoff, horizon, kind)
                        events = (
                            int(training.next_event.sum())
                            if kind == "B"
                            else int(training.event.sum())
                        )
                        budget = feature_budget(events)
                        diagnostic = {
                            "window": window,
                            "policy": policy,
                            "horizon": horizon,
                            "cutoff": cutoff.isoformat(),
                            "model": kind,
                            "training_rows": len(training),
                            "training_events": events,
                            "budget": budget,
                            "max_training_month": (
                                training.month.max().isoformat()
                                if len(training)
                                else None
                            ),
                            "training_outcome_end": (
                                (
                                    training.month.max() + pd.DateOffset(months=2)
                                ).isoformat()
                                if len(training) and kind == "B"
                                else (maximum + pd.DateOffset(months=1)).isoformat()
                            ),
                        }
                        if budget < 1:
                            status[kind] = (
                                f"Unavailable: {events} training events; zero parameter budget"
                            )
                            diagnostic["status"] = status[kind]
                            diagnostics.append(diagnostic)
                            continue
                        choice, cv = tune(panel, grid, cutoff, horizon, kind)
                        diagnostic["validation"] = cv
                        try:
                            model = cls().fit(
                                training, *choice, allow_feature=budget >= 2
                            )
                            scores[kind] = model.predict(
                                scoring,
                                horizon,
                                previous_rows(grid, scoring) if kind == "B" else None,
                            )
                            driver_values[kind] = model.drivers(scoring)
                            artifact = model.artifact()
                            if artifact["degrees_of_freedom"] > budget:
                                raise ValueError(
                                    "Event-based degrees-of-freedom cap exceeded"
                                )
                            diagnostic.update(
                                status="fitted",
                                predictor=artifact["predictor"],
                                degrees_of_freedom=artifact["degrees_of_freedom"],
                            )
                            if kind == "C":
                                diagnostic["ph"] = artifact["ph"]
                            name = f"{window}_{policy}_{cutoff.date()}_{horizon}m_{kind}.json"
                            write_json(
                                artifacts / name,
                                {"training": diagnostic, "model": artifact},
                            )
                        except (ValueError, np.linalg.LinAlgError) as exc:
                            status[kind] = "Unavailable: fit failure: " + str(exc)
                            scores.pop(kind, None)
                            diagnostic["status"] = status[kind]
                        diagnostics.append(diagnostic)
                    name = f"{window}_{policy}_{cutoff.date()}_{horizon}m_A.json"
                    write_json(
                        artifacts / name,
                        {
                            "max_training_month": maximum.isoformat(),
                            "model": anomaly.artifact(),
                        },
                    )
                    for name in MODEL_NAMES:
                        key = cutoff.strftime("%Y-%m-%d"), name
                        predicted = np.asarray(
                            scores.get(name, np.full(len(scoring), np.nan))
                        )
                        valid = np.isfinite(predicted)
                        base = {
                            "window": window,
                            "policy": policy,
                            "cutoff": key[0],
                            "horizon": horizon,
                            "model": name,
                            "n_eligible": len(scoring),
                            "n_scored": int(valid.sum()),
                            "events": int(scoring.outcome.sum()),
                            "base_rate": float(scoring.outcome.mean()),
                            "n_cutoffs": 1,
                            "evaluation_end": (
                                cutoff + pd.DateOffset(months=horizon)
                            ).strftime("%Y-%m-%d"),
                            "status": status.get(
                                name,
                                (
                                    "scored"
                                    if valid.all()
                                    else "Unavailable: no verified denominator/transform"
                                ),
                            ),
                            "training_max_month": maximum.strftime("%Y-%m-%d"),
                        }
                        if not valid.all():
                            # Partial size/self-history coverage is not evaluated on
                            # a selected subcohort and compared with full-cohort models.
                            results.append(empty_metrics(base))
                            continue
                        scored = scoring.assign(score=predicted)
                        samples[key] = MetricSample(scored, name in ["B", "C"])
                        metadata[key] = base
                        for i, row in scored.iterrows():
                            driver = driver_values.get(name, [[]] * len(scored))[i]
                            predictions.append(
                                {
                                    "window": window,
                                    "policy": policy,
                                    "cutoff": key[0],
                                    "horizon": horizon,
                                    "model": name,
                                    "entity_id": row.entity_id,
                                    "score": float(row.score),
                                    "outcome": int(row.outcome),
                                    "event_date": row.event_date,
                                    "duration": int(row.duration),
                                    "lead_months": (
                                        float(row.lead_months)
                                        if pd.notna(row.lead_months)
                                        else np.nan
                                    ),
                                    "c_12m": float(row.c_12m),
                                    "drivers": json.dumps(driver),
                                }
                            )
                estimates, pooled, paired = evaluate(samples, draws, seed)
                for key, values in estimates.items():
                    results.append(unpack_metrics(metadata[key], values))
                for name in MODEL_NAMES:
                    point = {
                        "window": window,
                        "policy": policy,
                        "cutoff": "pooled",
                        "horizon": horizon,
                        "model": name,
                        "n_eligible": None,
                        "n_scored": None,
                        "events": None,
                        "base_rate": None,
                        "n_cutoffs": sum(k[1] == name for k in samples),
                        "evaluation_end": end.strftime("%Y-%m-%d"),
                        "training_max_month": None,
                        "status": "scored" if name in pooled else "Unavailable",
                    }
                    results.append(
                        unpack_metrics(point, pooled[name])
                        if name in pooled
                        else empty_metrics(point)
                    )
                comparisons += [
                    dict(r, window=window, policy=policy, horizon=horizon)
                    for r in paired
                ]
                print(
                    f"  {horizon}m: {len(cutoff_dates(window,horizon))} cutoffs",
                    flush=True,
                )
        prediction_frame = pd.DataFrame(predictions)
        result_frame = pd.DataFrame(results).sort_values(
            ["window", "policy", "horizon", "cutoff", "model"]
        )
        for group in prediction_frame.groupby(
            ["window", "policy", "horizon", "model"], sort=True
        ):
            _, rows = group
            # Stable saved ranks permit auditing every flagged company.
            prediction_frame.loc[rows.index, "rank"] = rows.groupby(
                "cutoff"
            ).score.rank(method="first", ascending=False)
        prediction_frame.to_csv(
            output / "score_snapshots.csv.gz",
            index=False,
            compression={"method": "gzip", "mtime": 0},
        )
        result_frame.to_csv(output / "backtest_results.csv", index=False)
        pd.DataFrame(comparisons).to_csv(
            output / "baseline_comparisons.csv", index=False
        )
        chart = event_chart(
            grid, panels[("primary", "include")], entities, output, draws, seed
        )
        errors = error_review(prediction_frame, grid, entities, output)
        bins = calibration(prediction_frame, output, draws, seed)
        live_month = grid.month.max()
        live = grid[grid.month.eq(live_month)].copy().reset_index(drop=True)
        live_model = AnomalyModel().fit(live)
        live["anomaly_score"] = live_model.score(live)
        live["drivers"] = [json.dumps(d) for d in live_model.drivers(live)]
        live = live.merge(
            entities[["entity_id", "display_name"]],
            on="entity_id",
            validate="one_to_one",
        )
        live = live.sort_values(
            ["anomaly_score", "entity_id"], ascending=[False, True]
        ).reset_index(drop=True)
        live["rank"] = np.arange(1, len(live) + 1)
        live["accuracy_claim"] = "none: descriptive live anomaly ranking"
        live[
            [
                "entity_id",
                "display_name",
                "month",
                "type",
                "peer_group",
                "rank",
                "anomaly_score",
                "drivers",
                "accuracy_claim",
            ]
        ].to_csv(output / "live_model_a.csv", index=False)
        write_json(
            artifacts / "live_A.json",
            {
                "as_of": live_month.isoformat(),
                "model": live_model.artifact(),
                "use": "live ranking; no probability or post-2025 accuracy claim",
            },
        )
        if hashes != {str(p): fingerprint(p) for p in provenance_files}:
            raise ValueError(
                "Protected labels, identities, or M3 panel changed during the backtest"
            )
        audit = {
            "seed": seed,
            "bootstrap_draws": draws,
            "input_sha256": hashes,
            "feature_grid_sha256": fingerprint(
                data_dir / "marts/company_month_features.parquet"
            ),
            "latest_evaluated_outcome": "2025-08-31",
            "live_as_of": live_month.isoformat(),
            "dismissals": {
                "confirmed": int(reviewed.dismissal.eq("confirmed").sum()),
                "unknown": int(reviewed.dismissal.eq("unknown").sum()),
            },
            "events": {f"{w}/{p}": int(f.event.sum()) for (w, p), f in panels.items()},
            "leakage_checks": {
                "source_available_before_month": True,
                "complaint_received_order_and_buffer": True,
                "future_ID_validity_and_merger_censoring": "M2/M3 dated links retained",
                "train_only_transforms": True,
                "time_ordered_inner_folds": True,
                "protected_label_hashes_unchanged": True,
                "no_outcomes_after_2025_08": True,
                "historical_mapping_and_response_versions": "unverified; retrospective-source limitations disclosed",
            },
            "event_chart": chart,
            "scope": "Reviewed aliases only; all M2 mapped complaint links are manual",
        }
        write_json(output / "backtest_audit.json", audit)
        write_json(output / "model_diagnostics.json", diagnostics)
        report = generate(
            output,
            date.today().isoformat(),
            result_frame.to_dict("records"),
            comparisons,
            diagnostics,
            audit,
            chart,
            errors,
            bins,
        )
        # Dashboard-readable marts; report remains a standalone archive of its measurements.
        for frame, name in [
            (prediction_frame, "score_snapshot"),
            (result_frame, "backtest_results"),
            (live, "live_anomaly"),
        ]:
            import duckdb

            with duckdb.connect() as con:
                con.register("output", frame)
                con.sql("SELECT * FROM output").write_parquet(
                    str(data_dir / "marts" / f"{name}.parquet")
                )
        for path in output.iterdir():
            if path.is_dir():
                target = reports / path.name
                target.mkdir(exist_ok=True)
                for artifact in path.iterdir():
                    artifact.replace(target / artifact.name)
            else:
                path.replace(reports / path.name)
        return {
            "report": str(reports / report.name),
            "metrics_rows": len(results),
            "predictions": len(predictions),
            "matched_pairs": chart["pairs"],
            "live_companies": len(live),
            "event_counts": audit["events"],
        }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=Path("data"))
    parser.add_argument("--reports-dir", type=Path, default=Path("reports"))
    parser.add_argument("--bootstrap-draws", type=int, default=400)
    parser.add_argument("--seed", type=int, default=20260926)
    parser.add_argument("--reuse-grid", action="store_true")
    args = parser.parse_args()
    print(
        json.dumps(
            run(
                args.data_dir,
                args.reports_dir,
                args.bootstrap_draws,
                args.seed,
                not args.reuse_grid,
            ),
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
