# Not My Debt

Work on `pivot/not-my-debt`. The original mortgage implementation is preserved on
`main` and `mortgage-v1`; do not modify those refs as part of pivot development.

Use `uv sync --extra dev`, `uv run pytest -q`, and `uv run ruff check .`.
Run the app with `uv run streamlit run streamlit_app.py`.

Read `docs/scope.md` and `README.md` before changing product behavior. They distinguish
real complaint data, synthetic document benchmarks, and user-supplied case records.
Do not describe CFPB narratives as underlying patient documents or legal findings.

Store amounts as integer cents. Preserve document quotes when users correct fields.
An EOB is not proof of patient payment. Never default a missing payment to zero or
silently apply a receipt to a different account. Maintain conservative handling of
contradictions, duplicate evidence, payment status, and document chronology.

Keep case data out of shared caches, logs, and Git. No sending/filing occurs in the
current product. AI extraction must be explicitly selected and disclose that input
text goes to the configured provider. Retain the functional local extraction path.

Attribute AI-assisted work as required by the hackathon. Report measured results
only, and separate synthetic regression checks from real-world validation.
