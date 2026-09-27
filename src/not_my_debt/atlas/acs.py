"""ACS 2020–2024 5-year detailed tables for states and counties (no API key needed).

The Census table-based summary files are streamed once and filtered to state
(``0400000US``) and county (``0500000US``) rows, which are cached locally.
"""

from __future__ import annotations

import urllib.request
from pathlib import Path

from .net import HEADERS

VINTAGE = 2024
BASE = "https://www2.census.gov/programs-surveys/acs/summary_file/2024/table-based-SF"
TABLE_URL = BASE + "/data/5YRData/acsdt5y2024-{table}.dat"
GEOS_URL = BASE + "/documentation/Geos20245YR.txt"
SHELLS_URL = BASE + "/documentation/ACS20245YR_Table_Shells.txt"
TABLES = ("b01003", "b27010", "b17001", "b19013", "b18101", "b25070")
KEEP_PREFIXES = ("0400000US", "0500000US")

# Shell lines checked against ACS20245YR_Table_Shells.txt.
UNINSURED = ("B27010_E017", "B27010_E033", "B27010_E050", "B27010_E066")
RENT_BURDEN_30 = ("B25070_E007", "B25070_E008", "B25070_E009", "B25070_E010")


def filtered_download(url: str, path: Path, *, reuse: bool = True, key_column: int = 0) -> Path:
    """Stream a pipe-delimited Census file, keeping the header and state/county rows."""
    if reuse and path.exists() and path.stat().st_size > 0:
        return path
    path.parent.mkdir(parents=True, exist_ok=True)
    request = urllib.request.Request(url, headers=HEADERS)
    tmp = path.with_suffix(".part")
    with urllib.request.urlopen(request, timeout=900) as response, tmp.open("w") as out:
        header = True
        for raw in response:
            line = raw.decode("utf-8", "replace")
            if header:
                out.write(line)
                header = False
                continue
            fields = line.split("|")
            if len(fields) > key_column and fields[key_column].startswith(KEEP_PREFIXES):
                out.write(line)
    tmp.replace(path)
    return path


def read_psv(path: Path, id_column: str = "GEO_ID") -> dict[str, dict[str, str]]:
    with path.open() as handle:
        header = handle.readline().rstrip("\n").split("|")
        rows = {}
        for line in handle:
            values = line.rstrip("\n").split("|")
            row = dict(zip(header, values))
            rows[row[id_column]] = row
    return rows


def disability_columns(shells_path: Path) -> list[str]:
    with shells_path.open() as handle:
        return [
            line.split("|")[3].replace("_", "_E")
            for line in handle
            if line.startswith("B18101|") and line.split("|")[4].strip() == "With a disability"
        ]


def fetch(raw_dir: Path, *, reuse: bool = True) -> dict[str, Path]:
    paths = {
        table: filtered_download(TABLE_URL.format(table=table), raw_dir / f"acs_{table}.psv", reuse=reuse)
        for table in TABLES
    }
    geos_path = raw_dir / "acs_geos.psv"
    if not (reuse and geos_path.exists()):
        filtered_download(GEOS_URL, geos_path, reuse=reuse, key_column=40)
    paths["geos"] = geos_path
    shells = raw_dir / "acs_shells.txt"
    if not (reuse and shells.exists()):
        request = urllib.request.Request(SHELLS_URL, headers=HEADERS)
        with urllib.request.urlopen(request, timeout=300) as response:
            shells.write_bytes(response.read())
    paths["shells"] = shells
    return paths


def _int(row: dict, key: str) -> int | None:
    value = (row or {}).get(key)
    try:
        number = int(float(value))
    except (TypeError, ValueError):
        return None
    return number if number >= 0 else None  # negative sentinels mean not available


def _sum(row: dict, keys) -> int | None:
    values = [_int(row, key) for key in keys]
    return None if any(value is None for value in values) else sum(values)


def _rate(part: int | None, whole: int | None) -> float | None:
    return round(part / whole, 5) if part is not None and whole else None


def build(paths: dict[str, Path]) -> dict[str, dict]:
    """Return {geo_id: metrics} for states and counties."""
    tables = {table: read_psv(paths[table]) for table in TABLES}
    geos = read_psv(paths["geos"])
    disability = disability_columns(paths["shells"])
    out = {}
    for geo_id, row in tables["b01003"].items():
        if not geo_id.startswith(KEEP_PREFIXES):
            continue
        insurance = tables["b27010"].get(geo_id, {})
        poverty = tables["b17001"].get(geo_id, {})
        disabled = tables["b18101"].get(geo_id, {})
        rent = tables["b25070"].get(geo_id, {})
        uninsured = _sum(insurance, UNINSURED)
        insured_universe = _int(insurance, "B27010_E001")
        below_poverty = _int(poverty, "B17001_E002")
        poverty_universe = _int(poverty, "B17001_E001")
        disabled_count = _sum(disabled, disability)
        renters = _int(rent, "B25070_E001")
        renters_computed = (
            renters - (_int(rent, "B25070_E011") or 0) if renters is not None else None
        )
        burdened = _sum(rent, RENT_BURDEN_30)
        geo = geos.get(geo_id, {})
        out[geo_id] = {
            "geo_id": geo_id,
            "fips": geo_id.split("US", 1)[1],
            "name": geo.get("NAME", ""),
            "state_abbr": geo.get("STUSAB", ""),
            "population": _int(row, "B01003_E001"),
            "uninsured": uninsured,
            "uninsured_rate": _rate(uninsured, insured_universe),
            "poverty_rate": _rate(below_poverty, poverty_universe),
            "below_poverty": below_poverty,
            "median_income": _int(tables["b19013"].get(geo_id, {}), "B19013_E001"),
            "disability_rate": _rate(disabled_count, _int(disabled, "B18101_E001")),
            "rent_burden_rate": _rate(burdened, renters_computed),
        }
    return out
