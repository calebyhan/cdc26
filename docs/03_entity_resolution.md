# 03 · Entity Resolution

The approach is taken from the data spike ([FINDINGS.md §4](../FINDINGS.md)) and adapted to the mortgage scope.

## Problem

The same firm appears under different strings in each source:

| Source | Level it names | Example (Wells Fargo) |
|---|---|---|
| CCDB `Company` | Usually the holding company, sometimes the bank charter | `WELLS FARGO & COMPANY` |
| Enforcement caption | Bank charter, often several parties per caption | `Wells Fargo Bank, N.A` (sic) |
| FDIC `NAME` | Legal charter | `Wells Fargo Bank, National Association` |
| FDIC `NAMEHCR` | Holding company, Fed abbreviations | `WELLS FARGO&COMPANY` |

Firms also merge and rename. Examples: Discover was absorbed into Capital One on 2025-05-18, Nationstar operates as Mr. Cooper, Ocwen was renamed Onity, and Ditech was dissolved. A wrong match puts one firm's complaints next to another firm's enforcement action.

## Why fuzzy matching alone is not enough

In the spike, naive `token_set_ratio ≥ 88` produced **7 false positives among the top 40 CCDB companies**, all scoring 100 (e.g. `Experian Information Solutions` → `Solutions Bank`, `NAVY FEDERAL CREDIT UNION` → `Union Bank`). The improved v2 approach produced 0 false positives against FDIC, but still made 3 false positives and about 15 false negatives on enforcement parties. Conclusion: **fuzzy matching proposes, and a human decides**, for everything that matters.

## Why this is feasible

- The **top 150 mortgage company names cover 94.1%** of mortgage complaints, and the top 290 cover 97.0%.
- Mortgage-related enforcement parties number in the dozens (exact count due in M1).
- The whole universe is a few hundred entities, so Splink or dedupe would be overkill. We use `rapidfuzz` plus a curated alias table.

## Pipeline

1. **Split enforcement captions into parties.** Split on `;` always. Split on `, and` / ` and ` only when it follows a legal suffix (so `State Street Bank and Trust Company` stays whole). Cut at `d/b/a`, `f/k/a`, `a/k/a`, `n/k/a`, and keep each alias as an extra alias row. Tag individuals and non-entities ("et al.", "affiliates") and exclude them from matching.
2. **Normalize** with `normalize()` from `spike/entity_match.py`:
   - ASCII-fold and upper-case.
   - `&` → `AND`; `N.A.` / `NATIONAL ASSOCIATION` → `NA`; `U.S.` / `U S` → `US`.
   - Strip punctuation and collapse whitespace (FDIC has double-spaced names).
   - Expand Fed abbreviations (`FINL`, `BCORP`, `ASSN`, …).
   - Drop a leading or trailing `THE`.
   - Strip legal and generic tokens **only from the end** of the name.
3. **Exact normalized-key match** across CCDB, enforcement parties, FDIC `NAME`, and FDIC `NAMEHCR`.
4. **Fuzzy candidates:** `rapidfuzz.fuzz.token_sort_ratio`, **restricted to candidates that share the first token**.
   - ≥ 95: auto-accept, but still spot-checked.
   - 85–95: goes to the review queue.
   - Below 85: rejected.
   - **Never use `token_set_ratio` or `WRatio` as the only scorer.**
5. **Manual tier (required):**
   - Hand-verify the top 150 mortgage CCDB names and every mortgage-related enforcement party.
   - Add known renames and subsidiaries, for example `Nationstar Mortgage, LLC d/b/a Mr. Cooper` ↔ `NATIONSTAR MORTGAGE LLC` / `Mr. Cooper Group Inc.`, and Ocwen ↔ Onity.
   - Record decisions in `data/reference/alias_manual.csv`, which always overrides automated matches.
6. **Bank rollup through FDIC:** match to both `NAME` and `NAMEHCR`, then group charters by `RSSDHCR`, since one holding company can have several CERTs.
7. **Mergers:** use FDIC `/history` for banks and a hand-kept list for nonbanks. Set `successor_entity_id`, and never move the acquired firm's past complaints to the acquirer.

## Modeling level (ADR-005)

- **Banks:** holding company (`RSSDHCR`), because that is the level CCDB usually uses. Enforcement parties at charter level roll up to it.
- **Where CCDB uses the charter name** (e.g. `BANK OF AMERICA, NATIONAL ASSOCIATION`, `CITIBANK, N.A.`): map the charter and its holding company to the same entity, so the complaints and the actions meet.
- **Nonbank lenders and servicers:** the operating company, with the time-bounded links described above.

## Evaluation

- **Automatic tier:** precision and recall against the hand-verified set. Report the number of false positives above 95.
- **Coverage:** the share of mortgage complaints mapped to a reviewed entity (target ≥ 94%), and the share of mortgage-related enforcement parties mapped (target 100% of company parties).
- **Downstream check:** rerun the backtest using only manually reviewed aliases and report the difference.

## Deliverable

`data/marts/crosswalk.csv`: raw string (per source) ↔ `entity_id` ↔ FDIC CERTs ↔ `RSSDHCR` ↔ LEI (when available), with validity dates. This will be published as a reusable asset.

## Budget

The spike estimates 1–2 hours of manual review for about 150 names. Allow half a day including enforcement parties and mergers.
