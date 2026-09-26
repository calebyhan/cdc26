"""Generate a report and complete cutoff tables directly from saved measurements."""

import csv
import math
from pathlib import Path

METRIC_LABELS = {
    "precision_10": "P@10",
    "precision_20": "P@20",
    "recall_10": "R@10",
    "recall_20": "R@20",
    "pr_auc": "PR-AUC",
    "median_lead_months": "Lead (months)",
    "c_index": "C-index",
    "brier": "Brier",
}


def number(value):
    return "N/A" if value is None or not math.isfinite(value) else f"{value:.3f}"


def estimate(row, name):
    value = row.get(name)
    if value is None or not math.isfinite(value):
        return "N/A"
    return (
        f"{value:.3f} [{number(row.get(name+'_low'))}, {number(row.get(name+'_high'))}]"
    )


def table(rows, columns):
    return "\n".join(
        [
            "| " + " | ".join(label for _, label in columns) + " |",
            "| " + " | ".join("---" for _ in columns) + " |",
            *[
                "| "
                + " | ".join(
                    str(formatter(row)).replace("|", "/") for formatter, _ in columns
                )
                + " |"
                for row in rows
            ],
        ]
    )


def generate(
    output,
    report_date,
    results,
    comparisons,
    diagnostics,
    audit,
    chart,
    errors,
    calibrations,
):
    path = Path(output) / f"backtest_{report_date}.md"
    lines = [
        f"# Mortgage complaint backtest · {report_date}",
        "",
        "Model A is the shipped live anomaly ranking. Model B remains the planned primary statistical model; Model C is the Cox comparison. Model choice never changes the live ranking.",
        "",
        "This is a retrospective screening evaluation, not evidence of wrongdoing or an accuracy claim about enforcement after August 2025.",
        "",
        "## Findings and practical limits",
        "",
        "The primary window ends 2024-12-31; the secondary ends 2025-08-31. Each is reported with all filings and after excluding independently documented complete-case dismissals. The at-risk population is reconstructed for each policy, allowing a company whose first filing is dropped to remain at risk.",
        "",
        "**The verified size-normalized baseline is unavailable at every historical cutoff.** M3 deliberately does not backdate revised FDIC/HMDA files. It appears as N/A, with no fabricated rate or confidence interval. A separately labeled self-normalized-count reference is included. Size-adjustment superiority (H2) cannot be established from these archived vintages.",
        "",
        "Only a small number of first-company events support fitting. The ADR-008 budget reserves one baseline degree; folds below ten training events are not fit, folds with 10–19 events use baseline-only B/C, and folds with at least 20 permit one predictor. A baseline-only statistical model is explicitly identified in fit diagnostics, not presented as a learned complaint effect.",
        "",
        "Entity identities were curated retrospectively in 2026. Validity dates and all feature publication cutoffs are enforced, but historical availability of those exact mapping versions is unverified. Current complaint-response versions also cannot be reconstructed from the bulk snapshot. These limitations prevent a claim of a completely reconstructed contemporaneous deployment.",
        "",
        "## Reproduction and provenance",
        "",
        "```bash",
        "make backtest",
        "make test lint",
        "```",
        "",
        f"Seed: {audit['seed']}; bootstrap draws: {audit['bootstrap_draws']}. [Machine-readable audit](backtest_audit.json), [all metrics](backtest_results.csv), [predictions](score_snapshots.csv.gz), [fit diagnostics](model_diagnostics.json). The original enforcement-label checksum was checked before and after the run.",
        "",
        "## Methods",
        "",
        "January cutoffs 2016–2023 and horizons 6/12/18 months form the primary test. The secondary additionally permits 2024/2025 cutoffs with complete horizons by August 2025. Training feature months are at most T−h. All imputations, peer means/scales, and predictor/penalty choices are fit inside training folds. Existing contemporary M3 peer-z columns never enter training or historical scores.",
        "",
        "Model A equally averages available standardized self-history, acceleration, exposure rate, severity, timeliness, issue mix, and bank-stress components. No invented servicing exposure is used. B fits L2 logistic next-month hazards with company-cluster sandwich standard errors; its first forecast month uses the previous feature snapshot and later months hold T's snapshot fixed. C uses lifelines time-varying Cox, training-only risk-set Schoenfeld diagnostics, and median-split strata when a detected violation requires them. C extrapolates its mean training baseline hazard beyond observed follow-up; probabilities depend on this assumption.",
        "",
        "Two expanding, horizon-embargoed inner validation folds select from the anomaly composite/log complaint count and the prespecified penalty grid by Brier loss. Insufficient covariate-capable validation leaves the declared defaults unchanged. Details and all fold dates are in model_diagnostics.json.",
        "",
        "PR-AUC is non-interpolated average precision, with ties grouped. Top-k ties use stable entity IDs; precision divides by the smaller of k and the eligible population. Recall/PR-AUC with no events and concordance without comparable pairs are undefined. Model and baseline comparisons use the same eligible cohort at a cutoff; missing size denominators are not imputed from another sector.",
        "",
        "95% intervals resample company clusters, retaining the company's appearances across cutoffs. Pooled metrics are macro cutoff means per horizon; pooled lead time deduplicates company events and measures first annual top-20 alerts whose horizon covers the event. Annual observations make lead timing coarse. Bootstrap draws with no defined metric are excluded, and valid-draw counts are saved. These intervals condition on fitted models and do not include training-estimation, identity-review, or source-version uncertainty, or dependence from shared actions/calendar shocks.",
        "",
        "## Pooled metrics and confidence intervals",
        "",
        "Each value is estimate [95% company-cluster bootstrap interval]. Random-ranking prevalence appears in cutoff tables; the seeded random-rank baseline is separately measured.",
        "",
    ]
    primary = [
        r
        for r in comparisons
        if r["window"] == "primary"
        and r["policy"] == "include"
        and r["horizon"] == 12
        and r["baseline"] == "raw_count"
    ]
    lines += [
        "### Primary 12-month comparison",
        "",
        "The following differences compare each model with raw complaint count on its own shared cutoffs. Sparse-event B/C folds cannot be compared by subtracting their pooled scores from an eight-cutoff baseline.",
        "",
        table(
            primary,
            [
                (lambda r: r["model"], "Model"),
                (lambda r: r["n_cutoffs"], "Shared cutoffs"),
                (
                    lambda r: f"{number(r['pr_auc_difference'])} [{number(r['low'])}, {number(r['high'])}]",
                    "Δ PR-AUC [95% CI]",
                ),
            ],
        ),
        "",
    ]
    if primary and all(
        r["pr_auc_difference"] is not None and r["pr_auc_difference"] <= 0
        for r in primary
    ):
        lines += [
            "**All three models have lower point-estimate PR-AUC than raw count in this comparison.** This run does not establish an improvement in enforcement prediction. Model A still drives live screening under ADR-010; its operational role is not a claim of superior validated accuracy.",
            "",
        ]
    for window in ["primary", "secondary"]:
        for policy in ["include", "exclude_confirmed"]:
            lines += [
                f"### {window.title()} · {'all filings' if policy=='include' else 'confirmed dismissals excluded'}",
                "",
            ]
            rows = [
                r
                for r in results
                if r["window"] == window
                and r["policy"] == policy
                and r["cutoff"] == "pooled"
            ]
            columns = [
                (lambda r: r["horizon"], "H (months)"),
                (lambda r: r["model"], "Model/baseline"),
                (lambda r: r["n_cutoffs"], "Cutoffs"),
            ]
            columns += [
                (lambda r, m=m: estimate(r, m), label)
                for m, label in METRIC_LABELS.items()
            ]
            lines += [table(rows, columns), ""]
    lines += [
        "## Paired baseline comparisons",
        "",
        "Positive differences favor the model. Only shared, scoreable cutoffs enter each comparison. An interval spanning zero does not establish an improvement. N/A size comparisons are an explicit data gap.",
        "",
    ]
    lines += [
        table(
            comparisons,
            [
                (lambda r: r["window"], "Window"),
                (lambda r: r["policy"], "Policy"),
                (lambda r: r["horizon"], "H"),
                (lambda r: r["model"], "Model"),
                (lambda r: r["baseline"], "Baseline"),
                (lambda r: r["n_cutoffs"], "Shared cutoffs"),
                (
                    lambda r: f"{number(r['pr_auc_difference'])} [{number(r['low'])}, {number(r['high'])}]",
                    "Δ PR-AUC [95% CI]",
                ),
            ],
        ),
        "",
    ]
    wins = [
        r
        for r in comparisons
        if r["baseline"] in ["raw_count", "prior_action"]
        and r["low"] is not None
        and r["low"] > 0
    ]
    lines += [
        f"{len(wins)} paired comparisons have a lower interval above zero. These are exploratory comparisons across multiple overlapping horizons, not adjusted confirmatory tests. Model A always ships irrespective of this count.",
        "",
        "## Dismissal evidence and sensitivity",
        "",
        f"The reviewed mortgage-action table contains {audit['dismissals']['confirmed']} confirmed full-case dismissals and {audit['dismissals']['unknown']} unresolved disposition(s). Order expiry or termination alone is retained. The unresolved Borders litigation does not contribute an observed model-universe event; it is disclosed rather than guessed. PHH's dismissal is supported by the Bureau's administrative docket. Later 2025/2026 dismissals are a retrospective label sensitivity, not historically available model features.",
        "",
        "Evidence is kept in data/reference/enforcement_dismissals.csv; source hashes are verified. Dismissal-filtering never edits the original filing labels.",
        "",
        "## Event-aligned matched-peer chart",
        "",
        "![Event-aligned complaint trajectories](event_aligned.png)",
        "",
        f"{chart['pairs']} company pairs have an observable positive complaint baseline 48 months before filing and an eligible peer. Matching uses the same peer group and baseline log count; size is used only if available. The y-axis is complaints relative to each company's own −48m baseline, with add-one smoothing. It is **self-normalized**, not an unavailable size-normalized rate. Shading is a matched-company bootstrap interval.",
        "",
        "Early filings without a −48m baseline are excluded and listed in the audit. The unrestricted feature grid retains post-event complaints for the +12m descriptive trajectory; these never enter a prediction of that filing. Later descriptive complaint observations are not post-August-2025 accuracy claims. Controls have no qualifying filing within the evaluation window, not a claim of lifetime absence of enforcement. [Matched pairs](event_matched_pairs.csv), [monthly series](event_aligned_series.csv).",
        "",
        "## Error review",
        "",
        "The following categories describe observable structured signals in primary 12-month forecasts, using each available model's top 20. They do not infer why the agency did or did not act. A future filing outside the evaluated horizon is not silently relabeled as a true positive. [All company-level reviews](error_review.csv).",
        "",
    ]
    lines += [
        table(
            errors,
            [
                (lambda r: r["model"], "Model/baseline"),
                (lambda r: r["kind"], "Error type"),
                (lambda r: r["category"], "Observable category"),
                (lambda r: r["rows"], "Rows"),
            ],
        ),
        "",
    ]
    with (Path(output) / "error_review.csv").open(newline="") as handle:
        reviewed_errors = list(csv.DictReader(handle))
    examples = []
    for model in ["A", "B", "C"]:
        for kind in ["false_positive", "miss"]:
            choices = [
                r for r in reviewed_errors if r["model"] == model and r["kind"] == kind
            ]
            if choices:
                examples.append(
                    min(choices, key=lambda r: (r["cutoff"], int(r["rank"])))
                )
    lines += [
        "Examples below use the earliest scoreable cutoff and highest-ranked error of each type. They illustrate the categories without claiming that complaints caused a filing or that an unfiled company was compliant.",
        "",
        table(
            examples,
            [
                (lambda r: r["model"], "Model"),
                (lambda r: r["kind"], "Error"),
                (lambda r: r["cutoff"], "Cutoff"),
                (lambda r: r["display_name"], "Company"),
                (lambda r: r["rank"], "Rank"),
                (lambda r: r["c_12m"], "12m complaints"),
                (lambda r: r["category"], "Review"),
            ],
        ),
        "",
        "## Calibration",
        "",
        "Probability bins are fixed at 0–1%, 1–3%, 3–10%, and 10–100%. The table pools company-cutoff forecasts within each window/policy/horizon; intervals resample companies. Empty bins are omitted. Probabilities are noisy historical-regime estimates.",
        "",
    ]
    lines += [
        table(
            calibrations,
            [
                (lambda r: r["window"], "Window"),
                (lambda r: r["policy"], "Policy"),
                (lambda r: r["horizon"], "H"),
                (lambda r: r["model"], "Model"),
                (lambda r: r["bin"], "Bin"),
                (lambda r: r["n"], "N"),
                (lambda r: number(r["predicted"]), "Predicted"),
                (
                    lambda r: f"{number(r['observed'])} [{number(r['low'])}, {number(r['high'])}]",
                    "Observed [95% CI]",
                ),
            ],
        ),
        "",
        "## Per-cutoff metrics and confidence intervals",
        "",
        "Every eligible cutoff, horizon, model, and baseline appears below, including non-estimable rows with their reason. No outcome endpoint is later than 2025-08-31.",
        "",
    ]
    columns = [
        (lambda r: r["window"], "Window"),
        (lambda r: r["policy"], "Policy"),
        (lambda r: r["cutoff"], "Cutoff"),
        (lambda r: r["horizon"], "H"),
        (lambda r: r["model"], "Model/baseline"),
        (lambda r: r["n_eligible"], "N"),
        (lambda r: r["events"], "Events"),
        (lambda r: number(r["base_rate"]), "Prevalence"),
    ]
    columns += [
        (lambda r, m=m: estimate(r, m), label) for m, label in METRIC_LABELS.items()
    ]
    columns.append((lambda r: r["status"], "Status"))
    lines += [table([r for r in results if r["cutoff"] != "pooled"], columns), ""]
    path.write_text("\n".join(lines))
    return path
