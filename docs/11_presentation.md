# 11 · Presentation Plan

## Narrative arc (about 7 minutes)

1. **Hook (30 s).** One real enforced company's complaint timeline, with the action date revealed at the end. "This was public data the whole time."
2. **Question (30 s).** Was that a coincidence, or a pattern we could have used?
3. **The hard part (1 min).** Entity resolution: show one company under five names, then the crosswalk. Then normalization: raw counts would flag the biggest banks and miss everyone else.
4. **Evidence (2 min).** The event-aligned chart (enforced companies versus matched peers). Then the backtest: precision@20 versus baselines, with confidence intervals, and the lead-time histogram.
5. **Demo (2 min).** Leaderboard → a company's detail page → "why flagged" → backtest view.
6. **Honesty (45 s).** The circularity caveat, the 2025 regime change (no filings since August 2025, narratives no longer published), and what the model gets wrong (the error review).
7. **Why it still matters (optional, 20 s).** Even with federal enforcement quiet, complaints keep arriving every day. The anomaly ranking is useful to state regulators, journalists, and compliance teams right now.
8. **What's next (15 s).** Multi-regulator labels, other products, the stock event study.

## Demo script

- Pre-select one historical hit, one false positive, and one miss.
- Open the dashboard on the backtest view set to the most illustrative cutoff.
- Keep a recorded fallback video and screenshots ready.

## Rubric mapping

| Criterion | Evidence we show |
|---|---|
| Impact | Usable leaderboard; a published crosswalk others can reuse |
| Completeness | One-command pipeline; backtest across multiple cutoffs, with baselines |
| Innovation | Time-aware entity resolution + exposure normalization + survival modeling |
| Visualization | Event-aligned chart, company timeline, leaderboard, backtest view |
| Presentation | A single question, answered with evidence and caveats |

## Final claim (use only if the backtest supports it)

"We built a transparent system that ranks mortgage lenders by abnormal complaint activity using only structured public data. Backtested on 2012–2024 CFPB enforcement, it flagged N of M later actions a median of X months early, compared with Y for raw complaint counts."

If the backtest does not support it: "Normalized complaint signals did / did not reliably precede enforcement. Here is what we learned, and the infrastructure others can build on."
