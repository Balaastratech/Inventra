# Phase B evidence

Source plan: `PHASE_B_PLAN.md`.

| Guarantee | Test / command | Result |
|---|---|---|
| Standard-normal quantiles, demand statistics, Croston level, empirical intermittent safety stock, and all four demand quadrants are deterministic | `python -m pytest submission/tests/test_phase_b_statistics_and_policy_engine.py -q` | 10 passed |
| Completed-month and recent-demand windows use explicit calendar boundaries | same focused test | passed |
| ABC/XYZ, maturity, newsvendor bounds, safety stock, ROP, derived cover, regime shifts, and ABC hysteresis have hand-checked coverage | same focused test | passed |
| Full seeded historical classification can persist policies | `init_db('phase_b_test.db'); seed_data('phase_b_test.db')` | 391 `sku_policy` rows written across 34 SKU/warehouse pairs |
| Measured margin, carrying components, lateness distribution, billing basis, and quantity-dependent landed cost are independently loaded | same focused test, temporary SQLite database | passed |
| Fully measured `EconomicsInputs` remove assumption caveats and preserve per-figure provenance | same focused test | passed |
| All Python changes compile | `python -m compileall -q domain tools database submission` | passed |

RED evidence: before production code was added, the focused test failed at collection with `ModuleNotFoundError: No module named 'submission.statistics'`.

Known verification limitation: `submission/tests/test_phase2_3_graph.py` could not reset the shared `database/inventra.db` because another local process held a Windows file lock. It failed before test collection, not on a Phase B assertion. The focused Phase B suite was rerun afterward and passed.
