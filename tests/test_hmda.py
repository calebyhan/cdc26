from ews.ingest.hmda import profile_panel


def test_legacy_panel_has_no_header():
    result = profile_panel("2017,000123,9\n2017,000456,1\n", 2017)
    assert result["rows"] == 2
    assert result["fields"] == []
    assert result["headerless"] is True


def test_panel_missing_rssd_is_not_an_identifier():
    result = profile_panel(
        "respondent_name,other_lender_code,respondent_rssd\nRocket Mortgage,3,123\nOther,3,-1\n",
        2023,
    )
    assert result["rssd_by_other_lender_code"]["3"] == {"rows": 2, "with_rssd": 1}
