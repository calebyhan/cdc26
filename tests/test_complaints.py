import csv
from datetime import date

import duckdb
import pytest

from ews.ingest import ccdb
from ews.ingest.complaints import HEADERS, delta, ingest


def row(id=1, **overrides):
    return {
        **dict.fromkeys(HEADERS.values(), ""),
        "complaint_id": str(id),
        "date_received": "2025-01-01",
        "date_sent_to_company": "2025-01-02",
        "company": "Example",
        "product": "Mortgage",
        "zip_code": "001XX",
        "issue": "Loan modification,collection,foreclosure",
        "company_response": "In progress",
        **overrides,
    }


def prepare(tmp_path):
    path = tmp_path / "complaints.csv"
    with path.open("w") as output:
        writer = csv.DictWriter(output, fieldnames=HEADERS)
        writer.writeheader()
        for item in [
            row(),
            row(2, product="Credit card"),
            row(3, date_received="2024-01-01"),
        ]:
            writer.writerow({header: item[key] for header, key in HEADERS.items()})
    ingest(path, tmp_path)
    return tmp_path


def records(data):
    with duckdb.connect(str(data / "staging/ews.duckdb"), read_only=True) as db:
        return db.execute(
            "SELECT * FROM stg_complaints ORDER BY complaint_id"
        ).fetchall()


def test_bulk_and_idempotent_update(tmp_path):
    data = prepare(tmp_path)
    assert len(records(data)) == 2
    with duckdb.connect(str(data / "staging/ews.duckdb")) as db:
        assert db.execute(
            "SELECT zip_code, severity_tier, response_metrics_eligible FROM stg_complaints LIMIT 1"
        ).fetchone() == ("001XX", 3, False)
    filters = []

    def api(**kwargs):
        filters.append(kwargs)
        yield row(company_response="Closed with relief")
        yield row(
            4,
            date_received="2025-02-01T12:00:00.000Z",
            company_response="Closed without relief",
        )

    first = delta(data, today=date(2025, 2, 3), iterator=api)
    assert first["changed"] == 2
    assert filters[0]["date_received_min"] == "2024-12-03"  # catches missed days
    before = records(data)
    second = delta(
        data,
        today=date(2025, 2, 3),
        iterator=lambda **kw: iter(
            [
                row(
                    4,
                    date_received="2025-02-01T12:00:00.000Z",
                    company_response="Closed without relief",
                )
            ]
        ),
    )
    assert second["changed"] == 0
    assert records(data) == before
    assert len(before) == 3  # existing history preserved; no duplicate ID


@pytest.mark.parametrize("bad", ["unknown", "duplicate", "network", "product"])
def test_failed_delta_preserves_staging(tmp_path, bad):
    data = prepare(tmp_path)
    before = records(data)

    def api(**kwargs):
        yield row()
        if bad == "network":
            raise RuntimeError("connection lost on next page")
        yield (
            row(5, issue="new taxonomy")
            if bad == "unknown"
            else row(
                1 if bad == "duplicate" else 5,
                product="Card" if bad == "product" else "Mortgage",
            )
        )

    with pytest.raises((ValueError, RuntimeError)):
        delta(data, today=date(2025, 1, 10), iterator=api)
    assert records(data) == before


def test_empty_delta(tmp_path):
    data = prepare(tmp_path)
    before = records(data)
    assert (
        delta(data, today=date(2025, 1, 10), iterator=lambda **kw: iter(()))["changed"]
        == 0
    )
    assert records(data) == before


def test_search_after(monkeypatch):
    calls = []

    def search(**params):
        calls.append(params)
        n = len(calls)
        return {
            "hits": {
                "hits": (
                    [{"_source": {"complaint_id": n}, "sort": [123, n]}]
                    if n <= 2
                    else []
                )
            }
        }

    monkeypatch.setattr(ccdb, "search", search)
    assert list(ccdb.iter_all(page_size=1)) == [
        {"complaint_id": 1},
        {"complaint_id": 2},
    ]
    assert calls[1]["search_after"] == "123_1"
    assert calls[2]["search_after"] == "123_2"
    monkeypatch.setattr(
        ccdb,
        "search",
        lambda **kw: {"hits": {"hits": [{"_source": {}, "sort": [1, 2]}]}},
    )
    with pytest.raises(RuntimeError, match="repeated"):
        list(ccdb.iter_all())


def test_html_200_rejected(monkeypatch):
    class Response:
        headers = {"content-type": "text/html"}
        url = "https://example.test/removed"

        def raise_for_status(self):
            pass

        def json(self):
            pytest.fail("HTML must be rejected before JSON decoding")

    monkeypatch.setattr(ccdb.requests, "get", lambda *args, **kw: Response())
    with pytest.raises(RuntimeError, match="Non-JSON"):
        ccdb.search()


def test_missing_response_and_optional_date(tmp_path):
    data = prepare(tmp_path)
    delta(
        data,
        today=date(2025, 1, 10),
        iterator=lambda **kw: iter(
            [row(5, company_response=None, date_sent_to_company="")]
        ),
    )
    with duckdb.connect(str(data / "staging/ews.duckdb")) as db:
        assert db.execute(
            "SELECT response_std, response_severity_tier, response_metrics_eligible, date_sent_to_company FROM stg_complaints WHERE complaint_id=5"
        ).fetchone() == ("unknown", None, False, None)
