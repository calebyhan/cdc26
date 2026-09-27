"""CFPB medical-debt complaint records: bounded pull and geographic aggregation.

Only structured fields are kept (no narratives). A complaint is a consumer's
submission to the CFPB; it is not a verified finding, and the database is not
a statistical sample of consumer harm.
"""

from __future__ import annotations

import json
import re
import urllib.parse
from collections import Counter, defaultdict
from pathlib import Path

from .net import get_json

API_BASE = "https://www.consumerfinance.gov/data-research/consumer-complaints/search/api/v1/"
PRODUCT = "Debt collection•Medical debt"
FIELDS = (
    "complaint_id",
    "date_received",
    "state",
    "zip_code",
    "issue",
    "sub_issue",
    "company",
    "company_response",
    "timely",
    "submitted_via",
    "tags",
    "product",
    "sub_product",
)
PAGE_SIZE = 1000
MAX_PAGES_PER_WINDOW = 60
PAID_SUBISSUE = "Debt was paid"
NOT_OWED = "Attempts to collect debt not owed"


def window_url(start: str, end: str, search_after: str | None = None) -> str:
    params = {
        "size": PAGE_SIZE,
        "no_aggs": "true",
        "sort": "created_date_desc",
        "date_received_min": start,
        "date_received_max": end,
        "product": PRODUCT,
    }
    if search_after:
        params["search_after"] = search_after
    return API_BASE + "?" + urllib.parse.urlencode(params)


def window_total_url(start: str, end: str) -> str:
    params = {
        "size": 0,
        "date_received_min": start,
        "date_received_max": end,
        "product": PRODUCT,
    }
    return API_BASE + "?" + urllib.parse.urlencode(params)


def slim(source: dict) -> dict:
    record = {key: source.get(key) for key in FIELDS}
    record["date_received"] = (record["date_received"] or "")[:10]
    return record


def pull_window(start: str, end: str) -> tuple[list[dict], int]:
    """Page through one date window with search_after; verify the product filter."""
    total = get_json(window_total_url(start, end))["hits"]["total"]["value"]
    records: dict[str, dict] = {}
    cursor = None
    for _ in range(MAX_PAGES_PER_WINDOW):
        hits = get_json(window_url(start, end, cursor), timeout=180)["hits"]["hits"]
        if not hits:
            break
        for hit in hits:
            source = hit["_source"]
            if source.get("product") != "Debt collection" or source.get("sub_product") != (
                "Medical debt"
            ):
                raise RuntimeError("CFPB response contained a non-medical-debt record")
            records[source["complaint_id"]] = slim(source)
        cursor = "_".join(str(value) for value in hits[-1]["sort"])
        if len(hits) < PAGE_SIZE:
            break
    return list(records.values()), total


def pull(path: Path, windows: list[tuple[str, str]]) -> dict:
    """Pull all windows to JSONL; return per-window expected/received counts."""
    path.parent.mkdir(parents=True, exist_ok=True)
    report = []
    with path.open("w") as out:
        for start, end in windows:
            rows, total = pull_window(start, end)
            report.append({"start": start, "end": end, "api_total": total, "received": len(rows)})
            for row in rows:
                out.write(json.dumps(row, separators=(",", ":")) + "\n")
    return {"windows": report}


def load(path: Path) -> list[dict]:
    with path.open() as handle:
        return [json.loads(line) for line in handle if line.strip()]


def months_between(first: str, last: str) -> list[str]:
    year, month = map(int, first.split("-"))
    end_year, end_month = map(int, last.split("-"))
    out = []
    while (year, month) <= (end_year, end_month):
        out.append(f"{year:04d}-{month:02d}")
        month += 1
        if month == 13:
            year, month = year + 1, 1
    return out


def labeled(counter: Counter, limit: int | None = None) -> list[dict]:
    return [{"label": label, "count": count} for label, count in counter.most_common(limit)]


def zip5(value: str | None) -> str | None:
    return value if value and re.fullmatch(r"\d{5}", value) else None


def summarize(
    records: list[dict],
    *,
    months: list[str],
    rate_year: int,
    county_years: tuple[int, int],
    zcta_county: dict[str, str],
) -> dict:
    """Aggregate records by state, month, issue, response, company, and county."""
    month_index = {month: index for index, month in enumerate(months)}
    blank = lambda: [0] * len(months)  # noqa: E731
    monthly: dict[str, list[int]] = defaultdict(blank)
    national_monthly = blank()
    by_state: dict[str, dict] = defaultdict(
        lambda: {
            "count": 0,
            "issues": Counter(),
            "not_owed": Counter(),
            "responses": Counter(),
            "companies": Counter(),
            "timely": 0,
            "servicemember": 0,
            "older_american": 0,
            "zip5": 0,
        }
    )
    national = by_state["US"]
    county_counts: Counter = Counter()
    county_unmapped: Counter = Counter()
    county_total = 0
    for row in records:
        date = row.get("date_received") or ""
        state = row.get("state") or "Unknown"
        month = date[:7]
        if month in month_index:
            monthly[state][month_index[month]] += 1
            national_monthly[month_index[month]] += 1
        year = int(date[:4]) if date[:4].isdigit() else 0
        if county_years[0] <= year <= county_years[1]:
            county_total += 1
            fips = zcta_county.get(zip5(row.get("zip_code")) or "")
            if fips:
                county_counts[fips] += 1
            else:
                county_unmapped[state] += 1
        if year != rate_year:
            continue
        tags = row.get("tags") or ""
        for bucket in (by_state[state], national):
            bucket["count"] += 1
            bucket["issues"][row.get("issue") or "Not reported"] += 1
            if row.get("issue") == NOT_OWED:
                bucket["not_owed"][row.get("sub_issue") or "Not reported"] += 1
            bucket["responses"][row.get("company_response") or "Not reported"] += 1
            bucket["companies"][row.get("company") or "Not reported"] += 1
            bucket["timely"] += row.get("timely") == "Yes"
            bucket["servicemember"] += "Servicemember" in tags
            bucket["older_american"] += "Older American" in tags
            bucket["zip5"] += zip5(row.get("zip_code")) is not None

    def finish(bucket: dict) -> dict:
        count = bucket["count"]
        return {
            "count": count,
            "issues": labeled(bucket["issues"]),
            "not_owed": labeled(bucket["not_owed"]),
            "paid": bucket["not_owed"].get(PAID_SUBISSUE, 0),
            "responses": labeled(bucket["responses"]),
            "top_companies": labeled(bucket["companies"], 6),
            "timely": bucket["timely"],
            "servicemember": bucket["servicemember"],
            "older_american": bucket["older_american"],
            "zip5": bucket["zip5"],
        }

    states = {key: finish(value) for key, value in by_state.items() if key != "US"}
    return {
        "months": months,
        "rate_year": rate_year,
        "national": {**finish(national), "monthly": national_monthly},
        "states": {
            key: {**states.get(key, finish(by_state[key])), "monthly": monthly.get(key, blank())}
            for key in sorted(set(states) | set(monthly))
        },
        "counties": {
            "years": list(county_years),
            "total": county_total,
            "mapped": sum(county_counts.values()),
            "counts": dict(county_counts),
            "unmapped_by_state": dict(county_unmapped),
        },
    }
