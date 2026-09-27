"""Measure local extraction on Maya's fictional documents rendered in varied layouts.

Each document is drawn with PyMuPDF in six layouts that real bills use (table rows,
stacked labels, leader dots, two-column grids, an image-only scan, and a phone-style
photo). Field recall and precision are computed against the fixture values.
Pass --baseline-ref to also score the parser at an earlier Git revision.

    uv run python scripts/measure_layouts.py [--baseline-ref HEAD] [--out data/benchmark/layouts.json]

These are synthetic layouts of fictional documents: a regression check for the
parser, not an accuracy estimate on real patient paperwork.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import subprocess
import sys
import tempfile
import time
from datetime import date
from pathlib import Path

import pymupdf

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from not_my_debt.document_text import read_document  # noqa: E402
from not_my_debt.examples import example_documents  # noqa: E402
from not_my_debt.extract import extract_document  # noqa: E402

LABELS = {
    "provider": "Provider",
    "patient": "Patient Name",
    "account": "Account #",
    "claim_id": "Claim Number",
    "service_date": "Date of Service",
    "statement_date": "Statement Date",
    "charges": "Total Charges",
    "adjustments": "Network Discount",
    "allowed": "Allowed Amount",
    "insurer_paid": "Plan Paid",
    "patient_responsibility": "Amount You Owe",
    "patient_paid": "Patient Payments",
    "balance": "Balance Due",
    "payment_amount": "Amount Paid",
    "payment_date": "Payment Date",
    "payment_reference": "Confirmation #",
    "payment_status": "Status",
    "collector": "Collection Agency",
    "validation_end": "Respond By",
}
KIND_LABELS = {"collection": {"balance": "Amount of Debt"}}
TITLES = {
    "eob": "Explanation of Benefits",
    "bill": "Patient Statement",
    "receipt": "Payment Receipt",
    "collection": "Notice of Debt",
}
REDUCTIONS = {"adjustments", "insurer_paid", "patient_paid"}
LAYOUTS = ["table", "stacked", "leaders", "grid", "scan", "photo"]


def display(key: str, value: str, layout: str) -> str:
    if key in {"service_date", "statement_date", "payment_date", "validation_end"}:
        d = date.fromisoformat(value)
        return d.strftime("%m/%d/%Y") if layout in {"table", "scan", "grid"} else d.strftime("%B %-d, %Y")
    if key in {
        "charges", "adjustments", "allowed", "insurer_paid", "patient_responsibility",
        "patient_paid", "balance", "payment_amount",
    }:
        amount = f"${float(value):,.2f}"
        return f"-{amount}" if key in REDUCTIONS and layout in {"table", "scan"} else amount
    return value


def draw(kind: str, facts: dict[str, str], layout: str) -> pymupdf.Document:
    doc = pymupdf.open()
    page = doc.new_page(width=612, height=792)
    page.insert_text((72, 72), facts.get("provider", "Billing office"), fontsize=15)
    page.insert_text((72, 94), TITLES[kind], fontsize=11)
    y = 140
    labels = {**LABELS, **KIND_LABELS.get(kind, {})}
    items = [(labels[k], display(k, v, layout)) for k, v in facts.items()]
    base = "grid" if layout == "grid" else "table" if layout in {"table", "scan", "photo"} else layout
    if base == "grid":
        for i in range(0, len(items), 2):
            for col, (label, value) in enumerate(items[i : i + 2]):
                page.insert_text((72 + col * 270, y), f"{label}:", fontsize=10)
                page.insert_text((72 + col * 270 + 115, y), value, fontsize=10)
            y += 22
    else:
        for label, value in items:
            if base == "table":
                page.insert_text((72, y), label, fontsize=10.5)
                width = pymupdf.get_text_length(value, fontsize=10.5)
                page.insert_text((540 - width, y), value, fontsize=10.5)
                y += 22
            elif base == "stacked":
                page.insert_text((72, y), label.upper(), fontsize=8)
                page.insert_text((72, y + 14), value, fontsize=11.5)
                y += 36
            else:
                page.insert_text((72, y), f"{label} {'.' * 40} {value}", fontsize=10.5)
                y += 22
    page.insert_text((72, 740), "Questions? Call the billing office. Keep this notice for your records.", fontsize=8)
    return doc


def rendered(kind: str, facts: dict[str, str], layout: str) -> tuple[bytes, str]:
    doc = draw(kind, facts, layout)
    if layout == "scan":
        pix = doc[0].get_pixmap(dpi=150)
        scan = pymupdf.open()
        page = scan.new_page(width=612, height=792)
        page.insert_image(page.rect, stream=pix.tobytes("png"))
        return scan.tobytes(), "scan.pdf"
    if layout == "photo":
        return doc[0].get_pixmap(dpi=150).tobytes("png"), "photo.png"
    return doc.tobytes(), f"{layout}.pdf"


def load_parser(ref: str):
    """Import extract.py (and pypdf reading) as it was at ``ref``."""
    source = subprocess.run(
        ["git", "show", f"{ref}:src/not_my_debt/extract.py"],
        cwd=ROOT, check=True, capture_output=True, text=True,
    ).stdout
    path = Path(tempfile.mkdtemp()) / "extract_baseline.py"
    path.write_text(source)
    spec = importlib.util.spec_from_file_location("extract_baseline", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def score(extracted: dict[str, str], expected: dict[str, str]) -> dict:
    correct = sum(extracted.get(k) == v for k, v in expected.items())
    return {"expected": len(expected), "extracted": len(extracted), "correct": correct}


def run(baseline_ref: str | None) -> dict:
    baseline = load_parser(baseline_ref) if baseline_ref else None
    documents = {doc.kind: {k: f.value for k, f in doc.fields.items()} for doc in example_documents("paid")}
    results = {layout: {"current": [], "baseline": []} for layout in LAYOUTS}
    started = time.time()
    for layout in LAYOUTS:
        for kind, facts in documents.items():
            content, filename = rendered(kind, facts, layout)
            text = read_document(content, filename).text
            doc = extract_document(text, kind, kind, method="local")
            results[layout]["current"].append(score({k: f.value for k, f in doc.fields.items()}, facts))
            if baseline:
                try:
                    old_text = baseline.read_upload(content, filename)
                    old = baseline.extract_document(old_text, kind, kind, method="local")
                    got = {k: f.value for k, f in old.fields.items()}
                except ValueError:
                    got = {}
                results[layout]["baseline"].append(score(got, facts))
    summary = {}
    for layout, runs in results.items():
        summary[layout] = {}
        for name, rows in runs.items():
            if not rows:
                continue
            expected = sum(r["expected"] for r in rows)
            extracted = sum(r["extracted"] for r in rows)
            correct = sum(r["correct"] for r in rows)
            summary[layout][name] = {
                "fields_expected": expected,
                "fields_correct": correct,
                "fields_extracted": extracted,
                "recall": round(correct / expected, 3),
                "precision": round(correct / extracted, 3) if extracted else None,
            }
    return {
        "description": "Local extraction on Maya's four fictional documents drawn in six layouts.",
        "baseline_ref": baseline_ref,
        "seconds": round(time.time() - started, 1),
        "layouts": summary,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--baseline-ref")
    parser.add_argument("--out")
    args = parser.parse_args()
    result = run(args.baseline_ref)
    text = json.dumps(result, indent=1)
    if args.out:
        Path(args.out).write_text(text + "\n")
    print(text)


if __name__ == "__main__":
    main()
