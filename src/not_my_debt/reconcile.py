"""Conservative single-encounter arithmetic.

These are discrepancies in supplied records, never decisions about legal liability.
Only confirmed fields participate; missing or contradictory evidence cannot turn
into a zero or an assumed payment. All monetary operations use integer cents.
"""

import re
from datetime import date

from not_my_debt.domain import CaseResult, Document, Finding, LedgerRow, dollars, money_cents

IDENTITY = ("provider", "patient", "account", "service_date")
SETTLED = {"paid", "completed", "settled", "posted", "successful", "succeeded"}
REVERSED = {
    "reversed",
    "refunded",
    "void",
    "voided",
    "failed",
    "declined",
    "cancelled",
    "canceled",
    "chargeback",
}


def _value(doc, key):
    fact = doc.fields.get(key)
    return str(fact.value).strip() if fact and fact.confirmed and str(fact.value).strip() else None


def _normal(value):
    return re.sub(r"[^a-z0-9]", "", (value or "").lower())


def _date(doc, key):
    value = _value(doc, key)
    if not value or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def _money(doc, key):
    value = _value(doc, key)
    try:
        return money_cents(value) if value is not None else None
    except ValueError:
        return None


def _refs(doc, *keys):
    return [f"{doc.id}.{key}" for key in keys if _value(doc, key) is not None]


def _match(doc, anchor):
    """Exact reviewed identifiers only; shared amount/name alone cannot match."""
    for key in IDENTITY:
        left, right = _value(doc, key), _value(anchor, key)
        if not left or not right:
            return False, f"Confirm {key.replace('_', ' ')} on both records."
        if key == "account" and any(re.search(r"\*|[xX]{3,}", s) for s in (left, right)):
            return False, "Masked account references need manual account verification."
        if key == "service_date":
            if not _date(doc, key) or not _date(anchor, key):
                return False, "Confirm an unambiguous service date in YYYY-MM-DD format."
            equal = _date(doc, key) == _date(anchor, key)
        else:
            equal = bool(_normal(left)) and _normal(left) == _normal(right)
        if not equal:
            return False, f"The confirmed {key.replace('_', ' ')} values differ."
    if (
        _value(doc, "claim_id")
        and _value(anchor, "claim_id")
        and _normal(_value(doc, "claim_id")) != _normal(_value(anchor, "claim_id"))
    ):
        return False, "The confirmed claim references differ."
    return True, "Provider, patient, account and service date agree."


def reconcile(documents: list[Document]) -> CaseResult:
    """Reconcile one bill/collection account; ambiguous inputs cause abstention."""
    result = CaseResult()

    def finding(code, title, detail, refs=(), severity="warning"):
        result.findings.append(Finding(code, title, detail, severity, list(dict.fromkeys(refs))))

    def exclude(doc):
        if doc.id not in result.excluded_document_ids:
            result.excluded_document_ids.append(doc.id)

    def matched(doc):
        if doc.id not in result.matched_document_ids:
            result.matched_document_ids.append(doc.id)

    docs = [doc for doc in documents if doc.included]
    result.excluded_document_ids = [doc.id for doc in documents if not doc.included]
    if len({doc.id for doc in docs}) != len(docs):
        finding(
            "conflicting_documents",
            "Document identifiers must be unique",
            "Two included records share an identifier. Resolve this before linking evidence.",
        )
        return result
    corrections = [
        f"{doc.id}.{key}"
        for doc in docs
        for key, fact in doc.fields.items()
        if fact.confirmed and fact.origin != "document"
    ]
    if corrections:
        finding(
            "user_corrected_facts",
            "Using your confirmed corrections",
            "These values were corrected by the user. Original document quotes remain available; "
            "check each corrected value against the record before sharing the packet.",
            corrections,
            "info",
        )

    def select(kind):
        candidates = [doc for doc in docs if doc.kind == kind]
        if not candidates:
            finding(
                "insufficient_itemization",
                f"Add a {kind} record",
                "A confirmed provider bill and collection balance are needed for account arithmetic.",
            )
            return None
        first = candidates[0]
        signature = {k: _value(first, k) for k in first.fields if _value(first, k) is not None}
        for other in candidates[1:]:
            other_signature = {
                k: _value(other, k) for k in other.fields if _value(other, k) is not None
            }
            if signature != other_signature:
                finding(
                    "conflicting_documents",
                    f"Multiple {kind} records need review",
                    "The included versions contain different confirmed facts. Select one applicable "
                    "statement or resolve the differences; the engine does not guess which is final.",
                    _refs(first, *first.fields) + _refs(other, *other.fields),
                )
                return None
            exclude(other)
            finding(
                "duplicate_document",
                "Duplicate statement counted once",
                "These records have the same confirmed facts.",
                _refs(first, "balance") + _refs(other, "balance"),
                "info",
            )
        return first

    notice, bill = select("collection"), select("bill")
    if notice:
        result.collection_cents = _money(notice, "balance")
    if notice is None or bill is None:
        return result
    valid, why = _match(bill, notice)
    if not valid:
        exclude(bill)
        finding(
            "ambiguous_document_match",
            "Bill and collection notice do not securely match",
            why,
            _refs(bill, *IDENTITY, "claim_id") + _refs(notice, *IDENTITY, "claim_id"),
        )
        return result
    matched(bill)
    matched(notice)
    bill_date, notice_date = _date(bill, "statement_date"), _date(notice, "statement_date")
    service_date = _date(bill, "service_date")
    if (
        not bill_date
        or not notice_date
        or not service_date
        or not service_date <= bill_date <= notice_date
    ):
        finding(
            "ambiguous_document_dates",
            "Confirm the document timeline",
            "Use YYYY-MM-DD dates. The service must precede the bill, and the bill cannot "
            "postdate the collection notice used in this comparison.",
            _refs(bill, "service_date", "statement_date") + _refs(notice, "statement_date"),
        )
        return result
    amounts = {
        key: _money(bill, key)
        for key in ("charges", "adjustments", "insurer_paid", "patient_paid", "balance")
    }
    if any(value is None for value in amounts.values()) or result.collection_cents is None:
        missing = [key.replace("_", " ") for key, value in amounts.items() if value is None]
        if result.collection_cents is None:
            missing.append("collection balance")
        finding(
            "insufficient_itemization",
            "Confirm the account amounts",
            "Missing, unconfirmed or invalid: "
            + ", ".join(missing)
            + ". Enter exact nonnegative dollar amounts; do not assume omitted payments are zero.",
            _refs(bill, *amounts) + _refs(notice, "balance"),
        )
        return result
    obligation = amounts["charges"] - amounts["adjustments"] - amounts["insurer_paid"]
    expected = obligation - amounts["patient_paid"]
    result.ledger = [
        LedgerRow(label, sign * amounts[key], _refs(bill, key))
        for key, label, sign in (
            ("charges", "Provider charges", 1),
            ("adjustments", "Contractual adjustment", -1),
            ("insurer_paid", "Posted insurer payment", -1),
            ("patient_paid", "Patient payments already posted", -1),
        )
    ]
    result.ledger.append(
        LedgerRow("Provider statement balance", amounts["balance"], _refs(bill, "balance"))
    )
    if expected < 0 or expected != amounts["balance"]:
        finding(
            "amount_mismatch",
            "The provider statement does not reconcile",
            f"Charges minus adjustments, posted insurer payments and posted patient payments equal "
            f"{dollars(expected)}; the statement reports {dollars(amounts['balance'])}. "
            "Request an itemized ledger before applying additional payments.",
            _refs(bill, *amounts),
        )
        return result

    uncertain = False
    for eob in [doc for doc in docs if doc.kind == "eob"]:
        finding(
            "eob_is_not_payment_proof",
            "Insurance responsibility is not patient payment evidence",
            "An EOB describes insurance processing and patient responsibility. No patient payment "
            "is subtracted from the EOB.",
            _refs(eob, "patient_responsibility", "insurer_paid"),
            "info",
        )
        ok, reason = _match(eob, bill)
        eob_date = _date(eob, "statement_date")
        if not ok or not eob_date or not service_date <= eob_date <= notice_date:
            exclude(eob)
            uncertain = True
            finding(
                "ambiguous_document_match",
                "Insurance record needs matching review",
                reason
                if not ok
                else "Confirm whether this dated insurance record applies to this collection balance.",
                _refs(eob, *IDENTITY, "claim_id", "statement_date"),
            )
            continue
        matched(eob)
        checks = {
            "charges": amounts["charges"],
            "adjustments": amounts["adjustments"],
            "allowed": amounts["charges"] - amounts["adjustments"],
            "insurer_paid": amounts["insurer_paid"],
            "patient_responsibility": obligation,
        }
        for key, expected_value in checks.items():
            if _value(eob, key) is not None and _money(eob, key) != expected_value:
                uncertain = True
                finding(
                    "conflicting_documents",
                    "Insurance and provider amounts differ",
                    f"The insurance {key.replace('_', ' ')} does not agree with the provider's "
                    "posted accounting. This may involve a revision or posting delay; resolve it first.",
                    _refs(eob, key)
                    + _refs(
                        bill, "charges", "adjustments", "insurer_paid", "patient_paid", "balance"
                    ),
                )

    receipts = [doc for doc in docs if doc.kind == "receipt"]
    if not receipts:
        finding(
            "missing_payment_evidence",
            "Payment receipt needed",
            "No included payment receipt supports a patient payment. The EOB alone cannot show "
            "that the patient paid. Add a matching completed-payment record.",
            _refs(bill, "balance"),
        )

    # Group references before matching so a reversal/conflicting copy cannot leave
    # its earlier successful version available to be subtracted.
    # Either repeated reference OR repeated content links payment evidence. Use
    # connected groups so a renamed/edited copy cannot bypass duplicate handling.
    parents = list(range(len(receipts)))

    def root(index):
        while parents[index] != index:
            parents[index] = parents[parents[index]]
            index = parents[index]
        return index

    seen_keys = {}
    for index, receipt in enumerate(receipts):
        reference = _normal(_value(receipt, "payment_reference"))
        content = " ".join(receipt.text.split())
        keys = ([] if not reference else [("reference", reference)]) + (
            [] if not content else [("content", content)]
        )
        for key in keys:
            if key in seen_keys:
                parents[root(index)] = root(seen_keys[key])
            else:
                seen_keys[key] = index
    grouped = {}
    for index, receipt in enumerate(receipts):
        grouped.setdefault(root(index), []).append(receipt)
    unique = []
    for group in grouped.values():
        first = group[0]
        keys = (*IDENTITY, "claim_id", "payment_date", "payment_amount", "payment_status")

        def signature(doc):
            return tuple(
                (
                    _money(doc, key)
                    if key == "payment_amount"
                    else "settled"
                    if key == "payment_status" and _normal(_value(doc, key)) in SETTLED
                    else _normal(_value(doc, key))
                )
                for key in keys
            )

        references = {
            _normal(_value(item, "payment_reference"))
            for item in group
            if _value(item, "payment_reference")
        }
        if len(references) > 1 or any(signature(item) != signature(first) for item in group[1:]):
            uncertain = True
            finding(
                "conflicting_payment_evidence",
                "Payment records conflict",
                "Records for the same payment reference or content disagree about amount, date, "
                "identity or status. A reversal or corrected receipt must be resolved before subtraction.",
                [ref for item in group for ref in _refs(item, *keys, "payment_reference")],
            )
            for item in group:
                exclude(item)
            continue
        unique.append(first)
        for duplicate in group[1:]:
            exclude(duplicate)
            finding(
                "duplicate_payment_evidence",
                "Same payment counted once",
                "The payment reference or identical receipt content repeats; its amount is not added again.",
                _refs(first, "payment_reference", "payment_amount")
                + _refs(duplicate, "payment_reference", "payment_amount"),
                "info",
            )

    # Different-looking documents without references may describe the same payment.
    collision_groups = {}
    for receipt in unique:
        fingerprint = tuple(
            _normal(_value(receipt, key)) for key in (*IDENTITY, "payment_date")
        ) + (_money(receipt, "payment_amount"),)
        collision_groups.setdefault(fingerprint, []).append(receipt)
    ambiguous_ids = set()
    for group in collision_groups.values():
        if len(group) > 1 and any(not _value(item, "payment_reference") for item in group):
            uncertain = True
            ambiguous_ids.update(item.id for item in group)
            finding(
                "ambiguous_payment_identity",
                "Possible duplicate payment records",
                "The same account, amount and payment date appear on multiple documents without "
                "distinct confirmed transaction references. Confirm whether these are separate payments.",
                [
                    ref
                    for item in group
                    for ref in _refs(item, "payment_amount", "payment_date", "payment_reference")
                ],
            )
    applied_refs = []
    earlier_total = 0
    earlier_refs = []
    for receipt in unique:
        if receipt.id in ambiguous_ids:
            exclude(receipt)
            continue
        ok, reason = _match(receipt, bill)
        if not ok:
            uncertain = True
            exclude(receipt)
            finding(
                "ambiguous_document_match",
                "Receipt cannot be applied to this account",
                reason,
                _refs(receipt, *IDENTITY, "claim_id") + _refs(bill, *IDENTITY, "claim_id"),
            )
            continue
        matched(receipt)
        amount = _money(receipt, "payment_amount")
        paid_date = _date(receipt, "payment_date")
        receipt_date = _date(receipt, "statement_date")
        status = _normal(_value(receipt, "payment_status"))
        refs = _refs(
            receipt, "payment_amount", "payment_date", "payment_status", "payment_reference"
        )
        if status not in SETTLED:
            uncertain = True
            finding(
                "payment_not_settled",
                "Payment status does not support subtraction",
                "The payment is reversed, unsuccessful, pending or lacks a confirmed completed status. "
                "Obtain the current transaction record.",
                refs,
            )
            continue
        invalid_receipt_date = _value(receipt, "statement_date") is not None and (
            not receipt_date or (paid_date and receipt_date < paid_date)
        )
        if (
            amount is None
            or not paid_date
            or paid_date < service_date
            or paid_date >= notice_date
            or paid_date == bill_date
            or invalid_receipt_date
        ):
            uncertain = True
            finding(
                "ambiguous_payment_timing",
                "Payment amount or timing needs review",
                "Confirm the amount and YYYY-MM-DD payment date. A payment must follow the service; "
                "same-day ordering is unknown, and a payment on/after the notice cannot establish "
                "that the notice missed an earlier payment. A receipt issue date cannot precede "
                "its reported payment date.",
                refs
                + _refs(receipt, "statement_date")
                + _refs(bill, "statement_date")
                + _refs(notice, "statement_date"),
            )
            continue
        if paid_date < bill_date:
            earlier_total += amount
            earlier_refs.extend(refs)
            finding(
                "payment_already_in_statement",
                "Earlier payment not subtracted again",
                "This receipt predates the provider statement. The statement's posted-payment total "
                "is the baseline; confirm individual payment allocation in the provider ledger.",
                refs + _refs(bill, "patient_paid"),
                "info",
            )
            continue
        result.applied_payments_cents += amount
        applied_refs.extend(refs)
        result.ledger.append(LedgerRow("Matching completed payment after statement", -amount, refs))
    if earlier_total > amounts["patient_paid"]:
        uncertain = True
        finding(
            "unresolved_payment_allocation",
            "Earlier receipts exceed posted patient payments",
            "The earlier receipts cannot all be accounted for by the statement's posted patient "
            "payments. Request a transaction ledger; do not subtract them again by assumption.",
            earlier_refs + _refs(bill, "patient_paid"),
        )
    supported = amounts["balance"] - result.applied_payments_cents
    if supported < 0:
        uncertain = True
        finding(
            "payment_exceeds_statement_balance",
            "Payments exceed the statement balance",
            "Matching receipts exceed the balance in this statement. Allocation, refunds, reversals "
            "or other charges need review; this calculation does not establish an account credit.",
            applied_refs + _refs(bill, "balance"),
        )
    if uncertain:
        finding(
            "reconciliation_incomplete",
            "Resolve the highlighted evidence before comparing balances",
            "A final supported balance is withheld because included records have unresolved identity, "
            "timing, status or accounting questions. Subtotals are not a debt-validity determination.",
        )
        return result
    result.supported_balance_cents = supported
    result.ledger.append(
        LedgerRow(
            "Balance supported by supplied records",
            supported,
            _refs(bill, "balance") + applied_refs,
        )
    )
    difference = result.collection_cents - supported
    if difference > 0 and result.applied_payments_cents:
        finding(
            "possible_uncredited_payment",
            "A payment may not be reflected in the collection balance",
            f"The matching completed receipt(s) show {dollars(result.applied_payments_cents)} paid "
            f"after the provider statement and before the notice. Supplied-record arithmetic gives "
            f"{dollars(supported)}, while the notice requests {dollars(result.collection_cents)}. "
            "Request an updated itemized ledger and confirmation of payment allocation; later "
            "reversals or account activity are not established by these records.",
            applied_refs
            + _refs(bill, "balance", "statement_date")
            + _refs(notice, "balance", "statement_date"),
        )
    elif difference:
        finding(
            "amount_mismatch",
            "The supplied balances differ",
            f"The notice requests {dollars(result.collection_cents)}; the supplied-record calculation "
            f"is {dollars(supported)}. Ask for the transactions explaining this difference.",
            _refs(bill, "balance") + _refs(notice, "balance") + applied_refs,
        )
    elif receipts:
        finding(
            "no_discrepancy_detected_in_supplied_records",
            "Supplied amounts reconcile",
            "No balance discrepancy was detected in these confirmed records. This does not verify "
            "the current account ledger, later activity or legal liability.",
            _refs(bill, "balance") + _refs(notice, "balance") + applied_refs,
            "info",
        )
    return result
