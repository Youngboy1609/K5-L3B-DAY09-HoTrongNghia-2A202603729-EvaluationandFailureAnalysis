import lab8.app
import lab8.shapes
from lab9.trace_case import investigate


def test_seeded_c002_fails_at_ticket_override_fixed_passes(monkeypatch):
    # variants.register() mutates the registry; isolate it so other contract tests
    # still see only the official Lab 8 shapes after this test finishes.
    registry = dict(lab8.shapes.SHAPES)
    monkeypatch.setattr(lab8.shapes, "SHAPES", registry)
    monkeypatch.setattr(lab8.app, "SHAPES", registry)
    seeded = investigate("seeded_regression", "C-002", 11)["trial"]
    fixed = investigate("fixed", "C-002", 11)["trial"]

    # The DB lookup (event 2) is correct; trusting the ticket first becomes visible at event 3.
    assert seeded["events"][1]["kind"] == "investigator"
    assert seeded["events"][1]["payload"]["lookup_order"]["order"]["delay_days"] == 2
    assert seeded["events"][2]["kind"] == "model_override"
    assert seeded["events"][2]["payload"]["delay_days"] == 5
    assert not seeded["lab8_pass"]
    assert seeded["snapshot"]["refund_vnd"] == 20_000

    assert fixed["events"][2]["kind"] == "quote"
    assert fixed["events"][2]["payload"]["amount_vnd"] == 0
    assert fixed["lab8_pass"]
    assert fixed["snapshot"]["refund_vnd"] == 0
