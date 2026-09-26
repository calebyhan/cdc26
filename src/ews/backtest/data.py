"""Reconstruct risk sets for each outcome policy without censoring at dropped filings."""

import hashlib
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

from ews.features.panel import NUMERIC_FEATURES, build

PRIMARY_END = pd.Timestamp("2024-12-31")
SECONDARY_END = pd.Timestamp("2025-08-31")


def fingerprint(path):
    with Path(path).open("rb") as f:
        return hashlib.file_digest(f, "sha256").hexdigest()


def read_frame(path):
    with duckdb.connect() as con:
        return con.read_parquet(str(path)).df()


def load_grid(data_dir, rebuild=True):
    data_dir = Path(data_dir)
    if not (data_dir / "marts/company_month.parquet").exists():
        raise FileNotFoundError("M3 company_month panel must exist before M4")
    path = data_dir / "marts/company_month_features.parquet"
    if rebuild or not path.exists():
        build(
            data_dir,
            start=pd.Timestamp("2012-01-01").date(),
            reference=data_dir / "reference",
            truncate_at_event=False,
            output_name="company_month_features",
        )
    grid = read_frame(path)
    # Outcome and contemporaneous peer-z fields are deliberately not modeling inputs.
    keep = [
        "entity_id",
        "month",
        "type",
        "peer_group",
        "entry_date",
        "censor_date",
        "interval_start",
        "interval_stop",
        "start",
        "stop",
        "prior_action",
        "fdic_report_date",
        "fdic_available_from",
        "hmda_available_from",
        "complaints_received_before",
        *NUMERIC_FEATURES,
    ]
    grid = grid[keep].sort_values(["entity_id", "month"]).reset_index(drop=True)
    validate_grid(grid)
    return grid


def validate_grid(grid):
    if grid.duplicated(["entity_id", "month"]).any():
        raise ValueError("Duplicate entity-month keys")
    for source in ["fdic", "hmda"]:
        known = grid[f"{source}_available_from"].notna()
        if (
            grid.loc[known, f"{source}_available_from"] >= grid.loc[known, "month"]
        ).any():
            raise ValueError("Future source availability in model features")
    if (grid.complaints_received_before >= grid.month).any():
        raise ValueError("Complaint buffer must precede scoring month")
    if (grid.loc[grid.type.ne("bank"), "c_per_bn_assets"].notna()).any():
        raise ValueError("Bank exposure on a nonbank")


def load_actions(data_dir):
    data_dir = Path(data_dir)
    events = read_frame(data_dir / "staging/enforcement_events.parquet")
    links = read_frame(data_dir / "marts/enforcement_entity.parquet")
    reviews = pd.read_csv(
        data_dir / "reference/enforcement_dismissals.csv", dtype=str
    ).fillna("")
    expected = set(events.loc[events.mortgage_related, "action_id"])
    if set(reviews.action_id) != expected or reviews.action_id.duplicated().any():
        raise ValueError(
            "Dismissal reviews must cover each mortgage action exactly once"
        )
    if not reviews.dismissal.isin(["confirmed", "not_documented", "unknown"]).all():
        raise ValueError("Invalid dismissal review decision")
    compared = events[events.mortgage_related].merge(
        reviews, on="action_id", validate="one_to_one"
    )
    if (compared.raw_sha256 != compared.source_sha256).any():
        raise ValueError("Dismissal evidence changed; re-review before backtesting")
    joined = links.merge(
        compared[["action_id", "dismissal", "status", "url"]],
        on="action_id",
        validate="many_to_one",
    )
    return joined, compared


def risk_panel(grid, actions, end, policy="include"):
    end = pd.Timestamp(end)
    if end > SECONDARY_END:
        raise ValueError("No evaluated outcomes past 2025-08")
    qualifying = (
        actions if policy == "include" else actions[actions.dismissal.ne("confirmed")]
    )
    # Original entry, ID periods, and source features stay fixed between sensitivities.
    f = grid[(grid.month <= end) & (grid.month >= pd.Timestamp("2014-01-01"))].copy()
    f["entry_date"] = f.entry_date.clip(lower=pd.Timestamp("2014-01-01"))
    f["interval_start"] = f[["interval_start", "entry_date"]].max(axis=1)
    f["start"] = (f.interval_start - f.entry_date).dt.days
    f["censor_stop"] = f.censor_date.clip(upper=end) + pd.Timedelta(days=1)
    starts = f[["entity_id", "entry_date"]].drop_duplicates()
    a = qualifying.merge(starts, on="entity_id", validate="many_to_one")
    a = a[(a.date_filed >= a.entry_date) & (a.date_filed <= end)]
    first = a.groupby("entity_id", sort=True).date_filed.min()
    f["event_date"] = f.entity_id.map(first)
    f.loc[f.event_date >= f.censor_stop, "event_date"] = pd.NaT
    f = f[f.event_date.isna() | (f.month <= f.event_date)].copy()
    f["interval_stop"] = f[["interval_stop", "censor_stop"]].min(axis=1)
    f.loc[f.event_date.notna(), "interval_stop"] = f.loc[
        f.event_date.notna(), ["interval_stop", "event_date"]
    ].apply(lambda r: min(r.interval_stop, r.event_date + pd.Timedelta(days=1)), axis=1)
    f["stop"] = (f.interval_stop - f.entry_date).dt.days
    f["event"] = (
        f.event_date.notna()
        & (f.event_date >= f.interval_start)
        & (f.event_date < f.interval_stop)
    ).astype(int)
    f = f[f.stop > f.start].copy()
    prior = qualifying.merge(starts, on="entity_id", validate="many_to_one")
    priors = set(prior.loc[prior.date_filed < prior.entry_date, "entity_id"])
    f["prior_action"] = f.entity_id.isin(priors).astype(int)
    next_start = f.month + pd.DateOffset(months=1)
    next_end = f.month + pd.DateOffset(months=2)
    event_month = f.event_date.dt.to_period("M").dt.to_timestamp()
    f["next_event"] = np.where(
        event_month.eq(next_start),
        1.0,
        np.where(next_end <= f.censor_stop, 0.0, np.nan),
    )
    # Next-month prediction is conditional on being at risk at its start.
    f.loc[f.event_date.notna() & (f.event_date < next_start), "next_event"] = np.nan
    f.loc[next_start >= f.censor_stop, "next_event"] = np.nan
    return f.reset_index(drop=True)


def training_rows(panel, cutoff, horizon, kind):
    cutoff = pd.Timestamp(cutoff)
    maximum = cutoff - pd.DateOffset(months=horizon)
    stop = maximum + pd.DateOffset(months=1)
    f = panel[panel.month <= maximum].copy()
    if kind == "B":
        # Following calendar month must finish before the outer cutoff.
        known = (f.month + pd.DateOffset(months=2) <= cutoff) & f.next_event.notna()
        f = f[known].copy()
    else:
        f["interval_stop"] = f.interval_stop.clip(upper=stop)
        f["stop"] = (f.interval_stop - f.entry_date).dt.days
        f["event"] = (
            f.event_date.notna()
            & (f.event_date < f.interval_stop)
            & (f.event_date >= f.interval_start)
        ).astype(int)
        f = f[f.stop > f.start].copy()
    return f.reset_index(drop=True)


def evaluation_rows(panel, cutoff, horizon, end):
    cutoff = pd.Timestamp(cutoff)
    boundary = cutoff + pd.DateOffset(months=horizon)
    if boundary > pd.Timestamp(end) or pd.Timestamp(end) > SECONDARY_END:
        raise ValueError("Incomplete or forbidden evaluation horizon")
    f = panel[panel.month.eq(cutoff)].copy()
    f = f[f.event_date.isna() | (f.event_date > cutoff)].copy()
    hit = f.event_date.notna() & (f.event_date > cutoff) & (f.event_date <= boundary)
    observed = (f.censor_stop > boundary) | hit
    f = f[observed].copy()
    f["outcome"] = hit.loc[f.index].astype(int)
    f["lead_months"] = (f.event_date - cutoff).dt.days / 30.4375
    f["duration"] = (
        f.event_date.fillna(boundary).clip(upper=boundary) - cutoff
    ).dt.days
    f["observed_event"] = f.outcome
    return f.reset_index(drop=True)


def previous_rows(grid, scoring):
    previous_month = scoring.month.iloc[0] - pd.DateOffset(months=1)
    prior = grid[grid.month.eq(previous_month)].set_index("entity_id")
    result = scoring.copy()
    for i, row in scoring.iterrows():
        if row.entity_id in prior.index:
            for column in NUMERIC_FEATURES:
                result.at[i, column] = prior.at[row.entity_id, column]
        else:
            # Newly entered firm has no earlier complaint history. This is an
            # explicit missing snapshot, not substitution of current/future data.
            result.loc[i, NUMERIC_FEATURES] = np.nan
            result.at[i, "c_12m"] = 0.0
    return result
