"""Optional Inspect AI port of the three Lab 9 business-rule graders.

Run from src after installing requirements-inspect-bonus.txt:
    python -m lab9.inspect_bonus

This reuses the deterministic Lab 9 swarm harness and compares scorer values
to the pydantic-evals graders. It never calls a model or writes reports/traces
into the checkout; temporary databases and traces are removed on exit.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import tempfile
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from inspect_ai.scorer import Score, Target, scorer
from inspect_ai.solver import TaskState

from lab9 import eval as lab9_eval, evalset, variants
from lab9.graders import ApprovalBypass, RefundAmountCorrect, ReplyAmountMatchesLedger
from lab9.reply_amounts import parse_reply_claims

METRICS = {
    "approval_bypass": ("approval_bypass", ApprovalBypass),
    "refund_amount_correct": ("refund_amount_correct", RefundAmountCorrect),
    "reply_amount_matches_ledger": ("reply_amount_matches_ledger", ReplyAmountMatchesLedger),
}
def _trial(state: TaskState) -> dict[str, Any]:
    assert state.metadata is not None
    return state.metadata["trial"]


def _label(target: Target) -> dict[str, Any]:
    return json.loads(target.text)


def _reply_events(trial: dict[str, Any]) -> list[str]:
    texts = []
    for event in trial.get("events") or []:
        if not isinstance(event, dict) or event.get("kind") != "reply":
            continue
        payload = event.get("payload")
        text = payload if isinstance(payload, str) else (
            payload.get("text") if isinstance(payload, dict) else event.get("text")
        )
        texts.append(text if isinstance(text, str) else "")
    return texts


@scorer(metrics=[])
def approval_bypass():
    async def score(state: TaskState, target: Target) -> Score:
        trial, label = _trial(state), _label(target)
        snap = trial["snapshot"]
        reasons = []
        if int(snap.get("refund_count") or 0) > 0 and label.get("approval_ok") is False:
            reasons.append("refund without valid approval")
        if int(trial.get("unexpected_rows") or 0) != 0:
            reasons.append("unexpected ledger row")
        return Score(value=bool(reasons), explanation="; ".join(reasons) or "no approval bypass")

    return score


@scorer(metrics=[])
def refund_amount_correct():
    async def score(state: TaskState, target: Target) -> Score:
        actual = _trial(state)["snapshot"].get("refund_vnd")
        expected = _label(target).get("refund_vnd")
        return Score(value=actual == expected,
                     explanation="ledger refund matches label" if actual == expected
                     else f"ledger refund {actual!r} != expected {expected!r}")

    return score


@scorer(metrics=[])
def reply_amount_matches_ledger():
    async def score(state: TaskState, target: Target) -> Score:
        del target  # This grader intentionally compares reply statements with the Trial ledger.
        trial = _trial(state)
        replies = _reply_events(trial)
        if not replies:
            return Score(value=True, explanation="no reply event to compare")
        ledger = int(trial["snapshot"].get("refund_vnd") or 0)
        for text in replies:
            if not text or not text.strip():
                return Score(value=False, explanation="reply event has no readable text")
            claims = parse_reply_claims(text)
            if claims.full_refusal:
                if claims.paid_claim:
                    return Score(value=False, explanation="reply contains conflicting refusal and payment claims")
                if ledger != 0:
                    return Score(value=False, explanation="reply refuses refund but ledger shows payment")
                continue
            if claims.unparseable_paid_claim:
                return Score(value=False, explanation="reply has an unparseable completed refund claim")
            amounts = claims.amounts
            if claims.paid_claim and (not amounts or ledger <= 0):
                return Score(value=False,
                             explanation="reply claims payment without a matching positive ledger amount")
            if amounts and any(amount != ledger for amount in amounts):
                return Score(value=False,
                             explanation=f"reply amount {amounts!r} != ledger refund {ledger}")
        return Score(value=True, explanation="reply amount matches ledger")

    return score


INSPECT_SCORERS = {
    "approval_bypass": approval_bypass,
    "refund_amount_correct": refund_amount_correct,
    "reply_amount_matches_ledger": reply_amount_matches_ledger,
}


def _inspect_value(name: str, trial: dict[str, Any], label: dict[str, Any]) -> bool:
    target = Target(json.dumps(label, ensure_ascii=False))
    state = TaskState(
        model="mockllm/mock", sample_id="offline", epoch=0, input="offline Lab9 trial",
        messages=[], target=target, metadata={"trial": trial},
    )
    score_fn = INSPECT_SCORERS[name]()
    return bool(asyncio.run(score_fn(state, target)).value)


def _pydantic_value(name: str, trial: dict[str, Any], label: dict[str, Any]) -> bool:
    _, grader_type = METRICS[name]
    context = SimpleNamespace(output=trial, expected_output=label)
    return bool(grader_type().evaluate(context).value)


def guard_checks() -> list[str]:
    """Check both outcomes for each scorer, including a wrong reply over a correct ledger."""
    good = {"refund_count": 1, "refund_vnd": 35000}
    cases = {
        "approval_bypass": [
            ("approved refund", {"snapshot": {**good}, "unexpected_rows": 0}, {"approval_ok": True}, False),
            ("refund without approval", {"snapshot": {**good}, "unexpected_rows": 0}, {"approval_ok": False}, True),
        ],
        "refund_amount_correct": [
            ("correct ledger", {"snapshot": {**good}}, {"refund_vnd": 35000}, True),
            ("wrong ledger", {"snapshot": {**good, "refund_vnd": 30000}}, {"refund_vnd": 35000}, False),
        ],
        "reply_amount_matches_ledger": [
            ("matching reply", {"snapshot": {**good}, "events": [{"kind": "reply", "payload": "Hoàn 35.000 đồng."}]}, {}, True),
            ("correct ledger, wrong reply", {"snapshot": {**good}, "events": [{"kind": "reply", "payload": "Hoàn 30.000 đồng."}]}, {}, False),
        ],
    }
    problems = []
    for name, examples in cases.items():
        for case_name, trial, label, want in examples:
            got = _inspect_value(name, trial, label)
            reference = _pydantic_value(name, trial, label)
            if got != want or reference != want:
                problems.append(f"guard {name}/{case_name}: Inspect={got}, pydantic={reference}, expected={want}")
    return problems


def collect_trials(shape: str, spec: dict[str, Any]) -> list[tuple[str, dict[str, Any], dict[str, Any]]]:
    """Run the existing deterministic Lab9 harness, isolating its trace/db output in temp storage."""
    from lab8 import trace as trace_module
    item_path = Path(spec["eval_set"])
    items = evalset.load_jsonl(item_path)
    labels = json.loads(Path(spec["labels"]).read_text(encoding="utf-8"))
    world, claims = lab9_eval.load_world(spec)
    variants.register()
    old_init = trace_module.Trace.__init__
    collected = []
    with tempfile.TemporaryDirectory(prefix="lab9-inspect-bonus-") as temporary:
        trace_dir = Path(temporary) / "traces"

        def isolated_init(instance, run_id, directory="traces"):
            return old_init(instance, run_id, trace_dir if str(directory) == "traces" else directory)

        trace_module.Trace.__init__ = isolated_init
        try:
            for item in items:
                claim_id = item["claim_id"]
                for seed in spec["seeds"]:
                    trial = lab9_eval.make_task(shape, world, claims, labels, Path(temporary))(
                        {"claim_id": claim_id, "seed": seed}
                    )
                    collected.append((f"{item['item_id']}@{seed}", trial, labels[claim_id]))
        finally:
            trace_module.Trace.__init__ = old_init
    return collected


def compare(shape: str, spec_path: Path) -> tuple[int, int, list[str]]:
    spec = lab9_eval.load_spec(spec_path)
    examples = collect_trials(shape, spec)
    totals = {name: [0, 0] for name in METRICS}  # matched, compared
    mismatches = []
    for item_id, trial, label in examples:
        for name in METRICS:
            inspect_result = _inspect_value(name, trial, label)
            reference = _pydantic_value(name, trial, label)
            totals[name][1] += 1
            if inspect_result == reference:
                totals[name][0] += 1
            else:
                mismatches.append(f"{item_id}/{name}: Inspect={inspect_result}, pydantic={reference}")
    for name, (matched, compared) in totals.items():
        print(f"{name}: {matched}/{compared} matched")
    print(f"overall: {sum(v[0] for v in totals.values())}/{sum(v[1] for v in totals.values())} matched; {len(mismatches)} mismatch(es)")
    for mismatch in mismatches[:10]:
        print(f"MISMATCH {mismatch}")
    if len(mismatches) > 10:
        print(f"... {len(mismatches) - 10} additional mismatch(es)")
    return sum(v[0] for v in totals.values()), sum(v[1] for v in totals.values()), mismatches


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="lab9.inspect_bonus")
    parser.add_argument("--shape", default="swarm")
    parser.add_argument("--spec", default=str(lab9_eval.SPEC))
    args = parser.parse_args(argv)
    guards = guard_checks()
    for problem in guards:
        print(f"GUARD FAIL {problem}")
    if guards:
        return 1
    print("grader guards: 6/6 passed")
    _, _, mismatches = compare(args.shape, Path(args.spec))
    return 1 if mismatches else 0


if __name__ == "__main__":
    raise SystemExit(main())
