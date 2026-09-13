# PHASE_E1_PLAN.md — What's left after Phase E

**This is an inventory, not a fully ground-truth-verified execution plan**
like `PHASE_A_PLAN.md`/`PHASE_B_PLAN.md`/`PHASE_C_PLAN.md`/`PHASE_D_PLAN.md`/
`PHASE_E_PLAN.md`. Those four went through a full direct-code-read pass
before being written. This document instead **collects everything already
known to be unbuilt**, scattered across `AUTONOMOUS_PLAN.md` (Phases F, G,
H), `GAP_NEEDS_INFORMATION.md`, and `UPGRADES.md`, into one place — so that
the moment Phase E is finished, there is a ready-made queue instead of
having to re-read four documents to figure out "what's next."

Each item below is marked with a confidence level:
- **Confirmed unbuilt** — verified by a direct code read this session or a
  prior session's tracker entry.
- **Believed unbuilt, not re-verified this session** — taken from the
  source document's own "open"/"not built" status; should be re-confirmed
  with a quick grep before starting, the same discipline every phase plan
  so far has used (things get built without a tracker entry — see Entry
  018's finding on Phase C/C2, and this session's finding that Phase D is
  also now built with no logged entry).
- **Possibly already superseded** — the source document predates a later
  phase that may have solved the same problem differently; flagged so
  nobody re-builds something that already exists under a different name.

Nothing in this document should be started before Phase E
(`PHASE_E_PLAN.md`) is implemented and verified. **Phase E was implemented
and focused-verified on 2026-09-12**; this document is now the queue that
comes after it.

---

## 1. Immediate next step (unchanged)

**Phase E — Insufficient data loop.** Implemented and focused-verified.
`INSUFFICIENT_DATA` now terminates as `NEEDS_INFORMATION`, creates an
actionable park record, and can be resolved by `backfill_missing_sales`
followed by a fresh graph run. The ambiguous-demand window pause has been
retired in favour of parking. The Phase E regression test includes an
isolated database backfill-and-rerun proof.

---

## 2. Already-planned, still-unbuilt phases from `AUTONOMOUS_PLAN.md`

### Phase F — Manual order path

**Implemented 2026-09-12.** Phase F is deliberately narrower than the old
manual-order wording. The graph always fetches `get_sales_velocity` first:

- With fewer than three sale-days in either window, Phase E parks the exact
  SKU/warehouse/date gap. No human number can resume it; real `sales_daily`
  rows must be entered and the case rerun.
- With usable sales velocity but `PROVISIONAL` or `INSUFFICIENT` maturity,
  the graph pauses for exactly one whole-number input: days of stock to
  hold. It then computes demand, quantity, eligible suppliers, economics,
  policy review and proposal deterministically.
- With `ESTABLISHED` maturity, it ignores any pre-supplied cover value and
  uses `sku_policy.derived_cover_days`; no cover-days control is shown.

The public `run_case` CLI/UI entry point accepts only SKU and warehouse.
The sole manual resume payload is exactly `target_cover_days`; demand rate,
target units, and order quantity are rejected. Manual cover is recorded as
`manual_cover_days:operator`, while established policy is recorded as
`derived:sku_policy`.

### Phase G — Two Streamlit apps

**Confirmed unbuilt, audited 2026-09-12.** One Streamlit app exists at
`submission/ui.py`; the separate simulator/data console and agent console
do not.

Two separate apps, functional not pretty:
- **G1 (simulator/data console):** browse/edit every table, per-SKU levers
  (position, cover days, snapshot age, offer validity, vendor reliability,
  budget), a one-click scenario picker, a policy-floor editor, a live
  statistics panel, a freshness-threshold control, a fabrication log.
- **G2 (agent console):** "run monitor now" with live sweep progress,
  per-candidate outcomes as they land, a pending-approvals queue that
  distinguishes gate 1 from gate 2, a park queue with unblocking actions,
  audit playback per case, and **no field anywhere that asks for a per-SKU
  cover-days number** (the whole point of this project is that the number
  is derived, not typed).

Note: the brief awards **zero marks for a dashboard** — this phase exists
for your own demo/operator use, not for grading. Don't let it eat time
budgeted for anything above it in this list.

### Phase H — Upgrade and gap document (a checklist of small, named fixes)

**Partially complete, audited 2026-09-12**, and this phase is itself just a
checklist — no big design needed, just execution. The complete-day sales
window fix, real cancellation budget-release message, and
threshold-straddling ambiguity handling are already implemented. The
remaining items below need execution. Items, as currently listed in
`AUTONOMOUS_PLAN.md`:

- [ ] UI polish / responsive redesign (deferred, low priority)
- [ ] Multi-SKU purchase order consolidation per vendor
- [ ] Quantity-break / price-ladder pricing
- [ ] Stockout cost beyond lost contribution (SLA penalties, backorder,
  churn) — document as a known floor, not necessarily build
- [ ] Substitution map (lost sale valued at margin *difference*, not full
  contribution)
- [ ] Shelf life / expiry pricing
- [ ] Real background scheduler (cron/APScheduler) for sweeps and reminders
  — **this is the same thing as Upgrade 1 below; do not build twice**
- [ ] Supplier confirmation path (so `confirmed_inbound` is ever written by
  something) — **this is the same defect as the `CONFIRMED`-is-unreachable
  gap below; same fix, don't build twice**
- [ ] Full seasonality modelling beyond level + trend
- [ ] Lateral transshipment between warehouses
- [ ] `roll_forward()` fabricator operation (deferred from Phase A)
- [ ] Formal test suite restoration
- [ ] Fix the stale `test_phase10_cancel_purchase_request.py` docstring/name
  (assertions are already correct, per `DECISIONS.md` D26's correction —
  this is a five-minute cleanup, not a real bug)
- [ ] **Confirmed already fixed** — `tools/sales.py`'s window boundary (this
  session verified the fix is live, per Entry 006 and re-confirmed in
  `PHASE_E_PLAN.md`'s ground-truth table). Remove this line item, it's done.
- [ ] Delete the false cancellation message in `app.py::_print_cancellation`,
  or surface the real `budget_released` value — **check first**: Entry 006
  found this was already fixed once (`CancellationResult.budget_released`
  added, `_print_cancellation` reads it) — re-verify before assuming it's
  still open, since this list may be stale relative to that fix.
- [ ] Make the graph handle threshold-straddling SKUs the way
  `portfolio.scan_portfolio()` already does (evaluate both windows, take
  the worse) — **possibly already superseded by Phase E's own fix** to the
  ambiguous-window path; re-check against whatever Phase E actually ships
  before treating this as separate work.

---

## 3. Older backlog, not yet folded into `AUTONOMOUS_PLAN.md`

These live in `GAP_NEEDS_INFORMATION.md` and `UPGRADES.md` — written before
the autonomous-monitor plan existed, so some may now be superseded by a
later phase. Each is flagged.

### From `GAP_NEEDS_INFORMATION.md`

- **No order-confirmation mechanism (`CONFIRMED` is unreachable).**
  **Believed unbuilt.** `PurchaseRequestStatus.CONFIRMED` exists but nothing
  ever sets it — no supplier acknowledgement path, no goods-received step.
  Same root cause as Phase H's "supplier confirmation path" item above —
  **one fix, not two**.
- **`confirmed_inbound` is never written by anything real** (only by seed
  scripts, always `0`). This is what lets a re-run duplicate-order stock
  already purchased. **Possibly already mitigated**: Phase B/C's reorder
  guard (`get_open_order_quantity` folded into `compute_risk`) closes the
  practical duplicate-ordering risk by checking **open purchase requests**
  directly, rather than needing `confirmed_inbound` to be accurate — worth
  re-reading `tools/execution.py::get_open_order_quantity` and
  `nodes.compute_risk` before assuming this is still a live gap versus
  already covered by a different mechanism.
- **Idempotency-key edge case**: a cancelled request's `idempotency_key`
  still occupies its slot, so a byte-identical re-approval after
  cancellation could be silently deduped against the old cancelled row
  instead of writing a fresh one. **Confirmed still open** as of the doc's
  last note — low severity, needs two genuinely identical proposals in a
  row, deferred deliberately. Low priority; a partial-unique index
  (excluding `CANCELLED`/`FAILED` rows) is the documented fix if ever
  needed.
- **Email cannot be tested without live Gmail credentials** (hardcoded SMTP
  host, unconditional TLS/auth). Still likely true — worth a quick check of
  `submission/notifications/email.py`'s `send_email` for a test-mode escape
  hatch before assuming a fix is needed, since Phases C/D's own test files
  mock `send_email` rather than needing one, which may mean this was never
  actually a blocker in practice.

### From `UPGRADES.md`

- **Upgrade 1 — Proactive monitoring / auto-trigger.** **Possibly already
  superseded.** This upgrade's entire premise — "nobody is watching stock
  continuously, add a scheduler that scans and opens cases on its own" — is
  now Phase C's autonomous sweep (`submission/sweep/run.py::run_sweep`),
  which is built. What Upgrade 1 adds on top that Phase C does **not**
  cover: a genuine background **scheduler** (cron/APScheduler) that fires
  `run_sweep` without a human running the CLI command, and the "ask the
  human a question, interpret their reply, decide on a follow-up reminder
  date" two-way conversation loop. The scanning/case-opening half of this
  upgrade is done; the scheduler and the two-way-reply half are not, and
  both depend on Upgrade 4 below.
- **Upgrade 2 — Auto-redraft on fixable policy failures.** **Believed
  unbuilt**, "idea only" per its own status note. Bounded auto-retry when a
  policy review fails for a fixable reason (e.g. a cheaper eligible vendor
  exists) — re-drafts automatically instead of going straight to a human.
  Genuinely optional scope; not required by the brief.
- **Upgrade 3 — Vendor ordering integration (send the order to the
  supplier).** **Largely superseded — mostly built.** This session confirmed
  Phase D built exactly this: `send_purchase_order`, the
  `vendor_email_enabled` flag, the trust model (templated content only,
  gated behind human approval + revalidation, idempotent send, a dedicated
  second approval gate). What's *not* built: the go-live review this
  upgrade's own trust model calls for (SPF/DKIM/DMARC on the sending
  domain) before flipping `vendor_email_enabled` to `True` for real — that's
  an operational/deployment step, not code, and stays outside this project's
  scope until you're ready to actually email real vendors.
- **Upgrade 4 — Two-way email (read replies, parsed on-premise).**
  **Believed unbuilt.** The one remaining real prerequisite for Upgrade 1's
  full vision (notify → human replies by email → system parses the reply →
  acts). Explicitly designed to keep any reply-parsing on a local model, never
  a hosted one, since message content is untrusted user input. This is the
  most architecturally significant item left in the whole backlog — it's the
  only thing that would make the system genuinely conversational over email
  instead of link-click-only. Worth a dedicated planning pass of its own
  (its own `PHASE_X_PLAN.md`) rather than folding into Phase H's small-items
  checklist, given the security design it needs.

---

## 4. Recommended order after Phase E

1. **Phase E** (in progress / next) — `PHASE_E_PLAN.md`.
2. **Phase F** (manual order path) — small, self-contained, closes a real
   brief-adjacent gap (ordering a brand-new product).
3. **Phase H's cleanup items** — mostly quick, no design needed, and a
   couple may already be done (verify before starting, per §2 above).
4. **Phase G** (two Streamlit apps) — do this once the underlying phases
   (A-F) are solid; it's a view onto them, not new logic, and earns no
   grading marks, so don't let it jump the queue.
5. **Upgrade 4 (two-way email)** — the one item in the old backlog worth a
   dedicated design pass, if you want the full "proactive monitor that
   converses over email" vision from Upgrade 1. Optional, and its own
   plan document should be written fresh (not assumed from the 2026-09-06
   draft in `UPGRADES.md`) once you're ready for it, since the codebase has
   changed substantially since that draft was written.
6. **Everything else in §3** — low-severity, edge-case items. Pick up
   opportunistically, not on a schedule.

---

## 5. Before starting any item in this document

Re-verify its "unbuilt" status with a quick grep first. This project has
twice now had a phase get built with no tracker entry recording it (Phase
C/C2 per Entry 018, Phase D per Entry 019) — so "the plan says it's not
built" is weaker evidence in this codebase than in most, and every phase
plan so far has caught at least one item that was already fixed, already
superseded, or subtly different from its own written description.
