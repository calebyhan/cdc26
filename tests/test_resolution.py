import json
from datetime import date
from types import SimpleNamespace

import duckdb
import pytest

from ews.ingest.identity_sources import IdentityArchive
from ews.resolve import pipeline
from ews.resolve.matching import best, build_index, candidates, normalize


@pytest.mark.parametrize(
    "raw,expected",
    [
        (" Wélls  Fargo & Company ", "WELLS FARGO"),
        ("The Bank of America, National Association", "BANK OF AMERICA"),
        ("U S BCORP", "US"),
        ("U.S. Bank National Association", "US"),
        ("PNC FINL SVCS GRP INC", "PNC"),
        ("UNITED SERVICES AUTOMOBILE ASSN", "UNITED SERVICES AUTOMOBILE ASSOCIATION"),
        ("Nationstar Mortgage, LLC d/b/a Mr. Cooper", "NATIONSTAR MORTGAGE"),
        ("Old Mortgage LLC n/k/a New Mortgage", "OLD MORTGAGE"),
        ("Huntington National Bank, The", "HUNTINGTON NATIONAL"),
        ("Bank and Trust Company", "BANK AND TRUST"),
        ("", ""),
        ("...", ""),
    ],
)
def test_normalize(raw, expected):
    assert normalize(raw) == expected


@pytest.mark.parametrize(
    "query,wrong",
    [
        ("Experian Information Solutions Inc.", "Solutions Bank"),
        ("Navient Solutions LLC", "Solutions Bank"),
        ("Resurgent Capital Services L.P.", "Capital Bank, National Association"),
        ("ENCORE CAPITAL GROUP INC.", "Capital Bank, National Association"),
        ("NAVY FEDERAL CREDIT UNION", "Union Bank"),
        ("Fidelity National Information Services", "The Fidelity Bank"),
        ("UNITED SERVICES AUTOMOBILE ASSOCIATION", "United Bank"),
    ],
)
def test_spike_false_positives_do_not_match(query, wrong):
    assert candidates(query, build_index([wrong])) == []


def test_empty_key_and_exact_collisions():
    assert candidates("...", build_index(["..."])) == []
    assert best("", build_index([""])) == (None, 0.0)
    index = build_index(["Citizens Bank NA", "Citizens Financial Group Inc"])
    assert len(candidates("Citizens", index)) == 2
    rows = pipeline.propose(
        "ccdb",
        "Citizens",
        index,
        {
            "Citizens Bank NA": "E1",
            "Citizens Financial Group Inc": "E2",
        },
    )
    assert {r["status"] for r in rows} == {"ambiguous"}


def test_token_sort_penalizes_extra_tokens_and_blocks_first_token():
    assert candidates(
        "First National Bank of Pennsylvania",
        build_index(
            [
                "National First Bank of Pennsylvania",
                "First National Bank of Pana",
            ]
        ),
    ) == [("First National Bank of Pana", pytest.approx(87.096774), "fuzzy")]


@pytest.mark.parametrize(
    "score,status", [(85, "review"), (95, "review"), (95.01, "auto_accept")]
)
def test_review_threshold_includes_95(monkeypatch, score, status):
    monkeypatch.setattr(pipeline, "candidates", lambda *_: [("Target", score, "fuzzy")])
    assert (
        pipeline.propose("ccdb", "Query", {}, {"Target": "E1"})[0]["status"] == status
    )


def test_higher_scoring_candidate_is_only_auto_accept(monkeypatch):
    monkeypatch.setattr(
        pipeline,
        "candidates",
        lambda *_: [("A", 99, "fuzzy"), ("B", 97, "fuzzy"), ("C", 90, "fuzzy")],
    )
    assert [
        r["status"]
        for r in pipeline.propose(
            "ccdb", "Query", {}, {"A": "E1", "B": "E2", "C": "E3"}
        )
    ] == ["auto_accept", "alternative", "review"]


def review(source="ccdb", raw="Bank", eid="E1", start="", end="", decision="accept"):
    return dict(
        source=source,
        raw_string=raw,
        entity_id=eid,
        valid_from=start,
        valid_to=end,
        decision=decision,
        reviewed_by="Codex (review)",
        reviewed_on="2026-09-26",
        evidence="source",
        review_note="Inspected evidence",
    )


def entity(eid="E1", name="Bank", kind="bank", certs="1;2", hc="100", leis=""):
    return dict(
        entity_id=eid,
        display_name=name,
        type=kind,
        peer_group=kind,
        fdic_certs=certs,
        rssdhcr=hc,
        leis=leis,
        valid_from="",
        valid_to="",
        successor_entity_id="",
        reviewed_by="Codex (review)",
        reviewed_on="2026-09-26",
        evidence="source",
        review_note="review",
    )


def test_manual_override_and_merger_date_boundary():
    es = [entity(), entity("E2")]
    rows = [review(end="2022-11-30"), review(eid="E2", start="2022-12-01")]
    _, grouped = pipeline.validate_reviews(es, rows, [])
    assert (
        pipeline.resolve_reviewed("ccdb", "Bank", date(2022, 11, 30), grouped)[
            "entity_id"
        ]
        == "E1"
    )
    assert (
        pipeline.resolve_reviewed("ccdb", "Bank", date(2022, 12, 1), grouped)[
            "entity_id"
        ]
        == "E2"
    )
    rows.append(review(eid="E2", start="2020-01-01"))
    with pytest.raises(ValueError, match="Overlapping"):
        pipeline.validate_reviews(es, rows, [])
    _, grouped = pipeline.validate_reviews(es, [review(eid="", decision="reject")], [])
    assert (
        pipeline.resolve_reviewed("ccdb", "Bank", date.today(), grouped)["decision"]
        == "reject"
    )


def test_missing_provenance_and_unknown_entity_fail():
    with pytest.raises(ValueError, match="unknown entity"):
        pipeline.validate_reviews([entity()], [review(eid="E404")], [])
    row = review()
    row["reviewed_by"] = ""
    with pytest.raises(ValueError, match="provenance"):
        pipeline.validate_reviews([entity()], [row], [])


def test_bank_merger_checks_outgoing_and_surviving_cert():
    entities = {"E1": entity(certs="1"), "E2": entity("E2", certs="2")}
    links = [
        dict(
            entity_id="E1",
            successor_entity_id="E2",
            relationship="bank_merger",
            effective_date="2025-05-18",
        )
    ]
    event = dict(
        OUT_CERT=1,
        SUR_CERT=2,
        EFFDATE="2025-05-18T00:00:00",
        CHANGECODE_DESC="Merger -Without Assistance",
    )
    pipeline.validate_bank_mergers(links, entities, [event])
    event["SUR_CERT"] = 3
    with pytest.raises(ValueError, match="not verified"):
        pipeline.validate_bank_mergers(links, entities, [event])


def test_identifiers_nonbank_missing_rssd_and_multiple_charters():
    es = [
        entity(leis="LEI01"),
        entity("E2", "Nonbank", "nonbank_servicer", "", "", "LEI02"),
    ]
    hmda = [
        dict(
            lei="LEI01",
            respondent_name="Bank",
            respondent_rssd="000123",
            identifier_year="2023",
            identifier_source="panel",
        ),
        dict(
            lei="LEI02",
            respondent_name="Nonbank",
            respondent_rssd="-1",
            identifier_year="2023",
            identifier_source="panel",
        ),
    ]
    banks = [
        dict(CERT=1, NAME="Bank", FED_RSSD="000123", RSSDHCR="100"),
        dict(CERT=2, NAME="Bank 2", FED_RSSD="000456", RSSDHCR="100"),
    ]
    rows, _ = pipeline.make_crosswalk(
        es, [review(), review(raw="Nonbank", eid="E2")], hmda, banks
    )
    assert {r.get("fdic_cert") for r in rows if r["entity_id"] == "E1"} == {"1", "2"}
    nonbank = [r for r in rows if r["entity_id"] == "E2"]
    assert all(r.get("rssd", "") == "" and not r.get("fdic_cert") for r in nonbank)
    assert any(r.get("rssd") == "000123" for r in rows)
    assert all(r.get("hmda_identifier") == "LEI02" for r in nonbank)


def test_archive_integrity_and_html_rejection(tmp_path):
    archive = IdentityArchive(tmp_path)
    response = SimpleNamespace(
        content=b'{"data":[]}',
        url="https://example.test",
        headers={"Content-Type": "application/json"},
        raise_for_status=lambda: None,
        json=lambda: {},
    )
    archive.session.get = lambda *a, **kw: response
    archive.fetch("fdic/test.json", response.url)
    assert (
        IdentityArchive(tmp_path, offline=True).fetch("fdic/test.json", "unused")
        == response.content
    )
    (tmp_path / "fdic/test.json").write_text("{}")
    with pytest.raises(ValueError, match="checksum"):
        archive.fetch("fdic/test.json", "unused")
    response.headers["Content-Type"] = "text/html"
    with pytest.raises(ValueError, match="Expected JSON"):
        archive.fetch("other.json", response.url)


def test_fdic_pagination_requires_complete_stable_unique_snapshot():
    archive = IdentityArchive("unused")

    def payload(total, rows, index="snapshot"):
        return json.dumps(
            dict(
                meta=dict(total=total, index=dict(name=index)),
                data=[dict(data=r) for r in rows],
            )
        ).encode()

    calls = []
    pages = [payload(2, [dict(CERT=1)]), payload(2, [dict(CERT=2)])]

    def fetch(relative, url, params):
        calls.append(params["offset"])
        return pages.pop(0)

    archive.fetch = fetch
    assert archive.fdic("institutions") == [dict(CERT=1), dict(CERT=2)]
    assert calls == [0, 1]
    pages[:] = [payload(2, [dict(CERT=1)]), payload(2, [])]
    with pytest.raises(ValueError, match="Incomplete"):
        archive.fdic("institutions")
    pages[:] = [payload(2, [dict(CERT=1)]), payload(3, [dict(CERT=2)])]
    with pytest.raises(ValueError, match="snapshot changed"):
        archive.fdic("institutions")
    pages[:] = [payload(2, [dict(CERT=1), dict(CERT=1)])]
    with pytest.raises(ValueError, match="Duplicate"):
        archive.fdic("institutions")


def fixture_data(tmp_path):
    root = tmp_path / "data"
    (root / "reference").mkdir(parents=True)
    (root / "staging").mkdir()
    es = [entity("E1", "Nonbank", "nonbank_servicer", "", "")]
    aliases = [
        review(raw="Nonbank"),
        review(raw="Pending Company Match", eid="", decision="unresolved"),
        review("enforcement", "Nonbank"),
    ]
    pipeline.write_csv(root / "reference/entity_manual.csv", es, list(es[0]))
    pipeline.write_csv(root / "reference/alias_manual.csv", aliases, list(aliases[0]))
    pipeline.write_csv(
        root / "reference/entity_relationships.csv",
        [],
        [
            "entity_id",
            "successor_entity_id",
            "relationship",
            "effective_date",
            "evidence",
            "reviewed_by",
            "reviewed_on",
        ],
    )
    con = duckdb.connect()
    con.sql(
        "SELECT i complaint_id, DATE '2020-01-01' date_received, CASE WHEN i<96 THEN 'Nonbank' ELSE 'Pending Company Match' END company FROM range(100) t(i)"
    ).write_parquet(str(root / "staging/stg_complaints.parquet"))
    con.sql(
        "SELECT 'action' action_id, 1 party_index, 'Nonbank' party_raw, DATE '2020-01-01' date_filed, true mortgage_related, true is_company"
    ).write_parquet(str(root / "staging/stg_enforcement.parquet"))
    con.close()
    return root


def test_build_enforces_gates_and_deterministic_publication(tmp_path, monkeypatch):
    root = fixture_data(tmp_path)
    monkeypatch.setattr(pipeline, "load_sources", lambda *_: ([], [], []))
    report = pipeline.build(root, offline=True)
    assert report["reviewed_complaint_coverage"] == 0.96
    assert report["mortgage_company_party_coverage"] == 1
    assert report["independent_human_coverage"] == 0
    crosswalk = (root / "marts/crosswalk.csv").read_bytes()
    pipeline.build(root, offline=True)
    assert crosswalk == (root / "marts/crosswalk.csv").read_bytes()
    con = duckdb.connect()
    assert (
        con.read_parquet(str(root / "marts/complaint_entity.parquet"))
        .filter("entity_id IS NOT NULL")
        .count("*")
        .fetchone()[0]
        == 96
    )
    assert (
        dict(
            con.sql(f"DESCRIBE SELECT * FROM '{root}/marts/alias.parquet'")
            .project("column_name,column_type")
            .fetchall()
        )["valid_from"]
        == "DATE"
    )
    con.close()
    with pytest.raises(ValueError, match="human review gate"):
        pipeline.build(root, offline=True, require_human=True)
    assert crosswalk == (root / "marts/crosswalk.csv").read_bytes()
    aliases = pipeline.read_csv(root / "reference/alias_manual.csv")
    aliases[0]["decision"] = "unresolved"
    aliases[0]["entity_id"] = ""
    pipeline.write_csv(root / "reference/alias_manual.csv", aliases, list(aliases[0]))
    with pytest.raises(ValueError, match="below 94"):
        pipeline.build(root, offline=True)
    assert crosswalk == (root / "marts/crosswalk.csv").read_bytes()


def test_missing_enforcement_identity_never_publishes(tmp_path, monkeypatch):
    root = fixture_data(tmp_path)
    monkeypatch.setattr(pipeline, "load_sources", lambda *_: ([], [], []))
    aliases = pipeline.read_csv(root / "reference/alias_manual.csv")[:2]
    pipeline.write_csv(root / "reference/alias_manual.csv", aliases, list(aliases[0]))
    with pytest.raises(ValueError, match="Unmapped mortgage enforcement"):
        pipeline.build(root, offline=True)
    assert not (root / "marts/crosswalk.csv").exists()


def test_shared_lei_routes_to_predecessor_and_successor_by_vintage():
    old = entity("OLD", "Old Bank", certs="", leis="SHARED")
    new = entity("NEW", "New Bank", certs="", leis="SHARED")
    old["valid_to"] = "2022-11-30"
    links = [
        dict(
            entity_id="OLD",
            lei="SHARED",
            valid_from="",
            valid_to="2022-11-30",
            reviewed_by="Codex",
            reviewed_on="2026-09-26",
            evidence="panel",
            review_note="inspected",
        ),
        dict(
            entity_id="NEW",
            lei="SHARED",
            valid_from="2022-12-01",
            valid_to="",
            reviewed_by="Codex",
            reviewed_on="2026-09-26",
            evidence="panel",
            review_note="inspected",
        ),
    ]
    pipeline.validate_lei_reviews([old, new], links)
    hmda = [
        dict(
            lei="SHARED",
            respondent_name="Charter",
            respondent_rssd="123",
            identifier_year=str(y),
            identifier_source="panel",
        )
        for y in [2021, 2023]
    ]
    rows, _ = pipeline.make_crosswalk([old, new], [], hmda, [], links)
    assert {(r["entity_id"], r["identifier_year"]) for r in rows} == {
        ("OLD", "2021"),
        ("NEW", "2023"),
    }
    links[1]["valid_from"] = "2020-01-01"
    with pytest.raises(ValueError, match="Overlapping entity/LEI"):
        pipeline.validate_lei_reviews([old, new], links)


def test_nonbank_bank_identifiers_are_rejected_before_publication(
    tmp_path, monkeypatch
):
    root = fixture_data(tmp_path)
    es = pipeline.read_csv(root / "reference/entity_manual.csv")
    es[0]["fdic_certs"] = "1"
    pipeline.write_csv(root / "reference/entity_manual.csv", es, list(es[0]))
    monkeypatch.setattr(pipeline, "load_sources", lambda *_: ([dict(CERT=1)], [], []))
    with pytest.raises(ValueError, match="bank identifiers attached to nonbank"):
        pipeline.build(root, offline=True)
    assert not (root / "marts/crosswalk.csv").exists()
