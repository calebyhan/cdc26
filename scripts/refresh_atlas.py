"""Rebuild the community medical-debt atlas from public sources.

Usage:
    uv sync --extra dev --extra atlas
    python scripts/refresh_atlas.py            # reuse cached raw inputs when present
    python scripts/refresh_atlas.py --refresh  # re-download everything

Raw inputs stay in ignored data/raw/atlas; aggregates are written to public/atlas.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from not_my_debt.atlas import build, cfpb, cms, prices, schedule_h  # noqa: E402
from not_my_debt.atlas.net import utc_now  # noqa: E402
from not_my_debt.atlas.sources import SOURCES  # noqa: E402

RAW = ROOT / "data/raw/atlas"
IRS_YEARS = (2025, 2026)
PRICE_HOSPITALS_PER_STATE = 4
CFPB_WINDOWS = [(f"{y}-01-01", f"{y}-12-31") for y in range(2021, 2026)] + [
    ("2026-01-01", "2026-08-31")
]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--refresh", action="store_true", help="re-download cached inputs")
    args = parser.parse_args()
    reuse = not args.refresh
    RAW.mkdir(parents=True, exist_ok=True)
    started = utc_now()

    records = RAW / "cfpb_medical.jsonl"
    pull_report = RAW / "cfpb_pull_report.json"
    if args.refresh or not records.exists():
        pull_report.write_text(json.dumps(cfpb.pull(records, CFPB_WINDOWS), indent=1))
        print("CFPB records pulled", flush=True)

    hospitals_csv = cms.fetch(RAW, reuse=reuse)
    names = set()
    with hospitals_csv.open(encoding="utf-8-sig") as handle:
        for row in csv.DictReader(handle):
            if cms.ownership_class(row["Hospital Ownership"]) in {"nonprofit", "government"}:
                names.add(schedule_h.normalize_name(row["Facility Name"]))
    indexes = [schedule_h.fetch_index(RAW, year, reuse=reuse) for year in IRS_YEARS]
    candidates = schedule_h.candidate_returns(indexes, names)
    urls = [url for year in IRS_YEARS for url in schedule_h.batch_urls(year)]
    located = schedule_h.locate(
        {c["object_id"] for c in candidates}, urls, RAW / "irs_located.json", reuse=reuse
    )
    parsed = schedule_h.fetch_all(candidates, located, RAW / "schedule_h")
    print(f"Schedule H: {len(parsed)} filers of {len(candidates)} candidates", flush=True)

    out = ROOT / "public/atlas"
    result = build.build(RAW, out, reuse=reuse)
    # Price basket: a bounded sample of linked nonprofit hospitals per state.
    targets = prices.select_targets(out, PRICE_HOSPITALS_PER_STATE)
    _, price_tally = prices.collect(targets, RAW / "prices")
    print(f"Price files: {price_tally}", flush=True)
    result = build.build(RAW, out, reuse=True)
    manifest = {
        "schema_version": "1.0",
        "started_at": started,
        "generated_at": utc_now(),
        "sources": SOURCES,
        "cfpb_pull": json.loads(pull_report.read_text()) if pull_report.exists() else None,
        "irs": {
            "index_years": list(IRS_YEARS),
            "candidate_returns": len(candidates),
            "located_returns": len(located),
            "returns_with_schedule_h": len(parsed),
        },
        **result,
    }
    (ROOT / "public/atlas/manifest.json").write_text(json.dumps(manifest, indent=1))
    print(json.dumps(result["counts"], indent=1))
    print(json.dumps(result["model"], indent=1))


if __name__ == "__main__":
    main()
