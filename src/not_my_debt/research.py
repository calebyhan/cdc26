"""Reproducible, bounded CFPB medical-debt research; no outcome inference.

This module uses only the Python standard library. Narratives stay in ignored
raw storage; the public artifact contains aggregate counts and methods.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import re
import urllib.parse
import urllib.request
import zipfile
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

API_BASE = "https://www.consumerfinance.gov/data-research/consumer-complaints/search/api/v1/"
ARCHIVE_URL = "https://files.consumerfinance.gov/f/documents/CCDB_Export_9_January_2025_through_February_2025.zip"
ARCHIVE_SHA256 = "11c18bb0973eed8f5e4f66e2979346af0671a3aefcb5a6b9eec73009d53cff64"
ARCHIVE_BYTES = 75_475_199
MAX_DOWNLOAD_BYTES = 90_000_000
MAX_UNCOMPRESSED_BYTES = 600_000_000
NOT_OWED = "Attempts to collect debt not owed"
API_URL = (
    API_BASE
    + "?"
    + urllib.parse.urlencode(
        {
            "size": 3,
            "date_received_min": "2025-01-01",
            "date_received_max": "2025-12-31",
            # A separate sub_product parameter is silently ignored by the current API.
            "product": "Debt collection\u2022Medical debt",
        }
    )
)
PAID_SUBISSUE = "Debt was paid"
PAID_API_URL = API_URL + "&" + urllib.parse.urlencode({"issue": f"{NOT_OWED}\u2022{PAID_SUBISSUE}"})

# These patterns are intentionally inspectable string matching, not diagnoses or
# validated classifiers. Negation and context are not resolved.
PATTERNS = [
    {
        "id": "paid_language",
        "label": "Already-paid language",
        "description": "Mentions already paid, paid in full, or a zero balance; does not verify payment.",
        "regex": r"\b(?:already|previously)\s+(?:been\s+)?paid\b|\bpaid\s+in\s+full\b|\b(?:zero|0(?:\.00)?)\s+balance\b|\bbalance\s+(?:was|is|of)\s+(?:zero|\$?0(?:\.00)?)\b",
    },
    {
        "id": "insurance_language",
        "label": "Insurance / coverage language",
        "description": "Mentions insurance, insurer, coverage, or an explanation of benefits; does not establish an insurance error.",
        "regex": r"\b(?:insurance|insurer|coverage|eob)\b|\bexplanation\s+of\s+benefits\b",
    },
    {
        "id": "identity_language",
        "label": "Identity / recognition language",
        "description": "Mentions identity theft, not mine, not my debt, or wrong person; does not establish identity theft.",
        "regex": r"\bidentity\s+theft\b|\bnot\s+(?:my\s+debt|mine)\b|\bwrong\s+person\b",
    },
    {
        "id": "verification_language",
        "label": "Verification / documentation language",
        "description": "Mentions validation, verification, or requests for proof/documentation; does not establish that documents were missing.",
        "regex": r"\b(?:validat\w*|verif\w*|documentation)\b|\bproof\s+of\b",
    },
    {
        "id": "amount_language",
        "label": "Amount / duplicate-billing language",
        "description": "Mentions a wrong/incorrect amount, overcharge, or duplicate bill/charge; does not prove a billing discrepancy.",
        "regex": r"\b(?:wrong|incorrect|inaccurate)\s+(?:amount|balance)\b|\bovercharg\w*\b|\bduplicate\s+(?:bill\w*|charg\w*)\b",
    },
]
DOCUMENTS = [
    {
        "id": "eob",
        "label": "Explanation of benefits",
        "description": "Explicit EOB or explanation-of-benefits mention.",
        "regex": r"\beob\b|\bexplanation\s+of\s+benefits\b",
    },
    {
        "id": "bill",
        "label": "Bill / invoice / statement",
        "description": "Mentions a bill, billing statement, itemized statement, or invoice.",
        "regex": r"\bbills?\b|\binvoices?\b|\b(?:billing|itemized)\s+statements?\b",
    },
    {
        "id": "receipt",
        "label": "Receipt / payment proof",
        "description": "Mentions a receipt, payment confirmation, bank statement, canceled check, or proof of payment.",
        "regex": r"\breceipts?\b|\bpayment\s+confirmation\b|\bproof\s+of\s+payment\b|\bbank\s+statements?\b|\bcancel(?:l)?ed\s+checks?\b",
    },
    {
        "id": "collection_notice",
        "label": "Collection / validation notice",
        "description": "Explicit collection/dunning/validation notice or letter mention.",
        "regex": r"\b(?:collection|dunning|validation)\s+(?:notice|letter)\b",
    },
]


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def narrative_hash(text: str) -> str:
    normalized = " ".join(text.casefold().split())
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def fetch_api(path: Path) -> dict:
    with urllib.request.urlopen(API_URL, timeout=90) as response:
        if "application/json" not in response.headers.get("Content-Type", ""):
            raise ValueError("CFPB returned non-JSON; do not treat it as a valid API response")
        data = json.load(response)
    # Verify the hierarchical filter against returned rows, not merely URL text.
    hits = data.get("hits", {}).get("hits", [])
    if not hits or any(
        h["_source"].get("product") != "Debt collection"
        or h["_source"].get("sub_product") != "Medical debt"
        for h in hits
    ):
        raise ValueError("Medical-debt filter could not be verified")
    write_json(path, data)
    write_json(
        path.with_suffix(".metadata.json"),
        {"source_url": API_URL, "retrieved_at": utc_now(), "sha256": sha256_file(path)},
    )
    return data


def fetch_paid_api(path: Path) -> dict:
    """Fetch the "Debt was paid" subset; verify the hierarchical issue filter on rows."""
    with urllib.request.urlopen(PAID_API_URL, timeout=90) as response:
        if "application/json" not in response.headers.get("Content-Type", ""):
            raise ValueError("CFPB returned non-JSON; do not treat it as a valid API response")
        data = json.load(response)
    write_json(path, data)
    write_json(
        path.with_suffix(".metadata.json"),
        {"source_url": PAID_API_URL, "retrieved_at": utc_now(), "sha256": sha256_file(path)},
    )
    return data


def _response_group(label: str, data: dict) -> dict:
    total = data["hits"]["total"]["value"]
    buckets = data["aggregations"]["company_response"]["company_response"]["buckets"]
    responses = [{"label": b["key"], "count": b["doc_count"]} for b in buckets]
    if sum(item["count"] for item in responses) != total:
        raise ValueError(f"{label}: company responses do not sum to the complaint total")
    return {"label": label, "total": total, "responses": responses}


def summarize_response_outcomes(everything: dict, paid: dict) -> dict:
    """Company responses are what companies reported, not verified complaint outcomes."""
    for data in (everything, paid):
        hits = data["hits"]["hits"]
        if not hits or any(
            h["_source"].get("product") != "Debt collection"
            or h["_source"].get("sub_product") != "Medical debt"
            for h in hits
        ):
            raise ValueError("Response data does not verify the medical-debt filter")
    if any(h["_source"].get("sub_issue") != PAID_SUBISSUE for h in paid["hits"]["hits"]):
        raise ValueError(f"Response data does not verify the {PAID_SUBISSUE!r} filter")
    return {
        "groups": [
            _response_group("All medical-debt collection complaints", everything),
            _response_group(f"Categorized \u201c{PAID_SUBISSUE}\u201d", paid),
        ],
        "source_urls": [API_URL, PAID_API_URL],
        "caveat": "Company responses are reported by companies. \u201cClosed with explanation\u201d "
        "does not establish that a complaint was unfounded, and relief categories are not "
        "verified corrections.",
    }


def download_archive(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".part")
    try:
        with (
            urllib.request.urlopen(ARCHIVE_URL, timeout=120) as response,
            temporary.open("wb") as target,
        ):
            length = int(response.headers.get("Content-Length", "0"))
            if length > MAX_DOWNLOAD_BYTES:
                raise ValueError("Archive exceeds the bounded download limit")
            size = 0
            while chunk := response.read(1024 * 1024):
                size += len(chunk)
                if size > MAX_DOWNLOAD_BYTES:
                    raise ValueError("Archive exceeds the bounded download limit")
                target.write(chunk)
        if sha256_file(temporary) != ARCHIVE_SHA256:
            raise ValueError("Archive checksum changed; inspect the source before updating the pin")
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def labeled_counts(counter: Counter) -> list[dict]:
    return [{"label": label, "count": count} for label, count in counter.most_common()]


def summarize_api(data: dict) -> dict:
    hits = data["hits"]["hits"]
    if not hits or any(
        h["_source"].get("sub_product") != "Medical debt"
        or h["_source"].get("product") != "Debt collection"
        for h in hits
    ):
        raise ValueError("Cached API response does not verify the medical-debt filter")
    issues = data["aggregations"]["issue"]["issue"]["buckets"]
    not_owed = next(b for b in issues if b["key"] == NOT_OWED)
    return {
        "total_complaints": data["hits"]["total"]["value"],
        "issue_counts": [{"label": b["key"], "count": b["doc_count"]} for b in issues],
        "not_owed_count": not_owed["doc_count"],
        "not_owed_subissues": [
            {"label": b["key"], "count": b["doc_count"]}
            for b in not_owed["sub_issue.raw"]["buckets"]
        ],
        "source_url": API_URL,
        "filter_verified_sample_size": len(hits),
        "narratives_present_in_sample": sum(
            bool(h["_source"].get("complaint_what_happened")) for h in hits
        ),
        "narrative_status": "Current API supplies structured fields, not complaint narratives. Narrative analysis uses the historical archive.",
        "last_indexed": data.get("_meta", {}).get("last_indexed"),
    }


def summarize_archive(
    path: Path, extracted_path: Path | None = None, *, verify_checksum: bool = True
) -> dict:
    digest = sha256_file(path)
    if verify_checksum and digest != ARCHIVE_SHA256:
        raise ValueError("Archive checksum differs from the pinned official Jan–Feb 2025 release")
    total_rows = medical_total = with_narrative = duplicates = out_of_period = 0
    seen: set[str] = set()
    pattern_counts, document_counts, matrix = Counter(), Counter(), Counter()
    issue_counts, subissue_counts, narrative_issue_counts = Counter(), Counter(), Counter()
    unique_subissues, months = Counter(), Counter()
    matchers = [(p["id"], re.compile(p["regex"], re.I)) for p in PATTERNS]
    document_matchers = [(p["id"], re.compile(p["regex"], re.I)) for p in DOCUMENTS]
    extracted = None
    if extracted_path:
        extracted_path.parent.mkdir(parents=True, exist_ok=True)
        extracted = extracted_path.open("w", encoding="utf-8")
    try:
        with zipfile.ZipFile(path) as archive:
            members = [i for i in archive.infolist() if i.filename.lower().endswith(".csv")]
            if len(members) != 1 or members[0].file_size > MAX_UNCOMPRESSED_BYTES:
                raise ValueError("Expected one bounded CSV in the official archive")
            with (
                archive.open(members[0]) as binary,
                io.TextIOWrapper(binary, encoding="utf-8-sig", newline="") as source,
            ):
                csv.field_size_limit(10_000_000)
                rows = csv.DictReader(source)
                required = {
                    "Product",
                    "Sub-product",
                    "Consumer complaint narrative",
                    "Complaint ID",
                    "Date received",
                    "Issue",
                    "Sub-issue",
                }
                if not required.issubset(rows.fieldnames or []):
                    raise ValueError("Unexpected archive schema")
                for row in rows:
                    total_rows += 1
                    if row["Product"] != "Debt collection" or row["Sub-product"] != "Medical debt":
                        continue
                    medical_total += 1
                    date = row["Date received"]
                    try:
                        received = datetime.strptime(date, "%Y-%m-%d")
                    except ValueError:
                        received = datetime.strptime(date, "%m/%d/%Y")
                    if received.year != 2025 or received.month not in (1, 2):
                        out_of_period += 1
                    months[received.strftime("%Y-%m")] += 1
                    issue_counts[row["Issue"]] += 1
                    if row["Issue"] == NOT_OWED:
                        subissue_counts[row["Sub-issue"]] += 1
                    narrative = row["Consumer complaint narrative"].strip()
                    if not narrative:
                        continue
                    with_narrative += 1
                    narrative_issue_counts[row["Issue"]] += 1
                    key = narrative_hash(narrative)
                    if key in seen:
                        duplicates += 1
                        continue
                    seen.add(key)
                    if row["Issue"] == NOT_OWED:
                        unique_subissues[row["Sub-issue"]] += 1
                    patterns = [label for label, regex in matchers if regex.search(narrative)]
                    documents = [
                        label for label, regex in document_matchers if regex.search(narrative)
                    ]
                    pattern_counts.update(patterns)
                    document_counts.update(documents)
                    matrix.update(
                        (pattern, document) for pattern in patterns for document in documents
                    )
                    if extracted:
                        extracted.write(
                            json.dumps(
                                {
                                    "complaint_id": row["Complaint ID"],
                                    "date_received": received.strftime("%Y-%m-%d"),
                                    "issue": row["Issue"],
                                    "sub_issue": row["Sub-issue"],
                                    "narrative": narrative,
                                    "narrative_sha256": key,
                                    "matched_patterns": patterns,
                                    "document_mentions": documents,
                                },
                                ensure_ascii=False,
                            )
                            + "\n"
                        )
    finally:
        if extracted:
            extracted.close()
    if out_of_period:
        raise ValueError(f"Found {out_of_period} medical rows outside the specified archive period")
    return {
        "period": "January–February 2025",
        "source_url": ARCHIVE_URL,
        "sha256": digest,
        "compressed_bytes": path.stat().st_size,
        "archive_total_rows": total_rows,
        "medical_total": medical_total,
        "medical_with_narrative": with_narrative,
        "medical_without_narrative": medical_total - with_narrative,
        "unique_narratives": len(seen),
        "duplicate_narratives": duplicates,
        "narrative_coverage_pct": round(with_narrative / medical_total * 100, 2)
        if medical_total
        else 0,
        "deduplication": "SHA-256 of casefolded text with whitespace collapsed; not semantic or near-duplicate detection.",
        "monthly_counts": labeled_counts(months),
        "issue_counts": labeled_counts(issue_counts),
        "not_owed_subissues": labeled_counts(subissue_counts),
        "narrative_issue_counts_before_dedup": labeled_counts(narrative_issue_counts),
        "unique_not_owed_subissues": labeled_counts(unique_subissues),
        "patterns": [{**p, "count": pattern_counts[p["id"]]} for p in PATTERNS],
        "document_mentions": [{**p, "count": document_counts[p["id"]]} for p in DOCUMENTS],
        "pattern_document_matrix": [
            {"pattern_id": p["id"], "document_id": d["id"], "count": matrix[p["id"], d["id"]]}
            for p in PATTERNS
            for d in DOCUMENTS
        ],
        "examples": [],
        "example_policy": "Public artifacts contain aggregates only. Full narrative text remains in ignored local raw storage.",
    }


def build_research(api: dict, archive: dict, *, api_retrieved_at: str | None = None) -> dict:
    return {
        "schema_version": "1.0",
        "retrieved_at": api_retrieved_at or utc_now(),
        "generated_at": utc_now(),
        "scope": {"year": 2025, "product": "Debt collection", "sub_product": "Medical debt"},
        "api": summarize_api(api),
        "archive": archive,
        "caveats": [
            "Complaint counts describe submitted complaints, not population prevalence, distinct people, or verified wrongdoing.",
            "The annual API and the two-month narrative archive have different time windows and extraction dates; their denominators are not interchangeable.",
            "Narratives are consumer reports and are missing for many complaints. Narrative availability can introduce selection bias.",
            "Keyword patterns and document mentions overlap. Their denominator is unique nonempty medical-debt narratives, not all complaints.",
            "Matching a keyword does not verify payment, an insurance error, identity theft, document availability, or a correct legal outcome. Negation/context are not resolved.",
            "This research is exploratory; no classifier performance, human review, causal effect, or recovered-money outcome is claimed.",
            "CFPB narratives do not include paired EOB/bill/receipt/collection-notice bundles. Document reconciliation is evaluated separately on labeled synthetic fixtures.",
        ],
    }


def refresh_response_outcomes(
    research_path: Path, raw: Path, *, reuse: bool = False, root: Path | None = None
) -> dict:
    """Add company-response aggregates to research JSON and its source manifest."""
    everything_path, paid_path = raw / "medical_2025_api.json", raw / "medical_2025_paid_api.json"
    everything = (
        json.loads(everything_path.read_text(encoding="utf-8"))
        if reuse and everything_path.exists()
        else fetch_api(everything_path)
    )
    paid = (
        json.loads(paid_path.read_text(encoding="utf-8"))
        if reuse and paid_path.exists()
        else fetch_paid_api(paid_path)
    )
    research = json.loads(research_path.read_text(encoding="utf-8"))
    research["api"]["response_outcomes"] = summarize_response_outcomes(everything, paid)
    write_json(research_path, research)
    manifest_path = research_path.parent / "source_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    base = root or research_path.parents[2]

    def source(name: str, url: str, path: Path) -> dict:
        metadata = path.with_suffix(".metadata.json")
        return {
            "name": name,
            "source_url": url,
            "retrieved_at": json.loads(metadata.read_text()).get("retrieved_at")
            if metadata.exists()
            else utc_now(),
            "sha256": sha256_file(path),
            "bytes": path.stat().st_size,
            "local_path": str(path.relative_to(base)) if path.is_relative_to(base) else path.name,
        }

    entries = [
        source("CFPB medical-debt company responses, all 2025", API_URL, everything_path),
        source(
            f"CFPB medical-debt \u201c{PAID_SUBISSUE}\u201d company responses",
            PAID_API_URL,
            paid_path,
        ),
    ]
    names = {entry["name"] for entry in entries}
    manifest["sources"] = [s for s in manifest["sources"] if s["name"] not in names] + entries
    manifest["output"]["sha256"] = sha256_file(research_path)
    manifest["generated_at"] = utc_now()
    write_json(manifest_path, manifest)
    return research["api"]["response_outcomes"]
