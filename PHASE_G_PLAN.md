# PHASE_G_PLAN.md

Detailed, end-to-end execution plan for **Phase G — Two Streamlit apps**
(`AUTONOMOUS_PLAN.md` §Phase G, as amended 2026-09-12 with rule **R11**),
against the codebase as it **actually exists after Phase F landed** — verified
by fresh direct reads this session, not carried over from earlier sessions'
notes. Several facts in `PHASE_E1_PLAN.md` and `PHASE_F_PLAN.md` are now
stale; where they conflict with §1 below, §1 wins.

**This is a planning document. Nothing described here has been built.**

> ## ⚠ TESTING INSTRUCTION — applies to every task in this plan
>
> **Do NOT run the full test suite (`python -m pytest submission/tests -q`)
> as a routine verification step.** There are **31 test files**; the suite
> resets and re-seeds the shared database, takes ~85s+, and a failure in
> unrelated legacy behaviour is not evidence about the UI change you just
> made.
>
> Each task in §4 names the **specific test file(s)** to run, against an
> **isolated `DATABASE_PATH`** (§6 gives the exact command). The full suite
> is a **one-time final gate, only when the user explicitly asks for it** —
> never a step inside a task.
>
> Phase G is the phase where this matters most: it touches no graph node and
> no agent, so almost every existing test is irrelevant to it. Running them
> all would be pure noise.

---

## 0. What Phase G has to produce

Two Streamlit apps on two ports against one database:

- **G1 — data console.** Full, validated create/edit/delete on every *input*
  table, from a screen, with no SQL and no terminal. Plus the missing-sales
  entry screen that makes **R11** workable, per-SKU levers, a scenario
  picker, a live statistics panel, and a persistent change log.
- **G2 — agent console.** Run the monitor, watch the sweep, work the approval
  queues (both gates), work the park queue, replay any case's audit trail.

**Why G1 is not "polish".** Under R11 (`AUTONOMOUS_PLAN.md` §Phase G), a human
never types a number that feeds a calculation — when data is missing the human
**enters it into the real table** and the system **re-reads from the
database**. G1 is the only screen where that is possible. Without it, R11 is
only satisfiable from a terminal, and the rule quietly degrades back into
"type a number into the agent."

Visual polish, responsive layout and any non-Streamlit frontend remain
Phase H. **Validated database editing is not polish — it is the deliverable.**

---

## 1. Ground truth (fresh reads, this session)

Verified by direct reads this session of: `submission/graph/workflow.py`
(full), `submission/graph/routes.py` (`route_after_evidence`,
`route_after_target_cover`, `route_after_demand_assessment`, `route_after_risk`),
`submission/graph/nodes.py` (`resolve_target_cover` in full),
`submission/state/state.py` (`CaseState`, `create_initial_state`),
`submission/app.py` (full), `submission/ui.py` (imports, sidebar, watchlist,
investigate, case dispatch, `_render_manual_cover_form`, `VIEWS`),
`submission/ui_messages.py` (full), `submission/portfolio.py` (function list,
`scan_portfolio`, `_stocked_pairs`, `list_pending_cases`),
`submission/tests/test_phase_f_manual_target_constraints.py` (full),
`database/schema.sql` (full table list), `fixtures/fabricator.py` (full
function list), `tools/` (full module list, plus signatures in
`policy_floors.py`, `warehouses.py`, `sweep_runs.py`, `parking.py`,
`classification.py`), `tools/workflow.py` (full), `.streamlit/config.toml`
(full), and `submission/tests/` (full 31-file listing).

### 1.1 Phase F is implemented — and differently from `PHASE_F_PLAN.md`

`PHASE_F_PLAN.md` is **superseded**. Its DF1 (human-typed demand velocity) was
voided by R11 and the shipped design is stricter and better. What actually
exists:

| Piece | Detail |
|---|---|
| New graph node `resolve_target_cover` | Sits between `fetch_evidence` and `assess_demand`. Reads `sku_policy` (from the state snapshot or `get_latest_sku_policy`). `ESTABLISHED` → `target_cover_days = round(derived_cover_days)`, `target_provenance = "derived:sku_policy"`, `target_mode = "DERIVED"`. `PROVISIONAL`/`INSUFFICIENT` → `target_cover_days = None`, `target_mode = "MANUAL_COVER_REQUIRED"`, status `NEEDS_INFORMATION`. **It deliberately discards any `target_cover_days` supplied at state construction** — its own docstring says so. |
| New route `route_after_target_cover` | → `blocked` (error) / `manual_target_required` / `ready`. |
| New interrupt `_await_manual_target_cover` | In `workflow.py`. **Strictly validates the resume payload**: the key set must be *exactly* `{target_cover_days, requested_by}` — any extra key (e.g. a smuggled `demand_rate`) fails closed with "only accepts days of stock"; the value must be a real `int` (bools rejected) inside `config.target_cover_min_days..max_days`; `requested_by` must be a non-empty string. On success: `target_provenance = f"human:{name}"`, `target_mode = "MANUAL_COVER_CONFIRMED"`. |
| `run_case` signature | **`run_case(sku, warehouse_id)` — two parameters, nothing else.** A test asserts this by `inspect.signature`. No target, no quantity, no rate can enter through the public entrypoint. |
| `resume_manual_cover(case_id, target_cover_days, requested_by, thread_id=None)` | The single resume path for the one legal input. |
| New `CaseState` fields | `target_mode: str` (`UNRESOLVED` → `DERIVED` \| `MANUAL_COVER_REQUIRED` → `MANUAL_COVER_CONFIRMED`), `target_provenance: str` (`pending` → `derived:sku_policy` \| `pending_manual_cover_days` → `human:<name>`). `target_cover_days` is now `Optional[int]`, starting `None`. |
| New module `submission/ui_messages.py` | `manual_cover_warning(values)` returns the exact required sentence, or `None`. Dependency-free so tests can assert the wording without Streamlit. |
| UI | `_render_manual_cover_form(case_id, values)` dispatched on `target_mode == "MANUAL_COVER_REQUIRED"`; `manual_cover_warning` rendered inside `_render_approval`. |

**The concern I raised last session about a missing `sku_policy` row silently
falling back to a flat 14 is already handled correctly**: `resolve_target_cover`
fails with `NEEDS_INFORMATION` and the message "Refresh `sku_policy` from
`sales_daily`, then re-run this case." Nothing defaults to 14 on that path.

### 1.2 The last remaining R11 violations — both are Phase G's to fix

- [ ] **`scan_portfolio` still ranks the entire watchlist against a single
  flat number.** `submission/ui.py` now correctly calls
  `scan_portfolio(None, warehouse_filter)` (the slider is gone), but
  `portfolio.scan_portfolio`'s own body does
  `target = target_cover_days or config.target_cover_default_days` → **14 for
  every product**. So the graph is now fully per-SKU while the watchlist that
  decides *which products a human even looks at* is still flat-14. This is the
  last live instance of problem §0.2, and it is a **G2 fix** (§4, Task G2-1).
- [ ] **`_await_missing_info` still accepts `target_cover_days`.** Its
  interrupt payload includes it and it applies `corrected["target_cover_days"]`
  unconditionally — a second, ungated route by which a human can set the
  target, bypassing `resolve_target_cover`'s maturity gate entirely. Its
  `sku`/`warehouse_id` fields are legitimate (they identify *which* product).
  Fix in **G2, Task G2-2**, and note it touches `workflow.py` + `app.py` +
  `ui.py` together.

### 1.3 What exists to build G1 on — and what is missing

**Tables, split by whether a human may edit them** (confirmed against
`schema.sql`'s actual `CREATE TABLE` list):

- **Input tables (10) — editable in G1:** `products`, `warehouses`,
  `inventory_snapshots`, `sales_daily`, `vendors`, `vendor_offers`,
  `monthly_budgets`, `stock_receipts`, `policy_rules`, `carrying_cost_inputs`
- **Derived tables (6) — read-only in G1:** `sku_policy`, `parked_items`,
  `sweep_runs`, `purchase_requests`, `audit_events`, `agent_memory_signals`

**The existing write layer is scenario-shaped, not CRUD-shaped.**
`fixtures/fabricator.py` has: `fabricate_history`, `backfill_missing_sales`,
`set_position`, `set_cover_days`, `age_snapshot`, `expire_offer`,
`set_vendor_reliability`, `set_budget`, `upsert_warehouse`,
`set_selling_price`, `set_storage_cost`, `set_billing_basis`, `set_freight`,
`set_carrying_inputs`, `add_receipt`, `get_fabrication_log`. Plus
`tools/policy_floors.set_policy_floor`.

**Concretely missing for G1.1's "full CRUD on every input table":** no create
or delete for `products`, `vendors`, or `vendor_offers`; no delete for
*anything*; no setter for `products.lifecycle` or `products.unit_volume_m3`;
no deactivate/delete for `policy_rules`; no edit of an existing `sales_daily`
row (only additive backfill). G1 must add these — see DG2.

**The fabrication log does not survive a restart.** `fabricator._LOG` is a
module-level `list[dict]` in memory. `get_fabrication_log()` returns a copy of
it. A Streamlit rerun keeps it (same process), but a restart loses every
record. For G1.3's change log to be worth anything it must be persisted —
see DG5.

**No second app and no `pages/` directory exist.** `submission/ui.py` is a
single flat script with a module-level sidebar and a `VIEWS` dict
(`watchlist`, `investigate`, `case`, `pending`, `history`). Two apps means two
files on two ports.

**`.streamlit/config.toml` pins a dark theme** and its comment documents that
`ui.py` uses only theme-aware components and hardcodes no colours. G1 must
follow the same discipline or the pinning stops being true.

### 1.4 Two traps for whoever implements this

- **There are two files called `workflow.py`.** `submission/graph/workflow.py`
  is the real LangGraph wiring. **`tools/workflow.py` is unused
  starter-package legacy** — a parallel, much simpler
  `recommend_vendor_option`/`draft_replenishment_proposal` path that ranks on
  `min(total_cost)`, which D29 explicitly replaced. Nothing imports it. Do not
  wire G1 or G2 to it, and do not "fix" it.
- **A manual-cover pause is indistinguishable from a missing-fields pause in
  the pending queue.** `list_pending_cases()` reports `values["status"]`, and
  `MANUAL_COVER_REQUIRED` carries status `NEEDS_INFORMATION` — the same string
  a missing-`sku` pause carries. G2 must branch on `target_mode`, not status,
  to route an operator to the right form (§4, Task G2-3).

---

## 2. Design decisions (confirm before coding)

**DG1 — `submission/ui.py` becomes G2; a new `submission/data_console.py`
becomes G1.** `ui.py` already *is* the agent console in all but name — it has
the watchlist, the case screen, both approval gates, the pending queue, the
history timeline and the manual-cover form, all working and all covered by
existing tests. Rebuilding that as a "new G2" would throw away working code
for a rename. G1 is genuinely new and gets its own file. Two files, two
`streamlit run` commands, two ports, one database.

**DG2 — G1 writes through a new `submission/dataops/` package, never raw SQL
and never the fabricator directly.** Three reasons: (a) the fabricator is
demo-scenario shaped (`age_snapshot`, `set_cover_days`) and lacks CRUD
entirely, so it has to be extended regardless; (b) validation belongs in one
place that both the screen and its tests can call, not scattered through
Streamlit callbacks; (c) a raw SQL box would bypass R7's duplicate guard, the
FK checks, the derived-table ban and the change log all at once. `dataops`
owns validation + writes, and delegates to `fabricator`/`tools` where a
function already exists rather than duplicating it.

**DG3 — derived tables are read-only in G1, and visibly labelled.**
Hand-editing a `sku_policy` row would put a number into the evidence chain
that no computation produced — exactly what R3 and R11 exist to prevent. To
change a derived value you edit its **inputs** and recompute. G1 shows derived
tables (they are useful to read) with an explicit "computed — edit the inputs
and recompute" banner and no write controls.

**DG4 — validation is one declarative spec per table, not per-screen code.**
A single `submission/dataops/spec.py` describes each input table: columns,
Python types, ranges, nullability, FK target, unique key, and a human-readable
label per column. The editor screen and the validator both read that spec, so
a rule cannot be enforced on one screen and forgotten on another, and adding a
column is a one-line spec change rather than a UI change.

**DG5 — the change log is persisted to a new `data_change_log` table.** The
in-memory `fabricator._LOG` cannot satisfy G1.3 ("a demo is explainable
afterwards") across a restart. New additive table via the existing
`migrate.py::_ADDITIVE_TABLES` mechanism: `change_id`, `changed_at`,
`changed_by`, `table_name`, `row_key`, `action`
(`CREATE`/`UPDATE`/`DELETE`/`BACKFILL`), `before_json`, `after_json`, `note`.
`fabricator._log` keeps working as-is (in-memory, for tests) and `dataops`
writes both — so nothing existing breaks and the durable record exists.

**DG6 — the watchlist ranks on each SKU's own derived target.** `scan_portfolio`
gains a per-SKU lookup of `sku_policy.derived_cover_days`, falling back to a
**clearly-labelled** "no policy yet" state rather than silently to 14. Its
`target_cover_days` parameter is kept for backward compatibility with existing
callers/tests but becomes an override-for-testing rather than the normal path.
This closes §1.2's first violation.

**DG7 — `_await_missing_info` stops accepting `target_cover_days`.** Removed
from the interrupt payload, from the apply block, from
`app.resume_missing_info`'s signature, and from `ui._render_missing_info_form`.
`resolve_target_cover` becomes the only route to a target, which is what R11
requires. This closes §1.2's second violation. **This is a behaviour change to
a shipped API** — flagged separately, not bundled silently, because
`test_phase9_needs_information_resume.py` very likely constructs that payload.

**DG8 — the pending queue branches on `target_mode`, not status.** So a
manual-cover pause routes to the cover-days form and a missing-fields pause
routes to the fields form, instead of both landing on whichever branch is
checked first.

**DG9 — G1.2's "data is in, re-run" starts a fresh run; it does not resume.**
A thin-data case terminates at `finalize_needs_information` — there is no live
checkpoint to resume. `run_case(sku, warehouse_id)` starts a new run against
the same stable `case_id`, and because `fetch_evidence` re-reads
`get_sales_velocity` from the database, the newly entered rows are what feed
the arithmetic. **This is the mechanism that makes R11 true rather than
aspirational**, and the test in §5 asserts exactly it.

**DG10 — neither console has authentication, and that must be stated.**
G2 today is read-plus-approve; **G1 will be able to write to every input
table**, including prices, budgets and stock levels. Both run unauthenticated
on localhost. That is acceptable for a local demo tool and is *not* acceptable
if either is ever bound to a non-loopback address. G1 must therefore: bind
localhost only in its documented run command, carry a visible "local demo
tool, no access control" banner, and be recorded as a known limitation in
`test_report.md`. Adding real auth is Phase H, but **silently shipping an
unauthenticated write surface is not an option** — the limitation gets stated.

---

## 3. Files this phase touches

```
NEW  submission/data_console.py          G1 entry point (streamlit run)
NEW  submission/dataops/__init__.py
NEW  submission/dataops/spec.py          declarative per-table column spec (DG4)
NEW  submission/dataops/validate.py      pure validation: spec + row -> [errors]
NEW  submission/dataops/write.py          create/update/delete per input table,
                                          delegating to fabricator/tools where a
                                          function exists; writes data_change_log
NEW  submission/dataops/read.py           generic paged table read + the
                                          derived-table read-only reads
NEW  submission/dataops/scenarios.py      apply a named scenario from
                                          fixtures/scenarios.json
NEW  submission/dataops/stats_panel.py    assemble the live statistics view for
                                          one sku/warehouse from
                                          submission.statistics + tools

MOD  database/schema.sql                  + data_change_log table (DG5)
MOD  database/migrate.py                  + one _ADDITIVE_TABLES entry (DG5)

MOD  fixtures/fabricator.py               + the missing CRUD primitives named in
                                          §1.3: create/delete product, vendor,
                                          vendor_offer; update a sales_daily row;
                                          set lifecycle / unit_volume_m3;
                                          deactivate a policy_rule
MOD  tools/policy_floors.py               + deactivate_policy_floor (or an
                                          `active` flag setter) -- confirm the
                                          exact current signature of
                                          set_policy_floor first

MOD  submission/portfolio.py              scan_portfolio -> per-SKU derived
                                          target (DG6); list_pending_cases ->
                                          expose target_mode (DG8)
MOD  submission/graph/workflow.py         _await_missing_info drops
                                          target_cover_days (DG7)
MOD  submission/app.py                    resume_missing_info drops
                                          target_cover_days (DG7)
MOD  submission/ui.py                     G2: missing-info form drops the cover
                                          slider (DG7); pending queue branches on
                                          target_mode (DG8); sweep controls +
                                          progress; park queue with deep links
                                          into G1.2; derived-target display

NEW  submission/tests/test_phase_g_data_console.py
NEW  submission/tests/test_phase_g_agent_console.py
NEW  docs/testing/phase_g_two_consoles.tdd.md   (written after implementation)
```

Nothing in `submission/graph/nodes.py`, `submission/graph/economics.py`,
`submission/statistics/`, `submission/sweep/`, `submission/agents/`, or
`domain/tool_models.py` changes — **except** `nodes.py` is untouched entirely,
and `workflow.py`'s only edit is DG7's payload removal. Phase G adds no graph
node, no route, no agent and no interrupt.

---

## 4. Task-by-task

### G1-1 — the table spec and the validator *(pure, no UI, no DB)*

Build `dataops/spec.py` + `dataops/validate.py` first, with tests, before any
screen exists. This is the piece everything else leans on.

Spec shape, one entry per input table:

```python
TABLE_SPECS = {
    "sales_daily": TableSpec(
        label="Daily sales",
        primary_key="sale_id",
        unique=("sale_date", "sku", "warehouse_id"),   # R7
        columns=[
            ColumnSpec("sale_date", date, label="Day", required=True, not_future=True),
            ColumnSpec("sku", str, required=True, fk=("products", "sku")),
            ColumnSpec("warehouse_id", str, required=True, fk=("warehouses", "warehouse_id")),
            ColumnSpec("units_sold", int, required=True, min_value=0),
        ],
    ),
    ...
}
```

Validation rules the validator must enforce (each returning a message naming
the field and the reason, never a bare "invalid"):

- [ ] required / nullable
- [ ] type coercion and rejection (a bool is not an int — Phase F's own
  `_await_manual_target_cover` already sets this precedent explicitly)
- [ ] numeric ranges: `on_hand >= 0`, `reserved >= 0`, `units_sold >= 0`,
  `0 <= on_time_rate <= 1`, `0 <= fill_rate <= 1`, `0 <= quality_score <= 1`,
  `unit_price > 0`, `moq >= 1`, `selling_price > 0`, `unit_volume_m3 > 0`,
  `storage_cost_per_m3_month >= 0`, budget amounts `>= 0`
- [ ] enums: `products.lifecycle` ∈ `NEW|GROWTH|MATURE|DECLINING|EOL`;
  `vendors.billing_basis` ∈ `ORDERED|SHIPPED`
- [ ] FK existence, naming the missing key: "vendor `VEN-99` does not exist"
- [ ] unique-key collision on `sales_daily`, surfaced as **"a row already
  exists for 2026-08-04 / AC-001 / DEL-01 — edit that row instead"**, never an
  `IntegrityError`
- [ ] date sanity: `valid_from <= valid_until`; `ordered_at <= promised_at`;
  `ordered_at <= received_at`; no future `sale_date`
- [ ] **warn, don't block:** `selling_price` below the cheapest landed cost
  (B10 already treats a negative contribution as a data error rather than a
  small number, so this must be visible — but it is a business judgement, not
  a schema violation, so the write is allowed with the warning recorded)
- [ ] delete guards: refuse to delete a `product`/`vendor`/`warehouse` that
  still has dependent rows, naming the count and the table
  ("3 `sales_daily` rows and 2 `vendor_offers` reference this")

**Run after this task:** `test_phase_g_data_console.py` (spec/validator
sections only). Nothing else — this task touches no existing code.

### G1-2 — the write layer and the durable change log

- [ ] `dataops/write.py` exposes `create_row`, `update_row`, `delete_row`
  per table name, each: validate → refuse-with-reasons **or** write →
  log to `data_change_log` with before/after JSON
- [ ] Delegates to existing functions where they exist
  (`fabricator.set_position`, `fabricator.backfill_missing_sales`,
  `tools.policy_floors.set_policy_floor`, `fabricator.upsert_warehouse`, …)
  and adds only the primitives §1.3 named as missing
- [ ] **All-or-nothing per row:** a rejected multi-field edit leaves the row
  byte-identical. Use a single transaction per row edit.
- [ ] Schema + migration for `data_change_log` (DG5), idempotent, verified by
  running `migrate.py` twice
- [ ] `changed_by` is required on every write — the screen collects an
  operator name once per session and passes it through. An unattributed
  database change is not acceptable in a system whose whole argument is
  auditability.

**Run after this task:** `test_phase_g_data_console.py` (write/log sections)
**plus** `test_phase_a_data_foundation.py` (it asserts the schema's table set,
so a new table is exactly the kind of thing that legitimately touches it —
confirm whether its assertion is `issubset` (tolerant) or an exact-set
comparison before assuming it passes).

### G1-3 — the generic table editor screen

- [ ] One screen, table picker at the top, driven entirely by `TABLE_SPECS`
- [ ] Paged read (`st.dataframe`), row select → edit form built from the spec
- [ ] Create / update / delete, each showing validation errors **on the field**
- [ ] Derived tables appear in the picker but render read-only with the
  "computed — edit the inputs and recompute" banner (DG3)
- [ ] Operator-name input in the sidebar, required before any write control
  enables (mirrors how Phase F's manual-cover form requires a name)
- [ ] The "local demo tool, no access control" banner (DG10)
- [ ] Theme-aware components only, no hardcoded colours (§1.3)

**Run after this task:** `test_phase_g_data_console.py` only. UI-shape
assertions should test the *spec-driven* helpers (which form fields a spec
produces, which controls are disabled) rather than Streamlit rendering, so
they stay fast and don't need `AppTest`.

### G1-4 — the missing-sales-data screen *(the R11-critical one)*

- [ ] Entered with `sku`, `warehouse_id`, `start_date`, `end_date` — the same
  four facts a `parked_items` record and `fetch_evidence`'s message already
  carry, so G2 can deep-link straight into it
- [ ] Day-by-day view of the range: existing rows shown with their units,
  gaps shown visibly empty, so "what is missing" is a picture
- [ ] Per-day entry, and a bulk fill for a selected span — both writing real
  `sales_daily` rows through `fabricator.backfill_missing_sales` (already
  additive-safe: it skips days that already exist rather than raising)
- [ ] Live readiness counter: observations now in the 7-day window and the
  30-day window, against the `>= 3` threshold each needs — so the operator can
  see the moment the case becomes runnable
- [ ] **"Data is in — re-run this case"** → `run_case(sku, warehouse_id)`
  (a fresh run, DG9), then link to the case in G2
- [ ] If a `parked_items` record is open for this pair, offer "resolve this
  park" → `tools.parking.resolve_park(park_id, resolved_by, resolution)`,
  which already requires both a name and a note

**Run after this task:** `test_phase_g_data_console.py` (backfill + re-fetch
section) **plus** `test_phase_e_insufficient_data_loop.py` (it owns the
park/backfill behaviour this screen drives).

### G1-5 — levers, scenario picker, live statistics

- [ ] Per-SKU levers on one screen: position, cover days, snapshot age, offer
  validity, vendor reliability, budget, selling price, unit volume, freight,
  billing basis, lifecycle — all existing fabricator functions, just given a UI
- [ ] Scenario picker reading `fixtures/scenarios.json` (12 acceptance
  scenarios + 14 `phase_a_scenarios`, confirmed present), one click to apply
- [ ] Policy-floor editor writing `policy_rules` via
  `tools.policy_floors.set_policy_floor`, **requiring a stated business reason
  and a `set_by` name** — a floor is an audited exception (A4/D15), so an
  unexplained floor is refused
- [ ] Freshness-threshold control
- [ ] Live statistics panel for the selected sku/warehouse: μ, σ, CV, ADI,
  quadrant, ABC/XYZ, **maturity + confidence** (which is what now decides
  whether a human is asked for cover days at all), service level, safety
  stock, reorder point, derived cover days, current position — recomputed
  after each edit so the effect of a change is immediately visible
- [ ] Change-log viewer over `data_change_log`, filterable, exportable

**Run after this task:** `test_phase_g_data_console.py` only.

### G2-1 — per-SKU derived targets on the watchlist (DG6, closes an R11 violation)

- [ ] `scan_portfolio` looks up each pair's `sku_policy.derived_cover_days`
- [ ] No policy row, or non-`ESTABLISHED` maturity → the row says so
  explicitly ("target not yet derived — needs classification" /
  "provisional maturity"), and **never silently uses 14**
- [ ] Keep the `target_cover_days` parameter as a test override; it stops
  being the normal path
- [ ] The row shows which target it was judged against, so two products with
  different targets are not silently compared on one number

**Run after this task:** `test_phase_g_agent_console.py` **plus**
`test_phase6_revision_and_ui_reads.py` and `test_phase10_pending_scan_cost.py`
(both read `portfolio`; confirm exact filenames still exist by listing the
test directory before running, per this plan's own don't-trust-stale-notes
rule).

### G2-2 — remove the second target route (DG7, closes the other R11 violation)

- [ ] `workflow._await_missing_info`: drop `target_cover_days` from the
  interrupt payload and from the apply block
- [ ] `app.resume_missing_info`: drop the parameter
- [ ] `ui._render_missing_info_form`: drop the slider
- [ ] **Before editing:** grep `submission/tests/` for
  `resume_missing_info`/`target_cover_days` in the missing-info payload —
  `test_phase9_needs_information_resume.py` almost certainly constructs it.
  Update those tests deliberately as part of this task.

**Run after this task:** `test_phase9_needs_information_resume.py` **plus**
`test_phase_f_manual_target_constraints.py` (it owns the "only one target
route" guarantee) **plus** `test_phase_g_agent_console.py`.

### G2-3 — sweep controls, queues, park queue, playback

- [ ] "Run monitor now" → `app.run_sweep(warehouse_id)`, with a spinner and
  per-candidate results as they land
- [ ] Sweep history from `tools.sweep_runs.get_sweep_history`, showing
  examined / candidates / parked / deferred / opened / reminders / estimated
  model calls, and the per-candidate `detail` rows
- [ ] Pending queue split by gate: `AWAITING_APPROVAL` (gate 1),
  `AWAITING_VENDOR_APPROVAL` (gate 2), and **`NEEDS_INFORMATION` split by
  `target_mode`** (DG8) — `MANUAL_COVER_REQUIRED` routes to the cover-days
  form, anything else to the fields form
- [ ] Park queue from `tools.parking.get_open_parked_items`, each row
  **deep-linking into G1-4** with the sku/warehouse/date-range from the park
  record, plus a resolve action
- [ ] Audit playback per case via `portfolio.read_case_history` (already
  exists and already renders — confirm no change needed)
- [ ] Derived-vs-human target shown on every case: `target_provenance` and
  `manual_cover_warning(values)` (both already exist from Phase F)

**Run after this task:** `test_phase_g_agent_console.py` **plus**
`test_phase_c_autonomous_sweep.py` (sweep reads) **plus**
`test_phase9_pending_queue.py` and `test_phase9_ui_deep_links.py` (queue and
deep-link behaviour — confirm both filenames before running).

---

## 5. New test files

Two files, mirroring the two apps. Both use the **`tmp_path` +
`object.__setattr__(config, "database_path", ...)`** isolation pattern from
`test_phase_c_autonomous_sweep.py` (not the process-level `DATABASE_PATH` env
var), so they never touch the live database.

### `test_phase_g_data_console.py`

1. `test_every_input_table_has_a_spec_and_no_derived_table_does` — the spec
   covers exactly the 10 input tables; the 6 derived ones are absent or marked
   read-only. A structural guard against a future schema addition silently
   becoming editable.
2. `test_validation_rejects_out_of_range_and_names_the_field`
3. `test_validation_rejects_a_bool_where_an_int_is_required`
4. `test_validation_rejects_a_missing_foreign_key_and_names_it`
5. `test_duplicate_sales_day_is_refused_with_an_edit_that_row_message` (R7)
6. `test_reversed_date_range_and_future_sale_date_are_refused`
7. `test_selling_price_below_landed_cost_warns_but_writes`
8. `test_deleting_a_referenced_product_is_refused_with_the_dependent_count`
9. `test_a_rejected_multi_field_edit_leaves_the_row_unchanged`
10. `test_every_write_records_a_data_change_log_row_with_before_and_after`
11. `test_a_write_without_an_operator_name_is_refused`
12. `test_derived_tables_expose_no_write_function`
13. `test_backfilling_the_named_range_then_rerunning_produces_a_proposal_from_the_new_rows`
    — **the R11 keystone test.** Seed a pair with too-thin history; run and
    confirm `NEEDS_INFORMATION` + a park row; backfill the exact named range
    through `dataops`; re-run via `run_case(sku, warehouse_id)`; assert the
    resulting proposal's `daily_velocity` matches what the **newly written
    `sales_daily` rows** imply — proving the number came from the database
    re-read, not from a form value.
14. `test_migration_is_idempotent_for_data_change_log`

### `test_phase_g_agent_console.py`

1. `test_watchlist_uses_each_skus_own_derived_target` — two SKUs with
   different `derived_cover_days` are judged against different targets, not
   both against 14.
2. `test_watchlist_never_silently_defaults_to_the_config_target` — a pair with
   no `sku_policy` row is labelled as such rather than assessed against 14.
3. `test_missing_info_resume_no_longer_accepts_a_cover_target` — the inverse
   guard for DG7 (`inspect.signature(resume_missing_info)` has no
   `target_cover_days`, and the interrupt payload omits it).
4. `test_resolve_target_cover_is_the_only_route_to_a_target` — structural:
   grep/AST the codebase for writes to `state["target_cover_days"]` and assert
   the only ones are in `resolve_target_cover` and
   `_await_manual_target_cover`. This is the single strongest R11 regression
   guard available and it is cheap.
5. `test_pending_queue_distinguishes_manual_cover_from_missing_fields` (DG8)
6. `test_pending_queue_distinguishes_gate_one_from_gate_two`
7. `test_park_queue_rows_carry_sku_warehouse_and_a_date_range` — the three
   facts G1-4's deep link needs.
8. `test_sweep_history_reads_back_what_run_sweep_recorded`

---

## 6. Testing — the exact commands

**Isolated database, every time:**

```powershell
$env:DATABASE_PATH = "$env:TEMP\inventra_test_phase_g_$([guid]::NewGuid()).db"
python -m pytest submission/tests/test_phase_g_data_console.py -q
Remove-Item $env:DATABASE_PATH -ErrorAction SilentlyContinue
```

**Per-task, run only what §4 names.** Summary:

| Task | Run only |
|---|---|
| G1-1 spec/validator | `test_phase_g_data_console.py` |
| G1-2 writes + log | `test_phase_g_data_console.py`, `test_phase_a_data_foundation.py` |
| G1-3 editor screen | `test_phase_g_data_console.py` |
| G1-4 missing-sales screen | `test_phase_g_data_console.py`, `test_phase_e_insufficient_data_loop.py` |
| G1-5 levers/scenarios/stats | `test_phase_g_data_console.py` |
| G2-1 derived targets | `test_phase_g_agent_console.py`, `test_phase6_revision_and_ui_reads.py`, `test_phase10_pending_scan_cost.py` |
| G2-2 drop second target route | `test_phase9_needs_information_resume.py`, `test_phase_f_manual_target_constraints.py`, `test_phase_g_agent_console.py` |
| G2-3 queues + sweep | `test_phase_g_agent_console.py`, `test_phase_c_autonomous_sweep.py`, `test_phase9_pending_queue.py`, `test_phase9_ui_deep_links.py` |

**Confirm each filename still exists before running it.** This session found
`PHASE_E1_PLAN.md`/`PHASE_F_PLAN.md` already stale and a new `tools/workflow.py`
that no earlier note mentioned — file names in this plan are accurate as of
this session and may not be later.

**Manual smoke test** (no pytest substitute exists for "does the screen
work"), both bound to localhost only:

```powershell
streamlit run submission/ui.py --server.port 8501 --server.address 127.0.0.1
streamlit run submission/data_console.py --server.port 8502 --server.address 127.0.0.1
```

**The one-time final gate — only when the user explicitly asks:**

```powershell
$env:DATABASE_PATH = "$env:TEMP\inventra_phase_g_final_$([guid]::NewGuid()).db"
python -m pytest submission/tests/test_phase_a_data_foundation.py `
                 submission/tests/test_phase_b_statistics_and_policy_engine.py `
                 submission/tests/test_phase_c_autonomous_sweep.py `
                 submission/tests/test_phase_c2_policy_floor_reconciliation.py `
                 submission/tests/test_phase_d_two_gate_approval.py `
                 submission/tests/test_phase_e_insufficient_data_loop.py `
                 submission/tests/test_phase_f_manual_target_constraints.py `
                 submission/tests/test_phase_g_data_console.py `
                 submission/tests/test_phase_g_agent_console.py -q
Remove-Item $env:DATABASE_PATH -ErrorAction SilentlyContinue
```

Still not the whole suite — the seven phase-lettered files plus this phase's
two.

---

## 7. Out of scope for Phase G

- **Authentication / access control on either console.** DG10 — the limitation
  gets *documented*, not solved. Phase H.
- **Visual polish, responsive layout, any non-Streamlit frontend.** Phase H.
- **Editing derived tables.** DG3, permanently — not deferred, refused.
- **A raw SQL console.** DG2 — it would bypass every guard at once.
- **Any graph, agent, node, route or interrupt change**, other than DG7's
  payload removal from `_await_missing_info`.
- **A background scheduler for sweeps or reminders.** Phase H, unchanged.
- **`roll_forward()`** (deferred from Phase A) — a scenario-picker entry is
  not a substitute and this plan does not add it.
- **Fixing or removing `tools/workflow.py`.** §1.4 — unused legacy; leave it.
- **Multi-user concurrent editing.** SQLite plus two Streamlit processes will
  occasionally collide on a write lock; G1 should surface such an error
  readably, but proper concurrency is not designed here.

---

## 8. Open questions

- **Does `test_phase_a_data_foundation.py` assert the schema's table set as an
  exact match or an `issubset`?** If exact, DG5's new `data_change_log` table
  breaks it and that test must be updated as part of G1-2. Check before
  writing the migration, not after.
- **Should G1 be able to create a brand-new product** (a SKU that does not
  exist yet)? This plan says yes — it is an input table and R11's "enter it
  into the relevant table" reads naturally as including "the product row
  itself". But it is the one CRUD operation with no precedent anywhere in the
  codebase, and `PHASE_F_PLAN.md` §7 explicitly put it out of scope. Confirm.
- **Where does the operator name come from?** This plan uses a per-session
  sidebar input, consistent with how Phase F's manual-cover form asks for a
  name. If something closer to real identity is wanted, that is auth (DG10) and
  therefore Phase H.
- **Should the freshness-threshold control in G1-5 write anything durable?**
  `config.data_freshness_hours` is read from an env var at construction, so a
  UI control can only affect the running process. Options: session-only
  (simplest, and what this plan assumes), or promote it to a settings table.
  Flagged rather than decided.
- **Should `scan_portfolio` refuse to assess a pair with no `sku_policy` row
  at all**, rather than showing it with a "not yet derived" label? Refusing is
  more R11-pure; labelling is more useful to an operator who needs to know the
  product exists. This plan chooses labelling.
- Carried forward, out of scope here: **O1-O5**, **DB1-DB5**, and the open
  questions in `PHASE_C_PLAN.md`/`PHASE_D_PLAN.md`/`PHASE_E_PLAN.md` §9.

---

## 9. Exit criteria

- [ ] Two apps run on separate ports against one database, both bound to
  localhost, both carrying the no-access-control banner
- [ ] Every one of the 10 input tables is creatable, editable and deletable
  from G1, with validation that names the field and the reason
- [ ] All 6 derived tables are visible and have no write control anywhere
- [ ] An invalid edit — bad type, bool-for-int, missing FK, duplicate
  `sales_daily` day, reversed date range, future sale date — is refused with a
  specific readable message and leaves the row byte-identical
- [ ] Deleting a referenced product/vendor/warehouse is refused, naming the
  dependent count
- [ ] Every write appears in `data_change_log` with an operator name and
  before/after values, and survives a process restart
- [ ] **The full R11 loop runs with no terminal:** a thin-data SKU parks in
  G2's queue → deep-link to G1's missing-sales screen → the missing range is
  visible day by day → real rows are entered → the readiness counter clears →
  re-run from that screen → a proposal appears in G2 whose `daily_velocity`
  demonstrably came from the rows just written
- [ ] No screen anywhere offers a demand rate, target units, or an order
  quantity
- [ ] The **only** cover-days input in the entire product appears when
  `target_mode == "MANUAL_COVER_REQUIRED"`, and is recorded against a named
  person — proven structurally by
  `test_resolve_target_cover_is_the_only_route_to_a_target`
- [ ] The watchlist judges each SKU against its own derived target and never
  silently falls back to `config.target_cover_default_days`
- [ ] Both approval gates and the park queue are workable end to end from G2
- [ ] Sweep run, progress and history are all visible in G2
