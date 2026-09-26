"""PDF-backed presentation regressions on synthetic records. Built with Codex."""

import pytest

from not_my_debt.demo_documents import ROOT, demo_cases
from not_my_debt.extract import read_upload
from not_my_debt.web_bridge import handle_request


def test_demo_facts_and_quotes_come_from_original_pdf_bytes():
    examples, sources = demo_cases()
    for scenario, documents in examples.items():
        for document in documents:
            filename = sources[scenario].get(document["id"])
            if filename is None:
                continue
            assert document["text"] == read_upload((ROOT / filename).read_bytes(), filename)
            for fact in document["fields"].values():
                assert fact["confirmed"] is True
                assert fact["quote"] in document["text"]
    receipt = next(doc for doc in examples["paid"] if doc["kind"] == "receipt")
    assert receipt["fields"]["payment_amount"]["quote"] == "Payment amount: $150.00"


@pytest.mark.parametrize(
    ("scenario", "applied", "balance"),
    [
        ("paid", 15000, 0),
        ("missing_receipt", 0, 15000),
        ("partial_payment", 5000, 10000),
        ("wrong_account", 0, None),
        ("duplicate_receipt", 15000, 0),
        ("no_discrepancy", 0, 0),
    ],
)
def test_pdf_backed_cases_preserve_matching_and_conservative_balances(scenario, applied, balance):
    bootstrap = handle_request({"operation": "bootstrap"})
    response = handle_request(
        {"operation": "reconcile", "documents": bootstrap["examples"][scenario]}
    )
    assert response["result"]["applied_payments_cents"] == applied
    assert response["result"]["supported_balance_cents"] == balance


def test_variants_never_link_to_a_different_document_version():
    examples, sources = demo_cases()
    for scenario in ("partial_payment", "wrong_account"):
        receipt = next(doc for doc in examples[scenario] if doc["kind"] == "receipt")
        assert sources[scenario][receipt["id"]] == f"variants/03_payment_receipt_{scenario}.pdf"
    receipts = [doc for doc in examples["duplicate_receipt"] if doc["kind"] == "receipt"]
    assert len(receipts) == 2
    assert {sources["duplicate_receipt"][doc["id"]] for doc in receipts} == {
        "03_payment_receipt.pdf"
    }
    for document in examples["no_discrepancy"]:
        if document["kind"] in {"bill", "collection"}:
            assert document["id"] not in sources["no_discrepancy"]
