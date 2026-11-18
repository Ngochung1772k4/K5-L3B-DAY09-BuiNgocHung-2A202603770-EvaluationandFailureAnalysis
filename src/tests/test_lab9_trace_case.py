"""Regression tests from docs/trace_case.md: replay one trial and assert the grader that catches
the first wrong step. Runs the shape on a fresh temp store (MockLLM, deterministic)."""
import pytest

pytestmark = pytest.mark.student


def ctx(trial, label):
    from pydantic_evals.evaluators import EvaluatorContext

    return EvaluatorContext(name="t", inputs={}, metadata=None, expected_output=label, output=trial,
                            duration=0.0, _span_tree=None, attributes={}, metrics={})


def _case(shape, claim, seed):
    from lab9.trace_case import investigate

    case = investigate(shape, claim, seed)
    return case["trial"], case["label"]


def test_lab9_trace_case_fm05_pre_deducted_c014():
    """seeded_regression C-014@11: event 5 `proposal` 120000 = quote 150000 - prior 30000, the host
    deducts the prior refund again -> ledger 90000. fixed: no proposal event, ledger 120000."""
    from lab9 import graders

    bad, label = _case("seeded_regression", "C-014", 11)
    kinds = [e["kind"] for e in bad["events"]]
    first = kinds.index("proposal")
    assert kinds[first - 1] == "refund_history"
    assert bad["events"][first]["payload"]["amount_vnd"] == 120000
    assert graders.RefundAmountCorrect().evaluate(ctx(bad, label)).value is False
    assert graders.ProposalAmountCorrect().evaluate(ctx(bad, label)).value is False
    assert graders.ReplyAmountMatchesLedger().evaluate(ctx(bad, label)).value is False

    good, label = _case("fixed", "C-014", 11)
    assert "proposal" not in [e["kind"] for e in good["events"]]
    for g in (graders.RefundAmountCorrect, graders.ProposalAmountCorrect, graders.ReplyAmountMatchesLedger):
        assert g().evaluate(ctx(good, label)).value is True


def test_lab9_trace_case_fm08_reply_lies_while_lab8_passes_c008():
    """seeded_regression C-008@11: Lab 8's grader passes (ledger 20000 is right) but the reply tells
    the customer 35.000đ. Only the FM-08 grader sees it."""
    from lab9 import graders

    bad, label = _case("seeded_regression", "C-008", 11)
    assert bad["lab8_pass"] is True
    assert graders.ReplyAmountMatchesLedger().evaluate(ctx(bad, label)).value is False
    good, label = _case("fixed", "C-008", 11)
    assert graders.ReplyAmountMatchesLedger().evaluate(ctx(good, label)).value is True


def test_lab9_reply_amount_parser():
    from lab9.graders import stated_amounts

    assert stated_amounts("Dạ, LogiX đã hoàn 35.000đ cho đơn O-107.") == [35000]
    assert stated_amounts("hoàn phí 1.150.000đ, 150,000 VND, 20000 đồng") == [1150000, 150000, 20000]
    assert stated_amounts("Dạ, đơn O-1001 đã được xử lý.") == []
