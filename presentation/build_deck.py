"""Build presentation/index.html from deck.template.html and committed data.

Every number on the slides comes from here: the CFPB research snapshot, the
synthetic benchmark summary, and the evidence engine's own output for Maya's
fictional case. Rebuild after refreshing any of them:

    uv run python presentation/build_deck.py
"""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from not_my_debt.benchmark import FAMILIES  # noqa: E402
from not_my_debt.examples import example_documents  # noqa: E402
from not_my_debt.extract import extract_document  # noqa: E402
from not_my_debt.reconcile import reconcile  # noqa: E402

TEMPLATE = Path(__file__).with_name("deck.template.html")
OUTPUT = Path(__file__).with_name("index.html")
PLACEHOLDER = "/*DATA*/null"
FAILURE_TEXT = "Billed By: Maple Grove Medical\nAccount: MG-1042\nBalance: 150.00"
SHORT_PATTERNS = {
    "paid_language": "Already paid",
    "insurance_language": "Insurance / coverage",
    "identity_language": "Not mine / identity",
    "verification_language": "Verification / proof",
    "amount_language": "Wrong amount",
}
SHORT_DOCUMENTS = {"eob": "EOB", "bill": "Bill", "receipt": "Receipt", "collection_notice": "Notice"}


def _case(documents) -> dict:
    result = reconcile(documents)
    return {
        "ledger": [{"label": row.label, "cents": row.cents} for row in result.ledger],
        "supported": result.supported_balance_cents,
        "collection": result.collection_cents,
        "applied": result.applied_payments_cents,
        "findings": [finding.code for finding in result.findings],
    }


def deck_data() -> dict:
    research = json.loads((ROOT / "data/research/research.json").read_text(encoding="utf-8"))
    bench = json.loads((ROOT / "data/benchmark/results.json").read_text(encoding="utf-8"))
    api, archive = research["api"], research["archive"]

    paid = example_documents("paid")
    without_receipt = example_documents("paid")
    for doc in without_receipt:
        doc.included = doc.kind != "receipt"
    with_case, without_case = _case(paid), _case(without_receipt)
    wrong_case = _case(example_documents("wrong_account"))
    # The slides narrate these outcomes; fail the build rather than show stale claims.
    assert "possible_uncredited_payment" in with_case["findings"]
    assert "missing_payment_evidence" in without_case["findings"]
    assert wrong_case["supported"] is None
    wrong_receipt = next(d for d in example_documents("wrong_account") if d.kind == "receipt")

    parsed = extract_document(FAILURE_TEXT, "bill", "Bill", method="local")
    assert "provider" not in parsed.fields, "The failure example no longer fails"

    not_owed = "Attempts to collect debt not owed"
    outcomes = api["response_outcomes"]["groups"]
    payment_flag = {family.key: family.payment_finding for family in FAMILIES}
    return {
        "facts": {
            doc.kind: {key: {"value": f.value, "quote": f.quote} for key, f in doc.fields.items()}
            for doc in paid
        },
        "wrongAccount": wrong_receipt.fields["account"].value,
        "withReceipt": with_case,
        "withoutReceipt": without_case,
        "wrongCase": wrong_case,
        "drill": [
            {"total": api["total_complaints"], "segs": api["issue_counts"], "hi": not_owed},
            {"total": api["not_owed_count"], "segs": api["not_owed_subissues"], "hi": "Debt was paid"},
            {"total": outcomes[1]["total"], "segs": outcomes[1]["responses"], "hi": "Closed with explanation"},
        ],
        "allResponses": outcomes[0],
        "responseCaveat": api["response_outcomes"]["caveat"],
        "retrieved": research["retrieved_at"][:10],
        "archive": {
            "period": archive["period"],
            "unique": archive["unique_narratives"],
            "patterns": [
                {"id": p["id"], "label": SHORT_PATTERNS.get(p["id"], p["label"]), "count": p["count"]}
                for p in archive["patterns"]
            ],
            "documents": [
                {"id": d["id"], "label": SHORT_DOCUMENTS.get(d["id"], d["label"]), "count": d["count"]}
                for d in archive["document_mentions"]
            ],
            "matrix": archive["pattern_document_matrix"],
        },
        "bench": {
            "bundles": bench["bundles"],
            "passed": bench["all_checks_passed"],
            "falseFlags": bench["false_payment_findings"],
            "noPaymentBundles": bench["no_payment_bundles"],
            "shouldAbstain": bench["abstention"]["should_abstain"],
            "abstained": bench["abstention"]["correctly_abstained"],
            "families": [
                {
                    "key": f["key"],
                    "label": f["label"],
                    "bundles": f["bundles"],
                    "passed": f["passed"],
                    "withholds": f["withholds_balance"],
                    "flags": payment_flag[f["key"]],
                }
                for f in bench["families"]
            ],
        },
        "failure": {
            "lines": FAILURE_TEXT.splitlines(),
            "fields": {key: fact.value for key, fact in parsed.fields.items()},
        },
    }


def build() -> str:
    template = TEMPLATE.read_text(encoding="utf-8")
    if template.count(PLACEHOLDER) != 1:
        raise ValueError(f"{TEMPLATE.name} must contain {PLACEHOLDER} exactly once")
    data = json.dumps(deck_data(), ensure_ascii=False, separators=(",", ":"))
    return template.replace(PLACEHOLDER, data.replace("</", "<\\/"))


if __name__ == "__main__":
    OUTPUT.write_text(build(), encoding="utf-8")
    print(f"Wrote {OUTPUT.relative_to(ROOT)}")
