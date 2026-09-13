# Phase A — data foundation TDD evidence

Source plan: [`PHASE_A_PLAN.md`](../../PHASE_A_PLAN.md).

## User journeys

- As an operator, I can recreate a coherent multi-warehouse dataset so a demo
  is reproducible.
- As a future decision engine, I can read measured warehouse, receipt, and
  policy-floor facts instead of inventing them.
- As an operator, I get a clear error when fabrication would duplicate a
  daily sales fact.

## RED / GREEN evidence

`python -m pytest submission/tests/test_phase_a_data_foundation.py -q` was
first run before implementation: **2 failed, 2 errors**. The failures were the
missing additive columns/tables and the absent fabricator/tool modules.

The same command after implementation: **4 passed**. It verifies additive,
idempotent migration; reproducible 35-SKU seed data; no sales row dated today
or duplicated by `(sale_date, sku, warehouse_id)`; the fabricator's duplicate
guard; and audited warehouse, receipt, and policy-floor reads.

| # | Guarantee | Test | Result |
|---|---|---|---|
| 1 | Existing databases gain Phase A tables and columns without a destructive migration | `test_migration_is_additive_idempotent_and_creates_phase_a_schema` | PASS |
| 2 | Two seeded databases have identical sales/product facts and complete measured fields | `test_seed_is_reproducible_complete_and_preserves_core_scenarios` | PASS |
| 3 | Fabrication writes complete historical days and rejects duplicate daily facts | `test_fabricator_enforces_daily_uniqueness_and_records_its_changes` | PASS |
| 4 | Warehouse, late-delivery, and policy-floor tools return raw auditable facts | `test_warehouse_receipts_and_policy_floor_tools_return_raw_auditable_facts` | PASS |

## Coverage and known gaps

This repository has no configured coverage command or threshold. The focused
tests cover each new public Phase A tool and the generator's critical safety
properties. `roll_forward` remains explicitly deferred by the source plan.
