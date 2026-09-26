# 05 · Modeling

## Target definition

- **Event:** the first public, mortgage-related CFPB enforcement action naming the company, or a party that rolls up to it. Both forums count (Administrative Proceeding and Civil Action). The event date is the **filing date** on the CFPB listing.
- **Later status does not matter.** Several 2025 actions were later marked `Expired/Terminated/Dismissed`. The event records that the agency *acted*, not that it prevailed. A sensitivity run drops actions later dismissed.
- **Mortgage-related:** decided from the action's product tags and confirmed by reading its summary. The enforcement product taxonomy differs from CCDB's, so we keep a crosswalk of about 20 rows.
- **At-risk period:** from panel entry until the event, the company's exit, or the end of the window. Exit and window end are right-censored.
- **Prior enforcement:** companies with a mortgage-related action before 2014 enter with `prior_action = 1`. MVP 1 models first events after panel entry. Recurrent-event models are a stretch goal.
- **Sensitivity variant:** "any CFPB action" (not only mortgage-related), reported separately.

**Before modeling, count the events.** Tally mortgage-related actions that resolve to panel companies within 2014-01 → 2025-08. The full CFPB list has 386 actions across all products; the mortgage subset will be much smaller. That count sets the feature budget and determines which model is primary.

## Model A: transparent score (always shipped)

```
risk_score = mean over k of z_peer(feature_k), for the chosen feature set:
  c_selfz_12m, c_accel, normalized rate (best available denominator),
  sev3_share_12m, untimely_share_12m, issue_mix_jsd, financial_stress
```

- Equal weights by default. Any other weights must be justified and written down *before* running the backtest.
- The score is a ranking. It does not produce probabilities.
- Its purpose: anyone can audit it, and it is the benchmark the statistical models must beat.

## Model B: discrete-time logistic hazard (planned primary)

- Unit: company-month. Outcome: event in month *t+1*.
- `logit P(event) = baseline(time) + β·features`, where baseline is a spline or a small set of time dummies.
- Fit with `statsmodels` using L2 regularization, with cluster-robust standard errors by company.
- Probability of an event within horizon *h*: 1 − ∏ (1 − p̂ₜ) over the next *h* months, holding features at their last observed values.
- Why primary: it is stable with few events, handles time-varying features naturally, and turns directly into 6/12/18-month probabilities.

## Model C: Cox proportional hazards with time-varying covariates

- `lifelines.CoxTimeVaryingFitter` on the counting-process panel (`start`, `stop`, `event`), with `penalizer` tuned by time-ordered cross-validation.
- Check the proportional-hazards assumption with Schoenfeld residuals. If a feature violates it, stratify or add a time interaction.
- Reported alongside Model B. We use whichever is more stable in the backtest and say which we used.

## Optional Model D: random survival forest

`scikit-survival` random survival forest, used only as a nonlinear check. It will not be shipped unless it clearly beats Model B out of sample.

## Explanations

- **Model A:** the top three standardized components.
- **Models B and C:** coefficient × (feature value − peer median), showing the top three drivers.
- Drivers are displayed in plain language, e.g. "Complaints up 2.3 standard deviations versus the company's own history".

## Calibration

Few events means calibration estimates will be noisy. We report reliability in 3–5 probability bins with bootstrap confidence intervals, and show predicted probabilities as bands on the dashboard (low / elevated / high), not as precise percentages.

## Live use

CFPB has filed no action since 2025-08-21. When the models score companies today, their probabilities mean "risk *if* enforcement behaved as it did in 2012–2024", not a forecast of what the current CFPB will do. The dashboard labels them this way. The live ranking stands on the anomaly signal itself (Model A, plus change-point flags), which does not depend on enforcement resuming.

## What we will not do

- Tune on the test period.
- Add features after seeing backtest results without re-running *every* cutoff and logging the change in [09_decisions.md](09_decisions.md).
- Present probabilities as findings of wrongdoing.
