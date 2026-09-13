# Phase C autonomous sweep — TDD evidence

Source plan: [PHASE_C_PLAN.md](../../PHASE_C_PLAN.md).

| Guarantee | Target | Result |
| --- | --- | --- |
| Latest classification is read once per SKU and warehouses come from the authoritative table | `test_bulk_policy_read_and_warehouse_source` | PASS |
| At-risk SKUs become candidates while insufficient maturity is parked | `test_detects_risk_and_parks_insufficient_maturity` | PASS |
| Budget allocation is priority-ranked and cumulative | `test_budget_allocation_is_ranked_and_cumulative` | PASS |
| Parking is idempotent and a sweep record persists | `test_parking_is_idempotent_and_sweep_records_round_trip` | PASS |

RED evidence: before implementation, the new Phase C test target failed because the requested `submission.sweep` and `tools.sweep_runs` modules did not exist. GREEN evidence: `python -m pytest submission/tests/test_phase_c_autonomous_sweep.py -q` completed with `4 passed`.

## Phase C2 policy-floor reconciliation

`submission/tests/test_phase_c2_policy_floor_reconciliation.py` verifies that statistics win when above a floor, a higher floor is honoured and quantified, and the policy checklist exposes the floor question. Command: `python -m pytest submission/tests/test_phase_c2_policy_floor_reconciliation.py -q` — `3 passed`.

The existing policy-checklist regression file must be run with an isolated `DATABASE_PATH`; a live-database invocation was correctly blocked by a Windows file lock and was not treated as test evidence.
