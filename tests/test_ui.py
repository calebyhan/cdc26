"""Presentation workflow checks on fictional records."""

from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from not_my_debt.domain import Document, Fact
from not_my_debt.reconcile import reconcile


def click(app, label):
    next(button for button in app.button if button.label == label).click().run()
    assert not app.exception


def start():
    app = AppTest.from_file(Path(__file__).resolve().parents[1] / "streamlit_app.py").run()
    assert not app.exception
    return app


def test_demo_receipt_changes_finding_and_export_requires_review():
    app = start()
    click(app, "Review the evidence →")
    assert "possible_uncredited_payment" in {
        f.code for f in reconcile(app.session_state["nmd_documents"]).findings
    }
    assert any("Account reference: MG-1042" in m.value for m in app.markdown)
    app.toggle[0].set_value(False).run()
    assert not app.exception
    result = reconcile(app.session_state["nmd_documents"])
    assert "possible_uncredited_payment" not in {f.code for f in result.findings}
    assert "missing_payment_evidence" in {f.code for f in result.findings}
    assert any("Payment evidence is missing." in m.value for m in app.markdown)
    click(app, "Prepare a response →")
    assert not app.get("download_button")
    assert "Provider payment receipt, 2026-07-20" not in app.text_area[0].value
    app.checkbox[0].check().run()
    assert len(app.get("download_button")) == 1
    app.radio(key="nmd_step").set_value("2 · Connect the records").run()
    app.toggle[0].set_value(True).run()
    click(app, "Prepare a response →")
    assert not app.checkbox[0].value
    assert "Provider payment receipt, 2026-07-20" in app.text_area[0].value


def test_reset_restores_case_recipient_and_requires_fresh_review():
    app = start()
    app.radio(key="nmd_step").set_value("3 · Prepare a response").run()
    app.radio(key="nmd_recipient").set_value("Debt collector").run()
    app.text_area[0].set_value("An edited rehearsal draft").run()
    app.checkbox[0].check().run()
    click(app, "Reset case")
    assert app.session_state["nmd_step"] == "1 · The case"
    assert all(d.included for d in app.session_state["nmd_documents"])
    app.radio(key="nmd_step").set_value("3 · Prepare a response").run()
    assert app.radio(key="nmd_recipient").value == "Provider billing office"
    assert "An edited rehearsal draft" not in app.text_area[0].value
    assert not app.checkbox[0].value
    assert not app.get("download_button")


def test_secondary_tools_keep_local_extraction_and_research_accessible():
    app = start()
    click(app, "Start an empty case")
    assert app.session_state["nmd_workspace"] == "Evidence & uploads"
    app.text_area[0].set_value("Account reference: MG-1042\nPatient responsibility: 150.00")
    click(app, "Extract for review")
    documents = app.session_state["nmd_documents"]
    assert len(documents) == 1
    assert not documents[0].fields["account"].confirmed
    assert documents[0].fields["account"].quote == "Account reference: MG-1042"
    app.selectbox(key="nmd_workspace").set_value("Research").run()
    assert not app.exception
    assert any("8,843" in m.value for m in app.markdown)


def test_extraction_defaults_to_local_and_only_offers_configured_services(monkeypatch):
    monkeypatch.setattr("not_my_debt.ui.codex_available", lambda: False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    app = start()
    click(app, "Start an empty case")
    picker = app.selectbox(key="nmd_extraction_method")
    assert picker.value == "local"
    assert picker.options == ["Local parser (no network)"]
    assert any("Codex CLI was not found" in caption.value for caption in app.caption)
    assert any("OPENAI_API_KEY is not configured" in caption.value for caption in app.caption)


@pytest.mark.parametrize("method", ["codex", "openai"])
def test_explicit_ai_selection_dispatches_once_and_requires_fact_review(monkeypatch, method):
    monkeypatch.setattr("not_my_debt.ui.codex_available", lambda: True)
    monkeypatch.setenv("OPENAI_API_KEY", "synthetic-test-key")
    calls = []

    def extract(text, kind, title, *, method):
        calls.append((text, kind, title, method))
        # Even an adapter that returns a confirmed fact must not bypass UI review.
        return Document(
            "synthetic-extraction",
            kind,
            title,
            text,
            {"account": Fact("MG-1042", "Account reference: MG-1042", confirmed=True)},
        )

    monkeypatch.setattr("not_my_debt.ui.extract_document", extract)
    app = start()
    click(app, "Start an empty case")
    assert app.selectbox(key="nmd_extraction_method").value == "local"
    assert calls == []
    app.selectbox(key="nmd_extraction_method").set_value(method).run()
    assert not app.exception
    assert calls == []
    captions = " ".join(caption.value for caption in app.caption)
    if method == "codex":
        assert "Sends this document’s text to OpenAI" in captions
        assert "ChatGPT sign-in and plan usage" in captions
        assert "Internet required" in captions
    else:
        assert "Sends this document’s text to OpenAI" in captions
    app.text_area[0].set_value("Account reference: MG-1042")
    click(app, "Extract for review")
    assert len(calls) == 1
    assert calls[0][-1] == method
    documents = app.session_state["nmd_documents"]
    assert len(documents) == 1
    assert not documents[0].fields["account"].confirmed
    assert documents[0].fields["account"].quote == "Account reference: MG-1042"
    assert not app.get("download_button")


def test_codex_error_is_visible_without_fallback_or_document_insertion(monkeypatch):
    monkeypatch.setattr("not_my_debt.ui.codex_available", lambda: True)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    calls = []

    def fail(text, kind, title, *, method):
        calls.append(method)
        raise RuntimeError("Sign in to Codex with ChatGPT, then try again.")

    monkeypatch.setattr("not_my_debt.ui.extract_document", fail)
    app = start()
    click(app, "Start an empty case")
    app.selectbox(key="nmd_extraction_method").set_value("codex").run()
    app.text_area[0].set_value("Account reference: MG-1042")
    click(app, "Extract for review")
    assert calls == ["codex"]
    assert not app.session_state["nmd_documents"]
    assert app.selectbox(key="nmd_extraction_method").value == "codex"
    assert any("Sign in to Codex" in error.value for error in app.error)
    assert any("No alternate extraction method was used" in caption.value for caption in app.caption)


def test_codex_becoming_unavailable_blocks_submission_without_switching(monkeypatch):
    installed = {"value": True}
    monkeypatch.setattr("not_my_debt.ui.codex_available", lambda: installed["value"])
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    app = start()
    click(app, "Start an empty case")
    app.selectbox(key="nmd_extraction_method").set_value("codex").run()
    installed["value"] = False
    app.run()
    assert not app.exception
    assert app.selectbox(key="nmd_extraction_method").value == "codex"
    assert next(button for button in app.button if button.label == "Extract for review").disabled
    assert any("no longer available" in warning.value for warning in app.warning)
    app.selectbox(key="nmd_extraction_method").set_value("local").run()
    assert not app.exception
    assert not next(button for button in app.button if button.label == "Extract for review").disabled
