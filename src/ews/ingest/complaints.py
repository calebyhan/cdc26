"""Bulk CSV → all-product Parquet → typed mortgage staging; atomic daily upserts."""

import argparse
import fcntl
import json
import shutil
import time
import zipfile
from contextlib import contextmanager
from datetime import date, timedelta
from pathlib import Path

import duckdb
import requests

from ews.ingest.ccdb import iter_all

BULK_URL = "https://files.consumerfinance.gov/ccdb/complaints.csv.zip"
HEADERS = {
    "Date received": "date_received",
    "Product": "product",
    "Sub-product": "sub_product",
    "Issue": "issue",
    "Sub-issue": "sub_issue",
    "Company public response": "company_public_response",
    "Company": "company",
    "State": "state",
    "ZIP code": "zip_code",
    "Tags": "tags",
    "Submitted via": "submitted_via",
    "Date sent to company": "date_sent_to_company",
    "Company response to consumer": "company_response",
    "Timely response?": "timely",
    "Complaint ID": "complaint_id",
}
REFERENCE = Path(__file__).resolve().parents[3] / "data/reference"


def sql_path(path):
    return "'" + str(Path(path).resolve()).replace("'", "''") + "'"


@contextmanager
def pipeline_lock(data_dir):
    data_dir.mkdir(parents=True, exist_ok=True)
    with (data_dir / ".complaints.lock").open("w") as lock:
        # A second writer must not silently overwrite another run's updates.
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield


def download_bulk(csv_path):
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    archive = csv_path.with_suffix(".csv.zip")
    partial = archive.with_suffix(".zip.partial")
    with requests.get(BULK_URL, stream=True, timeout=(30, 180)) as response:
        response.raise_for_status()
        with partial.open("wb") as output:
            for chunk in response.iter_content(1024 * 1024):
                output.write(chunk)
    partial.replace(archive)
    with zipfile.ZipFile(archive) as zipped:
        with zipped.open("complaints.csv") as source:
            with csv_path.with_suffix(".csv.partial").open("wb") as output:
                shutil.copyfileobj(source, output)
    csv_path.with_suffix(".csv.partial").replace(csv_path)


def connection():
    con = duckdb.connect()
    con.execute("SET memory_limit='2GB'")
    con.execute("SET threads=4")
    con.execute("SET TimeZone='UTC'")
    return con


def enrich(con, source, reference=REFERENCE):
    for name, key in [("issue", "issue"), ("response", "company_response")]:
        con.execute(
            f"CREATE OR REPLACE TEMP TABLE {name}_map AS SELECT * FROM "
            f"read_csv({sql_path(reference / (name + '_crosswalk.csv'))}, header=true)"
        )
        if con.execute(
            f"SELECT EXISTS (SELECT 1 FROM {name}_map GROUP BY {key} HAVING count(*) > 1)"
        ).fetchone()[0]:
            raise ValueError(f"Duplicate keys in {name} crosswalk")
        unknown = con.execute(
            f"SELECT DISTINCT s.{key} FROM {source} s LEFT JOIN {name}_map m "
            f"ON s.{key} IS NOT DISTINCT FROM m.{key} WHERE m.{name}_std IS NULL"
        ).fetchall()
        if unknown:
            raise ValueError(f"Unmapped {name} labels: {unknown}")
    con.execute(
        f"""CREATE OR REPLACE TEMP TABLE incoming AS
        SELECT s.*, i.issue_std, r.response_std,
               i.severity_tier::SMALLINT AS severity_tier,
               r.response_severity_tier::SMALLINT AS response_severity_tier,
               r.response_metrics_eligible::BOOLEAN AS response_metrics_eligible,
               current_timestamp::TIMESTAMP AS ingested_at
        FROM {source} s JOIN issue_map i USING (issue)
        JOIN response_map r ON s.company_response IS NOT DISTINCT FROM r.company_response"""
    )
    invalid = con.execute("""SELECT count(*) - count(DISTINCT complaint_id)
             + count(*) FILTER (WHERE date_received IS NULL OR company IS NULL)
           FROM incoming""").fetchone()[0]
    if invalid:
        raise ValueError("Null required fields or duplicate complaint IDs")


def typed_projection(csv=False):
    expressions = []
    for header, key in HEADERS.items():
        column = f'"{header}"' if csv else f'"{key}"'
        if key in ("date_received", "date_sent_to_company"):
            # API timestamps include times; bulk exports have date-only strings.
            expression = f"CAST(nullif(substr({column}, 1, 10), '') AS DATE)"
        elif key == "complaint_id":
            expression = f"CAST({column} AS BIGINT)"
        else:
            expression = f"nullif({column}, '')"
        expressions.append(f'{expression} AS "{key}"')
    return ", ".join(expressions)


def publish(con, query, data_dir):
    staging = data_dir / "staging"
    staging.mkdir(parents=True, exist_ok=True)
    target = staging / "stg_complaints.parquet"
    temporary = target.with_suffix(".parquet.partial")
    con.execute(
        f"COPY ({query}) TO {sql_path(temporary)} (FORMAT PARQUET, COMPRESSION ZSTD)"
    )
    temporary.replace(target)
    # DuckDB exposes the Parquet table as a view: no divergent second data copy.
    with duckdb.connect(str(staging / "ews.duckdb")) as db:
        db.execute(
            "CREATE OR REPLACE VIEW stg_complaints AS SELECT * FROM "
            f"read_parquet({sql_path(target)})"
        )
    return con.execute(
        f"SELECT count(*) FROM read_parquet({sql_path(target)})"
    ).fetchone()[0]


def ingest(csv_path, data_dir, reference=REFERENCE):
    with pipeline_lock(data_dir):
        if not csv_path.exists():
            download_bulk(csv_path)
        parquet = data_dir / "staging/complaints_all.parquet"
        parquet.parent.mkdir(parents=True, exist_ok=True)
        with connection() as con:
            # Re-convert on every ingest: this is a genuine rebuild from the raw CSV.
            temporary = parquet.with_suffix(".parquet.partial")
            con.execute(
                f"COPY (SELECT {typed_projection(csv=True)} FROM "
                f"read_csv({sql_path(csv_path)}, header=true, all_varchar=true)) "
                f"TO {sql_path(temporary)} (FORMAT PARQUET, COMPRESSION ZSTD)"
            )
            temporary.replace(parquet)
            con.execute(
                "CREATE TEMP TABLE mortgage AS SELECT * FROM "
                f"read_parquet({sql_path(parquet)}) WHERE product='Mortgage'"
            )
            enrich(con, "mortgage", reference)
            return {"staging_rows": publish(con, "SELECT * FROM incoming", data_dir)}


def delta(data_dir, reference=REFERENCE, today=None, iterator=iter_all):
    today = today or date.today()
    with pipeline_lock(data_dir):
        target = data_dir / "staging/stg_complaints.parquet"
        if not target.exists():
            raise FileNotFoundError("Run make ingest before make delta")
        with connection() as con:
            con.execute(
                f"CREATE TEMP TABLE existing AS FROM read_parquet({sql_path(target)})"
            )
            latest = con.execute("SELECT max(date_received) FROM existing").fetchone()[
                0
            ]
            # Include missed days after downtime, plus the trailing 30-day overlap.
            start = min(latest or today, today) - timedelta(days=29)
            raw_dir = data_dir / "raw/deltas"
            raw_dir.mkdir(parents=True, exist_ok=True)
            raw = raw_dir / f"{time.time_ns()}.jsonl"
            n = 0
            with raw.with_suffix(".partial").open("w") as output:
                for row in iterator(
                    product="Mortgage",
                    date_received_min=start.isoformat(),
                    date_received_max=today.isoformat(),
                ):
                    if row.get("product") != "Mortgage":
                        raise ValueError(
                            "CCDB returned a non-mortgage row despite filter"
                        )
                    if (
                        not start.isoformat()
                        <= row["date_received"][:10]
                        <= today.isoformat()
                    ):
                        raise ValueError(
                            "CCDB returned a row outside the requested dates"
                        )
                    output.write(
                        json.dumps({key: row.get(key) for key in HEADERS.values()})
                        + "\n"
                    )
                    n += 1
            raw.with_suffix(".partial").replace(raw)
            if n:
                columns = ", ".join(f"'{key}': 'VARCHAR'" for key in HEADERS.values())
                con.execute(
                    f"CREATE TEMP TABLE mortgage AS SELECT {typed_projection()} FROM "
                    f"read_json({sql_path(raw)}, format='newline_delimited', columns={{{columns}}})"
                )
                enrich(con, "mortgage", reference)
                # Preserve rows (and ingestion timestamps) when the payload is unchanged.
                con.execute("""CREATE TEMP TABLE changed AS
                    SELECT * EXCLUDE (ingested_at) FROM incoming
                    EXCEPT SELECT * EXCLUDE (ingested_at) FROM existing""")
                count = publish(
                    con,
                    """
                    SELECT e.* FROM existing e
                    WHERE NOT EXISTS (SELECT 1 FROM changed c WHERE c.complaint_id=e.complaint_id)
                    UNION ALL SELECT i.* FROM incoming i
                    JOIN changed c ON i.complaint_id=c.complaint_id
                """,
                    data_dir,
                )
                changed = con.execute("SELECT count(*) FROM changed").fetchone()[0]
            else:
                count = con.execute("SELECT count(*) FROM existing").fetchone()[0]
                changed = 0
            return {
                "from": start.isoformat(),
                "through": today.isoformat(),
                "fetched": n,
                "changed": changed,
                "staging_rows": count,
            }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["ingest", "delta"])
    parser.add_argument("--csv", type=Path, default=Path("data/raw/complaints.csv"))
    parser.add_argument("--data-dir", type=Path, default=Path("data"))
    args = parser.parse_args()
    start = time.monotonic()
    result = (
        ingest(args.csv, args.data_dir)
        if args.command == "ingest"
        else delta(args.data_dir)
    )
    print(json.dumps({**result, "elapsed_seconds": round(time.monotonic() - start, 2)}))


if __name__ == "__main__":
    main()
