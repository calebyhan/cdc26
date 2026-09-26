"""Archive complete FDIC identities/history and small modern HMDA identity files."""

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

BASE = "https://api.fdic.gov/banks"
FIELDS = "NAME,CERT,FED_RSSD,ACTIVE,NAMEHCR,RSSDHCR,DATEUPDT,ESTYMD,INSDATE"


class IdentityArchive:
    def __init__(self, root, offline=False, refresh=False):
        self.root = Path(root)
        self.offline, self.refresh = offline, refresh
        self.session = requests.Session()
        self.session.mount(
            "https://",
            HTTPAdapter(
                max_retries=Retry(
                    total=4,
                    backoff_factor=1,
                    status_forcelist=[429, 500, 502, 503, 504],
                )
            ),
        )

    def fetch(self, relative, url, params=None):
        path = self.root / relative
        meta_path = path.with_name(path.name + ".meta.json")
        if path.exists() and not self.refresh:
            meta = json.loads(meta_path.read_text())
            body = path.read_bytes()
            if hashlib.sha256(body).hexdigest() != meta["sha256"]:
                raise ValueError(f"Identity archive checksum mismatch: {path}")
            return body
        if self.offline:
            raise FileNotFoundError(f"Missing identity archive: {path}")
        response = self.session.get(url, params=params, timeout=90)
        response.raise_for_status()
        body = response.content
        if relative.endswith(".json"):
            if "json" not in response.headers.get("Content-Type", ""):
                raise ValueError(f"Expected JSON: {response.url}")
            response.json()
        elif not body.startswith(b"PK"):
            raise ValueError(f"Expected ZIP: {response.url}")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(body)
        meta_path.write_text(
            json.dumps(
                {
                    "url": response.url,
                    "retrieved_at": datetime.now(timezone.utc).isoformat(),
                    "sha256": hashlib.sha256(body).hexdigest(),
                    "last_modified": response.headers.get("Last-Modified"),
                    "content_type": response.headers.get("Content-Type"),
                },
                indent=2,
            )
            + "\n"
        )
        return body

    def fdic(self, endpoint, filters="", fields=None):
        rows, total, index, offset = [], None, None, 0
        while total is None or offset < total:
            params = {
                "limit": 10000,
                "offset": offset,
                "filters": filters,
                "sort_by": "CERT" if endpoint == "institutions" else "EFFDATE",
                "sort_order": "ASC",
            }
            if fields:
                params["fields"] = fields
            key = hashlib.sha256(
                json.dumps(params, sort_keys=True).encode()
            ).hexdigest()[:16]
            payload = json.loads(
                self.fetch(f"fdic/{endpoint}-{key}.json", f"{BASE}/{endpoint}", params)
            )
            current_total = payload["meta"]["total"]
            current_index = payload["meta"]["index"]["name"]
            if total is not None and (total != current_total or index != current_index):
                raise ValueError("FDIC snapshot changed during pagination")
            total, index = current_total, current_index
            page = [r["data"] for r in payload["data"]]
            if not page and offset < total:
                raise ValueError("Incomplete FDIC pagination")
            rows.extend(page)
            offset += len(page)
        if len(rows) != total:
            raise ValueError("FDIC count mismatch")
        if endpoint == "institutions" and len({r["CERT"] for r in rows}) != total:
            raise ValueError("Duplicate CERT in FDIC roster")
        if endpoint == "history" and len({r["ID"] for r in rows}) != total:
            raise ValueError("Duplicate ID in FDIC history")
        return rows

    def hmda(self, year, kind):
        url = f"https://files.ffiec.cfpb.gov/static-data/snapshot/{year}/{year}_public_{kind}_csv.zip"
        return self.fetch(f"identity_hmda/{year}_{kind}.zip", url)
