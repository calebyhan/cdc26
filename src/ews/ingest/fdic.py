"""FDIC BankFind institution fetches ported from the feasibility spike."""

import json
from pathlib import Path

import requests

BASE = "https://api.fdic.gov/banks"
OUT = Path("data/raw")
FIELDS = (
    "NAME,CERT,FED_RSSD,ASSET,DEP,EQ,REPDTE,ACTIVE,CITY,STALP,NAMEHCR,RSSDHCR,WEBADDR"
)
TARGETS = [
    "WELLS FARGO",
    "JPMORGAN CHASE",
    "BANK OF AMERICA",
    "CITIBANK",
    "CAPITAL ONE",
    "U.S. BANK",
    "TRUIST",
    "PNC",
    "DISCOVER",
    "SYNCHRONY",
    "NAVY FEDERAL",
]


def institutions(**params):
    r = requests.get(
        f"{BASE}/institutions", params={"fields": FIELDS, **params}, timeout=60
    )
    r.raise_for_status()
    print(
        f"  ratelimit remaining={r.headers.get('x-ratelimit-remaining')}/{r.headers.get('x-ratelimit-limit')}"
    )
    return r.json()


def top_match(name):
    """`filters` is exact-match on keyword fields; `search` is the fuzzy name search."""
    res = institutions(
        search=f"NAME:{name}",
        filters="ACTIVE:1",
        sort_by="ASSET",
        sort_order="DESC",
        limit=3,
    )
    return [row["data"] for row in res["data"]]


if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    targets = {}
    for t in TARGETS:
        targets[t] = top_match(t)
        best = targets[t][0] if targets[t] else None
        print(
            t,
            "->",
            best and (best["NAME"], best["CERT"], best["ASSET"], best["NAMEHCR"]),
        )
    (OUT / "fdic_targets.json").write_text(json.dumps(targets, indent=1))

    # Full active roster (~4.4k rows) fits in one call (limit max 10,000).
    allrows = institutions(
        filters="ACTIVE:1", limit=10000, sort_by="ASSET", sort_order="DESC"
    )
    rows = [r["data"] for r in allrows["data"]]
    print(
        "active institutions:",
        allrows["meta"]["total"],
        "returned:",
        len(rows),
        "index:",
        allrows["meta"]["index"],
    )
    (OUT / "fdic_active_institutions.json").write_text(json.dumps(rows))
