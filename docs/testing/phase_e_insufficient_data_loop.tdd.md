# Phase E TDD evidence

Source plan: [PHASE_E_PLAN.md](../../PHASE_E_PLAN.md).

## User journeys

- A planner receives a precise, actionable request when sales history is too thin, rather than a dead-end block.
- A planner or data operator can backfill only missing daily sales rows and safely re-run the case.
- An undecidable demand signal becomes a parked work item rather than an interactive window-selection pause.
- A sweep does not spend work on a SKU that remains parked pending data resolution.

## RED / GREEN record

RED command:

```powershell
$env:DATABASE_PATH = Join-Path $env:TEMP ('inventra_phase_e_' + [guid]::NewGuid().ToString() + '.db')
python -m pytest submission/tests/test_phase_e_insufficient_data_loop.py -q
```

Before production edits this ran **3 failing tests**: insufficient data was `BLOCKED`, `backfill_missing_sales` did not exist, and `await_window_choice` was still a graph node.

GREEN command:

```powershell
$env:DATABASE_PATH = Join-Path $env:TEMP ('inventra_phase_e_' + [guid]::NewGuid().ToString() + '.db')
python -m pytest submission/tests/test_phase_e_insufficient_data_loop.py submission/tests/test_phase9_demand_clarification_message.py -q
```

Result: **9 passed**. The dedicated Phase C compatibility command also passed: `python -m pytest submission/tests/test_phase_c_autonomous_sweep.py -q` → **7 passed**.

## Guarantees

| Guarantee | Test coverage | Result |
|---|---|---|
| Thin sales data routes to `NEEDS_INFORMATION`, with exact SKU, warehouse, and deficit detail | `test_insufficient_sales_history_routes_to_needs_information` | PASS |
| A thin-data case creates an actionable `INSUFFICIENT_SALES_HISTORY` park | `test_insufficient_sales_history_creates_an_actionable_park` | PASS |
| Backfill is inclusive, preserves existing rows, and is idempotent | `test_backfill_missing_sales_is_additive_safe` | PASS |
| Backfill followed by a fresh compiled-graph run reads the active configured database | `test_backfill_then_fresh_graph_run_uses_the_configured_database` | PASS |
| Ambiguous demand parks with both demand-window figures | `test_ambiguous_demand_is_parked_with_both_window_figures` | PASS |
| The obsolete graph node and CLI API are absent | `test_ambiguous_window_pause_is_retired` | PASS |
| Sweeps exclude an already parked SKU | `test_detect_candidates_excludes_an_already_parked_sku` | PASS |

## Known verification boundary

The project is not a Git repository, so checkpoint commits were unavailable. The full test suite was intentionally not run: the Phase E plan explicitly reserves it for a later, explicit user request. Existing tests that reset the shared seeded database were not used as a routine gate; isolated tests above cover the changed behavior. During this proof, `tools.sales` and `backfill_missing_sales` were corrected to honor `config.database_path`, rather than silently using the repository-default database.
