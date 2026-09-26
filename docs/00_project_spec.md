# 00 · Project Specification

## Problem

CFPB enforcement actions arrive after years of investigation. Complaints about the same companies are public the whole time. We want to know whether those complaints, adjusted for company size and mortgage activity, would have identified companies that later faced enforcement, and how far ahead of time.

## Framing after the data spike

CFPB has filed no enforcement action since 2025-08-21, and stopped publishing complaint narratives on 2026-08-14 ([FINDINGS.md](../FINDINGS.md)). The project therefore has two parts:

1. **Historical evidence:** did normalized complaint anomalies precede the enforcement actions of 2012–2025? (The backtest.)
2. **Live product:** a daily anomaly ranking from structured complaint fields. Its enforcement probabilities are labeled as estimates from the historical regime, not forecasts for today's CFPB.

## Research question

Among mortgage lenders and servicers, does an unusual rise in normalized CFPB complaints predict a CFPB enforcement action within the next 6, 12, or 18 months?

## Hypotheses

- **H1 (signal):** Companies later subject to mortgage-related CFPB enforcement show higher normalized complaint growth in the 6–36 months before the action than matched peers that were never enforced against.
- **H2 (usefulness):** A size- and activity-normalized score ranks later-enforced companies higher than a raw-complaint-count ranking does.
- **H3 (lead time):** Where the signal exists, it appears early enough to matter. We measure the lead-time distribution rather than assume it. The often-quoted "18–36 months" figure is treated as a hypothesis until we find a citable source or reproduce it.

Each hypothesis can fail. A negative or weak result, reported honestly, still counts as a complete project.

## Scope

**In scope for MVP 1:**
- Complaints with `Product = Mortgage`, covering origination, servicing, and foreclosure issues.
- Banks, bank-affiliated mortgage companies, and nonbank lenders and servicers that can be resolved to a canonical entity.
- CFPB public enforcement actions whose subject matter includes mortgage origination, servicing, or foreclosure, from **2012-07 through 2025-08** (the full span of published actions).

**Out of scope for MVP 1:**
- Credit bureaus, debt collectors, general fintechs, and card issuers.
- Complaint narratives and NLP. Narratives are no longer published, and the frozen FOIA archive is a stretch goal for historical analysis only.
- Non-CFPB regulators' actions. Planned as a stretch goal.
- Stock-price event study. Planned as a stretch goal.

## Success criteria

| Criterion | Target |
|---|---|
| End-to-end pipeline | One command rebuilds everything from raw downloads to the dashboard |
| Entity resolution quality | Hand-verified alias table covering at least 94% of mortgage complaints (the top 150 names), plus every enforcement party. Precision and recall reported for the automatic tier |
| Backtest | At least 4 rolling cutoffs, each with top-10 and top-20 precision, recall, PR-AUC, and lead time |
| Baseline comparison | Model compared against raw count, size-normalized count, and prior-enforcement flag |
| Explainability | Every flagged company shows its top 3 contributing signals |
| Honesty | The limitations page ships with the dashboard |

We don't commit to beating the baselines. We commit to measuring whether we do.

## Deliverables

1. A reproducible pipeline (`make all`).
2. A published entity crosswalk linking CFPB company name, LEI, RSSD, FDIC certificate number, and HMDA identifier.
3. Model artifacts and backtest report.
4. A dashboard with four views (see [07_dashboard.md](07_dashboard.md)).
5. A presentation (see [11_presentation.md](11_presentation.md)).

## Headline claim (if results support it)

"After adjusting for lender size and mortgage activity, these companies showed an abnormal complaint signal before CFPB enforcement in 2012–2025. Here is how early, how often the signal was wrong, and which companies show the same pattern today."
