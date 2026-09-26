"""Source-linked medical billing workspace."""

from __future__ import annotations

import html
import json
import os
from dataclasses import asdict
from datetime import date
from hashlib import sha256
from pathlib import Path

import pandas as pd
import streamlit as st

from .domain import FIELD_LABELS, KINDS, MONEY_FIELDS, Document, Fact, dollars, money_cents
from .examples import example_documents
from .extract import extract_document, read_upload
from .packet import draft_letter, render_packet
from .reconcile import reconcile

ROOT = Path(__file__).resolve().parents[2]
SCENARIOS = {
    "paid": "Paid, then sent to collections",
    "missing_receipt": "What if the receipt is missing?",
    "wrong_account": "A receipt for another account",
    "partial_payment": "Only part of the balance was paid",
    "duplicate_receipt": "Two copies of the same payment",
    "no_discrepancy": "Records that agree",
}
STEPS = ["1 · The case", "2 · Connect the records", "3 · Prepare a response"]
WORKSPACES = ["Presentation demo", "Evidence & uploads", "Research"]
DOC_ICONS = {"eob": "01", "bill": "02", "receipt": "03", "collection": "04"}
CMS_URL = "https://www.cms.gov/initiatives/your-patient-rights/medical-bill-rights/get-help/medical-bill-guides-resources/how-read-health-insurance-explanation-benefits"
CFPB_URL = "https://www.consumerfinance.gov/ask-cfpb/what-should-i-do-when-a-debt-collector-contacts-me-en-1695/"

STYLE = """
<style>

html, body, [class*="css"], .stApp {font-family:'DM Sans',sans-serif;}
.stApp {background:#FAF9F5;color:#153C3A;}
.block-container {max-width:1180px;padding-top:1.5rem;padding-bottom:3rem;}
h1, h2, h3 {color:#153C3A;letter-spacing:-.035em;}
h1 {font-family:'DM Serif Display',Georgia,serif!important;font-weight:400!important;font-size:2.8rem!important;line-height:1.06!important;}
h2 {font-size:1.8rem!important;} h3 {font-size:1.25rem!important;}
[data-testid="stSidebar"] {background:#EDEEE5;border-right:1px solid #DCDDD1;}
[data-testid="stSidebar"] .block-container {padding-top:2rem;}
[data-baseweb="tab-list"] {gap:1.8rem;border-bottom:1px solid #DADFD4;margin-bottom:1.25rem;}
[data-baseweb="tab"] {font-size:.95rem;padding:12px 0;}
[data-baseweb="tab-highlight"] {background-color:#0C7168;}
.eyebrow {color:#54736A;font-size:.7rem;font-weight:700;letter-spacing:.15em;text-transform:uppercase;margin-bottom:.6rem;}
.brand {color:#153C3A;font-size:1.45rem;font-weight:700;letter-spacing:-.06em;margin-bottom:.15rem;}
.brand span {color:#C7664A;}
.subtle {color:#687A72;font-size:.9rem;line-height:1.55;}
.hero {background:#123F3B;border-radius:18px;padding:1.5rem 1.8rem;margin:.8rem 0 1.2rem;color:#FAF8F3;position:relative;overflow:hidden;}
.hero .eyebrow {color:#B5CEC2;}.hero h2 {color:#FAF8F3!important;font-family:'DM Serif Display',Georgia,serif!important;font-size:2.05rem!important;font-weight:400!important;margin:0 0 .6rem!important;padding:0!important;letter-spacing:-.025em;}
.hero p {color:#D7E3D9;max-width:770px;margin:0;font-size:1rem;line-height:1.55;}
.tag {display:inline-block;background:#E7EBDB;color:#42634F;padding:.35rem .65rem;border-radius:6px;font-size:.7rem;font-weight:700;letter-spacing:.055em;}
.tag-coral {background:#F4E1D5;color:#965138;}
.stat {background:#FFFFFF99;border:1px solid #DDE1D5;border-radius:12px;padding:1rem 1.1rem;min-height:110px;}
.stat-label {font-size:.74rem;color:#63766D;margin-bottom:.45rem;}
.stat-value {color:#153C3A;font-family:'DM Serif Display',Georgia,serif;font-size:2rem;line-height:1.2;}
.stat-foot {color:#718077;font-size:.73rem;margin-top:.3rem;}
.doc-num {color:#AF6449;font-size:.75rem;font-weight:700;letter-spacing:.1em;}
.source-quote {border-left:3px solid #B5C7B3;padding:.7rem 1rem;background:#F0F1E9;color:#3E574F;font-size:.9rem;border-radius:0 6px 6px 0;white-space:pre-wrap;}
.ledger {border:1px solid #DAE0D4;border-radius:12px;overflow:hidden;margin:.6rem 0 1rem;}
.ledger-row {display:flex;justify-content:space-between;gap:1rem;padding:.8rem 1rem;border-bottom:1px solid #E2E6DC;background:#FFFFFF80;font-size:.9rem;}
.ledger-row:last-child {border-bottom:0;}.ledger-total {background:#E3EBDD;font-weight:700;}
.footer-note {font-size:.75rem;color:#708176;border-top:1px solid #D9DFD3;padding-top:1rem;margin-top:2.5rem;}
div[data-testid="stMetric"] {background:#FFFFFF80;border:1px solid #DAE0D4;border-radius:12px;padding:.8rem;}
.stButton>button,.stDownloadButton>button {border-radius:8px;font-weight:600;}
[data-testid="stExpander"] {border-color:#D9DFD3;background:#FFFFFF45;border-radius:10px;}
.stAlert {border-radius:10px;}
@media(max-width:700px){h1{font-size:2.1rem!important}.hero{padding:1.2rem}.hero h2{font-size:1.6rem!important}.ledger-row{flex-wrap:wrap}}
</style>
"""


def _safe(value: object) -> str:
    return html.escape(str(value))


def _docs() -> list[Document]:
    return st.session_state["nmd_documents"]


def _fingerprint(documents: list[Document]) -> str:
    serialized = json.dumps([asdict(doc) for doc in documents], sort_keys=True, default=str)
    return sha256(serialized.encode()).hexdigest()[:14]


def _reset_review_state() -> None:
    for key in list(st.session_state):
        if key.startswith(("draft_", "review_", "include_")):
            del st.session_state[key]


def _go_step(step: str) -> None:
    st.session_state["nmd_step"] = step


def _load_case(scenario: str) -> None:
    _reset_review_state()
    st.session_state["nmd_workspace"] = WORKSPACES[0]
    st.session_state["nmd_step"] = STEPS[0]
    st.session_state["nmd_recipient"] = "Provider billing office"
    st.session_state["nmd_documents"] = example_documents(scenario=scenario)
    st.session_state["nmd_fictional"] = True
    st.session_state["nmd_scenario"] = scenario
    st.session_state["nmd_generation"] = st.session_state.get("nmd_generation", 0) + 1


def _clear_case() -> None:
    _reset_review_state()
    st.session_state["nmd_workspace"] = WORKSPACES[1]
    st.session_state["nmd_documents"] = []
    st.session_state["nmd_fictional"] = False
    st.session_state["nmd_generation"] += 1


def _toggle_document(doc_id: str, widget_key: str) -> None:
    for doc in _docs():
        if doc.id == doc_id:
            doc.included = st.session_state[widget_key]
            break


def _stat(label: str, value: str, foot: str = "") -> None:
    st.markdown(
        f'<div class="stat"><div class="stat-label">{_safe(label)}</div>'
        f'<div class="stat-value">{_safe(value)}</div><div class="stat-foot">{_safe(foot)}</div></div>',
        unsafe_allow_html=True,
    )


def _reset_demo() -> None:
    _load_case("paid")
    st.session_state["nmd_scenario_picker"] = "paid"


def _sidebar() -> None:
    with st.sidebar:
        st.markdown(
            '<div class="brand">not my debt<span>.</span></div><div class="subtle">Make the paperwork make sense.</div>',
            unsafe_allow_html=True,
        )
        st.divider()
        st.selectbox("Workspace", WORKSPACES, key="nmd_workspace")
        st.button("Reset demo", width="stretch", on_click=_reset_demo)
        st.caption("Returns to Maya’s original fictional case and clears draft edits and review.")
        with st.expander("More cases & tools"):
            scenario = st.selectbox(
                "Explore another scenario",
                list(SCENARIOS),
                format_func=SCENARIOS.get,
                key="nmd_scenario_picker",
            )
            st.button("Load fictional case", width="stretch", on_click=_load_case, args=(scenario,))
            st.button("Start an empty case", width="stretch", on_click=_clear_case)
        st.divider()
        st.caption("One provider · one account · one visit")
        st.caption("All example people, documents, dates, and amounts are fictional.")
        st.caption(
            "Findings describe supplied records. The provider’s current ledger and legal liability remain unconfirmed."
        )


def _unconfirmed(documents: list[Document]) -> list[tuple[Document, str]]:
    return [
        (doc, key)
        for doc in documents
        if doc.included
        for key, fact in doc.fields.items()
        if not fact.confirmed
    ]


def _case(documents: list[Document]) -> None:
    demo = st.session_state["nmd_fictional"] and st.session_state.get("nmd_scenario") == "paid"
    title = "Maya paid. Then a collection notice arrived." if demo else "Start with the records."
    description = (
        "Her provider bill said her share was $150. She paid it and kept the receipt. "
        "A month later, a collector asked for the same $150. What do her records support?"
        if demo
        else "Connect the insurance explanation, provider bill, payment evidence, and collection notice to see what needs clarification."
    )
    st.markdown(
        f'<div class="hero"><div class="eyebrow">ONE ACCOUNT. FOUR RECORDS.</div>'
        f"<h2>{_safe(title)}</h2><p>{_safe(description)}</p></div>",
        unsafe_allow_html=True,
    )
    if not documents:
        st.info("Add documents in Evidence & uploads, or use Reset demo to load Maya’s case.")
        return
    st.subheader("The paperwork, in one place")
    captions = {
        "eob": ("patient_responsibility", "Patient responsibility · not proof of payment"),
        "bill": ("balance", "Balance on the provider statement"),
        "receipt": ("payment_amount", "Payment recorded on the receipt"),
        "collection": ("balance", "Amount requested in the notice"),
    }
    for offset in range(0, len(documents), 4):
        columns = st.columns(min(4, len(documents) - offset))
        for column, doc in zip(columns, documents[offset : offset + 4]):
            with column, st.container(border=True):
                st.markdown(
                    f'<div class="doc-num">{_safe(DOC_ICONS.get(doc.kind, "•"))} / '
                    f"{_safe(KINDS.get(doc.kind, doc.kind).upper())}</div>",
                    unsafe_allow_html=True,
                )
                field, caption = captions.get(doc.kind, ("balance", "Document amount"))
                fact = doc.fields.get(field)
                amount = "Unknown"
                if fact and fact.confirmed:
                    try:
                        amount = dollars(money_cents(fact.value))
                    except ValueError:
                        amount = "Needs correction"
                st.subheader(amount)
                st.caption(caption)
                dated = doc.fields.get("statement_date")
                if dated and dated.confirmed:
                    st.caption(dated.value)
                if not doc.included:
                    st.caption("Excluded from analysis")
                with st.expander("Read source"):
                    st.text(doc.text)
    st.caption("Fictional examples are preconfirmed. New documents require your review before use.")
    st.button("Review the evidence →", type="primary", on_click=_go_step, args=(STEPS[1],))


def _finding_summary(documents: list[Document], result) -> None:
    finding = next(
        (item for item in result.findings if item.code == "possible_uncredited_payment"), None
    )
    if finding:
        title = f"A {dollars(result.applied_payments_cents)} payment may not have been credited."
        description = (
            "The completed receipt matches the account and encounter, and falls after the bill "
            "but before the collection notice. Ask the provider to confirm how it was credited."
        )
    elif any(item.code == "missing_payment_evidence" for item in result.findings):
        title = "Payment evidence is missing."
        description = (
            "We can’t confirm that this balance was paid. The insurance explanation describes "
            "patient responsibility; it does not prove a patient payment."
        )
    else:
        title = "Here’s what the supplied records support."
        description = "Review the findings and their sources below. Missing or conflicting evidence needs clarification."
    st.markdown(
        f'<div class="hero"><div class="eyebrow">THE EVIDENCE CHECK</div>'
        f"<h2>{_safe(title)}</h2><p>{_safe(description)}</p></div>",
        unsafe_allow_html=True,
    )
    if finding:
        with st.expander("Why this payment matches · inspect the evidence"):
            identity_refs = [
                f"{doc.id}.{field}"
                for doc in documents
                if doc.included and doc.id in result.matched_document_ids
                for field in ("account", "provider", "service_date", "payment_status")
                if field in doc.fields
            ]
            _show_refs(identity_refs + finding.refs, documents, "summary")


def _connect(documents: list[Document], result) -> None:
    receipts = [doc for doc in documents if doc.kind == "receipt"]
    for doc in receipts:
        key = f"include_{st.session_state['nmd_generation']}_{doc.id}"
        st.toggle(
            "Include payment receipt" if len(receipts) == 1 else f"Include {doc.title}",
            value=doc.included,
            key=key,
            on_change=_toggle_document,
            args=(doc.id, key),
            help="Exclude the receipt to see which findings can still be supported.",
        )
    _finding_summary(documents, result)
    _findings(documents, result)
    if documents:
        st.button("Prepare a response →", type="primary", on_click=_go_step, args=(STEPS[2],))


def _validate_field(key: str, value: str) -> None:
    if key in MONEY_FIELDS:
        money_cents(value)
    if key in {"service_date", "statement_date", "payment_date", "validation_end"}:
        try:
            date.fromisoformat(value)
        except ValueError as exc:
            raise ValueError("Use YYYY-MM-DD for dates; leave unknown dates blank.") from exc


def _fact_editor(doc: Document) -> None:
    generation = st.session_state["nmd_generation"]
    with st.expander(f"{KINDS.get(doc.kind, doc.kind)} · {doc.title}", expanded=len(_docs()) == 1):
        st.caption(
            f"{doc.extraction_method} · {'Included in analysis' if doc.included else 'Excluded from analysis'}"
        )
        for warning in doc.warnings:
            st.warning(warning)
        if doc.fields:
            rows = [
                {
                    "field": FIELD_LABELS.get(key, key),
                    "value": fact.value,
                    "reviewed": fact.confirmed,
                    "source": f"p. {fact.page} · {fact.quote}"
                    if fact.quote
                    else "User-supplied; no document passage",
                    "key": key,
                }
                for key, fact in doc.fields.items()
            ]
            with st.form(f"facts_{generation}_{doc.id}"):
                edited = st.data_editor(
                    rows,
                    hide_index=True,
                    width="stretch",
                    column_order=["field", "value", "reviewed", "source"],
                    disabled=["field", "source", "key"],
                    column_config={
                        "field": st.column_config.TextColumn("Fact", width="medium"),
                        "value": st.column_config.TextColumn("Value", width="medium"),
                        "reviewed": st.column_config.CheckboxColumn("Reviewed", width="small"),
                        "source": st.column_config.TextColumn("Original passage", width="large"),
                    },
                    key=f"editor_{generation}_{doc.id}_{sha256(json.dumps(rows, sort_keys=True).encode()).hexdigest()[:10]}",
                )
                confirm_all = st.checkbox(
                    "I checked every value above against this document",
                    key=f"bulk_{generation}_{doc.id}",
                )
                st.caption(
                    "Editing a value records it as your correction. The original passage is preserved. Blank values become unknown."
                )
                submitted = st.form_submit_button("Save reviewed facts", type="primary")
                if submitted:
                    problems = []
                    for row in edited:
                        value = str(row["value"] or "").strip()
                        if value:
                            try:
                                _validate_field(row["key"], value)
                            except ValueError as exc:
                                problems.append(f"{row['field']}: {exc}")
                    if problems:
                        for problem in problems:
                            st.error(problem)
                    else:
                        for row in edited:
                            key, value = row["key"], str(row["value"] or "").strip()
                            previous = doc.fields[key]
                            if not value:
                                del doc.fields[key]
                            else:
                                changed = value != previous.value
                                doc.fields[key] = Fact(
                                    value=value,
                                    quote=previous.quote,
                                    page=previous.page,
                                    confirmed=bool(changed or confirm_all or row["reviewed"]),
                                    origin="user" if changed else previous.origin,
                                )
                        st.rerun()
        else:
            st.info(
                "No supported labeled fields were extracted. Add confirmed facts below, or use a supported labeled-text example."
            )
        missing = [key for key in FIELD_LABELS if key not in doc.fields]
        if missing:
            with st.popover("Add a missing fact"):
                with st.form(f"add_fact_{generation}_{doc.id}"):
                    selected = st.selectbox("Fact", missing, format_func=FIELD_LABELS.get)
                    value = st.text_input(
                        "Confirmed value",
                        help="Use YYYY-MM-DD for dates and a dollar amount such as 150.00.",
                    )
                    passage = st.text_input(
                        "Supporting passage (optional)",
                        help="Paste the exact passage if present. Otherwise this is recorded as your statement.",
                    )
                    if st.form_submit_button("Add confirmed fact"):
                        try:
                            if not value.strip():
                                raise ValueError("Enter the value you confirmed.")
                            _validate_field(selected, value.strip())
                            doc.fields[selected] = Fact(
                                value=value.strip(),
                                quote=passage.strip(),
                                confirmed=True,
                                origin="user",
                            )
                            st.rerun()
                        except ValueError as exc:
                            st.error(str(exc))
        with st.expander("Read the original document"):
            st.text(doc.text)


def _add_documents() -> None:
    with st.expander("Add a document", expanded=not _docs()):
        st.caption(
            "Paste text or upload a text-based PDF/TXT. Scanned images and handwriting need transcription; OCR is not included."
        )
        with st.form("nmd_add_document"):
            left, right = st.columns(2)
            with left:
                kind = st.selectbox("Document role", list(KINDS), format_func=KINDS.get)
            with right:
                title = st.text_input("Document title", placeholder="e.g. April provider statement")
            source = st.radio("Input", ["Paste text", "Upload a text PDF or TXT"], horizontal=True)
            pasted = st.text_area(
                "Document text",
                height=150,
                placeholder="Paste the document text, including amounts, account reference, and dates.",
            )
            uploaded = st.file_uploader(
                "Text document",
                type=["pdf", "txt"],
                help="Maximum 8 MB. Uploaded text is held in this session.",
            )
            key_available = bool(os.environ.get("OPENAI_API_KEY"))
            use_model = st.checkbox(
                "Use OpenAI to propose fields from this document", disabled=not key_available
            )
            if key_available:
                st.caption(
                    "Opting in sends this document’s text to OpenAI. Local extraction runs without sending document text externally."
                )
            else:
                st.caption(
                    "Local labeled-field extraction is available. Model extraction is not configured for this session."
                )
            submitted = st.form_submit_button("Extract for review", type="primary")
        if submitted:
            try:
                if source == "Upload a text PDF or TXT":
                    if uploaded is None:
                        raise ValueError("Choose a text-based PDF or TXT file first.")
                    document_text = read_upload(uploaded.getvalue(), uploaded.name)
                else:
                    document_text = pasted.strip()
                if not document_text.strip():
                    raise ValueError(
                        "There is no readable text. Paste a transcription if this is a scanned document."
                    )
                with st.spinner("Extracting facts and preserving their sources…"):
                    doc = extract_document(
                        document_text,
                        kind,
                        title.strip() or KINDS[kind],
                        method="openai" if use_model else "local",
                    )
                # New input must pass human review even when a parser supplies optimistic flags.
                for fact in doc.fields.values():
                    fact.confirmed = False
                if any(previous.id == doc.id for previous in _docs()):
                    doc.id = f"{doc.id}-{len(_docs()) + 1}"
                _docs().append(doc)
                st.session_state["nmd_fictional"] = False
                st.rerun()
            except Exception as exc:
                st.error(f"Could not read this document: {exc}")


def _evidence(documents: list[Document]) -> None:
    st.subheader("Every fact has a starting point.")
    st.write(
        "Check the extraction, correct the values, and keep the original passage beside your changes."
    )
    _add_documents()
    for doc in documents:
        _fact_editor(doc)
    if documents:
        st.caption(
            "Corrections are user-confirmed statements. They do not alter the original document. Documents are stored in the active app session, not a shared case database."
        )


def _show_refs(refs: list[str], documents: list[Document], key: str) -> None:
    if not refs:
        st.caption("No supporting document passage is available.")
        return
    for index, ref in enumerate(dict.fromkeys(refs)):
        found = None
        for doc in documents:
            if ref == doc.id:
                found = (doc, None)
                break
            prefix = f"{doc.id}."
            if ref.startswith(prefix):
                found = (doc, doc.fields.get(ref[len(prefix) :]))
                break
        if found is None:
            st.caption(f"Evidence reference: {ref}")
            continue
        doc, fact = found
        if fact is None:
            with st.expander(doc.title):
                st.text(doc.text)
            continue
        st.markdown(f"**{doc.title} · page {fact.page}**")
        st.markdown(
            f'<div class="source-quote">{_safe(fact.quote or "No original passage: user-supplied information.")}</div>',
            unsafe_allow_html=True,
        )
        if fact.origin == "user":
            st.caption(
                f"User-confirmed value: {fact.value}. The original passage above is preserved."
            )
        else:
            st.caption(f"{'Reviewed' if fact.confirmed else 'Unreviewed'} value: {fact.value}")


def _findings(documents: list[Document], result) -> None:
    st.subheader("Follow the money")
    if not documents:
        st.info("Add documents in Evidence & uploads to begin.")
        return
    left, right = st.columns([1.08, 1], gap="large")
    with left:
        st.markdown("**The reconstructed ledger**")
        if result.ledger:
            for index, row in enumerate(result.ledger):
                if row.label == "Balance supported by supplied records":
                    continue
                amount_column, source_column = st.columns([4, 1], vertical_alignment="center")
                with amount_column:
                    st.markdown(
                        f'<div class="ledger-row"><span>{_safe(row.label)}</span><strong>{_safe(dollars(row.cents))}</strong></div>',
                        unsafe_allow_html=True,
                    )
                with source_column:
                    if row.refs:
                        with st.popover("Source", help=f"Source for {row.label}"):
                            _show_refs(row.refs, documents, f"ledger_{index}")
        else:
            st.info(
                "More confirmed account information is needed before the ledger can be reconstructed."
            )
        st.markdown(
            f'<div class="ledger-row ledger-total"><span>Balance supported by supplied records</span><strong>{_safe(dollars(result.supported_balance_cents))}</strong></div>',
            unsafe_allow_html=True,
        )
        st.caption(
            "This is not a live account balance. Later adjustments, reversals, and missing records can change the picture."
        )
        st.markdown(f"[Why an EOB is not proof of payment ↗]({CMS_URL})")
    with right:
        st.markdown("**What needs a closer look**")
        findings = sorted(
            result.findings, key=lambda item: item.code != "possible_uncredited_payment"
        )
        for index, finding in enumerate(findings):
            with st.container(border=True):
                st.write(f"**{finding.title}**")
                st.write(finding.detail.replace("$", r"\$"))
                with st.expander("Inspect supporting evidence"):
                    _show_refs(finding.refs, documents, f"finding_{index}")
        if not result.findings:
            st.info("No findings are available yet. Confirm the document facts in Evidence.")
    with st.expander("Which documents did the engine connect?"):
        matched = set(result.matched_document_ids)
        excluded = set(result.excluded_document_ids)
        rows = [
            {
                "Document": doc.title,
                "Role": KINDS.get(doc.kind, doc.kind),
                "Status": "Switched off"
                if not doc.included
                else "Connected"
                if doc.id in matched
                else "Not applied"
                if doc.id in excluded
                else "Reviewed for context",
            }
            for doc in documents
        ]
        st.dataframe(rows, hide_index=True, width="stretch")


def _response(documents: list[Document], result) -> None:
    st.subheader("Your evidence, ready for a billing inquiry.")
    st.write(
        "Ask for an updated itemized ledger and confirmation of how the payment was applied. Review the facts and draft before downloading."
    )
    if not any(doc.included and doc.fields for doc in documents):
        st.info("Add and review at least one document in Evidence & uploads first.")
        return
    pending = _unconfirmed(documents)
    if pending:
        st.warning(
            f"Review {len(pending)} extracted facts in Evidence & uploads before creating a response. You can exclude a document from the analysis if it is not ready."
        )
        return
    with st.expander("Evidence summary & attachment index", expanded=True):
        for finding in result.findings:
            st.write(f"**{finding.title}**")
            st.write(finding.detail.replace("$", r"\$"))
        st.caption("The current ledger, later activity, and any later reversal remain unconfirmed.")
        st.markdown("**Supporting records to attach**")
        for doc in documents:
            if doc.included:
                st.write(f"• {doc.title}")
        st.caption(
            "The download includes source passages and an attachment index. Attach original records separately."
        )
    with st.expander("Change recipient"):
        recipient_name = st.radio(
            "Who will receive the response?",
            ["Provider billing office", "Debt collector"],
            horizontal=True,
            key="nmd_recipient",
        )
    recipient = "provider" if recipient_name == "Provider billing office" else "collector"
    if recipient == "collector":
        st.info(
            "This draft is addressed to the debt collector. Filing a CFPB complaint is a separate action. The notice’s stated dispute date is preserved for your review; this app does not calculate a legal deadline."
        )
    fingerprint = _fingerprint(documents)
    draft = draft_letter(documents, result, recipient=recipient)
    text_key = f"draft_{fingerprint}_{recipient}"
    st.markdown(f"**Draft to: {recipient_name}**")
    reviewed_text = st.text_area(
        "Review and edit your draft", value=draft, height=360, key=text_key
    )
    st.caption(
        "Your export includes this draft, the evidence summary, and document references. Attach copies of the original records separately when you send it."
    )
    review_hash = sha256(reviewed_text.encode()).hexdigest()[:12]
    reviewed = st.checkbox(
        "I reviewed this draft and the supporting facts, and want to export this version",
        key=f"review_{fingerprint}_{recipient}_{review_hash}",
    )
    if reviewed:
        packet = render_packet(
            documents, result, recipient=recipient, letter_override=reviewed_text
        )
        st.download_button(
            "Download reviewed evidence packet",
            packet,
            file_name="not-my-debt-evidence-packet.html",
            mime="text/html",
            type="primary",
        )
        st.caption(
            "Open the downloaded HTML in a browser, then Print → Save as PDF. Nothing is sent to a provider, collector, or regulator by this app."
        )
    else:
        st.button("Download reviewed evidence packet", disabled=True)
    with st.expander("Official guidance and next steps"):
        st.markdown(f"[CFPB: responding to a debt collector]({CFPB_URL})")
        st.markdown(
            "[CFPB: what validation information includes](https://www.consumerfinance.gov/ask-cfpb/what-information-does-a-debt-collector-have-to-give-me-about-the-debt-en-331/)"
        )
        st.markdown("[CFPB: submit a complaint](https://www.consumerfinance.gov/complaint/)")
        st.write(
            "Keep a copy of your response and a record of delivery. Ask the provider for an updated itemized ledger and how the payment was allocated. A complaint to the CFPB is a separate escalation route."
        )


def _research() -> None:
    st.subheader("A recurring problem, grounded in complaint data.")
    st.write(
        "Public CFPB complaints inform which documentation problems this prototype checks. They are reported experiences, not verified billing errors."
    )
    research_path = ROOT / "data" / "research" / "research.json"
    if not research_path.exists():
        st.info(
            "The reproducible complaint-data analysis is being prepared. The document cases in this app are explicitly synthetic."
        )
        st.markdown(
            "[Explore the CFPB Consumer Complaint Database](https://www.consumerfinance.gov/data-research/consumer-complaints/)"
        )
        return
    try:
        research = json.loads(research_path.read_text())
    except (OSError, json.JSONDecodeError):
        st.info("The research artifact is not readable yet.")
        return
    api, archive = research.get("api", {}), research.get("archive", {})
    cols = st.columns(3)
    with cols[0]:
        value = api.get("total_complaints")
        _stat(
            "Medical-debt complaint records",
            f"{value:,}" if isinstance(value, int) else "Not measured",
            str(research.get("scope", {}).get("year", "")),
        )
    with cols[1]:
        value = archive.get("medical_with_narrative")
        _stat(
            "Medical complaints with narratives",
            f"{value:,}" if isinstance(value, int) else "Not measured",
            str(archive.get("period", "Archive sample")),
        )
    with cols[2]:
        value = archive.get("unique_narratives")
        _stat(
            "Unique narratives analyzed",
            f"{value:,}" if isinstance(value, int) else "Not measured",
            "After normalized-text deduplication",
        )
    st.write("")
    issue_counts = api.get("issue_counts", [])
    if issue_counts:
        st.markdown("**Consumer-selected issues**")
        st.bar_chart(
            pd.DataFrame(issue_counts).set_index("label")[["count"]],
            color="#0C7168",
            horizontal=True,
        )
    left, right = st.columns(2)
    for column, field, title in [
        (left, "patterns", "Reported documentation patterns"),
        (right, "document_mentions", "Documents mentioned"),
    ]:
        with column:
            values = archive.get(field, [])
            if values:
                st.markdown(f"**{title}**")
                st.bar_chart(
                    pd.DataFrame(values).set_index("label")[["count"]],
                    color="#B96D50",
                    horizontal=True,
                )
    st.caption(
        "Keyword-derived pattern counts overlap. Mentioning a document does not establish that it was supplied or verified."
    )
    for caveat in research.get("caveats", []):
        st.caption(caveat)
    with st.expander("Read example public complaint excerpts"):
        for example in archive.get("examples", [])[:6]:
            st.markdown(
                f"**Complaint {_safe(example.get('complaint_id', ''))} · {example.get('sub_issue', example.get('issue', ''))}**"
            )
            st.write(example.get("narrative_excerpt", ""))
    with st.expander("Data provenance and evaluation boundary"):
        st.write(f"Retrieved: {research.get('retrieved_at', 'Not recorded')}")
        if api.get("source_url"):
            st.markdown(f"[Reproduce the structured complaint query]({api['source_url']})")
        if archive.get("source_url"):
            st.markdown(f"[Narrative archive source]({archive['source_url']})")
        if archive.get("sha256"):
            st.code(archive["sha256"], language=None)
        st.write(
            "CFPB does not provide paired patient bills, EOBs, and receipts. Reconciliation is demonstrated on synthetic document bundles; this research does not validate legal outcomes or savings."
        )


def main() -> None:
    st.set_page_config(
        page_title="Not My Debt · Connect the evidence", page_icon="◒", layout="wide"
    )
    st.markdown(STYLE, unsafe_allow_html=True)
    if "nmd_documents" not in st.session_state:
        _load_case("paid")
    _sidebar()
    documents = _docs()
    result = reconcile(documents)
    top_left, top_right = st.columns([4, 1])
    with top_left:
        st.markdown(
            '<div class="eyebrow">NOT MY DEBT / EVIDENCE WORKSPACE</div>', unsafe_allow_html=True
        )
        st.title("Make the paperwork make sense.")
        st.markdown(
            '<div class="subtle">Connect the records. Understand the mismatch. Prepare a response you can stand behind.</div>',
            unsafe_allow_html=True,
        )
    with top_right:
        label = "FICTIONAL DEMO" if st.session_state["nmd_fictional"] else "ACTIVE SESSION"
        st.markdown(
            f'<div style="text-align:right;padding-top:.5rem"><span class="tag tag-coral">{label}</span></div>',
            unsafe_allow_html=True,
        )
    st.write("")
    workspace = st.session_state["nmd_workspace"]
    if workspace == WORKSPACES[0]:
        step = st.radio(
            "Demo steps", STEPS, horizontal=True, key="nmd_step", label_visibility="collapsed"
        )
        if step == STEPS[0]:
            _case(documents)
        elif step == STEPS[1]:
            _connect(documents, result)
        else:
            _response(documents, result)
    elif workspace == WORKSPACES[1]:
        _evidence(documents)
        with st.expander("Include or exclude documents"):
            for doc in documents:
                key = f"include_{st.session_state['nmd_generation']}_{doc.id}"
                st.toggle(
                    doc.title,
                    value=doc.included,
                    key=key,
                    on_change=_toggle_document,
                    args=(doc.id, key),
                )
    else:
        _research()
    st.markdown(
        '<div class="footer-note">A Carolina Data Challenge 2026 prototype · Evidence reconciliation for one provider, account, and visit</div>',
        unsafe_allow_html=True,
    )
