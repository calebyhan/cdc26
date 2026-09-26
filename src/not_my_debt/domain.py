"""Shared contracts."""

import re
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation

KINDS = {
    "eob": "Insurance explanation",
    "bill": "Provider bill",
    "receipt": "Payment receipt",
    "collection": "Collection notice",
}
FIELD_LABELS = {
    "provider": "Provider / original creditor",
    "patient": "Patient",
    "account": "Account reference",
    "claim_id": "Claim reference",
    "service_date": "Date of service",
    "statement_date": "Document date",
    "charges": "Provider charges",
    "adjustments": "Contractual adjustment",
    "allowed": "Allowed amount",
    "insurer_paid": "Insurer payment",
    "patient_responsibility": "Patient responsibility",
    "patient_paid": "Patient payments credited",
    "balance": "Statement / collection balance",
    "payment_amount": "Receipt payment",
    "payment_date": "Payment date",
    "payment_reference": "Payment reference",
    "payment_status": "Payment status",
    "collector": "Collector",
    "validation_end": "Stated dispute deadline",
}
MONEY_FIELDS = {
    "charges",
    "adjustments",
    "allowed",
    "insurer_paid",
    "patient_responsibility",
    "patient_paid",
    "balance",
    "payment_amount",
}


@dataclass
class Fact:
    value: str
    quote: str
    page: int = 1
    confirmed: bool = False
    origin: str = "document"


@dataclass
class Document:
    id: str
    kind: str
    title: str
    text: str
    fields: dict[str, Fact] = field(default_factory=dict)
    included: bool = True
    extraction_method: str = "Local labeled-field parser"
    warnings: list[str] = field(default_factory=list)


@dataclass
class Finding:
    code: str
    title: str
    detail: str
    severity: str = "info"
    refs: list[str] = field(default_factory=list)


@dataclass
class LedgerRow:
    label: str
    cents: int
    refs: list[str] = field(default_factory=list)


@dataclass
class CaseResult:
    findings: list[Finding] = field(default_factory=list)
    ledger: list[LedgerRow] = field(default_factory=list)
    collection_cents: int | None = None
    supported_balance_cents: int | None = None
    applied_payments_cents: int = 0
    matched_document_ids: list[str] = field(default_factory=list)
    excluded_document_ids: list[str] = field(default_factory=list)


def money_cents(value: str) -> int:
    """Parse exact nonnegative USD values, never round fractional cents silently."""
    raw = value.strip().removeprefix("$").strip()
    if len(raw) > 18 or not re.fullmatch(r"(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d{1,2})?", raw):
        raise ValueError("Enter a nonnegative dollar amount with at most two decimal places")
    cleaned = raw.replace(",", "")
    try:
        amount = Decimal(cleaned)
    except InvalidOperation as exc:
        raise ValueError("Enter a dollar amount such as 150.00") from exc
    if not amount.is_finite() or amount < 0 or amount * 100 != (amount * 100).to_integral_value():
        raise ValueError("Use a nonnegative amount with at most two decimal places")
    return int(amount * 100)


def dollars(cents: int | None) -> str:
    return "Unknown" if cents is None else f"${Decimal(cents) / 100:,.2f}"
