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
    assert grader.evaluate(ctx(trial(0, "LogiX không hoàn 20.000 VND."))).value is True
    assert grader.evaluate(ctx(trial(0, "The requested VND 20,000 was not refunded."))).value is True


def test_refusal_conflicts_with_paid_ledger(grader):
    assert grader.evaluate(ctx(trial(20000, "Đơn O-808 chưa đủ điều kiện hoàn."))).value is False


@pytest.mark.parametrize("ledger_amount", [0, 20000])
def test_paid_claim_without_amount_fails_closed(grader, ledger_amount):
    result = grader.evaluate(ctx(trial(ledger_amount, "LogiX đã hoàn cho đơn O-808.")))
    assert result.value is False


def test_ordinary_status_text_is_not_a_paid_claim(grader):
    assert grader.evaluate(ctx(trial(0, "Dạ, yêu cầu đã được chuyển cho chuyên viên xử lý."))).value is True


@pytest.mark.parametrize(("ledger", "text"), [
    (25000, "Khoản hoàn của đơn là 25 nghìn đồng."),
    (20000, "Đã chuyển yêu cầu hoàn 20.000 VND. Khoản hoàn của đơn là 20 nghìn đồng."),
    (20000, "Phí gốc 35.000 VND, lần này đã hoàn 20.000 VND."),
    (20000, "Lần trước đã hoàn 15.000 VND, lần này đã hoàn 20.000 VND."),
    (20000, "Dạ, đã hoàn 20.000 VND. Không hoàn thêm phần còn lại."),
    (20000, "LogiX đã hoàn 20.000 VND trên phí gốc 35.000 VND."),
    (20000, "Đã hoàn 20.000 VND và sẽ hoàn thêm 35.000 VND nếu được duyệt."),
    (20000, "Đã hoàn 20.000 đồng (phí gốc 35.000 đồng)."),
    (20000, "Refund processed: VND 20,000."),
    (20000, "Refunded VND 20,000. Original fee: VND 35,000."),
    (20000, "The requested refund for VND 20,000 was paid."),
    (20000, "Đã hoàn 20\u00a0000 đồng."),
    (20000, "Đã hoàn 20k."),
    (20000, "Đã hoàn 20,000.00 VND."),
])
def test_only_current_completed_refund_assertion_amounts_are_compared(grader, ledger, text):
    assert grader.evaluate(ctx(trial(ledger, text))).value is True


def test_changing_current_payout_still_fails(grader):
    assert grader.evaluate(ctx(trial(20000, "Khoản hoàn của đơn là 25 nghìn đồng."))).value is False
    assert grader.evaluate(ctx(trial(20000, "Đã hoàn 25.000 VND. Phí gốc là 20.000 VND."))).value is False
    assert grader.evaluate(ctx(trial(20000, "Đã chuyển 25.000 đồng tiền hoàn vào tài khoản."))).value is False
    assert grader.evaluate(ctx(trial(20000, "LogiX đã hoàn 25.000 VND trên phí gốc 20.000 VND."))).value is False
    assert grader.evaluate(ctx(trial(
        20000, "Đã hoàn 25.000 VND và sẽ hoàn thêm 20.000 VND nếu được duyệt."
    ))).value is False


@pytest.mark.parametrize("reply", [
    "Khoản hoàn: {amount} VND.",
    "Refund amount: {amount} VND.",
    "A refund of {amount} VND was issued.",
    "Đã hoàn {amount} VND và đã chuyển yêu cầu cho chuyên viên.",
    "Lần này đã hoàn {amount} VND so với 20.000 VND trước đó.",
    "LogiX đã xử lý hoàn tiền {amount} VND.",
    "Lần trước không được hoàn. Lần này đã hoàn {amount} VND.",
    "Previously not refunded. Refunded VND {amount} this time.",
    "The original fee of VND 35,000 was paid. Refunded VND {amount}.",
])
@pytest.mark.parametrize(("amount", "expected"), [("20.000", True), ("25.000", False)])
def test_current_payout_short_forms_and_side_actions(grader, reply, amount, expected):
    result = grader.evaluate(ctx(trial(20000, reply.format(amount=amount))))
    assert result.value is expected


def test_contrastive_current_payout_is_not_treated_as_a_prior_refund(grader):
    assert grader.evaluate(ctx(trial(
        20000, "Lần trước đã hoàn 15.000 VND nhưng lần này đã hoàn 20.000 VND."
    ))).value is True
    assert grader.evaluate(ctx(trial(
        20000, "Lần trước đã hoàn 20.000 VND nhưng lần này đã hoàn 25.000 VND."
    ))).value is False


def test_denial_of_whole_refund_conflicts_with_nonzero_ledger(grader):
    assert grader.evaluate(ctx(trial(20000, "Đơn này không được hoàn bất kỳ khoản nào."))).value is False


@pytest.mark.parametrize("text", [
    "Đã hoàn -20.000 VND.",
    "Đã hoàn −20.000 VND.",
    "Đã hoàn 20,00,0 VND.",
    "Đã hoàn 2,345.678 VND.",
    "Đã hoàn 20.000 VND. Đã được hoàn thêm 25.000 VND.",
    "Đã hoàn 20.000 VND. Không hoàn thêm phần còn lại. Đã được hoàn thêm 25.000 VND.",
])
def test_negative_malformed_and_duplicate_current_paid_claims_fail(grader, text):
    assert grader.evaluate(ctx(trial(20000, text))).value is False


def test_empty_reply_fails_closed(grader):
    assert grader.evaluate(ctx(trial(0, "  \n "))).value is False


def test_pending_future_amount_is_not_reported_as_paid(grader):
    assert grader.evaluate(ctx(trial(0, "Nếu được duyệt, LogiX sẽ hoàn 20.000 VND."))).value is True


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
