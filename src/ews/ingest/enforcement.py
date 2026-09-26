"""CFPB enforcement listing/detail scraper ported from the feasibility spike."""

import argparse
import json
import re
import time
from pathlib import Path

import requests
from bs4 import BeautifulSoup

BASE = "https://www.consumerfinance.gov"
LISTING = f"{BASE}/enforcement/actions/"
OUT = Path("data/raw")
HEADERS = {"User-Agent": "cdc26-hackathon-research (contact: calebhan2024@gmail.com)"}
DOLLAR_RE = re.compile(r"\$\s?[\d.,]+\s*(?:million|billion|thousand)?", re.I)


def fetch(url, **params):
    r = requests.get(url, params=params, headers=HEADERS, timeout=60)
    r.raise_for_status()
    return BeautifulSoup(r.text, "html.parser")


def scrape_listing():
    # Out-of-range ?page=N returns a populated page (not empty/404), so stop when a
    # page contributes no unseen slugs, and cross-check against the advertised count.
    actions, seen, page, expected = [], set(), 1, None
    while True:
        soup = fetch(LISTING, page=page)
        if expected is None:
            m = re.search(r"(\d+) filtered results", soup.get_text(" "))
            expected = int(m.group(1)) if m else None
        new = 0
        for c in soup.select("article.o-post-preview"):
            a = c.select_one(".o-post-preview__title a")
            slug = a["href"].rstrip("/").split("/")[-1]
            if slug in seen:
                continue
            seen.add(slug)
            new += 1
            t = c.select_one("time")
            desc = c.select_one(".o-post-preview__description")
            actions.append(
                {
                    "name": a.get_text(strip=True),
                    "url": BASE + a["href"],
                    "slug": slug,
                    "date_filed": t["datetime"][:10] if t else None,
                    "summary_short": desc.get_text(" ", strip=True) if desc else None,
                }
            )
        if new == 0 or (expected and len(actions) >= expected):
            break
        page += 1
        time.sleep(1)  # be polite; no documented rate limit for HTML pages
    if expected and len(actions) != expected:
        print(f"WARNING: scraped {len(actions)} actions but listing reports {expected}")
    return actions


def scrape_detail(url):
    soup = fetch(url)
    main = soup.find("main")
    meta = {}
    for box in soup.select(".m-related-metadata__item-container"):
        key = box.find("h3").get_text(strip=True)
        tags = [s.get_text(strip=True) for s in box.select(".a-tag-topic__text")]
        if tags:
            meta[key] = tags
        else:
            val = box.find(["p", "div", "ul"])
            meta[key] = val.get_text(" ", strip=True) if val else None
    # Summary is the rich-text block(s) before "Related documents"
    body = main.get_text("\n", strip=True)
    summary = body.split("Related documents")[0].split("\n", 3)[-1].strip()
    return {
        "name_h1": main.find("h1").get_text(strip=True),
        "forum": meta.get("Forum"),
        "docket_number": meta.get("Docket number"),
        "initial_filing_date": meta.get("Initial filing date"),
        "status": meta.get("Status", "").replace("See status definitions", "").strip()
        or None,
        "products": meta.get("Products"),
        "summary": summary,
        "dollar_mentions": DOLLAR_RE.findall(summary),
        "document_links": [
            BASE + a["href"] if a["href"].startswith("/") else a["href"]
            for a in main.select("a[href$='.pdf']")
        ],
    }


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--details", type=int, default=20)
    args = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    listing = scrape_listing()
    (OUT / "enforcement_listing.json").write_text(json.dumps(listing, indent=1))
    print(
        f"listing: {len(listing)} actions, {listing[-1]['date_filed']} .. {listing[0]['date_filed']}"
    )
    details = []
    for a in listing[: args.details]:
        details.append({**a, **scrape_detail(a["url"])})
        time.sleep(1)
    (OUT / "enforcement_details.json").write_text(json.dumps(details, indent=1))
    print(f"details: {len(details)}")
