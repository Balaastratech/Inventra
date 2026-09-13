# PHASE_F_PLAN.md

> **Superseded implementation note — 2026-09-12.** The velocity-override
> design below (DF1, DF3, DF7, and DF8) is void under `AUTONOMOUS_PLAN.md`
> R11 and tracker Entry 022. Missing sales evidence must be entered into
> `sales_daily` and re-fetched through Phase E; no form or CLI accepts a
> human demand rate, quantity, or target for an established SKU. The only
> valid Phase F manual input is whole-number cover days for an immature SKU
> with usable sales velocity, recorded against a named person. The live
> implementation and evidence are in
> `submission/tests/test_phase_f_manual_target_constraints.py` and
> `docs/testing/phase_f_manual_target_constraints.tdd.md`.

Detailed, end-to-end execution plan for **Phase F — Manual order path**
(`AUTONOMOUS_PLAN.md` §Phase F), against the codebase as it actually exists
today with Phases A, B, C, C2, D, and E all implemented and verified live
this session (see §0 and §1).

No file named `AUTOMATION.md` exists in this workspace (confirmed again this
session by `file_search`, zero results — same non-finding every prior
`PHASE_*_PLAN.md` has recorded). `AUTONOMOUS_PLAN.md` is the source plan.

**This is a planning document. Nothing described here has been built.**

**Testing instruction, carried forward from every prior phase plan, because
the user has repeated it across sessions:** do not run the full test suite
(`python -m pytest submission/tests -q`) as a routine step while
implementing Phase F. §7 names the exact narrow test file/command to run
after each task; the full suite is a one-time final gate, only when
explicitly requested.

---

## 0. Re-verification: are Phases D and E actually built? (the user's direct question this session)

Before touching Phase F, the user asked to re-check whether Phase D
(two-gate approval) and Phase E (insufficient-data loop) — both flagged in
Entries 018/019 as "implemented but with no tracker entry logging it" — are
genuinely in the code, since code can change between sessions. Direct reads
this session confirm **both are still fully live**, unchanged in shape from
what Entries 018/019 described:

- **Phase D (two-gate approval):** `submission/graph/nodes.py` has
  `request_vendor_approval`, `handle_vendor_decision`,
  `finalize_vendor_cancelled`; `domain/tool_models.py` has
  `VendorSendDecision` with its `ProposalStatus.AWAITING_VENDOR_APPROVAL`/
  `PURCHASE_REQUEST_CANCELLED` values; `submission/app.py` has
  `resume_vendor_send` and the `approve-vendor-send`/`reject-vendor-send`
  CLI commands. Confirmed by direct read, not by trusting the prior entry.
- **Phase E (insufficient-data loop):** `submission/graph/routes.py::route_after_evidence`
  now has the `"needs_information"` branch (confirmed exact current body,
  quoted in §1); `submission/graph/nodes.py::fetch_evidence` builds the
  exact-deficit message and calls `tools.parking.park_item(...,
  "INSUFFICIENT_SALES_HISTORY", ...)`; `fixtures/fabricator.py::backfill_missing_sales`
  exists; `submission/sweep/candidates.py` has the `ALREADY_PARKED` exclusion
  reading `tools.parking.get_open_parked_items`. `apply_window_choice`,
  `_await_window_choice`, and `route_after_window_choice` are confirmed
  **absent** — a repo-wide grep for each found zero matches.
  `docs/testing/phase_e_insufficient_data_loop.tdd.md` exists and records
  8 passing tests, matching `PHASE_E_PLAN.md`'s own test-file design almost
  exactly (slightly different test names than the plan proposed, same
  guarantees covered).

**Conclusion: both phases are genuinely built, not just planned.** The
tracker gap (no logged entry for who built them or when) remains
unresolved, but that is a process question, not a code question, and does
not block Phase F. This document proceeds on the assumption that Phase F is
the next real gap — confirmed in §1 below.

---

## 1. Ground truth: the codebase Phase F actually builds on

Verified this session by direct reads of `submission/app.py` (full),
`submission/state/state.py` (full — `CaseState`, `create_initial_state`),
`submission/graph/nodes.py` (`validate_request`, `check_product`,
`fetch_evidence`, `compute_risk`, `fetch_budget_and_policy`,
`draft_proposal`, `apply_human_edit`, `execute_purchase` regions),
`submission/graph/routes.py` (full), `submission/graph/support.py`
(`TargetReconciliation`/`reconcile_target`, full), `submission/graph/economics.py`
(`size_order_quantity`'s docstring and signature), `submission/portfolio.py`
(`scan_portfolio`, `_stocked_pairs`, full), `submission/ui.py` (the sidebar
target slider, `screen_watchlist`, `screen_investigate`, `screen_case`
dispatch region), `submission/config.py` (`target_cover_default_days`/
`target_cover_min_days`/`target_cover_max_days`), `domain/tool_models.py`
(`ProductRecord`, `ReplenishmentProposal`'s `target_provenance`/`target_basis`
fields, `SkuPolicy`), `tools/inventory.py` (`get_product`, `get_stock_position`,
`calculate_stock_risk`, full), `tools/classification.py` (full),
`tools/policy_floors.py` (`get_active_policy_floor`'s signature), and
`DECISIONS.md` D23 (the manual-order decision record).

| Fact | Detail |
|---|---|
| **A manual order path already exists in a real, working form** — `app.py run <sku> <warehouse> [target_cover_days]` / `submission.ui`'s "Look into this" button, both calling `run_case`/`create_initial_state`. This is **not** the gap. What's missing is specifically the **override of `INSUFFICIENT_DATA`**, the **`target_provenance="human:<name>"` stamping**, and the **explicit approval-card warning** D23 describes. | `submission/app.py::run_case`, `submission/state/state.py::create_initial_state` |
| **`create_initial_state` takes `target_cover_days` but never an approver/requester name.** No parameter exists for "who is manually ordering this and why." `target_provenance` is hardcoded to `"derived"` in every call site. | `submission/state/state.py` lines ~143-183 |
| **`fetch_evidence`'s `INSUFFICIENT_DATA` path (Phase E) has no override hook.** It always returns `NEEDS_INFORMATION` and parks the item — there is no state flag that says "a human already supplied the demand assumption, proceed anyway." Confirmed by reading the full function body this session (quoted in §0). | `submission/graph/nodes.py::fetch_evidence` |
| **`compute_risk` reads `sales.window_7_days`/`window_30_days` directly** (`velocity = sales.window_7_days if ... else sales.window_30_days`) — if `fetch_evidence` is made to proceed past `INSUFFICIENT_DATA`, `sales` still has `window_7_days=0, window_30_days=0` (per `tools/sales.py`'s own `SalesVelocity` construction on the insufficient-data path), so `compute_risk` would compute a velocity of exactly `0`. `calculate_stock_risk` explicitly handles `daily_velocity <= 0` by returning `cover_days=None` rather than inventing a number (confirmed: "Zero observed demand has no finite days-of-cover meaning. Do not invent a velocity floor") — so a manual order past insufficient data would compute `at_risk=False` (since `route_after_risk` treats `risk is None` as blocked, but a valid `StockRisk` with `cover_days=None` and `available_units` still populated needs its own read — flagged as a design question in §2, not assumed either way). **This is the single most important technical finding this session**: simply "let it past `fetch_evidence`" is not sufficient on its own, because the entire rest of the graph (`compute_risk`, `build_options`'s sizing via `size_order_quantity`) depends on a real velocity number, and a manual order with zero sales history has no velocity to give it. D23's own text says "the human has supplied the demand assumption the data could not" — meaning **the human must supply a velocity number, or an equivalent (a target quantity), not just permission to skip the check.** |
| **`size_order_quantity` sizes strictly from `daily_velocity`** (`required_quantity(available_units, daily_velocity, target_cover_days, lead_time_days, fill_rate)`) — confirmed by reading its docstring and signature. A velocity of `0` sizes an order of `0` (or just the MOQ floor), which defeats the entire purpose of a manual order for a brand-new product that a human wants stock of. This reinforces the finding above: the override needs an actual number, not a bypass flag. |
| **`ReplenishmentProposal` already has `target_provenance: str = "derived"` and `target_basis: str = "STATISTICAL"` fields**, wired through `draft_proposal` from `state.get("target_provenance", "derived")` — this is exactly the field D23/Phase C2 already plumbed for the floor-reconciliation feature. Phase F reuses it; it does **not** need a new field. Confirmed: `nodes.py` line ~559 reads `target_provenance=state.get("target_provenance", "derived")`. | `domain/tool_models.py`, `submission/graph/nodes.py::draft_proposal` |
| **`ui._approval_notes`/the approval screen do not currently render `target_provenance`** anywhere a human-supplied override would be visible as a warning — a grep for `target_provenance` in `ui.py` found only one read, in a different context (the target-basis reconciliation display at line ~692, which shows `target_basis`/`target_provenance` together but as a factual footer, not as a blunt warning banner). D23 requires the approval card to "state plainly" the gap — this needs new, dedicated rendering, not just reuse of the existing footer line. |
| **Policy floors already apply universally** — `fetch_budget_and_policy` calls `get_active_policy_floor(state["sku"], state["warehouse_id"])` unconditionally, with no manual/autonomous distinction. D23's "policy floors still apply to manual orders" requirement is **already satisfied by the existing code, with zero changes needed.** |
| **No CLI/UI surface exists for entering a manual order with a supplied demand assumption.** `app.py run` takes `target_cover_days` (a *duration*), not a *velocity* or *quantity* — there is no parameter anywhere for "assume N units/day" or "I want exactly Q units". |
| **No audit trail field exists for "who requested this manual override and why."** `emit_audit` calls throughout `nodes.py` take a free-text actor string (e.g. `f"human:{decision.approver}"` is the existing convention from Phase C2's `apply_human_edit`) — Phase F should follow that exact convention, not invent a new one. |

---

## 2. Design decisions this plan makes explicit (confirm before coding)

**DF1 — A manual order supplies an assumed daily velocity, not just a
"skip the check" flag.** Per §1's central finding: `compute_risk` and
`size_order_quantity` both need a real number to do anything useful. The
CLI/UI collects **"how many units per day do you expect this to sell?"**
alongside the existing "how many days of cover" question — this is the
"demand assumption the data could not [supply]" D23 refers to literally,
not metaphorically. Internally this becomes an **assumed `SalesVelocity`**
object (same Pydantic model `tools.sales.get_sales_velocity` already
returns, just constructed by hand instead of computed from `sales_daily`
rows), with `observation_count_7=0, observation_count_30=0` preserved
honestly (so nothing downstream is tricked into thinking real history
exists) and a new marker so the rest of the graph — and the approval card —
know this number came from a human, not from data.

**DF2 — The marker lives on `CaseState`, as a single new field
(`demand_override: Optional[dict]`, or a small frozen dataclass mirroring
`TargetReconciliation`'s shape), not by overloading `SalesVelocity` itself
with a new flag.** `SalesVelocity` is a `domain/tool_models.py` model shared
with every non-manual case; adding a manual-only field to it would leak a
Phase-F-specific concept into a model every other phase already depends on.
A new, small `CaseState` field is additive and invisible to every existing
code path that doesn't set it (mirrors how Phase C2 added
`target_reconciliation`/`policy_floor`/`target_provenance` to `CaseState`
without touching any model those fields didn't apply to).

**DF3 — `fetch_evidence` checks for the override *before* calling
`get_sales_velocity`, not after.** If a manual override is present, skip
the real sales read entirely and construct the assumed `SalesVelocity`
directly — this avoids a wasted DB read and, more importantly, avoids ever
calling `park_item(...)` (Phase E's insufficient-data park) for a case the
human has already explicitly taken responsibility for. A manually-overridden
case must never appear in the park queue.

**DF4 — `create_initial_state` gains two new optional parameters:
`requested_by: Optional[str]` and `demand_override_units_per_day: Optional[float]`.**
`target_provenance` is derived from whether `requested_by` is set
(`f"human:{requested_by}"` if set, else `"derived"`, exactly matching the
existing convention `apply_human_edit` already uses at Phase C2 — no new
provenance string format invented). `demand_override_units_per_day` is
threaded into a new `CaseState["demand_override"]` field, per DF2.

**DF5 — The override is a manual-run-only concept; the autonomous sweep
never sets it.** `submission/sweep/run.py::execute_candidate` calls
`create_initial_state` with `sku_policy_snapshot` from real, measured
statistics — it has no reason to ever pass `demand_override_units_per_day`,
and this plan does not add any code path for the sweep to do so. Enforced
by construction (the sweep's call site is simply never touched), not by a
runtime guard — there is nothing to guard against if the capability is
never wired to that caller.

**DF6 — The approval-card warning is a new, dedicated rendering block in
`submission/ui.py`, checked first, ahead of the existing target-basis
footer.** Per §1's finding that the existing `target_provenance` render is a
factual footer, not a warning: add a `st.warning(...)` block (matching the
visual weight `_render_missing_info_form`/`_render_window_choice_form`
already use for other "this needs your attention" states) at the top of
`_render_approval`, active whenever `values.get("target_provenance", "derived").startswith("human:")`
**and** `values.get("demand_override")` is truthy — the second condition
specifically distinguishes "a human picked a different eligible supplier"
(Phase C2's own use of a `human:` provenance-adjacent concept, via
`apply_human_edit`, which is a *different* feature and must not accidentally
trigger this new warning) from "a human supplied the demand number itself."
Confirm this distinction is correct against the exact current provenance
strings at implementation time — flagged, not assumed, since both features
now share the `human:<name>` string shape.

**DF7 — CLI surface: extend `app.py run`, not a new command.** Add two new
optional trailing arguments, `requested_by` and
`demand_override_units_per_day` — e.g.
`python -m submission.app run AC-NEW DEL-01 14 "Yuvraj" 5.0` — rather than a
separate `run-manual` command, since the only difference is two optional
parameters and the existing command already threads `target_cover_days`
through identically. Mirrors how `resume_case` already grew optional
trailing parameters (`edited_offer_id`, `chosen_target_basis`) for Phase
C2/D instead of forking into new functions.

**DF8 — UI surface: a new, explicit "Order this manually" entry point,
separate from "Look into this."** Per D23/`AUTONOMOUS_PLAN.md`'s own R5
("no per-product human input... the only exception is an explicit manual
order... [which] record[s] who set them and why") — this must be a
deliberate, separate action a human chooses, never a silent fallback when
"Look into this" happens to hit `INSUFFICIENT_DATA`. Concretely: the
watchlist row that today shows "Too few recent sales to predict demand" with
`can_investigate=True` (confirmed in `portfolio.scan_portfolio`, §1) gains a
second button, "Order manually instead," which routes to a small new form
(name, assumed units/day, days of cover) before calling `run_case` with the
override — the existing "Look into this" button is unchanged and still
runs the normal, data-driven path (which will still park it, per Phase E,
exactly as today).

---

## 3. New / modified files this phase touches

```
submission/state/state.py       MODIFIED —
                                 - CaseState gains: demand_override:
                                   Optional[dict] (or a small frozen
                                   dataclass -- confirm shape at
                                   implementation time per DF2)
                                 - create_initial_state gains two new
                                   optional params: requested_by,
                                   demand_override_units_per_day
                                 - target_provenance derivation:
                                   f"human:{requested_by}" if requested_by
                                   else "derived"

submission/graph/nodes.py       MODIFIED —
                                 - fetch_evidence: check state.get(
                                   "demand_override") BEFORE calling
                                   get_sales_velocity; if present, construct
                                   an assumed SalesVelocity by hand
                                   (observation_count_7=0,
                                   observation_count_30=0, window_7_days=
                                   window_30_days=demand_override["units_per_day"],
                                   error=None) and skip the park_item call
                                   entirely (DF3)
                                 - emit_audit gains a new event type
                                   ("demand_override_applied") when this
                                   path is taken, following the existing
                                   f"human:{name}" actor convention

submission/app.py               MODIFIED —
                                 - run_case gains two new optional trailing
                                   parameters (requested_by,
                                   demand_override_units_per_day), passed
                                   straight through to create_initial_state
                                 - main()'s "run" command branch parses two
                                   new optional positional args

submission/ui.py                MODIFIED —
                                 - screen_watchlist: the INSUFFICIENT_DATA
                                   row (can_investigate=True, "Too few
                                   recent sales...") gains a second button,
                                   "Order manually instead"
                                 - NEW: _render_manual_order_form(sku,
                                   warehouse_id) -- collects requested_by,
                                   assumed units/day, target_cover_days;
                                   calls run_case with the override; routes
                                   to screen_case on success (mirrors
                                   screen_investigate's existing shape)
                                 - _render_approval: NEW warning block at
                                   the top, gated per DF6, rendered before
                                   the existing proposal summary

submission/tests/test_phase_f_manual_order_path.py
                                 NEW — the phase's own dedicated test file

docs/testing/phase_f_manual_order_path.tdd.md
                                 NEW (write only after implementation, as
                                 RED/GREEN evidence -- matching the
                                 established convention in docs/testing/)
```

Nothing in `database/schema.sql`, `database/migrate.py`,
`submission/graph/routes.py`, `submission/graph/workflow.py`,
`submission/graph/economics.py`, `submission/sweep/`, or
`domain/tool_models.py` changes in this phase — no schema change, no new
graph node, no new interrupt, no new Pydantic model. This is a smaller
phase than D or E in terms of graph-shape risk; the risk is entirely in
getting `compute_risk`/`size_order_quantity`'s velocity dependency right
(§1's central finding), not in wiring new nodes.

---

## 4. Task-by-task plan

### Task 1 — `CaseState`'s new field + `create_initial_state`'s new parameters (DF2, DF4)

```python
# submission/state/state.py

class CaseState(TypedDict, total=False):
    ...
    # --- Manual order override (Phase F) ---
    demand_override: Optional[dict]  # {"units_per_day": float, "set_by": str} or None
    ...

def create_initial_state(
    sku: str,
    warehouse_id: str,
    target_cover_days: Optional[int] = None,
    budget_month: Optional[str] = None,
    sku_policy_snapshot: Optional[SkuPolicy] = None,
    requested_by: Optional[str] = None,
    demand_override_units_per_day: Optional[float] = None,
) -> CaseState:
    ...
    demand_override = (
        {"units_per_day": demand_override_units_per_day, "set_by": requested_by}
        if demand_override_units_per_day is not None else None
    )
    return CaseState(
        ...
        target_provenance=f"human:{requested_by}" if requested_by else "derived",
        demand_override=demand_override,
        ...
    )
```

Note: `requested_by` alone (no override number) is legal — this is the
ordinary "a human clicked Look into this" path, which already sets
`target_provenance` implicitly to `"derived"` today and should **not**
change behavior. Only set `target_provenance` to `human:<name>` when
`requested_by` is actually supplied — confirm no existing caller passes an
empty string that would accidentally trigger this (grep `create_initial_state(`
call sites before finalizing: `app.py::run_case`, `submission/ui.py`'s
`screen_investigate`, `submission/sweep/run.py::execute_candidate` are the
three known callers, per this session's own reads; none currently pass a
`requested_by` argument, so this is purely additive to all three by
default).

### Task 2 — `fetch_evidence`'s override branch (DF1, DF3)

```python
# submission/graph/nodes.py, fetch_evidence, inserted BEFORE the
# `sales = get_sales_velocity(...)` call

override = state.get("demand_override")
if override is not None:
    from domain.tool_models import SalesVelocity
    units = float(override["units_per_day"])
    sales = SalesVelocity(
        sku=state["sku"], warehouse_id=state["warehouse_id"],
        window_7_days=units, window_30_days=units,
        observation_count_7=0, observation_count_30=0,
        evidence_id=f"manual-override:{override.get('set_by', 'unknown')}",
        retrieved_at=datetime.utcnow(), error=None,
    )
    state["sales"] = sales
    emit_audit(state, f"human:{override.get('set_by', 'unknown')}", "demand_override_applied",
                {"units_per_day": units})
    emit_audit(state, "system", "evidence_gathered",
                {"stock_evidence_id": stock.evidence_id, "sales_evidence_id": sales.evidence_id})
    return state

sales = get_sales_velocity(state["sku"], state["warehouse_id"])
# ... existing code, unchanged
```

Placed after the existing stock-fetch and freshness-gate checks (both still
apply to a manual order — a manual order does not bypass `DATA_STALE`,
only `INSUFFICIENT_DATA`, since a stale snapshot is a different, unrelated
fact the human cannot supply an assumption for). Confirm this ordering
against the exact current function body at implementation time — this
session read it in full (quoted in §0/§1) and the insertion point described
here is the point immediately before the existing `sales =
get_sales_velocity(...)` line.

### Task 3 — CLI surface (DF7)

```python
# submission/app.py

def run_case(
    sku: str, warehouse_id: str, target_cover_days: int | None = None,
    requested_by: str | None = None, demand_override_units_per_day: float | None = None,
) -> dict:
    wire_agents()
    graph, conn = compile_graph()
    try:
        state = create_initial_state(
            sku, warehouse_id, target_cover_days,
            requested_by=requested_by,
            demand_override_units_per_day=demand_override_units_per_day,
        )
        ...  # unchanged

# main(), "run" branch:
elif command == "run":
    sku, warehouse_id = sys.argv[2], sys.argv[3]
    cover = int(sys.argv[4]) if len(sys.argv) > 4 else None
    requested_by = sys.argv[5] if len(sys.argv) > 5 else None
    override_units = float(sys.argv[6]) if len(sys.argv) > 6 else None
    _print_result(run_case(sku, warehouse_id, cover, requested_by, override_units))
```

Update the module docstring's usage block to document the two new optional
positional args, matching the existing convention (every other command's
usage line is already documented there).

### Task 4 — UI surface (DF8, DF6)

```python
# submission/ui.py, inside screen_watchlist's per-row rendering, where the
# existing "Look into this" button is built:

with right:
    if row.can_investigate:
        if st.button("Look into this", ...):
            _goto("investigate", sku=row.sku, warehouse_id=row.warehouse_id)
        # NEW: only offer this for the specific case Portfolio flags as
        # thin-data (matches the existing headline text this session
        # confirmed in portfolio.py: "Too few recent sales to predict
        # demand..."), not for every investigable row -- a healthy or
        # at-risk product with real history has no missing assumption for
        # a human to supply.
        if "Too few recent sales" in (row.headline or ""):
            if st.button("Order manually instead", key=f"manual-{row.sku}-{row.warehouse_id}"):
                _goto("manual_order", sku=row.sku, warehouse_id=row.warehouse_id)
    ...

# NEW screen:
def screen_manual_order() -> None:
    sku = st.session_state.get("sku")
    warehouse_id = st.session_state.get("warehouse_id")
    if not sku or not warehouse_id:
        _goto("watchlist"); return
    st.title(f"Order {sku} at {warehouse_id} manually")
    st.warning(
        "There is not enough sales history for this product to forecast demand. "
        "Supply your own assumption and the system will still handle vendor "
        "selection, economics and policy review for you."
    )
    requested_by = st.text_input("Your name")
    units_per_day = st.number_input("Assumed units sold per day", min_value=0.1, step=0.1)
    target = st.slider("How many days of stock should we aim to hold?",
                        min_value=config.target_cover_min_days, max_value=config.target_cover_max_days,
                        value=config.target_cover_default_days)
    if st.button("Run this order", type="primary", disabled=not requested_by.strip()):
        with st.spinner("Working through the case…"):
            result = run_case(sku, warehouse_id, target, requested_by.strip(), float(units_per_day))
        _goto("case", case_id=result.get("case_id"), thread_id=result.get("thread_id"))

# VIEWS dict gains: "manual_order": screen_manual_order
```

```python
# _render_approval, new block at the very top:
def _render_approval(case_id, values):
    override = values.get("demand_override")
    provenance = values.get("target_provenance") or values.get("proposal") and values["proposal"].target_provenance
    if override and str(provenance or "").startswith("human:"):
        st.warning(
            f"There is not enough sales history for this product; the demand assumption "
            f"({override['units_per_day']:g} units/day) and the cover target were set by "
            f"{override.get('set_by', 'a human')}, not derived from data."
        )
    ...  # existing rendering, unchanged
```

---

## 5. New test file — `submission/tests/test_phase_f_manual_order_path.py`

Sections, matching the established per-phase test file convention:

1. **`test_manual_order_sets_human_provenance`** — `create_initial_state`
   with `requested_by="Yuvraj"`; assert `state["target_provenance"] ==
   "human:Yuvraj"` and `state["demand_override"] is None` (no override
   number supplied — provenance can be set independently of the velocity
   override, per Task 1's note).
2. **`test_ordinary_run_case_unaffected`** — `create_initial_state` with no
   new parameters; assert `target_provenance == "derived"` and
   `demand_override is None` — the backward-compatibility check every prior
   phase plan has included for its own new optional parameter.
3. **`test_fetch_evidence_skips_the_real_sales_read_when_overridden`** —
   direct `nodes.fetch_evidence` call with `state["demand_override"] =
   {"units_per_day": 5.0, "set_by": "Yuvraj"}`; mock `get_sales_velocity` to
   raise if called (proving it's genuinely skipped, not just ignored) and
   `get_stock_position` to return a normal fixture; assert `state["sales"].window_7_days
   == 5.0` and `state["sales"].error is None`.
4. **`test_fetch_evidence_override_never_parks`** — same fixture, run
   through a full case; assert no `parked_items` row is created for this
   sku/warehouse (isolated-DB test, following the `tmp_path` +
   `object.__setattr__(config, "database_path", ...)` pattern from
   `test_phase_c_autonomous_sweep.py`).
5. **`test_end_to_end_manual_order_for_a_brand_new_sku_reaches_a_proposal`**
   — compiled graph, a genuinely zero-history SKU/warehouse pair (insert a
   product + a single inventory snapshot, no `sales_daily` rows at all),
   `run_case(sku, wh, 14, "Yuvraj", 5.0)`; assert the case reaches
   `AWAITING_APPROVAL` (`"__interrupt__" in result`) rather than
   `NEEDS_INFORMATION` — proving the override actually lets a no-history
   product reach a real proposal, which is Phase F's core deliverable.
6. **`test_the_sized_order_uses_the_assumed_velocity_not_zero`** — same
   fixture, inspect the resulting proposal's `quantity`/`daily_velocity`
   fields; assert `daily_velocity == 5.0` (not `0`) and `quantity > 0` —
   directly proving §1's central finding is actually fixed, not just that
   the case avoids `NEEDS_INFORMATION`.
7. **`test_policy_floor_still_applies_to_a_manual_order`** — same fixture,
   but with an active `policy_rules` floor row for this sku/warehouse set
   above what 5.0 units/day would otherwise size; assert the resulting
   proposal's `active_target_units`/`target_basis` reflect the floor,
   proving D23's "policy floors still apply" requirement (already true by
   construction per §1, but worth a regression test since this is exactly
   the kind of "already works, prove it doesn't regress" case this
   project's own test-writing convention favors).
8. **`test_approval_card_shows_the_override_warning`** — drive the same
   end-to-end case to the approval interrupt, then call `ui._render_approval`
   -- style test (or, if that function is hard to unit-test directly per its
   existing Streamlit coupling, assert on the underlying data
   (`values["demand_override"]`, `values["target_provenance"]`) being
   present and correctly shaped for the render function to use, mirroring
   how `test_phase6_revision_and_ui_reads.py` already tests UI-adjacent
   logic without a full Streamlit `AppTest` where avoidable).
9. **`test_sweep_never_sets_a_demand_override`** — read
   `submission/sweep/run.py::execute_candidate`'s call to
   `create_initial_state` and assert (via `inspect.signature` or a direct
   source grep within the test, matching the style of
   `test_phase10_demand_clarification_resume.py`'s own "assert an attribute
   doesn't exist" tests) that it never passes `requested_by`/
   `demand_override_units_per_day` — a structural regression guard for DF5,
   since there is no runtime check to test otherwise (by design, per DF5).

---

## 6. Testing — exactly what to run, and what NOT to run

**Do not run the full suite as a routine step in this phase.** Phase F
touches `fetch_evidence` (shared with every case, including Phase E's own
tests) and `create_initial_state` (called by every case-creation path,
including the sweep) — so, like every prior phase, treat the full suite as
a one-time final gate only.

**The exact mechanism** (unchanged from Phases C/D/E):

```powershell
$env:DATABASE_PATH = "$env:TEMP\inventra_test_phase_f_$([guid]::NewGuid()).db"
python -m pytest submission/tests/test_phase_f_manual_order_path.py -q
Remove-Item $env:DATABASE_PATH -ErrorAction SilentlyContinue
```

**Per-step, run only the file(s) that step just touched:**

| After building | Run only this |
|---|---|
| Task 1 (`CaseState`/`create_initial_state`) | New file, tests 1-2 |
| Task 2 (`fetch_evidence` override branch) | New file, tests 3-4, **plus** `submission/tests/test_phase_e_insufficient_data_loop.py` (this task edits the exact function Phase E's own tests cover — confirm nothing there regresses) |
| Task 3 (CLI) | New file, test 5 (exercises `run_case` end to end) |
| Task 4 (UI) | New file, tests 6-9. If a Streamlit `AppTest`-based check is added for the warning banner, also run whatever existing UI test file already uses that mechanism (confirm exact filename by grep before running — this session did not exhaustively catalogue every `AppTest` usage) |

**One combined run, once, as the final phase gate** (only when the user
asks for it):
```powershell
$env:DATABASE_PATH = "$env:TEMP\inventra_test_phase_f_final_$([guid]::NewGuid()).db"
python -m pytest submission/tests/test_phase_a_data_foundation.py `
                 submission/tests/test_phase_b_statistics_and_policy_engine.py `
                 submission/tests/test_phase_c_autonomous_sweep.py `
                 submission/tests/test_phase_c2_policy_floor_reconciliation.py `
                 submission/tests/test_phase_d_two_gate_approval.py `
                 submission/tests/test_phase_e_insufficient_data_loop.py `
                 submission/tests/test_phase_f_manual_order_path.py -q
Remove-Item $env:DATABASE_PATH -ErrorAction SilentlyContinue
```
Still not the entire suite — every phase-lettered file, the set this
project has used as its own "final gate" bundle since Phase D.

---

## 7. Explicitly out of scope for Phase F (do not build these here)

- **A UI/CLI surface for adding a brand-new product to `products` itself.**
  Phase F assumes the SKU already exists as a product row (just with no
  sales history) — creating products from scratch is not mentioned in
  `AUTONOMOUS_PLAN.md`'s Phase F text and is not this phase's job.
- **Any change to Phase E's park mechanism, `parked_items` schema, or the
  sweep's `ALREADY_PARKED` exclusion.** A manually-overridden case simply
  never reaches the park call (DF3) — nothing about parking itself changes.
- **Any change to `size_order_quantity`, `evaluate_options`, or the vendor
  ranking logic.** Once `fetch_evidence` supplies a real (assumed) velocity
  number, the rest of the graph runs completely unmodified — that is the
  whole point of DF1's design.
- **Letting the autonomous sweep use a demand override.** DF5 — explicitly
  a manual-run-only capability.
- **A structured "reason" field beyond the existing `requested_by` name.**
  D23 says the override must be "audited as a named human's decision" — a
  name is what's required; a free-text justification is not asked for by
  the source plan and is not added here. (If wanted later, it's a one-line
  addition to the same `demand_override` dict — not designed here since it
  wasn't requested.)

---

## 8. Open questions this plan surfaces (confirm before implementation)

- **New — exact shape of `CaseState["demand_override"]`.** DF2 proposes a
  plain `dict` (`{"units_per_day": float, "set_by": str}`) rather than a
  frozen dataclass like `TargetReconciliation`, on the reasoning that it
  needs to round-trip through the LangGraph checkpoint serializer the same
  way `vendor_rejection_detail: Optional[dict]` already does (confirmed
  existing precedent in `CaseState`) — but this should be checked against
  `checkpoint_allowlist()`'s exact mechanism (`submission/graph/workflow.py`)
  before assuming a plain dict serializes cleanly across a pause/resume
  cycle. This phase does not pause on this field (Task 2 resolves it inside
  a single node, no interrupt involved), so the risk is low, but worth a
  quick check rather than an assumption.
- **New — should `screen_manual_order` be reachable only from the
  thin-data watchlist row, or also from a general "order something new"
  entry point** (e.g. a text-input SKU search, for a product that doesn't
  even show up on the watchlist yet because it has no inventory snapshot
  at all)? This plan defaults to "only from the thin-data row" (§4, DF8),
  matching D23's own framing ("a human can order anything, **including** a
  no-history item" — read as extending the existing investigate flow, not
  replacing it with a from-scratch SKU picker). Flagged as a scope reading,
  not silently assumed to be the only valid one.
- **New — exact wording/placement of the approval-card warning** (DF6) —
  this plan's draft text is illustrative; the source plan's own exact
  required phrase ("there is not enough sales history for this product;
  the cover target was set by `<name>`, not derived from data") should be
  used verbatim or near-verbatim at implementation time rather than
  paraphrased further, since D23 quotes it directly as the required wording.
- Carried forward, unaddressed by this session (out of Phase F's scope):
  **O1-O5** (original plan), **DB1-DB5** (Phase B), the Phase-C-scoped open
  questions from Entry 017, Phase D's open questions
  (`PHASE_D_PLAN.md` §9), and Phase E's open questions (`PHASE_E_PLAN.md` §9).

---

## 9. Phase F exit criteria (from `AUTONOMOUS_PLAN.md`, restated concretely)

- [ ] A no-history SKU can be ordered manually, with the warning visible on
  the approval card and the provenance in the audit trail — proven by §5
  tests 5 and 8.
- [ ] The override is audited as a named human's decision — proven by §5
  test 3's `emit_audit` call and the `demand_override_applied` event.
- [ ] The agent still performs all vendor work (economics, policy review,
  drafting) rather than merely accepting a human-typed quantity — proven by
  §5 test 6 (the sized quantity comes from `size_order_quantity`, not from
  a human-typed number; R8's "humans choose among computed options, they
  never type a quantity" rule is preserved because the human types a
  *velocity assumption*, not an *order quantity* — the quantity is still
  computed downstream exactly as every other case computes it).
- [ ] Policy floors still apply to manual orders — proven by §5 test 7
  (and already true by construction per §1, this is a regression guard).
- [ ] A manual order with a derived-vs-supplied divergence still surfaces
  both numbers — the approval card already shows `statistical_target_units`/
  `active_target_units`/`policy_floor_units` side by side (existing Phase
  C2 rendering, confirmed in `submission/ui.py` line ~692); this phase adds
  the *provenance* warning on top, it does not need to add the numbers
  themselves, since they already exist for every case regardless of
  provenance.
- [ ] The ordinary (non-manual) run path is provably unaffected — proven by
  §5 test 2, and by every existing test file in the final-gate bundle (§6)
  continuing to pass unmodified.
