"""Publish chart-ready dashboard marts after validating the M4 prerequisite."""

import argparse
import hashlib
import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

from ews.models.anomaly import AnomalyModel, PeerTransform
from ews.models.hazard import CoxHazard, LogisticHazard, Predictors


def restore_transform(artifact):
    transform = PeerTransform()
    transform.features = artifact["features"]
    transform.stats = artifact["peer_statistics"]
    return transform


def restore_hazard(artifact):
    transform = Predictors()
    transform.anomaly = AnomalyModel()
    transform.anomaly.transformer = restore_transform(
        artifact["transform"]["anomaly"]["transform"]
    )
    transform.count_transform = restore_transform(artifact["transform"]["log_count"])
    transform.explanation_medians = artifact["transform"]["explanation_peer_medians"]
    if artifact["model"] == "B":
        model = LogisticHazard()
        coefficients = artifact["coefficients"]
        model.beta = np.array(
            [coefficients["baseline"]]
            + ([coefficients[artifact["predictor"]]] if artifact["predictor"] else [])
        )
    else:
        model = CoxHazard()
        model.beta = artifact["coefficient"]
        model.stratified = artifact["stratified"]
        if model.stratified:
            if "split" not in artifact:
                raise ValueError("Stratified artifact lacks fitted split")
            model.split = artifact["split"]
        model.baselines = {int(k): v for k, v in artifact["baseline"].items()}
    model.predictor = artifact["predictor"]
    model.transform = transform
    return model


def build(
    data_dir=Path("data"), reports=Path("reports"), output=None, meta=None, refresh=None
):
    data_dir, reports = Path(data_dir), Path(reports)
    output = Path(output or data_dir / "dashboard")
    required = [reports / "backtest_audit.json", reports / "models/live_A.json"]
    required += [
        data_dir / "marts" / f"{n}.parquet"
        for n in [
            "score_snapshot",
            "backtest_results",
            "live_anomaly",
            "company_month_features",
        ]
    ]
    for path in required:
        if not path.exists():
            raise FileNotFoundError(f"M4 prerequisite missing: {path}")
    for model in ["B", "C"]:
        if not list((reports / "models").glob(f"primary_include_*_{model}.json")):
            raise FileNotFoundError(f"M4 Model {model} artifacts missing")
    output.parent.mkdir(parents=True, exist_ok=True)
    with (
        tempfile.TemporaryDirectory(dir=output.parent, prefix=".dashboard-") as tmp,
        duckdb.connect(config={"threads": 2}) as con,
    ):
        target = Path(tmp)

        def load(name, path):
            con.read_parquet(str(path)).create_view(name)

        def write(name, frame):
            con.register("frame", frame)
            con.sql("SELECT * FROM frame").write_parquet(
                str(target / f"{name}.parquet"), compression="zstd"
            )
            con.unregister("frame")

        def query(name, sql):
            write(name, con.sql(sql).df())

        for name, relative in {
            "grid": "marts/company_month_features",
            "live": "marts/live_anomaly",
            "entity": "marts/entity",
            "input": "marts/complaint_features_input",
            "scores": "marts/score_snapshot",
            "results": "marts/backtest_results",
            "links": "marts/enforcement_entity",
            "actions": "staging/stg_enforcement",
            "alias": "marts/alias",
            "history": "staging/stg_fdic_history",
        }.items():
            load(name, data_dir / f"{relative}.parquet")
        # The chart timeline includes post-filing months, unlike the censored M3 panel.
        query(
            "company_trend",
            """
            WITH monthly AS (SELECT entity_id, received_month AS month, count(*) complaints
                FROM input WHERE entity_id IS NOT NULL GROUP BY 1,2),
            peers AS (SELECT e.peer_group,g.month,
                quantile_cont(coalesce(m.complaints,0),.5) peer_median,
                quantile_cont(coalesce(m.complaints,0),.25) peer_low,
                quantile_cont(coalesce(m.complaints,0),.75) peer_high
                FROM grid g JOIN entity e USING(entity_id)
                LEFT JOIN monthly m USING(entity_id,month) GROUP BY 1,2)
            SELECT g.entity_id,g.month,coalesce(m.complaints,0) complaints,p.peer_median,
                p.peer_low,p.peer_high,g.c_12m,g.c_per_bn_assets,g.c_per_1k_orig,
                g.untimely_rate_12m,g.relief_share_12m,g.c_selfz_12m,g.c_growth_6v6,
                (g.c_selfz_12m>=2 AND g.c_growth_6v6>.5) change_point,
                g.assets_lag,g.deposits_lag,g.equity_to_assets_lag,g.noncurrent_ratio_lag,
                g.provision_ratio_lag,g.fdic_report_date,g.fdic_available_from,g.hmda_available_from,
                g.hmda_year,g.hmda_denial_rate_lag,g.hmda_originations_lag
            FROM grid g LEFT JOIN monthly m USING(entity_id,month)
                JOIN peers p ON p.peer_group=g.peer_group AND p.month=g.month
            ORDER BY g.entity_id,g.month
        """,
        )
        query(
            "issue_mix",
            """SELECT entity_id,received_month AS month,issue_std,severity_tier,count(*) complaints
            FROM input WHERE entity_id IS NOT NULL GROUP BY 1,2,3,4 ORDER BY 1,2,4""",
        )
        # State means complaint geography, not headquarters or licensing status.
        query(
            "states",
            """SELECT entity_id,state,count(*) complaints FROM input
            WHERE entity_id IS NOT NULL AND length(state)=2
            AND date_received>=(SELECT max(complaints_received_before) FROM live)-INTERVAL 12 MONTH
            AND date_received<(SELECT max(complaints_received_before) FROM live)
            GROUP BY 1,2""",
        )
        query(
            "events",
            """SELECT DISTINCT l.entity_id,l.action_id,l.date_filed,a.name,a.url,a.status,a.forum
            FROM links l JOIN actions a USING(action_id) WHERE l.entity_id IS NOT NULL""",
        )
        query(
            "entities",
            "SELECT entity_id,display_name,type,peer_group,valid_from,valid_to,successor_entity_id,rssdhcr,leis FROM entity",
        )
        query(
            "aliases",
            "SELECT entity_id,raw_string,source,valid_from,valid_to FROM alias WHERE decision='accept'",
        )
        query(
            "bank_history",
            """SELECT DISTINCT e.entity_id,h.INSTNAME,h.FRM_INSTNAME,h.EFFDATE,h.CHANGECODE_DESC
            FROM entity e JOIN history h ON list_contains(e.fdic_certs,h.CERT)
            OR list_contains(e.fdic_certs,try_cast(h.SUR_CERT AS INTEGER))""",
        )
        query(
            "event_company",
            """SELECT DISTINCT l.entity_id,l.action_id,l.date_filed,t.month,
                date_diff('month',date_trunc('month',l.date_filed),t.month) relative_month,
                t.complaints,t.peer_median,t.peer_low,t.peer_high
                FROM links l JOIN read_parquet({event_trend}) t USING(entity_id)
                WHERE date_diff('month',date_trunc('month',l.date_filed),t.month) BETWEEN -48 AND 12
                ORDER BY l.entity_id,l.action_id,t.month""".replace(
                "{event_trend}",
                "'" + str(target / "company_trend.parquet").replace("'", "''") + "'",
            ),
        )
        relationships = pd.read_csv(
            data_dir / "reference/entity_relationships.csv"
        ).fillna("")
        write("relationships", relationships)
        live = con.sql("SELECT * FROM live ORDER BY anomaly_score DESC,entity_id").df()
        hazard_sources = {}
        for model in ["B", "C"]:
            for horizon in [6, 12, 18]:
                paths = sorted(
                    (reports / "models").glob(
                        f"primary_include_*_{horizon}m_{model}.json"
                    )
                )
                artifact = json.loads(paths[-1].read_text())
                hazard_sources[f"{model}_{horizon}"] = paths[-1].name
                fitted = restore_hazard(artifact["model"])
                previous = live.copy()
                previous["month"] -= pd.DateOffset(months=1)
                features = (
                    con.sql("SELECT * FROM grid").df().set_index(["entity_id", "month"])
                )
                for idx, row in previous.iterrows():
                    key = row.entity_id, row.month
                    if key in features.index:
                        for column in previous.columns.intersection(features.columns):
                            previous.at[idx, column] = features.loc[key, column]
                live[f"{model}_{horizon}"] = fitted.predict(
                    live, horizon, previous if model == "B" else None
                )
        live["risk_tier"] = np.where(
            live.anomaly_score >= 1,
            "high",
            np.where(live.anomaly_score >= 0.5, "elevated", "low"),
        )
        live["size_band"] = pd.cut(
            live.c_12m,
            [-1, 12, 100, 1000, np.inf],
            labels=[
                "<13 complaints",
                "13–100 complaints",
                "101–1,000 complaints",
                ">1,000 complaints",
            ],
        ).astype(str)
        events = con.read_parquet(str(target / "events.parquet")).df()
        active = set(
            events.loc[
                events.status.isin(["Pending Litigation", "Post Order/Post Judgment"]),
                "entity_id",
            ]
        )
        live["active_action"] = live.entity_id.isin(active)
        spark = (
            con.read_parquet(str(target / "company_trend.parquet"))
            .df()
            .groupby("entity_id")
            .tail(24)
            .groupby("entity_id")
            .complaints.agg(list)
        )
        live["sparkline"] = live.entity_id.map(spark)
        live["normalized_rate"] = live.c_per_bn_assets.where(
            live.type.eq("bank"), live.c_per_1k_orig
        )
        live["rate_basis"] = np.where(
            live.type.eq("bank"),
            "per $1bn assets",
            np.where(
                live.type.eq("nonbank_servicer"),
                "unavailable: servicing exposure",
                "per 1,000 originations",
            ),
        )
        live["top_drivers"] = live.drivers.map(
            lambda s: "; ".join(d["label"] for d in json.loads(s))
        )
        keep = [
            "entity_id",
            "display_name",
            "peer_group",
            "month",
            "rank",
            "anomaly_score",
            "risk_tier",
            "size_band",
            "active_action",
            "c_12m",
            "normalized_rate",
            "rate_basis",
            "top_drivers",
            "sparkline",
        ] + [f"{m}_{h}" for m in ["B", "C"] for h in [6, 12, 18]]
        write("leaderboard", live[keep])
        drivers = [
            {"entity_id": r.entity_id, **d}
            for r in live.itertuples()
            for d in json.loads(r.drivers)
        ]
        write("drivers", pd.DataFrame(drivers))
        query("metrics", "SELECT * FROM results")
        query(
            "hits",
            """SELECT s.* EXCLUDE(drivers),e.display_name FROM scores s JOIN entity e USING(entity_id)
            WHERE rank<=20 ORDER BY "window",policy,horizon,cutoff,model,rank""",
        )
        query(
            "flags",
            """SELECT DISTINCT entity_id,cutoff::DATE cutoff,rank,event_date,lead_months
            FROM scores WHERE model='A' AND "window"='primary' AND policy='include' AND horizon=12 AND rank<=20""",
        )
        # One earliest hit per company/model avoids counting repeated cutoffs as independent leads.
        query(
            "leads",
            """SELECT "window",policy,horizon,model,entity_id,event_date,max(lead_months) lead_months
            FROM scores WHERE rank<=20 AND outcome=1 GROUP BY 1,2,3,4,5,6""",
        )
        for name, file in [
            ("errors", "error_review.csv"),
            ("event_pairs", "event_matched_pairs.csv"),
        ]:
            write(name, pd.read_csv(reports / file))
        pairs = pd.read_csv(reports / "event_matched_pairs.csv")
        con.register("matched_pairs", pairs)
        query(
            "event_series",
            """SELECT p.entity_id,
            date_diff('month',date_trunc('month',p.event_date::TIMESTAMP),cg.month) relative_month,
            (cg.c_12m+1)::DOUBLE/(cb.c_12m+1) AS "case",
            (pg.c_12m+1)::DOUBLE/(pb.c_12m+1) AS peer
            FROM matched_pairs p
            JOIN grid cb ON cb.entity_id=p.entity_id AND cb.month=p.baseline_month::DATE
            JOIN grid pb ON pb.entity_id=p.peer_entity_id AND pb.month=p.baseline_month::DATE
            JOIN grid cg ON cg.entity_id=p.entity_id
            JOIN grid pg ON pg.entity_id=p.peer_entity_id AND pg.month=cg.month
            WHERE date_diff('month',date_trunc('month',p.event_date::TIMESTAMP),cg.month) BETWEEN -48 AND 12
            ORDER BY p.entity_id,relative_month""",
        )
        con.unregister("matched_pairs")
        series = con.read_parquet(str(target / "event_series.parquet")).df()
        ids = sorted(series.entity_id.unique())
        rng = np.random.default_rng(20260926)
        draws = int(
            json.loads((reports / "backtest_audit.json").read_text())["bootstrap_draws"]
        )
        samples = rng.integers(0, len(ids), size=(draws, len(ids))) if ids else []
        aggregate = []
        for column in ["case", "peer"]:
            matrix = series.pivot(
                index="entity_id", columns="relative_month", values=column
            ).reindex(ids)
            for offset in range(-48, 13):
                values = (
                    matrix[offset].to_numpy()
                    if offset in matrix
                    else np.full(len(ids), np.nan)
                )
                valid = np.isfinite(values).sum()
                if valid:
                    replicate = values[samples]
                    n = np.isfinite(replicate).sum(axis=1)
                    boot = np.divide(
                        np.nansum(replicate, axis=1),
                        n,
                        out=np.full(draws, np.nan),
                        where=n > 0,
                    )
                    low, high = np.nanquantile(boot, [0.025, 0.975])
                    avg = np.nanmean(values)
                else:
                    avg = low = high = np.nan
                aggregate.append(
                    dict(
                        series=column,
                        relative_month=offset,
                        value=avg,
                        low=low,
                        high=high,
                        n_pairs=int(valid),
                    )
                )
        write("event_aggregate", pd.DataFrame(aggregate))
        prior = (
            json.loads((output / "manifest.json").read_text())
            if (output / "manifest.json").exists()
            else {}
        )
        ccdb_meta = meta if meta is not None else prior.get("ccdb_meta", {})
        manifest = {
            "built_at": datetime.now(timezone.utc).isoformat(),
            "last_successful_refresh": refresh or prior.get("last_successful_refresh"),
            "ccdb_meta": ccdb_meta,
            "live_as_of": str(live.month.max().date()),
            "hazard_sources": hazard_sources,
            "probability_bands": {"low": "<3%", "elevated": "3%–<10%", "high": "≥10%"},
            "risk_tiers": {
                "low": "screening score <0.5",
                "elevated": "0.5–<1",
                "high": "≥1",
            },
            "size_basis": "Trailing 12-month complaint volume; comparable exposure denominators unavailable across peer groups",
            "change_point_rule": "Descriptive marker: own-history z ≥2 and 6v6 log growth >0.5; not a fitted change-point model",
            "action_filter_rule": "Conservative active-action proxy: Pending Litigation or Post Order/Post Judgment; order status does not establish ongoing wrongdoing",
            "ownership_coverage": "NIC/GLEIF parent chains are not present in M2; reviewed relationships and FDIC history only",
            "event_chart": json.loads((reports / "backtest_audit.json").read_text())[
                "event_chart"
            ],
            "files": {
                p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                for p in target.glob("*.parquet")
            },
        }
        (target / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
        # App deployments consume a complete committed bundle. Each file replaces atomically locally.
        output.mkdir(exist_ok=True)
        for path in target.glob("*.parquet"):
            os.replace(path, output / path.name)
        os.replace(target / "manifest.json", output / "manifest.json")
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=Path("data"))
    parser.add_argument("--reports-dir", type=Path, default=Path("reports"))
    args = parser.parse_args()
    print(json.dumps(build(args.data_dir, args.reports_dir), indent=2))


if __name__ == "__main__":
    main()
