# Not My Debt — animated presentation

Open `index.html` directly in a modern browser. The deck is self-contained,
uses system fonts, and works offline, including embedded captures of the working
community map. Source links and the live app require their respective connections.
It has **20 beats across 8 scenes**, advanced manually.

## Present

| Control | Action |
| --- | --- |
| Right / Space / Page Down / stage click | Finish an animation, then advance on the next press |
| Left / Page Up | Previous beat, immediately settled |
| Home / End | First / last beat |
| 1–8 / scene buttons | Jump to a scene |
| R | Replay the current beat from its preceding state |
| S / speed button | Cycle 0.5×, 1×, 2×, 4× |
| F | Fullscreen |
| N / notes button | Toggle speaker notes; Escape closes them |

Clickers sending PageDown/PageUp work. `#b=11` opens beat 12 (addresses use
zero-based numbering). Reduced-motion preferences show the settled state.
Speaker notes appear in this same window, so close them on the projector.
The browser's print command prints the current stage, not a complete slide deck.

The animations explain the evidence: bill arithmetic, payment chronology,
matching account identifiers, nested CFPB complaint categories, national and Georgia
community-map views, source-linked facts, a changing reconciliation waterfall,
narrative/document counts, and benchmark cases.
They do not represent a timed recording of model processing or benchmark execution.

| Scene | Beats | Rehearsal target |
| --- | --- | --- |
| Maya | 1–4 | 1 minute |
| The data | 5–7 | 50 seconds |
| Community map | 8–9 | 30–45 seconds |
| Not My Debt | 10–11 | 20 seconds, then about 2 minutes in the app |
| How it works | 12–15 | 1 minute |
| What shaped it | 16–17 | 30 seconds |
| Results | 18–19 | 40 seconds |
| Close | 20 | 20 seconds |

These are rehearsal targets, not measured results. Start the app beforehand:

```sh
uv sync --extra dev
npm ci
npm run build
npm start
```

The app opens on **Community map**. Beat 11 opens
<http://127.0.0.1:3000/?state=GA> in a new tab. Show Georgia briefly, then
choose **Upload a case → Open an example** to load Maya’s fictional records.
The selected Georgia hospital is real public-data context, not a provider in
Maya’s case. Follow [the demo script](../docs/demo.md), then return to the
presentation and advance to the method scene.

## Sources and boundaries

`build_deck.py` embeds committed research, atlas, screenshot, and benchmark data and runs the Python
engine on Maya's fixture with and without the receipt, plus a wrong-account case.
It also runs the local parser on the unrecognized-label example. The build fails
if its expected findings no longer hold.

- Maya and all displayed documents are fictional. Values and quotes come from
  [`examples.py`](../src/not_my_debt/examples.py). Document cards and the packet
  are illustrations, not app screenshots or underlying CFPB patient documents.
- CFPB counts and company responses come from
  [`research.json`](../data/research/research.json). The 2025 counts are complaint
  records, not unique people or verified errors. Company response categories do
  not establish whether a balance was corrected.
- The community-map figures come from [`states.json`](../public/atlas/states.json).
  The national and Georgia captures in [`assets/`](assets/) come from the working
  app. CFPB complaints are reported experiences; Census ACS population makes
  state rates comparable, while uninsured and poverty estimates supply context.
  County locations, CMS hospitals, linked IRS Schedule H policies, and sample
  posted prices are separate layers. Hospitals provide local context; filed
  policies are self-reported and posted prices do not determine a patient's bill.
- The heatmap uses overlapping keyword rules on 812 unique Jan–Feb 2025
  narratives; it is not a human-reviewed classification accuracy result.
- The benchmark uses [`results.json`](../data/benchmark/results.json): 70 seeded
  synthetic bundles in the local parser's labeled-text format. This is a
  regression check, not accuracy on real paperwork. Animated tally order is
  illustrative; summary results are from the committed measured run.
- Official queries, archive URLs, and retrieval times are recorded in
  [`source_manifest.json`](../data/research/source_manifest.json).

## Edit and rebuild

Edit **`deck.template.html`**, then rebuild the generated **`index.html`**:

```sh
uv run python presentation/build_deck.py
```

Headlines, captions, speaker notes, scene states, and animation clocks live in
`BEATS`. Colors and layout live in CSS; renderers draw the evidence and data.
The map captures in `presentation/assets/` are embedded by the builder, so
refresh them when the app’s map UI or atlas changes. After refreshing research,
atlas, screenshot, or benchmark inputs, rebuild and review every beat.

## AI attribution

Claude assisted with the initial animated deck and builder. OpenAI Codex assisted
with completion, review, navigation and replay fixes, layout, and documentation.
Research figures and regression results come from the linked project artifacts;
AI assistance is not an additional validation result.
