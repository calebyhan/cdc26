"""Next.js boundary regressions on synthetic records."""

from copy import deepcopy
from dataclasses import asdict

import pytest
from pydantic import ValidationError

from not_my_debt.examples import example_documents
from not_my_debt.web_bridge import handle_request


def case(scenario="paid"):
    return [asdict(doc) for doc in example_documents(scenario)]


def test_live_receipt_removal_changes_result_and_draft():
    documents = case()
    response = handle_request({"operation": "reconcile", "documents": documents})
    assert response["result"]["supported_balance_cents"] == 0
    assert "Provider payment receipt, 2026-07-20" in response["drafts"]["provider"]
    documents[2]["included"] = False
    missing = handle_request({"operation": "reconcile", "documents": documents})
    assert "possible_uncredited_payment" not in {f["code"] for f in missing["result"]["findings"]}
    assert "Provider payment receipt, 2026-07-20" not in missing["drafts"]["provider"]


@pytest.mark.parametrize("scenario", ["wrong_account", "duplicate_receipt", "partial_payment"])
def test_bridge_uses_existing_matching_and_deduplication(scenario):
    response = handle_request({"operation": "reconcile", "documents": case(scenario)})
    result = response["result"]
    assert (
        result["applied_payments_cents"]
        == {"wrong_account": 0, "duplicate_receipt": 15000, "partial_payment": 5000}[scenario]
    )


def test_local_extraction_stays_unconfirmed_and_retains_source():
    response = handle_request(
        {
            "operation": "extract",
            "text": "Account reference: MG-1042\nBalance: 150.00",
            "kind": "bill",
            "title": "Fictional bill",
            "method": "local",
        }
    )
    fact = response["document"]["fields"]["balance"]
    assert fact["confirmed"] is False
    assert fact["quote"] == "Balance: 150.00"


def test_packet_requires_confirmation_and_review():
    request = {"operation": "packet", "documents": case(), "letter": "Reviewed draft"}
    with pytest.raises(ValueError, match="Review the draft"):
        handle_request(request)
    request["reviewed"] = True
    request["documents"][0]["fields"]["account"]["confirmed"] = False
    with pytest.raises(ValueError, match="Review all"):
        handle_request(request)


def test_packet_escapes_user_text_and_keeps_original_quotes():
    documents = case()
    documents[2]["fields"]["payment_amount"].update(value="50.00", origin="user")
    response = handle_request(
        {
            "operation": "packet",
            "documents": documents,
            "reviewed": True,
            "letter": "<script>alert('fictional')</script>",
            "recipient": "provider",
        }
    )
    assert "<script>" not in response["html"]
    assert "Receipt payment: 150.00" in response["html"]
    assert "User-corrected value" in response["html"]


def test_bridge_rejects_duplicate_ids_and_string_confirmation_flags():
    documents = case()
    duplicate = deepcopy(documents[0])
    with pytest.raises(ValueError, match="distinct identifier"):
        handle_request({"operation": "reconcile", "documents": [*documents, duplicate]})
    documents[0]["fields"]["account"]["confirmed"] = "false"
    with pytest.raises(ValidationError):
        handle_request({"operation": "reconcile", "documents": documents})
