# Presentation deck

`deck.html` is the whole presentation in one file: page, animation code and data.
It needs no server.

## Present it

Open `deck.html` in Chrome, Edge, Firefox or Safari (double-click, or drag it into a
window). Keys:

| Key | Action |
| --- | --- |
| → / Space / PageDown / click | next step; during an animation, finish it |
| ← / PageUp | previous step |
| 1–5 | jump to a section |
| S | playback speed 0.5× / 1× / 2× / 4× |
| R | replay the current step |
| F | fullscreen |

Presentation clickers send PageDown/PageUp, so they work too. Adding `#b=6` to the
address opens a specific step (numbered from 0).

The font (Public Sans) loads from Google Fonts. Offline, the page falls back to
system fonts and still works.

The deck stops at "In the dashboard" for the live demo; the click path is on that
slide and in [docs/11_presentation.md](../docs/11_presentation.md).

## Edit it

All text lives in `deck.template.html`:

- **Headlines and captions**: the `BEATS` array, one entry per click. Captions are
  HTML; `${...}` pulls a number from the data, so an edited caption stays in step
  with the backtest.
- **Limitations rows**: the `LIMITS` array.
- **Demo steps and closing slide**: the `#demo` and `#end` sections in the markup.
- **Colours and font**: the `:root` block at the top. Each colour means one thing:
  green-teal is complaint volume, violet is the change score (Model A), crimson is
  a CFPB filing, grey is comparison only.

Then rebuild:

```bash
.venv/bin/python presentation/build_deck.py
```

## Refresh the data

Only needed if the backtest, dashboard bundle or complaint snapshot changes. It
reads `data/staging` (not in git), `data/dashboard` and `reports/`:

```bash
PYTHONPATH=src .venv/bin/python scripts/export_deck_data.py
.venv/bin/python presentation/build_deck.py
```

The export stops with an error if an input no longer has the shape the deck
assumes (for example, a different number of cutoffs), rather than drawing a
misleading chart.
