"""Archived FDIC financials and HMDA LAR → typed, version-aware staging.

Current downloads must not be backdated to the original period's release.
"""

import csv
import hashlib
import json
import shutil
import tempfile
import zipfile
from datetime import date, datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path

import requests

from ews.ingest.complaints import REFERENCE, connection, sql_path

FDIC_FIELDS = (
    "CERT,REPDTE,RSSDHCR,NAMEHCR,ASSET,DEP,EQ,LNRERES,LNLSGR,NCLNLS,"
    "ELNATQ,ELNLOSQ,OFFDOM"
)
RELEASES = {
    2018: "2019-08-30",
    2019: "2020-06-24",
    2020: "2021-06-17",
    2021: "2022-06-16",
    2022: "2023-06-29",
    2023: "2024-07-11",
    2024: "2025-07-07",
    2025: "2026-06-23",
}


def version_available(release, metadata):
    """Conservative: earliest scoring date supported for these exact bytes.

    Last-Modified is a version bound, NOT evidence of original public release.
    Without a version timestamp, use retrieval. The join itself is strict <.
    """
    stamp = metadata.get("last_modified")
    version = (
        parsedate_to_datetime(stamp).date()
        if stamp
        else datetime.fromisoformat(metadata["retrieved_at"]).date()
    )
    return max(date.fromisoformat(str(release)), version)


def _download_lar(archive, year):
    path = archive.root / "hmda_lar" / f"{year}.zip"
    meta_path = path.with_name(path.name + ".meta.json")
    if path.exists() and not archive.refresh:
        with path.open("rb") as source:
            digest = hashlib.file_digest(source, "sha256").hexdigest()
        if digest != json.loads(meta_path.read_text())["sha256"]:
            raise ValueError(f"LAR checksum mismatch: {path}")
        return path
    if archive.offline:
        raise FileNotFoundError(f"Missing HMDA LAR archive: {path}")
    url = f"https://files.ffiec.cfpb.gov/static-data/snapshot/{year}/{year}_public_lar_csv.zip"
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = path.with_suffix(".zip.partial")
    digest = hashlib.sha256()
    with archive.session.get(url, stream=True, timeout=(30, 180)) as response:
        response.raise_for_status()
        with partial.open("wb") as output:
            for chunk in response.iter_content(1024 * 1024):
                digest.update(chunk)
                output.write(chunk)
        meta = {
            "url": response.url,
            "retrieved_at": datetime.now(timezone.utc).isoformat(),
            "sha256": digest.hexdigest(),
            "last_modified": response.headers.get("Last-Modified"),
            "public_release": RELEASES[year],
        }
    with zipfile.ZipFile(partial) as zipped:
        if sum(n.filename.endswith(".csv") for n in zipped.infolist()) != 1:
            raise ValueError("Expected exactly one LAR CSV")
    partial.replace(path)
    meta_path.write_text(json.dumps(meta, indent=2) + "\n")
    return path


def download_lar(archive, year):
    for attempt in range(4):
        try:
            return _download_lar(archive, year)
        except (requests.RequestException, zipfile.BadZipFile):
            if attempt == 3:
                raise
            print(f"Retry HMDA {year} download ({attempt + 1}/3)", flush=True)


def stage_hmda_csv(con, path, year, available_from):
    """All reported dwelling/loan types; actions 1–5,7,8 are applications.

    Purchases (6) aren't applications or originations. Denial denominator is
    actions 1–3. Geography and refinance shares use originations only.
    """
    con.execute(f"""CREATE OR REPLACE TEMP TABLE lar AS
        SELECT lei::VARCHAR lei, try_cast(action_taken AS INTEGER) action_code,
          try_cast(loan_purpose AS INTEGER) purpose,
          nullif(trim(state_code), 'NA') state
        FROM read_csv({sql_path(path)}, header=true, all_varchar=true)
        WHERE lei IS NOT NULL""")
    con.execute("""CREATE OR REPLACE TEMP TABLE lar_states AS
        SELECT lei, state, count(*) n FROM lar WHERE action_code=1
        AND state IS NOT NULL AND length(state)=2 GROUP BY 1,2""")
    con.execute("""CREATE OR REPLACE TEMP TABLE lender AS
        SELECT lei, count(*) FILTER(WHERE action_code=1) originations,
          count(*) FILTER(WHERE action_code IN (1,2,3,4,5,7,8)) applications,
          count(*) FILTER(WHERE action_code=3) denials,
          count(*) FILTER(WHERE action_code IN (1,2,3)) decisions,
          count(*) FILTER(WHERE action_code=1 AND purpose IN (31,32)) refinances
        FROM lar GROUP BY lei""")
    con.execute(
        """CREATE OR REPLACE TEMP TABLE hmda_year AS
        SELECT l.*, ?::INTEGER AS year, ?::DATE AS available_from,
          denials::DOUBLE / nullif(decisions,0) denial_rate,
          refinances::DOUBLE / nullif(originations,0) refi_share,
          s.top_n::DOUBLE / nullif(s.total_n,0) top_state_share,
          coalesce(s.n_states,0)::INTEGER n_states
        FROM lender l LEFT JOIN (
          SELECT lei, max(n) top_n, sum(n) total_n, count(*) n_states
          FROM lar_states GROUP BY lei) s USING(lei)""",
        [year, available_from],
    )


def ingest_hmda(data_dir, archive, years=range(2018, 2026)):
    staging = data_dir / "staging"
    staging.mkdir(parents=True, exist_ok=True)
    con = connection()
    try:
        files = []
        for year in years:
            if year not in RELEASES:
                raise ValueError(
                    "LAR ingestion supports reviewed 2018–2025 LEI vintages"
                )
            path = download_lar(archive, year)
            metadata = json.loads(path.with_name(path.name + ".meta.json").read_text())
            available = version_available(RELEASES[year], metadata)
            print(f"HMDA {year}: aggregate LAR; available_from={available}", flush=True)
            # Expand only one vintage at a time; never retain multi-GB temporary CSVs.
            with tempfile.TemporaryDirectory(prefix="ews-lar-", dir=staging) as tmp:
                csv_path = Path(tmp) / "lar.csv"
                with zipfile.ZipFile(path) as zipped:
                    member = next(n for n in zipped.namelist() if n.endswith(".csv"))
                    with zipped.open(member) as source, csv_path.open("wb") as output:
                        shutil.copyfileobj(source, output, 1024 * 1024)
                stage_hmda_csv(con, csv_path, year, available)
                target = staging / f"hmda_{year}.parquet"
                con.sql("SELECT * FROM hmda_year ORDER BY lei").write_parquet(
                    str(target)
                )
                files.append(str(target))
        con.read_parquet(files).order("year,lei").write_parquet(
            str(staging / "stg_hmda_lender_year.parquet")
        )
    finally:
        con.close()


def ingest_fdic(data_dir, archive, reference=REFERENCE):
    entities = list(csv.DictReader((reference / "entity_manual.csv").open()))
    hcs = sorted(
        {e["rssdhcr"] for e in entities if e["type"] == "bank" and e["rssdhcr"]}
    )
    certs = sorted(
        {
            c
            for e in entities
            if e["type"] == "bank"
            for c in e["fdic_certs"].split(";")
            if c
        },
        key=int,
    )
    filters = f"(RSSDHCR:({' OR '.join(hcs)}) OR CERT:({' OR '.join(certs)})) AND REPDTE:[20110101 TO *]"
    rows, offset, total, index, timestamp = [], 0, None, None, None
    while total is None or offset < total:
        params = {
            "filters": filters,
            "fields": FDIC_FIELDS,
            "limit": 10000,
            "offset": offset,
            "sort_by": "CERT",
            "sort_order": "ASC",
        }
        key = hashlib.sha256(json.dumps(params, sort_keys=True).encode()).hexdigest()[
            :16
        ]
        payload = json.loads(
            archive.fetch(
                f"financials/{key}.json",
                "https://api.fdic.gov/banks/financials",
                params,
            )
        )
        meta = payload["meta"]
        if index and (index != meta["index"]["name"] or total != meta["total"]):
            raise ValueError("FDIC financial snapshot changed during pagination")
        index, total = meta["index"]["name"], meta["total"]
        timestamp = meta["index"]["createTimestamp"][:10]
        page = [r["data"] for r in payload["data"]]
        if not page and offset < total:
            raise ValueError("Incomplete financial pagination")
        rows.extend(page)
        offset += len(page)
    if len({(r["CERT"], r["REPDTE"]) for r in rows}) != total:
        raise ValueError("Duplicate CERT/quarter financial records")
    typed = []
    fields = [
        "ASSET",
        "DEP",
        "EQ",
        "LNRERES",
        "LNLSGR",
        "NCLNLS",
        "ELNATQ",
        "ELNLOSQ",
        "OFFDOM",
    ]
    for row in rows:
        period = datetime.strptime(row["REPDTE"], "%Y%m%d").date()
        nominal = period + timedelta(days=45)
        typed.append(
            {
                "cert": row["CERT"],
                "report_date": period.isoformat(),
                "rssdhcr": row.get("RSSDHCR") or "",
                "namehcr": row.get("NAMEHCR") or "",
                "nominal_release": nominal.isoformat(),
                "available_from": max(
                    nominal, date.fromisoformat(timestamp)
                ).isoformat(),
                "snapshot_version": timestamp,
                **{f.lower(): row.get(f) for f in fields},
            }
        )
    incoming = archive.fdic(
        "history",
        filters=f"(SUR_CERT:({' OR '.join(certs)}) OR ACQ_CERT:({' OR '.join(certs)})) "
        "AND CHANGECODE:(221 OR 222 OR 223 OR 224 OR 225) AND EFFDATE:[2011-01-01 TO *]",
    )
    staging = data_dir / "staging"
    staging.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=staging) as tmp:
        path = Path(tmp) / "financials.csv"
        with path.open("w") as output:
            writer = csv.DictWriter(output, fieldnames=list(typed[0]))
            writer.writeheader()
            writer.writerows(typed)
        con = connection()
        try:
            con.read_csv(str(path), all_varchar=True).project(
                "cert::INTEGER cert, report_date::DATE report_date, rssdhcr, namehcr, "
                "nominal_release::DATE nominal_release, available_from::DATE available_from, "
                "snapshot_version::DATE snapshot_version, "
                + ",".join(f"{f.lower()}::DOUBLE {f.lower()}" for f in fields)
            ).order("report_date,cert").write_parquet(
                str(staging / "stg_fdic_financials.parquet")
            )
            for name in ["institutions", "history"]:
                source = data_dir / "marts" / f"fdic_{name}.csv"
                if name == "history":
                    with source.open() as original:
                        reader = csv.DictReader(original)
                        fields = reader.fieldnames
                        history = list(reader)
                    history.extend(
                        {f: str(r.get(f) or "") for f in fields} for r in incoming
                    )
                    unique = {tuple(r[f] for f in fields): r for r in history}
                    source = Path(tmp) / "history.csv"
                    with source.open("w") as output:
                        writer = csv.DictWriter(output, fieldnames=fields)
                        writer.writeheader()
                        writer.writerows(unique.values())
                relation = con.read_csv(str(source), all_varchar=True)
                if name == "history":
                    relation = relation.project(
                        "* REPLACE (EFFDATE::TIMESTAMP::DATE AS EFFDATE, CERT::INTEGER AS CERT)"
                    )
                else:
                    relation = relation.project(
                        "* REPLACE (CERT::INTEGER AS CERT, ACTIVE::INTEGER AS ACTIVE)"
                    )
                relation.write_parquet(str(staging / f"stg_fdic_{name}.parquet"))
        finally:
            con.close()
    print(f"FDIC: {total} bank-quarter records; version={timestamp}", flush=True)
