"""Rebuild ingestion, reviewed entity resolution, exposures, and company_month."""

import argparse
import json
import shutil
from datetime import date
from pathlib import Path

from ews.features.panel import build
from ews.ingest.complaints import REFERENCE, ingest, pipeline_lock
from ews.ingest.enforcement import Archive, scrape
from ews.ingest.enforcement_labels import build as build_enforcement
from ews.ingest.exposures import ingest_fdic, ingest_hmda
from ews.ingest.identity_sources import IdentityArchive
from ews.resolve.pipeline import build as resolve


def run(
    data_dir=Path("data"),
    offline=False,
    start=date(2014, 1, 1),
    end=None,
    years=range(2018, 2026),
    rebuild_sources=True,
):
    data_dir = Path(data_dir)
    reference = data_dir / "reference"
    reference.mkdir(parents=True, exist_ok=True)
    for source in REFERENCE.glob("*.csv"):
        target = reference / source.name
        if not target.exists():
            shutil.copy2(source, target)
    years = tuple(years)
    if not years or len(years) != len(set(years)):
        raise ValueError("Supply distinct HMDA years")
    # Ingestion has its own lock. Never hold it recursively.
    if rebuild_sources:
        if offline and not (data_dir / "raw/complaints.csv").exists():
            raise FileNotFoundError(
                "Offline pipeline needs archived raw complaints.csv"
            )
        print("Rebuild complaint and enforcement staging", flush=True)
        ingest(data_dir / "raw/complaints.csv", data_dir, reference)
        records = scrape(Archive(data_dir / "raw/enforcement", offline=offline), 386)
        build_enforcement(records, data_dir, reference)
        print("Rebuild reviewed M2 crosswalk", flush=True)
        resolve(data_dir, offline=offline)
    with pipeline_lock(data_dir):
        archive = IdentityArchive(data_dir / "raw", offline=offline)
        ingest_fdic(data_dir, archive, reference)
        ingest_hmda(data_dir, archive, years)
        return build(data_dir, start, end, reference)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=Path("data"))
    parser.add_argument("--offline", action="store_true")
    parser.add_argument("--start", type=date.fromisoformat, default=date(2014, 1, 1))
    parser.add_argument("--end", type=date.fromisoformat, default=None)
    parser.add_argument(
        "--hmda-years", default="2018,2019,2020,2021,2022,2023,2024,2025"
    )
    parser.add_argument(
        "--reuse-staging",
        action="store_true",
        help="Skip M1/M2 rebuild; still rebuild exposures and panel",
    )
    args = parser.parse_args()
    years = [int(y) for y in args.hmda_years.split(",")]
    print(
        json.dumps(
            run(
                args.data_dir,
                args.offline,
                args.start,
                args.end,
                years,
                not args.reuse_staging,
            ),
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
