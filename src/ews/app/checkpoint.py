"""Package only the small inputs required by the daily refresh job."""

import argparse
import tarfile
from pathlib import Path

from ews.app.refresh import SEED_FILES


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    with tarfile.open(args.output, "w:gz") as archive:
        for relative in SEED_FILES:
            archive.add(Path("data") / relative, arcname=str(Path("data") / relative))


if __name__ == "__main__":
    main()
