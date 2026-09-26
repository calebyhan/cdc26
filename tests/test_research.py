"""Research checks focus on denominators, exclusions, and source integrity."""

import csv
import io
import zipfile

import pytest

from not_my_debt.research import NOT_OWED, summarize_api, summarize_archive


def test_archive_counts_missing_text_and_deduplicates_before_mentions(tmp_path):
    fields = [
        "Date received",
        "Product",
        "Sub-product",
        "Issue",
        "Sub-issue",
        "Consumer complaint narrative",
        "Complaint ID",
    ]
    base = {
        "Date received": "2025-01-12",
        "Product": "Debt collection",
        "Sub-product": "Medical debt",
        "Issue": NOT_OWED,
        "Sub-issue": "Debt was paid",
    }
    rows = [
        {
            **base,
            "Complaint ID": "1",
            "Consumer complaint narrative": "I already paid in full. I have a receipt and an EOB.",
        },
        {
            **base,
            "Complaint ID": "2",
            "Consumer complaint narrative": " I ALREADY paid in full.  I have a receipt and an EOB. ",
        },
        {**base, "Complaint ID": "3", "Consumer complaint narrative": ""},
        {
            **base,
            "Complaint ID": "4",
            "Consumer complaint narrative": "Please provide verification of the bill.",
        },
        {
            **base,
            "Complaint ID": "5",
            "Sub-product": "Credit card debt",
            "Consumer complaint narrative": "I already paid.",
        },
        {
            **base,
            "Complaint ID": "6",
            "Product": "Mortgage",
            "Consumer complaint narrative": "I already paid.",
        },
    ]
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=fields)
    writer.writeheader()
    writer.writerows(rows)
    source = tmp_path / "fixture.zip"
    with zipfile.ZipFile(source, "w") as archive:
        archive.writestr("fixture.csv", buffer.getvalue())
    result = summarize_archive(source, tmp_path / "extracted.jsonl", verify_checksum=False)
    assert result["archive_total_rows"] == 6
    assert result["medical_total"] == 4
    assert result["medical_with_narrative"] == 3
    assert result["medical_without_narrative"] == 1
    assert result["unique_narratives"] == 2
    assert result["duplicate_narratives"] == 1
    assert result["narrative_coverage_pct"] == 75
    counts = {p["id"]: p["count"] for p in result["document_mentions"]}
    assert counts["eob"] == 1
    assert counts["receipt"] == 1
    assert counts["bill"] == 1
    assert result["examples"] == []
    assert len((tmp_path / "extracted.jsonl").read_text().splitlines()) == 2
    with pytest.raises(ValueError, match="checksum"):
        summarize_archive(source)


def test_api_rejects_silently_ignored_subproduct_filter():
    # This was the real failure mode of sub_product=Medical+debt.
    data = {
        "hits": {
            "hits": [{"_source": {"product": "Debt collection", "sub_product": "I do not know"}}]
        }
    }
    with pytest.raises(ValueError, match="medical-debt filter"):
        summarize_api(data)


def test_committed_research_denominators_are_consistent():
    import json
    from pathlib import Path

    data = json.loads(
        (Path(__file__).resolve().parents[1] / "data/research/research.json").read_text()
    )
    api, archive = data["api"], data["archive"]
    assert sum(x["count"] for x in api["issue_counts"]) == api["total_complaints"]
    assert sum(x["count"] for x in api["not_owed_subissues"]) == api["not_owed_count"]
    assert (
        archive["medical_total"]
        == archive["medical_with_narrative"] + archive["medical_without_narrative"]
    )
    assert (
        archive["medical_with_narrative"]
        == archive["unique_narratives"] + archive["duplicate_narratives"]
    )
    assert all(
        x["count"] <= archive["unique_narratives"]
        for x in archive["patterns"] + archive["document_mentions"]
    )
    assert api["narratives_present_in_sample"] == 0


def _response_payload(total, sub_issue, responses):
    return {
        "hits": {
            "total": {"value": total},
            "hits": [
                {
                    "_source": {
                        "product": "Debt collection",
                        "sub_product": "Medical debt",
                        "sub_issue": sub_issue,
                    }
                }
            ],
        },
        "aggregations": {
            "company_response": {
                "company_response": {
                    "buckets": [{"key": k, "doc_count": v} for k, v in responses.items()]
                }
            }
        },
    }


def test_response_outcomes_verify_paid_filter_and_totals():
    from not_my_debt.research import summarize_response_outcomes

    everything = _response_payload(10, "Debt is not yours", {"Closed with explanation": 10})
    paid = _response_payload(
        4, "Debt was paid", {"Closed with explanation": 3, "Closed with monetary relief": 1}
    )
    outcome = summarize_response_outcomes(everything, paid)
    assert [g["total"] for g in outcome["groups"]] == [10, 4]
    assert outcome["groups"][1]["responses"][1] == {
        "label": "Closed with monetary relief",
        "count": 1,
    }
    wrong = _response_payload(4, "Debt is not yours", {"Closed with explanation": 4})
    with pytest.raises(ValueError, match="Debt was paid"):
        summarize_response_outcomes(everything, wrong)
    partial = _response_payload(4, "Debt was paid", {"Closed with explanation": 3})
    with pytest.raises(ValueError, match="sum"):
        summarize_response_outcomes(everything, partial)


def test_committed_response_outcomes_match_annual_counts():
    import json
    from pathlib import Path

    data = json.loads(
        (Path(__file__).resolve().parents[1] / "data/research/research.json").read_text()
    )
    api = data["api"]
    everything, paid = api["response_outcomes"]["groups"]
    paid_count = next(
        x["count"] for x in api["not_owed_subissues"] if x["label"] == "Debt was paid"
    )
    assert everything["total"] == api["total_complaints"]
    assert paid["total"] == paid_count
    for group in (everything, paid):
        assert sum(x["count"] for x in group["responses"]) == group["total"]
