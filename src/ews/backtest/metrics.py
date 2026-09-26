"""Ranking metrics with company-cluster bootstrap intervals and explicit undefined values."""

import hashlib

import numpy as np

METRICS = [
    "precision_10",
    "precision_20",
    "recall_10",
    "recall_20",
    "pr_auc",
    "median_lead_months",
    "c_index",
    "brier",
]


def seeded_score(entity_id, seed=20260926):
    digest = hashlib.sha256(f"{seed}:{entity_id}".encode()).digest()
    return int.from_bytes(digest[:8], "big") / 2**64


def weighted_median(values, weights):
    valid = np.isfinite(values) & (weights > 0)
    if not valid.any():
        return np.nan
    v, w = values[valid], weights[valid]
    order = np.argsort(v, kind="stable")
    total = w.sum()
    cumulative = np.cumsum(w[order])
    if np.all(w == np.floor(w)):
        lo = np.searchsorted(cumulative, np.floor((total - 1) / 2), side="right")
        hi = np.searchsorted(cumulative, np.floor(total / 2), side="right")
        return float((v[order][lo] + v[order][hi]) / 2)
    return float(v[order][np.searchsorted(cumulative, total / 2, side="left")])


class MetricSample:
    def __init__(self, frame, probability=False):
        self.frame = frame.sort_values(
            ["score", "entity_id"], ascending=[False, True], kind="stable"
        ).reset_index(drop=True)
        self.ids = self.frame.entity_id.to_numpy()
        self.y = self.frame.outcome.to_numpy(dtype=float)
        self.score = self.frame.score.to_numpy(dtype=float)
        self.lead = self.frame.lead_months.to_numpy(dtype=float)
        self.probability = probability
        self.ends = np.r_[
            np.flatnonzero(self.score[1:] != self.score[:-1]), len(self.score) - 1
        ]
        durations = self.frame.duration.to_numpy()
        self.pair_i, self.pair_j = np.where(
            (self.y[:, None] == 1) & (durations[:, None] < durations[None, :])
        )
        self.pair_accuracy = (self.score[self.pair_i] > self.score[self.pair_j]).astype(
            float
        ) + 0.5 * (self.score[self.pair_i] == self.score[self.pair_j])

    def compute(self, weights=None):
        w = (
            np.ones(len(self.y))
            if weights is None
            else np.asarray(weights, dtype=float)
        )
        total, events = w.sum(), np.dot(w, self.y)
        result = dict.fromkeys(METRICS, np.nan)
        if total == 0:
            return result
        prior = np.cumsum(w) - w
        top20 = None
        for k in [10, 20]:
            selected = np.minimum(w, np.maximum(0, k - prior))
            caught = np.dot(selected, self.y)
            result[f"precision_{k}"] = caught / min(k, total)
            result[f"recall_{k}"] = caught / events if events else np.nan
            if k == 20:
                top20 = selected
        if events:
            cumulative_p = np.cumsum(w * self.y)[self.ends]
            cumulative_n = np.cumsum(w)[self.ends]
            jumps = np.diff(np.r_[0, cumulative_p])
            result["pr_auc"] = float(
                np.sum(
                    np.divide(
                        cumulative_p,
                        cumulative_n,
                        out=np.zeros_like(cumulative_p),
                        where=cumulative_n > 0,
                    )
                    * jumps
                )
                / events
            )
        result["median_lead_months"] = weighted_median(self.lead, top20 * self.y)
        pair_weights = w[self.pair_i] * w[self.pair_j]
        if pair_weights.sum():
            result["c_index"] = float(
                np.dot(pair_weights, self.pair_accuracy) / pair_weights.sum()
            )
        if self.probability:
            result["brier"] = float(np.dot(w, (self.score - self.y) ** 2) / total)
        return result


def interval(values):
    valid = np.asarray(values, dtype=float)
    valid = valid[np.isfinite(valid)]
    return (
        (float(np.quantile(valid, 0.025)), float(np.quantile(valid, 0.975)), len(valid))
        if len(valid)
        else (None, None, 0)
    )


def finite(value):
    return float(value) if value is not None and np.isfinite(value) else None


def evaluate(samples, draws=400, seed=20260926):
    """A cluster is the same entity in ALL cutoffs within this window/policy/horizon."""
    ids = sorted({e for sample in samples.values() for e in sample.ids})
    positions = {e: i for i, e in enumerate(ids)}
    random = np.random.default_rng(seed)
    weights = random.multinomial(
        len(ids), np.repeat(1 / len(ids), len(ids)), size=draws
    )
    results, boots = {}, {}
    for key, sample in samples.items():
        indices = np.array([positions[e] for e in sample.ids])
        values = [sample.compute(w[indices]) for w in weights]
        boot = {m: np.array([r[m] for r in values]) for m in METRICS}
        point = sample.compute()
        results[key] = {
            m: {
                "value": finite(point[m]),
                "low": interval(boot[m])[0],
                "high": interval(boot[m])[1],
                "valid_bootstraps": interval(boot[m])[2],
            }
            for m in METRICS
        }
        boots[key] = boot
    models = sorted({k[1] for k in samples})
    pooled = {}
    for model in models:
        keys = [k for k in samples if k[1] == model]
        pooled[model] = {}
        for m in METRICS:
            points = np.array(
                [
                    (
                        results[k][m]["value"]
                        if results[k][m]["value"] is not None
                        else np.nan
                    )
                    for k in keys
                ]
            )
            stack = np.array([boots[k][m] for k in keys])
            n = np.isfinite(stack).sum(axis=0)
            average = np.divide(
                np.nansum(stack, axis=0), n, out=np.full(draws, np.nan), where=n > 0
            )
            point = float(np.nanmean(points)) if np.isfinite(points).any() else None
            low, high, valid = interval(average)
            pooled[model][m] = {
                "value": point,
                "low": low,
                "high": high,
                "valid_bootstraps": valid,
            }
        # Lead time pools unique company events rather than duplicate cutoff appearances.
        selected = {}
        for key in keys:
            s = samples[key]
            for i, e in enumerate(s.ids[:20]):
                if s.y[i] and np.isfinite(s.lead[i]):
                    selected[e] = max(selected.get(e, 0), s.lead[i])
        if selected:
            lead_ids = list(selected)
            lead_values = np.array([selected[e] for e in lead_ids])
            lead_weights = weights[:, [positions[e] for e in lead_ids]]
            values = [weighted_median(lead_values, w) for w in lead_weights]
            low, high, valid = interval(values)
            pooled[model]["median_lead_months"] = {
                "value": float(np.median(lead_values)),
                "low": low,
                "high": high,
                "valid_bootstraps": valid,
            }
    comparisons = []
    for model in ["A", "B", "C"]:
        for baseline in [
            "raw_count",
            "size_normalized",
            "prior_action",
            "self_normalized",
        ]:
            cutoffs = sorted(
                {k[0] for k in samples if k[1] == model and (k[0], baseline) in samples}
            )
            if not cutoffs:
                comparisons.append(
                    {
                        "model": model,
                        "baseline": baseline,
                        "n_cutoffs": 0,
                        "pr_auc_difference": None,
                        "low": None,
                        "high": None,
                    }
                )
                continue
            differences = []
            point = []
            for cutoff in cutoffs:
                a, b = (cutoff, model), (cutoff, baseline)
                av, bv = results[a]["pr_auc"]["value"], results[b]["pr_auc"]["value"]
                if av is not None and bv is not None:
                    point.append(av - bv)
                differences.append(boots[a]["pr_auc"] - boots[b]["pr_auc"])
            stack = np.array(differences)
            n = np.isfinite(stack).sum(axis=0)
            difference = np.divide(
                np.nansum(stack, axis=0), n, out=np.full(draws, np.nan), where=n > 0
            )
            low, high, _ = interval(difference)
            comparisons.append(
                {
                    "model": model,
                    "baseline": baseline,
                    "n_cutoffs": len(cutoffs),
                    "pr_auc_difference": float(np.mean(point)) if point else None,
                    "low": low,
                    "high": high,
                }
            )
    return results, pooled, comparisons
