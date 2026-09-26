"""Stateless JSON bridge for the Next.js UI.

Case input lives on stdin, never command arguments, caches, or application logs.
"""

import base64
import json
import os
import sys
from dataclasses import asdict
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, StrictBool

from not_my_debt.codex_adapter import codex_available
from not_my_debt.demo_documents import demo_cases
from not_my_debt.domain import FIELD_LABELS, KINDS, Document, Fact
from not_my_debt.examples import SCENARIOS
from not_my_debt.extract import extract_document, normalize_value, read_upload
from not_my_debt.packet import draft_letter, render_packet
from not_my_debt.reconcile import reconcile


class FactInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    value: str = Field(max_length=240)
    quote: str = Field(max_length=60000)
    page: int = Field(ge=1, le=100)
    confirmed: StrictBool
    origin: Literal["document", "user"]


class DocumentInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(min_length=1, max_length=100)
    kind: Literal["eob", "bill", "receipt", "collection"]
    title: str = Field(max_length=180)
    text: str = Field(max_length=60000)
    fields: dict[str, FactInput] = Field(max_length=25)
    included: StrictBool
    extraction_method: str = Field(max_length=180)
    warnings: list[str] = Field(max_length=100)


def documents_from_json(raw: list) -> list[Document]:
    if not isinstance(raw, list) or len(raw) > 16:
        raise ValueError("Use at most 16 documents for one case.")
    documents = []
    for item in raw:
        parsed = DocumentInput.model_validate(item)
        for key, fact in parsed.fields.items():
            if key not in FIELD_LABELS:
                raise ValueError("Choose a supported fact type.")
            if fact.confirmed:
                normalize_value(key, fact.value)
        documents.append(
            Document(
                **{
                    **parsed.model_dump(),
                    "fields": {
                        key: Fact(**fact.model_dump()) for key, fact in parsed.fields.items()
                    },
                }
            )
        )
    if len({doc.id for doc in documents}) != len(documents):
        raise ValueError("Each document needs a distinct identifier.")
    return documents


def handle_request(request: dict) -> dict:
    operation = request.get("operation")
    if operation == "bootstrap":
        research_path = Path(__file__).resolve().parents[2] / "data/research/research.json"
        examples, sources = demo_cases()
        return {
            "scenarios": SCENARIOS,
            "examples": examples,
            "document_sources": sources,
            "field_labels": FIELD_LABELS,
            "kinds": KINDS,
            "ai_available": bool(os.environ.get("OPENAI_API_KEY")),
            "codex_available": codex_available(),
            "research": json.loads(research_path.read_text()),
        }
    if operation == "extract":
        text = request.get("text", "")
        if "file" in request:
            content = base64.b64decode(request["file"], validate=True)
            text = read_upload(content, request.get("filename", ""))
        doc = extract_document(
            text,
            request.get("kind", ""),
            request.get("title", "Document"),
            method=request.get("method", "local"),
        )
        # No extraction is automatically approved for the user's packet.
        for fact in doc.fields.values():
            fact.confirmed = False
        return {"document": asdict(doc)}
    if operation not in {"reconcile", "packet"}:
        raise ValueError("Choose a supported operation.")
    documents = documents_from_json(request.get("documents", []))
    result = reconcile(documents)
    if operation == "reconcile":
        return {
            "result": asdict(result),
            "drafts": {
                key: draft_letter(documents, result, key) for key in ("provider", "collector")
            },
        }
    if request.get("reviewed") is not True:
        raise ValueError("Review the draft and supporting facts before exporting.")
    if not any(doc.included and doc.fields for doc in documents):
        raise ValueError("Include and review at least one document before exporting.")
    if any(not fact.confirmed for doc in documents if doc.included for fact in doc.fields.values()):
        raise ValueError("Review all included facts before exporting.")
    letter = request.get("letter")
    if not isinstance(letter, str) or len(letter) > 60000:
        raise ValueError("Use a draft shorter than 60,000 characters.")
    recipient = request.get("recipient", "provider")
    if recipient not in {"provider", "collector"}:
        raise ValueError("Choose provider or collector.")
    return {"html": render_packet(documents, result, recipient, letter_override=letter)}


def main() -> None:
    request = None
    try:
        request = json.loads(sys.stdin.read(14 * 1024 * 1024))
        response = handle_request(request)
    except Exception:
        # Validation and provider errors may contain case text; never echo them.
        message = "The request could not be completed. Check your fields, file, and review status."
        if isinstance(request, dict) and request.get("operation") == "extract":
            message = (
                "Document extraction failed. Check the selected method's setup, sign-in, "
                "usage, file, and connection; then retry. No alternate extractor was used."
            )
        response = {"error": message}
    sys.stdout.write(json.dumps(response))


if __name__ == "__main__":
    main()
