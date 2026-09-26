# 10 · Risks and Limitations

## Interpretation
- **Not a finding of wrongdoing.** A score describes complaint patterns. Enforcement also depends on agency priorities, resources, and politics.
- **Circularity.** CFPB uses complaints to prioritize supervision. Part of any predictive signal may be the agency acting on the same data we use. This makes the tool a mirror of regulatory attention as much as a detector of misconduct. We state this openly.
- **Absent enforcement is not innocence.** A company flagged high and never acted against is not necessarily a false positive, and a company never flagged is not necessarily clean.

## Data
- **Self-selection.** Complainants are not a random sample of customers. Awareness of the CFPB, and complaint-filing services, vary over time and by population.
- **Taxonomy change (2017).** Both issue schemes are handled through a crosswalk, but the severity mapping for older complaints is approximate.
- **Denominator gaps.** HMDA does not measure servicing, and FDIC data does not cover nonbanks. See ADR-006 and ADR-007.
- **Publication lag.** Complaints are published with a delay, which we model as a 1-month lag.
- **No narratives, permanently.** CFPB stopped publishing narratives on 2026-08-14 and removed the consent option. Older narratives survive only in a frozen FOIA archive, whose coverage of recent months is near zero.
- **Unstable API.** In August 2026 endpoints were removed and now return the HTML page with HTTP 200. Unknown parameters are silently ignored. Ingestion asserts the JSON content type and fails loudly.
- **Values change after publication.** `company_response` moves from "In progress" to a final value. We handle this with a trailing-30-day re-pull on each manual refresh and a 1-month feature lag.

## Statistical
- **Few events.** Estimates will be imprecise. We report confidence intervals everywhere and limit the number of features.
- **Regime change.** CFPB has filed no action since 2025-08-21, and several 2025 actions were later dismissed. Enforcement patterns before 2025 may not describe the present (see ADR-004). The live product therefore stands on the anomaly signal, not on predicted enforcement.
- **Status is not a merit label.** "Dismissed" can reflect policy change rather than the facts of a case. The event is the filing.
- **Entity errors** can create false links between complaints and events. We measure their impact with a sensitivity rerun.
- **Survivorship.** Companies that exit through bankruptcy or merger are censored. If exit is itself related to enforcement risk, results are biased. Noted, not solved, in MVP 1.

## Ethical and reputational
- Named companies are real. Neutral language rules are enforced in the dashboard (see [07_dashboard.md](07_dashboard.md)).
- Politically sensitive context, such as 2025 dismissals, is presented factually, without commentary on motives.
- The fair-lending context from HMDA is labeled a screening indicator. Denial-rate gaps are not evidence of discrimination on their own.

## Project risks
| Risk | Mitigation |
|---|---|
| Too few events | Count them in M1. Fallback ladder in the roadmap |
| Entity resolution takes too long | Hand-review the top 150 names (94% of mortgage complaints) first. Leave the long tail to fuzzy auto-accept at ≥ 95 |
| HMDA ingestion is slow or messy | Not yet spiked. Spike it in M0. Fall back to FDIC denominators and self-normalized features |
| Enforcement site layout changes | Save the raw HTML of every scraped page. The label file is version-controlled |
| Model doesn't beat baselines | Report it honestly. The event-aligned chart and the crosswalk are still valuable deliverables |
