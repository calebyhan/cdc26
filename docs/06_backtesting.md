# 06 · Backtesting

## Principle

At every cutoff, the model may only see what a real analyst could have seen on that date. This covers complaint data, financial data, HMDA vintages, and the entity mappings themselves.

## Window

- **Feature warm-up:** 2012–2014. The 36-month self-normalized features need history before they can be computed.
- **Primary evaluation window:** outcomes through **December 2024**. CFPB filed 20–55 actions a year in most years before 2025, then 9 in 2025 (the last on 2025-08-21) and none since.
- **Secondary window:** outcomes through **August 2025**, which adds the 2025 filings. Reported separately, including with and without actions later dismissed.
- **After August 2025:** there are no events to evaluate against. We report what the model flags, and make no accuracy claims for that period.

## Rolling-cutoff protocol

For each cutoff date T (annually on January 1, from 2016 through 2023), and each horizon h ∈ {6, 12, 18} months:

1. **Train** on panel rows with `month ≤ T − h`. Labels for those rows are fully known by T.
2. **Freeze** the model, the feature standardization values, and the peer-group medians.
3. **Score** every at-risk company using features as of T.
4. **Evaluate** against events in (T, T + h].
5. **Save** a `score_snapshot` and a `backtest_results` row.

Skip any (T, h) combination whose outcome window extends past December 2024.

## Metrics

| Metric | Why |
|---|---|
| Precision@10, Precision@20 | "Of the companies we'd flag, how many were later acted against?" |
| Recall@20 | "What share of actual actions did we catch?" |
| PR-AUC | Suited to rare events. Report it next to the base rate |
| Concordance (C-index) | Ranking quality for the survival models |
| Median lead time | Months from first entering the top 20 to the event, for caught events |
| Calibration | Binned, with bootstrap confidence intervals (see 05) |

Every metric is reported **per cutoff and pooled**, with bootstrap 95% confidence intervals, next to the random-ranking base rate.

## Baselines (all must be run)

1. Random ranking (the base rate).
2. Raw complaint count, trailing 12 months.
3. Complaints per size (assets or originations).
4. Prior enforcement flag, then raw count.
5. Model A (transparent score).

The claim "our model works" means Models B/C outperform baselines 2–4, with confidence intervals shown. If they don't, we say so.

## Leakage checklist (run before reporting any number)

- [ ] Lagged features use `available_from` dates, not the period described.
- [ ] HMDA vintage at T is the latest one *released* before T.
- [ ] The entity crosswalk at T excludes links whose `valid_from` is after T. Acquirers do not inherit targets' future data.
- [ ] Complaints filed after an action is announced cannot be used for that action's own prediction.
- [ ] Standardization and imputation values are computed on training rows only.
- [ ] No feature selection, threshold, or weight was chosen by looking at test results.
- [ ] The enforcement label file was not edited after viewing backtest output. It is version-controlled with a date.
- [ ] Response features rely on the 1-month lag. The bulk file stores each complaint's *current* `company_response`, not its value at the time.
- [ ] Complaint rows are ordered by `Date received`, never by `Complaint ID`, which is not chronological.

## Additional analyses

- **Event-aligned chart:** for every enforced company, plot the normalized complaint rate from month −48 to +12 around the event, against matched never-enforced peers (same peer group, similar size and complaint volume at month −48). This is the main test of H1 and H3.
- **Error review:** examine the highest-scored companies that were *not* acted against, and the acted-against companies we missed. Categorize why for each.
- **Entity-resolution sensitivity:** rerun using only manually reviewed links.

## Report output

`reports/backtest_<date>.md`, auto-generated with tables, the event-aligned chart, and the error review. The dashboard's backtest view reads from `backtest_results`.
