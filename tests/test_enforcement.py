import csv
import hashlib
import json
from types import SimpleNamespace

import duckdb
import pytest
from bs4 import BeautifulSoup

from ews.ingest.enforcement import Archive, parse_detail, scrape_listing
from ews.ingest.enforcement_labels import build, party_caption, summary_hash, validate
from ews.resolve.parties import split_parties


def listing(total, slugs):
    cards = "".join(
        f'<article class="o-post-preview"><div class="o-post-preview__title">'
        f'<a href="/enforcement/actions/{s}/">{s}</a></div>'
        '<time datetime="2024-01-01"></time></article>'
        for s in slugs
    )
    return BeautifulSoup(f"<main>{total} filtered results{cards}</main>", "html.parser")


class Pages:
    def __init__(self, pages):
        self.pages, self.calls = pages, []

    def fetch(self, url, relative, **params):
        self.calls.append(params["page"])
        return self.pages[params["page"] - 1]


def test_pagination_deduplicates_and_crosschecks():
    pages = Pages([listing(3, ["a", "b"]), listing(3, ["b", "c"])])
    assert [r["slug"] for r in scrape_listing(pages, 3)] == ["a", "b", "c"]
    assert pages.calls == [1, 2]


def test_repeated_page_stops_instead_of_looping_or_publishing_partial():
    pages = Pages([listing(3, ["a", "b"]), listing(3, ["a", "b"])])
    with pytest.raises(ValueError, match="2 unique actions vs 3 advertised"):
        scrape_listing(pages, 3)
    assert pages.calls == [1, 2]


def test_listing_count_drift_and_changed_snapshot_fail():
    with pytest.raises(ValueError, match="expected snapshot 386"):
        scrape_listing(Pages([listing(387, ["a"])]))
    with pytest.raises(ValueError, match="changed during pagination"):
        scrape_listing(Pages([listing(3, ["a"]), listing(4, ["b"])]), 3)


def test_archive_records_bytes_provenance_and_detects_tampering(tmp_path):
    body = b"<main>Original HTML</main>"
    archive = Archive(tmp_path, interval=0)
    response = SimpleNamespace(
        content=body,
        url="https://example.test/actions/?page=1",
        status_code=200,
        headers={"Content-Type": "text/html; charset=utf-8"},
        raise_for_status=lambda: None,
    )
    archive.session.get = lambda *a, **kw: response
    archive.fetch("https://example.test/actions/", "listing/page-001.html", page=1)
    html = tmp_path / "listing/page-001.html"
    metadata = json.loads(html.with_suffix(".json").read_text())
    assert html.read_bytes() == body
    assert metadata["sha256"] == hashlib.sha256(body).hexdigest()
    assert metadata["retrieved_at"] and metadata["url"].endswith("?page=1")
    offline = Archive(tmp_path, offline=True)
    assert (
        offline.fetch("unused", "listing/page-001.html").find("main").text
        == "Original HTML"
    )
    html.write_bytes(b"<main>Modified</main>")
    with pytest.raises(ValueError, match="checksum mismatch"):
        offline.fetch("unused", "listing/page-001.html")
    with pytest.raises(FileNotFoundError, match="Missing archived page"):
        offline.fetch("unused", "missing.html")


def test_summary_excludes_documents_related_news_and_metadata():
    soup = BeautifulSoup(
        """<main><h1>Example, Inc.</h1>
        <div class="m-full-width-text"><p>Mortgage servicing allegations.</p>
        <h2>Related documents</h2><a href="/order.pdf">Order</a></div>
        <aside><div class="m-related-metadata__item-container"><h3>Products</h3>
        <span class="a-tag-topic__text">Mortgage Servicing</span></div>
        <div class="m-related-metadata__item-container"><h3>Initial filing date</h3>
        <time datetime="2024-01-02">January 2, 2024</time></div>
        <div class="m-related-metadata__item-container"><h3>Status</h3>Post Order/Post Judgment</div>
        <div class="m-related-metadata__item-container"><h3>Forum</h3>Civil Action</div>
        <p>Unrelated news about credit cards</p></aside></main>""",
        "html.parser",
    )
    detail = parse_detail(soup, "https://example.test/action/")
    assert detail["summary"] == "Mortgage servicing allegations."
    assert detail["products"] == ["Mortgage Servicing"]
    assert detail["document_links"] == ["https://example.test/order.pdf"]
    assert detail["initial_filing_date"] == "2024-01-02"


@pytest.mark.parametrize(
    ("caption", "expected"),
    [
        (
            "Alpha, Inc.; Beta LLC; and Jane Doe",
            ["Alpha, Inc.", "Beta LLC", "Jane Doe"],
        ),
        ("Alpha, Inc., and Beta LLC", ["Alpha, Inc.", "Beta LLC"]),
        ("Alpha LLC, Beta LLC, and Jane Doe", ["Alpha LLC", "Beta LLC", "Jane Doe"]),
        (
            "State Street Bank and Trust Company",
            ["State Street Bank and Trust Company"],
        ),
        (
            "Alpha LLC (d/b/a One; Two, and Three); Beta LLC",
            ["Alpha LLC (d/b/a One; Two, and Three)", "Beta LLC"],
        ),
        (
            "Alpha, Inc., d/b/a Brand; Jane Doe, Jr.",
            ["Alpha, Inc., d/b/a Brand", "Jane Doe, Jr."],
        ),
    ],
)
def test_caption_separators_preserve_aliases_and_suffixes(caption, expected):
    assert split_parties(caption) == expected


def write_csv(path, rows):
    with path.open("w", newline="") as target:
        writer = csv.DictWriter(target, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


@pytest.fixture
def reviewed(tmp_path):
    actions = [
        dict(
            action_id="a",
            name="Alpha LLC; Jane Doe",
            name_h1="Alpha LLC",
            date_filed="2024-12-31",
            initial_filing_date="2024-12-31",
            products=["Payments"],
            summary="Unauthorized mortgage withdrawals.",
            status="Expired/Terminated/Dismissed",
        ),
        dict(
            action_id="b",
            name="Beta LLC",
            name_h1="Beta LLC",
            date_filed="2025-01-01",
            initial_filing_date="2025-01-01",
            products=["Mortgage Servicing"],
            summary="Mortgage servicing allegations.",
            status="Post Order/Post Judgment",
        ),
    ]
    reference = tmp_path / "reference"
    reference.mkdir()
    write_csv(
        reference / "enforcement_labels.csv",
        [
            dict(
                action_id=a["action_id"],
                date_filed=a["date_filed"],
                products_json=json.dumps(sorted(a["products"])),
                mortgage_related="true",
                rationale="Reviewed summary explicitly concerns mortgages.",
                summary_sha256=summary_hash(a),
                reviewed_by="Test reviewer",
                reviewed_on="2026-09-26",
            )
            for a in actions
        ],
    )
    write_csv(
        reference / "enforcement_parties.csv",
        [
            dict(
                action_id=a["action_id"],
                party_index=i,
                party_raw=name,
                party_type=kind,
                caption_sha256=hashlib.sha256(party_caption(a).encode()).hexdigest(),
                reviewed_by="Test reviewer",
                reviewed_on="2026-09-26",
            )
            for a, i, name, kind in [
                (actions[0], 1, "Alpha LLC", "company"),
                (actions[0], 2, "Jane Doe", "individual"),
                (actions[1], 1, "Beta LLC", "company"),
            ]
        ],
    )
    write_csv(
        reference / "enforcement_product_crosswalk.csv",
        [
            dict(
                enforcement_product=p,
                ccdb_products_json='["Mortgage"]',
                mapping_type="contextual",
                note="Read summary.",
            )
            for p in ["Payments", "Mortgage Servicing"]
        ],
    )
    return actions, reference


def test_typed_staging_distinct_counts_and_repeatable_build(reviewed, tmp_path):
    actions, reference = reviewed
    first = build(actions, tmp_path, reference)
    assert first == build(actions, tmp_path, reference)
    assert first["all_actions"] == 2 and first["party_rows"] == 3
    assert first["primary"]["mortgage_actions"] == 1
    assert first["secondary"]["mortgage_actions"] == 2
    with duckdb.connect(str(tmp_path / "staging/ews.duckdb")) as con:
        assert con.execute("select count(*) from enforcement_events").fetchone() == (2,)
        assert con.execute(
            "select count(*) from stg_enforcement where is_company"
        ).fetchone() == (2,)
        assert con.execute(
            "select typeof(date_filed), typeof(mortgage_related) from enforcement_events limit 1"
        ).fetchone() == ("DATE", "BOOLEAN")


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("summary", "New allegations.", "Summary changed"),
        ("name", "Different Company LLC", "Caption changed"),
        ("date_filed", "2024-12-30", "Date/products changed"),
        ("products", ["Deposits"], "Unmapped enforcement products"),
    ],
)
def test_changed_sources_require_review_before_replacing_staging(
    reviewed, tmp_path, field, value, message
):
    actions, reference = reviewed
    build(actions, tmp_path, reference)
    target = tmp_path / "staging/enforcement_events.parquet"
    before = target.read_bytes()
    actions[0][field] = value
    with pytest.raises(ValueError, match=message):
        build(actions, tmp_path, reference)
    assert target.read_bytes() == before


def test_missing_action_label_fails_instead_of_defaulting_false(reviewed):
    actions, reference = reviewed
    with pytest.raises(ValueError, match="exactly one reviewed action label"):
        validate(actions[:1], reference)
