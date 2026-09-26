"""Reproducible HMDA size/schema spike; downloads panels, never the full LAR."""

import csv
import io
import json
import re
import zipfile
from datetime import datetime, timezone
from pathlib import Path

import requests

SOURCE = "https://raw.githubusercontent.com/cfpb/hmda-frontend/master/src/"


def profile_panel(content, year):
    if year < 2018:
        rows = list(csv.reader(io.StringIO(content)))
        return {
            "rows": len(rows),
            "headerless": True,
            "column_count": len(rows[0]),
            "fields": [],
            "schema_url": "https://files.ffiec.cfpb.gov/static-data/snapshot/2017/2017_publicstatic_dataformat.pdf",
        }
    rows = list(csv.DictReader(io.StringIO(content)))
    examples = [
        r
        for r in rows
        if any(
            name in r["respondent_name"].upper()
            for name in [
                "ROCKET MORTGAGE",
                "QUICKEN LOANS",
                "UNITED WHOLESALE",
                "NATIONSTAR",
                "FREEDOM MORTGAGE",
            ]
        )
    ]
    groups = {}
    for code in sorted({r["other_lender_code"] for r in rows}):
        group = [r for r in rows if r["other_lender_code"] == code]
        groups[code] = {
            "rows": len(group),
            "with_rssd": sum(
                r["respondent_rssd"] not in ("", "-1", "0") for r in group
            ),
        }
    return {
        "fields": list(rows[0]),
        "rows": len(rows),
        "examples": examples,
        "rssd_by_other_lender_code": groups,
    }


def main():
    out = Path("data/raw/hmda")
    out.mkdir(parents=True, exist_ok=True)
    session = requests.Session()
    config = session.get(SOURCE + "common/constants/prod-config.json", timeout=60)
    config.raise_for_status()
    config = config.json()
    domain = config["fileServerDomain"]
    response = session.get(
        SOURCE + "data-publication/constants/snapshot-dataset.jsx", timeout=60
    )
    response.raise_for_status()
    manifest = response.text
    (out / "snapshot-dataset.jsx").write_text(manifest)
    results = []
    for match in re.finditer(
        r"  (20\d\d): \{(.*?)(?=\n  20\d\d: \{|\n\})", manifest, re.S
    ):
        year, block = match.groups()
        freeze = re.search(r"freezeDate: '([^']+)'", block).group(1)
        for kind in ["lar", "ts", "panel"]:
            path = f"/static-data/snapshot/{year}/{year}_public_{kind}_csv.zip"
            result = {"year": int(year), "kind": kind, "freeze_date": freeze}
            if path not in block:
                results.append({**result, "available": False})
                continue
            url = domain + path
            head = session.head(url, timeout=60)
            head.raise_for_status()
            result.update(
                url=url,
                available=True,
                zip_bytes=int(head.headers["Content-Length"]),
                last_modified=head.headers.get("Last-Modified"),
            )

            # HTTP ranges expose ZIP central-directory metadata without downloading GBs.
            class RemoteZip(io.RawIOBase):
                def __init__(self):
                    self.position = 0

                def seekable(self):
                    return True

                def seek(self, offset, whence=0):
                    self.position = (
                        0
                        if whence == 0
                        else self.position if whence == 1 else result["zip_bytes"]
                    ) + offset
                    return self.position

                def tell(self):
                    return self.position

                def read(self, size=-1):
                    end = (
                        result["zip_bytes"]
                        if size < 0
                        else min(self.position + size, result["zip_bytes"])
                    )
                    if end <= self.position:
                        return b""
                    r = session.get(
                        url,
                        headers={"Range": f"bytes={self.position}-{end-1}"},
                        timeout=60,
                        stream=True,
                    )
                    with r:
                        if r.status_code != 206:
                            raise RuntimeError(f"Server did not honor Range: {url}")
                        data = r.content
                    self.position = end
                    return data

            with zipfile.ZipFile(RemoteZip()) as archive:
                result["members"] = [
                    {"name": i.filename, "bytes": i.file_size}
                    for i in archive.infolist()
                ]
            if kind == "panel":
                r = session.get(url, timeout=60)
                r.raise_for_status()
                (out / f"{year}_panel.zip").write_bytes(r.content)
                with zipfile.ZipFile(io.BytesIO(r.content)) as archive:
                    name = next(n for n in archive.namelist() if n.endswith(".csv"))
                    content = archive.read(name).decode("utf-8-sig")
                result.update(profile_panel(content, int(year)))
            results.append(result)
            print(year, kind, result["zip_bytes"], flush=True)
            (out / "probe.json").write_text(
                json.dumps(
                    {
                        "checked_at": datetime.now(timezone.utc).isoformat(),
                        "files": results,
                    },
                    indent=2,
                )
            )
    (out / "probe.json").write_text(
        json.dumps(
            {"checked_at": datetime.now(timezone.utc).isoformat(), "files": results},
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
