"""Exercise the committed PDF bytes through the real upload path.

Created with assistance from OpenAI Codex. All records are synthetic.
"""

import json
from pathlib import Path

import pytest
from pypdf import PdfReader

from not_my_debt.examples import example_documents
from not_my_debt.extract import extract_document, read_upload
from not_my_debt.reconcile import reconcile

ROOT = Path(__file__).resolve().parents[1] / "sample_documents"
MANIFEST = json.loads((ROOT / "manifest.json").read_text())


def load_pdf(name, *, confirm=False):
    spec = MANIFEST["files"][name]
    text = read_upload((ROOT / name).read_bytes(), name)
    document = extract_document(text, spec["kind"], name, method="local")
    if confirm:
        for fact in document.fields.values():
            fact.confirmed = True
    return document


@pytest.mark.parametrize("name", MANIFEST["files"])
def test_pdf_upload_preserves_fixture_facts_and_sources(name):
    spec = MANIFEST["files"][name]
    fixture = next(
        doc for doc in example_documents(spec["scenario"]) if doc.kind == spec["kind"]
    )
    expected = {key: fact.value for key, fact in fixture.fields.items()}
    assert expected == spec["expected_fields"]
    reader = PdfReader(ROOT / name)
    assert not reader.is_encrypted
    assert len(reader.pages) == 1
    document = load_pdf(name)
    assert "Fictional demo" in document.text
    assert not document.warnings
    assert {key: fact.value for key, fact in document.fields.items()} == expected
    for fact in document.fields.values():
        assert not fact.confirmed
        assert fact.page == 1
        assert fact.quote in document.text


@pytest.mark.parametrize(
    ("receipt", "applied", "balance", "finding"),
    [
        ("03_payment_receipt.pdf", 15000, 0, "possible_uncredited_payment"),
        (None, 0, 15000, "missing_payment_evidence"),
        (
            "variants/03_payment_receipt_partial_payment.pdf",
            5000,
            10000,
            "possible_uncredited_payment",
        ),
        (
            "variants/03_payment_receipt_wrong_account.pdf",
            0,
            None,
            "ambiguous_document_match",
        ),
    ],
)
def test_reviewed_pdf_bundle_reconciles_conservatively(receipt, applied, balance, finding):
    documents = [
        load_pdf(name, confirm=True)
        for name in (
            "01_insurance_explanation.pdf",
            "02_provider_bill.pdf",
            "04_collection_notice.pdf",
        )
    ]
    if receipt:
        documents.append(load_pdf(receipt, confirm=True))
    result = reconcile(documents)
    assert result.collection_cents == 15000
    assert result.applied_payments_cents == applied
    assert result.supported_balance_cents == balance
    codes = {item.code for item in result.findings}
    assert finding in codes
    if applied == 0:
        assert "possible_uncredited_payment" not in codes


def test_unreviewed_uploaded_pdfs_cannot_establish_a_paid_balance():
    documents = [load_pdf(name) for name in MANIFEST["files"] if "/" not in name]
    result = reconcile(documents)
    assert result.supported_balance_cents is None
    assert result.applied_payments_cents == 0
    assert "possible_uncredited_payment" not in {item.code for item in result.findings}
