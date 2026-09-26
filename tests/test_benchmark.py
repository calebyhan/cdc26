"""The synthetic benchmark passes and is sensitive to a relaxed payment rule."""

from not_my_debt import reconcile as reconcile_module
from not_my_debt.benchmark import FAMILIES, run


def test_benchmark_bundles_meet_documented_rules():
    results = run(per_family=3)
    assert results["bundles"] == 3 * len(FAMILIES)
    assert results["all_checks_passed"] == results["bundles"]
    assert results["false_payment_findings"] == 0


def test_benchmark_detects_pending_payment_treated_as_settled(monkeypatch):
    monkeypatch.setattr(reconcile_module, "SETTLED", reconcile_module.SETTLED | {"pending"})
    results = run(per_family=3)
    failed = {f["key"] for f in results["families"] if f["passed"] < f["bundles"]}
    assert failed == {"pending_payment"}
