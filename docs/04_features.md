# 04 · Feature Catalog

All features are computed at the company × month level using only data available **before** that month (see the point-in-time rules in [01_data_sources.md](01_data_sources.md)). Windows are trailing. Features are standardized **within `peer_group`**, meaning each company is compared to similar firms rather than to the whole market.

**Structured fields only.** CFPB no longer publishes complaint narratives, so every feature below must be computable from the 15 structured CCDB columns. Anything used in the backtest must also be available to the live system.

## Complaint volume and velocity

| Feature | Definition |
|---|---|
| `c_3m`, `c_6m`, `c_12m` | Complaint counts in trailing windows |
| `c_growth_6v6` | log((c_6m + 1) / (c_prev6m + 1)) |
| `c_accel` | Change in `c_growth_6v6` versus 3 months earlier |
| `c_selfz_12m` | Current 3-month count as a z-score against the company's own trailing 36 months. Needs no denominator |
| `c_mkt_share_dev` | The company's share of all mortgage complaints minus its trailing 24-month average share. Removes market-wide swings such as the 2020 forbearance period |

## Normalized rates

| Feature | Definition | Applies to |
|---|---|---|
| `c_per_1k_orig` | c_12m ÷ HMDA originations (lagged vintage) × 1000 | Origination-heavy firms |
| `c_per_bn_assets` | c_12m ÷ total assets ($bn, lagged) | Banks |
| `c_per_servicing` | c_12m ÷ servicing-exposure proxy | Servicers. **Open decision**, see ADR-007 |

If no appropriate denominator exists, the rate feature is null and the model falls back on the self-normalized features. We never divide a nonbank's complaints by a bank asset figure.

## Severity and issue mix

We maintain a severity map in `data/reference/issue_crosswalk.csv` covering both the old and new issue taxonomies.

| Tier | Example issues |
|---|---|
| 3 (high) | Foreclosure; loan modification, collection, foreclosure; "Struggling to pay mortgage" sub-issues about foreclosure or loss mitigation |
| 2 (medium) | Trouble during payment process; loan servicing, payments, escrow account; closing on a mortgage |
| 1 (low) | Applying for or refinancing; settlement costs; other |

| Feature | Definition |
|---|---|
| `sev3_share_12m` | Share of the last 12 months' complaints in tier 3 |
| `sev_weighted_rate` | Σ tier ÷ exposure |
| `issue_mix_jsd` | Jensen-Shannon divergence between the last 6 months' issue distribution and the prior 24 months' |
| `servicer_issue_share` | Share of servicing, payment, and foreclosure issues |

Fair lending: the mortgage issue taxonomy has no explicit "discrimination" category. We **do not** create a discrimination feature from complaints. Fair-lending context comes only from HMDA (below) and is labeled as a screening indicator.

## Response behavior

| Feature | Definition |
|---|---|
| `untimely_rate_12m` | `Timely response? = No` or `Untimely response`, per 100 complaints. Only 1.9% of mortgage complaints are untimely, so treat this as a rare-event rate |
| `relief_share_12m` | Share closed with monetary or non-monetary relief, after mapping through the response crosswalk (below) |
| `explanation_only_share` | Share "Closed with explanation" |

Response crosswalk (`data/reference/response_crosswalk.csv`):

| Raw value | Standardized |
|---|---|
| Closed with monetary relief | relief_monetary |
| Closed with non-monetary relief | relief_nonmonetary |
| Closed with relief (pre-2017) | relief_unspecified |
| Closed with explanation | explanation |
| Closed without relief (pre-2017), Closed (pre-2017) | no_relief |
| Untimely response | untimely |
| In progress | *excluded* |

Complaints still "In progress" are excluded, because that value changes after ingestion.

**Dropped:** `Company public response`. Across all products, 98% of filled values are boilerplate. In mortgage, only 10% of complaints carry a substantive response. Revisit this only if the error review suggests it matters.

## Population and geography

| Feature | Definition |
|---|---|
| `older_american_share`, `servicemember_share` | Shares from `Tags`, which are present on 19.6% of mortgage complaints. Both are CFPB priority populations. `Tags` is a single string, so split on ", " |
| `state_hhi_12m` | Herfindahl index of complaints across states. Use `State`, not ZIP, because about 5% of ZIPs are masked to 3 digits |
| `state_shift_jsd` | Change in state distribution |

## HMDA context (lender × year, lagged vintage)

`originations`, `applications`, `denial_rate`, `refi_share`, `top_state_share`, `n_states`, `orig_growth_yoy`. A disparity screening indicator (the gap in denial rates between groups, controlling for loan type) is optional and is labeled "context only".

## FDIC (lagged one quarter; banks only)

`log_assets`, `deposits`, `resi_loans_share`, `noncurrent_ratio`, `provision_ratio`, `equity_to_assets`, `branch_count`, `recent_merger_24m` (flag, from `/history`).

- FDIC amounts are in **$ thousands**. `EQ` arrives as a string, so cast it.
- Sum across all CERTs belonging to the same holding company (`RSSDHCR`).
- `tier1_ratio` from Y-9C is optional, and only if Y-9C is added (see 01).

## Missing data

Each source gets a flag column (`has_fdic`, `has_hmda`). Nonbanks form their own peer groups, so missing bank financials are structural rather than random. Missing values are imputed to the peer-group median, and the flags are kept as features.

## Feature budget

The expected number of events is small, so the Cox and discrete-time models use **no more than about (number of events ÷ 10) features**. Feature selection happens only on training folds.
