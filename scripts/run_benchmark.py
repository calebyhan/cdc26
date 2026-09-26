"""Run the seeded synthetic reconciliation benchmark and write its summary."""

import argparse
import json
from pathlib import Path

from not_my_debt.benchmark import run

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--per-family", type=int, default=5)
    parser.add_argument("--output", type=Path, default=ROOT / "data/benchmark/results.json")
    args = parser.parse_args()
    results = run(per_family=args.per_family)
    args.output.write_text(json.dumps(results, indent=2) + "\n")
    print(f"{results['all_checks_passed']}/{results['bundles']} bundles passed all checks")


if __name__ == "__main__":
    main()
