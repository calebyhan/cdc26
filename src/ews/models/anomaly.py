"""Auditable equal-weight anomaly score with frozen, peer-specific transforms."""

import numpy as np
import pandas as pd

RAW_COMPONENTS = [
    "c_selfz_12m",
    "c_accel",
    "normalized_rate",
    "sev3_share_12m",
    "untimely_rate_12m",
    "issue_mix_jsd",
    "noncurrent_ratio_lag",
    "provision_ratio_lag",
    "negative_equity",
]
LABELS = {
    "self_history": "Complaint count versus own history",
    "acceleration": "Acceleration in complaint growth",
    "normalized_rate": "Complaints per available exposure",
    "severity": "Share of high-severity complaints",
    "untimely": "Untimely company responses",
    "issue_mix": "Change in complaint issue mix",
    "financial_stress": "Bank financial stress",
}


def raw_components(frame):
    f = frame.copy()
    f["normalized_rate"] = f["c_per_bn_assets"].where(f["type"].eq("bank"))
    orig = f["type"].isin(["nonbank_originator", "credit_union"])
    f.loc[orig, "normalized_rate"] = f.loc[orig, "c_per_1k_orig"]
    f["negative_equity"] = -f["equity_to_assets_lag"]
    return f


class PeerTransform:
    """No contemporary _peer_z columns or outcomes enter a backtest transform."""

    def fit(self, frame, features):
        self.features, self.stats = list(features), {}
        for group, rows in frame.groupby("peer_group", sort=True):
            self.stats[group] = {}
            for feature in features:
                known = rows[feature].dropna().astype(float)
                if known.empty:
                    self.stats[group][feature] = None
                    continue
                center = float(known.median())
                filled = rows[feature].fillna(center).astype(float)
                sd = float(filled.std(ddof=1)) if len(filled) > 1 else 0
                self.stats[group][feature] = [center, float(filled.mean()), sd]
        return self

    def transform(self, frame):
        result = pd.DataFrame(np.nan, index=frame.index, columns=self.features)
        for group, rows in frame.groupby("peer_group", sort=True):
            for feature in self.features:
                stat = self.stats.get(group, {}).get(feature)
                if stat is None:
                    continue
                center, avg, sd = stat
                values = rows[feature].fillna(center).astype(float)
                result.loc[rows.index, feature] = (
                    ((values - avg) / sd).clip(-5, 5) if sd > 0 else 0.0
                )
        return result

    def artifact(self):
        return {
            "features": self.features,
            "peer_statistics": self.stats,
            "clip_z": [-5, 5],
        }


class AnomalyModel:
    def fit(self, training):
        self.transformer = PeerTransform().fit(raw_components(training), RAW_COMPONENTS)
        return self

    def components(self, frame):
        raw = raw_components(frame)
        z = self.transformer.transform(raw)
        result = pd.DataFrame(index=frame.index)
        mapping = {
            "self_history": "c_selfz_12m",
            "acceleration": "c_accel",
            "normalized_rate": "normalized_rate",
            "severity": "sev3_share_12m",
            "untimely": "untimely_rate_12m",
            "issue_mix": "issue_mix_jsd",
        }
        for key, feature in mapping.items():
            result[key] = z[feature]
        # No structural missingness is filled with another company's exposure.
        result.loc[raw["normalized_rate"].isna(), "normalized_rate"] = np.nan
        stress = ["noncurrent_ratio_lag", "provision_ratio_lag", "negative_equity"]
        result["financial_stress"] = z[stress].mean(axis=1)
        result.loc[
            frame["type"].ne("bank") | raw[stress].isna().all(axis=1),
            "financial_stress",
        ] = np.nan
        return result

    def score(self, frame):
        return self.components(frame).mean(axis=1).fillna(0.0).to_numpy()

    def drivers(self, frame):
        components = self.components(frame)
        output = []
        for _, row in components.iterrows():
            ranked = sorted(
                ((k, float(v)) for k, v in row.items() if pd.notna(v)),
                key=lambda p: (-abs(p[1]), p[0]),
            )[:3]
            output.append(
                [
                    {
                        "component": k,
                        "label": LABELS[k],
                        "peer_z": v,
                        "contribution": v / int(row.notna().sum()),
                    }
                    for k, v in ranked
                ]
            )
        return output

    def artifact(self):
        return {
            "model": "A",
            "weight_policy": "equal across available components",
            "components": list(LABELS),
            "transform": self.transformer.artifact(),
        }
