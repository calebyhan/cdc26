# Not My Debt — proposed hackathon scope

Status: Next.js presentation UI checkpoint. The primary interface now uses
Next.js/TypeScript and Recharts over the existing Python engine. A stateless
route handler processes case requests without persistence or shared caching.
The legacy Streamlit implementation remains runnable. This replaces the original
Streamlit UI preference below; the product and evidence boundaries still apply.

First implementation checkpoint: The app has six synthetic scenarios,
local extraction, optional Codex and OpenAI API extraction, deterministic reconciliation,
source review, packet export, and public complaint aggregates. Codex extraction was
live-checked on the four fictional demo PDFs; see the [recorded synthetic run](demo.md#recorded-live-check).
The separate OpenAI API path has not been live-checked. The fuller evaluation and
presentation work below remain planned; they are not completed-result claims.
Prepared September 26, 2026 for 3–4 teammates with more than 12 hours remaining.

## Product decision

Build a medical-debt evidence reconciliation app for the person who says:
**“I paid my share. Why is this bill in collections?”**

The app organizes a collection notice, an insurance explanation of benefits
(EOB), a provider bill, and a payment receipt into a source-linked explanation
of the discrepancies. It creates a factual inquiry/dispute packet the user can
review and take to the provider, collector, or a consumer-assistance professional.

The first user is an insured adult with a disputed collection notice. A plausible
distribution partner is a patient-advocacy, financial-counseling, or employee-benefits
organization. This is a buyer hypothesis; willingness to pay has not been tested.
Useful outcomes to measure are preparation time, completeness, and factual accuracy.

## 1. Presentation story

Maya, a recent graduate, has a medical visit, pays the balance on her provider's
bill, and later receives a collection notice. Her records are scattered across
an insurance portal, a billing statement, and a receipt. She needs to explain
the discrepancy without becoming an expert in medical billing.

All names, identifiers, documents, dates, and amounts in the demo are fictional.
Use one provider, one encounter, one final EOB, and one account:

| Document | Relevant facts in the fictional example |
| --- | --- |
| Final EOB | Provider charges $1,200; allowed amount $800; plan payment reported as $650; patient responsibility $150 |
| Provider bill | Charges $1,200; contractual adjustment $400; posted insurance payment $650; balance $150 |
| Provider payment receipt | $150 paid against the matching account, after the bill and before the collection notice |
| Collection notice | Requests $150 for the same provider/account; identifies a stated validation-end date |

The finding is **“A $150 payment may not have been credited to the balance now
being collected.”** Explain which fields support the match and request an updated
itemized account ledger. The documents alone do not establish the provider's
current ledger, whether a payment was later reversed, or legal liability.

The EOB describes patient responsibility; it does not prove the patient paid.
CMS explicitly distinguishes these facts. The provider bill supplies the posted
insurance payment in this example. [CMS EOB guidance][cms-eob]

Two meaningful live perturbations:

1. Remove the receipt. The app withdraws its payment-supported finding and asks
   for payment evidence; it can still explain the $150 patient responsibility.
2. Replace the receipt with one for another account. The app flags an uncertain
   match and does not subtract that payment.

An optional third perturbation supplies both a bank statement and receipt for
the same payment. The app must avoid counting the payment twice.

## 2. App demo and functional boundary

| Step | User action | Output |
| --- | --- | --- |
| Load documents | Load the labeled example, paste text, or upload supported text PDFs | Document roles and extracted fields |
| Confirm facts | Correct names, account suffixes, dates, amounts, and the notice's stated deadline | Typed facts with page/text references; missing fields remain unknown |
| Follow the money | Inspect linked records and proposed matches | Charges, adjustments, insurer payments, and patient payments shown separately |
| Inspect the discrepancy | Click a finding or amount | Its evidence, matching rationale, unresolved questions, and arithmetic |
| Prepare a response | Review factual statements and choose recipient | Printable evidence summary, attachment index, questions, and editable draft |

The hero visual is a reconciled ledger with clickable source references. A compact
document relationship view can show which claim, service date, account, and payment
connect the records. A graph database is unnecessary.

The response packet contains:

- A one-page factual summary, including what remains unconfirmed.
- An indexed list of supporting documents and relevant passages.
- A provider billing inquiry requesting an updated ledger and payment reconciliation.
- When selected, a separate collector-directed dispute/information-request draft
  grounded in CFPB sample-letter guidance, with user-confirmed facts.
- A simple communication log the user can update manually.

The primary workflow ends at review/export. A CFPB complaint is a distinct
escalation route, not a substitute for a collector-directed dispute. Official
CFPB guidance supplies the procedural content. [CFPB response guidance][cfpb-reply]

## 3. Technical core

### Document extraction

Extract into a validated schema: document type, issuer, creditor/provider,
patient/account suffix, claim/reference ID, service dates, statement dates,
charge/adjustment/payment/balance fields, payment status, and supporting spans.
Store monetary values as decimal amounts or integer cents. Preserve originals.

Every extracted fact carries a document ID, page/section locator, source text,
and confirmation state. An external model may propose fields and explanations;
schema validation and user review control what enters the packet.

### Record matching and reconciliation

Match using combinations of account/claim IDs, service dates, provider, and payment
references. Similar names or equal amounts alone are insufficient. Different
collector and provider names do not establish fraud or invalidity.

Use deterministic arithmetic on facts with distinct meanings. Check whether a
provider statement reconciles charges, contractual adjustments, and posted insurer
payments. Apply a patient payment only when its account and timing match and it
has not already been included in the statement balance. Preserve unresolved
allocations and possible reversals. Never count the same payment twice.

The evidence engine emits structured findings, not a universal debt-validity score:
`possible_uncredited_payment`, `amount_mismatch`, `insufficient_itemization`,
`ambiguous_document_match`, or `no_discrepancy_detected_in_supplied_records`.
Finding definitions must be refined after reviewing the complaint corpus.

### Grounded response drafting

Compose the packet from confirmed facts, structured findings, and reviewed guidance.
Require an evidence reference for each factual assertion. A user statement stays
labeled as such if no document supports it. The app must support an incomplete
packet that asks for information rather than inventing a conclusion.

Surface the notice's stated validation-end date for confirmation. Do not calculate
a legal deadline from an upload date or invent a collector response countdown.
CFPB explains that timely written disputes within the validation period trigger
specific protections; the product should link to reviewed guidance rather than
make a case-specific legal determination. [Validation information][cfpb-validation]
[Current Regulation F][reg-f]

## 4. Required CFPB dataset and research contribution

The business track requires CFPB complaints and permits supplemental data.
[Track requirements][track]

Verified API snapshot on September 26, 2026, for complaints received in 2025:

| Consumer-selected medical-debt category | Count |
| --- | ---: |
| All medical-debt collection complaints | 8,843 |
| Attempts to collect debt not owed | 3,809 |
| Of the preceding category: debt was paid | 1,005 |
| Attempted to collect wrong amount | 926 |
| Insufficient information to verify debt | 1,235 |

These are complaint records and reported categories, not verified billing errors
or distinct people. Categories are not all mutually exclusive rows of one table:
the paid count is nested within debt-not-owed. [Exact API query][medical-api]

Use the hierarchical API filter `product=Debt collection•Medical debt`.
The tested `sub_product=Medical debt` parameter was silently ignored.

Start with the January–February 2025 narrative archive, approximately 75.5 MB.
Its medical-narrative count is not yet verified. In the first build hour, download,
filter, count usable narratives, deduplicate, and inspect a small sample. Expand
to an adjacent archive period if necessary; do not download the entire database.
[Archive][archive] [Selected ZIP][archive-zip]

Research question: **Which documentation problems recur in medical-debt complaints,
and can an evidence reconciliation tool identify the corresponding discrepancies
in a controlled document benchmark?**

Analyze all usable medical-debt narratives in the selected bounded period, including
paid-debt, wrong-amount, and insufficient-information issues. Extract reported
failure modes and the documents mentioned: insurer/provider disagreement, alleged
uncredited payment, missing itemization, duplicate billing, or uncertain account
identity. Include an unknown/other category; do not force every complaint into the
story selected for the demo.

Manually review about 60 narratives if the corpus permits. Compare a simple keyword
baseline with structured model extraction for these reported patterns, using a
held-out set and grouped splits for near-duplicate/template complaints. Do not
give the model the target subissue or company response as predictive inputs.
Use the results to justify the app's questions and evidence checks. Similar
complaints may illustrate patterns; they are not evidence about Maya's account.

Produce two useful visualizations: a distribution of observed failure modes in
the analyzed corpus, and a failure-mode-by-mentioned-document matrix. Show sample
sizes and unknowns. The CFPB evidence should materially determine which checks
are built, not serve as decoration beside a generic document app.

CFPB does not supply paired EOBs, receipts, bills, and notices. Create a separate,
explicitly synthetic document benchmark. Do not claim document reconciliation was
validated on real patient paperwork. Narrative data also does not establish which
letters caused resolution, money saved, or the probability of winning a dispute.

## 5. Evaluation and definition of done

Keep three evaluations separate:

| Evaluation | Evidence | Report |
| --- | --- | --- |
| Complaint-pattern extraction | Human-reviewed public narratives | Per-pattern precision/recall, sample size, unknowns, errors versus keyword baseline |
| Document reconciliation | About 20 synthetic bundles with known facts | Field accuracy, matching errors, false discrepancy flags, correct abstention, supported factual assertions |
| Usability | Optional 5–8 volunteers using fictional cases | Time, omissions, corrections, and ability to locate supporting evidence |

Split synthetic document families/layouts between development and held-out checks
where feasible. Include paid, partially paid, unpaid, mismatched account, duplicate
proof, missing receipt, missing itemization, conflicting service dates, and revised
EOB cases. At least one plausible case must correctly produce no payment finding.
Report synthetic results as a prototype benchmark, not production performance.

Compare usability with assembling the same packet from the original documents
and an official sample letter. A small pilot is descriptive, not evidence of debt
elimination or population-level impact. Keep all result numbers unfilled until measured.

The demo is complete when the four-document story works end to end, a field click
opens its source, an incorrect match can be corrected, removing evidence changes
the finding, and the reviewed packet exports successfully.

## 6. Team plan and implementation boundaries

| Owner | Main responsibility |
| --- | --- |
| A | Document schema, extraction, source references, synthetic input fixtures |
| B | Matching, deterministic reconciliation, finding definitions, benchmark |
| C | Streamlit workflow, evidence viewer, user corrections, packet export |
| D | CFPB corpus, pattern analysis/evaluation, official guidance, presentation |

With three people, distribute D's tasks across A/B and reserve a shared presentation
block. Integrate against a shared case JSON contract in the first hour.

| Elapsed time | Deliverable |
| --- | --- |
| 0–1 hours | Verify corpus viability; freeze fictional story and JSON schema |
| 1–5 hours | Parallel data analysis, extraction, reconciliation, and UI |
| 5–8 hours | Complete document-to-packet flow; confirm field edits propagate |
| 8–10 hours | Run held-out checks; inspect failures; optional usability pilot |
| 10–12 hours | Fix demo failures, polish charts, record backup video |
| Remaining time | Rehearse and assemble submission; add features only after core is reliable |

Use a separate `src/not_my_debt/` package and `apps/not_my_debt/app.py` entrypoint.
Reuse `ews.ingest.ccdb` for filtered structured queries. Existing mortgage bulk
ingestion hardcodes Mortgage and omits narratives; it needs a separate archive
reader. Skip mortgage entity tables, enforcement models, and dashboard marts.
Current checkout lacks the raw all-product corpus and an LLM integration.

Prefer the existing Python/Streamlit/Plotly stack. Implement paste/text-PDF support
first, with the example loadable even without a model connection. Label any cached
demo extraction as precomputed. OCR can follow once the complete path works.
Keep uploaded case data out of shared caches and logs; use fictional inputs for
the public hackathon demo.

Scope excludes coverage appeals, billing-code adjudication, multiple insurers,
multiple provider accounts, lawsuits, bankruptcy, credit repair, negotiation,
automated sending, and claims that the app establishes legal liability. These
require distinct workflows; unsupported cases should say what needs review.

## 7. Presentation and submission

Use one continuous sequence: **person paid → collection notice → evidence of
the broader problem → product promise → same person's app demo → technical
explanation and measured results → return to the person.**

Seven-minute presentation storyboard:

| Time | Visual | Spoken beat |
| --- | --- | --- |
| 0:00–0:40 | Maya's provider bill, followed by her matching receipt | “You go to the doctor. Insurance processes the claim. The provider says your share is $150. You pay it and keep the receipt.” |
| 0:40–1:00 | Later collection notice requesting the same $150 | “Then this arrives. You already paid. Now you have four documents from different organizations, and you need to explain why their records disagree.” |
| 1:00–1:35 | One chart: 1,005 paid-debt complaints within 8,843 medical-debt collection complaints in 2025 | “The CFPB recorded 1,005 medical-debt complaints in 2025 categorized as debt was paid. This is a recurring reported problem.” |
| 1:35–1:55 | Product name and the four documents becoming one evidence packet | “We built Not My Debt to connect those records, show what doesn't reconcile, and help you prepare an evidence-backed response.” |
| 1:55–4:15 | Live app, using Maya's exact documents | Load → confirm → reconcile → open a finding's sources → remove receipt and observe the changed finding → restore and export the reviewed packet. |
| 4:15–5:05 | Four-stage technical diagram | Extract typed facts with citations → match the account and encounter → reconcile with deterministic arithmetic → draft from confirmed evidence. |
| 5:05–6:15 | Actual evaluation results and one error example | Explain CFPB pattern analysis separately from the synthetic document benchmark. Include measured user preparation value if a pilot was completed. |
| 6:15–7:00 | Maya's finished packet and a patient-advocacy workflow | Maya can now identify the discrepancy, attach the supporting records, and ask specific questions. State the next real-user validation step and plausible distribution partner. |

Present Maya as a fictional scenario. Keep the exact same case and amounts
throughout the opening, demo, and closing. Introduce the technical method only
after the audience has seen the useful output.

The scale slide must say **complaint records**, not “1,005 people” or “this happens
to X people every year.” The snapshot does not provide a count of unique people,
adjudicated errors, or a national annual incidence estimate. Include the date range,
source link, and retrieval date in the chart footer. Broader medical-debt prevalence
must not be presented as the prevalence of already-paid debts being collected.

The closing outcome is preparation of a factual packet. Do not invent a successful
cancellation, a correction to a credit report, or dollars saved. The difficult
technical moment is the finding changing when its supporting evidence disappears.

Submission artifacts: runnable app, public-data source manifest, reproducible
analysis, source-linked charts, synthetic fixtures and labels, evaluation report,
README, short backup demo video, and AI/tool acknowledgments required by the event.
The published event instructions list submission at 11:00 AM on September 27.
[Judging and AI attribution][judging] [Submission instructions][submission]

[cms-eob]: https://www.cms.gov/initiatives/your-patient-rights/medical-bill-rights/get-help/medical-bill-guides-resources/how-read-health-insurance-explanation-benefits
[cfpb-reply]: https://www.consumerfinance.gov/ask-cfpb/what-should-i-do-when-a-debt-collector-contacts-me-en-1695/
[cfpb-validation]: https://www.consumerfinance.gov/ask-cfpb/what-information-does-a-debt-collector-have-to-give-me-about-the-debt-en-331/
[reg-f]: https://www.consumerfinance.gov/rules-policy/regulations/1006/38/
[medical-api]: https://www.consumerfinance.gov/data-research/consumer-complaints/search/api/v1/?size=3&date_received_min=2025-01-01&date_received_max=2025-12-31&product=Debt+collection%E2%80%A2Medical+debt
[archive]: https://www.consumerfinance.gov/foia-requests/foia-electronic-reading-room/cfpb-consumer-complaint-database-narratives-archive/
[archive-zip]: https://files.consumerfinance.gov/f/documents/CCDB_Export_9_January_2025_through_February_2025.zip
[track]: https://cdc2026.notion.site/1cb43707696082bda12081ccd3461af2
[judging]: https://cdc2026.notion.site/331437076960837b91a6016c345ebe97
[submission]: https://cdc2026.notion.site/10843707696082d9988a0116c06fb839
