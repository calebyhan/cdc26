#!/usr/bin/env python3
"""Fetch one bounded official archive and reproduce the committed research JSON."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from not_my_debt.research import (  # noqa: E402
    API_URL,
    ARCHIVE_URL,
    build_research,
    download_archive,
    fetch_api,
    sha256_file,
    summarize_archive,
    utc_now,
    write_json,
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--archive",
        type=Path,
        help="Reuse an existing official Jan–Feb 2025 ZIP; pinned checksum required",
    )
    parser.add_argument(
        "--api-cache", type=Path, help="Reuse a cached official medical-debt API response"
    )
    parser.add_argument(
        "--reuse", action="store_true", help="Reuse default raw files when available"
    )
    parser.add_argument("--output", type=Path, default=ROOT / "data/research/research.json")
    args = parser.parse_args()
    raw = ROOT / "data/raw"
    raw.mkdir(parents=True, exist_ok=True)
    api_path = args.api_cache or raw / "medical_2025_api.json"
    if args.api_cache or (args.reuse and api_path.exists()):
        api = json.loads(api_path.read_text(encoding="utf-8"))
    else:
        api = fetch_api(api_path)
    metadata_path = api_path.with_suffix(".metadata.json")
    metadata = json.loads(metadata_path.read_text()) if metadata_path.exists() else {}
    archive_path = args.archive or raw / ARCHIVE_URL.rsplit("/", 1)[1]
    if not archive_path.exists():
        if args.archive:
            parser.error("--archive does not exist")
        print("Downloading one archive, capped at 90 MB.", flush=True)
        download_archive(archive_path)
    print(
        "Scanning only the Jan–Feb 2025 archive; raw narrative text stays in data/raw.", flush=True
    )
    archive = summarize_archive(archive_path, raw / "medical_narratives.jsonl")
    # With legacy cached files, record the file timestamp rather than pretending
    # a fresh download happened during this run.
    from datetime import datetime, timezone

    api_retrieved = metadata.get("retrieved_at") or datetime.fromtimestamp(
        api_path.stat().st_mtime, timezone.utc
    ).isoformat(timespec="seconds")
    result = build_research(api, archive, api_retrieved_at=api_retrieved)
    write_json(args.output, result)
    manifest = {
        "schema_version": "1.0",
        "generated_at": utc_now(),
        "sources": [
            {
                "name": "CFPB medical-debt annual aggregation",
                "source_url": API_URL,
                "retrieved_at": api_retrieved,
                "sha256": sha256_file(api_path),
                "bytes": api_path.stat().st_size,
                "local_path": "data/raw/medical_2025_api.json",
            },
            {
                "name": "CFPB historical narratives, Jan–Feb 2025",
                "source_url": ARCHIVE_URL,
                "retrieved_at": datetime.fromtimestamp(
                    archive_path.stat().st_mtime, timezone.utc
                ).isoformat(timespec="seconds"),
                "sha256": archive["sha256"],
                "bytes": archive["compressed_bytes"],
                "local_path": "data/raw/" + archive_path.name,
            },
        ],
        "output": {
            "path": str(args.output.relative_to(ROOT))
            if args.output.is_relative_to(ROOT)
            else args.output.name,
            "sha256": sha256_file(args.output),
        },
    }
    write_json(args.output.parent / "source_manifest.json", manifest)
    print(
        json.dumps(
            {
                "annual_complaints": result["api"]["total_complaints"],
                "archive_medical_complaints": archive["medical_total"],
                "with_narratives": archive["medical_with_narrative"],
                "unique_narratives": archive["unique_narratives"],
                "output": str(args.output),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
