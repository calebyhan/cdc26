# First pivot checkpoint

Branch: `pivot/not-my-debt`. Start here before picking up parallel work.

```sh
git fetch origin
git switch pivot/not-my-debt
uv sync --extra dev
uv run streamlit run streamlit_app.py
```

The demo starts with fictional documents for Maya. Turn off the receipt in Overview
and inspect the changed finding. Evidence supports field review/correction. Response
packet exports reviewed printable HTML. Research uses real CFPB aggregate data.

## What is implemented

- Six fictional scenarios and exact-cent reconciliation with source references.
- Local labeled-text/text-PDF ingestion; optional OpenAI structured extraction.
- Review gates and preservation of original source text after a correction.
- Provider inquiry / collector draft and HTML packet export; no automatic sending.
- Reproducible CFPB analysis of 812 unique medical-debt narratives, plus annual counts.
- 79 passing regression tests and a clean Ruff check at this checkpoint.

Live OpenAI extraction has not been tested because no API key was configured.
The local parser requires explicit labels; arbitrary layouts and OCR are unfinished.
App interactions were also checked with Streamlit AppTest and a local browser.

## Suggested parallel ownership

| Workstream | Files | Next contribution |
| --- | --- | --- |
| Documents / AI | `extract.py`, `domain.py` | Test configurable AI extraction on varied fictional document layouts; measure source/field fidelity |
| Evidence engine | `reconcile.py`, `tests/test_reconcile.py` | Expand held-out synthetic bundles, especially masked IDs, incomplete ledgers, revised statements, and payment allocation |
| UX / response | `ui.py`, `packet.py` | Improve document preview/review ergonomics and printable packet layout; test mobile and presentation flow |
| Research / pitch | `research.py`, `data/research/`, `docs/` | Human-review narrative patterns; produce the story-to-data-to-demo presentation and measured usability results |

Coordinate changes to `domain.py` before changing the shared contracts. Use a
personal feature branch from this checkpoint and merge small reviewed changes.
Run `uv run pytest -q` and `uv run ruff check .` before handing work back.

## Claims to preserve

The user selected the document app with **clearly labeled synthetic demo documents**.
CFPB supplies complaints, not EOB/bill/receipt bundles. Keyword research is descriptive.
Do not claim real patient-document accuracy, verified debt invalidity, savings,
or successful dispute outcomes. The original project remains on `main` / `mortgage-v1`.
