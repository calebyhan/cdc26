"""Validate reviewed enforcement references, stage events, and report distinct counts."""

import csv
import hashlib
import json
from pathlib import Path

import duckdb

REFERENCE = Path(__file__).resolve().parents[3] / "data/reference"


def summary_hash(action):
    return hashlib.sha256(action["summary"].encode()).hexdigest()


def party_caption(action):
    # Listing cards truncate long captions; detail headings occasionally omit parties.
    # Preserve the fuller available caption, reviewed in the party reference.
    return max([action["name"], action["name_h1"]], key=len)


def read_csv(path):
    with path.open(newline="") as source:
        return list(csv.DictReader(source))


def unique_index(rows, key):
    index = {row[key]: row for row in rows}
    if len(index) != len(rows):
        raise ValueError(f"Duplicate {key} reference rows")
    return index


def validate(actions, reference=REFERENCE):
    labels = unique_index(read_csv(reference / "enforcement_labels.csv"), "action_id")
    action_index = unique_index(actions, "action_id")
    if labels.keys() != action_index.keys():
        raise ValueError("Every scraped action needs exactly one reviewed action label")
    crosswalk = unique_index(
        read_csv(reference / "enforcement_product_crosswalk.csv"), "enforcement_product"
    )
    for row in crosswalk.values():
        targets = json.loads(row["ccdb_products_json"])
        if (
            row["mapping_type"] not in {"product_family", "contextual", "context_only"}
            or not isinstance(targets, list)
            or any(not isinstance(p, str) or not p for p in targets)
            or (not targets and row["mapping_type"] != "context_only")
            or not row["note"]
        ):
            raise ValueError("Invalid enforcement product mapping")
    products = {p for action in actions for p in action["products"]}
    if products - crosswalk.keys():
        raise ValueError(
            f"Unmapped enforcement products: {products - crosswalk.keys()}"
        )
    parties = read_csv(reference / "enforcement_parties.csv")
    keys = set()
    for row in parties:
        key = (row["action_id"], int(row["party_index"]))
        if key in keys or row["action_id"] not in action_index:
            raise ValueError("Duplicate or unknown action-party reference")
        keys.add(key)
        if row["party_type"] not in {"company", "individual", "non_entity"}:
            raise ValueError("Unreviewed party type")
        if not row["party_raw"] or not row["reviewed_by"] or not row["reviewed_on"]:
            raise ValueError("Missing party review provenance")
        if (
            row["caption_sha256"]
            != hashlib.sha256(
                party_caption(action_index[row["action_id"]]).encode()
            ).hexdigest()
        ):
            raise ValueError(f"Caption changed; review parties: {row['action_id']}")
    if {r["action_id"] for r in parties} != action_index.keys():
        raise ValueError("Every action needs reviewed party rows")
    for action in actions:
        label = labels[action["action_id"]]
        if label["mortgage_related"] not in {"true", "false"}:
            raise ValueError("Unreviewed mortgage-related label")
        if not all(label[k] for k in ["rationale", "reviewed_by", "reviewed_on"]):
            raise ValueError("Missing action review provenance")
        if label["summary_sha256"] != summary_hash(action):
            raise ValueError(f"Summary changed; review label: {action['action_id']}")
        if label["date_filed"] != action["date_filed"] or json.loads(
            label["products_json"]
        ) != sorted(set(action["products"])):
            raise ValueError(
                f"Date/products changed; review label: {action['action_id']}"
            )
    return labels, parties


def event_counts(events, party_rows):
    results = {
        "all_actions": len(events),
        "all_mortgage_actions": sum(e["mortgage_related"] for e in events),
        "party_rows": len(party_rows),
    }
    for name, end in [("primary", "2024-12-31"), ("secondary", "2025-08-31")]:
        selected = [
            e
            for e in events
            if e["mortgage_related"] and "2014-01-01" <= e["date_filed"] <= end
        ]
        ids = {e["action_id"] for e in selected}
        companies = {r["action_id"] for r in party_rows if r["party_type"] == "company"}
        results[name] = {
            "start": "2014-01-01",
            "end": end,
            "mortgage_actions": len(selected),
            "with_named_company": len(ids & companies),
            "without_named_company": len(ids - companies),
            "status_counts": {
                s: sum(e["status"] == s for e in selected)
                for s in sorted({e["status"] for e in selected})
            },
        }
    return results


def build(actions, data_dir, reference=REFERENCE):
    labels, parties = validate(actions, reference)
    events, party_rows = [], []
    for action in actions:
        label = labels[action["action_id"]]
        events.append(
            {
                **action,
                "mortgage_related": label["mortgage_related"] == "true",
                "label_rationale": label["rationale"],
                "label_reviewed_by": label["reviewed_by"],
                "label_reviewed_on": label["reviewed_on"],
            }
        )
    index = {e["action_id"]: e for e in events}
    for party in parties:
        party_rows.append(
            {
                **index[party["action_id"]],
                **party,
                "party_index": int(party["party_index"]),
                "is_company": party["party_type"] == "company",
            }
        )
    counts = event_counts(events, party_rows)
    staging = data_dir / "staging"
    staging.mkdir(parents=True, exist_ok=True)
    with duckdb.connect() as con:
        for table, rows in [
            ("enforcement_events", events),
            ("stg_enforcement", party_rows),
        ]:
            raw = staging / f"{table}.json.partial"
            raw.write_text(json.dumps(rows))
            con.execute(
                f"CREATE OR REPLACE TEMP TABLE {table} AS SELECT * FROM read_json(?, format='array', maximum_object_size=16777216)",
                [str(raw)],
            )
            con.execute(f"ALTER TABLE {table} ALTER date_filed TYPE DATE")
            con.execute(f"ALTER TABLE {table} ALTER initial_filing_date TYPE DATE")
            target = staging / f"{table}.parquet"
            temporary = target.with_suffix(".parquet.partial")
            con.execute(
                f"COPY {table} TO '{str(temporary.resolve()).replace(chr(39), chr(39)*2)}' (FORMAT PARQUET, COMPRESSION ZSTD)"
            )
            temporary.replace(target)
            raw.unlink()
            csv_target = staging / f"{table}.csv"
            con.execute(
                f"COPY {table} TO '{str(csv_target.resolve()).replace(chr(39), chr(39)*2)}' (HEADER, FORMAT CSV)"
            )
    with duckdb.connect(str(staging / "ews.duckdb")) as con:
        for table in ["enforcement_events", "stg_enforcement"]:
            path = str((staging / f"{table}.parquet").resolve()).replace("'", "''")
            con.execute(
                f"CREATE OR REPLACE VIEW {table} AS FROM read_parquet('{path}')"
            )
    (staging / "enforcement_counts.json").write_text(
        json.dumps(counts, indent=2) + "\n"
    )
    return counts
