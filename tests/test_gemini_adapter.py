"""Gemini transport checks: schema shape, model chain, and sanitized failures (no network)."""

import io
import json
import urllib.error

import pytest

from not_my_debt import extract, gemini_adapter


def http_error(code: int) -> urllib.error.HTTPError:
    return urllib.error.HTTPError("https://example.invalid", code, "x", {}, io.BytesIO(b"{}"))


def test_inline_schema_resolves_refs_and_drops_unsupported_keywords():
    schema = extract.Extraction.model_json_schema()
    inlined = gemini_adapter.inline_schema(schema)
    text = json.dumps(inlined)
    assert "$ref" not in text and "$defs" not in text
    assert "additionalProperties" not in text and '"title"' not in text
    assert inlined["properties"]["fields"]["items"]["required"] == ["key", "value", "quote", "page"]


def test_inline_schema_keeps_fields_named_title():
    from not_my_debt.case_analysis import CaseExplanation

    inlined = gemini_adapter.inline_schema(CaseExplanation.model_json_schema())
    issue = inlined["properties"]["issues"]["items"]
    assert "title" in issue["properties"]
    assert set(issue["required"]) <= set(issue["properties"])


def test_quota_errors_move_through_the_model_chain(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.setenv("GEMINI_MODELS", "first,second")
    monkeypatch.setattr(gemini_adapter.time, "sleep", lambda _: None)
    calls = []

    def fake_post(model, body, timeout):
        calls.append(model)
        if model == "first":
            raise http_error(429)
        return {"candidates": [{"content": {"parts": [{"text": "{}"}]}}]}

    monkeypatch.setattr(gemini_adapter, "_post", fake_post)
    _, model = gemini_adapter.generate({})
    assert model == "second"
    assert calls == ["first", "second"]  # no retry on an exhausted quota


def test_exhausted_quota_reports_a_safe_message(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "secret-key-value")
    monkeypatch.setenv("GEMINI_MODELS", "only")
    monkeypatch.setattr(gemini_adapter.time, "sleep", lambda _: None)
    monkeypatch.setattr(
        gemini_adapter, "_post", lambda *a: (_ for _ in ()).throw(http_error(429))
    )
    with pytest.raises(gemini_adapter.GeminiError) as error:
        gemini_adapter.generate({"contents": "Patient: Maya Ellis"})
    assert "usage limit" in str(error.value)
    assert "Maya" not in str(error.value) and "secret" not in str(error.value)


def test_missing_key_is_reported_without_a_request(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    with pytest.raises(gemini_adapter.GeminiError, match="GEMINI_API_KEY"):
        gemini_adapter.generate({})


def test_gemini_extraction_still_requires_verifiable_quotes(monkeypatch):
    text = "Receipt\nAmount paid: $150.00\nPayment status: Posted"
    output = {
        "fields": [
            {"key": "payment_amount", "value": "150.00", "quote": "Amount paid: $150.00", "page": 1},
            {"key": "payment_date", "value": "2025-03-02", "quote": "Paid on 2025-03-02", "page": 1},
        ],
        "warnings": [],
    }
    monkeypatch.setattr(
        "not_my_debt.gemini_adapter.generate_json",
        lambda *a, **k: (json.dumps(output), "test-model"),
    )
    doc = extract.extract_document(text, "receipt", "Receipt", method="gemini")
    assert doc.extraction_method == "Google Gemini structured extraction"
    assert set(doc.fields) == {"payment_amount"}  # the invented quote is discarded
    assert any("could not be verified" in w for w in doc.warnings)
