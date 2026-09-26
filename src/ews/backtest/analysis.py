"""Descriptive matched-peer event chart and evidence-based error categories."""

import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd


def event_chart(grid, panel, entities, output, draws=400, seed=20260926):
    output = Path(output)
    events = panel[panel.event.eq(1)][["entity_id", "event_date"]].drop_duplicates()
    any_event = set(events.entity_id) | set(
        panel.loc[panel.prior_action.eq(1), "entity_id"]
    )
    names = entities.set_index("entity_id").display_name.to_dict()
    grid_index = grid.set_index(["entity_id", "month"])
    pairs, series, excluded = [], [], []
    for event in events.itertuples():
        event_month = event.event_date.to_period("M").to_timestamp()
        baseline = event_month - pd.DateOffset(months=48)
        key = event.entity_id, baseline
        if key not in grid_index.index or baseline < pd.Timestamp("2013-02-01"):
            excluded.append(
                {
                    "entity_id": event.entity_id,
                    "reason": "No complete complaint baseline 48 months before filing",
                }
            )
            continue
        row = grid_index.loc[key]
        if row.c_12m <= 0:
            excluded.append(
                {
                    "entity_id": event.entity_id,
                    "reason": "Zero complaint baseline at -48 months",
                }
            )
            continue
        candidates = grid[
            (grid.month.eq(baseline))
            & grid.peer_group.eq(row.peer_group)
            & ~grid.entity_id.isin(any_event)
            & grid.c_12m.gt(0)
        ].copy()
        if candidates.empty:
            excluded.append(
                {
                    "entity_id": event.entity_id,
                    "reason": "No observed never-filed peer with positive baseline",
                }
            )
            continue
        candidates["distance"] = abs(np.log1p(candidates.c_12m) - np.log1p(row.c_12m))
        if pd.notna(row.assets_lag):
            known = candidates.assets_lag.notna()
            candidates.loc[known, "distance"] += abs(
                np.log1p(candidates.loc[known, "assets_lag"]) - np.log1p(row.assets_lag)
            )
            candidates.loc[~known, "distance"] += 10
        peer = candidates.sort_values(["distance", "entity_id"]).iloc[0]
        pairs.append(
            {
                "entity_id": event.entity_id,
                "display_name": names.get(event.entity_id, event.entity_id),
                "peer_entity_id": peer.entity_id,
                "peer_name": names.get(peer.entity_id, peer.entity_id),
                "event_date": event.event_date.isoformat(),
                "baseline_month": baseline.isoformat(),
                "matching_distance": float(peer.distance),
                "size_available": bool(pd.notna(row.assets_lag)),
            }
        )
        for offset in range(-48, 13):
            month = event_month + pd.DateOffset(months=offset)
            left, right = (event.entity_id, month), (peer.entity_id, month)
            if left not in grid_index.index or right not in grid_index.index:
                continue
            case = (grid_index.loc[left].c_12m + 1) / (row.c_12m + 1)
            control = (grid_index.loc[right].c_12m + 1) / (peer.c_12m + 1)
            series.append(
                {
                    "entity_id": event.entity_id,
                    "relative_month": offset,
                    "case": float(case),
                    "peer": float(control),
                }
            )
    pairs_frame, series_frame = pd.DataFrame(pairs), pd.DataFrame(series)
    pairs_frame.to_csv(output / "event_matched_pairs.csv", index=False)
    series_frame.to_csv(output / "event_aligned_series.csv", index=False)
    fig, ax = plt.subplots(figsize=(10, 5.5), layout="constrained")
    if not series_frame.empty:
        ids = pairs_frame.entity_id.to_list()
        random = np.random.default_rng(seed)
        boot = random.integers(0, len(ids), size=(draws, len(ids)))
        for column, label, color in [
            ("case", "Enforced companies", "#125DA8"),
            ("peer", "Matched peers", "#B75B23"),
        ]:
            matrix = series_frame.pivot(
                index="entity_id", columns="relative_month", values=column
            ).reindex(ids)
            array = matrix.to_numpy()
            valid = np.isfinite(array[boot]).sum(axis=1)
            replicate = np.divide(
                np.nansum(array[boot], axis=1),
                valid,
                out=np.full((draws, array.shape[1]), np.nan),
                where=valid > 0,
            )
            ax.plot(
                matrix.columns,
                np.nanmean(array, axis=0),
                label=label,
                color=color,
                lw=2,
            )
            ax.fill_between(
                matrix.columns,
                np.nanquantile(replicate, 0.025, axis=0),
                np.nanquantile(replicate, 0.975, axis=0),
                color=color,
                alpha=0.15,
            )
        ax.axvline(0, color="#555555", ls="--", lw=1)
        ax.axhline(1, color="#999999", ls=":", lw=1)
        ax.legend(frameon=False)
    else:
        ax.text(
            0.5,
            0.5,
            "No eligible matched baseline pairs",
            ha="center",
            transform=ax.transAxes,
        )
    ax.set(
        xlabel="Months relative to first qualifying filing",
        ylabel="Trailing 12m complaints / own -48m baseline (add one)",
        title=f"Complaint trajectories: {len(pairs)} matched company pairs",
    )
    ax.spines[["top", "right"]].set_visible(False)
    fig.savefig(output / "event_aligned.png", dpi=180)
    fig.savefig(output / "event_aligned.svg")
    plt.close(fig)
    return {
        "pairs": len(pairs),
        "excluded": excluded,
        "matching": "same peer group and -48m log complaint count; size only if available",
        "interpretation": "Descriptive self-normalized complaints, not exposure-normalized rates. +12m data are never model inputs; no post-Aug-2025 accuracy claim.",
    }


def error_review(predictions, grid, entities, output):
    names = entities.set_index("entity_id").display_name.to_dict()
    reviews = []
    selected = predictions[
        (predictions.window.eq("primary"))
        & predictions.policy.eq("include")
        & predictions.horizon.eq(12)
    ]
    source = grid.set_index(["entity_id", "month"])
    for key, rows in selected.groupby(["cutoff", "model"], sort=True):
        rows = rows.sort_values(
            ["score", "entity_id"], ascending=[False, True]
        ).reset_index(drop=True)
        rows["rank"] = np.arange(1, len(rows) + 1)
        errors = rows[
            (rows["rank"].le(20) & rows.outcome.eq(0))
            | (rows["rank"].gt(20) & rows.outcome.eq(1))
        ]
        for row in errors.itertuples():
            feature = source.loc[(row.entity_id, pd.Timestamp(row.cutoff))]
            false_positive = row.rank <= 20
            baseline_only = row.model in ["B", "C"] and not json.loads(row.drivers)
            if baseline_only:
                category = "Baseline-only hazard; no fitted complaint predictor"
            elif false_positive:
                if feature.c_12m < 12:
                    category = "Sparse complaint history or rank tie"
                elif (
                    pd.notna(feature.c_selfz_12m) and feature.c_selfz_12m >= 2
                ) or feature.c_growth_6v6 > 0.5:
                    category = "Complaint surge without a filing in the horizon"
                elif feature.c_12m >= 100:
                    category = "Persistent high complaint volume"
                else:
                    category = "Elevated structured signal without a filing"
            elif feature.c_12m < 12:
                category = "Sparse complaint signal before filing"
            elif (
                pd.isna(feature.c_selfz_12m) or feature.c_selfz_12m < 1
            ) and feature.c_growth_6v6 <= 0.2:
                category = "No strong contemporaneous complaint anomaly"
            else:
                category = "Signal present but ranked below top 20"
            reviews.append(
                {
                    "cutoff": row.cutoff,
                    "model": row.model,
                    "entity_id": row.entity_id,
                    "display_name": names.get(row.entity_id, row.entity_id),
                    "kind": "false_positive" if false_positive else "miss",
                    "rank": int(row.rank),
                    "score": float(row.score),
                    "category": category,
                    "c_12m": float(feature.c_12m),
                    "self_z": (
                        None
                        if pd.isna(feature.c_selfz_12m)
                        else float(feature.c_selfz_12m)
                    ),
                    "growth_6v6": float(feature.c_growth_6v6),
                    "event_date": (
                        str(row.event_date) if pd.notna(row.event_date) else ""
                    ),
                    "interpretation": "Feature-based description; absence of a filing is not evidence of compliant or unlawful conduct.",
                }
            )
    pd.DataFrame(reviews).to_csv(Path(output) / "error_review.csv", index=False)
    counts = (
        pd.DataFrame(reviews).groupby(["model", "kind", "category"]).size()
        if reviews
        else pd.Series(dtype=int)
    )
    return [
        {"model": m, "kind": k, "category": c, "rows": int(n)}
        for (m, k, c), n in counts.items()
    ]


def calibration(predictions, output, draws=400, seed=20260926):
    records = []
    random = np.random.default_rng(seed)
    for key, rows in predictions[predictions.model.isin(["B", "C"])].groupby(
        ["window", "policy", "horizon", "model"], sort=True
    ):
        # Fixed probability ranges avoid choosing bins after viewing outcomes.
        cuts = [0.0, 0.01, 0.03, 0.1, 1.0000001]
        bins = pd.cut(rows.score, cuts, right=False, labels=False)
        ids = sorted(rows.entity_id.unique())
        weights = random.multinomial(
            len(ids), np.repeat(1 / len(ids), len(ids)), size=draws
        )
        positions = {e: i for i, e in enumerate(ids)}
        for number in range(4):
            subset = rows[bins.eq(number)]
            if subset.empty:
                continue
            indices = [positions[e] for e in subset.entity_id]
            w = weights[:, indices]
            total = w.sum(axis=1)
            observed = np.divide(
                w @ subset.outcome.to_numpy(),
                total,
                out=np.full(draws, np.nan),
                where=total > 0,
            )
            valid = observed[np.isfinite(observed)]
            records.append(
                dict(
                    zip(["window", "policy", "horizon", "model"], key),
                    bin=number,
                    n=len(subset),
                    predicted=float(subset.score.mean()),
                    observed=float(subset.outcome.mean()),
                    low=float(np.quantile(valid, 0.025)) if len(valid) else None,
                    high=float(np.quantile(valid, 0.975)) if len(valid) else None,
                )
            )
    pd.DataFrame(records).to_csv(Path(output) / "calibration.csv", index=False)
    return records


def write_json(path, value):
    Path(path).write_text(json.dumps(value, indent=2, allow_nan=False) + "\n")
