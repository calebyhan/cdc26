# Not My Debt — presentation deck

Open `index.html` directly in a modern browser. The twelve-slide deck is self-contained
and works offline; source links and the live app need their respective connections.
No build step, dependencies, remote fonts, or image downloads are required.

From the repository root, an optional local server is:

```sh
python3 -m http.server 8765
```

Then open <http://localhost:8765/presentation/>.

## Present

- **Right / Space / Page Down:** next slide. **Left / Page Up:** previous.
- **Home / End:** first / last. Bottom dots jump to a slide. Touch supports swiping.
- **F:** fullscreen. **N:** speaker notes. **Escape:** close notes.
- Slides advance manually. Short entrance animations follow each advance.
- The browser's reduced-motion preference removes entrance motion.
- Print from the browser for a static 16:9 copy of all twelve slides.

Notes are visible to anyone looking at this browser window; keep them closed on the
projector. The slide 8 **Open Maya’s case** button opens the Next.js app at `http://127.0.0.1:3000` in a
new tab. Start a production build beforehand and press **Reset case**:

```sh
uv sync --extra dev && npm ci
npm run build && npm start
```

After the demo, return to the deck tab and continue at slide 9.

| Slides | Section | Target time |
| --- | --- | --- |
| 1–4 | Maya's story: bill, receipt, collection notice, four records | 0:00–1:00 |
| 5–6 | Real CFPB data: 1,005 “Debt was paid” complaints; 82% closed with explanation | 1:00–1:45 |
| 7–8 | Product introduction and demo handoff | 1:45–2:10 |
| — | Live demo ([script](../docs/demo.md)) | 2:10–4:25 |
| 9 | Method: extract, match, reconcile, draft | 4:25–4:55 |
| 10 | Complaint themes that shaped the checks | 4:55–5:20 |
| 11 | Synthetic benchmark and one failure example | 5:20–5:55 |
| 12 | Back to Maya; next validation steps | 5:55–6:20 |

The times are rehearsal targets, not measured results.

## Sources for the numbers

Maya's names, amounts, account, and dates match the `paid` fixture in
[`src/not_my_debt/examples.py`](../src/not_my_debt/examples.py). All are fictional.
The collection notice is explicitly an excerpt, not a complete legal notice.
The evidence-summary visuals are illustrative, not app captures. The slides omit
repeated demo badges; the fictional-case disclosure remains in these docs and the
speaker notes.

- **Slide 5:** 1,005 complaints categorized “Debt was paid” within 8,843 medical-debt
  collection complaints received in 2025, from
  [`research.json`](../data/research/research.json) `api`. Complaint records, not
  unique people or verified billing errors. The bar's filled share is 1,005 / 8,843.
- **Slide 6:** company responses from `api.response_outcomes`: 823 of 1,005
  closed with explanation (81.9%), 149 non-monetary relief, 30 untimely, 3 monetary
  relief. All 8,843: 7,227 closed with explanation (81.7%). Company-reported; an
  explanation does not mean the complaint was unfounded. Refresh with
  `uv run python scripts/refresh_response_outcomes.py`.
- **Slide 10:** keyword-rule counts among 812 unique Jan–Feb 2025 narratives from
  `archive.document_mentions` and `archive.patterns`. Rules overlap and are not
  validated classifiers.
- **Slide 11:** [`data/benchmark/results.json`](../data/benchmark/results.json),
  regenerated with `uv run python scripts/run_benchmark.py`. 70 seeded synthetic
  bundles across 14 families; a synthetic regression check, not real-world accuracy.

Update the slide text when any source is refreshed. [`source_manifest.json`](../data/research/source_manifest.json)
records the official query URLs and retrieval times.

## Editing

Each `<section class="slide">` is a slide. Edit its visible HTML and associated
`<aside class="notes">` together, and keep the `NN / 12` page labels in order.
Colors and type are controlled by CSS variables at the top.
