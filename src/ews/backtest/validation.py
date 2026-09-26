"""Expanding temporal validation inside each outer training window."""

import numpy as np
import pandas as pd

from ews.backtest.data import evaluation_rows, previous_rows, training_rows
from ews.models.hazard import CoxHazard, LogisticHazard, feature_budget


def tune(panel, grid, cutoff, horizon, kind):
    outer_end = (
        pd.Timestamp(cutoff) - pd.DateOffset(months=horizon) + pd.DateOffset(months=1)
    )
    candidates = ["anomaly", "log_count"]
    penalties = [0.1, 1.0, 10.0] if kind == "B" else [0.001, 0.01, 0.1]
    fitter = LogisticHazard if kind == "B" else CoxHazard
    folds, losses = [], {}
    for gap in [12, 0]:
        validation_cutoff = outer_end - pd.DateOffset(months=horizon + gap)
        if validation_cutoff < pd.Timestamp("2016-01-01"):
            continue
        train = training_rows(panel, validation_cutoff, horizon, kind)
        events = int(train.next_event.sum()) if kind == "B" else int(train.event.sum())
        budget = feature_budget(events)
        scoring = evaluation_rows(panel, validation_cutoff, horizon, outer_end)
        folds.append(
            {
                "cutoff": validation_cutoff.isoformat(),
                "max_training_month": (
                    train.month.max().isoformat() if len(train) else None
                ),
                "validation_end": (
                    validation_cutoff + pd.DateOffset(months=horizon)
                ).isoformat(),
                "events": events,
                "validation_events": int(scoring.outcome.sum()),
                "budget": budget,
            }
        )
        if budget < 2 or len(scoring) < 10 or scoring.outcome.sum() == 0:
            continue
        for feature in candidates:
            for penalty in penalties:
                try:
                    model = fitter().fit(train, feature, penalty, True)
                    predicted = model.predict(
                        scoring,
                        horizon,
                        previous_rows(grid, scoring) if kind == "B" else None,
                    )
                    if np.isfinite(predicted).all():
                        losses.setdefault((feature, penalty), []).append(
                            float(
                                np.mean((predicted - scoring.outcome.to_numpy()) ** 2)
                            )
                        )
                except (ValueError, np.linalg.LinAlgError) as exc:
                    folds[-1].setdefault("fit_errors", []).append(str(exc))
    if losses:
        choice = min(
            losses,
            key=lambda k: (
                np.mean(losses[k]),
                candidates.index(k[0]),
                penalties.index(k[1]),
            ),
        )
        status = "time-ordered validation"
    else:
        choice = "anomaly", penalties[1]
        status = "insufficient covariate-capable inner folds; predeclared defaults"
    return choice, {
        "status": status,
        "folds": folds,
        "losses": [
            {
                "predictor": k[0],
                "penalty": k[1],
                "mean_brier": float(np.mean(v)),
                "folds": len(v),
            }
            for k, v in losses.items()
        ],
    }
