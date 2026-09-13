# Phase F constrained manual-cover path — TDD evidence

Source intent: `PHASE_E1_PLAN.md`, clarified by the operator on 2026-09-12
and superseded by `AUTONOMOUS_PLAN.md` R11.

## User journeys

1. When sales history is too thin, a planner cannot type any numeric
   substitute; the Phase E park/backfill/re-run loop remains mandatory.
2. When sales velocity is usable but policy maturity is `PROVISIONAL` or
   `INSUFFICIENT`, a planner may enter only whole-number days of stock to
   hold; demand, quantity, and supplier eligibility remain computed.
3. When maturity is `ESTABLISHED`, the graph uses
   `sku_policy.derived_cover_days` and does not accept a caller-supplied
   cover target.

## RED

`python -m pytest submission/tests/test_phase_f_manual_target_constraints.py -q --disable-warnings`

Before implementation: **5 failed**. The failures were missing target-policy
resolution/manual-resume nodes and the public `run_case` target parameter.

## GREEN

`python -m pytest submission/tests/test_phase_f_manual_target_constraints.py submission/tests/test_phase_e_insufficient_data_loop.py submission/tests/test_phase9_demand_clarification_message.py submission/tests/test_phase_c_autonomous_sweep.py -q --disable-warnings`

Result: **22 passed, 27576 warnings in 20.31s**.

`python -m compileall -q submission tools`

Result: success.

Manual local end-to-end check:

1. `python -m submission.app run AC-001 DEL-01` paused with
   `MANUAL COVER DAYS NEEDED` and explicitly stated that demand rate, target
   units, and order quantity stay system-computed.
2. `python -m submission.app resume-manual-cover CASE-AC-001-DEL-01 14 "Yuvraj"`
   resumed the paused graph. A checkpoint read then reported `NO_ACTION`,
   target `14`, and provenance `human:Yuvraj`.

## Guarantees

| Guarantee | Test / evidence | Result |
| --- | --- | --- |
| Established policy overrides an attempted pre-supplied cover value | `test_established_policy_overrides_any_pre_supplied_cover_days` | PASS |
| Provisional and insufficient maturity request only manual cover days | `test_provisional_policy_requires_the_single_manual_cover_days_input`, `test_insufficient_maturity_with_valid_velocity_also_requires_cover_days_only` | PASS |
| Extra numeric fields such as demand rate are rejected | `test_manual_target_resume_rejects_any_extra_human_number` | PASS |
| Public case start accepts SKU and warehouse only | `test_public_case_entrypoint_does_not_accept_a_target_or_order_quantity` | PASS |
| Thin-history backfill re-fetches the configured database and then reaches the maturity gate | `test_backfill_then_fresh_graph_run_uses_the_configured_database` | PASS |

## Named-provenance follow-up — 2026-09-12

The original implementation did not collect a person's name for the one
allowed manual cover target, so its provenance was the generic
`manual_cover_days:operator`. The follow-up requires a nonblank name in the
interrupt payload, records `human:<name>` in state and the audit event, and
shows the required approval-card warning. It also repaired a pre-existing
watchlist crash discovered by the focused UI smoke test.

- RED: `python -m pytest submission/tests/test_phase_f_manual_target_constraints.py -q`
  → 3 failed for missing named-person validation/provenance and the missing
  warning helper.
- GREEN: the same command → **8 passed**.
- UI smoke: `python -m pytest submission/tests/test_phase9_ui_deep_links.py -q`
  → initially exposed `min(..., reverse=True)` in `scan_portfolio`; after
  the focused fix → **2 passed**.
- Syntax: `python -m py_compile submission/graph/workflow.py submission/app.py submission/ui.py submission/ui_messages.py submission/portfolio.py`
  → success.

No full test suite was run, by request. The repository is not a Git worktree,
so no TDD checkpoint commits were possible.
