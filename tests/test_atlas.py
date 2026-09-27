"""Atlas checks: denominators, Schedule H semantics, linkage, and geographic attribution."""

import json
import math

import pytest

from not_my_debt.atlas import acs, build, cfpb, schedule_h
from not_my_debt.atlas.net import read_zip_member

SCHEDULE_H_XML = """<?xml version="1.0" encoding="utf-8"?>
<Return xmlns="http://www.irs.gov/efile" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
  xsi:schemaLocation="http://www.irs.gov/efile" returnVersion="2023v5.0">
  <ReturnHeader>
    <TaxYr>2024</TaxYr>
    <TaxPeriodEndDt>2024-12-31</TaxPeriodEndDt>
    <Filer>
      <EIN>123456789</EIN>
      <BusinessName><BusinessNameLine1Txt>EXAMPLE HEALTH SYSTEM INC</BusinessNameLine1Txt></BusinessName>
      <USAddress><StateAbbreviationCd>NC</StateAbbreviationCd></USAddress>
    </Filer>
  </ReturnHeader>
  <ReturnData>
    <IRS990ScheduleH>
      <FinancialAssistancePolicyInd>1</FinancialAssistancePolicyInd>
      <WrittenPolicyInd>1</WrittenPolicyInd>
      <FPGReferenceFreeCareInd>1</FPGReferenceFreeCareInd>
      <Percent200Ind>X</Percent200Ind>
      <FPGReferenceDiscountedCareInd>1</FPGReferenceDiscountedCareInd>
      <Percent400Ind>X</Percent400Ind>
      <FreeCareMedicallyIndigentInd>1</FreeCareMedicallyIndigentInd>
      <FinancialAssistanceAtCostTyp>
        <NetCommunityBenefitExpnsAmt>1000</NetCommunityBenefitExpnsAmt>
        <TotalExpensePct>0.0100</TotalExpensePct>
      </FinancialAssistanceAtCostTyp>
      <BadDebtExpenseAmt>500</BadDebtExpenseAmt>
      <WrittenDebtCollectionPolicyInd>1</WrittenDebtCollectionPolicyInd>
      <HospitalFacilitiesGrp>
        <FacilityNum>1</FacilityNum>
        <BusinessName><BusinessNameLine1Txt>EXAMPLE MEMORIAL HOSPITAL</BusinessNameLine1Txt></BusinessName>
        <USAddress><CityNm>DURHAM</CityNm><StateAbbreviationCd>NC</StateAbbreviationCd><ZIPCd>27710-1234</ZIPCd></USAddress>
        <FacilityReportingGroupCd>A</FacilityReportingGroupCd>
      </HospitalFacilitiesGrp>
      <HospitalFacilitiesGrp>
        <FacilityNum>2</FacilityNum>
        <BusinessName><BusinessNameLine1Txt>EXAMPLE RALEIGH HOSPITAL</BusinessNameLine1Txt></BusinessName>
        <USAddress><CityNm>RALEIGH</CityNm><StateAbbreviationCd>NC</StateAbbreviationCd><ZIPCd>27609</ZIPCd></USAddress>
      </HospitalFacilitiesGrp>
      <HospitalFacilitiesGrp>
        <FacilityNum>3</FacilityNum>
        <BusinessName><BusinessNameLine1Txt>EXAMPLE REGIONAL HOSPITAL</BusinessNameLine1Txt></BusinessName>
        <USAddress><CityNm>DURHAM</CityNm><StateAbbreviationCd>NC</StateAbbreviationCd><ZIPCd>27704</ZIPCd></USAddress>
        <FacilityReportingGroupCd>A</FacilityReportingGroupCd>
      </HospitalFacilitiesGrp>
      <HospitalFcltyPoliciesPrctcGrp>
        <HospitalFacilityName><BusinessNameLine1Txt>GROUP A</BusinessNameLine1Txt></HospitalFacilityName>
        <FPGFamilyIncmLmtFreeCarePct>200.000</FPGFamilyIncmLmtFreeCarePct>
        <FPGFamilyIncmLmtDscntCarePct>400.000</FPGFamilyIncmLmtDscntCarePct>
        <FAPAvailableOnWebsiteURLTxt>WWW.EXAMPLE.ORG/FAP</FAPAvailableOnWebsiteURLTxt>
        <NotifiedFAPCopyBillDisplayInd>X</NotifiedFAPCopyBillDisplayInd>
        <FAPActionsOnNonpaymentInd>1</FAPActionsOnNonpaymentInd>
        <PermitNoActionsInd>X</PermitNoActionsInd>
        <CollectionActivitiesInd>0</CollectionActivitiesInd>
        <AmountsGenerallyBilledInd>0</AmountsGenerallyBilledInd>
      </HospitalFcltyPoliciesPrctcGrp>
      <HospitalFcltyPoliciesPrctcGrp>
        <HospitalFacilityName><BusinessNameLine1Txt>EXAMPLE RALEIGH HOSPITAL</BusinessNameLine1Txt></HospitalFacilityName>
        <FPGFamilyIncmLmtFreeCarePct>150.000</FPGFamilyIncmLmtFreeCarePct>
        <FAPActionsOnNonpaymentInd>1</FAPActionsOnNonpaymentInd>
        <PermitReportToCreditAgencyInd>X</PermitReportToCreditAgencyInd>
        <PermitLegalJudicialProcessInd>X</PermitLegalJudicialProcessInd>
        <CollectionActivitiesInd>1</CollectionActivitiesInd>
        <FacilityNum>2</FacilityNum>
      </HospitalFcltyPoliciesPrctcGrp>
    </IRS990ScheduleH>
  </ReturnData>
</Return>"""


def test_schedule_h_parses_header_part1_and_namespaced_xml():
    parsed = schedule_h.parse_return(SCHEDULE_H_XML)
    assert parsed["ein"] == "123456789"
    assert parsed["state"] == "NC"
    assert parsed["tax_year"] == "2024"
    assert (parsed["free_fpg"], parsed["discount_fpg"]) == (200.0, 400.0)
    assert parsed["financial_assistance_cost"] == 1000
    assert parsed["bad_debt_expense"] == 500
    assert parsed["facilities"][0]["zip"] == "27710"


def test_zero_percent_fpg_limit_is_not_a_threshold():
    xml = SCHEDULE_H_XML.replace(
        "<FPGFamilyIncmLmtFreeCarePct>150.000", "<FPGFamilyIncmLmtFreeCarePct>0.000"
    )
    assert schedule_h.parse_return(xml)["policies"][1]["free_fpg"] is None


def test_schedule_h_returns_none_without_schedule():
    assert schedule_h.parse_return("<Return><ReturnHeader/></Return>") is None


def test_group_policy_applies_to_grouped_facilities_and_numbered_policy_to_its_facility():
    parsed = schedule_h.parse_return(SCHEDULE_H_XML)
    by_num = {f["num"]: f["policy"] for f in parsed["facilities"]}
    assert by_num == {"1": 0, "2": 1, "3": 0}


def test_line_18_is_read_as_actions_before_eligibility_efforts():
    parsed = schedule_h.parse_return(SCHEDULE_H_XML)
    group, single = parsed["policies"]
    assert group["no_ecas_before_efforts"] is True
    assert group["ecas_permitted_before_efforts"] == []
    assert group["ecas_before_reasonable_efforts"] is False
    assert group["notice_on_bills"] is True
    assert single["ecas_permitted_before_efforts"] == ["credit_reporting", "legal_process"]
    assert single["ecas_before_reasonable_efforts"] is True
    # A missing answer stays unknown rather than defaulting to "no".
    assert single["notice_on_bills"] is None


def hospital(id_, name, zip_code, city="DURHAM", state="NC"):
    return {"id": id_, "name": name, "zip": zip_code, "city": city, "state": state}


def test_facility_linkage_requires_name_overlap_not_just_a_shared_zip():
    filers = [schedule_h.parse_return(SCHEDULE_H_XML)]
    hospitals = [
        hospital("A", "EXAMPLE MEMORIAL HOSPITAL", "27710"),
        hospital("B", "UNRELATED REHABILITATION INSTITUTE", "27704"),
        hospital("C", "EXAMPLE RALEIGH HOSPITAL CAMPUS", "27699", city="RALEIGH"),
    ]
    schedule_h.match_facilities(filers, hospitals)
    links = {f["num"]: (f["cms_id"], f["match"]) for f in filers[0]["facilities"]}
    assert links["1"] == ("A", "zip+name")
    assert links["2"] == ("C", "city+name")
    assert links["3"] == (None, None)


def test_saint_tokens_do_not_link_different_organizations():
    assert schedule_h.similarity(
        "Nationwide Children's Hospital St Ann's NICU", "MOUNT CARMEL ST ANN'S"
    ) < 0.2


def test_specialty_units_do_not_inherit_host_hospital_links():
    assert schedule_h.similarity("Nationwide Children's Hospital Riverside NICU", "RIVERSIDE METHODIST HOSPITAL") == 0
    assert schedule_h.similarity("CONWAY REGIONAL REHAB HOSPITAL", "CONWAY BEHAVIORAL HEALTH") == 0
    assert schedule_h.similarity("ENCOMPASS REHABILITATION HOSPITAL OF DOTHAN", "DOTHAN REHAB HOSPITAL") > 0


def test_candidate_returns_keep_latest_990_per_ein_and_skip_foundations(tmp_path):
    index = tmp_path / "index.csv"
    index.write_text(
        "RETURN_ID,FILING_TYPE,EIN,TAX_PERIOD,SUB_DATE,TAXPAYER_NAME,RETURN_TYPE,DLN,OBJECT_ID,XML_BATCH_ID\n"
        ",EFILE,1,202312,2024,EXAMPLE HOSPITAL,990,,100,\n"
        ",EFILE,1,202412,2025,EXAMPLE HOSPITAL,990,,200,\n"
        ",EFILE,2,202412,2025,EXAMPLE HOSPITAL FOUNDATION,990,,300,\n"
        ",EFILE,3,202412,2025,EXAMPLE HOSPITAL,990T,,400,\n"
        ",EFILE,4,202412,2025,SMALL TOWN CLINIC,990,,500,\n"
    )
    found = schedule_h.candidate_returns([index], {"SMALL TOWN CLINIC"})
    assert sorted(c["object_id"] for c in found) == ["200", "500"]


def test_read_zip_member_inflates_a_deflated_member(monkeypatch):
    import io
    import zipfile

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("1_public.xml", "<x>hello</x>")
    data = buffer.getvalue()
    info = zipfile.ZipFile(io.BytesIO(data)).infolist()[0]
    member = {
        "name": info.filename,
        "offset": info.header_offset,
        "compressed": info.compress_size,
        "method": info.compress_type,
    }

    def fake_get(url, headers=None, **_):
        start, end = headers["Range"].removeprefix("bytes=").split("-")
        return data[int(start) : int(end) + 1]

    monkeypatch.setattr("not_my_debt.atlas.net.get", fake_get)
    assert read_zip_member("https://example.invalid/x.zip", member) == b"<x>hello</x>"


def record(date, state, zip_code, issue=cfpb.NOT_OWED, sub_issue="Debt was paid", **extra):
    return {
        "complaint_id": f"{date}{state}{zip_code}",
        "date_received": date,
        "state": state,
        "zip_code": zip_code,
        "issue": issue,
        "sub_issue": sub_issue,
        "company": "Collector A",
        "company_response": "Closed with explanation",
        "timely": "Yes",
        "tags": extra.get("tags"),
    }


def test_cfpb_summary_separates_rate_year_trend_and_county_windows():
    records = [
        record("2025-03-02", "NC", "27701"),
        record("2025-03-09", "NC", "277XX"),
        record("2024-11-01", "NC", "27701", sub_issue="Debt is not yours"),
        record("2025-01-15", "GA", "30301", issue="Communication tactics", sub_issue=None,
               tags="Servicemember"),
        record("2020-06-01", "GA", "30301"),
    ]
    summary = cfpb.summarize(
        records,
        months=cfpb.months_between("2024-11", "2025-03"),
        rate_year=2025,
        county_years=(2024, 2025),
        zcta_county={"27701": "37063", "30301": "13121"},
    )
    assert summary["national"]["count"] == 3
    assert summary["states"]["NC"]["count"] == 2
    assert summary["states"]["NC"]["paid"] == 2
    assert summary["states"]["NC"]["zip5"] == 1
    assert summary["states"]["NC"]["monthly"] == [1, 0, 0, 0, 2]
    assert summary["states"]["GA"]["servicemember"] == 1
    # County window covers 2024–2025; masked ZIPs stay unmapped instead of guessed.
    assert summary["counties"]["counts"] == {"37063": 2, "13121": 1}
    assert summary["counties"]["unmapped_by_state"] == {"NC": 1}
    assert summary["counties"]["total"] == 4


def test_months_between_crosses_years():
    assert cfpb.months_between("2025-11", "2026-02") == ["2025-11", "2025-12", "2026-01", "2026-02"]


def test_poisson_interval_brackets_count_and_handles_zero():
    low, high = build.poisson_ci(100)
    assert 80 < low < 100 < high < 125
    assert build.poisson_ci(0) == (0.0, 3.689)


def test_poisson_model_recovers_rate_with_only_population_differences():
    rows = [
        {"count": 10 * k, "population": 100_000 * k, "uninsured_rate": 0.05 + 0.01 * (k % 3),
         "poverty_rate": 0.1 + 0.01 * (k % 2)}
        for k in range(1, 11)
    ]
    model = build.fit_poisson(rows, ["uninsured_rate", "poverty_rate"])
    for row, expected in zip(rows, model["expected"]):
        assert expected == pytest.approx(row["count"], rel=1e-6)
    assert model["rate_ratio_per_sd"]["uninsured_rate"] == pytest.approx(1.0, abs=1e-6)


def test_tercile_assignment():
    cuts = build.tercile_cuts([1, 2, 3, 4, 5, 6])
    assert [build.tercile(v, cuts) for v in (1, 3, 6)] == [0, 1, 2]
    assert build.tercile(None, cuts) is None


def test_policy_summary_uses_linked_facilities_as_denominator():
    policies = [
        {"free_fpg": 200.0, "discount_fpg": 400.0, "ecas_permitted_before_efforts": [],
         "ecas_before_reasonable_efforts": False, "notice_on_bills": True},
        {"free_fpg": 100.0, "discount_fpg": None, "ecas_permitted_before_efforts": ["credit_reporting"],
         "ecas_before_reasonable_efforts": None, "notice_on_bills": None},
    ]
    summary = build.policy_summary(policies)
    assert summary["facilities_with_policy"] == 2
    assert summary["median_free_fpg"] == 150.0
    assert summary["median_discount_fpg"] == 400.0
    assert summary["share_credit_reporting_before_efforts"] == 0.5
    assert build.policy_summary([])["share_ecas_permitted_before_efforts"] is None


def test_acs_build_computes_rates_and_rejects_negative_sentinels(tmp_path):
    def write(name, header, rows):
        path = tmp_path / name
        path.write_text("|".join(header) + "\n" + "\n".join("|".join(r) for r in rows) + "\n")
        return path

    geo = ["0400000US37", "0500000US37063"]
    paths = {
        "b01003": write("p.psv", ["GEO_ID", "B01003_E001"], [[geo[0], "1000"], [geo[1], "100"]]),
        "b27010": write(
            "u.psv",
            ["GEO_ID", "B27010_E001", *acs.UNINSURED],
            [[geo[0], "900", "10", "20", "30", "40"], [geo[1], "90", "1", "2", "3", "-666666666"]],
        ),
        "b17001": write("pov.psv", ["GEO_ID", "B17001_E001", "B17001_E002"], [[geo[0], "950", "95"]]),
        "b19013": write("inc.psv", ["GEO_ID", "B19013_E001"], [[geo[0], "70000"]]),
        "b18101": write("dis.psv", ["GEO_ID", "B18101_E001", "B18101_E004"], [[geo[0], "900", "90"]]),
        "b25070": write(
            "rent.psv",
            ["GEO_ID", "B25070_E001", *acs.RENT_BURDEN_30, "B25070_E011"],
            [[geo[0], "110", "10", "10", "10", "10", "10"]],
        ),
        "geos": write(
            "geos.psv", ["STUSAB", "GEO_ID", "NAME"],
            [["NC", geo[0], "North Carolina"], ["NC", geo[1], "Durham County, North Carolina"]],
        ),
        "shells": tmp_path / "shells.txt",
    }
    paths["shells"].write_text(
        "Table ID|Line|Indent|Unique ID|Label\nB18101|4.0|3|B18101_004|With a disability\n"
    )
    out = acs.build(paths)
    state = out[geo[0]]
    assert state["uninsured"] == 100
    assert state["uninsured_rate"] == pytest.approx(100 / 900, abs=1e-5)
    assert state["poverty_rate"] == 0.1
    assert state["disability_rate"] == 0.1
    assert state["rent_burden_rate"] == 0.4
    county = out[geo[1]]
    assert county["uninsured"] is None and county["uninsured_rate"] is None
    assert county["poverty_rate"] is None


def test_published_atlas_keeps_case_data_out_and_links_policies():
    from pathlib import Path

    root = Path(__file__).resolve().parents[1] / "public" / "atlas"
    if not (root / "states.json").exists():
        pytest.skip("atlas artifacts not built")
    summary = json.loads((root / "states.json").read_text())
    # Complaints without a state or from military/territory codes stay in the national total.
    assert summary["national"]["count"] >= sum(s["complaints"] for s in summary["states"])
    for state in summary["states"]:
        if state["population"]:
            assert math.isclose(
                state["rate_per_100k"], state["complaints"] / state["population"] * 1e5, abs_tol=6e-4
            )
    hospitals = json.loads((root / "hospitals.json").read_text())
    filers = json.loads((root / "schedule_h.json").read_text())["filers"]
    ref = hospitals["fields"].index("policy_ref")
    for row in hospitals["rows"]:
        if row[ref]:
            filer, policy = row[ref]
            assert 0 <= policy < len(filers[filer]["policies"])
    text = (root / "states.json").read_text()
    assert "complaint_id" not in text and "narrative" not in text
