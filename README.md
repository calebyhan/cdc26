# Not My Debt

A medical-billing evidence workspace: connect a provider bill, insurance explanation,
payment receipt, and collection notice; inspect discrepancies; prepare a factual
response packet for review.

**Data boundary:** CFPB supplies complaint records and archived consumer narratives,
not the underlying bills or receipts. The Research view uses real public data.
The document scenarios are fictional, and document-reconciliation tests are synthetic.
This prototype has not been validated on real patient paperwork or legal outcomes.

## Run locally

The primary interface uses **Next.js, React, TypeScript, Recharts, and Lucide**.
The existing Python extraction, reconciliation, and packet engine runs through a
stateless Next.js route handler. Node.js 20.9+, Python 3.11+, npm, and
[uv](https://docs.astral.sh/uv/) are required.

```sh
uv sync --extra dev
npm ci
npm run dev
```

Open **http://127.0.0.1:3000**. No API key is needed. The app starts with Maya's
preconfirmed fictional case: **Your case → Connect the records → Prepare a response**.
Open a document to view its original fictional PDF, switch to extracted text, or
download the file. Ledger sources link to the same PDFs. Demo facts are extracted
locally from those files and preconfirmed only because these are known fixtures.
Switch off **Include payment receipt** to see the finding and balance chart change; restore it, review the
provider inquiry, and download the printable HTML evidence packet. Nothing is sent
or filed. **Reset case** restores the documents and clears edits and review approval.

**Documents & review** supports pasted text, text-based PDF/TXT upload, fact
corrections with retained original quotes, review, and document exclusion.
**Complaint research** uses real public aggregates, separately from the fictional
case. The sidebar's **Explore another case** menu contains the alternate scenarios
and an empty-case option. See [the rehearsal guide](docs/demo.md).

For a local production run:

```sh
npm run build
npm start
```

The Node server needs the Python package, `src/`, `sample_documents/`, public research aggregates,
and a Python environment at runtime. By default it uses `.venv/bin/python`;
set `NMD_PYTHON` to a different interpreter if needed. This is a Node + Python
application, not a static export or a deploy-ready Node-only serverless app.

The legacy Streamlit UI is still available with
`uv run streamlit run streamlit_app.py` on port 8501. Its opening workspace is
**Case overview**; choose a scenario and select **Load case** to replace the records.

## Extraction and data handling

In **Documents & review**, use **Extraction method** to choose an extractor for
each document:

| Choice | Setup | Where the document text goes |
| --- | --- | --- |
| **Local parser** | None | No network request; recognizes explicit `Label: value` fields in the local app |
| **Codex (ChatGPT sign-in)** | Installed Codex CLI and saved ChatGPT sign-in | Sent to OpenAI through the CLI; no API key required |
| **OpenAI API** | `OPENAI_API_KEY` | Sent to the OpenAI Responses API |

The local parser remains available without a model connection and makes no network
requests. None of these paths adds OCR: scanned PDFs need transcription. AI proposals must pass schema and source
quotation checks and then user review. Original source passages are preserved.
An extraction error is shown; the app does not silently switch to another extractor.
Choose **Local parser** and retry explicitly if you want the local path.

### Codex with your ChatGPT sign-in

For the local fictional demo, install the Codex CLI on the machine running the
Next.js/Python server if needed. Sign in and launch the app from a terminal where
`codex` is on `PATH`, after completing the setup above:

```sh
codex login
codex login status
npm run dev
```

In **Documents & review**, select **Codex (ChatGPT sign-in)** for the document and
run extraction. The adapter reuses the CLI's saved ChatGPT authentication; do not
copy login files into the project or enter an API key for this option. By default
it lets the installed CLI select its model (no `--model` argument) and uses a
120-second timeout. Optional server-side configuration:

```sh
export NMD_CODEX_MODEL='' # Leave empty to use the installed CLI's default model
export NMD_CODEX_TIMEOUT_SECONDS='120'
```

The timeout must be between 10 and 300 seconds. Set `NMD_CODEX_MODEL` only if you
have confirmed that the model identifier works with your ChatGPT CLI account.
Model access and available usage depend on your account. CLI requests consume
your ChatGPT/Codex usage allowance; this is an online service, not offline extraction.
See [OpenAI usage and pricing](https://learn.chatgpt.com/docs/pricing).
This saved-login setup is intended for a demo on your own machine with fictional
records; it is not a public multiuser deployment recipe.

The adapter starts a separate invocation in a temporary working directory, passes
the document text through standard input, and uses `--ephemeral` to avoid saving
Codex session rollout files. It ignores user configuration and captures the result
for validation. The app does not deliberately keep an input log or a persistent
Codex session. Ephemeral mode does not override provider data policies or promise
zero provider retention. See [OpenAI non-interactive mode](https://learn.chatgpt.com/docs/non-interactive-mode).

### OpenAI API

The separate API option remains available:

```sh
export OPENAI_API_KEY='your-key'
export OPENAI_MODEL='gpt-6-astra'
npm run dev
```

Choose **OpenAI API** for the document. Requests use a structured schema and
`store=False`; provider retention policies still apply. This path requires an
API key and uses API billing separately from the saved ChatGPT CLI login. The
separate API path has not been live-checked; the [demo guide](docs/demo.md#recorded-live-check)
records the bounded synthetic Codex check.

Case data lives in React memory and is processed transiently by the local
Node/Python server. The app does not persist it in a shared database, cache,
application case log, browser storage, or committed file. Reloading the page clears
the case. Processing may use temporary files, and downloaded packets contain case
information. The legacy Streamlit app uses session memory.

The public hackathon demo uses fictional documents. Credentials belong in the
server process environment, a local ignored `.env`, or the CLI's own login storage,
never in Git. `.env.example` documents configuration. Next.js loads local `.env`
files on the server; the legacy Streamlit app requires exported process variables
and does not load `.env` automatically. Keep these settings server-side: never add
`NEXT_PUBLIC_` prefixes or copy authentication files into the project.

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

Company responses for the same 2025 query come from the CFPB API aggregations:
823 of 1,005 “Debt was paid” complaints (81.9%) and 7,227 of all 8,843 (81.7%)
were closed with explanation; 3 and 22, respectively, ended with monetary relief.
These are company-reported response categories, not verified outcomes.

```sh
uv run python scripts/refresh_research.py --help
uv run python scripts/refresh_response_outcomes.py   # response aggregates only
```

## Synthetic benchmark

`scripts/run_benchmark.py` generates 70 seeded case bundles across 14 perturbation
families (paid, partial, duplicate, already credited, missing receipt, notice fees,
wrong/masked account, pending/reversed payment, payment after notice, overpayment,
bill arithmetic error, unrecognized label). Each bundle passes through the local
parser and reconciler. Expected outcomes follow the documented product rules.

Measured on the committed seed ([results](data/benchmark/results.json)): 70/70
bundles meet every check; 0 false possible-uncredited-payment findings in 55
bundles where none was expected; 40/40 correct abstentions. A mutation test
confirms that treating “Pending” as paid fails the benchmark. The parser reads
known labels only; an unfamiliar label such as “Billed by” causes a withheld balance.
This is a synthetic regression check in the parser's own text format, not an
accuracy estimate for real paperwork.

```sh
uv run python scripts/run_benchmark.py
```

## Verify

```sh
uv run pytest -q
uv run ruff check .
npm run typecheck
npm run lint
npm run build
```

Tests cover evidence matching, missing/partial/duplicate/reversed payments, dates,
invalid amounts, source verification, extraction uncertainty, safe HTML rendering,
and research aggregation. Synthetic regression results are not an accuracy estimate
for real-world documents. No debt cancellation, credit correction, or savings
outcome has been measured.

## Project files

- `app/`: Next.js interface, Recharts views, source/review drawer, and API route.
- `lib/`: TypeScript case contracts and API client.
- `src/not_my_debt/`: Python evidence engine, stateless web bridge, and legacy UI.
- `data/research/`: reproducible public aggregate data and source manifest.
- `data/benchmark/`: seeded synthetic benchmark summary.
- `presentation/`: self-contained twelve-slide deck; see its README.
- `tests/`: synthetic regression cases and parser/aggregation checks.
- [Scope and presentation storyboard](docs/scope.md).

This pivot uses branch `pivot/not-my-debt`. The mortgage project is preserved on
`main` and tag `mortgage-v1` in the shared repository.

## Attribution

Official guidance: [CFPB response resources](https://www.consumerfinance.gov/ask-cfpb/what-should-i-do-when-a-debt-collector-contacts-me-en-1695/),
[CMS EOB explanation](https://www.cms.gov/initiatives/your-patient-rights/medical-bill-rights/get-help/medical-bill-guides-resources/how-read-health-insurance-explanation-benefits),
and [OpenAI Structured Outputs](https://developers.openai.com/api/docs/guides/structured-outputs).
