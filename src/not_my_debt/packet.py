"""Reviewable response packets; no external sending."""

from datetime import date
from html import escape

from not_my_debt.domain import FIELD_LABELS, KINDS, CaseResult, Document, dollars

SOURCES = {
    "CFPB: responding to a debt collector": "https://www.consumerfinance.gov/ask-cfpb/what-should-i-do-when-a-debt-collector-contacts-me-en-1695/",
    "CFPB: validation information": "https://www.consumerfinance.gov/ask-cfpb/what-information-does-a-debt-collector-have-to-give-me-about-the-debt-en-331/",
    "CMS: understanding an explanation of benefits": "https://www.cms.gov/initiatives/your-patient-rights/medical-bill-rights/get-help/medical-bill-guides-resources/how-read-health-insurance-explanation-benefits",
}


def _confirmed_value(documents: list[Document], kind: str, key: str) -> str | None:
    matches = [
        doc.fields[key].value
        for doc in documents
        if doc.included and doc.kind == kind and key in doc.fields and doc.fields[key].confirmed
    ]
    return matches[0] if len(matches) == 1 else None


def _supporting_records(documents: list[Document], refs: list[str]) -> str:
    """Name cited records the way a billing office would, not by internal reference."""
    cited = []
    for doc in documents:
        if any(ref == doc.id or ref.startswith(f"{doc.id}.") for ref in refs):
            dated = next(
                (
                    doc.fields[key].value
                    for key in ("statement_date", "payment_date")
                    if key in doc.fields and doc.fields[key].confirmed
                ),
                None,
            )
            cited.append(f"{doc.title}, {dated}" if dated else doc.title)
    return "; ".join(cited)


def draft_letter(documents: list[Document], result: CaseResult, recipient: str = "provider") -> str:
    if recipient not in ("provider", "collector"):
        raise ValueError("Choose provider or collector.")
    account = _confirmed_value(documents, "collection", "account")
    provider = _confirmed_value(documents, "bill", "provider")
    if recipient == "provider":
        opening = "I am requesting a review of my account and a current, itemized billing ledger."
        greeting = f"To the billing team{(' at ' + provider) if provider else ''},"
    else:
        opening = (
            "I am writing about your collection notice. I dispute the balance as presented "
            "and request verification and an itemized explanation of how it was calculated."
        )
        greeting = "To the debt collector,"
    lines = [date.today().isoformat(), "", greeting, "", opening]
    if account:
        lines.extend(["", f"Account reference shown on the notice: {account}."])
    if result.collection_cents is not None:
        lines.append(f"The supplied collection notice requests {dollars(result.collection_cents)}.")
    useful = [
        f
        for f in result.findings
        if f.code
        in {
            "possible_uncredited_payment",
            "amount_mismatch",
            "insufficient_itemization",
            "ambiguous_document_match",
            "missing_payment_evidence",
            "user_corrected_facts",
        }
    ]
    if useful:
        lines.extend(["", "The following points need clarification based on the attached records:"])
        for finding in useful:
            records = _supporting_records(documents, finding.refs)
            lines.append(
                f"- {finding.detail}" + (f" (Supporting records: {records})" if records else "")
            )
    lines.extend(
        [
            "",
            "Please identify the original provider, account, and dates of service, and explain how "
            "the balance reflects contractual adjustments, insurance payments, patient payments, "
            "and any reversals. Please confirm how the attached payment records were allocated.",
            "",
            "This request is based on the records currently available to me; please provide any "
            "missing or updated account information so the discrepancy can be reconciled.",
            "",
            "Sincerely,",
            "[Your name]",
            "[Your preferred reply address]",
        ]
    )
    return "\n".join(lines)


def render_packet(
    documents: list[Document],
    result: CaseResult,
    recipient: str = "provider",
    letter_override: str | None = None,
) -> str:
    """Escape all document/user content, retain provenance, and support browser printing."""
    letter = (
        draft_letter(documents, result, recipient) if letter_override is None else letter_override
    )
    facts = []
    attachments = []
    for doc in documents:
        if not doc.included:
            continue
        attachments.append(
            f"<li>{escape(doc.title)} · {escape(KINDS.get(doc.kind, doc.kind))} · {escape(doc.id)}</li>"
        )
        for key, fact in doc.fields.items():
            if not fact.confirmed:
                continue
            source_note = (
                "User-corrected value; original source retained"
                if fact.origin == "user"
                else "Reviewed document extraction"
            )
            facts.append(
                f"<tr><td>{escape(doc.id + '.' + key)}</td>"
                f"<td>{escape(FIELD_LABELS.get(key, key))}<br><strong>{escape(fact.value)}</strong></td>"
                f"<td>Page {fact.page}: {escape(fact.quote)}<br><small>{escape(source_note)}</small></td></tr>"
            )
    findings = "".join(
        f"<article><h3>{escape(f.title)}</h3><p>{escape(f.detail)}</p>"
        f"<small>{escape(', '.join(f.refs))}</small></article>"
        for f in result.findings
    )
    ledger = "".join(
        f"<tr><td>{escape(row.label)}</td><td>{escape(dollars(row.cents))}</td>"
        f"<td>{escape(', '.join(row.refs))}</td></tr>"
        for row in result.ledger
    )
    sources = "".join(
        f'<li><a href="{escape(url, quote=True)}">{escape(title)}</a></li>'
        for title, url in SOURCES.items()
    )
    note = (
        "Edited draft supplied by the user; review every change against the evidence."
        if letter_override is not None
        else "Draft assembled from the confirmed fields and the findings below."
    )
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Not My Debt — evidence packet</title>
<style>
body{{font:15px/1.6 system-ui,sans-serif;color:#173b39;background:#faf9f5;margin:0}}
main{{max-width:920px;margin:40px auto;padding:40px;background:white;border:1px solid #dce4df}}
h1{{font-size:34px;margin:0}}h2{{margin-top:32px}}h3{{font-size:17px;margin-bottom:4px}}
.eyebrow{{letter-spacing:.13em;text-transform:uppercase;font-size:11px;color:#52716a}}
.note{{padding:16px;background:#f5f0e5;border-left:3px solid #cc8c5b}}
table{{border-collapse:collapse;width:100%;font-size:12px}}th,td{{padding:10px;text-align:left;border-bottom:1px solid #dce4df;vertical-align:top;overflow-wrap:anywhere}}
pre{{font:14px/1.7 system-ui,sans-serif;white-space:pre-wrap;overflow-wrap:anywhere}}
small{{color:#566961}}article{{padding:10px 0;border-bottom:1px solid #eee}}a{{color:#21655a}}
@media print{{body{{background:white}}main{{border:0;margin:0;padding:0}}h2,h3{{break-after:avoid}}tr{{break-inside:avoid}}.draft{{break-before:page}}}}
</style></head><body><main>
<div class="eyebrow">Not My Debt · prepared {date.today().isoformat()}</div>
<h1>Your evidence, in one place.</h1>
<p>A review packet for a medical billing inquiry. It describes the supplied records and questions requiring clarification.</p>
<p class="note">This packet does not determine legal liability or confirm the provider's current ledger. Review the recipient, identifiers, dates, and every factual statement before sharing. This file contains your case information; save and share it carefully.</p>
<h2>What needs clarification</h2>{findings or "<p>No findings could be supported from the confirmed records.</p>"}
<h2>Reconstruction from supplied records</h2>
<table><thead><tr><th>Entry</th><th>Amount</th><th>Evidence</th></tr></thead><tbody>{ledger}</tbody></table>
<h2>Attachment index</h2><ol>{"".join(attachments)}</ol>
<p>Attach copies of the relevant records yourself. This packet lists them; it does not embed the original files.</p>
<h2>Reviewed facts and source passages</h2>
<table><thead><tr><th>Evidence reference</th><th>Fact</th><th>Original source</th></tr></thead><tbody>{"".join(facts)}</tbody></table>
<section class="draft"><h2>{"Provider inquiry" if recipient == "provider" else "Collector dispute / information request"} — draft</h2>
<p><small>{escape(note)}</small></p><pre>{escape(letter)}</pre></section>
<h2>Communication log</h2><table><tr><th>Date</th><th>Who / channel</th><th>What was sent or received</th><th>Next step</th></tr><tr><td>________</td><td>________</td><td>________________</td><td>________</td></tr></table>
<h2>Official guidance</h2><ul>{sources}</ul>
<p><small>A collector-directed dispute and a CFPB complaint are separate processes. Verify the date stated in your notice. No messages or filings have been sent by this app.</small></p>
</main></body></html>"""
