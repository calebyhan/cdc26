"""Join public sources into the community priority map artifacts in ``public/atlas``."""

from __future__ import annotations

import json
import math
import statistics
from collections import Counter, defaultdict
from pathlib import Path

from . import acs, cfpb, cms, geo, prices, schedule_h
from .net import sha256_file, utc_now

OUT_DIR = Path("public/atlas")
RATE_YEAR = 2025
COUNTY_YEARS = (2023, 2025)
TREND_MONTHS = ("2021-01", "2026-08")
COUNTY_MIN_COUNT = 10
MODEL_EXCLUDE = {"72"}  # Puerto Rico: survey and complaint-channel context differ


def poisson_ci(count: int) -> tuple[float, float]:
    """Byar's approximation to the exact 95% Poisson interval for a count."""
    if count == 0:
        return 0.0, 3.689
    lower = count * (1 - 1 / (9 * count) - 1.96 / (3 * math.sqrt(count))) ** 3
    upper = (count + 1) * (1 - 1 / (9 * (count + 1)) + 1.96 / (3 * math.sqrt(count + 1))) ** 3
    return lower, upper


def fit_poisson(rows: list[dict], features: list[str]) -> dict:
    """Poisson regression with a log-population offset via IRLS (numpy only).

    Descriptive only: it estimates how many complaints a state would have if it
    followed the national relationship with the listed ACS characteristics.
    """
    import numpy as np

    x = np.array([[1.0] + [row[f] for f in features] for row in rows])
    means = x[:, 1:].mean(axis=0)
    sds = x[:, 1:].std(axis=0)
    x[:, 1:] = (x[:, 1:] - means) / sds
    y = np.array([row["count"] for row in rows], dtype=float)
    offset = np.log(np.array([row["population"] for row in rows], dtype=float))
    beta = np.zeros(x.shape[1])
    beta[0] = math.log(y.sum() / np.exp(offset).sum())
    for _ in range(50):
        mu = np.exp(x @ beta + offset)
        z = x @ beta + (y - mu) / mu
        w = mu
        updated = np.linalg.solve(x.T @ (w[:, None] * x), x.T @ (w * z))
        if np.max(np.abs(updated - beta)) < 1e-10:
            beta = updated
            break
        beta = updated
    mu = np.exp(x @ beta + offset)
    dispersion = float(((y - mu) ** 2 / mu).sum() / (len(y) - len(beta)))
    return {
        "features": features,
        "rate_ratio_per_sd": {f: round(math.exp(b), 4) for f, b in zip(features, beta[1:])},
        "feature_mean": {f: round(float(m), 5) for f, m in zip(features, means)},
        "feature_sd": {f: round(float(s), 5) for f, s in zip(features, sds)},
        "pearson_dispersion": round(dispersion, 2),
        "expected": [float(v) for v in mu],
        "n": len(rows),
    }


def tercile_cuts(values: list[float]) -> list[float]:
    ordered = sorted(values)
    return [ordered[len(ordered) // 3], ordered[(2 * len(ordered)) // 3]]


def tercile(value: float | None, cuts: list[float]) -> int | None:
    if value is None:
        return None
    return 0 if value < cuts[0] else 1 if value < cuts[1] else 2


def median(values: list[float]) -> float | None:
    values = [v for v in values if v is not None]
    return statistics.median(values) if values else None


def share(part: int, whole: int) -> float | None:
    return round(part / whole, 4) if whole else None


def policy_summary(policies: list[dict]) -> dict:
    """State-level Schedule H summary over linked CMS nonprofit facilities."""
    n = len(policies)
    permits_any = sum(bool(p["ecas_permitted_before_efforts"]) for p in policies)
    credit = sum("credit_reporting" in p["ecas_permitted_before_efforts"] for p in policies)
    legal = sum("legal_process" in p["ecas_permitted_before_efforts"] for p in policies)
    early = sum(bool(p["ecas_before_reasonable_efforts"]) for p in policies)
    on_bills = sum(bool(p["notice_on_bills"]) for p in policies)
    return {
        "facilities_with_policy": n,
        "median_free_fpg": median([p["free_fpg"] for p in policies]),
        "median_discount_fpg": median([p["discount_fpg"] for p in policies]),
        "share_free_fpg_at_least_200": share(
            sum((p["free_fpg"] or 0) >= 200 for p in policies), n
        ),
        "share_ecas_permitted_before_efforts": share(permits_any, n),
        "share_credit_reporting_before_efforts": share(credit, n),
        "share_legal_process_before_efforts": share(legal, n),
        "share_ecas_taken_before_efforts": share(early, n),
        "share_notice_on_bills": share(on_bills, n),
    }


def compact_policy(policy: dict) -> dict:
    return {key: value for key, value in policy.items() if key not in {"facility_num", "name"}}


def build(raw_dir: Path, out_dir: Path = OUT_DIR, *, reuse: bool = True) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    geo_paths = geo.fetch(raw_dir, reuse=reuse)
    centroids = geo.zcta_centroids(geo_paths["zcta_gazetteer"])
    zcta_county = geo.zcta_to_county(geo_paths["zcta_county"])
    acs_paths = acs.fetch(raw_dir, reuse=reuse)
    census = acs.build(acs_paths)
    hospitals_path = cms.fetch(raw_dir, reuse=reuse)
    hospitals = cms.load(hospitals_path, centroids, zcta_county)
    records_path = raw_dir / "cfpb_medical.jsonl"
    records = cfpb.load(records_path)
    months = cfpb.months_between(*TREND_MONTHS)
    complaints = cfpb.summarize(
        records,
        months=months,
        rate_year=RATE_YEAR,
        county_years=COUNTY_YEARS,
        zcta_county=zcta_county,
    )

    # ---- Schedule H (cached parsed filings)
    filers = [
        json.loads(p.read_text())
        for p in sorted((raw_dir / "schedule_h").glob("*.json"))
        if p.stat().st_size > 2
    ]
    for filer in filers:  # also normalize filings cached before the 0% rule
        for key in ("free_fpg", "discount_fpg"):
            filer[key] = schedule_h.positive_pct(filer.get(key))
            for policy in filer["policies"]:
                policy[key] = schedule_h.positive_pct(policy.get(key))
    schedule_h.match_facilities(filers, hospitals)
    hospital_by_id = {h["id"]: h for h in hospitals}
    filer_rows = []
    for filer_index, filer in enumerate(sorted(filers, key=lambda f: f["name"])):
        for facility in filer["facilities"]:
            hospital = hospital_by_id.get(facility.get("cms_id"))
            if hospital and facility.get("policy") is not None and "policy_ref" not in hospital:
                hospital["policy_ref"] = [filer_index, facility["policy"]]
        filer_rows.append(
            {
                **{k: v for k, v in filer.items() if k not in {"facilities", "policies"}},
                "facilities": [
                    {k: facility.get(k) for k in ("name", "city", "state", "zip", "website", "cms_id", "match", "policy")}
                    for facility in filer["facilities"]
                ],
                "policies": [compact_policy(p) for p in filer["policies"]],
            }
        )

    # ---- states
    state_rows = {k: v for k, v in census.items() if k.startswith("0400000US")}
    national_count = complaints["national"]["count"]
    us_pop = sum(v["population"] or 0 for k, v in state_rows.items() if v["fips"] not in MODEL_EXCLUDE)
    national_rate = national_count / us_pop * 100_000
    hospitals_by_state: dict[str, list[dict]] = defaultdict(list)
    for hospital in hospitals:
        hospitals_by_state[hospital["state"]].append(hospital)

    states = []
    for row in state_rows.values():
        abbr = row["state_abbr"]
        c = complaints["states"].get(abbr, {})
        count = c.get("count", 0)
        population = row["population"] or 0
        low, high = poisson_ci(count)
        in_state = hospitals_by_state.get(abbr, [])
        ownership = Counter(h["ownership_class"] for h in in_state)
        nonprofit = [h for h in in_state if h["ownership_class"] == "nonprofit"]
        linked = [
            filer_rows[h["policy_ref"][0]]["policies"][h["policy_ref"][1]]
            for h in nonprofit
            if h.get("policy_ref")
        ]
        states.append(
            {
                **row,
                "complaints": count,
                "rate_per_100k": round(count / population * 100_000, 3) if population else None,
                "rate_ci": [
                    round(low / population * 100_000, 3),
                    round(high / population * 100_000, 3),
                ]
                if population
                else None,
                "per_10k_uninsured": round(count / row["uninsured"] * 10_000, 3)
                if row["uninsured"]
                else None,
                "ratio_to_national": round(count / (population * national_rate / 100_000), 3)
                if population
                else None,
                "paid": c.get("paid", 0),
                "not_owed": c.get("not_owed", []),
                "issues": c.get("issues", []),
                "responses": c.get("responses", []),
                "top_companies": c.get("top_companies", []),
                "timely": c.get("timely", 0),
                "servicemember": c.get("servicemember", 0),
                "older_american": c.get("older_american", 0),
                "zip5": c.get("zip5", 0),
                "monthly": c.get("monthly", [0] * len(months)),
                "hospitals": dict(ownership),
                "nonprofit_hospitals": len(nonprofit),
                "nonprofit_linked": len(linked),
                "schedule_h": policy_summary(linked),
            }
        )

    modeled = [s for s in states if s["fips"] not in MODEL_EXCLUDE and s["population"]]
    model = fit_poisson(
        [
            {
                "count": s["complaints"],
                "population": s["population"],
                "uninsured_rate": s["uninsured_rate"],
                "poverty_rate": s["poverty_rate"],
            }
            for s in modeled
        ],
        ["uninsured_rate", "poverty_rate"],
    )
    for state, expected in zip(modeled, model.pop("expected")):
        state["expected_adjusted"] = round(expected, 1)
        state["adjusted_ratio"] = round(state["complaints"] / expected, 3) if expected else None
    burden_cuts = tercile_cuts([s["rate_per_100k"] for s in modeled])
    need_cuts = tercile_cuts([s["uninsured_rate"] for s in modeled])
    for state in states:
        state["bivariate"] = (
            [tercile(state["uninsured_rate"], need_cuts), tercile(state["rate_per_100k"], burden_cuts)]
            if state["fips"] not in MODEL_EXCLUDE
            else None
        )
    states.sort(key=lambda s: s["name"])

    # ---- counties (pooled years, annualized)
    years = COUNTY_YEARS[1] - COUNTY_YEARS[0] + 1
    county_counts = complaints["counties"]["counts"]
    counties = []
    for geo_id, row in census.items():
        if not geo_id.startswith("0500000US"):
            continue
        count = county_counts.get(row["fips"], 0)
        population = row["population"] or 0
        reportable = count >= COUNTY_MIN_COUNT and population > 0
        counties.append(
            {
                "fips": row["fips"],
                "name": row["name"],
                "state": row["state_abbr"],
                "population": population,
                "uninsured_rate": row["uninsured_rate"],
                "poverty_rate": row["poverty_rate"],
                "median_income": row["median_income"],
                "complaints": count,
                "annual_rate_per_100k": round(count / years / population * 100_000, 2)
                if reportable
                else None,
            }
        )

    # ---- price-transparency basket (cached per hospital by the refresh script)
    price_rows = {}
    price_status: Counter = Counter()
    for path in sorted((raw_dir / "prices").glob("*.json")):
        cached = json.loads(path.read_text())
        price_status[cached.get("status", "unknown")] += 1
        if cached.get("prices"):
            price_rows[cached["hospital_id"]] = {
                k: cached[k] for k in ("location_name", "mrf_url", "prices")
            }
    for hospital in hospitals:
        hospital["has_prices"] = hospital["id"] in price_rows

    hospital_fields = [
        "id", "name", "city", "state", "zip", "county_fips", "type", "ownership",
        "ownership_class", "emergency", "rating", "lat", "lon", "policy_ref", "has_prices",
    ]
    hospital_rows = [[h.get(f) for f in hospital_fields] for h in hospitals]

    national = complaints["national"]
    facility_links = [f for filer in filer_rows for f in filer["facilities"]]
    generated = utc_now()
    summary = {
        "generated_at": generated,
        "rate_year": RATE_YEAR,
        "months": months,
        "national": {
            **national,
            "rate_per_100k": round(national_rate, 3),
            "population": us_pop,
        },
        "model": model,
        "bivariate_cuts": {"uninsured_rate": need_cuts, "rate_per_100k": burden_cuts},
        "counts": {
            "cfpb_records": len(records),
            "cms_hospitals": len(hospitals),
            "cms_hospitals_located": sum(h["lat"] is not None for h in hospitals),
            "schedule_h_filers": len(filer_rows),
            "schedule_h_facilities": len(facility_links),
            "schedule_h_facilities_linked": sum(bool(f["cms_id"]) for f in facility_links),
            "cms_nonprofit": sum(h["ownership_class"] == "nonprofit" for h in hospitals),
            "cms_nonprofit_with_policy": sum(
                h["ownership_class"] == "nonprofit" and bool(h.get("policy_ref")) for h in hospitals
            ),
            "price_hospitals_attempted": sum(price_status.values()),
            "price_hospitals_with_basket": len(price_rows),
            "county_complaints": complaints["counties"]["total"],
            "county_complaints_mapped": complaints["counties"]["mapped"],
        },
        "states": states,
    }
    outputs = {
        "states.json": summary,
        "counties.json": {
            "generated_at": generated,
            "years": list(COUNTY_YEARS),
            "min_count": COUNTY_MIN_COUNT,
            "unmapped_by_state": complaints["counties"]["unmapped_by_state"],
            "counties": counties,
        },
        "hospitals.json": {"generated_at": generated, "fields": hospital_fields, "rows": hospital_rows},
        "schedule_h.json": {"generated_at": generated, "filers": filer_rows},
        "prices.json": {
            "generated_at": generated,
            "basket": prices.BASKET,
            "status": dict(price_status),
            "hospitals": price_rows,
        },
    }
    for name, value in outputs.items():
        (out_dir / name).write_text(json.dumps(value, separators=(",", ":")))
    return {
        "inputs": {
            "cfpb_medical.jsonl": sha256_file(records_path),
            "cms_hospital_general_information.csv": sha256_file(hospitals_path),
            **{p.name: sha256_file(p) for p in geo_paths.values()},
            **{p.name: sha256_file(p) for p in acs_paths.values()},
        },
        "outputs": {name: sha256_file(out_dir / name) for name in outputs},
        "counts": summary["counts"],
        "model": model,
    }
