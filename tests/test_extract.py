"""Extraction must preserve uncertainty and reject unsupported model fields."""

import pytest

from not_my_debt.extract import (
    ExtractedField,
    Extraction,
    extract_document,
    read_upload,
    validate_extraction,
)


def test_local_parses_pages_without_claiming_confirmation():
    doc = extract_document(
        "Provider: Example Clinic\nAmount paid: $150.00\fPayment date: 08/10/2026",
        "receipt",
        "Receipt",
    )
    assert doc.fields["payment_amount"].value == "150.00"
    assert doc.fields["payment_date"].value == "2026-08-10"
    assert doc.fields["payment_date"].page == 2
    assert not doc.fields["payment_amount"].confirmed


def test_conflicting_amounts_are_omitted():
    doc = extract_document("Balance: $150\nBalance: $250", "bill", "Bill")
    assert "balance" not in doc.fields
    assert any("Conflicting" in warning for warning in doc.warnings)


def test_eob_amount_due_is_not_paid():
    doc = extract_document("Amount due: $150", "eob", "EOB")
    assert doc.fields["patient_responsibility"].value == "150.00"
    assert "payment_amount" not in doc.fields


def test_unsupported_ai_quotes_values_and_dates_discarded():
    text = "Balance: $150.00\nStatement date: 2026-08-01"
    parsed = Extraction(
        fields=[
            ExtractedField(key="balance", value="1000.00", quote="Balance: $150.00", page=1),
            ExtractedField(key="provider", value="Invented", quote="Provider: Invented", page=1),
            ExtractedField(
                key="statement_date", value="2025-08-01", quote="Statement date: 2026-08-01", page=1
            ),
        ],
        warnings=[],
    )
    fields, warnings = validate_extraction(parsed, text)
    assert fields == {}
    assert len(warnings) == 3


def test_supported_ai_field_retains_exact_quote_and_requires_review():
    text = "Balance: $150.00"
    fields, warnings = validate_extraction(
        Extraction(
            fields=[ExtractedField(key="balance", value="150", quote=text, page=1)], warnings=[]
        ),
        text,
    )
    assert fields["balance"].quote == text
    assert not fields["balance"].confirmed
    assert not warnings


@pytest.mark.parametrize("amount", ["-150", "NaN", "Infinity", "150.001", "1e10000000", "1,50"])
def test_invalid_amounts_not_accepted(amount):
    doc = extract_document(f"Amount paid: {amount}", "receipt", "Receipt")
    assert "payment_amount" not in doc.fields
    assert doc.warnings


def test_read_upload_bounds_and_types():
    assert read_upload(b"Provider: Example", "bill.txt") == "Provider: Example"
    with pytest.raises(ValueError):
        read_upload(b"<html>", "bill.html")
    with pytest.raises(ValueError):
        read_upload(b"x" * 60_001, "bill.txt")


def test_missing_ai_key_does_not_silently_use_local(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(ValueError, match="OPENAI_API_KEY"):
        extract_document("Balance: $150", "bill", "Bill", "openai")
