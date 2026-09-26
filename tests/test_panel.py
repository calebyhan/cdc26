import csv
import json
from datetime import date

import duckdb
import pytest

from ews.features.panel import (
    BANK_FEATURES,
    NUMERIC_FEATURES,
    build,
    complaint_features,
    jsd,
    latest_available,
    month_date,
    month_index,
)
from ews.ingest.complaints import connection
from ews.ingest.exposures import stage_hmda_csv, version_available


def parquet(con, path, sql):
    path.parent.mkdir(parents=True, exist_ok=True)
    con.sql(sql).write_parquet(str(path))


@pytest.fixture
def inputs(tmp_path):
    data = tmp_path / "data"
    ref = data / "reference"
    ref.mkdir(parents=True)
    con = connection()
    parquet(
        con,
        data / "marts/entity.parquet",
        """SELECT * FROM (VALUES
      ('bank','Bank','bank','bank',[1,2]::INTEGER[],'100',NULL::DATE,NULL::DATE),
      ('servicer','Servicer','nonbank_servicer','nonbank_servicer',[1]::INTEGER[],'100',NULL::DATE,NULL::DATE),
      ('lender','Lender','nonbank_originator','nonbank_originator',[]::INTEGER[],'',NULL::DATE,NULL::DATE))
      t(entity_id,display_name,type,peer_group,fdic_certs,rssdhcr,valid_from,valid_to)""",
    )
    parquet(
        con,
        data / "staging/stg_complaints.parquet",
        """SELECT
      row_number() OVER(ORDER BY m DESC,firm,copy)::BIGINT complaint_id,
      (m+INTERVAL 14 DAY)::DATE date_received,
      (m+INTERVAL 29 DAY)::DATE date_sent_to_company,
      firm company, 'servicing_payments_escrow' issue_std, 2 severity_tier,
      CASE WHEN copy=2 THEN 'in_progress' ELSE 'explanation' END response_std,
      copy=1 response_metrics_eligible,
      CASE WHEN copy=2 THEN 'No' ELSE 'Yes' END timely,
      'Older American, Servicemember' tags,
      CASE WHEN copy=1 THEN 'NC' ELSE 'VA' END state,
      'Ignore this narrative entirely' complaint_narrative
      FROM generate_series(DATE '2018-01-01',DATE '2023-12-01',INTERVAL 1 MONTH) g(m)
      CROSS JOIN (VALUES ('bank',1),('servicer',1),('servicer',2)) f(firm,copy)
      ORDER BY date_received DESC""",
    )
    parquet(
        con,
        data / "marts/complaint_entity.parquet",
        f"""SELECT complaint_id,date_received,company,company entity_id
      FROM read_parquet('{data / 'staging/stg_complaints.parquet'}')""",
    )
    parquet(
        con,
        data / "marts/enforcement_entity.parquet",
        """SELECT 'bank' entity_id,
      DATE '2023-06-15' date_filed, 'action' action_id""",
    )
    parquet(
        con,
        data / "staging/stg_fdic_financials.parquet",
        """SELECT * FROM (VALUES
      (1,'100',DATE '2020-03-31',DATE '2020-05-15',1000,800,100,300,500,20,1,NULL,3),
      (2,'100',DATE '2020-03-31',DATE '2020-05-15',3000,2400,300,900,1500,60,3,NULL,7),
      (1,'100',DATE '2020-06-30',DATE '2020-08-14',2000,1600,200,600,1000,40,2,NULL,4),
      (2,'100',DATE '2020-06-30',DATE '2020-08-14',6000,4800,600,1800,3000,120,6,NULL,8))
      t(cert,rssdhcr,report_date,available_from,asset,dep,eq,lnreres,lnlsgr,nclnls,elnatq,elnlosq,offdom)""",
    )
    parquet(
        con,
        data / "staging/stg_hmda_lender_year.parquet",
        """SELECT * FROM (VALUES
      ('LEIBANK',2020,DATE '2021-06-17',100,200,20,150,40,.1,1),
      ('LEIBANK',2021,DATE '2022-06-01',200,400,40,300,80,.1,1),
      ('LEILENDER',2019,DATE '2020-07-01',50,100,10,75,20,.2,2),
      ('LEISERVICER',2020,DATE '2021-06-17',20,40,4,30,8,.2,2))
      t(lei,year,available_from,originations,applications,denials,decisions,refinances,top_state_share,n_states)""",
    )
    with (ref / "hmda_lei_manual.csv").open("w") as output:
        writer = csv.writer(output)
        writer.writerow(["entity_id", "lei", "valid_from", "valid_to"])
        writer.writerows(
            [
                ["bank", "LEIBANK", "", ""],
                ["lender", "LEILENDER", "", ""],
                ["servicer", "LEISERVICER", "", ""],
            ]
        )
    (ref / "entity_relationships.csv").write_text(
        "entity_id,successor_entity_id,relationship,effective_date\n"
    )
    (data / "marts/resolution_report.json").write_text(
        json.dumps(
            {"reviewed_complaint_coverage": 1, "mortgage_company_party_coverage": 1}
        )
    )
    con.close()
    return data, ref


def query(data, sql):
    with duckdb.connect() as con:
        con.read_parquet(str(data / "marts/company_month.parquet")).create_view("panel")
        return con.execute(sql).fetchall()


def test_calendar_windows_and_response_eligibility(inputs):
    data, ref = inputs
    build(data, date(2020, 1, 1), date(2022, 9, 26), ref)
    assert (
        query(
            data,
            """SELECT c_3m,c_6m,c_12m,c_prev6m,c_growth_6v6,c_accel,
      untimely_rate_12m,relief_share_12m,explanation_only_share,
      older_american_share,servicemember_share,state_hhi_12m,servicer_issue_share
      FROM panel WHERE entity_id='servicer' AND month=DATE '2022-09-01'""",
        )
        == [(6, 12, 24, 12, 0.0, 0.0, 0.0, 0.0, 1.0, 1.0, 1.0, 0.5, 1.0)]
    )
    assert query(
        data,
        "SELECT c_3m FROM panel WHERE entity_id='bank' AND month=DATE '2020-01-01'",
    ) == [(3,)]


def test_publication_join_and_holding_company_sums(inputs):
    data, ref = inputs
    build(data, date(2020, 1, 1), date(2022, 9, 26), ref)
    assert query(
        data,
        "SELECT has_fdic,assets_lag FROM panel WHERE entity_id='bank' AND month=DATE '2020-05-01'",
    ) == [(0, None)]
    assert (
        query(
            data,
            """SELECT assets_lag,deposits_lag,equity_to_assets_lag,
      resi_loans_share_lag,noncurrent_ratio_lag,provision_ratio_lag,branch_count_lag
      FROM panel WHERE entity_id='bank' AND month=DATE '2020-06-01'""",
        )
        == [(4000.0, 3200.0, 0.1, 0.3, 0.04, 0.008, 10.0)]
    )
    assert query(
        data,
        "SELECT assets_lag FROM panel WHERE entity_id='bank' AND month=DATE '2020-08-01'",
    ) == [(4000.0,)]
    assert query(
        data,
        "SELECT assets_lag FROM panel WHERE entity_id='bank' AND month=DATE '2020-09-01'",
    ) == [(8000.0,)]
    assert query(
        data,
        "SELECT has_hmda FROM panel WHERE entity_id='bank' AND month=DATE '2021-06-01'",
    ) == [(0,)]
    assert query(
        data,
        "SELECT hmda_year,hmda_originations_lag FROM panel WHERE entity_id='bank' AND month=DATE '2022-06-01'",
    ) == [(2020, 100.0)]
    assert query(
        data,
        "SELECT hmda_year,hmda_orig_growth_yoy_lag FROM panel WHERE entity_id='bank' AND month=DATE '2022-07-01'",
    ) == [(2021, 1.0)]
    assert query(data, "SELECT min(month) FROM panel WHERE entity_id='lender'") == [
        (date(2020, 8, 1),)
    ]


def test_structural_nulls_survive_peer_imputation(inputs):
    data, ref = inputs
    build(data, date(2020, 1, 1), date(2022, 9, 26), ref)
    columns = BANK_FEATURES + [
        "c_per_1k_orig",
        "c_per_servicing",
        "sev_weighted_rate",
        "hmda_originations_lag",
    ]
    assert all(
        all(x is None for x in r)
        for r in query(
            data,
            "SELECT "
            + ",".join(columns + [c + "_peer_z" for c in columns])
            + " FROM panel WHERE entity_id='servicer'",
        )
    )


def test_future_sources_cannot_change_historical_features(inputs):
    data, ref = inputs
    cutoff = date(2022, 9, 26)
    build(data, date(2020, 1, 1), cutoff, ref)
    projection = ",".join(["entity_id", "month", *NUMERIC_FEATURES])
    before = query(
        data, "SELECT " + projection + " FROM panel ORDER BY entity_id,month"
    )
    with duckdb.connect() as con:
        path = data / "staging/stg_fdic_financials.parquet"
        con.read_parquet(str(path)).create("old")
        con.execute(
            "INSERT INTO old SELECT cert,rssdhcr,DATE '2029-03-31',DATE '2020-01-01',999999999,dep,eq,lnreres,lnlsgr,nclnls,elnatq,elnlosq,offdom FROM old LIMIT 1"
        )
        con.table("old").write_parquet(str(path))
        path = data / "staging/stg_hmda_lender_year.parquet"
        con.read_parquet(str(path)).create("old_hmda")
        con.execute(
            "INSERT INTO old_hmda SELECT lei,2029,DATE '2030-06-01',999999999,applications,denials,decisions,refinances,top_state_share,n_states FROM old_hmda"
        )
        con.table("old_hmda").write_parquet(str(path))
    build(data, date(2020, 1, 1), cutoff, ref)
    assert (
        query(data, "SELECT " + projection + " FROM panel ORDER BY entity_id,month")
        == before
    )


def test_no_future_rows_and_received_order(inputs):
    data, ref = inputs
    build(data, date(2020, 1, 1), date(2022, 9, 26), ref)
    assert query(data, "SELECT max(month),max(interval_stop) FROM panel") == [
        (date(2022, 9, 1), date(2022, 9, 27))
    ]
    with duckdb.connect() as con:
        result = con.read_parquet(str(data / "marts/complaint_features_input.parquet"))
        rows = result.project("date_received,complaint_id").fetchall()
        assert rows == sorted(rows)
        assert "complaint_narrative" not in result.columns
        assert "date_sent_to_company" not in result.columns
    with pytest.raises(ValueError, match="future"):
        build(data, end=date(2099, 1, 1), reference=ref)


def test_first_event_horizon_and_censoring(inputs):
    data, ref = inputs
    build(data, date(2020, 1, 1), date(2023, 9, 26), ref)
    assert query(
        data,
        "SELECT sum(event),max(month),max(interval_stop) FROM panel WHERE entity_id='bank'",
    ) == [(1, date(2023, 6, 1), date(2023, 6, 16))]
    assert query(
        data,
        "SELECT event_next_6m FROM panel WHERE entity_id='bank' AND month=DATE '2023-01-01'",
    ) == [(1,)]
    assert query(
        data,
        "SELECT event_next_6m FROM panel WHERE entity_id='servicer' AND month=DATE '2023-09-01'",
    ) == [(None,)]
    assert query(
        data,
        "SELECT event_next_6m FROM panel WHERE entity_id='servicer' AND month=DATE '2022-01-01'",
    ) == [(0,)]
    assert query(data, "SELECT count(*) FROM panel WHERE stop<=start") == [(0,)]


def test_mergers_censor_and_recent_merger_is_past_only(inputs):
    data, ref = inputs
    (ref / "entity_relationships.csv").write_text(
        "entity_id,successor_entity_id,relationship,effective_date\n"
        "bank,lender,bank_merger,2021-03-15\n"
    )
    build(data, date(2020, 1, 1), date(2022, 9, 26), ref)
    assert query(
        data,
        "SELECT max(month),max(interval_stop),sum(event) FROM panel WHERE entity_id='bank'",
    ) == [(date(2021, 3, 1), date(2021, 3, 15), 0)]


def test_m2_numerical_gate(inputs):
    data, ref = inputs
    (data / "marts/resolution_report.json").write_text(
        json.dumps(
            {"reviewed_complaint_coverage": 0.93, "mortgage_company_party_coverage": 1}
        )
    )
    with pytest.raises(ValueError, match="M2"):
        build(data, reference=ref)


def test_revised_version_not_backdated():
    metadata = {
        "last_modified": "Fri, 21 Nov 2025 18:27:40 GMT",
        "retrieved_at": "2026-09-26T10:00:00+00:00",
    }
    assert version_available("2019-08-30", metadata) == date(2025, 11, 21)
    assert version_available("2026-06-23", metadata) == date(2026, 6, 23)
    assert version_available(
        "2019-08-30", {"retrieved_at": metadata["retrieved_at"]}
    ) == date(2026, 9, 26)


def test_strict_availability_and_future_period():
    rows = [
        {"report_date": date(2020, 3, 31), "available_from": date(2020, 6, 1)},
        {"report_date": date(2030, 3, 31), "available_from": date(2019, 1, 1)},
    ]
    assert latest_available(rows, date(2020, 6, 1), "report_date") is None
    assert latest_available(rows, date(2020, 7, 1), "report_date") == rows[0]


def test_hmda_counts_exclude_purchased_loans(tmp_path):
    path = tmp_path / "lar.csv"
    path.write_text(
        "lei,action_taken,loan_purpose,state_code\n"
        "A,1,31,NC\nA,1,1,NC\nA,1,32,VA\nA,3,1,NC\nA,2,1,NA\nA,6,31,VA\nA,4,1,VA\n"
    )
    with connection() as con:
        stage_hmda_csv(con, path, 2020, date(2021, 6, 17))
        assert con.execute(
            "SELECT originations,applications,denial_rate,refi_share,top_state_share,n_states,available_from FROM hmda_year"
        ).fetchone() == (3, 6, 0.2, 2 / 3, 2 / 3, 2, date(2021, 6, 17))


def test_jsd_and_calendar_leap_arithmetic():
    assert jsd({"a": 2}, {"a": 1}) == 0
    assert jsd({"a": 2}, {"b": 1}) == 1
    assert jsd({}, {"a": 1}) is None
    assert month_date(month_index(date(2020, 2, 29)) + 1) == date(2020, 3, 1)


def test_received_window_boundaries_and_growth():
    # At May 1, April is the publication buffer; Jan–Mar is the current 3m.
    def mi(y, m):
        return month_index(date(y, m, 1))

    counts = {
        mi(2020, 1): {"n": 2},
        mi(2020, 2): {"n": 3},
        mi(2020, 3): {"n": 5},
        mi(2020, 4): {"n": 1000},
        mi(2019, 9): {"n": 7},
    }
    values = complaint_features(counts, {}, {}, {}, date(2020, 5, 1))
    assert values["c_3m"] == 10
    assert values["c_6m"] == 10
    assert values["c_prev6m"] == 7
    assert values["c_12m"] == 17
    import math

    assert values["c_growth_6v6"] == pytest.approx(math.log(11 / 8))
    assert values["c_accel"] == pytest.approx(math.log(11 / 8) - math.log(8))


def test_future_complaints_do_not_leak_and_unmapped_market_is_included(inputs):
    data, ref = inputs
    build(data, date(2020, 1, 1), date(2022, 9, 26), ref)
    projection = ",".join(["entity_id", "month", *NUMERIC_FEATURES])
    before = query(
        data, "SELECT " + projection + " FROM panel ORDER BY entity_id,month"
    )
    with duckdb.connect() as con:
        path = data / "staging/stg_complaints.parquet"
        con.read_parquet(str(path)).create("complaints")
        con.execute("""INSERT INTO complaints SELECT 999999, DATE '2030-01-01',
          DATE '2010-01-01', company,issue_std,severity_tier,response_std,
          response_metrics_eligible,timely,tags,state,complaint_narrative
          FROM complaints WHERE company='bank' LIMIT 1""")
        con.table("complaints").write_parquet(str(path))
        path = data / "marts/complaint_entity.parquet"
        con.read_parquet(str(path)).create("links")
        con.execute(
            "INSERT INTO links VALUES (999999, DATE '2030-01-01','bank','bank')"
        )
        con.table("links").write_parquet(str(path))
    build(data, date(2020, 1, 1), date(2022, 9, 26), ref)
    assert (
        query(data, "SELECT " + projection + " FROM panel ORDER BY entity_id,month")
        == before
    )
    with duckdb.connect() as con:
        from ews.features.panel import complaints_input

        _, _, _, market = complaints_input(con, data, date(2022, 9, 26))
        assert market[month_index(date(2022, 5, 1))] == 3
        path = data / "marts/complaint_entity.parquet"
        con.read_parquet(str(path)).create("links")
        con.execute("UPDATE links SET entity_id=NULL WHERE company='bank'")
        con.table("links").write_parquet(str(path))
    with duckdb.connect() as con:
        _, _, _, market_after = complaints_input(con, data, date(2022, 9, 26))
        assert market_after == market


def test_stale_m2_crosswalk_rejected(inputs):
    data, ref = inputs
    with duckdb.connect() as con:
        path = data / "marts/complaint_entity.parquet"
        con.read_parquet(str(path)).create("links")
        con.execute("UPDATE links SET date_received=DATE '2000-01-01'")
        con.table("links").write_parquet(str(path))
    with pytest.raises(ValueError, match="stale"):
        build(data, reference=ref)


def test_recent_merger_uses_history_and_never_future_dates(inputs):
    data, ref = inputs
    with duckdb.connect() as con:
        parquet(
            con,
            data / "staging/stg_fdic_history.parquet",
            """SELECT * FROM (VALUES
          ('223','1','1',DATE '2021-03-15'),
          ('223','2','2',DATE '2028-01-01'),
          ('510','1','1',DATE '2021-02-01'))
          t(CHANGECODE,SUR_CERT,ACQ_CERT,EFFDATE)""",
        )
    build(data, date(2020, 1, 1), date(2023, 9, 26), ref)
    assert query(
        data,
        "SELECT recent_merger_24m FROM panel WHERE entity_id='bank' AND month=DATE '2021-03-01'",
    ) == [(0.0,)]
    assert query(
        data,
        "SELECT recent_merger_24m FROM panel WHERE entity_id='bank' AND month=DATE '2021-04-01'",
    ) == [(1.0,)]
    assert query(
        data,
        "SELECT recent_merger_24m FROM panel WHERE entity_id='bank' AND month=DATE '2023-04-01'",
    ) == [(0.0,)]


def test_partial_year_lei_identity_does_not_assign_whole_year(inputs):
    data, ref = inputs
    with (ref / "hmda_lei_manual.csv").open() as source:
        rows = list(csv.DictReader(source))
    for row in rows:
        if row["lei"] == "LEIBANK":
            row["valid_from"] = "2021-12-01"
    with (ref / "hmda_lei_manual.csv").open("w") as output:
        writer = csv.DictWriter(output, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    build(data, date(2020, 1, 1), date(2022, 9, 26), ref)
    assert query(data, "SELECT max(has_hmda) FROM panel WHERE entity_id='bank'") == [
        (0,)
    ]


def test_geographic_concentration_independent_of_source_group_order():
    labels = [(f"state{i:02}", i + 1) for i in range(45)]
    month = month_index(date(2020, 1, 1))
    forward = {month: dict(labels)}
    reverse = {month: dict(reversed(labels))}
    first = complaint_features({}, {}, forward, {}, date(2020, 5, 1))
    second = complaint_features({}, {}, reverse, {}, date(2020, 5, 1))
    assert first["state_hhi_12m"] == second["state_hhi_12m"]
