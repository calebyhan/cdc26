"""CMS Hospital General Information: facility location, type, and ownership."""

from __future__ import annotations

import csv
import re
from pathlib import Path

from .net import cached_download

HOSPITALS_URL = (
    "https://data.cms.gov/provider-data/api/1/datastore/query/xubh-q36u/0/download?format=csv"
)
HOSPITALS_PAGE = "https://data.cms.gov/provider-data/dataset/xubh-q36u"


def fetch(raw_dir: Path, *, reuse: bool = True) -> Path:
    return cached_download(HOSPITALS_URL, raw_dir / "cms_hospital_general_information.csv", reuse=reuse)


def ownership_class(value: str) -> str:
    value = value.lower()
    if value.startswith("voluntary"):
        return "nonprofit"
    if value.startswith(("proprietary", "physician")):
        return "for_profit"
    if value.startswith(("government", "veterans", "department of defense", "tribal")):
        return "government"
    return "other"


def zip5(value: str) -> str:
    digits = re.sub(r"\D", "", value or "")
    return digits[:5].zfill(5) if digits else ""


def load(
    path: Path,
    centroids: dict[str, tuple[float, float]],
    zcta_county: dict[str, str],
) -> list[dict]:
    hospitals = []
    with path.open(encoding="utf-8-sig") as handle:
        for row in csv.DictReader(handle):
            code = zip5(row["ZIP Code"])
            point = centroids.get(code)
            rating = row.get("Hospital overall rating", "")
            hospitals.append(
                {
                    "id": row["Facility ID"],
                    "name": row["Facility Name"].strip(),
                    "city": row["City/Town"].strip(),
                    "state": row["State"].strip(),
                    "zip": code,
                    "county_fips": zcta_county.get(code),
                    "county_name": row["County/Parish"].strip(),
                    "type": row["Hospital Type"].strip(),
                    "ownership": row["Hospital Ownership"].strip(),
                    "ownership_class": ownership_class(row["Hospital Ownership"]),
                    "emergency": row["Emergency Services"].strip() == "Yes",
                    "rating": int(rating) if rating.isdigit() else None,
                    "lat": point[0] if point else None,
                    "lon": point[1] if point else None,
                }
            )
    return hospitals
