# Not My Debt

A medical-billing evidence workspace: connect a provider bill, insurance explanation,
payment receipt, and collection notice; inspect discrepancies; prepare a factual
response packet for review.

**Data boundary:** CFPB supplies complaint records and archived consumer narratives,
not the underlying bills or receipts. The Research view uses real public data.
The document scenarios are fictional, and document-reconciliation tests are synthetic.
This prototype has not been validated on real patient paperwork or legal outcomes.

## Run locally

Python 3.11+ and [uv](https://docs.astral.sh/uv/) are required.

```sh
uv sync --extra dev
uv run streamlit run streamlit_app.py
```

The app opens with Maya's fictional paid-bill case. Switch off the receipt to see
the payment finding disappear. Other examples cover partial payment, wrong account,
duplicate payment evidence, missing receipt, and records that agree.

Use **Evidence** to paste text or upload a text-based PDF, review extracted facts,
and make corrections. Source passages remain visible beside corrected values.
Use **Findings** to inspect the ledger and supporting evidence. **Response packet**
produces a reviewed HTML download that can be printed to PDF from a browser.
Nothing is sent to providers, collectors, or regulators.

## Extraction and data handling

The local parser recognizes explicit `Label: value` fields. It does not perform
general OCR or understand arbitrary document layouts. Scanned PDFs need transcription.
Confirmed user corrections remain labeled and the original source is preserved.

Optional AI extraction uses the OpenAI Responses API and a structured schema:

```sh
export OPENAI_API_KEY='your-key'
export OPENAI_MODEL='gpt-6-astra'
uv run streamlit run streamlit_app.py
```

Then select **Use OpenAI** for a document. The app explicitly sends that document's
text to the configured API. Requests use `store=False`; provider retention policies
still apply. Values and exact source quotations are checked before human review.
The app works without a key. Live AI extraction was not exercised during this
implementation because no API key was configured; local extraction and model-output
validation are covered by tests.

Private case data stays in session memory and is not written to a shared application
database/cache or committed files. Downloaded packets contain case information.
The public hackathon demo uses fictional documents. API keys belong in environment
variables, never in Git. `.env.example` documents configuration; `.env` is not
automatically loaded by the app.

## How the evidence engine works

- Extract typed facts with exact source passages and page references.
- Require confirmation before using a field.
- Match provider, patient, account, service date, and available claim identifiers.
- Reconcile amounts with integer cents; an EOB is never proof of patient payment.
- Check payment status and chronology, deduplicate references, and withhold a final
  balance when records are contradictory or ambiguous.
- Draft from the resulting evidence and reviewed procedural guidance.

Supported scope is one provider, one account, one encounter. The engine currently
requires exact normalized identities and explicit payment status; ambiguous masked
identifiers and missing facts require review. It does not adjudicate insurance
coverage, diagnose billing-code errors, decide legal liability, or calculate legal
deadlines. It surfaces the date printed on a collection notice.

## Research

The committed aggregate snapshot contains 8,843 medical-debt complaint records
received in 2025. A bounded January–February 2025 archive contains 1,644 medical
complaints, 819 nonempty narratives, and 812 unique normalized narrative texts.

Pattern/document-mention counts use transparent keyword rules. They overlap and
are not verified events, unique people, or supervised-model accuracy. Raw archive
and extracted narratives are excluded from Git; aggregates and source checksums
are committed. See [sources and methods](docs/data_sources.md).

```sh
uv run python scripts/refresh_research.py --help
```

## Verify

```sh
uv run pytest -q
uv run ruff check .
```

Tests cover evidence matching, missing/partial/duplicate/reversed payments, dates,
invalid amounts, source verification, extraction uncertainty, safe HTML rendering,
and research aggregation. Synthetic regression results are not an accuracy estimate
for real-world documents. No debt cancellation, credit correction, or savings
outcome has been measured.

## Project files

- `src/not_my_debt/`: schema, extraction, reconciliation, packet export, research, UI.
- `data/research/`: reproducible public aggregate data and source manifest.
- `tests/`: synthetic regression cases and parser/aggregation checks.
- [Scope and presentation storyboard](docs/scope.md).

This pivot uses branch `pivot/not-my-debt`. The mortgage project is preserved on
`main` and tag `mortgage-v1` in the shared repository.

## Attribution

Created with assistance from OpenAI Codex for design, code, tests, and documentation.
Official guidance: [CFPB response resources](https://www.consumerfinance.gov/ask-cfpb/what-should-i-do-when-a-debt-collector-contacts-me-en-1695/),
[CMS EOB explanation](https://www.cms.gov/initiatives/your-patient-rights/medical-bill-rights/get-help/medical-bill-guides-resources/how-read-health-insurance-explanation-benefits),
and [OpenAI Structured Outputs](https://developers.openai.com/api/docs/guides/structured-outputs).
