"""Daily complaint delta, dated reviewed links, current panel and frozen-model scores."""

import argparse
import json
import shutil
import tempfile
from datetime import date, datetime, timezone
from pathlib import Path

import duckdb
import numpy as np

from ews.app.precompute import build as dashboard_build
from ews.backtest.data import read_frame
from ews.features.panel import build as panel_build
from ews.ingest.ccdb import search
from ews.ingest.complaints import delta
from ews.models.anomaly import AnomalyModel

# A small operational checkpoint, not the 13GB raw archive. Static exposures retain
# their original report and availability dates; daily updates only change CCDB data.
SEED_FILES = [
    "staging/stg_complaints.parquet",
    "staging/stg_fdic_financials.parquet",
    "staging/stg_fdic_history.parquet",
    "staging/stg_hmda_lender_year.parquet",
    "staging/stg_enforcement.parquet",
    "marts/entity.parquet",
    "marts/alias.parquet",
    "marts/enforcement_entity.parquet",
    "marts/resolution_report.json",
    "marts/score_snapshot.parquet",
    "marts/backtest_results.parquet",
]


def relink(data_dir):
    """Reuse reviewed dated aliases; new/unreviewed names remain unmapped."""
    with duckdb.connect() as con:
        con.read_parquet(str(data_dir / "staging/stg_complaints.parquet")).create_view(
            "complaints"
        )
        con.read_parquet(str(data_dir / "marts/alias.parquet")).create_view("aliases")
        rows = con.sql("""SELECT c.complaint_id,c.date_received,c.company,
            a.entity_id,a.reviewed_by,a.reviewed_on FROM complaints c LEFT JOIN aliases a
            ON a.source='ccdb' AND a.decision='accept' AND a.raw_string=c.company
            AND (a.valid_from IS NULL OR c.date_received>=a.valid_from)
            AND (a.valid_to IS NULL OR c.date_received<=a.valid_to)""")
        rows.create_view("links")
        total, mapped, duplicates = con.sql(
            "SELECT count(*),count(entity_id),count(*)-count(DISTINCT complaint_id) FROM links"
        ).fetchone()
        if duplicates or not total or mapped / total < 0.94:
            raise ValueError(
                "Reviewed dated alias coverage must remain ≥94% with unique complaint IDs"
            )
        rows.write_parquet(str(data_dir / "marts/complaint_entity.parquet"))
        report_path = data_dir / "marts/resolution_report.json"
        report = json.loads(report_path.read_text())
        report.update(
            mortgage_complaints=total,
            reviewed_mapped_complaints=mapped,
            reviewed_complaint_coverage=mapped / total,
        )
        report_path.write_text(json.dumps(report, indent=2) + "\n")


def run(data_dir=Path("data"), reports=Path("reports")):
    data_dir, reports = Path(data_dir), Path(reports)
    # Fail before mutation on API schema/content-type changes.
    payload = search(size=0, product="Mortgage", no_aggs="true")
    meta = payload.get("_meta")
    if not isinstance(meta, dict) or not meta.get("last_indexed"):
        raise ValueError("CCDB _meta.last_indexed is required to publish a refresh")
    with tempfile.TemporaryDirectory(prefix=".refresh-", dir=data_dir.parent) as tmp:
        work = Path(tmp) / "data"
        for file in SEED_FILES:
            source = data_dir / file
            destination = work / file
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)
        shutil.copytree(data_dir / "reference", work / "reference")
        report = delta(work, reference=work / "reference")
        relink(work)
        # Rebuild both the censored M3 mart and uncensored chart/model features.
        panel_build(work, reference=work / "reference")
        panel_build(
            work,
            start=date(2012, 1, 1),
            reference=work / "reference",
            truncate_at_event=False,
            output_name="company_month_features",
        )
        grid = read_frame(work / "marts/company_month_features.parquet")
        live = grid[grid.month.eq(grid.month.max())].copy().reset_index(drop=True)
        model = AnomalyModel().fit(live)
        live["anomaly_score"] = model.score(live)
        live["drivers"] = [json.dumps(d) for d in model.drivers(live)]
        entities = read_frame(work / "marts/entity.parquet")
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
        with duckdb.connect() as con:
            con.register("live", live)
            con.sql("SELECT * FROM live").write_parquet(
                str(work / "marts/live_anomaly.parquet")
            )
        bundle = dashboard_build(work, reports, output=work / "dashboard", meta=meta)
        # Publish only after all network, linking, panel and scoring checks succeed.
        for folder in ["staging", "marts", "dashboard"]:
            for source in (work / folder).glob("*"):
                if source.is_file():
                    destination = data_dir / folder / source.name
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    source.replace(destination)
        report.update(ccdb_meta=meta, built_at=bundle["built_at"])
        return report


def mark_success(data_dir=Path("data")):
    path = Path(data_dir) / "dashboard/manifest.json"
    info = json.loads(path.read_text())
    info["last_successful_refresh"] = datetime.now(timezone.utc).isoformat()
    temporary = path.with_suffix(".partial")
    temporary.write_text(json.dumps(info, indent=2) + "\n")
    temporary.replace(path)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=Path("data"))
    parser.add_argument("--reports-dir", type=Path, default=Path("reports"))
    parser.add_argument("--mark-success", action="store_true")
    args = parser.parse_args()
    if args.mark_success:
        mark_success(args.data_dir)
    else:
        print(json.dumps(run(args.data_dir, args.reports_dir), indent=2))


if __name__ == "__main__":
    main()
