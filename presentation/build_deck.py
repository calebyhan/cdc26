"""Build presentation/index.html from deck.template.html and committed data.

Slide figures come from the CFPB research and atlas snapshots, the synthetic
benchmark summary, and the evidence engine's output for Maya's fictional case.
Two app captures are embedded for the community-map beats. Rebuild after
refreshing any of them:

    uv run python presentation/build_deck.py
"""

import base64
import json
import math
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from not_my_debt.benchmark import FAMILIES  # noqa: E402
from not_my_debt.examples import example_documents  # noqa: E402
from not_my_debt.extract import extract_document  # noqa: E402
from not_my_debt.reconcile import reconcile  # noqa: E402

TEMPLATE = Path(__file__).with_name("deck.template.html")
OUTPUT = Path(__file__).with_name("index.html")
PLACEHOLDER = "/*DATA*/null"
FAILURE_TEXT = "Billed By: Maple Grove Medical\nAccount: MG-1042\nBalance: 150.00"
SHORT_PATTERNS = {
    "paid_language": "Already paid",
    "insurance_language": "Insurance / coverage",
    "identity_language": "Not mine / identity",
    "verification_language": "Verification / proof",
    "amount_language": "Wrong amount",
}
SHORT_DOCUMENTS = {"eob": "EOB", "bill": "Bill", "receipt": "Receipt", "collection_notice": "Notice"}


ATLAS = ROOT / "public/atlas"
DEMO_HOSPITAL = "110018"  # Piedmont Newton Hospital, Covington GA (CMS ID)
# Recorded September 27, 2026 from the app's guide (Gemini tool calls; see docs/HANDOFF.md).
GUIDE_EXCHANGE = {
    "question": "Show me Georgia and tell me the complaint rate there.",
    "tools": ["get_state_profile", "open_state"],
    "answer": [
        "I have opened Georgia on the community map for you.",
        "There are 7.18 medical debt collection complaints per 100,000 residents. "
        "This is 2.72 times the national average of 2.64.",
        "Even after adjusting for the state's uninsured and poverty rates, Georgia's "
        "complaint rate is nearly double (1.99 times) what would be expected.",
    ],
}


def _albers(lon: float, lat: float) -> tuple[float, float]:
    """d3.geoAlbersUsa lower-48 projection at scale 1300, matching us-atlas Albers files."""
    p0, p1 = math.radians(29.5), math.radians(45.5)
    n = (math.sin(p0) + math.sin(p1)) / 2
    c = 1 + math.sin(p0) * (2 * n - math.sin(p0))
    r0 = math.sqrt(c) / n

    def raw(lam: float, phi: float) -> tuple[float, float]:
        r = math.sqrt(c - 2 * n * math.sin(phi)) / n
        return r * math.sin(lam * n), r0 - r * math.cos(lam * n)

    cx, cy = raw(math.radians(-0.6), math.radians(38.7))
    px, py = raw(math.radians(lon + 96), math.radians(lat))
    return round(487.5 + 1300 * (px - cx), 1), round(305 - 1300 * (py - cy), 1)


def _state_paths() -> dict:
    """Decode the pre-projected us-atlas TopoJSON into SVG path strings and boxes."""
    topo = json.loads((ATLAS / "states-albers-10m.json").read_text(encoding="utf-8"))
    sx, sy = topo["transform"]["scale"]
    tx, ty = topo["transform"]["translate"]
    arcs = []
    for arc in topo["arcs"]:
        x = y = 0
        points = []
        for dx, dy in arc:
            x, y = x + dx, y + dy
            points.append((round(x * sx + tx, 1), round(y * sy + ty, 1)))
        arcs.append(points)

    def ring(indices):
        out = []
        for i in indices:
            points = arcs[i] if i >= 0 else arcs[~i][::-1]
            out.extend(points if not out else points[1:])
        return out

    shapes = {}
    for geometry in topo["objects"]["states"]["geometries"]:
        polygons = geometry["arcs"] if geometry["type"] == "MultiPolygon" else [geometry["arcs"]]
        rings = [ring(r) for polygon in polygons for r in polygon]
        xs = [x for r in rings for x, _ in r]
        ys = [y for r in rings for _, y in r]
        shapes[geometry["id"]] = {
            "d": "".join("M" + "L".join(f"{x},{y}" for x, y in r) + "Z" for r in rings),
            "box": [min(xs), min(ys), max(xs), max(ys)],
        }
    return shapes


def atlas_data() -> dict:
    summary = json.loads((ATLAS / "states.json").read_text(encoding="utf-8"))
    manifest = json.loads((ATLAS / "manifest.json").read_text(encoding="utf-8"))
    hospitals = json.loads((ATLAS / "hospitals.json").read_text(encoding="utf-8"))
    filers = json.loads((ATLAS / "schedule_h.json").read_text(encoding="utf-8"))["filers"]
    prices = json.loads((ATLAS / "prices.json").read_text(encoding="utf-8"))
    shapes = _state_paths()
    modeled = [s for s in summary["states"] if s["bivariate"]]
    rates = [s["rate_per_100k"] for s in modeled]
    states = [
        {
            "abbr": s["state_abbr"],
            "name": s["name"],
            "d": shapes[s["fips"]]["d"],
            "box": shapes[s["fips"]]["box"],
            "rate": s["rate_per_100k"],
            "adjusted": s.get("adjusted_ratio"),
            "uninsured": s["uninsured_rate"],
            "poverty": s["poverty_rate"],
            "population": s["population"],
            "complaints": s["complaints"],
            "modeled": bool(s["bivariate"]),
        }
        for s in summary["states"]
        if s["fips"] in shapes
    ]
    fields = hospitals["fields"]
    rows = [dict(zip(fields, r)) for r in hospitals["rows"]]
    ga = [
        {
            "xy": _albers(h["lon"], h["lat"]),
            "own": h["ownership_class"],
            "linked": bool(h["policy_ref"]),
            "id": h["id"],
        }
        for h in rows
        if h["state"] == "GA" and h["lat"] is not None
    ]
    demo = next(h for h in rows if h["id"] == DEMO_HOSPITAL)
    filer = filers[demo["policy_ref"][0]]
    policy = filer["policies"][demo["policy_ref"][1]]
    counts = manifest["counts"]
    adjusted = sorted(
        (s for s in modeled if s["complaints"] >= 100), key=lambda s: -s["adjusted_ratio"]
    )
    return {
        "states": states,
        "national": summary["national"]["rate_per_100k"],
        "year": summary["rate_year"],
        "rateCuts": [round(q, 2) for q in statistics.quantiles(rates, n=6)],
        "topRate": [
            {"abbr": s["state_abbr"], "value": s["rate_per_100k"], "n": s["complaints"]}
            for s in sorted(modeled, key=lambda s: -s["rate_per_100k"])[:5]
        ],
        "topAdjusted": [
            {"abbr": s["state_abbr"], "value": s["adjusted_ratio"], "n": s["complaints"]}
            for s in adjusted[:5]
        ],
        "rUninsured": round(statistics.correlation([s["uninsured_rate"] for s in modeled], rates), 2),
        "rPoverty": round(statistics.correlation([s["poverty_rate"] for s in modeled], rates), 2),
        "model": summary["model"],
        "gaHospitals": ga,
        "demoHospital": {
            "xy": _albers(demo["lon"], demo["lat"]),
            "name": demo["name"].title(),
            "city": demo["city"].title(),
            "filer": filer["name"],
            "taxYear": filer["tax_year"],
            "free": policy["free_fpg"],
            "discount": policy["discount_fpg"],
            "noticeOnBills": policy["notice_on_bills"],
            "translated": policy["translated"],
            "ecasBefore": policy["ecas_permitted_before_efforts"],
            "noEcasBefore": policy["no_ecas_before_efforts"],
        },
        "counts": counts,
        "cfpbWindows": manifest["cfpb_pull"]["windows"],
        "priceStatus": prices["status"],
        "linkReview": {"first": [48, 50], "second": [50, 50]},
        "guide": GUIDE_EXCHANGE,
    }


def _case(documents) -> dict:
    result = reconcile(documents)
    return {
        "ledger": [{"label": row.label, "cents": row.cents} for row in result.ledger],
        "supported": result.supported_balance_cents,
        "collection": result.collection_cents,
        "applied": result.applied_payments_cents,
        "findings": [finding.code for finding in result.findings],
    }


LAYOUT_LABELS = {
    "table": "Table rows",
    "stacked": "Label above value",
    "leaders": "Dotted leaders",
    "grid": "Two columns",
    "scan": "Scanned PDF (OCR)",
    "photo": "Phone photo (OCR)",
}
TEXT_LAYOUTS = ("table", "stacked", "leaders", "grid")


def layout_data(layouts: dict) -> dict:
    rows = [
        {
            "key": key,
            "label": LAYOUT_LABELS[key],
            "before": layouts["layouts"][key]["baseline"]["fields_correct"],
            "now": layouts["layouts"][key]["current"]["fields_correct"],
            "wrong": layouts["layouts"][key]["current"]["fields_extracted"]
            - layouts["layouts"][key]["current"]["fields_correct"],
        }
        for key in LAYOUT_LABELS
    ]
    expected = {v["current"]["fields_expected"] for v in layouts["layouts"].values()}
    assert len(expected) == 1, "Layouts must score the same field set"
    # The slide says every text layout is fully read and only OCR layouts miss values.
    text =[r for r in rows if r["key"] in TEXT_LAYOUTS]
    assert all(r["now"] == next(iter(expected)) and r["wrong"] == 0 for r in text)
    return {"expected": next(iter(expected)), "rows": rows}


def deck_data() -> dict:
    research = json.loads((ROOT / "data/research/research.json").read_text(encoding="utf-8"))
    bench = json.loads((ROOT / "data/benchmark/results.json").read_text(encoding="utf-8"))
    layouts = json.loads((ROOT / "data/benchmark/layouts.json").read_text(encoding="utf-8"))
    atlas = json.loads((ROOT / "public/atlas/states.json").read_text(encoding="utf-8"))
    api, archive = research["api"], research["archive"]
    assert atlas["rate_year"] == research["scope"]["year"]
    assert atlas["national"]["count"] == api["total_complaints"]
    georgia = next(row for row in atlas["states"] if row["state_abbr"] == "GA")

    def screenshot(name: str) -> str:
        data = (ROOT / "presentation/assets" / name).read_bytes()
        return "data:image/png;base64," + base64.b64encode(data).decode("ascii")

    paid = example_documents("paid")
    without_receipt = example_documents("paid")
    for doc in without_receipt:
        doc.included = doc.kind != "receipt"
    with_case, without_case = _case(paid), _case(without_receipt)
    wrong_case = _case(example_documents("wrong_account"))
    # The slides narrate these outcomes; fail the build rather than show stale claims.
    assert "possible_uncredited_payment" in with_case["findings"]
    assert "missing_payment_evidence" in without_case["findings"]
    assert wrong_case["supported"] is None
    wrong_receipt = next(d for d in example_documents("wrong_account") if d.kind == "receipt")

    parsed = extract_document(FAILURE_TEXT, "bill", "Bill", method="local")
    assert "provider" not in parsed.fields, "The failure example no longer fails"

    not_owed = "Attempts to collect debt not owed"
    outcomes = api["response_outcomes"]["groups"]
    payment_flag = {family.key: family.payment_finding for family in FAMILIES}
    return {
        "facts": {
            doc.kind: {key: {"value": f.value, "quote": f.quote} for key, f in doc.fields.items()}
            for doc in paid
        },
        "wrongAccount": wrong_receipt.fields["account"].value,
        "withReceipt": with_case,
        "withoutReceipt": without_case,
        "wrongCase": wrong_case,
        "drill": [
            {"total": api["total_complaints"], "segs": api["issue_counts"], "hi": not_owed},
            {"total": api["not_owed_count"], "segs": api["not_owed_subissues"], "hi": "Debt was paid"},
            {"total": outcomes[1]["total"], "segs": outcomes[1]["responses"], "hi": "Closed with explanation"},
        ],
        "allResponses": outcomes[0],
        "responseCaveat": api["response_outcomes"]["caveat"],
        "retrieved": research["retrieved_at"][:10],
        "community": {
            "rateYear": atlas["rate_year"],
            "georgiaComplaints": georgia["complaints"],
            "georgiaRate": georgia["rate_per_100k"],
            "nationalImage": screenshot("community-national.png"),
            "georgiaImage": screenshot("community-georgia.png"),
        },
        "archive": {
            "period": archive["period"],
            "unique": archive["unique_narratives"],
            "patterns": [
                {"id": p["id"], "label": SHORT_PATTERNS.get(p["id"], p["label"]), "count": p["count"]}
                for p in archive["patterns"]
            ],
            "documents": [
                {"id": d["id"], "label": SHORT_DOCUMENTS.get(d["id"], d["label"]), "count": d["count"]}
                for d in archive["document_mentions"]
            ],
            "matrix": archive["pattern_document_matrix"],
        },
        "bench": {
            "bundles": bench["bundles"],
            "passed": bench["all_checks_passed"],
            "falseFlags": bench["false_payment_findings"],
            "noPaymentBundles": bench["no_payment_bundles"],
            "shouldAbstain": bench["abstention"]["should_abstain"],
            "abstained": bench["abstention"]["correctly_abstained"],
            "families": [
                {
                    "key": f["key"],
                    "label": f["label"],
                    "bundles": f["bundles"],
                    "passed": f["passed"],
                    "withholds": f["withholds_balance"],
                    "flags": payment_flag[f["key"]],
                }
                for f in bench["families"]
            ],
        },
        "layouts": layout_data(layouts),
        "atlas": atlas_data(),
        "failure": {
            "lines": FAILURE_TEXT.splitlines(),
            "fields": {key: fact.value for key, fact in parsed.fields.items()},
        },
    }


def build() -> str:
    template = TEMPLATE.read_text(encoding="utf-8")
    if template.count(PLACEHOLDER) != 1:
        raise ValueError(f"{TEMPLATE.name} must contain {PLACEHOLDER} exactly once")
    data = json.dumps(deck_data(), ensure_ascii=False, separators=(",", ":"))
    return template.replace(PLACEHOLDER, data.replace("</", "<\\/"))


if __name__ == "__main__":
    OUTPUT.write_text(build(), encoding="utf-8")
    print(f"Wrote {OUTPUT.relative_to(ROOT)}")
