# Not My Debt — opening story

Open `index.html` directly in a modern browser. The seven-slide deck is self-contained
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
- Print from the browser for a static 16:9 copy of all seven slides.

The script is approximately 1 minute 45 seconds before the app demo. Notes are
visible to anyone looking at this browser window; keep them closed on the projector.
The **Open Maya’s case** button opens `http://127.0.0.1:3000` in a new tab.
After the setup in the [project README](../README.md#run-locally), start the app:

```sh
npm run dev
```

## Scope and editing

This checkpoint contains only the opening story, one CFPB statistic, the product
introduction, and the live-demo handoff. The technical explanation, evaluation,
business model, and closing slides have not been added.

Each `<section class="slide">` is a slide. Edit its visible HTML and associated
`<aside class="notes">` together. Colors and type are controlled by CSS variables
at the top. All document visuals are editable HTML excerpts, not screenshots of
real patient records. The evidence-summary visual is illustrative, not an app capture.

Maya's names, amounts, account, and dates match the `paid` fixture in
[`src/not_my_debt/examples.py`](../src/not_my_debt/examples.py). All are fictional.
The collection notice is explicitly an excerpt, not a complete legal notice.
The slides omit repeated demo badges and AI footers; the fictional-case disclosure
and attribution remain in these docs and speaker notes.

The real CFPB number comes from the committed
[`research.json`](../data/research/research.json) snapshot and
[`source_manifest.json`](../data/research/source_manifest.json): 1,005 complaints
categorized “Debt was paid” within 8,843 medical-debt collection complaints received
in 2025. It counts complaint records, not unique people or verified billing errors.
The chart's filled share is 1,005 / 8,843 (approximately 11.4%). The slide links to
the exact official query and the snapshot. Update both numbers and the chart if
you refresh the source. CFPB does not supply the demo's underlying documents.

Story, design, and implementation created with assistance from OpenAI Codex.
