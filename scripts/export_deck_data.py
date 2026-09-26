"""Export the numbers the presentation deck draws into presentation/deck-data.json.

Reads the complaint and enforcement staging files, the dashboard bundle, and the
M4 backtest reports. Every chart in the deck is drawn from this file, so a
re-run after the backtest changes keeps slides and reports in step. Fails loudly
when an input no longer has the shape the deck assumes.

    PYTHONPATH=src .venv/bin/python scripts/export_deck_data.py
    .venv/bin/python presentation/build_deck.py
"""

from __future__ import annotations

import json
from pathlib import Path

import duckdb
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
BUNDLE = ROOT / "data/dashboard"
OUT = ROOT / "presentation/deck-data.json"
# The backtest slice the deck reports: primary window, all filings, 12 months.
SLICE = {"window": "primary", "policy": "include", "horizon": 12}
RERANK_CUTOFF = "2017-01-01"
PLANET = "E2C144F51D5CE"
OCWEN = "E58809E9BF1B6"
DHI = "EE034DEE8CD18"


def require(condition, message):
    if not condition:
        raise SystemExit(f"export_deck_data: {message}")


def monthly_complaints():
    rows = (
        duckdb.sql(
            """
            SELECT strftime(date_trunc('month', date_received), '%Y-%m') AS month,
                   count(*) AS n
            FROM read_parquet(?)
            WHERE product = 'Mortgage'
            GROUP BY 1 ORDER BY 1
            """,
            params=[str(ROOT / "data/staging/complaints_all.parquet")],
        )
        .df()
        .values.tolist()
    )
    total = sum(n for _, n in rows)
    require(total > 400_000, f"only {total} mortgage complaints in staging")
    # The newest month is partial at export time; the chart would show a false drop.
    return [[m, int(n)] for m, n in rows[:-1]], int(total), rows[-1][0]


def filings():
    events = pd.read_parquet(ROOT / "data/staging/enforcement_events.parquet")
    require(len(events) >= 386, f"{len(events)} enforcement events")
    dates = pd.to_datetime(events.date_filed)
    is_mortgage = events.mortgage_related.astype(bool)
    return {
        "all": int(len(events)),
        "mortgage": sorted(dates[is_mortgage].dt.strftime("%Y-%m-%d")),
        "other": sorted(dates[~is_mortgage].dt.strftime("%Y-%m-%d")),
        "first": dates.min().strftime("%Y-%m-%d"),
        "last": dates.max().strftime("%Y-%m-%d"),
    }


def snapshot_slice():
    s = pd.read_csv(ROOT / "reports/score_snapshots.csv.gz")
    for key, value in SLICE.items():
        s = s[s[key] == value]
    require(len(s), "no score snapshots for the deck slice")
    return s


def names():
    return (
        pd.read_parquet(BUNDLE / "entities.parquet").set_index("entity_id").display_name
    )


def backtest_design(s, name):
    a = s[s.model == "A"]
    rows = []
    for cutoff, g in a.groupby("cutoff"):
        hits = g[g.outcome == 1]
        rows.append(
            {
                "cutoff": cutoff,
                "eligible": int(len(g)),
                "events": [
                    {"name": name[e], "date": str(d)[:10]}
                    for e, d in zip(hits.entity_id, hits.event_date)
                ],
            }
        )
    require(len(rows) == 8, f"expected 8 cutoffs, found {len(rows)}")
    return rows


def rerank(s, name):
    g = s[s.cutoff == RERANK_CUTOFF]
    a = g[g.model == "A"].set_index("entity_id")
    raw = g[g.model == "raw_count"].set_index("entity_id")
    require(set(a.index) == set(raw.index), "A and raw_count cohorts differ")
    require(a["rank"].notna().all() and raw["rank"].notna().all(), "missing ranks")
    return {
        "cutoff": RERANK_CUTOFF,
        "rows": [
            {
                "name": name[e],
                "a": int(a.at[e, "rank"]),
                "raw": int(raw.at[e, "rank"]),
                "c12": int(a.at[e, "c_12m"]),
                "enforced": int(a.at[e, "outcome"]),
            }
            for e in sorted(a.index)
        ],
    }


def overlap(s):
    top = s[s["rank"] <= 20]
    rows = []
    for cutoff, g in top.groupby("cutoff"):
        a = set(g[g.model == "A"].entity_id)
        raw = set(g[g.model == "raw_count"].entity_id)
        rows.append({"cutoff": cutoff, "shared": len(a & raw)})
    return rows


def planet(s):
    trend = pd.read_parquet(BUNDLE / "company_trend.parquet")
    trend = trend[trend.entity_id.eq(PLANET)].sort_values("month")
    trend = trend[trend.month < "2018-07-01"]
    require(len(trend) > 24, "Planet Home trend too short")
    flags = []
    for cutoff in ["2016-01-01", "2017-01-01"]:
        g = s[(s.cutoff == cutoff) & (s.entity_id == PLANET)].set_index("model")
        require({"A", "raw_count"} <= set(g.index), f"Planet Home missing at {cutoff}")
        flags.append(
            {
                "cutoff": cutoff,
                "a": int(g.at["A", "rank"]),
                "raw": int(g.at["raw_count", "rank"]),
                "eligible": int((s[(s.cutoff == cutoff) & (s.model == "A")]).shape[0]),
            }
        )
    events = pd.read_parquet(BUNDLE / "events.parquet")
    filed = events[events.entity_id.eq(PLANET)].date_filed.min()
    return {
        "months": [m.strftime("%Y-%m") for m in pd.to_datetime(trend.month)],
        "complaints": [int(v) for v in trend.complaints],
        "flags": flags,
        "filed": pd.Timestamp(filed).strftime("%Y-%m-%d"),
    }


def pooled():
    m = pd.read_parquet(BUNDLE / "metrics.parquet")
    for key, value in SLICE.items():
        m = m[m[key] == value]
    m = m[m.cutoff.eq("pooled")].set_index("model")
    out = {}
    for model in ["raw_count", "A", "B", "C", "random"]:
        r = m.loc[model]
        out[model] = {
            k: float(r[k])
            for k in [
                "recall_20",
                "recall_20_low",
                "recall_20_high",
                "precision_20",
                "pr_auc",
            ]
        } | {"cutoffs": int(r.n_cutoffs)}
    deltas = pd.read_csv(ROOT / "reports/baseline_comparisons.csv")
    deltas = deltas[
        deltas.baseline.eq("raw_count")
        & deltas.window.eq(SLICE["window"])
        & deltas.policy.eq(SLICE["policy"])
        & deltas.horizon.eq(SLICE["horizon"])
    ].set_index("model")
    for model in ["A", "B", "C"]:
        d = deltas.loc[model]
        out[model]["delta_pr_auc"] = [
            float(d.pr_auc_difference),
            float(d.low),
            float(d.high),
        ]
    return out


def event_aligned():
    a = pd.read_parquet(BUNDLE / "event_aggregate.parquet").sort_values(
        "relative_month"
    )
    series = {
        group: rows[["relative_month", "value", "low", "high"]].values.round(3).tolist()
        for group, rows in a.groupby("series")
    }
    require(set(series) == {"case", "peer"}, "event aggregate series changed")
    manifest = json.loads((BUNDLE / "manifest.json").read_text())
    return {"series": series, "pairs": int(manifest["event_chart"]["pairs"])}


def main():
    s = snapshot_slice()
    name = names()
    monthly, total, partial = monthly_complaints()
    aliases = pd.read_parquet(BUNDLE / "aliases.parquet")
    aliases = aliases[aliases.entity_id.eq(OCWEN)].drop_duplicates(
        ["raw_string", "source"]
    )
    dhi = s[(s.model == "A") & (s.entity_id == DHI) & (s.cutoff == "2016-01-01")].iloc[
        0
    ]
    data = {
        "slice": SLICE,
        "complaints": {
            "total": total,
            "monthly": monthly,
            "partial_month_dropped": partial,
        },
        "filings": filings(),
        "ocwen_aliases": aliases[["raw_string", "source"]].values.tolist(),
        "ocwen_unlinked": sorted(
            n for n in name if n.startswith("Ocwen") and n != name[OCWEN]
        ),
        "design": backtest_design(s, name),
        "planet": planet(s),
        "rerank": rerank(s, name),
        "overlap": overlap(s),
        "pooled": pooled(),
        "event": event_aligned(),
        "dhi": {
            "rank": int(dhi["rank"]),
            "c12": int(dhi.c_12m),
            "cutoff": "2016-01-01",
        },
    }
    OUT.write_text(json.dumps(data, separators=(",", ":")) + "\n")
    print(f"wrote {OUT} ({OUT.stat().st_size // 1024} KiB)")


if __name__ == "__main__":
    main()
