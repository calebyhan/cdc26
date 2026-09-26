"""Sample the CFPB Consumer Complaint Database search API.

Usage: python spike/ccdb_sample.py
Writes spike/data/ccdb_sample_500.json, spike/data/ccdb_companies.json,
spike/data/ccdb_state_counts_2025.json.

Gotchas encoded here (verified 2026-09-26):
  * URL must end in "/v1/" - without the trailing slash you get the HTML search UI (HTTP 200).
  * Never pass format=json -> 404. format=csv is the export path (100k-row cap, 2 req/min).
  * Anonymous search is throttled at 20 req/min.
  * The company aggregation is capped at 6,500 buckets, so enumerate companies per year.
"""
import json
import time
from pathlib import Path

import requests

API = "https://www.consumerfinance.gov/data-research/consumer-complaints/search/api/v1/"
OUT = Path(__file__).parent / "data"
MIN_INTERVAL = 3.1  # stay under 20 req/min


def search(**params):
    r = requests.get(API, params=params, timeout=180)
    r.raise_for_status()
    if not r.headers.get("content-type", "").startswith("application/json"):
        raise RuntimeError(f"Non-JSON response from {r.url} - check trailing slash / params")
    time.sleep(MIN_INTERVAL)
    return r.json()


def sample_rows(n=500, **filters):
    d = search(size=n, sort="created_date_desc", no_aggs="true", **filters)
    return [h["_source"] for h in d["hits"]["hits"]]


def iter_all(page_size=1000, **filters):
    """Deep pagination via search_after (frm is capped at 10,000)."""
    after = None
    while True:
        params = dict(size=page_size, sort="created_date_desc", no_aggs="true", **filters)
        if after:
            params["search_after"] = after
        hits = search(**params)["hits"]["hits"]
        if not hits:
            return
        yield from (h["_source"] for h in hits)
        s = hits[-1]["sort"]
        after = f"{s[0]}_{s[1]}"


def aggregations(**filters):
    """size=0 returns only aggregations: product, issue, company, state, tags, timely, ..."""
    return search(size=0, **filters)["aggregations"]


def buckets(aggs, field):
    return {b["key"]: b["doc_count"] for b in aggs[field][field]["buckets"]}


if __name__ == "__main__":
    OUT.mkdir(exist_ok=True)
    rows = sample_rows(500, date_received_min="2025-06-01", date_received_max="2025-06-30")
    (OUT / "ccdb_sample_500.json").write_text(json.dumps(rows, indent=1))
    print("sample rows:", len(rows))

    # State x count replaces the removed /geo/states endpoint.
    states = buckets(aggregations(date_received_min="2025-01-01", date_received_max="2025-12-31"), "state")
    (OUT / "ccdb_state_counts_2025.json").write_text(json.dumps(states, indent=1))
    print("states in 2025:", len(states))

    companies = {}
    for year in range(2011, 2027):
        aggs = aggregations(date_received_min=f"{year}-01-01", date_received_max=f"{year}-12-31")
        co = aggs["company"]["company"]
        if co["sum_other_doc_count"]:
            print(f"  WARNING {year}: {co['sum_other_doc_count']} complaints beyond bucket cap")
        for k, v in buckets(aggs, "company").items():
            companies[k] = companies.get(k, 0) + v
        print(f"  {year}: {len(co['buckets'])} companies")
    (OUT / "ccdb_companies.json").write_text(json.dumps(companies, indent=1))
    print("distinct companies all-time:", len(companies))
