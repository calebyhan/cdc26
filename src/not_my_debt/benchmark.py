"""Seeded synthetic regression benchmark for document reconciliation.

Each bundle is generated from a perturbation family whose expected outcome follows
from how the bundle was built (the product rules in docs/scope.md), not from engine
output. Bundles pass through the local text parser before reconciliation. This is a
synthetic regression check, not an accuracy estimate for real patient paperwork.
"""

import random
from dataclasses import dataclass

from not_my_debt.domain import Document
from not_my_debt.extract import ALIASES, extract_document
from not_my_debt.reconcile import reconcile

PAYMENT_FINDING = "possible_uncredited_payment"


@dataclass(frozen=True)
class Family:
    key: str
    label: str
    expected_code: str
    # None means the engine should withhold a final balance (correct abstention).
    supported: str  # "zero" | "balance" | "balance_minus_payment" | "none"
    payment_finding: bool


FAMILIES = (
    Family("paid_after_bill", "Paid in full after the bill", PAYMENT_FINDING, "zero", True),
    Family("partial_payment", "Partial payment", PAYMENT_FINDING, "balance_minus_payment", True),
    Family(
        "duplicate_receipt",
        "Same receipt supplied twice",
        "duplicate_payment_evidence",
        "zero",
        True,
    ),
    Family(
        "already_credited",
        "Payment already credited",
        "no_discrepancy_detected_in_supplied_records",
        "zero",
        False,
    ),
    Family("missing_receipt", "No payment evidence", "missing_payment_evidence", "balance", False),
    Family(
        "notice_adds_fees", "Notice exceeds bill, no payment", "amount_mismatch", "balance", False
    ),
    Family(
        "wrong_account", "Receipt for another account", "ambiguous_document_match", "none", False
    ),
    Family(
        "masked_account", "Masked account on receipt", "ambiguous_document_match", "none", False
    ),
    Family("pending_payment", "Pending payment status", "payment_not_settled", "none", False),
    Family("reversed_payment", "Reversed payment", "payment_not_settled", "none", False),
    Family(
        "paid_after_notice", "Payment after the notice", "ambiguous_payment_timing", "none", False
    ),
    Family(
        "overpayment",
        "Receipt exceeds the balance",
        "payment_exceeds_statement_balance",
        "none",
        False,
    ),
    Family(
        "bill_does_not_add_up", "Provider bill arithmetic error", "amount_mismatch", "none", False
    ),
    Family(
        "unrecognized_label",
        'Bill labels provider as "Billed by"',
        "ambiguous_document_match",
        "none",
        False,
    ),
)


def _dollars(cents: int) -> str:
    return f"{cents // 100}.{cents % 100:02d}"


def _text(title: str, values: dict, rng: random.Random) -> str:
    """Vary label wording across the parser's supported aliases."""
    return "\n".join(
        [f"FICTIONAL BENCHMARK — {title}"]
        + [f"{rng.choice(ALIASES[key]).title()}: {value}" for key, value in values.items()]
    )


def build_bundle(family: Family, rng: random.Random) -> tuple[list[tuple[str, str, str]], dict]:
    """Return (kind, title, text) records and the expected ground truth."""
    balance = rng.choice(range(2_500, 90_000, 25))
    insurer = rng.choice(range(10_000, 400_000, 100))
    adjustments = rng.choice(range(5_000, 200_000, 100))
    charges = balance + insurer + adjustments
    payment = balance
    if family.key == "partial_payment":
        payment = rng.randrange(100, balance, 25)
    if family.key == "overpayment":
        payment = balance + rng.randrange(100, 5_000, 25)
    identity = {
        "provider": rng.choice(["Maple Grove Medical", "Riverside Clinic", "Oak Hill Imaging"]),
        "patient": rng.choice(["Maya Ellis", "Jordan Reyes", "Sam Patel"]),
        "account": f"AC-{rng.randrange(1000, 9999)}",
        "claim_id": f"CL-{rng.randrange(100000, 999999)}",
        "service_date": "2026-07-01",
    }
    posted = payment if family.key == "already_credited" else 0
    bill_balance = balance - posted
    bill = {
        **identity,
        "statement_date": "2026-07-25" if family.key == "already_credited" else "2026-07-15",
        "charges": _dollars(charges),
        "adjustments": _dollars(adjustments),
        "insurer_paid": _dollars(insurer),
        "patient_paid": _dollars(posted),
        "balance": _dollars(bill_balance + (500 if family.key == "bill_does_not_add_up" else 0)),
    }
    eob = {
        **identity,
        "statement_date": "2026-07-12",
        "charges": _dollars(charges),
        "adjustments": _dollars(adjustments),
        "allowed": _dollars(charges - adjustments),
        "insurer_paid": _dollars(insurer),
        "patient_responsibility": _dollars(balance),
    }
    notice_balance = bill_balance
    if family.key == "notice_adds_fees":
        notice_balance += rng.randrange(1_000, 5_000, 25)
    notice = {
        **identity,
        "statement_date": "2026-08-15",
        "collector": "Pine Valley Account Services",
        "balance": _dollars(notice_balance),
    }
    paid_on = {"already_credited": "2026-07-10", "paid_after_notice": "2026-08-20"}.get(
        family.key, "2026-07-20"
    )
    receipt = {
        **identity,
        "statement_date": paid_on,
        "payment_date": paid_on,
        "payment_amount": _dollars(payment),
        "payment_reference": f"PAY-{rng.randrange(100000, 999999)}",
        "payment_status": {"pending_payment": "Pending", "reversed_payment": "Reversed"}.get(
            family.key, "Completed"
        ),
    }
    if family.key == "wrong_account":
        receipt["account"] = f"AC-{rng.randrange(1000, 9999)}X"
    if family.key == "masked_account":
        receipt["account"] = "****" + identity["account"][-4:]
    bill_text = _text("Provider bill", bill, rng)
    if family.key == "unrecognized_label":
        # The local parser reads known labels only; an unknown one must not be guessed.
        bill_text = "\n".join(
            f"Billed By: {identity['provider']}"
            if line.split(":")[0].lower() in ALIASES["provider"]
            else line
            for line in bill_text.splitlines()
        )
    records = [
        ("eob", "Insurance explanation", _text("Insurance explanation", eob, rng)),
        ("bill", "Provider bill", bill_text),
        ("collection", "Collection notice", _text("Collection notice", notice, rng)),
    ]
    if family.key not in {"missing_receipt", "notice_adds_fees"}:
        records.append(("receipt", "Payment receipt", _text("Payment receipt", receipt, rng)))
    if family.key == "duplicate_receipt":
        records.append(("receipt", "Payment receipt (second upload)", records[-1][2]))
    supported = {
        "zero": 0,
        "balance": bill_balance,
        "balance_minus_payment": balance - payment,
        "none": None,
    }[family.supported]
    return records, {
        "supported_cents": supported,
        "applied_cents": payment if family.payment_finding else 0,
    }


def _documents(records: list[tuple[str, str, str]]) -> list[Document]:
    docs = []
    for index, (kind, title, text) in enumerate(records):
        doc = extract_document(text, kind, title, method="local")
        doc.id = f"{kind}{index}"
        for fact in doc.fields.values():
            fact.confirmed = True
        docs.append(doc)
    return docs


def run(per_family: int = 5, seed: int = 20260926) -> dict:
    rng = random.Random(seed)
    rows = []
    for family in FAMILIES:
        for _ in range(per_family):
            records, truth = build_bundle(family, rng)
            result = reconcile(_documents(records))
            codes = {finding.code for finding in result.findings}
            rows.append(
                {
                    "family": family.key,
                    "expected_code_found": family.expected_code in codes,
                    "balance_correct": result.supported_balance_cents == truth["supported_cents"],
                    "payment_finding_correct": (PAYMENT_FINDING in codes) == family.payment_finding,
                    "counted_once": result.applied_payments_cents == truth["applied_cents"]
                    or truth["supported_cents"] is None,
                    "abstained": result.supported_balance_cents is None,
                    "should_abstain": truth["supported_cents"] is None,
                }
            )
    checks = ("expected_code_found", "balance_correct", "payment_finding_correct", "counted_once")
    families = []
    for family in FAMILIES:
        subset = [row for row in rows if row["family"] == family.key]
        families.append(
            {
                "key": family.key,
                "label": family.label,
                "bundles": len(subset),
                "passed": sum(all(row[c] for c in checks) for row in subset),
                "expected_outcome": family.expected_code,
                "withholds_balance": family.supported == "none",
            }
        )
    by_key = {family.key: family for family in FAMILIES}
    no_payment = [row for row in rows if not by_key[row["family"]].payment_finding]
    return {
        "seed": seed,
        "bundles": len(rows),
        "families": families,
        "totals": {check: sum(row[check] for row in rows) for check in checks},
        "all_checks_passed": sum(all(row[c] for c in checks) for row in rows),
        "abstention": {
            "should_abstain": sum(row["should_abstain"] for row in rows),
            "correctly_abstained": sum(row["should_abstain"] and row["abstained"] for row in rows),
            "abstained_when_answer_expected": sum(
                row["abstained"] and not row["should_abstain"] for row in rows
            ),
        },
        "false_payment_findings": sum(
            1 for row in no_payment if not row["payment_finding_correct"]
        ),
        "no_payment_bundles": len(no_payment),
        "scope": "Synthetic, generated bundles in the local parser's labeled-text format. "
        "Expected outcomes follow the documented product rules. Not a real-world accuracy estimate.",
    }
