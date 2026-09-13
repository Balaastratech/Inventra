# PHASE_E_PLAN.md

Detailed, end-to-end execution plan for **Phase E — Insufficient data loop**
(`AUTONOMOUS_PLAN.md` §Phase E), against the codebase as it actually exists
today with Phase A, Phase B, Phase C, Phase C2, and Phase D all implemented
(verified by direct reads and one context-gatherer sweep this session — see
§1).

No file named `AUTOMATION.md` exists in this workspace (confirmed by
`file_search`, zero results, same finding `PHASE_D_PLAN.md` already recorded).
`AUTONOMOUS_PLAN.md` is the source plan. Read alongside
`AUTONOMOUS_TRACKER.md` (all entries), `DECISIONS.md` D20-D24 (which already
describe most of this phase's intended design — see the important finding in
§1), and `PHASE_D_PLAN.md` (for the two-gate approval shape Phase E's changes
must not disturb).

**This is a planning document. Nothing described here has been built.**

**A testing instruction that applies to every step in this plan, carried
forward from `PHASE_C_PLAN.md`/`PHASE_D_PLAN.md` because the user repeated it
explicitly for this session too:**

> **Do NOT run the full test suite (`python -m pytest submission/tests -q`)
> as a routine step while implementing Phase E.** Every task below names the
> exact, narrow test file(s) it needs, run with an **isolated
> `DATABASE_PATH`** (mechanism confirmed working in Phases C and D — see §7).
> The full suite is a final gate to run **once**, only when the user
> explicitly asks for it, never a step inside an individual task.

---

## 0. What Phase E actually has to produce

Per `AUTONOMOUS_PLAN.md` §Phase E, five deliverables:

1. Fix an off-spec behaviour: `fetch_evidence`'s `INSUFFICIENT_DATA` failure
   currently ends the case as `BLOCKED`. It must end as `NEEDS_INFORMATION`.
2. The resulting pause/park must state **exactly** what is missing — which
   SKU, which warehouse, which date range, how many observations short.
3. A resume path: once the missing data exists, the case re-runs and
   proceeds normally.
4. Simulator support: a "backfill missing sales" action.
5. Retire the ambiguous-demand-window interrupt (`_await_window_choice`).
   Undecidable cases get **parked**, not paused. Keep `_await_missing_info`
   (brief scenario 2) untouched.

**The single most important finding this session**, recorded in §1: **the
design for this entire phase is already written down**, almost verbatim, as
`DECISIONS.md` D20 through D24 — but **none of it has been implemented**.
D22 literally says "change `nodes.fetch_evidence` so `INSUFFICIENT_DATA`
produces `NEEDS_INFORMATION`" and D21 says "remove `_await_window_choice`" —
both read as completed decisions, but a direct read of the current code
shows `fetch_evidence` still defaults to `BLOCKED` and `_await_window_choice`
is still fully wired into the graph, with a dedicated, still-passing test
file asserting its presence. This is the **opposite** of the process gap
Entry 018 flagged for Phase C (code built with no tracker entry) — here the
decision and its rationale were written and never executed. Phase E's job is
to **build what D20-D24 already decided**, not to re-decide it.

---

## 1. Ground truth: the codebase Phase E actually builds on

Verified this session by a context-gatherer sweep plus direct reads of
`submission/graph/nodes.py` (`fetch_evidence`, `_fail`, `assess_demand`,
`apply_window_choice`, `_override_ambiguity_if_windows_disagree_on_risk`,
all finalize_* nodes, full), `submission/graph/routes.py` (full, all 13
functions), `submission/graph/workflow.py` (full — every node/edge, all four
interrupt call sites), `domain/tool_models.py` (`ErrorCode`, `ProposalStatus`,
`SalesVelocity`, `ParkedItemRecord`, `SkuPolicy` regions), `submission/state/state.py`
(full), `tools/sales.py` (full — the `<3`-observation rule and its exact
window-boundary formula), `tools/parking.py` (full), `submission/sweep/parking.py`
and `candidates.py` (full), `fixtures/fabricator.py` (full), `fixtures/scenarios.json`
(the `INSUFFICIENT_SALES_HISTORY`/`MISSING_DATA` entries), `database/schema.sql`
(`parked_items`, `sales_daily` — confirmed no schema change is needed for this
phase), `database/migrate.py` (`_ADDITIVE_TABLES` mechanism, for completeness —
not needed here), `submission/app.py` (full CLI, `resume_demand_clarification`,
`_print_pending`, `_print_result`), `submission/ui.py` (`_render_window_choice_form`,
the missing-info form, the status-label dict), `submission/notifications/email.py`
(`notify_needs_information`, `notify_blocked`), `tools/memory.py`
(`record_signal`, for the "best-effort write" convention), and every existing
test file that touches this territory (`test_phase9_demand_clarification_message.py`,
`test_phase10_demand_clarification_resume.py`, `test_phase5_remaining_scenarios.py`,
`test_phase6_revision_and_ui_reads.py`'s trending-disagreement test).

| Fact | Detail |
|---|---|
| **`fetch_evidence`'s `INSUFFICIENT_DATA` failure still defaults to `BLOCKED`**, confirmed off-spec, matches D22's own description exactly | `nodes.py::fetch_evidence` calls `_fail(state, sales.error, <message>)` with no 4th argument, so `_fail`'s default `status: ProposalStatus = ProposalStatus.BLOCKED` applies. Every other `_fail` call in the file that means `NEEDS_INFORMATION` passes it explicitly (`validate_request`, `assess_demand`'s ambiguous branch) — `fetch_evidence` is the one outlier. |
| **Fixing only the `_fail` status argument is NOT sufficient** — a second bug this session found, not previously documented in D22 or any tracker entry | `route_after_evidence` today is `return "blocked" if state.get("error_code") is not None else "ok"` — it has no `"needs_information"` branch, so **any** `error_code`, regardless of what `_fail` set `status` to, routes to `finalize_blocked`. And `finalize_blocked` **unconditionally overwrites** `state["status"] = ProposalStatus.BLOCKED`, discarding whatever `_fail` set. So changing only the `_fail` call's 4th argument would have **zero visible effect** on the final case status — the terminal node stamps over it. This is the real reason D22 was never completed: the obvious one-line fix does not work, and the actual fix is a **routing** change, not a status-argument change. |
| **`_await_window_choice` / `apply_window_choice` / `route_after_window_choice` are all still fully implemented, wired, and covered by a dedicated, currently-passing test file** | `workflow.py` has the node, both conditional-edge branches (`"ambiguous" -> await_window_choice`, and `await_window_choice`'s own `ok`/`invalid`/`retries_exhausted` edges), `nodes.py::apply_window_choice` (full logic, config-bounded retries), `routes.py::route_after_window_choice`. `app.py::resume_demand_clarification` is a distinct, tested public entry point. `submission/tests/test_phase10_demand_clarification_resume.py` exercises the whole thing end to end via a real compiled graph, and will need to be deleted or fully rewritten (see §6). |
| **The insufficient-data gate (`tools/sales.get_sales_velocity`) and the maturity gate (Phase B's `SkuPolicy.maturity`) are two different, unrelated signals** — a finding with real consequences for the sweep, not previously flagged | Maturity is about **total history length** (months of data). The sales-velocity gate is `count_7 < 3 or count_30 < 3` — too few sale-days in a **specific recent window**, which can happen to a well-established, 24-months-of-history **lumpy/intermittent** SKU that simply has had a quiet patch. `submission/sweep/candidates.py::detect_candidates` only screens out `maturity == "INSUFFICIENT"` before invoking the graph — it does **not** call `tools.sales` at all. So a sweep-opened case for an established lumpy SKU can absolutely still hit `fetch_evidence`'s `INSUFFICIENT_DATA` path today, and will keep doing so after this phase's fix — this is not a manual-run-only edge case, it is a live autonomous-sweep path, which is why the routing fix matters for Phase C's cost-control story too (see DE4 below). |
| **A parking mechanism already exists** (`tools/parking.py::park_item`/`get_open_parked_items`/`resolve_park`, backed by the real `parked_items` table) but is **only wired to the sweep's maturity check** (`submission/sweep/parking.py::maybe_park`, called from `candidates.py`). It has never been called from inside the graph itself. `ParkedItemRecord` has exactly `park_id, sku, warehouse_id, reason (free text), parked_at, resolved_at, resolved_by, note (free text)` — no structured `question`/`unblocking_action`/`actionable_now` fields; existing callers encode all of that into the free-text `note`. | `tools/parking.py`, `domain/tool_models.py::ParkedItemRecord` |
| **No schema change is needed for this phase.** `parked_items` already has everything this phase's park calls need (`reason` + `note` is exactly the shape `maybe_park` already uses); `sales_daily` already has the `UNIQUE(sale_date, sku, warehouse_id)` constraint the new backfill fabricator function must respect. | `database/schema.sql` |
| **No "backfill missing sales" fabricator function exists.** `fixtures/fabricator.py::fabricate_history` inserts a *fresh* run of days ending yesterday and **raises `ValueError`** on any duplicate `(sale_date, sku, warehouse_id)` row — it cannot be re-run over a partially-populated range, which is exactly the situation "backfill the gap" needs to handle. | `fixtures/fabricator.py` |
| **`fixtures/scenarios.json`'s `INSUFFICIENT_SALES_HISTORY` entry already hedges** — `"expected_outcome": "NEEDS_INFORMATION or BLOCKED"` — so the JSON scenario catalogue does not need to change; only the code needs to stop being the `BLOCKED` half of that "or". | `fixtures/scenarios.json` lines ~191-208 |
| **Two existing tests currently assert the off-spec behaviour as correct**, and must change, not just gain new assertions | `test_phase5_remaining_scenarios.py::test_insufficient_sales_history_blocks` asserts `result["status"] == ProposalStatus.BLOCKED` today. `test_phase9_demand_clarification_message.py::test_insufficient_sales_message_shows_observation_counts` only checks `error_code`/`error_detail` substrings, not `status` — it will keep passing unchanged, but should gain a `status` assertion so the fix is actually locked in going forward. |
| **One existing test's entire premise disappears with D21** | `test_phase6_revision_and_ui_reads.py::test_approval_screen_warns_when_the_sales_trends_disagree` drives the `AC-001/DEL-22` trending fixture through a real pause-then-resume-then-approve flow, asserting the approval screen still shows the disagreement warning *after* a human answers the window-choice question. Once that interrupt is retired, there is no "after a human answers" step — the case parks and terminates at `assess_demand` instead of ever reaching an approval screen. This test's assertion has to change shape, not just its setup (see §6). |
| **`app.py`'s CLI help text (`_print_pending`, `_print_result`) references the retired pause** | `_print_result` checks `payload.get("kind") == "demand_clarification"` and prints a `resume-window` hint; `app.py`'s `resume-window` CLI branch calls `resume_demand_clarification`. All become dead code once the interrupt is gone and should be removed for consistency, not just left inert. |
| **`ui.py::_render_window_choice_form` and its dispatch branch become dead code** for the same reason | `submission/ui.py` lines ~540-545 (`elif awaiting and assessment is not None and getattr(assessment, "ambiguous", False): _render_window_choice_form(...)`) and the form function itself (~lines 640+). |

---

## 2. Design decisions this plan makes explicit (confirm before coding)

**DE1 — The fix is a routing change, not a status-argument change.**
`route_after_evidence` gains a third branch (`"needs_information"`), mapped
in `workflow.py` to the **existing** `finalize_needs_information` terminal
node (already used by `validate_request`'s retry-exhausted path — no new
terminal node needed). `finalize_blocked` and `finalize_needs_information`
both already independently set their own `state["status"]`, so once
`INSUFFICIENT_DATA` stops being routed to `finalize_blocked`, it never gets
overwritten back to `BLOCKED`. The `_fail(...)` call's status argument
change (to `ProposalStatus.NEEDS_INFORMATION`) is still made too, for
consistency with every other `_fail` call and because the UI/CLI read
`state["status"]` before the terminal node runs in a couple of places — but
it is the routing change that actually fixes the bug D22 described.

**DE2 — No new graph node, no new interrupt.** Per D20's own framing
("parking, not blocking, for undecidable single SKUs") and the brief
scenario 11's actual shape (a case that cannot be assessed yet — not one
that is mid-assessment and needs a human's judgment call), the fix is: the
case terminates as `NEEDS_INFORMATION` (a normal graph run, no pause) **and**
is additionally written to the existing `parked_items` table for
cross-run/cross-sweep visibility. `test_insufficient_sales_history_blocks`'s
existing assertion `"__interrupt__" not in result` stays true — this plan
does not introduce a pause where none exists today, it only fixes the
terminal status and adds park visibility.

**DE3 — Both `fetch_evidence`'s insufficient-data failure and
`assess_demand`'s ambiguous-window failure call `tools.parking.park_item`
directly**, at the exact point in `nodes.py` where the specific facts (SKU,
warehouse, exact deficit / exact disagreement) are already on hand — not
inside the generic `finalize_needs_information` node, which serves other
callers (`validate_request`'s retry-exhausted path) that have nothing to
park. Two distinct `reason` codes, matching the existing convention where
`maybe_park` uses `"INSUFFICIENT_MATURITY"` as `reason` and a full sentence
as `note`:
- `reason="INSUFFICIENT_SALES_HISTORY"` from `fetch_evidence`
- `reason="AMBIGUOUS_DEMAND_SIGNAL"` from `assess_demand` (replaces the
  interrupt this phase retires)

Both calls are best-effort in spirit but **not wrapped in try/except**,
matching `submission/sweep/parking.py::maybe_park`'s own (unguarded)
convention — a `parked_items` write failing here would be a real
infrastructure problem worth surfacing, not something to swallow silently
the way `tools/memory.py::record_signal` deliberately does for a
lower-stakes signal.

**DE4 — The sweep must not re-open a case that is already parked.**
Not explicitly asked for in `AUTONOMOUS_PLAN.md`'s Phase E bullet list, but
required for DE2/DE3 to actually save the LLM-call budget Phase C's C1 was
built to protect (see §1's finding that this is a live sweep path, not just
a manual one). `submission/sweep/candidates.py::detect_candidates` gains one
more exclusion check, mirroring the existing `INSUFFICIENT_MATURITY` check's
shape exactly: before invoking anything, check
`tools.parking.get_open_parked_items(warehouse_id)` for an open record
matching this SKU, and if found, exclude with a new
`ExclusionReason.ALREADY_PARKED = "already parked pending human data resolution"`
instead of proceeding. This does not require a new tool function —
`get_open_parked_items(warehouse_id)` already exists and returns everything
needed; `detect_candidates` filters by `sku` in Python, matching how it
already reads `get_latest_policies_for_warehouse` and filters in-loop.

**DE5 — No new fields on `ParkedItemRecord`.** The source plan's Phase C4
(a different, larger parking spec for the sweep's own maturity-based
parking) describes richer fields (`question`, `unblocking_action`,
`actionable_now`) that do not exist on the current model. This phase does
**not** extend the schema to add them — it reuses the existing
`reason`/`note` shape exactly as `maybe_park` already does, encoding the
question and the unblocking action into the `note` string. Extending
`ParkedItemRecord` with structured fields is named explicitly as **out of
scope** here (§8) — it is C4's concern, not E's, and touching it now would
require a migration this phase does not otherwise need.

**DE6 — `_await_missing_info` is untouched.** Confirmed by direct read: it
satisfies brief scenario 2 (missing/invalid `sku`/`warehouse_id`/`target_cover_days`)
and has nothing to do with sales-history sufficiency. No task in this plan
modifies it, `validate_request`, `route_after_validate`, or
`resume_missing_info`.

**DE7 — Retiring `_await_window_choice` removes code, it does not replace it
with a different interrupt.** `assess_demand`'s ambiguous branch keeps
computing `ambiguous`/`clarification_needed` exactly as it does today (via
`_override_ambiguity_if_windows_disagree_on_risk`, unchanged) — only what
happens *after* `ambiguous=True` changes: instead of pausing at
`await_window_choice`, the case parks (DE3) and terminates via the existing
`finalize_needs_information` node, the same terminal node `fetch_evidence`'s
fix now also uses. `route_after_demand_assessment`'s `"needs_information"`
label is kept (no rename), only its `workflow.py` edge target changes from
`"await_window_choice"` to `"finalize_needs_information"`.

**DE8 — The fabricator's new backfill function is additive-safe by
construction, unlike `fabricate_history`.** `backfill_missing_sales(sku,
warehouse_id, start_date, end_date, units_per_day, conn=None)` inserts a row
for every day in `[start_date, end_date]` that does **not already have
one**, silently skipping days that do, rather than raising on any duplicate
the way `fabricate_history` does. This is a deliberate, named difference
from that function's existing "refuse on duplicate" contract (R7's
loud-guard discipline) — because the backfill's entire purpose is to fill
gaps in a range that is, by definition, already partially populated. The
function still respects the same `UNIQUE(sale_date, sku, warehouse_id)`
constraint; it just treats "already exists" as success instead of an error
for this specific, gap-filling operation.

---

## 3. New / modified files this phase touches

```
submission/graph/nodes.py       MODIFIED —
                                 - fetch_evidence: pass
                                   status=ProposalStatus.NEEDS_INFORMATION to
                                   the sales.error _fail(...) call; extend the
                                   message with the exact missing date
                                   range(s) and observation deficit; call
                                   tools.parking.park_item(..., reason=
                                   "INSUFFICIENT_SALES_HISTORY", note=...)
                                 - assess_demand: in the `result.ambiguous`
                                   branch, call tools.parking.park_item(...,
                                   reason="AMBIGUOUS_DEMAND_SIGNAL", note=...)
                                 - REMOVE: apply_window_choice (whole function)

submission/graph/routes.py      MODIFIED —
                                 - route_after_evidence: new
                                   "needs_information" branch for
                                   ErrorCode.INSUFFICIENT_DATA specifically
                                   (all other error codes still -> "blocked")
                                 - REMOVE: route_after_window_choice

submission/graph/workflow.py    MODIFIED —
                                 - REMOVE: _await_window_choice function,
                                   the "await_window_choice" node, and its
                                   conditional edges
                                 - fetch_evidence's conditional edges gain
                                   "needs_information": "finalize_needs_information"
                                 - assess_demand's conditional edges: the
                                   "needs_information" label's target changes
                                   from "await_window_choice" to
                                   "finalize_needs_information"

fixtures/fabricator.py          MODIFIED — NEW: backfill_missing_sales(sku,
                                 warehouse_id, start_date, end_date,
                                 units_per_day, conn=None) -> int (returns
                                 count of days actually inserted)

submission/sweep/candidates.py  MODIFIED —
                                 - ExclusionReason gains ALREADY_PARKED
                                 - detect_candidates: new check against
                                   tools.parking.get_open_parked_items(
                                   warehouse_id) before the existing maturity
                                   check (DE4)

submission/app.py               MODIFIED —
                                 - REMOVE: resume_demand_clarification
                                 - REMOVE: the "resume-window" CLI branch
                                 - REMOVE: the `payload.get("kind") ==
                                   "demand_clarification"` branch in
                                   _print_result (dead once the interrupt
                                   never fires)
                                 - _print_pending: no change needed --
                                   NEEDS_INFORMATION already has a resume
                                   hint branch; confirm at implementation
                                   time whether the insufficient-data/
                                   ambiguous-demand terminal cases should
                                   even appear in "pending" (they should NOT
                                   -- they are terminal, not paused; verify
                                   list_pending_cases() naturally excludes
                                   them because a completed graph run has no
                                   snapshot.next, same mechanism that already
                                   distinguishes every other terminal status)

submission/ui.py                MODIFIED —
                                 - REMOVE: _render_window_choice_form
                                 - REMOVE: its dispatch branch (the `elif
                                   awaiting and assessment is not None and
                                   getattr(assessment, "ambiguous", False):`
                                   block) -- becomes unreachable once
                                   ambiguous cases never pause, but must be
                                   deleted, not left as dead code that
                                   silently never fires
                                 - REMOVE: the resume_demand_clarification
                                   import

submission/tests/test_phase5_remaining_scenarios.py
                                 MODIFIED — test_insufficient_sales_history_blocks
                                 rewritten: status == NEEDS_INFORMATION (not
                                 BLOCKED); add an assertion that a
                                 parked_items row now exists for the case

submission/tests/test_phase9_demand_clarification_message.py
                                 MODIFIED — test_insufficient_sales_message_shows_observation_counts
                                 gains a status assertion; the message-content
                                 assertions may need updating once the exact
                                 date-range wording is finalized in nodes.py
                                 (the ambiguous-question test is unaffected --
                                 it calls assess_demand directly and does not
                                 touch routing)

submission/tests/test_phase6_revision_and_ui_reads.py
                                 MODIFIED — test_approval_screen_warns_when_the_sales_trends_disagree
                                 rewritten (see §6): the AC-001/DEL-22 case now
                                 parks and terminates at assess_demand instead
                                 of pausing-then-resuming-then-reaching an
                                 approval screen

submission/tests/test_phase10_demand_clarification_resume.py
                                 DELETE (entire file tests retired behaviour --
                                 see §6 for exactly which assertions move
                                 where, if anywhere)

submission/tests/test_phase_e_insufficient_data_loop.py
                                 NEW — the phase's own dedicated test file,
                                 matching the test_phase_a/b/c/d_*.py naming
                                 convention (see §5)

docs/testing/phase_e_insufficient_data_loop.tdd.md
                                 NEW (write only after implementation, as the
                                 RED/GREEN evidence record -- matching
                                 docs/testing/phase_[abc]_*.tdd.md's existing
                                 convention)
```

Nothing in `submission/graph/support.py`, `submission/graph/economics.py`,
`submission/statistics/`, `submission/sweep/ranking.py`,
`submission/sweep/run.py`, `submission/sweep/resweep.py`, `database/schema.sql`,
or `database/migrate.py` changes in this phase (no schema change needed —
see DE5/§1).

---

## 4. Task-by-task plan

### Task 1 — `fetch_evidence`'s routing fix (DE1)

```python
# submission/graph/routes.py

def route_after_evidence(state: CaseState) -> str:
    """After stock+sales fetch and our own freshness gate.

    INSUFFICIENT_DATA is the one error this node can produce that is a
    request for more data, not a dead end -- everything else (a missing
    product/stock row, DATA_STALE, an unexpected read failure) still fails
    closed to BLOCKED."""
    error_code = state.get("error_code")
    if error_code is None:
        return "ok"
    if error_code == ErrorCode.INSUFFICIENT_DATA:
        return "needs_information"
    return "blocked"
```

```python
# submission/graph/workflow.py -- the existing fetch_evidence edges gain one entry
graph.add_conditional_edges(
    "fetch_evidence", routes.route_after_evidence,
    {"ok": "assess_demand", "needs_information": "finalize_needs_information", "blocked": "finalize_blocked"},
)
```

### Task 2 — `fetch_evidence`'s message + park call (DE1, DE3)

```python
# submission/graph/nodes.py, inside fetch_evidence's sales.error branch

sales = get_sales_velocity(state["sku"], state["warehouse_id"])
state["sales"] = sales
if sales.error is not None:
    yesterday = datetime.utcnow().date() - timedelta(days=1)
    start_7 = yesterday - timedelta(days=6)
    start_30 = yesterday - timedelta(days=29)
    deficit_7 = max(0, 3 - sales.observation_count_7)
    deficit_30 = max(0, 3 - sales.observation_count_30)
    detail = (
        f"Sales history is too thin to plan against: from {start_7} to {yesterday} "
        f"(last 7 days) only {sales.observation_count_7} sale-day(s) were recorded "
        f"(need at least 3, {deficit_7} short); from {start_30} to {yesterday} "
        f"(last 30 days) only {sales.observation_count_30} sale-day(s) were recorded "
        f"(need at least 3, {deficit_30} short). Backfill sales_daily for "
        f"{state['sku']}/{state['warehouse_id']} across the missing dates, then "
        f"re-run this case."
    )
    _fail(state, sales.error, detail, ProposalStatus.NEEDS_INFORMATION)
    if sales.error == ErrorCode.INSUFFICIENT_DATA:
        from tools.parking import park_item
        park_item(state["sku"], state["warehouse_id"], "INSUFFICIENT_SALES_HISTORY", detail)
    emit_audit(state, "system", "sales_check_failed", {...})  # unchanged payload
    return state
```

Note: `sales.error` can only be `INSUFFICIENT_DATA` or `UNKNOWN_ERROR` per
`tools/sales.py` — the `if sales.error == ErrorCode.INSUFFICIENT_DATA` guard
matters because `route_after_evidence` (Task 1) still sends `UNKNOWN_ERROR`
to `"blocked"`, and this park call should only fire for the genuinely
data-thin case, not an unexpected read failure. Confirm the exact final
message wording against whatever `test_phase9_demand_clarification_message.py`
already asserts (`"1 of last 7 days"` / `"2 of last 30 days"` substrings) —
**do not silently drop those exact substrings**, either keep them verbatim
inside the richer message or update that test's assertions to match the new
wording deliberately, not by accident.

### Task 3 — retire `_await_window_choice` (DE7, DE3)

```python
# submission/graph/nodes.py -- assess_demand, in the result.ambiguous branch
if result.ambiguous:
    _fail(state, ErrorCode.INVALID_INPUT,
          result.clarification_needed or "The demand signal is ambiguous and needs clarification.",
          ProposalStatus.NEEDS_INFORMATION)
    from tools.parking import park_item
    sales = state.get("sales")
    note = (
        f"{result.clarification_needed or 'Demand signal ambiguous.'} "
        f"7-day trend: {getattr(sales, 'window_7_days', '?')}/day "
        f"({getattr(sales, 'observation_count_7', '?')} obs); "
        f"30-day trend: {getattr(sales, 'window_30_days', '?')}/day "
        f"({getattr(sales, 'observation_count_30', '?')} obs)."
    )
    park_item(state["sku"], state["warehouse_id"], "AMBIGUOUS_DEMAND_SIGNAL", note)
    emit_audit(state, "system", "demand_ambiguous", {"question": result.clarification_needed})
return state
```

Then, mechanically:
- Delete `apply_window_choice` from `nodes.py` entirely.
- Delete `_await_window_choice` from `workflow.py` entirely; remove
  `"await_window_choice"` from the node list and both of its conditional
  edge blocks.
- Change `assess_demand`'s existing conditional edge:
  `{"ok": "compute_risk", "needs_information": "finalize_needs_information", "blocked": "finalize_blocked"}`
  (was `"needs_information": "await_window_choice"`).
- Delete `route_after_window_choice` from `routes.py`.
- Delete `resume_demand_clarification` from `app.py`, the `"resume-window"`
  CLI branch, and the `demand_clarification`-kind branch in `_print_result`.
- Delete `_render_window_choice_form` from `ui.py` and its dispatch `elif`.

### Task 4 — sweep-side ALREADY_PARKED exclusion (DE4)

```python
# submission/sweep/candidates.py

class ExclusionReason(str, Enum):
    ...
    ALREADY_PARKED = "already parked pending human data resolution"

def detect_candidates(warehouse_id: str, as_of: date | None = None) -> tuple[list[Candidate], list[ExclusionRecord]]:
    as_of = as_of or date.today()
    classify_portfolio(warehouse_id, as_of, db_path=config.database_path)
    from tools.parking import get_open_parked_items
    open_parks = {p.sku for p in get_open_parked_items(warehouse_id)}
    candidates, exclusions = [], []
    for policy in get_latest_policies_for_warehouse(warehouse_id, as_of):
        if policy.sku in open_parks:
            exclusions.append(ExclusionRecord(policy.sku, warehouse_id, ExclusionReason.ALREADY_PARKED,
                                               "Waiting on a human to resolve an open park item.")); continue
        product = get_product(policy.sku)
        ...  # unchanged from here
```

Placed **before** the existing `product.active`/stale/maturity checks, since
an already-parked SKU should short-circuit before spending any further
reads on it, mirroring how the existing checks are already ordered
cheapest-first.

### Task 5 — fabricator's backfill function (deliverable 4)

```python
# fixtures/fabricator.py

def backfill_missing_sales(sku: str, warehouse_id: str, start_date, end_date,
                           units_per_day: int, conn: sqlite3.Connection | None = None) -> int:
    """Fills any missing sales_daily rows in [start_date, end_date] with
    units_per_day units each, silently skipping days that already have a
    row. Unlike fabricate_history (which refuses any duplicate, per R7's
    loud-guard discipline), this operation exists specifically to fill gaps
    in an already-partially-populated range -- 'already exists' is success
    here, not an error. Returns the number of days actually inserted."""
    own = conn is None
    conn = conn or sqlite3.connect("database/inventra.db")
    try:
        added = 0
        day = start_date
        while day <= end_date:
            existing = conn.execute(
                "SELECT 1 FROM sales_daily WHERE sale_date=? AND sku=? AND warehouse_id=?",
                (day.isoformat(), sku, warehouse_id),
            ).fetchone()
            if not existing:
                conn.execute(
                    "INSERT INTO sales_daily (sale_id, sale_date, sku, warehouse_id, units_sold) VALUES (?, ?, ?, ?, ?)",
                    (f"SALE-{sku}-{warehouse_id}-{day.isoformat()}", day.isoformat(), sku, warehouse_id, units_per_day),
                )
                added += 1
            day += timedelta(days=1)
        if own:
            conn.commit()
        _log("backfill_missing_sales", sku=sku, warehouse_id=warehouse_id,
             start=str(start_date), end=str(end_date), added=added)
        return added
    finally:
        if own:
            conn.close()
```

### Task 6 — end-to-end resume proof (deliverable 3)

No new code — this task is a **test**, proving the resume path deliverable
with the pieces built in Tasks 1, 2, and 5: run a thin-data case (parks,
terminates `NEEDS_INFORMATION`), call `backfill_missing_sales` for the exact
date range the case's own message named, then start a **fresh** run of the
same `sku`/`warehouse_id` (a new `thread_id`, same `case_id` — this system
never resumes a *terminal* thread, it starts a new run, exactly like every
other terminal-then-retry path already works) and confirm it now proceeds
past `fetch_evidence` normally. See §5's new test file for the exact
assertions.

---

## 5. New test file — `submission/tests/test_phase_e_insufficient_data_loop.py`

Sections, matching the phase_c/phase_d test files' own internal structure
(fixture at top using the `tmp_path` + `object.__setattr__(config, "database_path", ...)`
isolation pattern from `test_phase_c_autonomous_sweep.py`, not the older
`DATABASE_PATH`-env-var pattern):

1. **`test_insufficient_sales_history_ends_needs_information_not_blocked`** —
   direct `nodes.fetch_evidence` call (unit-level, matching
   `test_phase9_demand_clarification_message.py`'s existing style) with a
   sparse `SalesVelocity` fixture; assert `state["status"] ==
   ProposalStatus.NEEDS_INFORMATION` (not `BLOCKED`) and `state["error_code"]
   == ErrorCode.INSUFFICIENT_DATA`.
2. **`test_insufficient_sales_message_names_the_exact_gap`** — assert the
   message contains the SKU, the warehouse, both date ranges, and both
   deficit counts (not just the raw observation counts the existing test
   already checks).
3. **`test_insufficient_sales_history_parks_the_item`** — same fixture,
   assert a `parked_items` row now exists with `reason ==
   "INSUFFICIENT_SALES_HISTORY"` for this sku/warehouse (isolated DB fixture
   required for this one, since it's a real write).
4. **`test_end_to_end_thin_data_case_through_the_real_graph`** — compiled
   graph, a genuinely `<3`-observation seeded fixture (reuse or copy the
   `INSUFFICIENT_HISTORY_CASE` pattern from `submission/tests/seed_extra.py`),
   assert `"__interrupt__" not in result` and `result["status"] ==
   ProposalStatus.NEEDS_INFORMATION` (replaces
   `test_phase5_remaining_scenarios.py`'s old assertion, kept here as the
   canonical version; that file's own copy should be updated to match, not
   left contradicting this one).
5. **`test_backfilling_the_named_gap_and_rerunning_succeeds`** — Task 6's
   resume proof: park via a thin fixture, call `backfill_missing_sales` for
   the exact range, start a fresh run, assert it now reaches `compute_risk`
   or beyond (no longer `NEEDS_INFORMATION`).
6. **`test_ambiguous_demand_no_longer_pauses_the_graph`** — the
   `AC-001/DEL-22`-style trending fixture (reuse `seed_extra.py`'s
   `TRENDING_CASE`), assert the graph now reaches a **terminal**
   `NEEDS_INFORMATION` state with `"__interrupt__" not in result`, instead of
   pausing with `payload["kind"] == "demand_clarification"`. This is the
   direct replacement for `test_phase6_revision_and_ui_reads.py`'s retired
   assertion (see §6) and for the deleted
   `test_phase10_demand_clarification_resume.py::test_end_to_end_ambiguous_case_pauses_then_continues_after_an_answer`.
7. **`test_ambiguous_demand_parks_with_both_window_figures`** — same
   fixture, assert a `parked_items` row exists with `reason ==
   "AMBIGUOUS_DEMAND_SIGNAL"` and both `window_7_days`/`window_30_days`
   values appear somewhere in `note`.
8. **`test_await_window_choice_node_no_longer_exists`** — `"await_window_choice"
   not in build_graph().nodes` (inverts `test_phase10_...`'s old assertion —
   a direct, cheap regression guard that the retirement actually happened
   in the graph, not just in the ambiguous-branch's routing).
9. **`test_resume_demand_clarification_no_longer_exists`** —
   `not hasattr(app, "resume_demand_clarification")` (inverts that old
   file's public-API assertion the same way).
10. **`test_sweep_excludes_an_already_parked_sku`** — DE4's new exclusion:
    park a SKU directly via `tools.parking.park_item`, run
    `detect_candidates`, assert it appears in `exclusions` with
    `ExclusionReason.ALREADY_PARKED` and does **not** appear in `candidates`.

---

## 6. Exactly what happens to the two existing tests this phase breaks

**`test_phase10_demand_clarification_resume.py` — delete the whole file.**
Every one of its tests exercises retired code
(`apply_window_choice`/`_await_window_choice`/`route_after_window_choice`/
`app.resume_demand_clarification`). Its two regression-guard tests
(`test_the_pause_node_is_actually_wired_into_the_graph`,
`test_answering_is_reachable_from_the_public_api`) are **inverted**, not
dropped — they become §5's tests 8 and 9 above, in the new file, asserting
absence instead of presence. Its end-to-end test
(`test_end_to_end_ambiguous_case_pauses_then_continues_after_an_answer`) is
replaced by §5's test 6, asserting termination instead of pause-then-resume.

**`test_phase6_revision_and_ui_reads.py::test_approval_screen_warns_when_the_sales_trends_disagree`
— rewrite, do not delete.** The test's *purpose* (proving a human is told
when two sales trends disagree) survives; its *mechanism* (drive through a
pause, answer it, then check the resulting approval screen's note) does not,
because there is no longer an approval screen reached for this case at all —
it now parks and terminates at `assess_demand`. The rewritten version should
assert the **park note** (or the terminal case's `error_detail`) carries the
disagreement warning, matching the spirit of `_approval_notes`'s original
job but reading from the new terminal state instead of a resumed approval
screen. Do not simply delete this test's assertions without replacing them —
the underlying user-facing guarantee (a human is told *why* a case is stuck,
with the actual conflicting numbers, not just a status code) still matters
and still needs a regression guard; it is asserted differently now, not
dropped. This is functionally identical to §5's test 7 above — implementing
that test in the new file and then deciding whether
`test_phase6_revision_and_ui_reads.py`'s copy becomes redundant (delete it)
or stays as a UI-layer-specific check (keep it, pointed at the new terminal
shape) is a five-minute call to make at implementation time, not a design
question — flagged in §9 for a decision, not silently assumed either way.

---

## 7. Testing — exactly what to run, and what NOT to run

**Do not run the full suite (`python -m pytest submission/tests -q`) as a
routine step in this phase.** This phase touches `route_after_evidence` and
`assess_demand`'s conditional edge — both are on the path **every single
existing test that reaches `compute_risk`** passes through, making this at
least as high-risk as Phase D's `execute_purchase` split. The full suite is
the right *final* gate, run once, only when explicitly asked for.

**The exact mechanism** (confirmed working in Phases C/D, reused verbatim —
prefer the `tmp_path` + `object.__setattr__` pattern from
`test_phase_c_autonomous_sweep.py` for any new test needing a real
throwaway database, since it does not depend on process-level env vars):

```powershell
$env:DATABASE_PATH = "$env:TEMP\inventra_test_phase_e_$([guid]::NewGuid()).db"
python -m pytest submission/tests/test_phase_e_insufficient_data_loop.py -q
Remove-Item $env:DATABASE_PATH -ErrorAction SilentlyContinue
```

**Per-step, run only the file(s) that step just touched:**

| After building | Run only this |
|---|---|
| Task 1 (routing fix) | `test_phase_e_insufficient_data_loop.py`'s tests 1, 4 only (write the file incrementally — do not wait until every task is done to write the first test) |
| Task 2 (message + park) | Same file, tests 1-3 |
| Task 3 (retire window-choice) | Same file, tests 6-9, **plus** `test_phase9_demand_clarification_message.py` (unrelated ambiguous-question unit test that must keep passing unmodified) — **do not** run `test_phase10_demand_clarification_resume.py` at this step, delete it as part of this task instead |
| Task 4 (sweep exclusion) | Same file, test 10, **plus** `submission/tests/test_phase_c_autonomous_sweep.py` (Phase C's existing sweep tests, since this edits the same `candidates.py` they cover) |
| Task 5 (fabricator backfill) | Same file, test 5 (the only test that exercises it directly) |
| Task 6 (resume proof) | Same file, test 5 again, end to end |
| Rewriting `test_phase5_remaining_scenarios.py` | That file alone, plus the new file's test 4 (they should agree) |
| Rewriting `test_phase6_revision_and_ui_reads.py`'s trending test | That file alone (it has other, unrelated tests in it — run the whole file, not a `-k` filter, to catch any fixture-sharing surprise) |

**One combined run, once, as the final phase gate** (only when the user asks
for it):
```powershell
$env:DATABASE_PATH = "$env:TEMP\inventra_test_phase_e_final_$([guid]::NewGuid()).db"
python -m pytest submission/tests/test_phase_a_data_foundation.py `
                 submission/tests/test_phase_b_statistics_and_policy_engine.py `
                 submission/tests/test_phase_c_autonomous_sweep.py `
                 submission/tests/test_phase_c2_policy_floor_reconciliation.py `
                 submission/tests/test_phase_d_two_gate_approval.py `
                 submission/tests/test_phase_e_insufficient_data_loop.py `
                 submission/tests/test_phase5_remaining_scenarios.py `
                 submission/tests/test_phase6_revision_and_ui_reads.py `
                 submission/tests/test_phase9_demand_clarification_message.py -q
Remove-Item $env:DATABASE_PATH -ErrorAction SilentlyContinue
```
Still not the entire suite — every phase-lettered file plus the four
existing numbered files this phase's own changes touch directly. If
implementation surfaces some *other* existing file depending on
`_await_window_choice`/`resume_demand_clarification`/`route_after_window_choice`
not caught by this session's greps, name it explicitly and add it here —
do not reach for the full suite just because one more file turned out
affected.

---

## 8. Explicitly out of scope for Phase E (do not build these here)

- **Extending `ParkedItemRecord` with structured `question`/`unblocking_action`/
  `actionable_now` fields.** DE5 — this phase reuses the existing
  `reason`/`note` free-text shape. A future Phase C4-proper pass (if the
  source plan's fuller parking spec is ever built out) can add the
  structured columns; doing it here would require a migration this phase
  otherwise does not need.
- **A UI screen for the parking queue.** `AUTONOMOUS_PLAN.md`'s G1 (simulator
  console) and G2 (agent console) own that; this phase only ensures the
  `parked_items` rows exist and are correct, via `tools.parking.park_item`/
  `get_open_parked_items`/`resolve_park`, all of which already exist.
- **Auto-resolving a park record when a manual re-run of the same case
  succeeds.** A manual re-run (fresh `thread_id`, same `case_id`) is
  unaffected by an open park row today (DE4's exclusion only applies to the
  *sweep's* candidate detection, not to `app.run_case`), so the deliverable-3
  resume path works without this. Auto-resolving the stale park row is a
  nice-to-have left for whoever builds the G1/G2 UI to wire a "resolve"
  button against the existing `resolve_park` function — not required for
  Phase E's own exit criteria.
- **A real background scheduler or any change to when the sweep runs.**
  Unchanged, Phase H's concern, same as every prior phase's plan already
  says.
- **Changing `_await_missing_info`, `validate_request`, or brief scenario 2's
  behavior in any way.** DE6 — confirmed untouched by this plan.
- **Changing anything in `submission/graph/economics.py`,
  `submission/statistics/`, or Phase C2's target-reconciliation machinery.**
  None of it is on the code paths this phase touches.

---

## 9. Open questions this plan surfaces (confirm before implementation)

- **New — should `test_phase6_revision_and_ui_reads.py`'s rewritten
  disagreement test be kept as a UI-layer-specific check, or fully
  superseded by §5's test 7 in the new phase file (making the old one
  redundant and deletable)?** §6 defaults to "keep both, pointed at the new
  shape" as the safe default, but flags this as a five-minute call at
  implementation time rather than deciding it now.
- **New — exact final wording of `fetch_evidence`'s enriched message.**
  Task 2's draft keeps the existing test's exact substrings
  (`"1 of last 7 days"`/`"2 of last 30 days"`-style phrasing) alongside the
  new date-range/deficit content, but the precise final string should be
  checked against `test_phase9_demand_clarification_message.py`'s existing
  assertions before considering this task done — don't let the substring
  match become accidental.
- **New — should `resolve_park`'s existing `resolved_by`/`resolution`
  validation (`ValueError` if either is blank) also be exercised by a new
  Phase E test**, given this phase is the first caller to actually populate
  `parked_items` from inside the graph (as opposed to the sweep's maturity
  path, which already has its own idempotency test)? Not required for this
  phase's exit criteria, since `resolve_park` itself is unchanged code, but
  worth a one-line mention if a reviewer asks why park resolution isn't
  covered here.
- Carried forward, unaddressed by this session (out of Phase E's scope):
  **O1-O5** (original plan), **DB1-DB5** (Phase B), the Phase-C-scoped
  open questions from tracker Entry 017, and Phase D's open questions from
  `PHASE_D_PLAN.md` §9.

---

## 10. Phase E exit criteria (from `AUTONOMOUS_PLAN.md`, restated concretely)

- [ ] A thin-data SKU run through the real compiled graph produces
  `NEEDS_INFORMATION` (not `BLOCKED`), with `"__interrupt__" not in result` —
  proven by §5 test 4, and by `test_phase5_remaining_scenarios.py`'s
  rewritten assertion agreeing with it.
- [ ] The `NEEDS_INFORMATION` case names the exact SKU, warehouse, both date
  ranges, and both observation deficits — proven by §5 test 2.
- [ ] The case is visible in `parked_items` with a reason a human can act
  on — proven by §5 test 3.
- [ ] Backfilling the named date range via `fixtures.fabricator.backfill_missing_sales`
  and starting a fresh run of the same SKU/warehouse produces a normal
  proposal path (past `fetch_evidence`) — proven by §5 test 5.
- [ ] `_await_window_choice` no longer exists as a graph node;
  `app.resume_demand_clarification` no longer exists — proven by §5 tests 8
  and 9.
- [ ] An ambiguous-demand case parks and terminates instead of pausing —
  proven by §5 tests 6 and 7.
- [ ] The sweep does not re-open (or re-spend an LLM call on) an
  already-parked SKU — proven by §5 test 10.
- [ ] Brief scenario 2 (missing request fields) still demonstrably passes,
  unchanged — confirmed by leaving `_await_missing_info`,
  `validate_request`, and `resume_missing_info` untouched (DE6); no new test
  needed for this, since no code on that path changes.
