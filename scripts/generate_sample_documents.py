"""Generate searchable, fictional upload PDFs. Created with OpenAI Codex.

Run from the repository: uv run --with reportlab==5.0.1 python scripts/generate_sample_documents.py
"""

from __future__ import annotations

import argparse
import json
import sys
from decimal import Decimal
from pathlib import Path

from reportlab.lib.colors import HexColor
from reportlab.lib.pagesizes import letter
from reportlab.lib.utils import simpleSplit
from reportlab.pdfgen import canvas

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from not_my_debt.domain import MONEY_FIELDS  # noqa: E402
from not_my_debt.examples import example_documents  # noqa: E402

INK = HexColor("#183C36")
MUTED = HexColor("#596A64")
LINE = HexColor("#D6DED7")
CREAM = HexColor("#F3F1E9")

# Explicit aliases supported by the app's local extractor. Each label/value is
# drawn as ONE PDF text operation, keeping pypdf's extracted line intact.
LABELS = {
    "provider": "Provider",
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
    "patient_paid": "Patient payments already in statement",
    "balance": "Balance due",
    "payment_date": "Payment date",
    "payment_amount": "Payment amount",
    "payment_reference": "Payment reference",
    "payment_status": "Payment status",
    "collector": "Collector",
    "validation_end": "Stated dispute deadline",
}

COMMON = ("patient", "provider", "account", "claim_id", "service_date", "statement_date")
SPECS = {
    "eob": {
        "issuer": "Piedmont Care Health Plan",
        "title": "Explanation of benefits",
        "intro": "This is not a bill. This statement explains the insurance processing of one visit.",
        "section": "Claim calculation",
        "color": "#315978",
        "fields": (
            "charges", "adjustments", "allowed", "insurer_paid", "patient_responsibility"
        ),
        "total_key": "patient_responsibility",
        "total_label": "Your share of the allowed amount",
        "total_note": "Patient responsibility reported by the plan",
        "note": "The $800 allowed amount is the $1,200 charge less the $400 contractual adjustment. "
        "The plan reports a $650 payment, leaving $150 patient responsibility. "
        "An explanation of benefits does not establish whether the patient paid.",
    },
    "bill": {
        "issuer": "Maple Grove Medical",
        "title": "Patient billing statement",
        "intro": "An itemized account summary for the visit identified below.",
        "section": "Posted account activity",
        "color": "#246459",
        "fields": ("charges", "adjustments", "insurer_paid", "patient_paid", "balance"),
        "total_key": "balance",
        "total_label": "Balance on this statement",
        "total_note": "As of the document date above",
        "note": "The statement shows a $400 contractual adjustment and a $650 insurance payment "
        "against the $1,200 charge. No patient payment is included in this statement. "
        "Activity posted after the statement date is not reflected here.",
    },
    "receipt": {
        "issuer": "Maple Grove Medical",
        "title": "Payment receipt",
        "intro": "Confirmation of a completed payment to the provider.",
        "section": "Transaction details",
        "color": "#246459",
        "fields": ("payment_date", "payment_amount", "payment_reference", "payment_status"),
        "total_key": "payment_amount",
        "total_label": "Payment received",
        "total_note": "Status: Completed",
        "note": "Keep this receipt with your billing statement. It documents the payment "
        "and account shown above. It is not a complete account ledger or a record of later activity.",
    },
    "collection": {
        "issuer": "Pine Valley Account Services",
        "title": "Collection notice",
        "intro": "Simplified fictional notice excerpt. This example is not a complete legal notice.",
        "section": "Collection account details",
        "color": "#AD5037",
        "fields": ("collector", "balance", "validation_end"),
        "total_key": "balance",
        "total_label": "Amount requested",
        "total_note": "For the provider account shown above",
        "note": "The notice requests the balance shown for this provider account. The supplied "
        "documents do not establish the current ledger or legal liability. "
        "The stated dispute date belongs to the fictional scenario; it is not a live deadline.",
    },
}


def money(value: str) -> str:
    return f"${Decimal(value):,.2f}"


def paragraph(pdf: canvas.Canvas, text: str, x: float, y: float, width: float) -> float:
    pdf.setFont("Helvetica", 10)
    pdf.setFillColor(MUTED)
    for line in simpleSplit(text, "Helvetica", 10, width):
        pdf.drawString(x, y, line)
        y -= 15
    return y


def create_pdf(path: Path, document, variant: str | None = None) -> dict:
    spec = SPECS[document.kind]
    accent = HexColor(spec["color"])
    values = {key: fact.value for key, fact in document.fields.items()}
    path.parent.mkdir(parents=True, exist_ok=True)
    pdf = canvas.Canvas(str(path), pagesize=letter, pageCompression=1, invariant=1)
    pdf.setTitle(f"FICTIONAL DEMO - Maya Ellis - {spec['title']}")
    pdf.setAuthor("Not My Debt team; created with assistance from OpenAI Codex")
    pdf.setSubject("Synthetic hackathon upload fixture. No real patient information.")

    pdf.setFillColor(MUTED)
    pdf.setFont("Helvetica", 8)
    pdf.drawRightString(564, 748, "Fictional demo")

    pdf.setFillColor(accent)
    pdf.setFont("Helvetica-Bold", 12)
    pdf.drawString(48, 714, spec["issuer"])
    pdf.setFillColor(INK)
    pdf.setFont("Helvetica-Bold", 25)
    pdf.drawString(48, 680, spec["title"])
    paragraph(pdf, spec["intro"], 48, 657, 516)

    pdf.setStrokeColor(LINE)
    pdf.line(48, 632, 564, 632)
    pdf.setFillColor(INK)
    pdf.setFont("Helvetica", 10.5)
    y = 611
    for key in COMMON:
        line = f"{LABELS[key]}: {values[key]}"
        pdf.drawString(48, y, line)
        y -= 18

    pdf.setFont("Helvetica-Bold", 9)
    pdf.setFillColor(accent)
    pdf.drawString(48, 467, spec["section"].upper())
    if variant:
        pdf.setFont("Helvetica-Bold", 8)
        pdf.drawRightString(564, 467, variant.replace("_", " ").upper())
    y = 441
    for key in spec["fields"]:
        label = "Collection balance" if document.kind == "collection" and key == "balance" else LABELS[key]
        value = money(values[key]) if key in MONEY_FIELDS else values[key]
        line = f"{label}: {value}"
        assert pdf.stringWidth(line, "Helvetica", 11) <= 516, line
        pdf.setFillColor(INK)
        pdf.setFont("Helvetica", 11)
        pdf.drawString(48, y, line)
        pdf.setStrokeColor(LINE)
        pdf.line(48, y - 11, 564, y - 11)
        y -= 29

    pdf.setFillColor(CREAM)
    pdf.roundRect(48, 220, 516, 72, 5, fill=1, stroke=0)
    pdf.setFillColor(INK)
    pdf.setFont("Helvetica-Bold", 11)
    pdf.drawString(64, 265, spec["total_label"])
    pdf.setFont("Helvetica", 9)
    pdf.setFillColor(MUTED)
    pdf.drawString(64, 245, spec["total_note"])
    pdf.setFillColor(accent)
    pdf.setFont("Helvetica-Bold", 29)
    pdf.drawRightString(548, 247, money(values[spec["total_key"]]))

    pdf.setFillColor(accent)
    pdf.setFont("Helvetica-Bold", 9)
    pdf.drawString(48, 195, "ABOUT THIS DOCUMENT")
    bottom = paragraph(pdf, spec["note"], 48, 177, 516)
    assert bottom > 82, "Note overlaps footer"

    pdf.setStrokeColor(LINE)
    pdf.line(48, 70, 564, 70)
    pdf.setFillColor(MUTED)
    pdf.setFont("Helvetica", 8)
    pdf.drawString(48, 55, "Not My Debt | Synthetic demo documents | Created with assistance from OpenAI Codex")
    pdf.drawString(48, 42, "For demonstration only. No payment, filing, or contact action is requested.")
    pdf.drawRightString(564, 42, "1 / 1")
    pdf.showPage()
    pdf.save()
    return {"kind": document.kind, "scenario": variant or "paid", "expected_fields": values}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "sample_documents")
    args = parser.parse_args()
    manifest = {
        "synthetic": True,
        "fixture_source": "src/not_my_debt/examples.py",
        "case": "Maya Ellis / MG-1042 / July 1, 2026",
        "files": {},
    }
    filenames = {
        "eob": "01_insurance_explanation.pdf",
        "bill": "02_provider_bill.pdf",
        "receipt": "03_payment_receipt.pdf",
        "collection": "04_collection_notice.pdf",
    }
    for document in example_documents("paid"):
        name = filenames[document.kind]
        manifest["files"][name] = create_pdf(args.output / name, document)
    for scenario in ("partial_payment", "wrong_account"):
        receipt = next(doc for doc in example_documents(scenario) if doc.kind == "receipt")
        name = f"variants/03_payment_receipt_{scenario}.pdf"
        manifest["files"][name] = create_pdf(args.output / name, receipt, scenario)
    (args.output / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(f"Created {len(manifest['files'])} fictional PDFs in {args.output}")


if __name__ == "__main__":
    main()
