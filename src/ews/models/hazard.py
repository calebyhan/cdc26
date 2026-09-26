"""Budget-constrained logistic and time-varying Cox hazards; training-only diagnostics."""

import warnings

import numpy as np
import pandas as pd
import statsmodels.api as sm
from lifelines import CoxTimeVaryingFitter
from scipy.special import expit
from scipy.stats import spearmanr

from ews.models.anomaly import LABELS, AnomalyModel, PeerTransform


class Predictors:
    def fit(self, training):
        self.anomaly = AnomalyModel().fit(training)
        f = training.assign(log_count=np.log1p(training.c_12m))
        self.count_transform = PeerTransform().fit(f, ["log_count"])
        explanations = self.anomaly.components(training)
        explanations["log_count"] = self.values(training, "log_count")
        self.explanation_medians = {}
        for group, indices in training.groupby("peer_group").groups.items():
            self.explanation_medians[group] = {
                name: float(values.median())
                for name, values in explanations.loc[indices].items()
                if values.notna().any()
            }
        return self

    def values(self, frame, feature):
        if feature == "anomaly":
            return self.anomaly.score(frame)
        if feature == "log_count":
            return (
                self.count_transform.transform(
                    frame.assign(log_count=np.log1p(frame.c_12m))
                )["log_count"]
                .fillna(0)
                .to_numpy()
            )
        return np.zeros(len(frame))

    def drivers(self, frame, predictor, coefficient):
        if predictor is None:
            return [[] for _ in range(len(frame))]
        values = (
            self.anomaly.components(frame)
            if predictor == "anomaly"
            else pd.DataFrame(
                {"log_count": self.values(frame, predictor)}, index=frame.index
            )
        )
        result = []
        for index, row in values.iterrows():
            reference = self.explanation_medians.get(frame.loc[index, "peer_group"], {})
            count = max(1, int(row.notna().sum()))
            parts = [
                {
                    "component": name,
                    "contribution": float(
                        coefficient * (value - reference.get(name, 0)) / count
                    ),
                    "label": LABELS.get(name, "Trailing complaint count"),
                }
                for name, value in row.items()
                if pd.notna(value)
            ]
            result.append(
                sorted(parts, key=lambda p: (-abs(p["contribution"]), p["component"]))[
                    :3
                ]
            )
        return result

    def artifact(self):
        return {
            "anomaly": self.anomaly.artifact(),
            "log_count": self.count_transform.artifact(),
            "explanation_peer_medians": self.explanation_medians,
        }


def feature_budget(events):
    return max(0, min(2, int(events) // 10))


class LogisticHazard:
    def fit(self, frame, predictor="anomaly", penalty=1.0, allow_feature=True):
        self.predictor = predictor if allow_feature else None
        self.penalty = penalty
        self.transform = Predictors().fit(frame)
        values = self.transform.values(frame, self.predictor)
        self.columns = ["baseline"] + ([predictor] if self.predictor else [])
        x = (
            np.column_stack([np.ones(len(frame)), values])
            if self.predictor
            else np.ones((len(frame), 1))
        )
        y = frame.next_event.to_numpy(dtype=float)
        alpha = np.array([0.0] + ([penalty / len(frame)] if self.predictor else []))
        with warnings.catch_warnings(record=True) as captured:
            warnings.simplefilter("always")
            fitted = sm.GLM(y, x, family=sm.families.Binomial()).fit_regularized(
                alpha=alpha, L1_wt=0.0, maxiter=1000, cnvrg_tol=1e-10
            )
        self.beta = np.asarray(fitted.params)
        self.warnings = [str(w.message) for w in captured]
        if not np.all(np.isfinite(self.beta)):
            raise ValueError("Nonfinite logistic coefficients")
        p = expit(x @ self.beta)
        bread = x.T @ (x * (p * (1 - p))[:, None]) + np.diag(alpha * len(frame))
        scores = x * (y - p)[:, None]
        grouped = (
            pd.DataFrame(scores)
            .groupby(frame.entity_id.to_numpy(), sort=True)
            .sum()
            .to_numpy()
        )
        inverse = np.linalg.pinv(bread)
        g = len(grouped)
        correction = g / (g - 1) if g > 1 else 1.0
        covariance = correction * inverse @ (grouped.T @ grouped) @ inverse
        self.cluster_se = np.sqrt(np.maximum(0, np.diag(covariance)))
        return self

    def monthly(self, frame):
        values = self.transform.values(frame, self.predictor)
        eta = self.beta[0] + (self.beta[1] * values if self.predictor else 0)
        return expit(eta + np.zeros(len(frame)))

    def predict(self, frame, horizon, previous=None):
        p = self.monthly(frame)
        first = self.monthly(previous) if previous is not None else p
        return -np.expm1(
            np.log1p(-np.clip(first, 1e-12, 1 - 1e-12))
            + (horizon - 1) * np.log1p(-np.clip(p, 1e-12, 1 - 1e-12))
        )

    def drivers(self, frame):
        return self.transform.drivers(
            frame, self.predictor, self.beta[1] if self.predictor else 0
        )

    def artifact(self):
        return {
            "model": "B",
            "predictor": self.predictor,
            "penalty": self.penalty,
            "coefficients": dict(zip(self.columns, self.beta.tolist())),
            "cluster_robust_se": dict(zip(self.columns, self.cluster_se.tolist())),
            "degrees_of_freedom": len(self.beta),
            "warnings": self.warnings,
            "transform": self.transform.artifact(),
            "target": "event in following calendar month",
        }


def schoenfeld(frame, beta):
    """Efron expected risk-set means; no held-out events enter this diagnostic."""
    times, residuals = [], []
    for t, events in frame[frame.event.eq(1)].groupby("stop", sort=True):
        risk = frame[(frame.start < t) & (frame.stop >= t)]
        w = np.exp(np.clip(risk.x.to_numpy() * beta, -40, 40))
        death_w = np.exp(np.clip(events.x.to_numpy() * beta, -40, 40))
        d = len(events)
        expected = (
            sum(
                (
                    np.sum(w * risk.x.to_numpy())
                    - j / d * np.sum(death_w * events.x.to_numpy())
                )
                / (w.sum() - j / d * death_w.sum())
                for j in range(d)
            )
            / d
        )
        for v in events.x:
            times.append(np.log1p(t))
            residuals.append(float(v - expected))
    if len(residuals) < 5 or np.std(residuals) == 0 or np.std(times) == 0:
        return {
            "status": "insufficient variation",
            "events": len(residuals),
            "p_value": None,
        }
    result = spearmanr(times, residuals)
    return {
        "status": "checked",
        "events": len(residuals),
        "p_value": float(result.pvalue),
        "time": times,
        "residual": residuals,
    }


class CoxHazard:
    def fit(self, frame, predictor="anomaly", penalty=0.01, allow_feature=True):
        self.predictor = predictor if allow_feature else None
        self.penalty = penalty
        self.transform = Predictors().fit(frame)
        fitting = frame[["entity_id", "start", "stop", "event"]].copy()
        fitting["x"] = self.transform.values(frame, self.predictor)
        self.stratified = False
        self.ph = {"status": "not applicable: no covariate", "p_value": None}
        columns = ["entity_id", "start", "stop", "event"] + (
            ["x"] if self.predictor else []
        )
        self.fitter = CoxTimeVaryingFitter(penalizer=penalty)
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            self.fitter.fit(
                fitting[columns],
                id_col="entity_id",
                start_col="start",
                stop_col="stop",
                event_col="event",
            )
        self.warnings = [str(w.message) for w in caught]
        self.beta = float(self.fitter.params_.get("x", 0))
        if self.predictor:
            self.ph = schoenfeld(fitting, self.beta)
            if self.ph["p_value"] is not None and self.ph["p_value"] < 0.05:
                self.stratified = True
                self.split = float(np.median(fitting.x))
                fitting["stratum"] = (fitting.x > self.split).astype(int)
                self.fitter = CoxTimeVaryingFitter(penalizer=penalty)
                self.fitter.fit(
                    fitting[["entity_id", "start", "stop", "event", "stratum"]],
                    id_col="entity_id",
                    start_col="start",
                    stop_col="stop",
                    event_col="event",
                    strata="stratum",
                )
                self.beta = 0.0
                self.ph["remedy"] = (
                    "median-split covariate strata; no linear coefficient; two baselines"
                )
        if not self.stratified:
            fitting["stratum"] = 0
        self.baselines = {}
        for group, subset in fitting.groupby("stratum", sort=True):
            cumulative = 0.0
            points = [[0.0, 0.0]]
            for t, events in subset[subset.event.eq(1)].groupby("stop", sort=True):
                risk = subset[(subset.start < t) & (subset.stop >= t)]
                denominator = np.exp(
                    np.clip(risk.x.to_numpy() * self.beta, -40, 40)
                ).sum()
                cumulative += len(events) / denominator
                points.append([float(t), float(cumulative)])
            self.baselines[int(group)] = {
                "points": points,
                "followup": float(subset.stop.max()),
                "tail_hazard": cumulative / max(1, float(subset.stop.max())),
            }
        return self

    def cumulative(self, ages, strata):
        result = []
        for age, s in zip(ages, strata):
            b = self.baselines.get(int(s))
            if b is None:
                result.append(np.nan)
                continue
            times, values = np.array(b["points"]).T
            index = max(0, np.searchsorted(times, age, side="right") - 1)
            value = values[index]
            if age > b["followup"]:
                value += (age - b["followup"]) * b["tail_hazard"]
            result.append(value)
        return np.array(result)

    def predict(self, frame, horizon, previous=None):
        x = self.transform.values(frame, self.predictor)
        strata = (
            (x > self.split).astype(int)
            if self.stratified
            else np.zeros(len(frame), dtype=int)
        )
        ages = (frame.month - frame.entry_date).dt.days.to_numpy(dtype=float)
        future = frame.month.map(lambda d: d + pd.DateOffset(months=horizon))
        after = (future - frame.entry_date).dt.days.to_numpy(dtype=float)
        increment = np.maximum(
            0, self.cumulative(after, strata) - self.cumulative(ages, strata)
        )
        return -np.expm1(-increment * np.exp(np.clip(x * self.beta, -40, 40)))

    def drivers(self, frame):
        if not self.predictor:
            return [[] for _ in range(len(frame))]
        values = self.transform.values(frame, self.predictor)
        if self.stratified:
            return [
                [
                    {
                        "component": self.predictor,
                        "contribution": float(v > self.split),
                        "label": "Training median complaint stratum",
                    }
                ]
                for v in values
            ]
        return self.transform.drivers(frame, self.predictor, self.beta)

    def artifact(self):
        return {
            "model": "C",
            "predictor": self.predictor,
            "penalty": self.penalty,
            "coefficient": self.beta,
            "degrees_of_freedom": 2 if self.predictor else 1,
            "stratified": self.stratified,
            "baseline": self.baselines,
            "ph": self.ph,
            "warnings": self.warnings,
            "transform": self.transform.artifact(),
            "tail_policy": "constant mean training baseline hazard beyond observed follow-up",
        }
