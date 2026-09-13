# PHASE_C_PLAN.md

Detailed, end-to-end execution plan for **Phase C — Autonomous sweep**
(`AUTONOMOUS_PLAN.md` §Phase C, C1-C6) plus **Phase C2 — Policy floor
reconciliation**, against the codebase as it actually exists today with
Phase A and Phase B implemented (verified by direct reads + one
context-gatherer sweep this session; see §1).

**This is a planning document. Nothing described here has been built.**
Read alongside `PHASE_A_PLAN.md` and `PHASE_B_PLAN.md` — same relationship:
`AUTONOMOUS_PLAN.md` is the *why*, these three are the *how*, in build
order, against real code.

**A testing instruction that applies to every step in this plan, stated once
here because it matters more in Phase C than anywhere before it:** do not run
`python -m pytest submission/tests -q` (the full suite) as a routine
verification step. Per tracker Entries 011-016, the full suite against the
live `database/inventra.db` is slow (seeding now backfills 24 months of
classification across 35 SKUs) and has hit a Windows file-lock contention
issue in recent sessions that left its final result uncaptured. Every
verification step in this plan names the **specific test file(s)** relevant
to the task just finished, run with an **isolated `DATABASE_PATH`**, per the
confirmed mechanism in §1. The full suite is something to run once, as a
final gate, when the user explicitly asks for it — not a step inside any
individual Phase C task.

---

## 0. What Phase C actually has to produce

Per `AUTONOMOUS_PLAN.md`: "something decides on its own which products to
open cases for." Concretely, three deliverables plus one reconciliation
layer:

1. **Candidate detection (C1)** — a deterministic function that, given a
   warehouse (or all warehouses), reads Phase B's `sku_policy` +Phase A's
   live stock/budget data and returns which (sku, warehouse) pairs are
   genuinely at risk, with every non-candidate's exclusion reason recorded.
2. **Ranking + budget allocation (C2)** — orders candidates by urgency ×
   economic value and allocates the warehouse's remaining monthly budget
   down that list *before* any case is opened, so nothing gets approved
   that the budget can't actually cover once its neighbors are also
   approved.
3. **Per-candidate execution (C3)** — runs the **existing, unmodified** case
   graph for each surviving candidate with a **derived** `target_cover_days`
   (from `sku_policy.derived_cover_days`, not the config default).
4. **Parking (C4)** and **re-sweep behavior (C5)** — undecidable or
   already-in-flight SKUs don't block the sweep or get duplicated.
5. **A sweep record (C6)** — one row per sweep run, auditable after the fact.
6. **Phase C2 — policy floor reconciliation** — layered on top of C3: when a
   `policy_rules` floor and `sku_policy`'s statistical target disagree, both
   numbers are always shown and a human chooses, reusing the existing
   `apply_human_edit` cycle.

Phase C does **not** rebuild the case graph. Every node from
`validate_request` through `finalize_success` stays exactly as Phase B left
it. Phase C's own new code is a **thin, deterministic layer above the
graph** — it decides *whether and with what inputs* to call
`graph.invoke(create_initial_state(...))`, the same call `app.py::run_case`
already makes today. This is the single most important scoping fact in
this plan, restated in §8 with its full list of "do not touch" files.

---

## 1. Ground truth: the codebase Phase C actually builds on

Verified this session by direct reads (`tools/warehouses.py`, a live query
against `database/inventra.db`, `database/seed.py`'s backfill call site,
`submission/graph/routes.py`'s full function list) plus a context-gatherer
sweep of `submission/statistics/classify.py`, `tools/classification.py`,
`database/backfill_classification.py`, `submission/state/state.py`,
`submission/graph/nodes.py`, `submission/graph/workflow.py`,
`submission/portfolio.py`, `tools/execution.py`, `tools/memory.py`,
`submission/config.py`, `submission/tests/`, `submission/app.py`, and
`fixtures/scenarios.json` — cross-checked against my own reads where they
overlap.

| Fact | Detail |
|---|---|
| **`sku_policy` is live and populated** | Confirmed by direct query: **817 rows, 35 distinct (sku, warehouse_id) pairs** in the current `database/inventra.db`. `database/seed.py` calls `backfill_classification.backfill_all(db_path)` at the end of `seed_data()` (confirmed by direct grep, line ~104-105). Phase C can rely on this table being populated after any fresh seed. |
| **`classify_portfolio` is per-warehouse, and self-persists by default** | `classify_portfolio(warehouse_id, as_of, conn=None, db_path=...)` classifies every SKU with sales history *in that one warehouse* and, when called with `conn=None` (the default), **writes to `sku_policy` as a side effect** via an inline `upsert_sku_policy` call. Phase C's sweep must decide explicitly whether it wants this write-through behavior (fine for a real sweep that intends to refresh classification) or a pure read (pass its own `conn`). This is a real API sharp edge to design around, not incidental. |
| **No bulk/portfolio-wide classification read exists** | `tools/classification.py` only has `get_latest_sku_policy(sku, warehouse_id, ...)`, `get_sku_policy_history(...)`, `upsert_sku_policy(...)` — all single-SKU. Phase C's candidate detection needs "give me the latest row for every SKU in this warehouse" and must add this as new, additive functionality (see §4 C1). |
| **`CaseState` has no classification field** | Unchanged since Phase B (confirmed by direct read of `submission/state/state.py`). Phase C must decide whether the case graph itself needs to know its `sku_policy` row (see §4 C3/§9 open question) or whether the derived `target_cover_days` is a sufficient handoff at the graph's existing entry point. |
| **The only way to start a case today is `app.py::run_case` / the Streamlit UI calling the same function** | Confirmed: no scheduler, no poller, no sweep entry point exists anywhere in the codebase. This is exactly the gap C1-C3 fill. `submission/portfolio.py::list_pending_cases()` already has the "don't duplicate an open case" pattern (batched `latest_thread_ids` + one graph scan) — C5 should reuse this pattern, not reinvent it. |
| **`scan_portfolio()` is NOT a drop-in candidate-detection seam** | It's deterministic, portfolio-wide, and already ranks by urgency — but it uses only raw `calculate_stock_risk` velocity math, with **zero awareness of `sku_policy`** (no ABC/XYZ, no `reorder_point_units`, no `active_target_units`, no policy floors). Phase C's trigger condition (`current_position < max(reorder_point, policy_floor)`, per `AUTONOMOUS_PLAN.md` C1) needs `sku_policy.reorder_point_units` and `policy_rules`, neither of which `scan_portfolio` reads. C1 needs a **new** function; `scan_portfolio` is a useful reference for the "graceful per-row failure, most-urgent-first" pattern, not something to extend in place (extending it would conflate the pre-Phase-B watchlist view with the new autonomous trigger — different consumers, different correctness bars). |
| **Budget reservation/release is per-warehouse-per-month, in `tools/execution.py`** | `create_purchase_request` increments `monthly_budgets.committed_amount`; `cancel_purchase_request` decrements it against the *specific* `committed_budget_month` the request reserved. Confirmed exact SQL. **This is the reused mechanism for C2** — but C2's ranked pre-allocation must account for `committed_amount` growing *across the sweep itself* (candidate 3's budget check must see candidates 1 and 2's reservations), not just check once against a stale snapshot taken before the sweep started. |
| **`portfolio.py::list_warehouses()` is still stale** | Confirmed still `SELECT DISTINCT warehouse_id FROM inventory_snapshots`, with a docstring claiming no `warehouses` table exists — false since Phase A. `tools/warehouses.py::list_warehouses()` (confirmed, full read) correctly reads the real table. **Fixing this one call site is now a genuine Phase C prerequisite**, not a cosmetic nice-to-have deferred from Phase A/B: C1's sweep needs the warehouse list, and it should not inherit a function that silently misses a warehouse with no `inventory_snapshots` row yet (e.g. a brand-new warehouse with only a `budgets`/`warehouses` row). Promoted from "nice-to-have" (Phase A/B plans) to "do this" (§4 C1, step 0). |
| **`fixtures/scenarios.json` already has scenarios 13-26** | Confirmed by direct structural description: a `phase_a_scenarios` array with all of `STEADY_DEMAND(13)` through `FREIGHT_INVERSION(26)`, including both policy-floor scenarios (`POLICY_LOW_FLOOR(21)`, `POLICY_HIGH_FLOOR(22)` — note these are numbered differently from `AUTONOMOUS_PLAN.md`'s own "16, 17" — see §9 open question) already present as compact fact-rows. Phase C/C2 needs new scenario entries for **budget squeeze (5)**, **reliability collapse (6)**, **learned preference (7)**, **un-emailed PO (14)**, and confirmation that the existing 21/22 map correctly to what C2 needs. |
| **The isolated-test-DB mechanism is confirmed and exact** | `config.database_path` reads `os.getenv("DATABASE_PATH", "database/inventra.db")` at construction. Setting `DATABASE_PATH` **before the process starts** (not mid-test, except via `object.__setattr__` on the frozen config instance, which one existing test already does) points `reset_db.py`'s `reset_business_state()` and every tool's default `db_path` argument at a throwaway file. This is the exact mechanism named in the testing instruction above and used throughout §7. |
| **No sweep/monitor config exists yet** | Confirmed nothing in `submission/config.py` for max LLM calls per sweep, budget-allocation caps, or sweep intervals — Phase C adds all of it fresh, no risk of duplicating existing config. |
| **`routes.py` has 13 routing predicates, none sweep-aware** | Full list confirmed (`route_after_validate` through `route_after_execution`). Phase C adds zero new routes to this file — the case graph's internal routing is unchanged; C2's floor-reconciliation choice is carried as a new field on the existing `ApprovalDecision`/edit-cycle inputs, not a new graph edge (per `AUTONOMOUS_PLAN.md` D19/§C2.3's own explicit "no new graph shape" rule). |

---

## 2. Design decisions this plan makes explicit (confirm before coding)

**DC1 — the sweep is a new top-level package, not more functions bolted onto
`portfolio.py`.** `scan_portfolio()` is watchlist/UI-facing, read-only,
pre-Phase-B. Mixing sweep-and-execute logic into the same file would
conflate two different correctness bars (a UI read that can tolerate a
slightly stale row vs. an autonomous process that opens real cases and
spends real LLM budget). New package: `submission/sweep/`.

**DC2 — `classify_portfolio`'s self-persisting default is used deliberately
by the sweep, not avoided.** A real autonomous sweep *should* refresh
classification before deciding — that's more correct than trusting a
possibly-stale `sku_policy` row from last month's backfill. The sweep calls
`classify_portfolio(warehouse_id, as_of=today(), conn=None)` once per
warehouse **at the start of its own run**, accepting the write-through as a
feature. This is the resolution of the sharp edge named in §1 — documented
here as a decision, not left ambiguous.

**DC3 — candidate detection is a fresh function, not an extension of
`scan_portfolio`.** Per §1's finding. New function:
`submission/sweep/candidates.py::detect_candidates(warehouse_id, as_of) ->
list[Candidate]`.

**DC4 — `CaseState` gains one new optional field, `sku_policy_snapshot`.**
Rather than have the case graph re-derive statistics it already has from
the sweep, `create_initial_state` gains an optional parameter
`sku_policy_snapshot: Optional[SkuPolicy] = None`. When the sweep opens a
case, it passes the `SkuPolicy` row that justified the candidate; when a
human runs `app.py run <sku> <warehouse>` manually (Phase F territory,
later), it stays `None` and existing behavior is unchanged. This is additive
to `CaseState` (a new optional key in the `TypedDict`), not a breaking
change — `create_initial_state`'s existing callers keep working with zero
edits. This directly answers §1's flagged question about whether the graph
needs classification data: yes, but only as a passenced-through snapshot,
never recomputed inside a node (keeps R3 — arithmetic stays outside the
LLM's and outside any *new* node's reach; it was already computed once by
the sweep).

**DC5 — `derived_cover_days` becomes the new `target_cover_days` for
sweep-opened cases only.** Manually-run cases (`app.py run`) keep today's
`config.target_cover_default_days` fallback unless a caller passes an
explicit value — Phase C does not remove the manual override capability
(that's explicitly Phase F's job to formalize; Phase C must not regress it).
`AUTONOMOUS_PLAN.md`'s D2 ("target_cover_days becomes a derived output,
input removed") describes the **end state after Phase F/G**, not something
Phase C alone must enforce — flagged so a future agent doesn't try to strip
the manual entry point prematurely.

**DC6 — the sweep never calls the LLM agents directly.** It calls
`graph.invoke(...)` once per surviving candidate, exactly like `app.py`
does today. The "3 LLM calls per candidate" cost control (C3) is enforced
by C1/C2's filtering happening *before* any `graph.invoke` call, not by any
new cost-tracking code inside the graph itself.

**DC7 — fix `portfolio.py::list_warehouses()` as a Phase C prerequisite
(§1).** Small, contained, one-function change with an existing docstring
that needs correcting at the same time (it currently asserts a false
premise). Not deferred.

---

## 3. New files this phase creates

```
submission/sweep/
    __init__.py
    candidates.py       C1 — detect_candidates(), Candidate dataclass,
                              exclusion-reason enum
    ranking.py           C2 — rank_candidates(), allocate_budget()
    parking.py            C4 — park_candidate(), resolve_park(), ParkedItem
                              read/write (tools/parking.py does the DB I/O;
                              this module holds the decision logic for WHEN
                              to park)
    resweep.py             C5 — reminder-vs-reopen decision for SKUs already
                              mid-case
    run.py                  C3/C6 — run_sweep(warehouse_id=None) -> SweepRecord,
                              the orchestrator tying C1-C5 together and
                              writing the sweep_runs row

tools/
    parking.py            NEW (C4) — get_open_parked_items, park_item,
                              resolve_park (narrow, parked_items-only,
                              matches existing tools/ convention)
    sweep_runs.py          NEW (C6) — record_sweep_run, get_sweep_history
    classification.py     MODIFIED — add get_latest_policies_for_warehouse
                              (the bulk read §1 found missing)

database/
    schema.sql             MODIFIED — new table sweep_runs (C6); parked_items
                              already exists from Phase A, unchanged shape
    migrate.py              MODIFIED — sweep_runs added to _ADDITIVE_TABLES

domain/tool_models.py     MODIFIED — add SweepRun, SweepCandidateResult,
                              ParkedItemRecord models (Candidate itself stays
                              a plain sweep-internal dataclass, not a Pydantic
                              tool-model, since it never crosses a tool
                              boundary — matches AUTONOMOUS_PLAN.md's R3
                              distinction between tool evidence and internal
                              computation)

submission/state/state.py MODIFIED — CaseState gains
                              `sku_policy_snapshot: Optional[SkuPolicy]` (DC4)
submission/graph/nodes.py  MODIFIED — draft_proposal reads
                              policy_rules via a new deterministic step
                              (C2.3/C2.4, see §5) folded into the EXISTING
                              fetch_budget_and_policy node, not a new node
submission/agents/models.py MODIFIED — ApprovalDecision gains
                              `chosen_target_basis: Optional[str]` (C2.2)
submission/graph/nodes.py (same file) — apply_human_edit handles
                              target-basis switches as well as offer switches

submission/portfolio.py    MODIFIED — list_warehouses() now delegates to
                              tools.warehouses.list_warehouses() (DC7)

submission/app.py          MODIFIED — new `sweep [warehouse_id]` CLI command

submission/config.py       MODIFIED — new sweep-related config (see §4 per task)

submission/tests/test_phase_c_autonomous_sweep.py
                              NEW — C1-C6
submission/tests/test_phase_c2_policy_floor_reconciliation.py
                              NEW — C2.1-C2.4 (kept as a separate file from
                              the sweep tests since C2 exercises the case
                              graph's existing edit-cycle, a different
                              fixture shape than the sweep's candidate lists)
```

Nothing in `submission/graph/economics.py`, `submission/statistics/`, or
any Phase A/B tool module changes in this phase — Phase C consumes their
output, it does not modify their formulas.

---

## 4. Task-by-task plan

### C1 — Candidate detection (`submission/sweep/candidates.py`)

**Step 0 (prerequisite, DC7):** `submission/portfolio.py::list_warehouses()`
body becomes:
```python
def list_warehouses() -> list[str]:
    from tools.warehouses import list_warehouses as _list_warehouses
    return [w.warehouse_id for w in _list_warehouses()]
```
Docstring rewritten to state the `warehouses` table exists and is now the
source (removes the now-false "no warehouses table" claim). This is a
pure refactor of an existing function's body — its return type
(`list[str]`) is unchanged, so every existing caller keeps working.

**New bulk read** (`tools/classification.py`, additive):
```python
def get_latest_policies_for_warehouse(warehouse_id: str, before_as_of: date | None = None,
                                        db_path: str = "database/inventra.db") -> list[SkuPolicy]:
    """One row per SKU: its most recent sku_policy row at or before
    before_as_of (default: today) for this warehouse. Used by the sweep to
    avoid N individual get_latest_sku_policy calls."""
```

**Candidate dataclass** (`submission/sweep/candidates.py`, plain dataclass,
not a Pydantic tool model per §3's note):
```python
@dataclass(frozen=True)
class Candidate:
    sku: str
    warehouse_id: str
    policy: SkuPolicy               # the sku_policy row that justified this
    policy_floor: Optional[PolicyFloor]
    current_position: int           # on_hand - reserved + confirmed_inbound + open_order_units
    trigger: str                    # "REORDER_POINT" | "POLICY_FLOOR" | "BOTH"
    urgency_score: float            # see C2 for the formula; computed here since
                                     # it is a property of the trigger facts, not
                                     # of the ranking step itself

class ExclusionReason(str, Enum):
    DATA_STALE = "stale snapshot"
    CASE_ALREADY_OPEN = "already has a pending case awaiting a human"
    SUFFICIENT_ON_ORDER = "already on order in sufficient quantity"
    INACTIVE = "product inactive/EOL"
    INSUFFICIENT_MATURITY = "maturity INSUFFICIENT -- parked, not excluded"
    HEALTHY = "current position covers reorder point and any policy floor"

@dataclass(frozen=True)
class ExclusionRecord:
    sku: str
    warehouse_id: str
    reason: ExclusionReason
    detail: str

def detect_candidates(warehouse_id: str, as_of: date | None = None
                       ) -> tuple[list[Candidate], list[ExclusionRecord]]:
    """
    1. classify_portfolio(warehouse_id, as_of, conn=None)  -- refresh + read (DC2)
    2. for each SkuPolicy row:
       a. get_stock_position(sku, warehouse_id) -- staleness check first,
          same freshness threshold as the case graph (config.data_freshness_hours)
          -> stale: ExclusionRecord(DATA_STALE), continue
       b. get_open_order_quantity(sku, warehouse_id) via tools/execution.py
       c. current_position = on_hand - reserved + confirmed_inbound + open_order_units
       d. if get_latest_sku_policy's maturity == INSUFFICIENT:
          -> not excluded, PARKED (delegates to submission/sweep/parking.py,
             C4) -- never silently dropped
       e. policy_floor = get_active_policy_floor(sku, warehouse_id, as_of)
       f. floor_units = max(policy_floor.min_units or 0,
                             policy_floor.min_cover_days * policy.mean_daily_demand
                             if policy_floor and policy_floor.min_cover_days else 0)
       g. threshold = max(policy.reorder_point_units, floor_units)
       h. if current_position >= threshold: ExclusionRecord(HEALTHY), continue
       i. else: check for an already-open case via
          latest_thread_id + compile_graph() scan for a PAUSED/awaiting-human
          checkpoint (reuse list_pending_cases()'s exact pattern) ->
          if found: ExclusionRecord(CASE_ALREADY_OPEN), continue (C5 handles
          this SKU separately, in the SAME sweep run, as a reminder check --
          see resweep.py)
       j. else: append Candidate(..., trigger=...)
    Returns (candidates, exclusions) -- every non-candidate has a reason,
    per the plan's explicit "nothing happened is explainable" requirement.
    """
```

**Trigger condition, exactly per `AUTONOMOUS_PLAN.md` C1:**
`current_position < max(reorder_point, policy_floor)` — either breach
fires. `trigger` field distinguishes which (or both) fired, purely for the
sweep record's explainability (C6), not for different handling downstream —
both trigger types produce an identical `Candidate` shape and flow through
C2/C3 identically.

**New config** (`submission/config.py`): none needed for C1 itself — every
threshold it uses already exists (`config.data_freshness_hours`, and
`sku_policy`'s own `reorder_point_units`/`maturity` fields).

### C2 — Ranking and budget allocation (`submission/sweep/ranking.py`)

```python
def urgency_score(candidate: Candidate) -> float:
    """Already computed once in detect_candidates per DC's own note --
    this function is the SHARED definition both candidates.py and ranking.py
    import, so it is defined here and imported by candidates.py, not
    duplicated. urgency = economic_value / max(cover_days_remaining, 0.1):
      economic_value = candidate.policy.consumption_value_12m
      cover_days_remaining = current_position / policy.mean_daily_demand
                              if policy.mean_daily_demand > 0 else 0
    Higher score = more urgent AND more economically important. A near-zero
    cover_days_remaining with low economic value still ranks below a
    5-days-remaining high-value SKU -- this is a deliberate business choice
    (protect revenue-critical stock first), named explicitly here as a
    provisional default (see Sec9 open questions), not hidden inside the
    formula."""

@dataclass(frozen=True)
class BudgetAllocationResult:
    approved: list[Candidate]           # will proceed to C3
    deferred: list[tuple[Candidate, str]]  # (candidate, reason) -- named, not silent

def allocate_budget(candidates: list[Candidate], warehouse_id: str, budget_month: str
                     ) -> BudgetAllocationResult:
    """
    1. Rank candidates by urgency_score, descending.
    2. Read get_budget_position(warehouse_id, budget_month) ONCE at the start.
    3. running_committed = budget.committed_amount  (starting point)
    4. For each candidate in ranked order:
       a. Estimate its cost via a CHEAP proxy, not a full graph run:
          estimated_cost = policy.reorder_point_units * cheapest active
          landed_unit_cost for that sku (tools/cost_inputs.landed_unit_cost,
          already built in Phase B/B10) -- an ESTIMATE, always re-validated
          for real once C3 actually runs the graph (the graph's own budget
          check in fetch_budget_and_policy / draft_proposal is untouched and
          remains the authoritative gate; this estimate exists ONLY to decide
          sweep-time ordering, never to bypass the graph's real check).
       b. if running_committed + estimated_cost <= budget.budget_amount:
            approved.append(candidate); running_committed += estimated_cost
          else:
            deferred.append((candidate, f"Budget would be exceeded: estimated "
                              f"${estimated_cost:,.2f} against ${budget.budget_amount - running_committed:,.2f} "
                              f"remaining after {len(approved)} higher-priority candidate(s)."))
    Returns both lists -- deferred candidates are NEVER silently dropped,
    exactly the plan's explicit requirement (C2's own text: 'Candidates
    beyond the budget line are deferred with a named reason, not silently
    failed').
    """
```

**Why this fixes the real defect the plan names:** today, each case
independently reads `budget.remaining` and only *reserves* money at
execution time — so N candidates can each individually "fit" against the
same stale snapshot, all get approved, and the last few fail revalidation
*after* a human already approved them. `allocate_budget`'s `running_committed`
accumulator is exactly the fix: it simulates the sequential reservation
*before* any candidate is drafted, so the ranked list handed to C3 is
already budget-consistent. C3 still runs the real graph (which still does
its own live, authoritative budget check) — this estimate only decides
*ordering and which candidates are even attempted*, and a live check
diverging from the estimate (e.g. because the real per-supplier sizing
differs from the flat `reorder_point_units` proxy) is expected and handled
normally by the graph's existing over-budget path, not treated as an error
in this layer.

**New config:** none required — `allocate_budget` reads existing
`monthly_budgets` via the existing `tools/policy.get_budget_position`.

### C3 — Per-candidate execution (`submission/sweep/run.py`, partial)

```python
def execute_candidate(candidate: Candidate, budget_month: str) -> CaseState:
    """The ONLY new code here is the call shape -- the graph itself, every
    node, every route, is untouched.
    state = create_initial_state(
        candidate.sku, candidate.warehouse_id,
        target_cover_days=round(candidate.policy.derived_cover_days) if candidate.policy.derived_cover_days else None,
        budget_month=budget_month,
        sku_policy_snapshot=candidate.policy,   # DC4's new optional field
    )
    graph, conn = compile_graph()
    try:
        result = graph.invoke(state, config={"configurable": {"thread_id": state["thread_id"]}})
    finally:
        conn.close()
    return result
    """
```

`target_cover_days=None` (when `derived_cover_days` is unavailable, e.g. a
lumpy SKU whose Croston-based cover isn't meaningfully expressed as a
scalar day count — see `PHASE_B_PLAN.md`'s DB4) falls back to
`create_initial_state`'s existing default
(`config.target_cover_default_days`) — unchanged existing behavior, not a
new fallback path.

**Cost control (3 LLM calls per candidate) is enforced entirely by C1/C2
happening first** — restating DC6. No new code inside `run.py` counts LLM
calls; the discipline is structural (filter hard before any `graph.invoke`).

### C4 — Parking (`submission/sweep/parking.py` + `tools/parking.py`)

`parked_items` table already exists from Phase A (confirmed by
`PHASE_A_PLAN.md`/schema — unchanged shape needed here: `park_id, sku,
warehouse_id, reason, parked_at, resolved_at, resolved_by, note`).

`tools/parking.py` (new, narrow, matches existing tools/ convention):
```python
def park_item(sku: str, warehouse_id: str, reason: str, note: str = "") -> ParkedItemRecord
def get_open_parked_items(warehouse_id: str | None = None) -> list[ParkedItemRecord]
def resolve_park(park_id: str, resolved_by: str, resolution: str) -> ParkedItemRecord
```

`submission/sweep/parking.py` (decision logic, thin):
```python
def maybe_park(candidate_or_insufficient_maturity_row: SkuPolicy, sku, warehouse_id) -> ParkedItemRecord:
    """Called from detect_candidates (C1) when maturity == 'INSUFFICIENT'.
    Builds the specific, actionable note per the plan's C4 requirement --
    NOT 'needs more data' but e.g. 'SKU-014/BLR-01 has 6 weeks of sales
    history (42 observations); needs at least 90 days (config.
    maturity_confidence_full_at_observations-derived floor) before a
    reorder point can be classified as ESTABLISHED or safely PROVISIONAL.'
    Records what WAS computed (mean/std/cv/adi/quadrant -- all already on
    the SkuPolicy row, since Phase B computes provisional stats even for
    INSUFFICIENT maturity) so a human sees how far the analysis got, per the
    plan's explicit ask. Idempotent: does not create a second open park row
    for the same (sku, warehouse_id) if one is already open --
    get_open_parked_items filters first."""
```

**A parked SKU never stops the sweep** — `detect_candidates` calls
`maybe_park` inline and `continue`s to the next SKU; `run_sweep` (C6) never
sees parking as an error condition, just another per-SKU outcome to tally.

### C5 — Re-sweep behavior (`submission/sweep/resweep.py`)

```python
def check_in_flight_case(sku: str, warehouse_id: str) -> Optional[ReminderAction]:
    """Called from detect_candidates when CASE_ALREADY_OPEN fires (C1 step i).
    Reuses list_pending_cases()'s pattern: latest_thread_id(case_id) +
    one compile_graph() scan for the checkpoint's paused state.
    If found paused at request_approval (gate 1) or the future gate-2 pause
    (Phase D, not yet built -- see Sec9):
      - re-check freshness the SAME way fetch_evidence does
        (config.data_freshness_hours against the case's OWN stock snapshot,
        re-fetched fresh, not the stale one baked into the paused state)
      - fresh -> ReminderAction(kind='REMINDER', message='approve or reject')
      - stale -> ReminderAction(kind='REVALIDATION_NEEDED',
                  message='this needs re-validation before it can be sent')
    Returns None if no case is currently paused (nothing to remind about --
    this is a normal, frequent outcome, not an error)."""
```

`case_id` stays stable (`CASE-{sku}-{warehouse_id}`, unchanged — Phase B/A
never touched `new_case_id`). Each sweep run does **not** get a new
`thread_id` for an already-open case — it reuses the found one (a reminder
is not a new run; it's a nudge on the existing paused run). A brand-new
candidate (no open case) gets a fresh `thread_id` via `create_initial_state`
exactly as today.

**Note on scope**: this task's *reminder-sending* half (actually emailing
the approver again) depends on Gate 2 / the email approval flow's current
shape, which Phase C does not change. C5 in Phase C only produces the
**decision** ("this needs a reminder, here's why") and records it on the
sweep run (C6); wiring an actual re-send is deferred to whichever of Phase D
or a small follow-up implements it, since Phase C's own scope (per
`AUTONOMOUS_PLAN.md`) is the sweep's *detection* logic, not the
notification pipeline. Flagged explicitly, not silently narrowed — see §9.

### C6 — Sweep record (`submission/sweep/run.py` orchestrator + `tools/sweep_runs.py`)

New table (`database/schema.sql`, `_ADDITIVE_TABLES` in `migrate.py`):
```sql
CREATE TABLE IF NOT EXISTS sweep_runs (
    sweep_id TEXT PRIMARY KEY,
    started_at TIMESTAMP NOT NULL,
    completed_at TIMESTAMP,
    warehouse_ids TEXT NOT NULL,        -- JSON list, or "ALL"
    pairs_examined INTEGER NOT NULL DEFAULT 0,
    candidates_found INTEGER NOT NULL DEFAULT 0,
    parked_count INTEGER NOT NULL DEFAULT 0,
    deferred_for_budget_count INTEGER NOT NULL DEFAULT 0,
    cases_opened INTEGER NOT NULL DEFAULT 0,
    reminders_sent INTEGER NOT NULL DEFAULT 0,
    total_model_calls_estimate INTEGER NOT NULL DEFAULT 0,
    detail_json TEXT                    -- full per-SKU outcome list, for audit playback
);
```

```python
# tools/sweep_runs.py
def record_sweep_run(...) -> SweepRun
def get_sweep_history(limit: int = 20) -> list[SweepRun]
```

```python
# submission/sweep/run.py

def run_sweep(warehouse_id: str | None = None, as_of: date | None = None) -> SweepRun:
    """The orchestrator. warehouse_id=None means every warehouse
    (tools.warehouses.list_warehouses(), post-DC7 fix).
    for each warehouse:
        candidates, exclusions = detect_candidates(warehouse_id, as_of)  # C1 (parking happens inside)
        allocation = allocate_budget(candidates, warehouse_id, budget_month)  # C2
        for candidate in allocation.approved:
            result = execute_candidate(candidate, budget_month)          # C3
            tally outcome (opened / no_action / blocked / needs_information)
        for sku, wh in already_open_cases_found_during_detection:
            reminder = check_in_flight_case(sku, wh)                     # C5
            tally reminder outcome
    record_sweep_run(...)                                                # C6
    return the SweepRun
    """
```

This is the function `app.py`'s new `sweep` CLI command calls, and the
function G2's future "Run monitor now" button will call.

### Phase C2 — Policy floor reconciliation

**C2.1 — Three figures, always shown.** No new table — `ReplenishmentProposal`
(existing model, `domain/tool_models.py`) needs three new optional fields:
`policy_floor_units: Optional[float]`, `statistical_target_units: Optional[float]`
(already exists on `SkuPolicy`, just needs to flow onto the proposal),
`active_target_units: Optional[float]`, `target_basis: str` (`"POLICY_FLOOR" |
"STATISTICAL" | "STATISTICAL_MINIMUM"`), `target_provenance: str` (`"derived"`
or `"human:<name>"`).

**C2.2 — Divergence logic** — a small, pure function,
`submission/graph/support.py::reconcile_target(statistical: float,
floor: Optional[PolicyFloor], mean_daily_demand: float) -> TargetReconciliation`:
```python
@dataclass(frozen=True)
class TargetReconciliation:
    active_target_units: float
    basis: str
    excess_or_shortfall_units: float   # positive = floor forces MORE than stats
    explanation: str                    # the specific arithmetic sentence,
                                         # per AUTONOMOUS_PLAN.md's C2.2 table
```
Per `AUTONOMOUS_PLAN.md` C2.2's table exactly:
- statistics > floor → recommend statistics, explanation proves the floor
  is insufficient with real numbers ("at X units/day and Y-day lead time,
  the floor is under half a day of cover — you would stock out before any
  delivery lands").
- floor > statistics → recommend the floor (per O1's provisional default,
  already decided in `AUTONOMOUS_PLAN.md`/`DECISIONS.md` D16 — Phase C2
  does not re-open O1, it implements the existing decision), explanation
  quantifies the excess cost in dollars, using `tools/cost_inputs.py`'s
  already-built `carrying_rate_per_day` (B10) — the excess units' carrying
  cost per period.
- equal → no choice offered, normal approve/reject.

**C2.3 — Graph changes (small, reuses the existing cycle, per D19):**
- `fetch_budget_and_policy` (existing node, `submission/graph/nodes.py`)
  gains one new deterministic step: read `get_active_policy_floor(sku,
  warehouse_id)` and call `reconcile_target(...)`, storing the result on
  `state` (new `CaseState` field, `target_reconciliation:
  Optional[TargetReconciliation]` — additive, same pattern as DC4).
  **No new node.** This is the exact insertion point
  `AUTONOMOUS_PLAN.md` C2.3 specifies ("fold into fetch_budget_and_policy").
- `ApprovalDecision` (existing model, `submission/agents/models.py`) gains
  `chosen_target_basis: Optional[str] = None`.
- `apply_human_edit` (existing node) gains a branch: if
  `chosen_target_basis` is set (and differs from the current
  `target_reconciliation.basis`), re-derive quantity/cost against the
  chosen basis and re-enter the **existing**
  `apply_human_edit → draft_proposal → review_policy → request_approval`
  cycle — reusing the exact mechanism `AUTONOMOUS_PLAN.md` D19 already
  designed for offer switches, extended to also cover basis switches.
  Bounded by the existing `config.max_human_edit_cycles = 3` — **no new
  bound needed**, per the plan's own explicit statement.

**C2.4 — Policy review changes:**
- `PolicyReview.checklist` (currently pinned at exactly 8 items, per
  `AUTONOMOUS_PLAN.md`'s own note that Phase C2 makes it 9) gains a 9th
  `PolicyQuestion`: does the proposal respect the policy floor. Forced
  deterministically in `_override_policy_checklist` (existing function),
  exactly like the other 7 mechanically-checkable rows (only
  `tradeoff_explained` stays agent-judged).
- `_checklist_covers_every_question_exactly_once` (existing validator,
  `submission/agents/models.py` or wherever it currently lives — confirm
  exact location before editing) updated for 9, not 8.
- **A human choosing a target below the policy floor produces an
  `EXCEPTION` verdict, never a silent `PASS`** — mirrors the existing
  over-budget-tolerance pattern (`config.over_budget_exception_tolerance`),
  same code shape.

---

## 5. Flow diagrams

### 5.1 The sweep, end to end

```
app.py "sweep" CLI  /  future G2 "Run monitor now" button
        │
        ▼
submission/sweep/run.py :: run_sweep(warehouse_id=None)
        │
        ├── tools/warehouses.py::list_warehouses()      (post-DC7 fix)
        │
        └── for each warehouse ─────────────────────────────────────────┐
              │                                                          │
              ▼                                                          │
        submission/sweep/candidates.py :: detect_candidates(wh, as_of)   │
              │                                                          │
              ├── classify_portfolio(wh, as_of, conn=None)  [DC2: write-through]
              ├── per SKU: stale? → excluded                             │
              │            insufficient maturity? → parking.py::maybe_park (C4)
              │            already open case? → resweep.py::check_in_flight_case (C5)
              │            current_position >= max(reorder_point, floor)? → excluded (HEALTHY)
              │            else → Candidate(...)                          │
              │                                                          │
              ▼                                                          │
        submission/sweep/ranking.py :: allocate_budget(candidates, wh, month)  (C2)
              │  ranks by urgency_score, walks the ranked list against a
              │  running committed-budget accumulator, splits into
              │  approved / deferred(reason)                             │
              ▼                                                          │
        for each approved candidate:                                    │
              submission/sweep/run.py :: execute_candidate(candidate, month)
                    │                                                     │
                    ▼                                                     │
              create_initial_state(sku, wh,                               │
                  target_cover_days=policy.derived_cover_days,            │
                  sku_policy_snapshot=policy)        [DC4]                │
                    │                                                     │
                    ▼                                                     │
              graph.invoke(state, ...)   ── THE EXISTING, UNCHANGED CASE GRAPH ──
                    │  fetch_evidence → assess_demand → compute_risk →
                    │  fetch_vendor_evidence → build_options → recommend_vendor →
                    │  fetch_budget_and_policy [+ reconcile_target, C2.3] →
                    │  draft_proposal → review_policy [+9th checklist row, C2.4] →
                    │  request_approval → (pause for human) ...           │
                    ▼                                                     │
              tally outcome (opened / no_action / blocked / needs_info)  │
                                                                           │
        for each already-open SKU found during detection:                │
              submission/sweep/resweep.py :: check_in_flight_case(sku, wh)  (C5)
              tally reminder outcome ◀──────────────────────────────────┘
              │
              ▼
        tools/sweep_runs.py :: record_sweep_run(...)   (C6)
              │
              ▼
        sweep_runs table  (one row, full detail_json for audit playback)
```

### 5.2 Where C2's reconciliation sits inside the existing cycle

```
fetch_budget_and_policy (EXISTING node, gains one deterministic step)
        │
        ├── get_budget_position(...)                    (existing, unchanged)
        ├── get_active_policy_floor(sku, warehouse_id)   (existing tool, Phase A)
        └── reconcile_target(statistical, floor, mean_daily_demand)  (NEW, pure)
                    │
                    ▼
        state["target_reconciliation"] = TargetReconciliation(...)  (NEW CaseState field)
                    │
                    ▼
draft_proposal (EXISTING, reads target_reconciliation to set
                policy_floor_units / statistical_target_units /
                active_target_units / target_basis on the proposal)
                    │
                    ▼
review_policy (EXISTING, 9th checklist row forces respects-floor check)
                    │
                    ▼
request_approval → human sees BOTH figures + the reconciliation explanation
                    │
                    ▼
        [human either approves, or edits with chosen_target_basis set]
                    │
                    ▼
apply_human_edit (EXISTING node, gains a target-basis branch)
        │
        └── re-derive quantity/cost against chosen basis
                    │
                    ▼
        RE-ENTER: draft_proposal → review_policy → request_approval
        (the EXISTING cycle, D19 — no new graph shape, bounded by the
         EXISTING config.max_human_edit_cycles = 3)
```

---

## 6. Execution order (session-sized chunks)

1. **DC7's `list_warehouses()` fix + the new bulk-read tool
   (`get_latest_policies_for_warehouse`).** Small, isolated, verify with a
   focused new test file before anything else depends on it.
2. **`Candidate`/`ExclusionReason` + `detect_candidates` (C1)**, tested
   against the real seeded 35-SKU/4-warehouse database (not a scratch
   fixture — the seeded data already has known-healthy, known-lumpy,
   known-thin-history SKUs to exercise every branch) with an isolated
   `DATABASE_PATH` copy.
3. **`tools/parking.py` + `submission/sweep/parking.py` (C4)** — small,
   needed by step 2's insufficient-maturity branch; sequenced right after
   since C1's tests need it to pass.
4. **`allocate_budget` (C2 sweep-level, not to be confused with Phase C2
   the floor-reconciliation phase — naming collision flagged in §9)** —
   tested with hand-picked candidate lists against a known budget figure.
5. **`sweep_runs` schema + tool + `run_sweep` orchestrator skeleton (C6,
   most of C3)**, initially calling a stub `execute_candidate` that records
   "would open a case" without actually invoking the graph — proves the
   whole detection→ranking→tally pipeline before spending any real LLM
   calls or graph invocations.
6. **Wire `execute_candidate` to the real `graph.invoke` (finishes C3)** +
   `create_initial_state`'s new `sku_policy_snapshot` param (DC4) +
   `CaseState`'s new field — run against the isolated DB, verify a
   known-at-risk seeded SKU (e.g. one of the `SKU-0xx` rows with a
   deliberately low position) actually reaches `AWAITING_APPROVAL`.
7. **`check_in_flight_case` (C5)** — needs step 6's graph-invocation
   plumbing to have a real paused case to detect.
8. **`app.py`'s new `sweep` CLI command** — thin wrapper, last, once
   `run_sweep` itself is proven.
9. **Phase C2 (policy floor reconciliation)** — deliberately sequenced
   *after* the sweep is working, even though `AUTONOMOUS_PLAN.md`'s own
   dependency diagram shows C2 depending on C (not the other way), because
   C2's test scenarios (`POLICY_LOW_FLOOR`/`POLICY_HIGH_FLOOR`, already in
   `fixtures/scenarios.json`) are most naturally exercised by running the
   sweep against the 4 already-seeded `policy_rules` rows, so having the
   sweep working first makes C2's own testing faster, not because C2
   structurally requires it — flagged as a pragmatic ordering choice, not a
   hard dependency (`reconcile_target` and the graph changes in §4/C2.3-C2.4
   could be built and unit-tested independently at any point after Phase B).

Do not parallelize steps 1-2 with anything else — every later step depends
on `detect_candidates`' exact `Candidate` shape being settled.

---

## 7. Testing — exactly what to run, and what NOT to run

**Do not run the full suite (`python -m pytest submission/tests -q`) as a
routine step in this phase.** Per §0's instruction and the tracker's own
recent history (Entries 011-016), it's slow against the live db (seeding
backfills 24 months of classification) and has had unresolved Windows
file-lock contention. Reserve it for one explicit, final gate — and even
then, run it against an isolated `DATABASE_PATH`, never the live
`database/inventra.db`, so a lock never blocks the user's own manual use of
the app mid-session.

**The exact mechanism (confirmed working, per §1):**
```powershell
# One throwaway db per isolated run. Never reuse the same path across
# concurrent invocations.
$env:DATABASE_PATH = "$env:TEMP\inventra_test_phase_c_$([guid]::NewGuid()).db"
python -m pytest submission/tests/test_phase_c_autonomous_sweep.py -q
Remove-Item $env:DATABASE_PATH -ErrorAction SilentlyContinue
```

**Per-step, run only the file(s) that step just touched:**

| After building | Run only this |
|---|---|
| Step 1 (DC7 fix + bulk read) | A small new focused test (add to `test_phase_c_autonomous_sweep.py`'s top, or a throwaway ad hoc check) — no existing test file exercises `list_warehouses()`'s exact return values in a way this change could break, but grep `list_warehouses` across `submission/tests/` first to confirm before assuming zero blast radius |
| Step 2 (C1) | `submission/tests/test_phase_c_autonomous_sweep.py` (new, C1 section only at this point) |
| Step 3 (C4) | same file, C4 section |
| Step 4 (C2 ranking) | same file, ranking section |
| Step 5-6 (C3/C6) | same file, full — plus, once only, `submission/tests/test_phase2_3_graph.py` (or whatever file currently covers `create_initial_state`/`compile_graph`'s basic contract) to confirm the new optional `sku_policy_snapshot` param didn't change existing graph-construction behavior |
| Step 7 (C5) | same file, C5 section, plus a quick check of whatever file currently tests `list_pending_cases()` (grep for it first) since C5 reuses that pattern |
| Step 8 (CLI) | manual smoke test (`python -m submission.app sweep DEL-01`) against an isolated `DATABASE_PATH` — a CLI wrapper this thin doesn't need its own pytest file |
| Step 9 (Phase C2) | `submission/tests/test_phase_c2_policy_floor_reconciliation.py` (new), plus — because this step edits `PolicyReview`'s checklist count from 8 to 9 — **must** also run whichever existing test file(s) assert the exact 8-item checklist contract (grep `_checklist_covers_every_question_exactly_once` or `len(checklist)` across `submission/tests/` to find them by name before starting; do not guess the filename) |

**One combined run, once, as the final phase gate** (only when the user
asks for it, or right before considering Phase C "done"):
```powershell
$env:DATABASE_PATH = "$env:TEMP\inventra_test_phase_c_final_$([guid]::NewGuid()).db"
python -m pytest submission/tests/test_phase_a_data_foundation.py `
                 submission/tests/test_phase_b_statistics_and_policy_engine.py `
                 submission/tests/test_phase_c_autonomous_sweep.py `
                 submission/tests/test_phase_c2_policy_floor_reconciliation.py -q
Remove-Item $env:DATABASE_PATH -ErrorAction SilentlyContinue
```
This is still not the *entire* suite — it's every phase-lettered file plus
the two new Phase C files, which is the right-sized regression check for
work that (per §8) never touches the pre-existing numbered-phase test files'
subject matter at all. If a change in this phase ever *does* need to touch
older graph code (only C2.4's checklist-count change qualifies), name the
exact older file(s) affected, per the table above, rather than reaching for
the full suite reflexively.

---

## 8. Explicitly out of scope for Phase C (do not build these here)

- **Rebuilding, reordering, or adding nodes to the case graph beyond
  exactly what C2.3/C2.4 specify.** Every node from `validate_request`
  through `finalize_success` keeps its current shape. The sweep calls the
  graph; it does not change it (outside the one named, bounded
  `fetch_budget_and_policy`/`apply_human_edit`/`review_policy` edit set for
  Phase C2, which is itself explicitly "no new graph shape" per D19).
- **Gate 2 (vendor-email approval) and its reminder-sending mechanics.**
  C5 only produces the *decision* that a reminder is due; actually sending
  one is Phase D territory. Flagged in §4 C5, not silently dropped.
- **The two Streamlit UIs (G1/G2).** `run_sweep`'s existence is what a
  future "Run monitor now" button calls — Phase C does not build the
  button.
- **Manual order path formalization (Phase F).** Phase C must not regress
  `app.py run <sku> <warehouse>`'s existing manual behavior (DC5), but
  formalizing `target_provenance = human:<name>` end-to-end is Phase F's
  job.
- **A real background scheduler (cron/APScheduler).** `run_sweep` is
  something a human or a script invokes; Phase C does not add anything
  that runs itself. Matches `AUTONOMOUS_PLAN.md`'s own Phase H deferral.
- **Touching `submission/graph/economics.py` or any `submission/statistics/`
  module.** Phase C consumes their outputs (`SkuPolicy`, `OptionsEconomics`)
  unchanged.

---

## 9. Open questions this plan surfaces (confirm before implementation)

- **New — naming collision.** `AUTONOMOUS_PLAN.md` uses "C2" for two
  different things depending on section: within Phase C, "C2" names the
  *ranking and budget allocation* task; as a top-level phase heading,
  "Phase C2" names the *policy floor reconciliation* phase that comes
  after all of Phase C. This plan preserves both names exactly as the
  source plan uses them (§4's "C2 — Ranking and budget allocation" vs the
  later "Phase C2 — Policy floor reconciliation" heading) but flags the
  collision explicitly here so nobody confuses the two when skimming.
- **New — do the already-seeded `POLICY_LOW_FLOOR(21)`/`POLICY_HIGH_FLOOR(22)`
  scenario rows in `fixtures/scenarios.json` line up with what
  `AUTONOMOUS_PLAN.md`'s scenario catalogue calls "16, 17"?** The
  numbering differs between the two documents (source plan's scenario
  table vs. the already-implemented `phase_a_scenarios` array). Needs a
  direct comparison before Phase C2's tests assume a specific SKU/warehouse
  pair is "the floor-too-low case" — read the actual `fact` field on rows
  21/22 in `scenarios.json` and cross check against the 4 real
  `policy_rules` rows seeded in `database/seed.py` (per `PHASE_B_PLAN.md`'s
  own ground-truth note: AC-001/DEL-01 SLA, SKU-011/BLR-01 warranty,
  SKU-016/CHE-01 legacy-below, SKU-021/DEL-01 legacy-above) before writing
  C2's tests against assumed SKU names.
- **`urgency_score`'s exact formula (§4 C2) is this plan's own provisional
  default**, same treatment as O1/O2/O4/O5/DB1-DB7 elsewhere in this
  project — flagged, not decided. The specific choice (economic value ÷
  cover-days-remaining) is defensible but not sourced from
  `AUTONOMOUS_PLAN.md`'s text, which only says "urgency × economic value"
  without a formula.
- **Should `check_in_flight_case` (C5) also cover cases paused at
  `await_missing_info` or `await_window_choice`** (the two other existing
  interrupt pauses), not just `request_approval`? `AUTONOMOUS_PLAN.md`'s C5
  text only discusses the approval-gate reminder case explicitly. A case
  stuck at `await_missing_info` (e.g. waiting on a data-team backfill) is
  arguably a different kind of "already open" than one awaiting a human's
  approve/reject — worth a decision before C5 is implemented, since
  treating them identically vs. differently changes `check_in_flight_case`'s
  branching.
- **Confirm the exact current location of `_checklist_covers_every_question_exactly_once`**
  (§4 C2.4) before editing it — the context-gatherer sweep this session did
  not pin down whether it lives in `submission/agents/models.py` or
  elsewhere; a direct grep is needed at implementation time, not assumed
  from this plan's text.
