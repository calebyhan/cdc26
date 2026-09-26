"""CCDB JSON search, aggregation helpers, and search_after pagination."""

import time
from pathlib import Path

import requests

API = "https://www.consumerfinance.gov/data-research/consumer-complaints/search/api/v1/"
OUT = Path("data/raw")
MIN_INTERVAL = 3.1  # stay under 20 req/min


def search(**params):
    r = requests.get(API, params=params, timeout=180)
    r.raise_for_status()
    if (
        r.headers.get("content-type", "").split(";", 1)[0].strip().lower()
        != "application/json"
    ):
        raise RuntimeError(
            f"Non-JSON response from {r.url} - check trailing slash / params"
        )
    time.sleep(MIN_INTERVAL)
    return r.json()


def sample_rows(n=500, **filters):
    d = search(size=n, sort="created_date_desc", no_aggs="true", **filters)
    return [h["_source"] for h in d["hits"]["hits"]]


def iter_all(page_size=1000, **filters):
    """Deep pagination via search_after (frm is capped at 10,000)."""
    after = None
    seen = set()
    while True:
        params = dict(
            size=page_size, sort="created_date_desc", no_aggs="true", **filters
        )
        if after:
            params["search_after"] = after
        hits = search(**params)["hits"]["hits"]
        if not hits:
            return
        s = hits[-1]["sort"]
        cursor = f"{s[0]}_{s[1]}"
        if cursor in seen:
            raise RuntimeError("CCDB repeated search_after cursor")
        seen.add(cursor)
        yield from (h["_source"] for h in hits)
        after = cursor


def aggregations(**filters):
    """size=0 returns only aggregations: product, issue, company, state, tags, timely, ..."""
    return search(size=0, **filters)["aggregations"]


def buckets(aggs, field):
    return {b["key"]: b["doc_count"] for b in aggs[field][field]["buckets"]}
