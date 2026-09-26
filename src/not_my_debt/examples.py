"""Fictional, labeled document bundles."""

from copy import deepcopy

from not_my_debt.domain import FIELD_LABELS, Document, Fact

SCENARIOS = {
    "paid": "Paid, then sent to collections",
    "missing_receipt": "Payment receipt missing",
    "wrong_account": "Receipt belongs to another account",
    "partial_payment": "Only part of the balance paid",
    "duplicate_receipt": "Same receipt uploaded twice",
    "no_discrepancy": "Payment already credited",
}
SCENARIO_NAMES = tuple(SCENARIOS)


def _document(identifier, kind, title, values):
    lines = [f"FICTIONAL DEMO — {title}"]
    fields = {}
    for key, value in values.items():
        line = f"{FIELD_LABELS.get(key, key)}: {value}"
        lines.append(line)
        fields[key] = Fact(str(value), line, confirmed=True)
    return Document(
        identifier,
        kind,
        title,
        "\n".join(lines),
        fields,
        extraction_method="Preconfirmed fictional example",
    )


def example_documents(scenario: str = "paid") -> list[Document]:
    """Return fresh objects; every name, identifier, date and amount is invented."""
    if scenario not in SCENARIOS:
        raise ValueError(f"Unknown scenario: {scenario}")
    common = dict(
        provider="Maple Grove Medical",
        patient="Maya Ellis",
        account="MG-1042",
        claim_id="CL-260701",
        service_date="2026-07-01",
    )
    eob = _document(
        "eob",
        "eob",
        "Insurance explanation",
        {
            **common,
            "statement_date": "2026-07-12",
            "charges": "1200.00",
            "adjustments": "400.00",
            "allowed": "800.00",
            "insurer_paid": "650.00",
            "patient_responsibility": "150.00",
        },
    )
    bill = _document(
        "bill",
        "bill",
        "Provider bill",
        {
            **common,
            "statement_date": "2026-07-15",
            "charges": "1200.00",
            "adjustments": "400.00",
            "insurer_paid": "650.00",
            "patient_paid": "0.00",
            "balance": "150.00",
        },
    )
    receipt_values = {
        **common,
        "statement_date": "2026-07-20",
        "payment_date": "2026-07-20",
        "payment_amount": "50.00" if scenario == "partial_payment" else "150.00",
        "payment_reference": "PAY-715028",
        "payment_status": "Completed",
    }
    if scenario == "wrong_account":
        receipt_values["account"] = "MG-9999"
    receipt = _document("receipt", "receipt", "Provider payment receipt", receipt_values)
    notice = _document(
        "collection",
        "collection",
        "Collection notice",
        {
            **common,
            "statement_date": "2026-08-15",
            "collector": "Pine Valley Account Services",
            "balance": "150.00",
            "validation_end": "2026-09-20",
        },
    )
    if scenario == "no_discrepancy":
        # A later bill explicitly includes the earlier payment; do not deduct twice.
        bill = _document(
            "bill",
            "bill",
            "Provider bill with posted payment",
            {
                **common,
                "statement_date": "2026-07-25",
                "charges": "1200.00",
                "adjustments": "400.00",
                "insurer_paid": "650.00",
                "patient_paid": "150.00",
                "balance": "0.00",
            },
        )
        notice = _document(
            "collection",
            "collection",
            "Collection account update",
            {
                **common,
                "statement_date": "2026-08-15",
                "collector": "Pine Valley Account Services",
                "balance": "0.00",
            },
        )
    docs = [eob, bill, receipt, notice]
    if scenario == "missing_receipt":
        docs.remove(receipt)
    if scenario == "duplicate_receipt":
        duplicate = deepcopy(receipt)
        duplicate.id = "receipt_copy"
        duplicate.title = "Second upload of the same payment receipt"
        docs.insert(3, duplicate)
    return docs
