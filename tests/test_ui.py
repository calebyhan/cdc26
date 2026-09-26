"""Presentation workflow checks on fictional records."""

from pathlib import Path

from streamlit.testing.v1 import AppTest

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
    click(app, "Reset demo")
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
