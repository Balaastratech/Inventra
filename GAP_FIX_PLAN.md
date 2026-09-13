# Implementation Plan: Close the Documented Gaps + Upgrade 2

This plan is written for Kiro to execute directly. It supersedes the "what's
missing" framing in `GAP_NEEDS_INFORMATION.md` and `UPGRADES.md` with
concrete file-level changes, verified against the code on 2026-09-05.

**Two corrections to the source docs before starting** (confirmed by direct
code read, not assumption):

1. `GAP_NEEDS_INFORMATION.md`'s "Streamlit was never built" section is
   **stale**. `submission/ui.py` has three working screens (watchlist, case,
   history) built the same day the gap doc was last edited. Do not rebuild
   the UI from scratch — extend it (see Phase 2, 3, 10).
2. `GAP_NEEDS_INFORMATION.md`'s "2-hour freshness threshold" section is
   **stale**. `config.py`, `tools/inventory.py`, and `policy.md` already
   agree at 48h/2 days. The remaining work is collapsing a duplicated
   constant, not fixing a live mismatch (Phase 1).

## Scope for this plan

**In:** All 8 documented gaps, plus Upgrade 2 (auto-redraft on fixable
policy failures). Vendor-ordering (Gap 8 / Upgrade 3) is built in full —
schema, templated send, idempotency — but the actual outbound send stays
behind its own default-off flag (`vendor_email_enabled`) pending a separate
go-live review, since it's a real commercial action to a third party.

**Out (separate future plan, do not build here):**
- Upgrade 1 (proactive monitoring scheduler + two-way email-reply parsing).
  Needs its own cadence/scope/untrusted-input-parsing design pass.

  **Superseded 2026-09-06:** both are now wanted. Two-way email reply
  parsing has been split out into its own entry (`UPGRADES.md` Upgrade 4)
  because it is a prerequisite for monitoring rather than part of it, and
  because it carries a constraint this plan never considered: message
  content may not be sent to a hosted LLM, so any parsing runs on a local
  model or on deterministic matching only. See Upgrade 4 for the
  authorization design. This plan's phases remain as executed.
- Per-warehouse freshness configurability. Nothing in current data requires
  it (all snapshots cluster at ~1h except one synthetic 78h fixture); Phase 1
  leaves the extension point but ships a single global number.
- RAG/chunking of `policy.md`. The doc is currently short enough that a
  size-guard (Phase 6) is the correct-sized fix; don't build retrieval infra
  for a document that fits in one prompt.

---

## Phase 1 — Foundation: schema + config (do first, everything else depends on it)

**Config changes** — `submission/config.py`:
- Flip `email_enabled` default from `False` to `True` (line 103).
- Add `vendor_email_enabled: bool = field(default_factory=lambda: _bool("VENDOR_EMAIL_ENABLED", False))` — stays off until Phase 8 is explicitly reviewed and turned on.
- Add `max_info_retries: int = 3` — bounds the NEEDS_INFORMATION resume loop (Phase 2), mirroring how `max_revision_cycles` bounds the approval-revise loop.
- Add `max_auto_redraft_cycles: int = 1` — bounds Upgrade 2 (Phase 7), separate from `max_revision_cycles` so human revisions and machine auto-redrafts don't share a budget.

**Schema changes** — new migration in `database/` (follow the existing `schema.sql` pattern):
- `vendors.contact_email TEXT` — nullable, ops-maintained, no default. Never populated from evidence/agent text (Phase 8).
- `purchase_requests.vendor_sent_at TIMESTAMP`, `purchase_requests.vendor_send_status TEXT` — nullable, for Phase 8 idempotency.
- New table `agent_memory_signals`: `id, entity_type TEXT, entity_key TEXT, signal_type TEXT, signal_text TEXT, weight REAL, source_case_id TEXT, created_at TIMESTAMP` (Phase 9).

**Dedupe the freshness constant** — `tools/inventory.py:18`:
- Replace the standalone `STALE_THRESHOLD_HOURS = 48` with a value read from `submission/config.py`'s `data_freshness_hours` (pass it in as a parameter to `calculate_stock_risk`, don't import config directly into a tools module if that breaks the existing dependency direction — check how other tools receive config today and match it). This removes the second source of truth the doc flagged, even though both numbers already agree today.

**Test:** extend `submission/tests/test_phase1_contracts.py` (or add a new
`test_phase9_config.py` per this project's per-phase test file convention) to
assert `config.email_enabled is True` by default and that changing
`data_freshness_hours` changes `tools/inventory.py`'s behavior (proves it's
no longer a hardcoded duplicate).

---

## Phase 2 — NEEDS_INFORMATION pause/resume loop (Gap 1)

Reuse the exact interrupt idiom already in `submission/graph/workflow.py:31-46`
(`_await_approval`). Do not invent a new pause mechanism.

- Add `_await_missing_info` node to `submission/graph/workflow.py`: a
  single `interrupt()` call, nothing else (matches `_await_approval`'s
  side-effect-free shape so re-execution on resume is safe).
- Change the route in `submission/graph/routes.py` /
  `submission/graph/workflow.py:78-81`: `validate_request` → (invalid) →
  `_await_missing_info` (was: straight to `finalize_needs_information`).
- On resume: `_await_missing_info` returns the corrected fields via
  `Command(resume=...)`, which route back into `validate_request` to
  re-check. Bound the loop with `max_info_retries` (new retry-count entry,
  same pattern as `retry_counts["revalidate"]` in `revalidation.py`) — after
  the cap, fall through to today's `finalize_needs_information` → END.
- `submission/app.py`: add a resume path parallel to `resume_case`
  (`app.py:43-80`) that accepts corrected `sku`/`warehouse_id`/
  `target_cover_days` and resumes the same `thread_id` via
  `Command(resume=...)`. Don't overload the existing approval-specific
  `resume_case` — it's typed around `ApprovalDecision`; add a sibling
  function.
- `submission/ui.py`: in `screen_case` (`ui.py:367`), when
  `status == "NEEDS_INFORMATION"`, render an inline form (same shape as
  `_render_approval`, `ui.py:464`) collecting the missing/invalid fields
  and calling the new resume path instead of starting a fresh case via
  `screen_investigate`.

**Test:** new `submission/tests/test_phase9_needs_information_resume.py` —
start a case with a missing field, confirm it pauses (not terminal), resume
with corrected fields, confirm it proceeds into `fetch_evidence`; also test
that exceeding `max_info_retries` still falls through to
`finalize_needs_information`.

---

## Phase 3 — Notification completeness (Gap 2, NO_ACTION, BLOCKED vagueness)

`submission/notifications/email.py`:
- Add `notify_needs_information(state)` — mirrors `notify_blocked`'s shape;
  include which fields are missing/invalid and, once Phase 10's deep-link
  lands, a link straight to the case's UI screen.
- Add `notify_no_action(state)` — pull `available_units`, `daily_velocity`,
  `cover_days`, `target_cover_days`, `projected_stockout_date` straight off
  the `StockRisk` object already computed in `compute_risk`; this is the
  same data `ui.py`'s `_render_no_action_reasoning` (`ui.py:404`) already
  renders — reuse its formatting logic rather than re-deriving it in the
  email template.
- Enhance `notify_blocked`'s no-eligible-vendor case: `build_options`
  already computes `expired_count`/`inactive_count` and knows per-offer
  which failed on reliability vs. deadline — thread that structured detail
  through `state`/the audit event instead of the current flat
  `"No eligible vendor options (reliability or deadline)."` string, and
  render it as a per-vendor breakdown table in the email.

Wire the three new/enhanced calls into `finalize_needs_information`,
`finalize_no_action`, `finalize_blocked` in `submission/graph/nodes.py`
(same call shape as the existing `notify_blocked(state)` call).

**Test:** extend `submission/tests/test_phase3_email_approval.py` (or add
`test_phase9_notifications.py`) asserting each of the three new/changed
notify functions fires exactly once per matching outcome and that the
BLOCKED detail includes per-vendor reasons, not the flat string.

---

## Phase 4 — Revalidation: blocker-aware retry + clear failure messaging (Gap 6, failed-revalidation gap)

`submission/graph/routes.py`, `route_after_revalidation` (line 85-95):
- Read the individual flags from `revalidate_proposal`'s result, not just
  `all_checks_pass`:
  - `hash_matches is False` → fail closed immediately, skip the bounce
    (structural mismatch, a retry cannot fix it).
  - `budget_valid is False` → fail closed immediately (matches the existing
    rule that budget is never re-litigated by a retry).
  - `stock_valid is False` or `offer_valid is False` → keep today's one
    bounce back to `compute_risk` (these can plausibly resolve on a
    fresh read).
- Pass which specific flag failed into `finalize_blocked`'s state so
  Phase 3's `notify_blocked` can build "the price changed after you
  approved" / "the offer was withdrawn" messaging instead of a generic
  blocked notice — add a small `notify_revalidation_failed` variant (or a
  branch inside `notify_blocked`) keyed off this new detail.

**Test:** extend whatever test currently exercises `route_after_revalidation`
with four cases, one per flag being the sole failure, asserting hash/budget
skip the retry and stock/offer take it.

---

## Phase 5 — Approval email: REVISE + formatting (Gap 7)

The graph side already works — `route_after_decision`'s `"revise"` branch
was fixed from an off-by-one bug and `tokens.py`'s `decision` field is a
free string, not a constrained enum, so no graph or token-schema change is
needed. The gap is purely: no REVISE entry point in the email, and no
comment capture.

- `submission/notifications/tokens.py`: no schema change required — confirm
  `make_token` can already produce a `"REVISE"` decision token as-is.
- `submission/notifications/email.py`, `notify_awaiting_approval`: add a
  `revise_url` alongside `approve_url`/`reject_url`, pointing at a new GET
  route (not embedding free text in the signed token itself).
- `submission/graph/approval_server.py`: add `GET /decide` branch for
  `decision == "REVISE"` that renders a small HTML form (comment textarea +
  submit), matching the existing confirm-decision page style. Its POST
  target re-uses `POST /decide`, reading the submitted comment and passing
  it as `decision_payload["comments"]` (line 137) instead of the current
  hardcoded `"via email link"`.
- Formatting cleanup in the same email template: `strftime` for
  `expected_arrival`/`projected_stockout_date` instead of raw ISO, thousands
  separators + fixed 2-decimal for `unit_price`/`total_cost`, and replace
  the `<p>` list with an HTML `<table>`. Keep the existing HTML-escaping.

**Test:** extend `submission/tests/test_phase3_email_approval.py` with a
REVISE-token round trip (GET renders form → POST with comment → graph
resumes with the submitted comment, not the hardcoded string).

---

## Phase 6 — Policy review hardening (Gap 5)

Don't build chunking/RAG — `policy.md` is short. Two right-sized additions
instead:

- `tools/policy.py`, `get_policy_guidance`: add a length guard (e.g. warn/log
  if the raw text exceeds a token-count threshold) so growth of `policy.md`
  becomes visible instead of silently degrading accuracy. This is a
  tripwire, not a fix — if it ever fires, chunking becomes an explicit
  follow-up task, not something built speculatively now.
- Extend the deterministic-override pattern already used for budget in
  `review_policy` (`nodes.py:366-412`) and already used a second time for
  vendor economics (`_validate_recommendation`/`economics.py`'s
  `ACCEPTABLE_VERDICTS`) to the freshness and arrival-vs-stockout questions:
  both facts (`stale`, `meets_deadline`) are already computed booleans
  elsewhere in the graph — cross-check the AI's verdict against them the
  same way budget is cross-checked, instead of trusting the AI's reading of
  those two policy.md questions at face value.

**Test:** add a case where evidence says stale/deadline-missed but the AI
verdict (simulate via stub agent) says PASS — assert the code override
forces the correct verdict, same shape as the existing budget-override test.

---

## Phase 7 — Upgrade 2: auto-redraft on fixable policy failures

Same loop shape as the existing human-REVISE path
(`route_after_decision` → `recommend_vendor`), triggered by a policy BLOCK
instead of a human, bounded by `max_auto_redraft_cycles` (Phase 1).

- `submission/graph/nodes.py`, `review_policy`: on a BLOCKED verdict,
  classify fixable vs. unfixable via an explicit reason code (not free-text
  parsing) — reuse whatever error-code convention `_fail(...)` already uses
  elsewhere in this file:
  - Fixable: over-budget (not within tolerance, but a cheaper eligible
    vendor might exist), or a policy concern tied to *which vendor* was
    picked.
  - Unfixable: missing/insufficient/stale evidence, no eligible vendor
    options, SKU not actually at risk — these fail closed exactly as today.
- Route fixable BLOCKED → back to `recommend_vendor` with the block reason
  attached, reusing the same `render_approver_feedback`-style mechanism
  `strategist.py:103` already uses for human comments, but sourced from the
  machine-generated reason instead.
- Hard constraint carried forward unchanged: the budget verdict itself stays
  code-computed and code-enforced (Phase 6/existing `review_policy` logic);
  auto-redraft may only change *which eligible option* is proposed, never
  soften the over-budget check itself.
- After `max_auto_redraft_cycles` is exhausted with no passing redraft, fall
  through to `finalize_blocked` with the last rejected proposal + reason
  attached (so Phase 3's improved BLOCKED email has something concrete to
  show), not a bare BLOCKED.

**Test:** one case where the first pick is over-budget but a cheaper
eligible vendor exists (assert auto-redraft finds it and passes), one case
where no cheaper option exists (assert it exhausts the cap and blocks with
the reason attached), one unfixable case (assert it fails closed on the
first attempt, no redraft spent).

---

## Phase 8 — Vendor ordering: build the capability, ship the send disabled (Gap 8 / Upgrade 3, narrowed)

Schema is already done in Phase 1 (`vendors.contact_email`,
`purchase_requests.vendor_sent_at`/`vendor_send_status`).

- New file `submission/notifications/vendor_email.py`, separate from the
  internal `notifications/email.py` to keep the trust boundary explicit in
  the file structure itself: builds a strictly templated PO message from
  only validated `Proposal`/`PurchaseRequest` fields (`sku`, `quantity`,
  `unit_price`, `total_cost`, `vendor` name, `expected_arrival`) — no field
  sourced from agent-generated text, ever.
- `submission/graph/nodes.py`, `execute_purchase` (line 514-535): after
  `create_purchase_request` succeeds, call the new vendor-send function
  **only if** `config.vendor_email_enabled` is `True` — the flag stays
  `False` (Phase 1 default) until this is explicitly reviewed and turned on
  as its own decision, separate from merging this code.
- Idempotency: key the send on `proposal_hash` (same key already used for
  the DB write's idempotency), check/set `vendor_sent_at`/
  `vendor_send_status` before sending so a retried `execute_purchase` or a
  re-approval can never double-send.
- Authorization gate: the vendor-send function must only be reachable from
  `execute_purchase`, i.e. only after the same "human-approved +
  revalidated" gate that already protects `create_purchase_request` — no
  new path into it.
- **Deployment prerequisite, not code**: note in this file's header comment
  that going live requires SPF/DKIM/DMARC alignment on the sending domain
  (start DMARC at `p=none`, tighten to `p=reject` after monitoring) — this
  is an infra/DNS task for whoever owns the sending domain, out of scope for
  Kiro to implement.

**Test:** `vendor_email_enabled=False` (default) → assert no send attempt
occurs even on a successful `execute_purchase`. With the flag mocked/forced
`True` in a test-only config → assert the templated content contains only
whitelisted fields (no agent free-text substring possible even if injected
into upstream evidence), and that calling `execute_purchase` twice with the
same `proposal_hash` sends at most once.

---

## Phase 9 — Agent memory: preference-learning store (Gap 9)

Table already added in Phase 1 (`agent_memory_signals`).

- Write path: hook `submission/graph/nodes.py`'s `handle_decision` (human
  REJECT/REVISE with a comment) to insert a signal
  (`entity_type="vendor"`, `entity_key=vendor_id`, `signal_type="human_rejected"`,
  `signal_text=<comment>`, `source_case_id`). Also hook wherever vendor
  performance (`on_time_rate`) is read in `tools/vendors.py` to log a
  `signal_type="late_delivery"` entry when a vendor underperforms its
  recorded reliability on an actual case outcome, so the store accumulates
  real signal over time rather than only human commentary.
- Read path: new `summarize_memory_for_prompt(sku, warehouse_id, candidate_vendor_ids)`
  helper (co-locate with `tools/vendors.py` or a new `tools/memory.py`) that
  composes a short natural-language digest of relevant prior signals.
- Wire the digest into `submission/prompts/strategist.py`'s
  `build_user_message` (`strategist.py:82-105`) as an **additive** evidence
  field — it must inform the LLM's reasoning, never bypass the deterministic
  gates (`_validate_recommendation`, budget override, eligibility filter)
  that already gate the final pick. Memory changes what gets *proposed*,
  never what gets *approved*.
- Explicitly not built here: no scheduler, no auto-triggered reminders —
  that's Upgrade 1. This phase only guarantees Upgrade 1 will have
  somewhere durable to write to later without a schema change.

**Test:** new `test_phase9_agent_memory.py` — reject a proposal with a
comment, confirm a signal row is written; run a second case for the same
sku/vendor, confirm the strategist's prompt payload includes a memory
digest referencing the prior rejection (assert on the prompt-building
function's output, not on live LLM behavior).

---

## Phase 10 — UI: reload-safe deep links + BLOCKED reasoning surfaced

- `submission/ui.py`: sync `case_id` and `view` into `st.query_params` (zero
  usage today, confirmed) whenever they change, and read them back on load
  to restore context after a hard reload — same session-state variables
  that already exist (`ui.py:118-119` etc.), just mirrored into the URL.
- Add a `_render_blocked_reasoning` screen section (parallel to the existing
  `_render_no_action_reasoning`, `ui.py:404`) that renders the per-vendor
  breakdown from Phase 3's enhanced BLOCKED detail, and a
  NEEDS_INFORMATION-specific render that hosts Phase 2's correction form.

**Test:** manual/UI check — reload the case screen mid-session, confirm the
same case reappears instead of falling back to the watchlist (this is a
Streamlit UI behavior, not easily unit-tested; verify by running the app).

---

---

## Follow-up pass, 2026-09-06 (after Phases 1-10)

Four items from `test_report.md`'s "Known limits" were closed:

| Item | Implementation |
|---|---|
| Ambiguous-demand `NEEDS_INFORMATION` was terminal | `_await_window_choice` (workflow.py) + `nodes.apply_window_choice` + `routes.route_after_window_choice`, bounded by `config.max_info_retries`. Re-enters at `compute_risk`, deliberately **not** `assess_demand` — re-running the model would re-derive the judgment the human just overrode and could set `ambiguous` back to True, looping forever. |
| No rollback/cancel | `tools.execution.cancel_purchase_request`, guarded on `PENDING` and on `vendor_send_status != 'SENT'`; new `cancelled_at`/`cancelled_by`/`cancel_reason` columns plus `database/migrate.py` (idempotent, additive) so an existing database is not wiped to gain them. |
| No CLI pending list | `app.py pending`, reusing `portfolio.list_pending_cases` so the CLI and UI cannot report different queues. Also hoisted `compile_graph()` and thread-id resolution out of that function's per-case loop (new `workflow.latest_thread_ids`) — it was rebuilding the whole graph and opening a fresh checkpoint connection per pending case, on a path the Streamlit sidebar re-runs on every interaction. |
| No edit at approval | `nodes.apply_human_edit` + `ApprovalDecision.edited_offer_id`, routed `await_approval` → `apply_human_edit` → `draft_proposal` so quantity, totals, budget line and hash are recomputed and `review_policy` runs again. Restricted to `vendor_options.eligible_options`; **quantity is deliberately not editable** because it is sized per supplier from that supplier's lead time by `economics.size_order_quantity`, so switching supplier re-sizes it correctly and a typed override would reintroduce the hand-computed figure this system exists to remove. |

Also closed in the same pass: the Policy Reviewer was reviewing vendor
economics without being given the computed per-vendor comparison the
Strategist already had (`prompts/policy.py`); revalidation failures reported
a generic label instead of the actual shortfall (`graph/revalidation.py`); a
bounced approval rebuilt an identical-looking screen with no explanation
(`ui.py`); and "order placed" was asserted from in-memory state rather than
verified against `purchase_requests` (`portfolio.get_purchase_request`).

**New gaps found while doing the above** — all recorded in
`GAP_NEEDS_INFORMATION.md`, none yet fixed: no reorder guard
(`confirmed_inbound` is never written, and no open-order lookup exists, so a
re-run can order the same stock twice); `CONFIRMED` is unreachable, so an
order's lifecycle is one state deep; approved orders never reserve budget;
email cannot be tested without live Gmail credentials (hardcoded SMTP host,
unconditional TLS/auth). The first two are one chain with Upgrade 4 — a
supplier reply is what would set `CONFIRMED`, which feeds `confirmed_inbound`,
which is what suppresses the duplicate order.

---

## Suggested build order for Kiro

Phases 1 → 2 → 3 → 4 → 5 → 6 → 7 → 9 → 8 → 10. Rationale: Phase 1 unblocks
everything; 2/3/4/5 are independent of each other and of 6/7 (parallelizable
if Kiro supports it); 6 must land before 7 (auto-redraft depends on the
hardened policy checks); 9 before 8 is arbitrary but both are independent of
the rest; 10 last since it's polish on top of 2/3's new states.

---

## Deferred monitor-cost plan (decision recorded 2026-09-13; do not implement yet)

When this work is authorised, limit its scope to these two layers:

1. **Skip unchanged inputs before candidate screening.** For each
   SKU/warehouse pair, compare a durable fingerprint of inventory, recent
   sales, vendor offers, and applicable policy against the fingerprint from
   the last completed scan.  If it matches, do not re-screen the pair.
2. **Skip unchanged terminal candidate outcomes before graph execution.** For
   a candidate that previously ended `NO_ACTION`, `BLOCKED`, or was deferred,
   compare the current relevant-input fingerprint with its stored outcome
   fingerprint.  If it matches, record a skipped/unchanged result rather than
   invoke the graph or resend a notification.

Explicit non-goals: risk-based scan intervals, a per-run/per-day model-call
budget, and provider token/cost telemetry.  These are optional later
optimisations, not prerequisites for the selected change-driven scanning and
outcome-deduplication work.
