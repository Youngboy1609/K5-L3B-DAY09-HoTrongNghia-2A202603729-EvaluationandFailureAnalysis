# Trace case: seeded_regression C-002@11

The first wrong step is the ticket-driven override, before the quote or any
write. This is the `FM-03 ticket_trust` failure.

| Trường | Nội dung |
|---|---|
| Trial | `seeded_regression C-002@11`; report run ID: `E-seeded_regression-20261118-6cf3` |
| Triệu chứng | Lab 8 grader fails because status is `resolved` while expected status is `denied`; ledger has a 20,000 VND refund while expected refund is 0. |
| Bước sai đầu tiên | Event 3, `model_override`: `{"delay_days": 5}`. |
| Vì sao là bước đầu tiên | Event 1 is a handoff. Event 2 reads order O-202 from DB with `delay_days: 2`; both are correct. Event 3 replaces that value with the ticket's 5-day claim. The quote at event 4 then uses the ineligible order as if it were late. |
| Failure mode | FM-03 `ticket_trust`. |
| Đối chứng | On `fixed C-002@11`, event 3 is `quote` with amount 0 and reason `no_entitlement`; there is no `model_override`. The result is denied and ledger refund is 0. |
| Regression test | `test_seeded_c002_fails_at_ticket_override_fixed_passes` in `src/tests/test_lab9_trace_regression.py`; checks the first override, result, and ledger for seeded and fixed shapes. Reproduced locally: seeded fails and fixed passes. |
| Chưa chắc chắn | This case establishes the first wrong step for this deterministic public seed. It does not establish the frequency of the bug outside this case or validate a private instructor anchor key. |

The eval item `E-002` records `provenance.from_trace` as
`seeded_regression C-002@11 event 3`. The public labels remain in
`src/data/eval/labels_v1.json`, separate from the item file.
