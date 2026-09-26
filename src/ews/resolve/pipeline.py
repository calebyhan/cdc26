"""Reviewed identities, dated aliases, candidate queue, and reproducible crosswalk."""

import argparse
import csv
import hashlib
import io
import json
import tempfile
import zipfile
from collections import defaultdict
from datetime import date
from pathlib import Path

import duckdb

from ews.ingest.identity_sources import FIELDS, IdentityArchive
from ews.resolve.matching import candidates, normalize

REVIEW_FIELDS = [
    "source",
    "raw_string",
    "entity_id",
    "valid_from",
    "valid_to",
    "decision",
    "reviewed_by",
    "reviewed_on",
    "evidence",
    "review_note",
]


def read_csv(path):
    with Path(path).open(newline="", encoding="utf-8") as stream:
        return list(csv.DictReader(stream))


def write_csv(path, rows, fields):
    with Path(path).open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def identifier(value):
    """Identifiers are strings; blank/-1/zero are missing, never join keys."""
    value = str(value or "").strip()
    return "" if value in {"-1", "0", "None"} else value


def in_period(row, when):
    when = str(when)[:10]
    return (not row.get("valid_from") or row["valid_from"] <= when) and (
        not row.get("valid_to") or when <= row["valid_to"]
    )


def validate_reviews(entities, aliases, relationships):
    entity_map = {row["entity_id"]: row for row in entities}
    if len(entity_map) != len(entities):
        raise ValueError("Duplicate entity_id")
    for row in entities:
        if row["type"] not in {
            "bank",
            "credit_union",
            "nonbank_originator",
            "nonbank_servicer",
            "bureau",
            "other",
        }:
            raise ValueError("Unknown entity type")
        if not all(
            row.get(f)
            for f in [
                "entity_id",
                "display_name",
                "reviewed_by",
                "reviewed_on",
                "evidence",
            ]
        ):
            raise ValueError("Missing entity review provenance")
        if (
            row.get("successor_entity_id")
            and row["successor_entity_id"] not in entity_map
        ):
            raise ValueError("Unknown successor entity")
    grouped = defaultdict(list)
    for row in aliases:
        if row["decision"] not in {"accept", "unresolved", "reject"}:
            raise ValueError("Unknown review decision")
        for field in [
            "source",
            "raw_string",
            "reviewed_by",
            "reviewed_on",
            "evidence",
            "review_note",
        ]:
            if not row.get(field):
                raise ValueError(f"Missing review provenance: {field}")
        date.fromisoformat(row["reviewed_on"])
        for field in ["valid_from", "valid_to"]:
            if row[field]:
                date.fromisoformat(row[field])
        if (
            row["valid_from"]
            and row["valid_to"]
            and row["valid_from"] > row["valid_to"]
        ):
            raise ValueError("Reversed alias validity")
        if row["decision"] == "accept" and row["entity_id"] not in entity_map:
            raise ValueError("Reviewed alias references unknown entity")
        if row["decision"] != "accept" and row["entity_id"]:
            raise ValueError("Unresolved/rejected alias must not carry an entity_id")
        grouped[(row["source"], row["raw_string"])].append(row)
    for key, rows in grouped.items():
        ordered = sorted(rows, key=lambda r: r["valid_from"] or "0001-01-01")
        for left, right in zip(ordered, ordered[1:]):
            if (left["valid_to"] or "9999-12-31") >= (
                right["valid_from"] or "0001-01-01"
            ):
                raise ValueError(f"Overlapping alias validity: {key}")
    for row in relationships:
        if row["entity_id"] not in entity_map or (
            row["successor_entity_id"] and row["successor_entity_id"] not in entity_map
        ):
            raise ValueError("Unknown relationship entity")
        if (
            row["entity_id"] == row["successor_entity_id"]
            and row["relationship"] != "rename"
        ):
            raise ValueError("Self successor")
        if not all(
            row.get(f)
            for f in ["effective_date", "evidence", "reviewed_by", "reviewed_on"]
        ):
            raise ValueError("Missing relationship provenance")
        date.fromisoformat(row["effective_date"])
    return entity_map, grouped


def resolve_reviewed(source, raw, when, grouped):
    hits = [r for r in grouped.get((source, raw), []) if in_period(r, when)]
    return hits[0] if hits else None


def propose(source, raw, index, targets):
    hits = candidates(raw, index)
    if not hits:
        return [{"source": source, "raw_string": raw, "status": "unmatched"}]
    best_score = max(h[1] for h in hits)
    tied_entities = {targets[name] for name, score, _ in hits if score == best_score}
    rows = []
    for name, score, method in hits:
        status = (
            "ambiguous"
            if len(tied_entities) > 1 and score == best_score
            else (
                "auto_accept"
                if score > 95 and score == best_score
                else "review" if score <= 95 else "alternative"
            )
        )
        rows.append(
            {
                "source": source,
                "raw_string": raw,
                "candidate_name": name,
                "candidate_entity_id": targets[name],
                "score": round(score, 6),
                "method": method,
                "status": status,
            }
        )
    return rows


def load_sources(data_dir, archive, entities):
    banks = archive.fdic("institutions", fields=FIELDS)
    certs = sorted(
        {cert for e in entities for cert in e["fdic_certs"].split(";") if cert}
    )
    history = (
        archive.fdic(
            "history",
            filters="CERT:("
            + " OR ".join(certs)
            + ") AND CHANGECODE:(221 OR 222 OR 223 OR 224 OR 225 OR 510)",
        )
        if certs
        else []
    )
    hmda = []
    for year in range(2018, 2026):
        kind = "panel" if year <= 2023 else "ts"
        body = archive.hmda(year, kind)
        with zipfile.ZipFile(io.BytesIO(body)) as zipped:
            name = next(n for n in zipped.namelist() if n.endswith(".csv"))
            for row in csv.DictReader(
                io.StringIO(zipped.read(name).decode("utf-8-sig"))
            ):
                row["identifier_year"] = str(year)
                row["identifier_source"] = (
                    f"https://files.ffiec.cfpb.gov/static-data/snapshot/{year}/{year}_public_{kind}_csv.zip"
                )
                hmda.append(row)
    return banks, history, hmda


def build(data_dir=Path("data"), offline=False, refresh=False, require_human=False):
    data_dir = Path(data_dir)
    reference = data_dir / "reference"
    entities = read_csv(reference / "entity_manual.csv")
    aliases = read_csv(reference / "alias_manual.csv")
    relationships = read_csv(reference / "entity_relationships.csv")
    entity_map, grouped = validate_reviews(entities, aliases, relationships)
    lei_path = reference / "hmda_lei_manual.csv"
    if any(e["leis"] for e in entities) and not lei_path.exists():
        raise FileNotFoundError(f"Missing reviewed HMDA links: {lei_path}")
    lei_reviews = read_csv(lei_path) if lei_path.exists() else []
    validate_lei_reviews(entities, lei_reviews)
    banks, history, hmda = load_sources(
        data_dir, IdentityArchive(data_dir / "raw", offline, refresh), entities
    )
    bank_map = {str(b["CERT"]): b for b in banks}
    for e in entities:
        if e["type"] != "bank" and (e["fdic_certs"] or e["rssdhcr"]):
            raise ValueError("FDIC bank identifiers attached to nonbank")
        for cert in filter(None, e["fdic_certs"].split(";")):
            if cert not in bank_map:
                raise ValueError(f"Unknown FDIC CERT: {cert}")
    validate_bank_mergers(relationships, entity_map, history)
    con = duckdb.connect()
    complaints = con.execute(
        "SELECT company,date_received,count(*) n FROM read_parquet(?) GROUP BY 1,2",
        [str(data_dir / "staging/stg_complaints.parquet")],
    ).fetchall()
    parties = con.execute(
        "SELECT action_id,party_index,party_raw,date_filed FROM read_parquet(?) WHERE mortgage_related AND is_company",
        [str(data_dir / "staging/stg_enforcement.parquet")],
    ).fetchall()
    counts = defaultdict(int)
    for company, _, n in complaints:
        counts[company] += n
    top = sorted(counts, key=lambda n: (-counts[n], n))[:150]
    priority_missing = [n for n in top if ("ccdb", n) not in grouped]
    if priority_missing:
        raise ValueError(f"Missing top-150 review: {priority_missing}")
    # Gold set is ONLY explicitly accepted aliases, never automatic proposals.
    reviewed, human, total = 0, 0, 0
    unmapped = defaultdict(int)
    for name, when, n in complaints:
        total += n
        review = resolve_reviewed("ccdb", name, when, grouped)
        if review and review["decision"] == "accept":
            reviewed += n
            human += n if not review["reviewed_by"].startswith("Codex") else 0
        else:
            unmapped[name] += n
    resolved_parties = []
    for action, party_index, name, when in parties:
        review = resolve_reviewed("enforcement", name, when, grouped)
        if not review or review["decision"] != "accept":
            raise ValueError(f"Unmapped mortgage enforcement company: {name}")
        resolved_parties.append(
            {
                "action_id": action,
                "party_index": party_index,
                "party_raw": name,
                "date_filed": str(when),
                "entity_id": review["entity_id"],
            }
        )
    crosswalk, gaps = make_crosswalk(entities, aliases, hmda, banks, lei_reviews)
    targets = {}
    for row in aliases:
        if row["decision"] == "accept":
            # Candidate keys include interval+entity so same spelling can propose
            # multiple distinct historical entities. Proposals never override dates.
            key = (row["raw_string"], row["entity_id"])
            targets[key] = row["entity_id"]
    for row in crosswalk:
        if row["source"] in {"hmda", "fdic_name", "fdic_namehcr"}:
            targets[(row["raw_string"], row["entity_id"])] = row["entity_id"]
    name_index = defaultdict(list)
    for key in targets:
        name_index[normalize(key[0])].append(key)
    # candidates() accepts index values of any type; normalize only the keys.
    queue = []
    proposals = []
    for source, names in [("ccdb", counts), ("enforcement", {p[2] for p in parties})]:
        for name in sorted(names):
            if (source, name) in grouped:
                continue
            for row in propose(source, name, name_index, targets):
                if row.get("candidate_name"):
                    row["candidate_name"] = row["candidate_name"][0]
                row["complaint_count"] = counts.get(name, 0)
                proposals.append(row)
                if row["status"] in {"review", "ambiguous"}:
                    queue.append(row)
    # Include reviewed fuzzy-band candidates as a closed decision audit.
    for row in aliases:
        if row.get("candidate_score") and 85 <= float(row["candidate_score"]) <= 95:
            queue.append(
                {
                    "source": row["source"],
                    "raw_string": row["raw_string"],
                    "candidate_name": row.get("candidate_name", ""),
                    "candidate_entity_id": row["entity_id"],
                    "score": row["candidate_score"],
                    "status": "reviewed_" + row["decision"],
                    "complaint_count": counts.get(row["raw_string"], 0),
                }
            )
    queue.sort(
        key=lambda r: (
            -int(r.get("complaint_count", 0)),
            r["raw_string"],
            -float(r.get("score", 0)),
        )
    )
    report = {
        "mortgage_complaints": total,
        "reviewed_mapped_complaints": reviewed,
        "reviewed_complaint_coverage": reviewed / total if total else 0,
        "independent_human_mapped_complaints": human,
        "independent_human_coverage": human / total if total else 0,
        "reviewer": "See alias_manual.csv; Codex reviews are not independent human adjudication",
        "top_names_reviewed": len(top),
        "top_names_accepted": sum(
            any(r["decision"] == "accept" for r in grouped[("ccdb", n)]) for n in top
        ),
        "mortgage_company_party_rows": len(parties),
        "mortgage_company_party_names": len({p[2] for p in parties}),
        "mapped_mortgage_company_party_rows": len(resolved_parties),
        "mortgage_company_party_coverage": (
            len(resolved_parties) / len(parties) if parties else 0
        ),
        "open_review_queue_rows": sum(
            not r["status"].startswith("reviewed_") for r in queue
        ),
        "unmapped_complaints": sorted(
            [{"company": n, "complaints": v} for n, v in unmapped.items()],
            key=lambda r: (-r["complaints"], r["company"]),
        ),
        "identifier_gaps": gaps,
        "optional_sources": "GLEIF/NIC deferred; dated HMDA identities plus FDIC cover demonstrated joins. No servicing denominator inferred.",
        "evaluation": evaluate(aliases),
        "input_fingerprints": {
            str(p.relative_to(data_dir)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(
                [
                    reference / name
                    for name in [
                        "alias_manual.csv",
                        "entity_manual.csv",
                        "entity_relationships.csv",
                    ]
                ]
                + ([lei_path] if lei_path.exists() else [])
            )
        },
        "source_counts": {
            "fdic_institutions": len(banks),
            "fdic_history_events": len(history),
            "hmda_identity_rows": len(hmda),
        },
    }
    if total == 0 or reviewed / total < 0.94:
        raise ValueError(
            f"Reviewed complaint coverage {reviewed / total if total else 0:.2%} below 94%"
        )
    if require_human and (
        human / total < 0.94
        or any(
            resolve_reviewed("enforcement", p[2], p[3], grouped)[
                "reviewed_by"
            ].startswith("Codex")
            for p in parties
        )
    ):
        raise ValueError(
            "Independent human review gate not met; Codex review cannot satisfy it"
        )
    marts = data_dir / "marts"
    marts.mkdir(exist_ok=True)
    # Validate all inputs and exit gates before replacing the published artifacts.
    with tempfile.TemporaryDirectory(dir=marts) as temporary:
        out = Path(temporary)
        write_csv(out / "crosswalk.csv", crosswalk, CROSSWALK_FIELDS)
        write_csv(out / "entity.csv", entities, list(entities[0]))
        write_csv(
            out / "alias.csv",
            [dict(r, method="manual") for r in aliases],
            REVIEW_FIELDS + ["method"],
        )
        write_csv(out / "match_review_queue.csv", queue, QUEUE_FIELDS)
        write_csv(out / "match_proposals.csv", proposals, QUEUE_FIELDS)
        write_csv(
            out / "enforcement_entity.csv",
            resolved_parties,
            ["action_id", "party_index", "party_raw", "date_filed", "entity_id"],
        )
        (out / "resolution_report.json").write_text(json.dumps(report, indent=2) + "\n")
        for filename in ["entity", "alias", "enforcement_entity"]:
            relation = con.read_csv(str(out / f"{filename}.csv"), all_varchar=True)
            date_fields = {
                "entity": ["valid_from", "valid_to", "reviewed_on"],
                "alias": ["valid_from", "valid_to", "reviewed_on"],
                "enforcement_entity": ["date_filed"],
            }[filename]
            relation = relation.project(
                "* REPLACE ("
                + ",".join(f"CAST({field} AS DATE) AS {field}" for field in date_fields)
                + ")"
            )
            if filename == "entity":
                relation = relation.project(
                    "* REPLACE (CASE WHEN fdic_certs IS NULL THEN []::INTEGER[] ELSE string_split(fdic_certs, ';')::INTEGER[] END AS fdic_certs)"
                )
            relation.write_parquet(str(out / f"{filename}.parquet"))
        con.read_parquet(str(out / "alias.parquet")).create_view("reviewed_alias")
        con.read_parquet(str(data_dir / "staging/stg_complaints.parquet")).create_view(
            "mortgage_complaints"
        )
        con.sql(
            """SELECT c.complaint_id, c.date_received, c.company,
                   a.entity_id, a.reviewed_by, a.reviewed_on
                   FROM mortgage_complaints c LEFT JOIN reviewed_alias a
                   ON a.source='ccdb' AND a.decision='accept' AND a.raw_string=c.company
                   AND (a.valid_from IS NULL OR c.date_received>=a.valid_from)
                   AND (a.valid_to IS NULL OR c.date_received<=a.valid_to)"""
        ).write_parquet(str(out / "complaint_entity.parquet"))
        write_csv(
            out / "top150_review.csv",
            [
                dict(r, rank=rank, complaint_count=counts[name])
                for rank, name in enumerate(top, 1)
                for r in grouped[("ccdb", name)]
            ],
            ["rank", "complaint_count"] + REVIEW_FIELDS,
        )
        write_csv(
            out / "fdic_institutions.csv",
            banks,
            ["CERT", "NAME", "FED_RSSD", "ACTIVE", "NAMEHCR", "RSSDHCR"],
        )
        write_csv(
            out / "fdic_history.csv",
            history,
            [
                "CERT",
                "OUT_CERT",
                "SUR_CERT",
                "ACQ_CERT",
                "INSTNAME",
                "FRM_INSTNAME",
                "OUT_INSTNAME",
                "SUR_INSTNAME",
                "EFFDATE",
                "CHANGECODE",
                "CHANGECODE_DESC",
            ],
        )
        for file in out.iterdir():
            file.replace(marts / file.name)
    con.close()
    return report


QUEUE_FIELDS = [
    "source",
    "raw_string",
    "complaint_count",
    "candidate_name",
    "candidate_entity_id",
    "method",
    "score",
    "status",
]
CROSSWALK_FIELDS = [
    "source",
    "raw_string",
    "cfpb_company_name",
    "entity_id",
    "display_name",
    "entity_type",
    "lei",
    "rssd",
    "rssdhcr",
    "fdic_cert",
    "hmda_identifier",
    "identifier_year",
    "identifier_source",
    "valid_from",
    "valid_to",
    "method",
    "reviewed_by",
    "reviewed_on",
    "evidence",
]


def validate_bank_mergers(relationships, entities, history):
    for row in relationships:
        if row["relationship"] != "bank_merger":
            continue
        source = entities[row["entity_id"]]
        target = entities[row["successor_entity_id"]]
        hits = [
            h
            for h in history
            if str(h.get("OUT_CERT")) in source["fdic_certs"].split(";")
            and str(h.get("SUR_CERT")) in target["fdic_certs"].split(";")
            and str(h.get("EFFDATE", ""))[:10] == row["effective_date"]
            and "merg" in h.get("CHANGECODE_DESC", "").lower()
        ]
        if not hits:
            raise ValueError(
                f"Bank merger not verified by FDIC /history: {source['display_name']}"
            )


def evaluate(aliases):
    """Leave one raw spelling out; compare candidate identity to reviewed gold.

    Manual-only names without another spelling have no automatic prediction.
    This is an alias self-check, not independent validation of the review itself.
    """
    from ews.resolve.matching import normalize

    accepted = [r for r in aliases if r["decision"] == "accept"]
    correct = predicted = high_false = 0
    for row in accepted:
        # Historical spelling reuse is evaluated through the dated resolver.
        others = [
            r
            for r in accepted
            if r["raw_string"] != row["raw_string"]
            and not (
                r["valid_from"]
                and row["valid_to"]
                and r["valid_from"] > row["valid_to"]
            )
            and not (
                r["valid_to"]
                and row["valid_from"]
                and r["valid_to"] < row["valid_from"]
            )
        ]
        idx = defaultdict(list)
        for r in others:
            idx[normalize(r["raw_string"])].append(r["entity_id"])
        hits = candidates(row["raw_string"], idx)
        if not hits:
            continue
        score = max(h[1] for h in hits)
        ids = {h[0] for h in hits if h[1] == score}
        if len(ids) != 1:
            continue
        predicted += 1
        hit = row["entity_id"] in ids
        correct += hit
        high_false += int(not hit and score >= 95)
    return {
        "design": "leave-one-spelling-out against Codex-reviewed aliases; not independent human validation",
        "gold_alias_rows": len(accepted),
        "unique_predictions": predicted,
        "correct_predictions": correct,
        "precision": correct / predicted if predicted else None,
        "recall": correct / len(accepted) if accepted else None,
        "false_positives_at_or_above_95": high_false,
    }


def validate_lei_reviews(entities, reviews):
    if not reviews:
        return
    entity_map = {e["entity_id"]: e for e in entities}
    grouped = defaultdict(list)
    for row in reviews:
        if row["entity_id"] not in entity_map or row["lei"] not in entity_map[
            row["entity_id"]
        ]["leis"].split(";"):
            raise ValueError("Unknown reviewed entity/LEI link")
        if not all(
            row.get(f)
            for f in ["reviewed_by", "reviewed_on", "evidence", "review_note"]
        ):
            raise ValueError("Missing LEI review provenance")
        for f in ["valid_from", "valid_to", "reviewed_on"]:
            if row.get(f):
                date.fromisoformat(row[f])
        if (
            row["valid_from"]
            and row["valid_to"]
            and row["valid_from"] > row["valid_to"]
        ):
            raise ValueError("Reversed LEI validity")
        grouped[row["lei"]].append(row)
    for lei, rows in grouped.items():
        ordered = sorted(rows, key=lambda r: r["valid_from"] or "0001-01-01")
        for left, right in zip(ordered, ordered[1:]):
            if (left["valid_to"] or "9999-12-31") >= (
                right["valid_from"] or "0001-01-01"
            ):
                raise ValueError(f"Overlapping entity/LEI links: {lei}")
    required = {
        (e["entity_id"], lei)
        for e in entities
        for lei in filter(None, e["leis"].split(";"))
    }
    if required != {(r["entity_id"], r["lei"]) for r in reviews}:
        raise ValueError("Missing reviewed entity/LEI link")


def make_crosswalk(entities, aliases, hmda, banks, lei_reviews=()):
    entity_map = {e["entity_id"]: e for e in entities}
    bank_map = {str(b["CERT"]): b for b in banks}
    by_lei = defaultdict(list)
    for h in hmda:
        if identifier(h.get("lei")):
            by_lei[h["lei"]].append(h)
    links, gaps = {}, []
    for e in entities:
        records = []
        certs = list(filter(None, e["fdic_certs"].split(";")))
        for lei in filter(None, e["leis"].split(";")):
            if lei not in by_lei:
                raise ValueError(f"Reviewed LEI not observed in HMDA: {lei}")
            for h in by_lei[lei]:
                link = next(
                    (
                        r
                        for r in lei_reviews
                        if r["entity_id"] == e["entity_id"] and r["lei"] == lei
                    ),
                    e,
                )
                if not in_period(link, h["identifier_year"] + "-12-31"):
                    continue
                # Identifier assertions retain their activity vintage. A source row
                # is not a point-in-time exposure/ownership denominator.
                rssd = identifier(h.get("respondent_rssd"))
                cert = next(
                    (
                        c
                        for c in certs
                        if identifier(bank_map[c].get("FED_RSSD")) == rssd
                    ),
                    "",
                )
                records.append(
                    {
                        "lei": lei,
                        "rssd": rssd,
                        "fdic_cert": cert,
                        "hmda_identifier": lei,
                        "identifier_year": h["identifier_year"],
                        "identifier_source": h["identifier_source"],
                        "hmda_name": h["respondent_name"],
                        "link_valid_from": link.get("valid_from", ""),
                        "link_valid_to": link.get("valid_to", ""),
                    }
                )
        for cert in certs:
            b = bank_map[cert]
            if e.get("valid_to") and e["valid_to"] < "2026-01-01":
                continue
            records.append(
                {
                    "fdic_cert": cert,
                    "rssd": identifier(b.get("FED_RSSD")),
                    "identifier_source": "https://api.fdic.gov/banks/institutions",
                    "identifier_year": "2026",
                }
            )
        if not records:
            records = [
                {
                    "identifier_source": "No verified reporter/bank identifier; identity only"
                }
            ]
        if not e["leis"]:
            gaps.append(
                {
                    "entity_id": e["entity_id"],
                    "name": e["display_name"],
                    "gap": "No reviewed HMDA reporter LEI; may be a servicer, non-reporter or legacy entity",
                }
            )
        links[e["entity_id"]] = records
    result = []
    for a in aliases:
        if a["decision"] != "accept":
            continue
        e = entity_map[a["entity_id"]]
        for record in links[a["entity_id"]]:
            # Explicitly selected LEIs can span a bank merger. Restrict their
            # annual records to this entity's reviewed identity period.
            year = record.get("identifier_year")
            if record.get("lei") and year and not in_period(e, year + "-12-31"):
                continue
            result.append(
                {
                    **record,
                    **a,
                    "cfpb_company_name": (
                        a["raw_string"] if a["source"] == "ccdb" else ""
                    ),
                    "display_name": e["display_name"],
                    "entity_type": e["type"],
                    "rssdhcr": e["rssdhcr"],
                    "method": "manual",
                }
            )
    # Publish source HMDA/FDIC aliases alongside CCDB/enforcement spellings.
    for e in entities:
        for record in links[e["entity_id"]]:
            year = record.get("identifier_year")
            if record.get("lei") and not in_period(e, year + "-12-31"):
                continue
            if record.get("hmda_name"):
                result.append(
                    {
                        **record,
                        "source": "hmda",
                        "raw_string": record["hmda_name"],
                        "entity_id": e["entity_id"],
                        "display_name": e["display_name"],
                        "entity_type": e["type"],
                        "rssdhcr": e["rssdhcr"],
                        "method": "manual",
                        "reviewed_by": e["reviewed_by"],
                        "reviewed_on": e["reviewed_on"],
                        "evidence": e["evidence"],
                        "valid_from": record.get("link_valid_from", ""),
                        "valid_to": record.get("link_valid_to", ""),
                    }
                )
        for cert in filter(None, e["fdic_certs"].split(";")):
            b = bank_map[cert]
            if e.get("valid_to") and e["valid_to"] < "2026-01-01":
                continue
            for field, source in [("NAME", "fdic_name"), ("NAMEHCR", "fdic_namehcr")]:
                if b.get(field) and (
                    field == "NAME" or identifier(b.get("RSSDHCR")) == e["rssdhcr"]
                ):
                    result.append(
                        {
                            "source": source,
                            "raw_string": b[field],
                            "entity_id": e["entity_id"],
                            "display_name": e["display_name"],
                            "entity_type": e["type"],
                            "rssd": identifier(b.get("FED_RSSD")),
                            "rssdhcr": e["rssdhcr"],
                            "fdic_cert": cert,
                            "method": "manual",
                            "identifier_year": "2026",
                            "identifier_source": "https://api.fdic.gov/banks/institutions",
                            "reviewed_by": e["reviewed_by"],
                            "reviewed_on": e["reviewed_on"],
                            "evidence": e["evidence"],
                        }
                    )
    return result, gaps


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=Path("data"))
    parser.add_argument("--offline", action="store_true")
    parser.add_argument("--refresh", action="store_true")
    parser.add_argument("--require-human-review", action="store_true")
    args = parser.parse_args(argv)
    report = build(args.data_dir, args.offline, args.refresh, args.require_human_review)
    print(
        json.dumps(
            {
                k: v
                for k, v in report.items()
                if k not in {"unmapped_complaints", "identifier_gaps"}
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
