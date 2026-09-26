"""Synthetic accounting/matching checks."""

from copy import deepcopy

import pytest

from not_my_debt.domain import Fact
from not_my_debt.examples import SCENARIOS, example_documents
from not_my_debt.reconcile import reconcile


def find(docs, kind):
    return next(doc for doc in docs if doc.kind == kind)


def change(docs, kind, key, value, confirmed=True, origin="document"):
    doc = find(docs, kind)
    doc.fields[key] = Fact(value, f"{key}: {value}", confirmed=confirmed, origin=origin)
    return doc


def codes(result):
    return {finding.code for finding in result.findings}


def assert_abstains(result):
    assert result.supported_balance_cents is None
    assert "possible_uncredited_payment" not in codes(result)
    assert "no_discrepancy_detected_in_supplied_records" not in codes(result)


def test_paid_story_has_exact_accounting_and_linked_sources():
    docs = example_documents()
    result = reconcile(docs)
    assert result.collection_cents == 15000
    assert result.applied_payments_cents == 15000
    assert result.supported_balance_cents == 0
    assert "possible_uncredited_payment" in codes(result)
    assert set(result.matched_document_ids) == {doc.id for doc in docs}
    references = {ref for item in result.findings + result.ledger for ref in item.refs}
    assert "receipt.payment_amount" in references
    assert "bill.insurer_paid" in references
    index = {doc.id: doc for doc in docs}
    for reference in references:
        identifier, field = reference.split(".", 1)
        assert index[identifier].fields[field].confirmed


@pytest.mark.parametrize(
    "scenario,balance,applied",
    [
        ("paid", 0, 15000),
        ("missing_receipt", 15000, 0),
        ("partial_payment", 10000, 5000),
        ("duplicate_receipt", 0, 15000),
        ("no_discrepancy", 0, 0),
    ],
)
def test_scenarios(scenario, balance, applied):
    result = reconcile(example_documents(scenario))
    assert result.supported_balance_cents == balance
    assert result.applied_payments_cents == applied


def test_wrong_account_distinguishes_mismatch_from_missing_evidence():
    result = reconcile(example_documents("wrong_account"))
    assert_abstains(result)
    assert result.applied_payments_cents == 0
    assert "ambiguous_document_match" in codes(result)
    assert "missing_payment_evidence" not in codes(result)


def test_missing_receipt_does_not_treat_eob_as_payment():
    result = reconcile(example_documents("missing_receipt"))
    assert "missing_payment_evidence" in codes(result)
    assert result.applied_payments_cents == 0
    assert "possible_uncredited_payment" not in codes(result)
    assert "eob_is_not_payment_proof" in codes(result)


@pytest.mark.parametrize(
    "kind,field,value",
    [
        ("receipt", "patient", "Another Person"),
        ("receipt", "provider", "Other Clinic"),
        ("receipt", "account", "OTHER-123"),
        ("receipt", "service_date", "2026-07-02"),
        ("receipt", "claim_id", "DIFFERENT"),
        ("bill", "account", "OTHER-123"),
        ("collection", "provider", "Other Clinic"),
        ("collection", "patient", "Another Person"),
    ],
)
def test_wrong_encounter_never_subtracts_payment(kind, field, value):
    docs = example_documents()
    change(docs, kind, field, value)
    result = reconcile(docs)
    assert_abstains(result)
    assert result.applied_payments_cents == 0


@pytest.mark.parametrize(
    "kind,field",
    [
        ("bill", "statement_date"),
        ("collection", "statement_date"),
        ("receipt", "payment_date"),
        ("receipt", "service_date"),
        ("bill", "service_date"),
        ("receipt", "patient"),
        ("receipt", "payment_status"),
    ],
)
def test_missing_dates_and_identity_abstain(kind, field):
    docs = example_documents()
    del find(docs, kind).fields[field]
    result = reconcile(docs)
    assert_abstains(result)
    assert result.applied_payments_cents == 0


@pytest.mark.parametrize(
    "value",
    ["07/20/2026", "2026-13-20", "July 20", "2026-07-15", "2026-08-15", "2026-09-01", "2026-06-30"],
)
def test_ambiguous_same_day_late_and_impossible_payment_dates(value):
    docs = example_documents()
    change(docs, "receipt", "payment_date", value)
    result = reconcile(docs)
    assert_abstains(result)
    assert result.applied_payments_cents == 0


@pytest.mark.parametrize(
    "status", ["Pending", "Authorized", "Reversed", "Refunded", "Failed", "Unknown"]
)
def test_unsettled_and_reversed_receipts_cannot_be_applied(status):
    docs = example_documents()
    change(docs, "receipt", "payment_status", status)
    result = reconcile(docs)
    assert_abstains(result)
    assert result.applied_payments_cents == 0
    assert "payment_not_settled" in codes(result)


def test_reversal_of_same_reference_invalidates_successful_copy():
    docs = example_documents()
    reversed_doc = deepcopy(find(docs, "receipt"))
    reversed_doc.id = "reversal"
    reversed_doc.fields["payment_status"].value = "Reversed"
    docs.append(reversed_doc)
    result = reconcile(docs)
    assert_abstains(result)
    assert result.applied_payments_cents == 0
    assert "conflicting_payment_evidence" in codes(result)


def test_duplicate_content_without_reference_counts_once():
    docs = example_documents("duplicate_receipt")
    for doc in docs:
        if doc.kind == "receipt":
            del doc.fields["payment_reference"]
    result = reconcile(docs)
    assert result.applied_payments_cents == 15000
    assert result.supported_balance_cents == 0


def test_same_day_same_amount_without_shared_reference_requires_review():
    docs = example_documents("duplicate_receipt")
    duplicate = next(doc for doc in docs if doc.id == "receipt_copy")
    del duplicate.fields["payment_reference"]
    duplicate.text += "\nThis is a differently formatted payment proof."
    result = reconcile(docs)
    assert_abstains(result)
    assert result.applied_payments_cents == 0
    assert "ambiguous_payment_identity" in codes(result)


def test_distinct_completed_transactions_can_be_added():
    docs = example_documents("partial_payment")
    second = deepcopy(find(docs, "receipt"))
    second.id = "receipt_second"
    second.fields["payment_reference"].value = "PAY-OTHER"
    second.fields["payment_amount"].value = "100.00"
    second.text = second.text.replace("PAY-715028", "PAY-OTHER").replace("50.00", "100.00")
    docs.append(second)
    result = reconcile(docs)
    assert result.applied_payments_cents == 15000
    assert result.supported_balance_cents == 0


def test_overpayment_does_not_infer_negative_debt_or_refund():
    docs = example_documents()
    change(docs, "receipt", "payment_amount", "151.00")
    result = reconcile(docs)
    assert_abstains(result)
    assert "payment_exceeds_statement_balance" in codes(result)


def test_posted_payment_is_not_deducted_twice():
    result = reconcile(example_documents("no_discrepancy"))
    assert result.supported_balance_cents == 0
    assert result.applied_payments_cents == 0
    assert "payment_already_in_statement" in codes(result)
    assert "no_discrepancy_detected_in_supplied_records" in codes(result)


def test_earlier_receipt_without_posted_credit_needs_account_ledger():
    docs = example_documents()
    change(docs, "receipt", "payment_date", "2026-07-14")
    result = reconcile(docs)
    assert_abstains(result)
    assert result.applied_payments_cents == 0
    assert "unresolved_payment_allocation" in codes(result)


def test_confirmed_user_correction_is_usable_and_labelled():
    docs = example_documents()
    change(docs, "receipt", "payment_amount", "150.00", origin="user")
    result = reconcile(docs)
    assert result.supported_balance_cents == 0
    correction = next(item for item in result.findings if item.code == "user_corrected_facts")
    assert "receipt.payment_amount" in correction.refs


@pytest.mark.parametrize(
    "kind,field", [("receipt", "payment_amount"), ("receipt", "account"), ("bill", "patient_paid")]
)
def test_unconfirmed_facts_are_never_used(kind, field):
    docs = example_documents()
    find(docs, kind).fields[field].confirmed = False
    result = reconcile(docs)
    assert_abstains(result)
    assert result.applied_payments_cents == 0
    for item in result.findings + result.ledger:
        assert f"{find(docs, kind).id}.{field}" not in item.refs


def test_excluding_receipt_withdraws_payment_finding():
    docs = example_documents()
    find(docs, "receipt").included = False
    result = reconcile(docs)
    assert result.supported_balance_cents == 15000
    assert "possible_uncredited_payment" not in codes(result)
    assert "receipt" in result.excluded_document_ids


@pytest.mark.parametrize("amount", ["149.99", "150.001", "NaN", "-150", ""])
def test_bill_must_balance_in_exact_cents(amount):
    docs = example_documents()
    change(docs, "bill", "balance", amount)
    assert_abstains(reconcile(docs))


def test_conflicting_revised_eob_abstains():
    docs = example_documents()
    revised = deepcopy(find(docs, "eob"))
    revised.id = "revised_eob"
    revised.fields["patient_responsibility"].value = "300.00"
    docs.append(revised)
    assert_abstains(reconcile(docs))


def test_conflicting_statement_versions_abstain():
    docs = example_documents()
    revision = deepcopy(find(docs, "bill"))
    revision.id = "revised_bill"
    revision.fields["balance"].value = "200.00"
    docs.append(revision)
    result = reconcile(docs)
    assert_abstains(result)
    assert "conflicting_documents" in codes(result)


def test_subcent_receipt_and_masked_accounts_abstain():
    docs = example_documents()
    change(docs, "receipt", "payment_amount", "0.001")
    assert_abstains(reconcile(docs))
    docs = example_documents()
    for doc in docs:
        doc.fields["account"].value = "****1042"
    assert_abstains(reconcile(docs))


def test_examples_are_independent_and_marked_fictional():
    for scenario in SCENARIOS:
        first, second = example_documents(scenario), example_documents(scenario)
        assert all("FICTIONAL DEMO" in doc.text for doc in first)
        first[0].fields["patient"].value = "Changed"
        assert second[0].fields["patient"].value == "Maya Ellis"


def test_receipt_deduplication_never_compares_amounts_by_digit_string():
    docs = example_documents("duplicate_receipt")
    receipt = find(docs, "receipt")
    receipt.fields["payment_amount"].value = "1.50"
    duplicate = next(doc for doc in docs if doc.id == "receipt_copy")
    duplicate.fields["payment_amount"].value = "15.0"
    result = reconcile(docs)
    assert_abstains(result)
    assert result.applied_payments_cents == 0


def test_identical_content_with_different_confirmed_references_needs_review():
    docs = example_documents("duplicate_receipt")
    duplicate = next(doc for doc in docs if doc.id == "receipt_copy")
    duplicate.fields["payment_reference"].value = "OTHER-REFERENCE"
    result = reconcile(docs)
    assert_abstains(result)
    assert result.applied_payments_cents == 0


def test_receipt_cannot_be_issued_before_its_payment():
    docs = example_documents()
    change(docs, "receipt", "statement_date", "2026-07-18")
    assert_abstains(reconcile(docs))
