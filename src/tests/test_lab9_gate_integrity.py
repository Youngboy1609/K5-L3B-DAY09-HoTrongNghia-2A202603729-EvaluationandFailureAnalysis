import copy

import pytest

pytestmark = pytest.mark.student


def _report(rows, metrics):
    return {"run_id": "toy", "manifest": {"eval_set_sha": "toy", "items": 4, "seeds": [1, 2]},
            "rows": rows, "metrics": metrics, "evaluator_failures": []}


def _pass_rows(value=True):
    return [{"item_id": f"E-{i}", "seed": seed, "pass_rate": value, "slices": []}
            for i in range(4) for seed in (1, 2)]


def test_integrity_reconciles_reported_aggregates_with_raw_rows():
    from lab9 import gate

    rows = _pass_rows(True)
    baseline = _report(copy.deepcopy(rows), {"pass_rate": 1.0})
    forged = _report(copy.deepcopy(rows), {"pass_rate": 0.5})
    assert gate.integrity_check(baseline, baseline, {"metrics": [{"id": "pass_rate", "kind": "capability"}]}) == []
    assert any("aggregate pass_rate" in p for p in gate.integrity_check(
        forged, baseline, {"metrics": [{"id": "pass_rate", "kind": "capability"}]}))


def test_integrity_requires_registered_grader_field_on_every_row():
    from lab9 import gate

    rows = _pass_rows(True)
    rows[0].pop("pass_rate")
    report = _report(rows, {"pass_rate": 1.0})
    assert any("missing pass_rate" in p for p in gate.integrity_check(
        report, report, {"metrics": [{"id": "pass_rate", "grader": "lab8.metrics.trial_pass"}]}))


def test_check_rejects_malformed_manifest_and_empty_paired_samples():
    from lab9 import gate

    malformed = _report(_pass_rows(True), {"pass_rate": 1.0})
    malformed.pop("manifest")
    blocked, lines = gate.check(malformed, malformed, {"metrics": []})
    assert blocked == ["integrity"] and any("manifest" in line for line in lines)

    base = _report(_pass_rows(True), {"pass_rate": 1.0})
    pr = _report(_pass_rows(True), {"pass_rate": 1.0})
    for row in pr["rows"]:
        row["slices"] = ["only-pr"]
    spec = {"metrics": [{"id": "pass_rate", "kind": "capability", "blocking": True,
                         "threshold": {"min": 0.0, "no_significant_drop": True}}]}
    # The persisted reports disagree on slice labels, so the gate blocks before bootstrapping.
    assert gate.check(pr, base, spec)[0] == ["integrity"]

    spec["metrics"][0]["threshold"].pop("no_significant_drop")
    spec["slices"] = [{"name": "empty", "metric": "pass_rate", "blocking": True,
                       "no_significant_drop": True}]
    blocked, lines = gate.check(base, base, spec)
    assert blocked == ["slice:empty/pass_rate"]
    assert any("no paired slice items" in line for line in lines)


def test_ratchet_keys_slices_by_name_and_metric_and_checks_finite_bounds():
    from lab9 import gate

    report = _report(_pass_rows(True), {"pass_rate": 1.0})
    old = {"eval_set_version": "v2", "metrics": [{"id": "pass_rate", "threshold": {"min": 0.8}}],
           "slices": [{"name": "risk", "metric": "pass_rate", "min": 0.8, "blocking": True}]}
    changed_pair = copy.deepcopy(old)
    changed_pair["slices"][0]["metric"] = "reply_amount_matches_ledger"
    assert gate.integrity_check(report, report, changed_pair, old)

    invalid_bound = copy.deepcopy(old)
    invalid_bound["metrics"][0]["threshold"]["min"] = float("nan")
    assert any("not finite" in p for p in gate.integrity_check(report, report, invalid_bound))
