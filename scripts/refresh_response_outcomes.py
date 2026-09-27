#!/usr/bin/env python3
"""Add CFPB company-response aggregates to the committed research JSON."""

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from not_my_debt.research import refresh_response_outcomes  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reuse", action="store_true", help="Reuse cached raw API responses")
    parser.add_argument("--output", type=Path, default=ROOT / "data/research/research.json")
    args = parser.parse_args()
    outcome = refresh_response_outcomes(args.output, ROOT / "data/raw", reuse=args.reuse, root=ROOT)
    for group in outcome["groups"]:
        print(
            group["label"], group["total"], [(r["label"], r["count"]) for r in group["responses"]]
        )


if __name__ == "__main__":
    main()
