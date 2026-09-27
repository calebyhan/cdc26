"""Hospital price-transparency files: a small, matched basket of shoppable services.

CMS requires hospitals to post machine-readable standard-charge files (MRFs) and
to list them in ``/cms-hpt.txt`` at the site root. This module finds that index
from the website a nonprofit hospital reported on Schedule H, streams its MRF,
and keeps only the basket codes. Files that are unreachable, too large, or not
in a recognizable CMS template are skipped and counted, never guessed.

Prices are integer cents. A posted price is not what a given patient owes.
"""

from __future__ import annotations

import csv
import io
import json
import re
import statistics
import time
import urllib.parse
import urllib.request
import zipfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

BASKET = {
    "99283": "Emergency department visit, moderate severity",
    "70553": "MRI of brain, without then with contrast",
    "73721": "MRI of a leg joint (such as a knee), without contrast",
    "45378": "Diagnostic colonoscopy",
    "80053": "Comprehensive metabolic panel (blood test)",
    "71046": "Chest X-ray, two views",
}
CMS_PAGE = "https://www.cms.gov/priorities/key-initiatives/hospital-price-transparency/hospitals"
MAX_BYTES = 300_000_000
MAX_SECONDS = 240
BROWSER_HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; not-my-debt-atlas)"}


def to_cents(value) -> int | None:
    if value is None:
        return None
    text = re.sub(r"[$,\s]", "", str(value))
    try:
        amount = float(text)
    except ValueError:
        return None
    return round(amount * 100) if amount > 0 else None


def parse_index(text: str) -> list[dict]:
    """Parse cms-hpt.txt into [{location_name, mrf_url, source_page_url}]."""
    entries: list[dict] = []
    current: dict = {}
    for raw in text.splitlines():
        if ":" not in raw:
            continue
        key, value = raw.split(":", 1)
        key = key.strip().lower()
        value = value.strip()
        if key == "location-name":
            if current.get("mrf_url"):
                entries.append(current)
            current = {"location_name": value}
        elif key == "mrf-url":
            current["mrf_url"] = value
        elif key == "source-page-url":
            current["source_page_url"] = value
    if current.get("mrf_url"):
        entries.append(current)
    return entries


def fetch_index(domain: str) -> list[dict]:
    for host in (f"www.{domain}", domain):
        try:
            request = urllib.request.Request(f"https://{host}/cms-hpt.txt", headers=BROWSER_HEADERS)
            with urllib.request.urlopen(request, timeout=20) as response:
                text = response.read(200_000).decode("utf-8", "replace")
            entries = parse_index(text)
            if entries:
                return entries
        except Exception:
            continue
    return []


def _new_code_bucket() -> dict:
    return {"gross": [], "cash": [], "negotiated": [], "file_min": [], "file_max": []}


def _record(buckets: dict, code: str, gross, cash, negotiated, low, high) -> None:
    bucket = buckets.setdefault(code, _new_code_bucket())
    for key, value in (("gross", gross), ("cash", cash), ("file_min", low), ("file_max", high)):
        cents = to_cents(value)
        if cents:
            bucket[key].append(cents)
    for value in negotiated:
        cents = to_cents(value)
        if cents:
            bucket["negotiated"].append(cents)


def parse_csv(lines) -> dict:
    """Parse CMS CSV templates (v2 tall or wide). Returns raw per-code buckets."""
    reader = csv.reader(lines)
    header = None
    for _ in range(6):
        row = next(reader, None)
        if row is None:
            return {}
        lowered = [cell.strip().lower() for cell in row]
        if "description" in lowered and any(cell.startswith("code|") for cell in lowered):
            header = lowered
            break
    if header is None:
        return {}
    code_columns = [
        (i, header.index(f"{name}|type"))
        for i, name in enumerate(header)
        if re.fullmatch(r"code\|\d+", name) and f"{name}|type" in header
    ]
    col = {name: i for i, name in enumerate(header)}
    negotiated_cols = [
        i for i, name in enumerate(header)
        if name == "standard_charge|negotiated_dollar"
        or (name.startswith("standard_charge|") and name.endswith("|negotiated_dollar"))
    ]
    modifier = col.get("modifiers")
    buckets: dict = {}
    for row in reader:
        for code_i, type_i in code_columns:
            if code_i >= len(row):
                continue
            code = row[code_i].strip()
            if code in BASKET and row[type_i].strip().upper() in {"CPT", "HCPCS"}:
                if modifier is not None and modifier < len(row) and row[modifier].strip():
                    break  # modifier rows describe a component, not the whole service
                get = lambda name: row[col[name]] if name in col and col[name] < len(row) else None  # noqa: E731
                _record(
                    buckets,
                    code,
                    get("standard_charge|gross"),
                    get("standard_charge|discounted_cash"),
                    [row[i] for i in negotiated_cols if i < len(row)],
                    get("standard_charge|min"),
                    get("standard_charge|max"),
                )
                break
    return buckets


def parse_json(data: dict) -> dict:
    buckets: dict = {}
    for item in data.get("standard_charge_information", []) or []:
        codes = [
            c.get("code", "").strip()
            for c in item.get("code_information", []) or []
            if str(c.get("type", "")).upper() in {"CPT", "HCPCS"}
        ]
        code = next((c for c in codes if c in BASKET), None)
        if not code:
            continue
        for charge in item.get("standard_charges", []) or []:
            if charge.get("modifier_code") or charge.get("modifiers"):
                continue
            _record(
                buckets,
                code,
                charge.get("gross_charge"),
                charge.get("discounted_cash"),
                [p.get("standard_charge_dollar") for p in charge.get("payers_information", []) or []],
                charge.get("minimum"),
                charge.get("maximum"),
            )
    return buckets


def summarize(buckets: dict) -> dict:
    out = {}
    for code, bucket in buckets.items():
        negotiated = bucket["negotiated"]
        lows = bucket["file_min"] + negotiated
        highs = bucket["file_max"] + negotiated
        out[code] = {
            "gross_cents": round(statistics.median(bucket["gross"])) if bucket["gross"] else None,
            "cash_cents": round(statistics.median(bucket["cash"])) if bucket["cash"] else None,
            "negotiated_min_cents": min(lows) if lows else None,
            "negotiated_median_cents": round(statistics.median(negotiated)) if negotiated else None,
            "negotiated_max_cents": max(highs) if highs else None,
            "payer_rates": len(negotiated),
        }
    return {code: value for code, value in out.items() if any(v for k, v in value.items() if k != "payer_rates")}


def download(url: str, path: Path) -> Path | None:
    if path.exists() and path.stat().st_size > 0:
        return path
    request = urllib.request.Request(url, headers=BROWSER_HEADERS)
    with urllib.request.urlopen(request, timeout=180) as response:
        length = int(response.headers.get("Content-Length") or 0)
        if length > MAX_BYTES:
            return None
        tmp = path.with_suffix(".part")
        total = 0
        started = time.monotonic()
        with tmp.open("wb") as out:
            while chunk := response.read(1 << 20):
                total += len(chunk)
                if total > MAX_BYTES or time.monotonic() - started > MAX_SECONDS:
                    out.close()
                    tmp.unlink(missing_ok=True)
                    return None
                out.write(chunk)
    tmp.replace(path)
    return path


def parse_file(path: Path) -> dict:
    with path.open("rb") as handle:
        head = handle.read(4)
    if head.startswith(b"PK"):
        with zipfile.ZipFile(path) as archive:
            member = next(
                (n for n in archive.namelist() if n.lower().endswith((".csv", ".json"))), None
            )
            if not member:
                return {}
            with archive.open(member) as raw:
                if member.lower().endswith(".json"):
                    return parse_json(json.load(raw))
                return parse_csv(io.TextIOWrapper(raw, encoding="utf-8-sig", errors="replace"))
    with path.open("rb") as handle:
        start = handle.read(2048).lstrip()
    if start[:1] in (b"{", b"["):
        with path.open(encoding="utf-8-sig", errors="replace") as handle:
            data = json.load(handle)
        return parse_json(data if isinstance(data, dict) else {})
    with path.open(encoding="utf-8-sig", errors="replace", newline="") as handle:
        return parse_csv(handle)


def domain_of(url: str | None) -> str | None:
    if not url:
        return None
    url = url.strip().lower()
    if not url.startswith("http"):
        url = "https://" + url
    try:
        host = urllib.parse.urlparse(url).hostname
    except ValueError:
        return None
    return host.removeprefix("www.") if host else None


def collect(targets: list[dict], raw_dir: Path, workers: int = 8) -> tuple[list[dict], dict]:
    """targets: [{hospital_id, name, domains}] → price rows and a status tally."""
    raw_dir.mkdir(parents=True, exist_ok=True)
    from .schedule_h import similarity

    def one(target: dict) -> tuple[dict | None, str]:
        cache = raw_dir / f"{target['hospital_id']}.json"
        if cache.exists():
            cached = json.loads(cache.read_text())
            return (cached if cached.get("prices") else None), cached.get("status", "cached")
        status = "no_index"
        result = None
        try:
            entries = next(
                (found for domain in target["domains"] if (found := fetch_index(domain))), []
            )
            if entries:
                status = "no_location_match"
                scored = sorted(
                    ((similarity(target["name"], e.get("location_name", "")), e) for e in entries),
                    key=lambda pair: -pair[0],
                )
                entry = scored[0][1] if (scored[0][0] >= 0.34 or len(entries) == 1) else None
                if entry:
                    status = "too_large_or_unreachable"
                    suffix = ".zip" if ".zip" in entry["mrf_url"].lower() else ".dat"
                    path = download(entry["mrf_url"], raw_dir / f"{target['hospital_id']}{suffix}")
                    if path:
                        status = "unrecognized_format"
                        prices = summarize(parse_file(path))
                        path.unlink(missing_ok=True)  # keep only the extracted basket
                        if prices:
                            status = "ok"
                            result = {
                                "hospital_id": target["hospital_id"],
                                "location_name": entry.get("location_name"),
                                "mrf_url": entry["mrf_url"],
                                "prices": prices,
                            }
        except Exception:
            status = status if status != "no_index" else "error"
        cache.write_text(json.dumps({**(result or {}), "status": status}))
        return result, status

    rows, tally = [], {}
    with ThreadPoolExecutor(workers) as pool:
        for result, status in pool.map(one, targets):
            tally[status] = tally.get(status, 0) + 1
            if result:
                rows.append(result)
    return rows, tally


def select_targets(out_dir: Path, per_state: int) -> list[dict]:
    """Up to ``per_state`` linked nonprofit hospitals per state, ordered by CMS ID."""
    hospitals = json.loads((out_dir / "hospitals.json").read_text())
    filers = json.loads((out_dir / "schedule_h.json").read_text())["filers"]
    fields = hospitals["fields"]
    chosen: dict[str, list[dict]] = {}
    for values in sorted(hospitals["rows"], key=lambda r: r[0]):
        row = dict(zip(fields, values))
        if row["ownership_class"] != "nonprofit" or not row["policy_ref"]:
            continue
        filer_index, policy_index = row["policy_ref"]
        filer = filers[filer_index]
        policy = filer["policies"][policy_index]
        websites = [f.get("website") for f in filer["facilities"] if f.get("cms_id") == row["id"]]
        domains = []
        for url in (*websites, policy.get("fap_url"), policy.get("application_url")):
            domain = domain_of(url)
            if domain and domain not in domains:
                domains.append(domain)
        bucket = chosen.setdefault(row["state"], [])
        if domains and len(bucket) < per_state:
            bucket.append({"hospital_id": row["id"], "name": row["name"], "domains": domains})
    return [target for bucket in chosen.values() for target in bucket]
