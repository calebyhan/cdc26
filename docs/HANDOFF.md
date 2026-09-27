# Next.js presentation checkpoint

Branch: `pivot/not-my-debt`. Start here before picking up parallel work.

```sh
git fetch origin
git switch pivot/not-my-debt
uv sync --extra dev
npm ci
npm run dev
```

The app opens on **Community map**, a public-data priority map of reported
medical-debt collection complaints (CFPB), adjusted for population and coverage
(ACS). It overlays CMS hospitals, IRS Schedule H financial-assistance policies,
and a price-transparency sample, and links to the evidence navigator. See
[docs/atlas.md](atlas.md); refresh with `uv sync --extra dev --extra atlas` and
`uv run python scripts/refresh_atlas.py`. **Upload a case** starts with an empty
upload case. Add the documents, check their roles,
extract fields, and review each record before selecting **Create timeline &
explanation**. The combined timeline and AI explanation open only after that
explicit request succeeds. **View timeline only** is an explicit local-only path.
Maya's preloaded case remains a secondary option. **Start over** empties an uploaded
case and queue; **Reset case** restores the selected preloaded scenario.
Open http://127.0.0.1:3000; the Node route requires the Python environment at runtime.
**Check what we read.** leads to each document's review. Documents & review also
supports field correction. Prepare a response exports reviewed
printable HTML. Complaint research uses real CFPB aggregate data.

## What is implemented

- Six fictional scenarios and exact-cent reconciliation with source references.
- Local labeled-text/text-PDF ingestion; optional Codex or OpenAI API extraction.
- Review gates and preservation of original source text after a correction.
- Provider inquiry / collector draft and HTML packet export; no automatic sending.
- Reproducible CFPB analysis of 812 unique medical-debt narratives, plus annual counts.
- Next.js/TypeScript UI, Recharts visualizations, source drawer, review gates, and responsive layouts.
- Stateless Node-to-Python bridge retaining the existing reconciliation and local extraction.
- Synthetic regression checks for reconciliation, extraction, source references, and the bridge.
- An upload-first entrypoint, per-document review, and an explicit request for the
  combined timeline and Codex/API explanation.

The [Codex extraction check](demo.md#recorded-live-check) and
[separate case-analysis check](demo.md#recorded-case-analysis-check) are recorded in
the rehearsal guide. Case analysis was live-checked on four fictional scenarios
using existing ChatGPT sign-in and the CLI's default model: paid, missing receipt,
wrong account, and partial payment. All passed structural/citation checks; inspected
explanations agreed with the deterministic $0, $150, unknown, and $100 balances,
respectively. Runs took 14.2–15.3 seconds and changed no records or arithmetic.
These synthetic checks are not a real-document accuracy estimate. A separate
[upload-to-analysis integration check](demo.md#recorded-upload-to-analysis-check)
took 57.21 seconds: 40 returned facts matched, the receipt document date remained
missing, review was required, and the reviewed case produced a $0 balance with four
analysis events. This is not complete field recall or measured browser review time.
Neither OpenAI API path has been live-tested.
The local parser reads known labels in colon, table-row, leader-dot, and stacked layouts;
scans and photos go through local RapidOCR (see README for the measured layout results).
Unknown labels such as "Billed By" are still not guessed.

End-to-end browser QA (September 27, 2026, headless Chrome through the DevTools protocol)
passed 46 scripted steps with no console errors or failed requests: every Community map
control, the advocate briefing download, navigator hand-off, upload of four PDFs and of a
scanned bill plus a receipt photo, review and save, timeline, finding, example case, source
drawers, waterfall click, field correction, add-document, exclusion, recipient switch, letter
edit and packet export, scenario picker, reset/start over, and research. Gemini extraction of
the four PDFs (36–44 s), Gemini case explanation (8 s), and one guide question (2 s) also
passed. That check found and fixed two Gemini schema bugs (a property named "title" was
stripped; length keywords were rejected).
The legacy UI retains its Streamlit AppTest coverage. Check the primary UI with
`npm run typecheck`, `npm run lint`, and `npm run build`, and rehearse in a browser.

## Timeline and case analysis

In **Connect the records**, **Your case, in order** is built from reviewed fields.
Its dates and amounts are deterministic. A displayed record may be **Not used in
balance**; preserve that distinction for mismatches, duplicates, and payment-status
questions. The analysis provider is chosen under **Analysis method**, and
**Create timeline & explanation** is the explicit network action after review.

All included fields must be reviewed and valid before analysis. Only those facts,
their original source passages and correction provenance, and the authoritative
reconciliation are sent. Full document text and manually excluded records stay out
of the model input. Validate citations against those facts and finding codes
against the current result. Reject numeric prose and unknown
references; these checks do not establish semantic correctness. Preserve user
correction provenance. The model cannot change numerical/date cards or arithmetic.
Changing the evidence or provider must clear the explanation, including a stale
response that arrives after the change. Batch extraction must not append late
results into a reset or replaced case; every upload starts unconfirmed. Uploaded
PDF previews use transient browser URLs, revoked on reset, replacement, and unmount. Do not automatically run AI or fall back
to another provider. Analysis text stays separate from the response letter and
export in this iteration.

## Gemini and the guide

- `src/not_my_debt/gemini_adapter.py`: Gemini JSON-schema extraction and case
  analysis, with the same quote validation and review gates as the other providers.
- `lib/server/gemini.ts`, `lib/server/assistant-tools.ts`, `app/api/assistant/route.ts`,
  `app/components/assistant.tsx`: the in-app guide (tool-calling over public atlas
  data; UI actions to open a state, workspace, or the navigator).
- The key lives in ignored `.env.local` as `GEMINI_API_KEY`. It is a free-tier key
  (20 requests/day/model); the adapters move through `GEMINI_MODELS` on 429/503.
- Recorded check (September 27, 2026, fictional PDFs): Gemini extracted the EOB
  (11 fields, 4.8 s) and provider bill (11 fields, 9.6 s) with every quote
  verified. The receipt and notice then hit the daily quota and were not re-run.
  One guide question ("Show me Georgia…") opened Georgia and returned figures
  matching the atlas (7.18 per 100k, 2.72× U.S., 1.99× expected) in 31.9 s,
  mostly spent skipping exhausted models.

## Community map

- `src/not_my_debt/atlas/`: the pipeline (`cfpb`, `acs`, `cms`, `geo`,
  `schedule_h`, `prices`, `build`). Raw inputs stay in ignored `data/raw/atlas/`;
  static artifacts go to `public/atlas/` with `manifest.json` hashes.
- `app/components/atlas/`: map, state profile, hospital card, support-gap scatter,
  price basket, and the community card shown in the upload/case views. `lib/atlas.ts`
  holds types and loaders; `lib/briefing.ts` builds the printable briefing.
- Community data never enter case requests or the Python bridge. The navigator only
  receives a state code and CMS hospital ID in React state.
- Keep the guardrails: reported complaints, not harm; no hospital ranking; Schedule H
  line 18 means actions permitted *before* eligibility efforts; posted prices are
  not what a patient owes.

## Suggested parallel ownership

| Workstream | Files | Next contribution |
| --- | --- | --- |
| Documents / AI | `extract.py`, `domain.py` | Test configurable AI extraction on varied fictional document layouts; measure source/field fidelity |
| Evidence engine | `reconcile.py`, `tests/test_reconcile.py` | Expand held-out synthetic bundles, especially masked IDs, incomplete ledgers, revised statements, and payment allocation |
| UX / response | `app/`, `lib/`, `packet.py` | Improve document preview/review ergonomics and printable packet layout; test mobile and presentation flow |
| Research / pitch | `research.py`, `data/research/`, `docs/` | Human-review narrative patterns; produce the story-to-data-to-demo presentation and measured usability results |

Coordinate changes to `domain.py` before changing the shared contracts. Use a
personal feature branch from this checkpoint and merge small reviewed changes.
Run Python checks plus `npm run typecheck`, `npm run lint`, and `npm run build`
before handing work back. See README for runtime/deployment requirements.

## Claims to preserve

The case documents are fictional. The user now prefers clean app, PDF, and slide
surfaces without repeated demo, synthetic, or AI-attribution labels. Keep the
fictional-data disclosure and AI attribution in repository documentation and
presenter notes; this copy preference does not change the evidence or its limits.
CFPB supplies complaints, not EOB/bill/receipt bundles. Keyword research is descriptive.
Do not claim real patient-document accuracy, verified debt invalidity, savings,
or successful dispute outcomes. The original project remains on `main` / `mortgage-v1`.

Licensing note: PyMuPDF is AGPL-3.0 (or commercial); RapidOCR and its ONNX models are
Apache-2.0. Both are fine for this open hackathon repository; revisit PyMuPDF before any
closed-source distribution (pypdf remains as a permissive fallback reader).
