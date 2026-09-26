from not_my_debt.domain import CaseResult, Document, Fact, Finding
from not_my_debt.packet import draft_letter, render_packet


def test_packet_escapes_document_and_letter_injection():
    doc = Document(
        "x",
        "bill",
        "<script>bad</script>",
        "",
        fields={"provider": Fact("<img onerror=evil>", "<script>evil</script>", confirmed=True)},
    )
    result = CaseResult(
        findings=[Finding("test", "<script>title</script>", "<script>detail</script>")]
    )
    html = render_packet([doc], result, letter_override="<script>letter</script>")
    assert "<script>" not in html
    assert "&lt;script&gt;" in html


def test_packet_keeps_unconfirmed_and_excluded_facts_out():
    docs = [
        Document(
            "x", "bill", "Bill", "", fields={"provider": Fact("UNREVIEWED", "", confirmed=False)}
        ),
        Document(
            "y",
            "receipt",
            "Excluded",
            "",
            included=False,
            fields={"payment_amount": Fact("999", "", confirmed=True)},
        ),
    ]
    html = render_packet(docs, CaseResult())
    assert "UNREVIEWED" not in html
    assert "999" not in html


def test_collector_and_provider_actions_are_distinct():
    assert "dispute" in draft_letter([], CaseResult(), "collector")
    assert "billing ledger" in draft_letter([], CaseResult(), "provider")
    assert "must respond within 30" not in draft_letter([], CaseResult(), "collector")


def test_letter_cites_records_by_title_not_internal_ref():
    docs = [
        Document(
            "receipt",
            "receipt",
            "Provider payment receipt",
            "",
            fields={"statement_date": Fact("2026-07-20", "", confirmed=True)},
        ),
        Document("bill", "bill", "Provider bill", ""),
    ]
    finding = Finding(
        "possible_uncredited_payment",
        "t",
        "Payment may not be credited.",
        refs=["receipt.payment_amount", "receipt.payment_date", "bill.balance"],
    )
    letter = draft_letter(docs, CaseResult(findings=[finding]))
    assert "receipt.payment_amount" not in letter
    assert "(Supporting records: Provider payment receipt, 2026-07-20; Provider bill)" in letter
