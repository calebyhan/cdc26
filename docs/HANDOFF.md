# Next.js presentation checkpoint

Branch: `pivot/not-my-debt`. Start here before picking up parallel work.

```sh
git fetch origin
git switch pivot/not-my-debt
uv sync --extra dev
npm ci
npm run dev
```

The demo starts with fictional documents for Maya. Turn off the receipt in Overview
and inspect the changed finding and Recharts balance comparison. Open
http://127.0.0.1:3000; the Node route requires the Python environment at runtime.
Documents & review supports field review/correction. Select Prepare a response to
open the Prepare your response view and export reviewed printable HTML. Complaint
research uses real CFPB aggregate data.

## What is implemented

- Six fictional scenarios and exact-cent reconciliation with source references.
- Local labeled-text/text-PDF ingestion; optional OpenAI structured extraction.
- Review gates and preservation of original source text after a correction.
- Provider inquiry / collector draft and HTML packet export; no automatic sending.
- Reproducible CFPB analysis of 812 unique medical-debt narratives, plus annual counts.
- Next.js/TypeScript UI, Recharts visualizations, source drawer, review gates, and responsive layouts.
- Stateless Node-to-Python bridge retaining the existing reconciliation and local extraction.
- 90 passing Python tests, including eight new bridge checks, and a clean Ruff check.

Live OpenAI extraction has not been tested because no API key was configured.
The local parser requires explicit labels; arbitrary layouts and OCR are unfinished.
The legacy UI retains its Streamlit AppTest coverage. Check the primary UI with
`npm run typecheck`, `npm run lint`, and `npm run build`, and rehearse in a browser.

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
