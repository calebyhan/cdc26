"""Link public fictional PDF sources to exact demo fixtures. Built with OpenAI Codex."""

import json
from dataclasses import asdict
from pathlib import Path

from not_my_debt.examples import SCENARIOS, example_documents
from not_my_debt.extract import extract_document, read_upload

ROOT = Path(__file__).resolve().parents[2] / "sample_documents"


def demo_cases() -> tuple[dict, dict]:
    """Preconfirm known fictional PDFs only; user-upload extraction stays unreviewed.

    Versions without a matching PDF retain the explicit text fixture. Never show
    the original paid bill as the source for a later, zero-balance statement.
    """
    manifest = json.loads((ROOT / "manifest.json").read_text())
    if manifest.get("synthetic") is not True:
        raise ValueError("Demo sources must be explicitly fictional.")
    examples, sources = {}, {}
    for scenario in SCENARIOS:
        documents = example_documents(scenario)
        sources[scenario] = {}
        for doc in documents:
            values = {key: fact.value for key, fact in doc.fields.items()}
            filename = next(
                (
                    name
                    for name, spec in manifest["files"].items()
                    if spec["kind"] == doc.kind and spec["expected_fields"] == values
                ),
                None,
            )
            if filename is None:
                continue
            extracted = extract_document(
                read_upload((ROOT / filename).read_bytes(), filename),
                doc.kind,
                doc.title,
            )
            if {key: fact.value for key, fact in extracted.fields.items()} != values:
                raise ValueError("A fictional PDF no longer matches its fixture.")
            doc.text, doc.fields = extracted.text, extracted.fields
            doc.extraction_method = "PDF · Local parser"
            for fact in doc.fields.values():
                fact.confirmed = True
            sources[scenario][doc.id] = filename
        examples[scenario] = [asdict(doc) for doc in documents]
    return examples, sources
