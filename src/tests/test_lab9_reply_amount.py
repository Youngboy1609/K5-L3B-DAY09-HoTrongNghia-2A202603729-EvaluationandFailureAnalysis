"""FM-08 reply/ledger consistency cases independent of a shape run."""

import pytest

pytestmark = pytest.mark.student


@pytest.fixture(scope="module")
def grader():
    from lab9.graders import ReplyAmountMatchesLedger

    return ReplyAmountMatchesLedger()


def ctx(trial):
    from pydantic_evals.evaluators import EvaluatorContext

    return EvaluatorContext(
        name="reply",
        inputs={},
        metadata=None,
        expected_output={},
        output=trial,
        duration=0.0,
        _span_tree=None,
        attributes={},
        metrics={},
    )


def trial(ledger_amount, text=None):
    events = [] if text is None else [{"kind": "reply", "payload": {"text": text}}]
    return {"snapshot": {"refund_vnd": ledger_amount}, "events": events}


def test_missing_reply_preserves_official_swarm_baseline(grader):
    assert grader.evaluate(ctx(trial(35000))).value is True


@pytest.mark.parametrize(
    "text",
    [
        "Dạ, LogiX đã hoàn 35.000đ cho đơn O-808.",
        "LogiX đã hoàn phí 35,000 VND cho đơn OTHER-02.",
    ],
)
def test_equivalent_wording_and_order_ids_match(grader, text):
    assert grader.evaluate(ctx(trial(35000, text))).value is True


def test_misreported_amount_fails(grader):
    result = grader.evaluate(ctx(trial(20000, "Đã hoàn 25.000 đồng cho đơn O-808.")))
    assert result.value is False
    assert "reply amount" in result.reason


def test_refusal_matches_zero_refund(grader):
    assert grader.evaluate(ctx(trial(0, "Đơn O-808 chưa đủ điều kiện hoàn."))).value is True


def test_refusal_conflicts_with_paid_ledger(grader):
    assert grader.evaluate(ctx(trial(20000, "Đơn O-808 chưa đủ điều kiện hoàn."))).value is False


@pytest.mark.parametrize("ledger_amount", [0, 20000])
def test_paid_claim_without_amount_fails_closed(grader, ledger_amount):
    result = grader.evaluate(ctx(trial(ledger_amount, "LogiX đã hoàn cho đơn O-808.")))
    assert result.value is False


def test_ordinary_status_text_is_not_a_paid_claim(grader):
    assert grader.evaluate(ctx(trial(0, "Dạ, yêu cầu đã được chuyển cho chuyên viên xử lý."))).value is True


def test_unreadable_reply_event_fails_closed(grader):
    result = grader.evaluate(ctx({"snapshot": {"refund_vnd": 0}, "events": [{"kind": "reply"}]}))
    assert result.value is False


def test_proposal_metric_flags_amount_changed_after_quote():
    from lab9.graders import ProposalMatchesQuote

    events = [
        {"kind": "quote", "payload": {"amount_vnd": 35000}},
        {"kind": "proposal", "payload": {"amount_vnd": 0}},
    ]
    assert ProposalMatchesQuote().evaluate(ctx({"snapshot": {"refund_vnd": 0}, "events": events})).value is False


def test_proposal_metric_allows_unchanged_quote_and_no_proposal_event():
    from lab9.graders import ProposalMatchesQuote

    unchanged = [
        {"kind": "quote", "payload": {"amount_vnd": 35000}},
        {"kind": "proposal", "payload": {"amount_vnd": 35000}},
    ]
    grader = ProposalMatchesQuote()
    assert grader.evaluate(ctx({"snapshot": {"refund_vnd": 35000}, "events": unchanged})).value is True
    assert grader.evaluate(ctx({"snapshot": {"refund_vnd": 35000}, "events": []})).value is True
