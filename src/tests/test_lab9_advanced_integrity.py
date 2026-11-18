"""M7 extra vectors for integrity_check (traps beyond the public four)."""
import copy

import pytest

pytestmark = pytest.mark.student

ROWS = [{"item_id": f"E-{i:03d}", "seed": s, "pass_rate": i != 3 or s != 1, "cost": 1.0,
         "slices": ["money_movement"] if i < 2 else []}
        for i in range(4) for s in (1, 2)]
SPEC = {"eval_set_version": "v2", "metrics": [{"id": "pass_rate", "kind": "capability", "blocking": True,
                                               "threshold": {"min": 0.8, "no_significant_drop": True}}],
        "slices": [{"name": "money_movement", "metric": "pass_rate", "min": 0.9, "blocking": True}]}


def _report(rows):
    from lab9.eval import aggregate

    return {"manifest": {"eval_set_sha": "x", "items": 4, "seeds": [1, 2]}, "rows": rows,
            "metrics": aggregate(rows, ["pass_rate"]), "evaluator_failures": []}


@pytest.fixture
def base():
    return _report(copy.deepcopy(ROWS))


def test_advanced_clean_report_passes(base):
    from lab9 import gate

    assert gate.integrity_check(base, base, SPEC, SPEC) == []


def test_advanced_duplicated_rows_replacing_a_failure(base):
    from lab9 import gate

    rows = [r for r in copy.deepcopy(ROWS) if r["pass_rate"]]
    rows.append(copy.deepcopy(rows[0]))                    # same count, failing row swapped for a dup
    assert gate.integrity_check(_report(rows), base, SPEC)


def test_advanced_evaluator_failures_on_green_run(base):
    from lab9 import gate

    pr = _report(copy.deepcopy(ROWS))
    pr["evaluator_failures"] = ["E-003@1:TrialPass:boom"]
    assert gate.integrity_check(pr, base, SPEC)


def test_advanced_hand_edited_metric(base):
    from lab9 import gate

    pr = _report(copy.deepcopy(ROWS))
    pr["metrics"]["pass_rate"] = 1.0
    assert gate.integrity_check(pr, base, SPEC)


def test_advanced_item_relabelled_out_of_slice(base):
    from lab9 import gate

    rows = copy.deepcopy(ROWS)
    for r in rows:
        if r["item_id"] == "E-001":
            r["slices"] = []
    assert gate.integrity_check(_report(rows), base, SPEC)


def test_advanced_ratchet_blocking_and_slice_drop(base):
    from lab9 import gate

    off = copy.deepcopy(SPEC)
    off["metrics"][0]["blocking"] = False
    assert gate.integrity_check(base, base, off, SPEC)
    no_drop = copy.deepcopy(SPEC)
    no_drop["metrics"][0]["threshold"].pop("no_significant_drop")
    assert gate.integrity_check(base, base, no_drop, SPEC)
    renamed = copy.deepcopy(SPEC)
    renamed["eval_set_version"] = "v3"                     # same eval set sha: still ratcheted
    renamed["slices"] = []
    assert gate.integrity_check(base, base, renamed, SPEC)
    stricter = copy.deepcopy(SPEC)
    stricter["metrics"][0]["threshold"]["min"] = 0.9
    assert gate.integrity_check(base, base, stricter, SPEC) == []
