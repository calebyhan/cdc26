"""Auditable CFPB enforcement scrape and labeled action × party staging."""

import argparse
import hashlib
import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

BASE = "https://www.consumerfinance.gov"
LISTING = f"{BASE}/enforcement/actions/"
HEADERS = {"User-Agent": "cdc26-mortgage-ews-research (public enforcement archive)"}


class Archive:
    """Raw response bytes plus provenance; cached pages can be replayed offline."""

    def __init__(self, root, refresh=False, offline=False, interval=1.0):
        self.root = Path(root)
        self.refresh = refresh
        self.offline = offline
        self.interval = interval
        self.last_request = 0.0
        self.session = requests.Session()
        self.session.headers.update(HEADERS)
        self.session.mount(
            "https://",
            HTTPAdapter(
                max_retries=Retry(
                    total=4,
                    backoff_factor=1,
                    status_forcelist=[429, 500, 502, 503, 504],
                    allowed_methods=["GET"],
                    respect_retry_after_header=True,
                )
            ),
        )

    def fetch(self, url, relative, **params):
        path = self.root / relative
        if path.exists() and not self.refresh:
            content = path.read_bytes()
            provenance = json.loads(path.with_suffix(".json").read_text())
            if hashlib.sha256(content).hexdigest() != provenance["sha256"]:
                raise ValueError(f"Archived HTML checksum mismatch: {path}")
            return BeautifulSoup(content, "html.parser")
        if self.offline:
            raise FileNotFoundError(f"Missing archived page: {path}")
        time.sleep(max(0, self.interval - (time.monotonic() - self.last_request)))
        response = self.session.get(url, params=params, timeout=(20, 90))
        self.last_request = time.monotonic()
        response.raise_for_status()
        if (
            response.headers.get("Content-Type", "").split(";", 1)[0].lower()
            != "text/html"
        ):
            raise ValueError(f"Expected HTML at {response.url}")
        soup = BeautifulSoup(response.content, "html.parser")
        if soup.find("main") is None:
            raise ValueError(f"Missing main content at {response.url}")
        path.parent.mkdir(parents=True, exist_ok=True)
        temp = path.with_suffix(".html.partial")
        temp.write_bytes(response.content)
        temp.replace(path)
        path.with_suffix(".json").write_text(
            json.dumps(
                {
                    "url": response.url,
                    "retrieved_at": datetime.now(timezone.utc).isoformat(),
                    "sha256": hashlib.sha256(response.content).hexdigest(),
                    "status_code": response.status_code,
                    "content_type": response.headers.get("Content-Type"),
                    "last_modified": response.headers.get("Last-Modified"),
                },
                indent=2,
            )
            + "\n"
        )
        return soup


def parse_listing(soup):
    match = re.search(r"([\d,]+)\s+filtered results", soup.get_text(" ", strip=True))
    if not match:
        raise ValueError("Listing has no advertised filtered-results count")
    expected = int(match.group(1).replace(",", ""))
    actions = []
    for card in soup.select("article.o-post-preview"):
        anchor = card.select_one(".o-post-preview__title a")
        filed = card.select_one("time[datetime]")
        if not anchor or not filed:
            raise ValueError("Incomplete enforcement listing card")
        url = urljoin(BASE, anchor["href"])
        slug = url.rstrip("/").split("/")[-1]
        desc = card.select_one(".o-post-preview__description")
        actions.append(
            {
                "action_id": slug,
                "name": anchor.get_text(" ", strip=True),
                "url": url,
                "slug": slug,
                "date_filed": filed["datetime"][:10],
                "summary_short": desc.get_text(" ", strip=True) if desc else "",
            }
        )
    if expected and not actions:
        raise ValueError("Advertised results but no enforcement cards")
    return expected, actions


def scrape_listing(archive, expected_total=386, max_pages=100):
    actions, seen, expected = [], set(), None
    for page in range(1, max_pages + 1):
        soup = archive.fetch(LISTING, f"listing/page-{page:03d}.html", page=page)
        advertised, rows = parse_listing(soup)
        if expected is None:
            expected = advertised
            if expected_total is not None and expected != expected_total:
                raise ValueError(
                    f"Listing advertises {expected}; expected snapshot {expected_total}"
                )
        elif advertised != expected:
            raise ValueError("Advertised listing total changed during pagination")
        new = [r for r in rows if r["slug"] not in seen]
        for row in new:
            if row["slug"] not in seen:
                actions.append(row)
                seen.add(row["slug"])
        # Out-of-range pages repeat populated results; never rely on empty pages.
        if not new or len(actions) >= expected:
            break
    else:
        raise ValueError(f"Exceeded pagination safety bound ({max_pages})")
    if len(actions) != expected:
        raise ValueError(
            f"Incomplete listing: {len(actions)} unique actions vs {expected} advertised"
        )
    return actions


def parse_detail(soup, url):
    main = soup.find("main")
    title = main.find("h1") if main else None
    blocks = main.select(".m-full-width-text") if main else []
    if not title or not blocks:
        raise ValueError(f"Missing enforcement detail content: {url}")
    # Exclude documents, newsroom links, metadata, and changing related-post widgets.
    texts = []
    for block in blocks:
        body = block.get_text(" ", strip=True)
        texts.append(
            re.split(
                r"Related documents|Important documents|Press release|Case docket",
                body,
                maxsplit=1,
                flags=re.I,
            )[0]
        )
    summary = " ".join(texts).strip()
    if not summary:
        raise ValueError(f"Empty enforcement summary: {url}")
    meta, initial_date = {}, None
    for box in main.select(".m-related-metadata__item-container"):
        heading = box.find("h3")
        if not heading:
            continue
        key = heading.get_text(" ", strip=True)
        tags = [s.get_text(" ", strip=True) for s in box.select(".a-tag-topic__text")]
        if key == "Products":
            meta[key] = tags
        else:
            text = box.get_text(" ", strip=True)
            meta[key] = (
                text.removeprefix(key).replace("See status definitions", "").strip()
            )
        if key == "Initial filing date":
            filed = box.find("time", datetime=True)
            initial_date = filed["datetime"][:10] if filed else None
    if (
        not all(meta.get(k) for k in ["Products", "Status", "Forum"])
        or not initial_date
    ):
        raise ValueError(
            f"Missing product tags, status, forum or initial filing date: {url}"
        )
    return {
        "name_h1": title.get_text(" ", strip=True),
        "forum": meta.get("Forum"),
        "docket_number": meta.get("Docket number"),
        "initial_filing_date": initial_date,
        "status": meta.get("Status"),
        "products": meta["Products"],
        "summary": summary,
        "document_links": list(
            dict.fromkeys(
                urljoin(url, a["href"])
                for a in main.select("a[href]")
                if ".pdf" in a["href"].lower()
            )
        ),
    }


def scrape(archive, expected_total=386):
    listing = scrape_listing(archive, expected_total)
    (archive.root / "listing.json").write_text(json.dumps(listing, indent=2) + "\n")
    details = []
    for n, action in enumerate(listing, 1):
        soup = archive.fetch(action["url"], f"details/{action['slug']}.html")
        row = {**action, **parse_detail(soup, action["url"])}
        row["raw_html"] = str(archive.root / f"details/{action['slug']}.html")
        row["raw_sha256"] = hashlib.sha256(
            (archive.root / f"details/{action['slug']}.html").read_bytes()
        ).hexdigest()
        if row["date_filed"] != row["initial_filing_date"]:
            raise ValueError(f"Listing/detail date disagreement for {row['slug']}")
        details.append(row)
        if n % 20 == 0 or n == len(listing):
            print(f"enforcement details: {n}/{len(listing)}", flush=True)
    target = archive.root / "actions.json"
    temp = target.with_suffix(".json.partial")
    temp.write_text(json.dumps(details, indent=2) + "\n")
    temp.replace(target)
    return details


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=Path("data"))
    parser.add_argument("--refresh", action="store_true")
    parser.add_argument("--offline", action="store_true")
    parser.add_argument("--scrape-only", action="store_true")
    parser.add_argument("--expected-total", type=int, default=386)
    args = parser.parse_args()
    if args.refresh and args.offline:
        parser.error("--refresh and --offline are mutually exclusive")
    archive = Archive(args.data_dir / "raw/enforcement", args.refresh, args.offline)
    actions = scrape(archive, args.expected_total)
    if not args.scrape_only:
        from ews.ingest.enforcement_labels import build

        print(json.dumps(build(actions, args.data_dir), indent=2))


if __name__ == "__main__":
    main()
