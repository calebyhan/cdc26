"""Census ZIP Code Tabulation Area helpers: approximate centroids and county assignment.

USPS ZIP codes and Census ZCTAs are not identical. A ZIP is assigned to the county
containing the largest share of its ZCTA land area, so county attribution is approximate.
"""

from __future__ import annotations

import csv
import io
import zipfile
from pathlib import Path

from .net import cached_download

ZCTA_GAZETTEER_URL = (
    "https://www2.census.gov/geo/docs/maps-data/data/gazetteer/2024_Gazetteer/"
    "2024_Gaz_zcta_national.zip"
)
ZCTA_COUNTY_URL = (
    "https://www2.census.gov/geo/docs/maps-data/data/rel2020/zcta520/"
    "tab20_zcta520_county20_natl.txt"
)


def fetch(raw_dir: Path, *, reuse: bool = True) -> dict[str, Path]:
    return {
        "zcta_gazetteer": cached_download(
            ZCTA_GAZETTEER_URL, raw_dir / "2024_Gaz_zcta_national.zip", reuse=reuse
        ),
        "zcta_county": cached_download(
            ZCTA_COUNTY_URL, raw_dir / "tab20_zcta520_county20_natl.txt", reuse=reuse
        ),
    }


def zcta_centroids(path: Path) -> dict[str, tuple[float, float]]:
    """Return {zcta: (lat, lon)} internal points from the Census gazetteer."""
    with zipfile.ZipFile(path) as archive:
        name = next(n for n in archive.namelist() if n.endswith(".txt"))
        text = archive.read(name).decode("utf-8", "replace")
    reader = csv.reader(io.StringIO(text), delimiter="\t")
    header = [column.strip() for column in next(reader)]
    geoid, lat, lon = header.index("GEOID"), header.index("INTPTLAT"), header.index("INTPTLONG")
    return {
        row[geoid].strip(): (round(float(row[lat]), 4), round(float(row[lon]), 4))
        for row in reader
        if len(row) > lon
    }


def zcta_to_county(path: Path) -> dict[str, str]:
    """Assign each ZCTA to the county with the largest overlapping land area."""
    best: dict[str, tuple[int, str]] = {}
    with path.open(encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle, delimiter="|")
        for row in reader:
            zcta, county = row["GEOID_ZCTA5_20"], row["GEOID_COUNTY_20"]
            if not zcta or not county:
                continue
            area = int(row["AREALAND_PART"] or 0)
            if zcta not in best or area > best[zcta][0]:
                best[zcta] = (area, county)
    return {zcta: county for zcta, (_, county) in best.items()}
