"""Local reading of real-world layouts: tables, stacked labels, leaders, grids, scans."""

import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import measure_layouts as layouts  # noqa: E402

from not_my_debt.document_text import lines_from_boxes, read_document  # noqa: E402
from not_my_debt.examples import example_documents  # noqa: E402
from not_my_debt.extract import extract_document  # noqa: E402

FACTS = {d.kind: {k: f.value for k, f in d.fields.items()} for d in example_documents("paid")}


@pytest.mark.parametrize("layout", ["table", "stacked", "leaders", "grid"])
@pytest.mark.parametrize("kind", sorted(FACTS))
def test_text_layouts_recover_every_field(layout, kind):
    content, filename = layouts.rendered(kind, FACTS[kind], layout)
    doc = extract_document(read_document(content, filename).text, kind, kind, method="local")
    assert {k: f.value for k, f in doc.fields.items()} == FACTS[kind]
    assert all(not f.confirmed for f in doc.fields.values())


def test_table_rows_keep_label_and_amount_on_one_line():
    text = lines_from_boxes(
        [(72, 100, 160, 110, "Balance"), (163, 100, 190, 110, "due"), (500, 100, 540, 110, "$150.00")]
    )
    assert text == "Balance due  $150.00"


@pytest.mark.skipif(bool(os.environ.get("NMD_SKIP_OCR")), reason="OCR model load is slow")
def test_scanned_bill_is_read_with_local_ocr():
    content, filename = layouts.rendered("bill", FACTS["bill"], "scan")
    result = read_document(content, filename)
    assert any("OCR" in note for note in result.notes)
    doc = extract_document(result.text, "bill", "Bill", method="local")
    got = {k: f.value for k, f in doc.fields.items()}
    for key in ("account", "charges", "adjustments", "insurer_paid", "balance", "service_date"):
        assert got.get(key) == FACTS["bill"][key]


def test_value_on_next_line_and_label_variants():
    text = "PATIENT NAME\nMaya Ellis\nAcct #: MG-1042\nDOS 07/01/2026\nAmount You Owe ........ $150.00"
    doc = extract_document(text, "eob", "EOB")
    got = {k: f.value for k, f in doc.fields.items()}
    assert got == {
        "patient": "Maya Ellis",
        "account": "MG-1042",
        "service_date": "2026-07-01",
        "patient_responsibility": "150.00",
    }
    assert doc.fields["patient"].quote == "PATIENT NAME\nMaya Ellis"


def test_reductions_shown_negative_are_read_but_negative_balances_are_not():
    doc = extract_document("Plan Paid  -$650.00\nBalance Due  ($25.00)", "bill", "Bill")
    assert doc.fields["insurer_paid"].value == "650.00"
    assert "balance" not in doc.fields
    assert any("negative" in w for w in doc.warnings)


def test_negative_receipt_payment_is_not_flipped():
    doc = extract_document("Amount Paid: -$150.00", "receipt", "Receipt")
    assert "payment_amount" not in doc.fields


def test_generic_labels_follow_document_type():
    receipt = extract_document("Amount  $150.00\nDate  07/20/2026", "receipt", "Receipt")
    assert receipt.fields["payment_amount"].value == "150.00"
    assert receipt.fields["payment_date"].value == "2026-07-20"
    notice = extract_document("Amount  $150.00\nDate  08/15/2026", "collection", "Notice")
    assert notice.fields["balance"].value == "150.00"
    assert notice.fields["statement_date"].value == "2026-08-15"


def test_unknown_labels_are_still_not_guessed():
    doc = extract_document("Billed By: Maple Grove Medical\nMisc: $5.00", "bill", "Bill")
    assert not doc.fields


def test_conflicting_values_are_withheld():
    doc = extract_document("Balance Due  $150.00\nBalance Due  $175.00", "bill", "Bill")
    assert "balance" not in doc.fields
    assert any("Conflicting" in w for w in doc.warnings)


def test_images_and_unsupported_types():
    with pytest.raises(ValueError):
        read_document(b"<html>", "bill.html")
    with pytest.raises(ValueError):
        read_document(b"not an image", "bill.png")
