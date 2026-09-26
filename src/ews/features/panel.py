"""Structured complaint features and a monthly first-event counting-process panel."""

import csv
import json
import math
import tempfile
from collections import Counter, defaultdict
from datetime import date, timedelta
from pathlib import Path
from statistics import mean, median, stdev

from ews.ingest.complaints import REFERENCE, connection, sql_path

MODEL_TYPES = {"bank", "credit_union", "nonbank_originator", "nonbank_servicer"}
BANK_FEATURES = [
    "assets_lag",
    "deposits_lag",
    "log_assets",
    "resi_loans_share_lag",
    "noncurrent_ratio_lag",
    "provision_ratio_lag",
    "equity_to_assets_lag",
    "branch_count_lag",
    "c_per_bn_assets",
    "recent_merger_24m",
]
NUMERIC_FEATURES = [
    "c_3m",
    "c_6m",
    "c_12m",
    "c_growth_6v6",
    "c_accel",
    "c_selfz_12m",
    "c_mkt_share_dev",
    "c_per_1k_orig",
    "c_per_servicing",
    "sev3_share_12m",
    "sev_weighted_rate",
    "issue_mix_jsd",
    "servicer_issue_share",
    "untimely_rate_12m",
    "relief_share_12m",
    "explanation_only_share",
    "older_american_share",
    "servicemember_share",
    "state_hhi_12m",
    "state_shift_jsd",
    "hmda_originations_lag",
    "hmda_applications_lag",
    "hmda_denial_rate_lag",
    "hmda_refi_share_lag",
    "hmda_top_state_share_lag",
    "hmda_n_states_lag",
    "hmda_orig_growth_yoy_lag",
    *BANK_FEATURES,
]


def month_index(d):
    return d.year * 12 + d.month - 1


def month_date(i):
    return date(i // 12, i % 12 + 1, 1)


def ratio(n, d, scale=1):
    return n / d * scale if n is not None and d is not None and d > 0 else None


def jsd(left, right):
    """Base-2 Jensen-Shannon divergence, null when either sample is empty."""
    a, b = sum(left.values()), sum(right.values())
    if not a or not b:
        return None
    value = 0.0
    for key in sorted(left.keys() | right.keys()):
        p, q = left.get(key, 0) / a, right.get(key, 0) / b
        m = (p + q) / 2
        value += (p * math.log2(p / m) if p else 0) / 2
        value += (q * math.log2(q / m) if q else 0) / 2
    return value


def counter_window(series, cutoff, width):
    result = Counter()
    for i in range(cutoff - width, cutoff):
        result.update(series.get(i, {}))
    return result


def count_window(series, cutoff, width, key="n"):
    return sum(series.get(i, {}).get(key, 0) for i in range(cutoff - width, cutoff))


def latest_available(rows, cutoff, period_key, max_age=None):
    eligible = [
        r for r in rows if r["available_from"] < cutoff and r[period_key] < cutoff
    ]
    if max_age is not None:
        eligible = [r for r in eligible if (cutoff - r[period_key]).days <= max_age]
    return max(
        eligible, key=lambda r: (r[period_key], r["available_from"]), default=None
    )


def dict_rows(con, sql):
    result = con.execute(sql)
    names = [d[0] for d in result.description]
    return [dict(zip(names, r)) for r in result.fetchall()]


def prepare_exposures(con, data_dir, reference):
    """Join reviewed IDs, sum amounts first, THEN compute holding-company ratios."""
    for name in ["fdic_financials", "hmda_lender_year"]:
        con.read_parquet(str(data_dir / "staging" / f"stg_{name}.parquet")).create_view(
            name
        )
    con.read_csv(str(reference / "hmda_lei_manual.csv"), all_varchar=True).create_view(
        "lei_links"
    )
    con.execute("""CREATE TEMP TABLE fdic_entity AS
        SELECT e.entity_id, f.report_date, max(f.available_from) available_from,
          count(*) cert_count,
          CASE WHEN count(asset)=count(*) THEN sum(asset) END assets,
          CASE WHEN count(dep)=count(*) THEN sum(dep) END deposits,
          CASE WHEN count(eq)=count(*) THEN sum(eq) END equity,
          CASE WHEN count(lnreres)=count(*) THEN sum(lnreres) END resi_loans,
          CASE WHEN count(lnlsgr)=count(*) THEN sum(lnlsgr) END loans,
          CASE WHEN count(nclnls)=count(*) THEN sum(nclnls) END noncurrent,
          CASE WHEN count(coalesce(elnatq,elnlosq))=count(*)
            THEN sum(coalesce(elnatq,elnlosq)) END provisions,
          CASE WHEN count(offdom)=count(*) THEN sum(offdom) END branches
        FROM fdic_financials f JOIN entities e ON e.type='bank'
          AND ((nullif(f.rssdhcr,'') IS NOT NULL AND f.rssdhcr=e.rssdhcr)
            OR (nullif(f.rssdhcr,'') IS NULL AND list_contains(e.fdic_certs,f.cert)))
          AND (e.valid_from IS NULL OR f.report_date>=e.valid_from)
          AND (e.valid_to IS NULL OR f.report_date<=e.valid_to)
        GROUP BY e.entity_id,f.report_date""")
    # A partial-year ownership link cannot assign an entire lender-year to a new
    # owner: public LAR lacks unredacted loan dates. Retain those rows unmapped.
    con.execute("""CREATE TEMP TABLE hmda_entity AS
        SELECT l.entity_id, h.year, make_date(h.year,12,31) report_date,
          max(h.available_from) available_from,
          sum(h.originations) originations, sum(h.applications) applications,
          sum(h.denials)::DOUBLE / nullif(sum(h.decisions),0) denial_rate,
          sum(h.refinances)::DOUBLE / nullif(sum(h.originations),0) refi_share,
          CASE WHEN count(*)=1 THEN max(h.top_state_share) END top_state_share,
          CASE WHEN count(*)=1 THEN max(h.n_states) END n_states
        FROM hmda_lender_year h JOIN lei_links l USING(lei)
        JOIN entities e ON e.entity_id=l.entity_id
        WHERE (l.valid_from IS NULL OR l.valid_from::DATE<=make_date(h.year,1,1))
          AND (l.valid_to IS NULL OR l.valid_to::DATE>=make_date(h.year,12,31))
          AND (e.valid_from IS NULL OR e.valid_from<=make_date(h.year,1,1))
          AND (e.valid_to IS NULL OR e.valid_to>=make_date(h.year,12,31))
        GROUP BY l.entity_id,h.year""")
    for table in ["fdic_entity", "hmda_entity"]:
        con.sql(f"SELECT * FROM {table} ORDER BY entity_id,report_date").write_parquet(
            str(data_dir / "marts" / f"{table}.parquet")
        )
    return dict_rows(con, "SELECT * FROM fdic_entity"), dict_rows(
        con, "SELECT * FROM hmda_entity"
    )


def complaints_input(con, data_dir, end):
    con.read_parquet(str(data_dir / "staging/stg_complaints.parquet")).create_view(
        "complaints"
    )
    con.read_parquet(str(data_dir / "marts/complaint_entity.parquet")).create_view(
        "complaint_links"
    )
    if con.execute(
        "SELECT count(*)-count(DISTINCT complaint_id) FROM complaint_links"
    ).fetchone()[0]:
        raise ValueError("Complaint entity join is not one-to-one")
    missing = con.execute(
        """SELECT count(*) FROM complaints c LEFT JOIN complaint_links l USING(complaint_id)
        WHERE l.complaint_id IS NULL OR c.date_received<>l.date_received OR c.company<>l.company"""
    ).fetchone()[0]
    if missing:
        raise ValueError("M2 complaint crosswalk is stale; rerun entity resolution")
    con.execute(
        """CREATE TEMP TABLE feature_input AS
        SELECT l.entity_id, c.complaint_id, c.date_received,
          (c.date_received + INTERVAL 1 MONTH)::DATE available_from,
          date_trunc('month',c.date_received)::DATE received_month,
          c.issue_std,c.severity_tier,c.response_std,c.response_metrics_eligible,
          c.timely,c.tags,c.state
        FROM complaints c JOIN complaint_links l USING(complaint_id)
        WHERE c.date_received<=? ORDER BY c.date_received,c.complaint_id""",
        [end],
    )
    con.sql(
        "SELECT * FROM feature_input ORDER BY date_received,complaint_id"
    ).write_parquet(str(data_dir / "marts/complaint_features_input.parquet"))
    monthly = dict_rows(
        con,
        """SELECT entity_id,received_month,
        count(*) n, sum(severity_tier) severity,
        count(*) FILTER(WHERE severity_tier=3) sev3,
        count(*) FILTER(WHERE issue_std IN ('servicing_payments_escrow','loss_mitigation_foreclosure')) servicing,
        count(*) FILTER(WHERE response_metrics_eligible) response_n,
        count(*) FILTER(WHERE response_metrics_eligible AND (timely='No' OR response_std='untimely')) untimely,
        count(*) FILTER(WHERE response_metrics_eligible AND response_std IN
            ('relief_monetary','relief_nonmonetary','relief_unspecified')) relief,
        count(*) FILTER(WHERE response_metrics_eligible AND response_std='explanation') explanation,
        count(*) FILTER(WHERE list_contains(string_split(tags, ', '),'Older American')) older,
        count(*) FILTER(WHERE list_contains(string_split(tags, ', '),'Servicemember')) military
        FROM feature_input WHERE entity_id IS NOT NULL GROUP BY 1,2 ORDER BY 2,1""",
    )
    counts, issues, states = defaultdict(dict), defaultdict(dict), defaultdict(dict)
    for row in monthly:
        counts[row["entity_id"]][month_index(row["received_month"])] = row
    for dimension, destination in [("issue_std", issues), ("state", states)]:
        condition = (
            "AND state IS NOT NULL AND length(state)=2" if dimension == "state" else ""
        )
        for e, m, key, n in con.execute(
            f"""SELECT entity_id,received_month,{dimension},count(*)
            FROM feature_input WHERE entity_id IS NOT NULL {condition} GROUP BY 1,2,3"""
        ).fetchall():
            destination[e].setdefault(month_index(m), Counter())[key] = n
    # Includes unreviewed companies: market-wide changes must not depend on M2 coverage.
    market = {
        month_index(m): n
        for m, n in con.execute(
            "SELECT received_month,count(*) FROM feature_input GROUP BY 1"
        ).fetchall()
    }
    return counts, issues, states, market


def complaint_features(counts, issues, states, market, scoring_month):
    # One full calendar-month buffer: at September 1, use received < August 1.
    cutoff = month_index(scoring_month) - 1
    values = {f"c_{w}m": count_window(counts, cutoff, w) for w in [3, 6, 12]}
    values["c_prev6m"] = count_window(counts, cutoff - 6, 6)
    growth = math.log((values["c_6m"] + 1) / (values["c_prev6m"] + 1))
    prior_growth = math.log(
        (count_window(counts, cutoff - 3, 6) + 1)
        / (count_window(counts, cutoff - 9, 6) + 1)
    )
    values.update(c_growth_6v6=growth, c_accel=growth - prior_growth)
    # Compare current 3m count with 36 PRIOR overlapping 3m windows. A minimum
    # twelve historical windows is required; do not invent pre-entry zeros.
    first = min(counts, default=cutoff)
    baseline = [
        count_window(counts, i, 3) for i in range(cutoff - 36, cutoff) if i - 3 >= first
    ]
    sd = stdev(baseline) if len(baseline) >= 12 else 0
    values["c_selfz_12m"] = (values["c_3m"] - mean(baseline)) / sd if sd else None
    share = ratio(
        values["c_3m"], sum(market.get(i, 0) for i in range(cutoff - 3, cutoff))
    )
    past = [
        ratio(
            count_window(counts, i, 3), sum(market.get(j, 0) for j in range(i - 3, i))
        )
        for i in range(cutoff - 24, cutoff)
        if i - 3 >= first
    ]
    past = [x for x in past if x is not None]
    values["c_mkt_share_dev"] = (
        share - mean(past) if share is not None and past else None
    )
    n = values["c_12m"]
    values["severity_sum_12m"] = count_window(counts, cutoff, 12, "severity")
    values["sev3_share_12m"] = ratio(count_window(counts, cutoff, 12, "sev3"), n)
    values["servicer_issue_share"] = ratio(
        count_window(counts, cutoff, 12, "servicing"), n
    )
    eligible = count_window(counts, cutoff, 12, "response_n")
    values["untimely_rate_12m"] = ratio(
        count_window(counts, cutoff, 12, "untimely"), eligible, 100
    )
    values["relief_share_12m"] = ratio(
        count_window(counts, cutoff, 12, "relief"), eligible
    )
    values["explanation_only_share"] = ratio(
        count_window(counts, cutoff, 12, "explanation"), eligible
    )
    values["older_american_share"] = ratio(count_window(counts, cutoff, 12, "older"), n)
    values["servicemember_share"] = ratio(
        count_window(counts, cutoff, 12, "military"), n
    )
    values["issue_mix_jsd"] = jsd(
        counter_window(issues, cutoff, 6), counter_window(issues, cutoff - 6, 24)
    )
    values["state_shift_jsd"] = jsd(
        counter_window(states, cutoff, 6), counter_window(states, cutoff - 6, 24)
    )
    geography = counter_window(states, cutoff, 12)
    total = sum(geography.values())
    values["state_hhi_12m"] = (
        math.fsum((geography[k] / total) ** 2 for k in sorted(geography))
        if total
        else None
    )
    return values


def exposure_features(row, financials, hmda):
    cutoff, kind = row["month"], row["type"]
    f = (
        latest_available(financials, cutoff, "report_date", max_age=200)
        if kind == "bank"
        else None
    )
    h = (
        latest_available(hmda, cutoff, "report_date", max_age=1100)
        if kind != "nonbank_servicer"
        else None
    )
    row.update({key: None for key in BANK_FEATURES})
    row.update(
        has_fdic=int(f is not None),
        has_hmda=int(h is not None),
        fdic_report_date=None,
        fdic_available_from=None,
        hmda_year=None,
        hmda_available_from=None,
        c_per_1k_orig=None,
        c_per_servicing=None,
        sev_weighted_rate=None,
        hmda_orig_growth_yoy_lag=None,
    )
    for source, dest in [
        ("originations", "hmda_originations_lag"),
        ("applications", "hmda_applications_lag"),
        ("denial_rate", "hmda_denial_rate_lag"),
        ("refi_share", "hmda_refi_share_lag"),
        ("top_state_share", "hmda_top_state_share_lag"),
        ("n_states", "hmda_n_states_lag"),
    ]:
        row[dest] = h[source] if h else None
    if h:
        row.update(hmda_year=h["year"], hmda_available_from=h["available_from"])
        previous = next(
            (
                p
                for p in hmda
                if p["year"] == h["year"] - 1 and p["available_from"] < cutoff
            ),
            None,
        )
        row["hmda_orig_growth_yoy_lag"] = (
            ratio(h["originations"], previous["originations"]) - 1
            if previous and previous["originations"]
            else None
        )
        if kind in {"bank", "credit_union", "nonbank_originator"}:
            row["c_per_1k_orig"] = ratio(row["c_12m"], h["originations"], 1000)
            if kind != "bank":
                row["sev_weighted_rate"] = ratio(
                    row["severity_sum_12m"], h["originations"], 1000
                )
    if f:
        row.update(
            fdic_report_date=f["report_date"],
            fdic_available_from=f["available_from"],
            assets_lag=f["assets"],
            deposits_lag=f["deposits"],
            branch_count_lag=f["branches"],
        )
        row["log_assets"] = (
            math.log(f["assets"]) if f["assets"] and f["assets"] > 0 else None
        )
        row["resi_loans_share_lag"] = ratio(f["resi_loans"], f["assets"])
        row["noncurrent_ratio_lag"] = ratio(f["noncurrent"], f["loans"])
        row["provision_ratio_lag"] = ratio(f["provisions"], f["loans"], 4)
        row["equity_to_assets_lag"] = ratio(f["equity"], f["assets"])
        row["c_per_bn_assets"] = ratio(row["c_12m"], f["assets"], 1_000_000)
        row["sev_weighted_rate"] = ratio(
            row["severity_sum_12m"], f["assets"], 1_000_000
        )


def standardize_peers(rows):
    """Same scoring month only; preserve raw/structural nulls in the source columns.

    Companion _peer_z columns impute with this month's group median. Training
    folds can instead fit their own transforms to the raw features in M4.
    """
    grouped = defaultdict(list)
    for row in rows:
        grouped[(row["month"], row["peer_group"])].append(row)
    for group in grouped.values():
        for feature in NUMERIC_FEATURES:
            applicable = [
                r
                for r in group
                if not (feature in BANK_FEATURES and r["type"] != "bank")
                and not (
                    feature in {"c_per_1k_orig", "sev_weighted_rate", "c_per_servicing"}
                    and r["type"] == "nonbank_servicer"
                )
            ]
            known = [r[feature] for r in applicable if r[feature] is not None]
            center = median(known) if known else None
            filled = [
                r[feature] if r[feature] is not None else center for r in applicable
            ]
            sd = stdev(filled) if center is not None and len(filled) > 1 else 0
            avg = mean(filled) if center is not None else None
            for r in group:
                r[feature + "_peer_z"] = None
            for r, value in zip(applicable, filled):
                r[feature + "_peer_z"] = (
                    (value - avg) / sd if sd else (0.0 if value is not None else None)
                )


def build(
    data_dir=Path("data"),
    start=date(2014, 1, 1),
    end=None,
    reference=REFERENCE,
    truncate_at_event=True,
    output_name="company_month",
):
    data_dir, reference = Path(data_dir), Path(reference)
    end = end or date.today()
    if end > date.today():
        raise ValueError("Panel end cannot be in the future")
    if start.day != 1 or start > end:
        raise ValueError("Panel start must be a month boundary before the end")
    report = json.loads((data_dir / "marts/resolution_report.json").read_text())
    if (
        report["reviewed_complaint_coverage"] < 0.94
        or report["mortgage_company_party_coverage"] != 1
    ):
        raise ValueError("M2 numerical exit gates must pass before M3")
    marts = data_dir / "marts"
    con = connection()
    try:
        con.read_parquet(str(marts / "entity.parquet")).create_view("entities")
        entities = dict_rows(con, "SELECT * FROM entities ORDER BY entity_id")
        counts, issues, states, market = complaints_input(con, data_dir, end)
        financial, hmda = prepare_exposures(con, data_dir, reference)
        financial_by, hmda_by = defaultdict(list), defaultdict(list)
        for r in financial:
            financial_by[r["entity_id"]].append(r)
        for r in hmda:
            hmda_by[r["entity_id"]].append(r)
        actions = defaultdict(list)
        for e, d in con.execute(
            f"SELECT DISTINCT entity_id,date_filed FROM read_parquet({sql_path(marts / 'enforcement_entity.parquet')}) WHERE date_filed<=?",
            [end],
        ).fetchall():
            actions[e].append(d)
        relationships = list(
            csv.DictReader((reference / "entity_relationships.csv").open())
        )
        merged_into, merger_exit = defaultdict(list), {}
        for r in relationships:
            if r["relationship"] == "bank_merger":
                d = date.fromisoformat(r["effective_date"])
                merged_into[r["successor_entity_id"]].append(d)
                if r["entity_id"] != r["successor_entity_id"]:
                    merger_exit[r["entity_id"]] = d
        history_path = data_dir / "staging/stg_fdic_history.parquet"
        if history_path.exists():
            con.read_parquet(str(history_path)).create_view("bank_history")
            for history in dict_rows(con, "SELECT * FROM bank_history"):
                if str(history["CHANGECODE"]) not in {
                    "221",
                    "222",
                    "223",
                    "224",
                    "225",
                }:
                    continue
                d = history["EFFDATE"]
                incoming_certs = {
                    int(history[f]) for f in ["SUR_CERT", "ACQ_CERT"] if history.get(f)
                }
                for e in entities:
                    if (
                        e["type"] == "bank"
                        and incoming_certs.intersection(e["fdic_certs"])
                        and (e["valid_from"] is None or d >= e["valid_from"])
                        and (e["valid_to"] is None or d <= e["valid_to"])
                    ):
                        merged_into[e["entity_id"]].append(d)
        rows, excluded_events = [], []
        for e in entities:
            eid = e["entity_id"]
            if e["type"] not in MODEL_TYPES:
                continue
            series = counts[eid]
            entries = [month_date(min(series))] if series else []
            # A lender cannot enter a historical universe through a future release.
            entries += [
                max(
                    date(h["year"], 1, 1),
                    month_date(month_index(h["available_from"]) + 1),
                )
                for h in hmda_by[eid]
                if h["available_from"] < end
            ]
            if not entries:
                excluded_events.extend((eid, d.isoformat()) for d in actions[eid])
                continue
            entry = max(start, min(entries), e["valid_from"] or start)
            dates = [d for d in actions[eid] if d >= entry]
            event_date = min(dates, default=None)
            censor = min(
                end + timedelta(days=1),
                (e["valid_to"] + timedelta(days=1)) if e["valid_to"] else date.max,
                merger_exit.get(eid, date.max),
            )
            if event_date and event_date >= censor:
                event_date = None
            exit_date = min(
                censor,
                (
                    event_date + timedelta(days=1)
                    if event_date and truncate_at_event
                    else date.max
                ),
            )
            for mi in range(
                month_index(entry), month_index(exit_date - timedelta(days=1)) + 1
            ):
                month = month_date(mi)
                left, right = max(entry, month), min(month_date(mi + 1), exit_date)
                if right <= left:
                    continue
                row = {
                    "entity_id": eid,
                    "month": month,
                    "type": e["type"],
                    "peer_group": e["peer_group"],
                    "entry_date": entry,
                    "interval_start": left,
                    "interval_stop": right,
                    "start": (left - entry).days,
                    "stop": (right - entry).days,
                    "event": int(event_date is not None and left <= event_date < right),
                    "event_date": event_date,
                    "censor_date": censor - timedelta(days=1),
                    "prior_action": int(any(d < entry for d in actions[eid])),
                    "complaints_received_before": month_date(mi - 1),
                }
                for horizon in [6, 12, 18]:
                    boundary = month_date(mi + horizon)
                    hit = event_date is not None and month <= event_date < boundary
                    row[f"event_next_{horizon}m"] = (
                        1 if hit else (0 if boundary <= censor else None)
                    )
                row.update(
                    complaint_features(series, issues[eid], states[eid], market, month)
                )
                exposure_features(row, financial_by[eid], hmda_by[eid])
                if e["type"] == "bank":
                    row["recent_merger_24m"] = int(
                        any(month_date(mi - 24) <= d < month for d in merged_into[eid])
                    )
                row["data_available_flags"] = (
                    f"fdic={row['has_fdic']};hmda={row['has_hmda']}"
                )
                rows.append(row)
        if not rows:
            raise ValueError("No eligible panel rows")
        rows.sort(key=lambda r: (r["entity_id"], r["month"]))
        standardize_peers(rows)
        validate_rows(rows, end)
        with tempfile.TemporaryDirectory(dir=marts) as tmp:
            path = Path(tmp) / "panel.csv"
            with path.open("w") as output:
                writer = csv.DictWriter(output, fieldnames=list(rows[0]))
                writer.writeheader()
                writer.writerows(rows)
            relation = con.read_csv(str(path), all_varchar=True)
            dates = {
                "month",
                "entry_date",
                "interval_start",
                "interval_stop",
                "event_date",
                "censor_date",
                "complaints_received_before",
                "fdic_report_date",
                "fdic_available_from",
                "hmda_available_from",
            }
            strings = {"entity_id", "type", "peer_group", "data_available_flags"}
            integers = {
                "start",
                "stop",
                "event",
                "prior_action",
                "hmda_year",
                "has_fdic",
                "has_hmda",
                "event_next_6m",
                "event_next_12m",
                "event_next_18m",
                "c_3m",
                "c_6m",
                "c_12m",
                "c_prev6m",
                "severity_sum_12m",
            }
            expressions = [
                f"{key}::{('DATE' if key in dates else 'VARCHAR' if key in strings else 'BIGINT' if key in integers else 'DOUBLE')} AS \"{key}\""
                for key in rows[0]
            ]
            relation.project(",".join(expressions)).order(
                "entity_id,month"
            ).write_parquet(str(Path(tmp) / "company_month.parquet"))
            (Path(tmp) / "company_month.parquet").replace(
                marts / f"{output_name}.parquet"
            )
        result = {
            "rows": len(rows),
            "entities": len({r["entity_id"] for r in rows}),
            "events": sum(r["event"] for r in rows),
            "start": start.isoformat(),
            "end": end.isoformat(),
            "fdic_rows": sum(r["has_fdic"] for r in rows),
            "hmda_rows": sum(r["has_hmda"] for r in rows),
            "mapped_events_without_observed_entry": sorted(excluded_events),
            "availability_policy": "strict < scoring month; complaints one full calendar-month buffer; financial/HMDA current versions never backdated",
            "servicer_policy": "ADR-007 option (a); all servicing exposure rates remain structural nulls",
        }
        (
            marts
            / (
                "panel_report.json"
                if output_name == "company_month"
                else f"{output_name}_report.json"
            )
        ).write_text(json.dumps(result, indent=2) + "\n")
        return result
    finally:
        con.close()


def validate_rows(rows, end):
    seen = set()
    for r in rows:
        key = r["entity_id"], r["month"]
        if key in seen or r["month"] > end or r["stop"] <= r["start"]:
            raise ValueError("Invalid counting-process panel")
        seen.add(key)
        for source in ["fdic", "hmda"]:
            if (
                r[source + "_available_from"]
                and r[source + "_available_from"] >= r["month"]
            ):
                raise ValueError("Future exposure leaked into panel")
        if r["type"] != "bank" and any(r[k] is not None for k in BANK_FEATURES):
            raise ValueError("Bank features assigned to a nonbank")
        if r["type"] == "nonbank_servicer" and any(
            r[k] is not None
            for k in ["c_per_1k_orig", "c_per_servicing", "sev_weighted_rate"]
        ):
            raise ValueError("Inappropriate nonbank servicing denominator")
