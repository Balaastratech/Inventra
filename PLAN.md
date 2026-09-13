# Inventra — Working Plan

Living document. Updated as decisions get made.
Started: 2026-08-30

---

## 0. Session intent (captured from user)

Build the Inventra agentic stockout resolution system from scratch, planning first:

- Understand the problem fully before writing code
- Break the workflow down to its lowest level (product info, stock info, sales velocity + observation counts, etc.)
- User's initial instinct: **one agent per lowest-level step**
- Treat the provided `tools/` package as an *example*, not a mandate — we may write our own tools
- Work **one phase at a time**, with Q&A before each phase
- Ask the user for every decision that needs making

---

## 1. Environment (verified 2026-08-30)

| Package | Version |
|---|---|
| langgraph | 1.2.8 |
| langchain-core | 1.4.8 |
| pydantic | 2.13.4 |
| langchain-openai | 1.3.3 |
| langchain-google-genai | 4.2.6 |
| pytest | 9.1.1 |
| **langgraph-checkpoint-sqlite** | **NOT INSTALLED** — needed for durable pause/resume |
| langchain (umbrella) | not installed (fine, we use langchain-core) |
| nbclient / jupyter | not installed |

Python 3.13. Windows / PowerShell.

LangGraph 1.2.8 means the **modern HITL API**: `interrupt()` called inside a node,
resumed with `Command(resume=...)`, backed by a checkpointer. The older
compile-time `interrupt_before` / `interrupt_after` hooks still work but are less
flexible. ([LangGraph interrupts docs](https://docs.langchain.com/oss/python/langgraph/interrupts),
[HITL docs](https://docs.langchain.com/oss/python/langgraph/human-in-the-loop))
Content rephrased for compliance with licensing restrictions.

---

## 2. What the challenge actually requires (from the .docx brief)

Five terminal outcomes: `NO_ACTION`, `NEEDS_INFORMATION`, `BLOCKED`,
`AWAITING_APPROVAL`, `PURCHASE_REQUEST_CREATED`.

Hard constraints that are directly graded:

- LangGraph, explicit typed state, conditional routes
- **Two to four agents.** More agents explicitly earn no extra marks.
- Authoritative arithmetic comes from tools, never the LLM
- All critical agent outputs Pydantic-validated
- Max **one** revision cycle; max **two** model attempts per agent node
- Approval is a real interrupt, not text classification
- Approval bound to an exact proposal version/hash
- Revalidation immediately before the write
- Idempotent, transaction-safe write
- No generic SQL / direct DB access exposed to agents
- Audit events carry structured summaries, not chain-of-thought

Rubric weight: Graph/approval/execution 20, Failure+idempotency 20,
Decomposition 15, Agent+tool boundaries 15, State+contracts 15,
Testing+observability 10, Clarity 5.

---

## 3. OPEN CONFLICT: agent granularity

The user wants one agent per lowest-level step. That would be roughly:

    product-agent, stock-agent, sales-agent, risk-agent, vendor-offer-agent,
    vendor-perf-agent, option-builder-agent, budget-agent, policy-agent,
    approval-agent, execution-agent   → ~11 agents

This conflicts with the brief on three separate counts:

1. **Hard cap.** "Use two to four agents." Checked via agent charter + tool
   permission matrix. 11 agents fails the constraint outright.
2. **Explicit anti-pattern.** Brief: "More agents do not earn more marks."
   And: "WHAT DOES NOT EARN MARKS — more agents […] Complexity must solve a
   stated failure or business requirement."
3. **Unanswerable justification.** Every agent must answer: "Why does this agent
   need an LLM instead of ordinary code?" A `get_product_info` agent cannot
   answer it — that step is one indexed SQLite read with a typed result. Wrapping
   it in an LLM adds latency, cost, and a hallucination surface, and removes zero
   ambiguity.

### Resolution proposed

The user's decomposition instinct is **correct** — it is just the wrong unit.
Decompose to the lowest level as **nodes and tools**. Group into agents by
**type of judgment required**, not by data-fetch step.

    Fine-grained  →  deterministic NODES + TOOLS   (product, stock, sales,
                                                    risk math, offers, perf,
                                                    options, budget)
    Coarse-grained →  AGENTS, one per judgment call

Proposed 3 agents (see §4). Awaiting user confirmation.

---

## 4. Proposed architecture (DRAFT — not yet approved)

### Agents (3)

**A1 — Intake & Demand Interpreter**
Judgment it owns: the request is ambiguous or incomplete; the 7-day and 30-day
velocities disagree and something must decide which window to trust and say why.
(Observed real case: AC-003 had 7d=1.71 vs 30d=1.93. Picking one is a judgment.)
Tools: `get_product`, `get_stock_position`, `get_sales_velocity`.
No math. Emits `DemandAssessment` with chosen velocity + written justification
+ evidence IDs.

**A2 — Replenishment Strategist**
Judgment it owns: cost vs speed vs risk buffer. Deciding whether 840 extra rupees
buys enough stockout margin to be worth it. Writing an explanation a planner can
push back on.
Tools: `list_vendor_offers`, `get_vendor_performance`, `build_vendor_options`
(reads the computed options; never recomputes cost or arrival).
Emits `ReplenishmentProposal` (Pydantic, hashed).

**A3 — Policy Reviewer**
Judgment it owns: reading `policy.md` prose and deciding whether *this* evidence
bundle satisfies *that* guidance; whether a concern is a hard block or a
labelled exception. Independent second opinion on A2.
Tools: `get_policy_guidance`, `get_budget_position`. Read-only. Cannot edit the
proposal — only returns a verdict + concerns.
Emits `PolicyReview`.

### Deterministic nodes (no LLM)

`validate_request`, `compute_risk`, `route_*`, `build_approval_packet`,
`human_approval_gate` (interrupt), `revalidate`, `execute_write`, `audit`.

### The write boundary

Only `execute_write` touches `create_purchase_request`. It is a plain Python
function. No LLM has the tool bound. Reached only via
approval → revalidation pass.

---

## 5. Confirmed findings from the starter package (investigated 2026-08-30)

Ran `test_tools.ipynb` end to end (all 11 cells green, DB restored afterward).
Verified against source. These are real defects/mismatches we must handle:

1. **`revalidate_approved_proposal` is a stub.** `tools/execution.py` has a
   `# TODO` and returns all-True unconditionally. Ignores the hash. Never reads
   the DB. **Scenario 7 cannot pass against it.** We must implement real
   revalidation ourselves.
2. **Boundary leak.** `build_tool_lookup()` exposes
   `revalidate_approved_proposal` to agents. Only `create_purchase_request` and
   `append_audit_event` are gated behind `include_write_tools=True`. Brief says
   revalidate is deterministic-node-only.
3. **Freshness threshold disagrees 4 ways.** Brief: 2 hours. `.env.example`
   `DATA_FRESHNESS_THRESHOLD=2` (hours). `policy.md`: 2 days.
   `tools/inventory.py` `STALE_THRESHOLD_HOURS = 48`. Must be one config value.
4. **Scenario 11 unpassable as seeded.** `get_sales_velocity` flags
   `INSUFFICIENT_DATA` only below 3 observations. AC-005 is seeded with 6 and 14.
   Tool returns clean data; fixture expects the error.
5. **Scenario 4's trap is absent.** AC-003 cheapest (V-CHEAP) arrives 2026-09-06,
   projected stockout 2026-09-08 → `meets_deadline: True`. Both vendors eligible
   and on time. The brief's stated condition (cheapest arrives *after* stockout)
   is not in the data.
6. **`tools/workflow.py` is training wheels, not agents.**
   `recommend_vendor_option` is `min()` plus an if/else with template strings.
   `draft_replenishment_proposal` hardcodes `policy_passed=False` and
   `vendor_evidence_ids=[]`. Useful as an output-shape reference and a
   deterministic fallback. If we just wire these up we submit a system with
   zero agents.
7. **Notebook's revision forks the case ID.** It passes `case_id + "-REV1"` as
   `case_id`, so the purchase request landed under `CASE-AC003-DEL01-REV1` while
   the audit event landed under `CASE-AC003-DEL01`. They do not join. A revision
   must bump a **proposal version**, keeping `case_id` stable.
8. `datetime.utcnow()` used throughout, deprecated on 3.13, all naive. Do not
   mix in aware datetimes.
9. `record_human_review` returns `next_status=AWAITING_APPROVAL` for an
   **APPROVED** decision. Do not route on its labels.
10. Idempotency **works**. Verified: second call with same key returned
    `created=False`, same `request_id`, one row.

---

## 6. Decisions needed from user

All ten resolved 2026-09-04 (see §7). Not re-litigating unless something breaks.

| # | Decision | Resolution |
|---|---|---|
| D1 | Agent count / granularity | 3 agents (§4), fine granularity as nodes |
| D2 | Reuse provided `tools/` or rewrite | Reuse read tools (inventory/sales/vendors/policy), rewrite `execution.py::revalidate_approved_proposal` (currently a hardcoded-True stub — fails scenario 7 as-is), ignore `workflow.py` (reference-only template, not wired into the real graph) |
| D3 | LLM provider | **Revised 2026-09-04: no Anthropic.** `MODEL_PROVIDER=gemini` (default) or `openai`, user's choice, no third option. Gemini via a plain AI Studio API key (not Vertex — user has Vertex set up for other projects, but this submission should run on any grader's machine with one env var, not a GCP project + IAM). Per-task model picked from the live Sep-2026 Gemini lineup, not guessed: `gemini-3.5-flash-lite` for Intake and Strategist (narrow, tool-grounded judgment), `gemini-3.5-flash` for Policy Reviewer (reads policy.md prose + full evidence bundle, worth the ~5x cost step up from flash-lite). Explicitly avoids `gemini-2.5-flash` (deprecated 2026-10-16). OpenAI fallback: `gpt-4o-mini` for all three. Implemented in `submission/config.py`. |
| D11 | Email notifications + approval channel (added 2026-09-04, user request) | Gmail SMTP (App Password, stdlib `smtplib` — no OAuth complexity). Two things, both required, working together: (1) **notifications** at `AWAITING_APPROVAL` / `BLOCKED` / final outcome, sent by a deterministic function (never an LLM tool — same boundary as `append_audit_event`); (2) **reply/link-based approval** (user's explicit choice over notify-only): the approval email contains signed one-click Approve/Reject links. Design: `GET` renders a confirmation page (never mutates state — email clients/security scanners prefetch links, so a bare `GET` that approves would be a real bug), the confirm page's `POST` is what actually calls `Command(resume=...)` on the paused thread. Token = HMAC-signed (`APPROVAL_TOKEN_SECRET`, stdlib `hmac`, no new dependency) over `case_id + proposal_hash + decision + expiry`, single-use, expires per `APPROVAL_TIMEOUT_MINUTES`. Binding the token to `proposal_hash` means a stale link from an earlier revision fails closed automatically — this doubles as extra scenario-7 protection, not just convenience. Runs as a small local server (`submission/graph/approval_server.py`, Phase 3/6) sharing the same `SqliteSaver` checkpoint file as the CLI, so it can resume a thread the CLI paused, per LangGraph's documented cross-process resume model. Both the Streamlit approval screen (D7) and email links stay live at once — same underlying `Command(resume=...)` call, whichever arrives first wins, the other is rejected as already-used. Config + `.env.example` in `submission/.env.example`. |
| D4 | Freshness threshold value | ~~2 hours, single constant in `submission/config.py`. Brief (`authority: primary_requirements`) overrides `policy.md`'s stale "2 days" wording and `tools/inventory.py`'s hardcoded 48h.~~ **D4-REVISED (2026-09-06):** project owner's explicit call — policy.md is authoritative for this one value, not the brief. `data_freshness_hours = 48.0` (2 days), configurable via `DATA_FRESHNESS_HOURS` env var per the brief's own "keep thresholds configurable" instruction. Rationale: the Policy Reviewer agent reads policy.md's "2 days" as evidence every run; enforcing 2h in code while the agent's own prompt says 2 days would have the agent reasoning against a fact the system contradicts. |
| D5 | Fix seed data for scenarios 4 & 11 | Additive fixture script (`submission/tests/seed_extra.py`) that inserts new rows for a "cheapest-arrives-late" vendor case and a true `<3`-observation SKU. Never edit the provided `database/inventra.db` seed or `seed.py` in place. |
| D6 | Checkpointer | `SqliteSaver` (`langgraph-checkpoint-sqlite`, not yet installed — confirmed via `pip show`). Single-process app; Postgres would be over-engineering for a student submission. |
| D7 | App surface | CLI (`app.py`) is the primary, required entry point. Add one minimal single-page Streamlit view *only* for the human-approval step (show proposal + evidence + Approve/Reject/Revise buttons) — this is the one place a plain terminal prompt is a genuinely worse demo. **No multi-page dashboard, no analytics, no extra screens** — the rubric explicitly excludes "a large dashboard" from earning marks. |
| D8 | Revision semantics | Version bump on stable `case_id` (`proposal_version` increments; `case_id` never forks — the notebook's `case_id + "-REV1"` bug is not repeated) |
| D9 | Over-budget behaviour | Default: `BLOCKED` (fail closed) with the exact shortfall amount in the reason. Bounded exception path: Policy Reviewer may label it a "flagged exception" only if within a small tolerance defined in config (e.g. ≤5% over) — human approver still has final say, one revision cycle max. |
| D10 | Where to put our code | `submission/` per brief §7, at repo root alongside the provided `database/`, `tools/`, `domain/`, `fixtures/` |

---

## 7. Decision log

- **2026-09-04** — All D1–D10 resolved per table above, based on: (a) the challenge brief being the sole authority for requirements (per its own `authority: primary_requirements` front-matter — not `policy.md`, not the reference PDFs' example architecture, not `tools/workflow.py`); (b) the user's explicit instruction not to just copy the starter package's reference agent flow (`Investigator`/`Sourcing`/`Policy-Proposal` shown in the supplied interface PDFs, using `recommend_vendor_option`/`draft_replenishment_proposal`) — that reference architecture is an *example*, and wiring it up as-is would submit a system with zero real agent judgment (workflow.py's `recommend_vendor_option` is literally `min()`); (c) web research confirming current (Sep 2026) LangGraph best practice for `interrupt()`/`Command(resume=...)` + `SqliteSaver`, and one important gotcha below.

### Research finding worth flagging (2026-09-04)

LangGraph's built-in node `RetryPolicy` **does not reliably catch `pydantic.ValidationError`** (open upstream issue). The brief's "max two model attempts per agent node, then fail closed" requirement (scenario 6) must **not** be implemented via `RetryPolicy` — implement it as an explicit conditional edge: call agent → validate → on `ValidationError` route back to the same node once with the error appended to context → on second failure route to `finalize_blocked` with a structured error, never a third attempt. Source: [LangGraph interrupts docs](https://docs.langchain.com/oss/python/langgraph/interrupts), [structured output docs](https://docs.langchain.com/oss/python/langchain/structured-output), and the open GitHub issue on retry policies vs Pydantic errors (langchain-ai/langgraph#6027).

---

## 8. Roadmap (phase-by-phase, one at a time, gated on user check-in)

- [x] **Phase 0** — Understand + decide. D1–D11 answered (§6/§7). Environment verified.
- [x] **Phase 1 — Contracts** (done 2026-09-04)
  - `submission/config.py` — frozen-dataclass config: freshness threshold, target-cover bounds, retry caps, budget tolerance, checkpointer path, LLM provider + per-agent models, email + approval-server settings
  - `submission/state/state.py` — typed `CaseState` covering all 7 minimum categories, reusing `domain.tool_models` types instead of redefining them; `create_initial_state()` factory
  - `submission/agents/models.py` — Pydantic output models: `DemandAssessment`, `ReplenishmentRecommendation`, `PolicyReview` (all `extra="forbid"`, narrow judgment-only fields — arithmetic stays in deterministic code, agents never emit the full `ReplenishmentProposal` or its hash directly)
  - `submission/.env.example` — new env vars this phase introduced (LLM provider, email, approval server)
  - `submission/tests/test_phase1_contracts.py` — 5 tests, passing: config values, initial-state shape, and proof the 3 new models actually reject bad input (not just accept good input)
  - No graph, no LLM calls, no UI yet — just types that compile and validate
- [x] **Phase 2 — Deterministic skeleton** (done 2026-09-04)
  - `submission/graph/workflow.py` — full `StateGraph`, all nodes wired, agents pluggable via `nodes.set_agents()` (stubbed by default, `submission/agents/stubs.py`)
  - `submission/graph/routes.py`, `submission/graph/nodes.py`, `submission/graph/support.py` (audit + retry-once-then-fail-closed helper), `submission/graph/hashing.py`
  - All 5 terminal states reachable with zero LLM cost; scenario 1 (healthy stock → NO_ACTION, no vendor/write calls) passing
- [x] **Phase 3 — Approval + execution boundary** (done 2026-09-04)
  - `langgraph-checkpoint-sqlite` installed; `SqliteSaver` wired in `compile_graph()` with `JsonPlusSerializer(allowed_msgpack_modules=True)` (all checkpointed types are our own trusted models)
  - `interrupt()` isolated in its own tiny `_await_approval` node (nothing side-effecting before it, so a resume never re-runs the email/audit that already fired — see workflow.py docstring)
  - `submission/graph/revalidation.py` — real revalidation (hash/stock-freshness/offer/budget), replacing the provided stub
  - `submission/notifications/{tokens,email}.py`, `submission/graph/approval_server.py` — D11's email notifications + signed single-use reply/link approval, GET-never-mutates / POST-executes split, FastAPI (already installed, no new dependency)
  - `submission/app.py` — minimal CLI (`run` / `resume`), enough to drive and prove the graph
  - Scenarios 1, 3, 4, 5, 7, 8, 9, 10, 12 passing (15 tests total, `submission/tests/test_phase2_3_graph.py` + `test_phase3_email_approval.py`)

  **New defects found this phase (all fixed, none touch the provided starter package):**
  - *Starter package:* `build_vendor_options()`'s order-quantity formula (`max(moq, available_units*0.5)`) is decoupled from `target_cover_days`/velocity — sizes bigger orders for warehouses that already have more stock. Worked around in `nodes._size_quantity()`, a submission-owned correction applied after calling the provided tool (tool itself untouched). Documented inline in `nodes.py`.
  - *Starter package / fixtures:* AC-001's seeded numbers give ~13-15 days real coverage, not the fixture's claimed ">20 days" — still usable as a healthy-stock case, just at a lower target_cover_days (7, not the 14 default). Noted for `test_report.md`.
  - *Our own code, caught by the Phase 3 test suite itself:* (1) `invoke_agent_with_retry` was accumulating attempts in `state["retry_counts"]` across separate node *visits* within one case, not per-visit — a node hit a 3rd legitimate time (e.g. after the revalidation-retry bounce) would wrongly fail closed even though every individual call had succeeded; fixed to track attempts locally per call, state is audit-only now. (2) `invalidate_approval` didn't clear `error_code`/`error_detail` before looping back to `compute_risk`, so every `route_after_*` that checks "is error_code set" would misfire on the *next* node's routing using the *previous* failure's leftover error — fixed by clearing both fields in `invalidate_approval`. (3) the over-budget exception-tolerance check divided by `budget.remaining`, which breaks (crashes or flips sign) once a warehouse's remaining budget is already zero or negative; fixed to measure the overage against `budget.budget_amount` instead, which is always a stable, positive denominator.
  - All three of the "our own code" bugs were caught by `test_budget_change_during_pause_invalidates_approval` alone — reinforces Phase 0's bet that the deterministic skeleton is where the real risk lives, not the agent prompts.
- [x] **Phase 4 — Real agents** (done 2026-09-04)
  - `submission/agents/llm.py` — chat model factory, Gemini (`langchain-google-genai`, already installed) default / OpenAI fallback, per-role model from `config.active_models()`, no Anthropic (D3)
  - `submission/prompts/{demand,strategist,policy}.py` — versioned (`VERSION = "v1"`) system prompts + evidence-only user messages; every prompt explicitly states that vendor names/notes/product text are untrusted data, never instructions
  - `submission/agents/real.py` — the three real agent functions, same `(state, last_error) -> Model` shape as the Phase 2/3 stubs, swapped in via the existing `nodes.set_agents()` pluggable-agent mechanism (no changes needed to `nodes.py` or `workflow.py` themselves)
  - `submission/agents/wiring.py` — one-time wiring shared by `app.py` and `approval_server.py`: real agents if a key is configured for `MODEL_PROVIDER`, Phase 2/3 stubs otherwise (prints a warning, doesn't crash) — so the CLI runs out of the box either way
  - **`support.invoke_agent_with_retry` extended**, not replaced: (1) broadened to catch `Exception` generally, not just `pydantic.ValidationError` — a real LLM call also fails with provider timeouts/rate limits/parser errors that aren't `ValidationError` subclasses, and the brief lists "tool timeout" and "invalid model output" as the same class of failure (design.md §7); (2) added an optional `validate` callback for semantic checks beyond schema shape — used in `nodes.py` to catch an agent inventing an `offer_id`/`proposal_id` that doesn't exist, which used to crash `draft_proposal` downstream with a raw `StopIteration` instead of triggering the repair loop
  - Scenario 6 (one repair attempt, then fail closed) now proven against real exception paths, not just the stub's always-valid path — `submission/tests/test_phase4_agents.py`: repair-then-succeed, two-failures-then-blocked, and semantic-hallucination-then-repair, all driving the actual graph (not just the helper in isolation)
  - A live, opportunistic integration test calls the real Gemini/OpenAI API and asserts a valid `DemandAssessment` comes back — `pytest.mark.skipif` when no key is configured, so it never fails the suite for a grader without one, but proves the real path once a key exists

  **D3 revised again (2026-09-05): Vertex AI is now live and the default.** Project owner asked to reuse an existing GCP project instead of an AI Studio key. Checked the Organizer/Second-Brain project first (as asked) — its own docs say it calls the plain Gemini API directly, zero GCP project, so there was nothing to reuse there. Project owner then gave `gen-lang-client-0491543355` directly (an auto-provisioned "second brain" project, ADC already configured on this machine — `gcloud auth application-default login` had been run before).

  **Real problem hit and fixed:** `langchain-google-vertexai`'s `ChatVertexAI` (and even a raw `import vertexai`) hung for 4+ minutes in this dev sandbox — `google.auth` + `gcloud` both worked fine and fast (same credentials, same project), so it wasn't auth or the project being misconfigured. `google-cloud-aiplatform` imports its *entire* generated API surface (Vizier, Tensorboard, Feature Store, RAG, dozens of services) and appears to default to a gRPC transport that stalls in this sandbox specifically. Switched to the newer `google-genai` unified SDK (`Client(vertexai=True, project=..., location=...)`, HTTP-based) — confirmed with a live call (~10-25s cold, real "OK" response) and rewired `submission/agents/llm.py` around it (`call_structured()`, one function for all three providers now, replacing the old per-provider `get_chat_model()`). If a future `langchain-google-vertexai` release fixes the underlying hang, swapping back is contained to `_call_vertex()` in that one file.

  **Also found by actually running the real agent against a live case** (not caught by review — the model itself flagged it by correctly refusing to guess): the Policy Reviewer prompt only forwarded `stock`/`sales`/`budget`/the proposal, not the full evidence bundle policy.md's own "Required evidence before review" checklist demands. First real run blocked on "missing `retrieved_at` for the freshness check"; second blocked on "missing the actual vendor offer objects." Fixed by forwarding everything on that checklist (`product`, `stock`, `sales`, `risk`, `vendor_offers`, `vendor_performance`, `budget`) — third run reached a real, evidence-cited `AWAITING_APPROVAL` with a genuinely well-reasoned trade-off explanation (chose the $1080-more-expensive, faster vendor because it leaves ~6.7 days of stockout buffer vs. ~1.7 for the cheap one), then approved cleanly to `PURCHASE_REQUEST_CREATED`. This is worth keeping in `test_report.md` as an example of the model behaving exactly as intended (fail closed on insufficient evidence) rather than a bug being "fixed away."

  **Test-isolation bug found and fixed along the way:** `approval_server.py`'s `wire_agents()` flips a process-wide flag once real agents are configured, which is correct for a real server process but was leaking into the test suite — `test_phase3_email_approval.py`'s approval-link test triggered it, silently switching every *later* Phase 2/3 test in the same pytest session from fast deterministic stubs to slow live LLM calls. Fixed by monkeypatching `wire_agents` to a no-op in that one test file (it only tests token/approval mechanics, not agent judgment).

  `submission/.env` (gitignored, not committed) now has `MODEL_PROVIDER=vertex` + the real project ID. `submission/.env.example` documents all three paths (vertex / gemini API key / openai) for anyone without this GCP project.
- [x] **Phase 5 — Remaining scenarios + tests** (done 2026-09-05)
  - `submission/tests/test_phase5_remaining_scenarios.py`: scenario 2 (missing sku/warehouse_id, out-of-range target_cover_days — all confirm zero DB queries happened before the block), scenario 4 (explicit assertion that a non-cheapest pick populates `cost_vs_speed_trade_off`), scenario 11 (insufficient sales history)
  - Scenario 11 needed its own additive fixture (`seed_extra.INSUFFICIENT_HISTORY_CASE`, AC-003/DEL-09 with only 2 sparse sales rows) — confirmed AC-005 as seeded has 6-14 observations in both windows, not the <3 the scenario requires (PLAN.md defect #4)
  - **All 12 acceptance scenarios now have a passing test.** Full suite: 24/24 passing (`submission/tests/`), ~193s (dominated by the one live Vertex call in Phase 4's tests; everything else uses fast stub agents)
- [x] **Phase 6a — Operator UI + the reads it needs** (done 2026-09-05)

  **Why this moved ahead of the docs.** Reviewing the system end to end
  surfaced a gap that isn't structural: the brief's premise is a planner
  responsible for hundreds of products who *cannot notice a stockout in
  time*, and our system required them to already know the SKU and warehouse
  before it could help. Every tool in the package answers "how bad is THIS
  product here"; nothing answered "which ones should I look at". The
  detection step is the part that makes the workflow non-manual, so it was
  built before any further documentation of a workflow that couldn't be
  entered. Same reasoning for reading the audit trail back: we were writing
  197 audit rows and had no code path that read one, while the brief's own
  success criterion is that outcomes can be *reconstructed*.

  - `submission/portfolio.py` — operator read models, deterministic, never
    exposed to an agent (justified inline per brief §4's new-tool rules):
    - `scan_portfolio()` — the watchlist. Every stocked product/warehouse
      pair, ranked worst-first, each with a plain-language headline. Ranks
      on the *worse* of the 7-day and 30-day trends so an optimistic window
      can't bury a product, and flags when the two disagree. Only one new
      SQL statement in the whole submission (discovering which sku/warehouse
      pairs exist — there is no `warehouses` table in the provided schema,
      warehouse_id is only ever a column); every number after that comes
      from the provided tools unmodified, so the watchlist's arithmetic is
      the same arithmetic the graph uses when the case is opened.
    - `read_case_history()` / `list_cases()` — the audit trail as a readable
      timeline. Plain lookup table, deliberately not a model call: turning a
      known event_type into a known sentence needs no judgment, and this is
      the one place a hallucination would directly mislead an auditor.
    - Unassessable products are shown with the reason, never dropped —
      hiding one is the only outcome that could cause a real stockout.
  - `submission/ui.py` — the operator screen (`streamlit run submission/ui.py`).
    Three views, each one a step of the planner's actual job: **watchlist**
    (which products need me), **case** (what's recommended, do I approve),
    **history** (what did we decide before). Still not a dashboard — no
    charts, no KPIs, no analytics; each view exists because a required
    workflow step was otherwise unreachable, which is the D7 line the rubric
    draws. Non-technical vocabulary throughout ("product", "supplier", "days
    of stock left"); identifiers and the proposal hash live behind an audit
    details toggle. Calls the same `run_case` / `resume_case` / `load_case`
    functions as the CLI, so the two entry points cannot drift.
  - `submission/app.py` — added `load_case()` so the UI can show the full
    proposal, agent reasoning and policy review. The interrupt payload only
    carries what the CLI needs for a one-line summary.
  - **Two facts now on the approval screen that the system already computed
    and had never told the approver** (`ui._approval_notes`, presentation-only,
    no new arithmetic, kept as a standalone function so the approval email
    can reuse it):
    1. *Minimum-order overshoot.* Measured on AC-001/DEL-04: the shortfall
       is **1 unit**, every eligible supplier's minimum order is 5, so the
       approver is asked for **$1,100** to close a one-unit gap. Legitimate
       business call, but it has to be a visible one.
    2. *Disagreeing sales trends.* Same case: at risk on the 30-day trend,
       comfortably fine on the 7-day one. The whole buy-or-don't decision
       rests on which window the Demand agent chose, and the approver's
       signature was going on that choice without being told.

  **Revision cycle fixed — it was dead code.** `handle_decision` increments
  `revision_count` *before* `route_after_decision` reads it, and the route
  compared `>= config.max_revision_cycles` (1). So the very first REVISE
  scored 1 >= 1 and routed to `revision_limit_exceeded` → BLOCKED: zero
  revisions were possible and workflow.py's `"revise"` edge was unreachable.
  The brief's "maximum one revision cycle … graph test proves termination"
  therefore had nothing to prove and no test. Three changes, because fixing
  only the first would have produced a revision loop that did nothing useful:
  1. `routes.route_after_decision` compares `>` not `>=` (the counter is
     already incremented by the time the route runs).
  2. New `nodes.prepare_revision`: clears the recommendation/proposal/review
     being replaced but **keeps `approval_decision`**, because the approver's
     comment is the entire input to the revision.
  3. The revise edge re-enters at **`fetch_evidence`**, not `recommend_vendor`.
     A human pause is normally longer than the 2-hour freshness limit, so
     re-recommending against the pre-pause snapshot spent model calls on a
     proposal guaranteed to die at revalidation. Re-reading means a genuinely
     stale snapshot now blocks at intake with DATA_STALE, which is honest.
  - `prompts/_shared.render_approver_feedback()` + a Strategist prompt rule:
    the approver's comment now reaches the agent, in a section visibly
    separate from the evidence block. This is the one input in the system
    that *is* a legitimate instruction (a named human asked for a different
    answer) as opposed to database text that must never be read as one — so
    the trust boundary is stated to the model, not just commented in code.
    Its authority is explicitly narrow: it can redirect which eligible
    option is picked, never a computed number or a policy rule, both of
    which code re-checks afterwards anyway.

  **Test-isolation defect found and fixed (pre-existing, exposed by this
  phase's full-suite run).** The suite passed exactly once on a freshly
  seeded database and failed on every subsequent run. Two tests leave
  permanent marks and the `clean_state` fixtures only reset the checkpoint
  file: (a) the approval tests write real `purchase_requests` rows, and the
  idempotency key is deterministic (`proposal_hash:approver`), so the second
  run correctly got `created=False` and `assert created is True` failed —
  the write was behaving exactly as designed, the test was asserting against
  a dirty database; (b) `test_budget_change_during_pause_invalidates_approval`
  sets DEL-02's `spent_amount` to its full budget and never restores it, so
  on run 2 that case failed closed before reaching a human and
  `assert "__interrupt__" in result` failed. Fixed with
  `submission/tests/reset_db.py`, which re-applies the *provided* seed
  (`database/seed.py`, never edited) plus `seed_extra()` at the start of every
  test module. A submission graded on idempotency should not ship a suite
  that is only correct on first use. Verified by running the two affected
  modules twice back to back: 10 passed, then 10 passed again.

  - `submission/tests/test_phase6_revision_and_ui_reads.py` — 15 tests:
    both halves of the bounded revision (first REVISE re-runs and re-pauses;
    second terminates), the re-read-evidence guarantee, the comment
    surviving into both the prompt and the audit trail, the watchlist's
    coverage/ranking/plain-language/no-hidden-products contracts, the
    disagreeing-trends flag, the audit playback (ordered, readable, and
    asserted to contain no model reasoning fields), both approver warnings
    firing on AC-001/DEL-04 and *not* firing on AC-003/DEL-01, and a real
    `streamlit.testing.v1.AppTest` run of `ui.py` so a crash on load is a
    test failure rather than a silent outage.
  **Checkpoint serializer was on a deprecation path (found via log noise).**
  Every run logged `Deserializing unregistered type domain.tool_models.X from
  checkpoint. This will be blocked in a future version`. Cause:
  `compile_graph()` passed `JsonPlusSerializer(allowed_msgpack_modules=True)`
  with a comment claiming this allowed our whole module set. Reading the
  installed source, `True` is LangGraph's **permissive** mode — it
  deserializes any type and warns per type — and is byte-for-byte identical
  to passing nothing, so it opted into nothing while appearing deliberate.
  Two real consequences, not just noise: (a) the warning means a future
  LangGraph release blocks that path, at which point **every paused case
  fails to resume** — a silent upgrade-triggered break of the human approval
  gate, the single most load-bearing behaviour in this submission; (b) the
  serializer's own docs warn that an attacker able to write to the checkpoint
  database may trigger code execution on deserialize, and permissive mode is
  the wide-open setting — the old comment's "our own types are trustworthy"
  answered the wrong question, since the risk is what the *file* could
  contain. Fixed with `workflow.checkpoint_allowlist()`, which derives the
  44 model/enum classes from `domain.tool_models` + `submission.agents.models`
  rather than hand-listing them (a renamed model becomes an import error
  instead of a runtime resume failure). Verified: 0 warnings, and all 8
  pre-existing checkpoint threads written under the permissive serializer
  still read back with correct status and pause point, so the change is
  backward-compatible. Pinned by
  `test_checkpoint_allowlist_covers_everything_a_paused_case_stores`.

  - Full suite: **24 → 40 passing** (5 + 8 + 2 + 4 + 5 + 16 across the six
    test modules), ~10 min, and now repeatable rather than first-run-only.

  **Unrelated environment noise, deliberately not "fixed":**
  `RequestsDependencyWarning: urllib3 (2.7.0) or chardet (6.0.0.post1)/
  charset_normalizer (3.4.4) doesn't match a supported version!` comes from
  `requests`' own import-time version check against the user's global
  site-packages. Nothing in this submission imports `requests` directly (it
  arrives via the Google SDK chain) and nothing here is affected. Silencing
  it would mean changing pinned versions in a global Python install shared
  with the project owner's other work, so it is left alone and documented
  instead.

- [x] **Phase 7 — Decision quality + UI usability** (done 2026-09-05)

  Four fixes, in the order they were agreed. The first two were blocking use
  of the screen; the last two changed what actually gets ordered.

  **1. UI colours.** The first UI hand-rolled a `<style>` block with
  light-mode hex values (white card backgrounds, grey captions, pastel status
  pills) and never set a foreground colour, so under a dark theme the card
  text rendered white-on-white and was unreadable. There was also no
  `.streamlit/config.toml`, so the theme followed each viewer's OS setting and
  the app looked different on every machine. Fixed by deleting all custom CSS
  rather than patching it: `submission/ui.py` now uses only theme-aware
  primitives (`st.container(border=True)`, `st.metric(border=True)`,
  `st.badge` with Streamlit's semantic colour names, `st.caption`,
  `st.warning`) and contains zero hex literals and zero `unsafe_allow_html`.
  `.streamlit/config.toml` pins the theme so it is deterministic; flipping
  `base` to "light" needs no other change. Also added, while in there:
  `_render_no_action_reasoning()` (the NO_ACTION outcome showed nothing at
  all, so "no order needed" looked like the system had done nothing — it now
  shows units / days of cover / target and the reasoning), a "What each choice
  does" expander explaining the three decision buttons, and a per-run
  timeline (`read_case_history(case_id, trace_id)`) because a case_id
  accumulates every run and the screen was showing 39 steps spanning three
  separate investigations.

  **2. Per-run thread identity.** `thread_id` was exactly `case_id`, so a case
  had one checkpoint thread for all time. Once a case hit a terminal state,
  starting the same product again resumed the *finished* thread — a rejected
  product could never be re-examined. Invisible while the CLI was the only
  entry point and someone had to retype the SKU; a real bug the moment the
  watchlist gave people a button. Now `state.new_thread_id()` produces
  `<case_id>#<utc timestamp>` (fixed-width, so lexicographic order is
  chronological) and `workflow.latest_thread_id(case_id)` resolves a business
  id to its newest run — matching bare `case_id` too, so checkpoints written
  before this change stay resumable. `app.load_case` / `app.resume_case` take
  an optional explicit `thread_id` (the UI passes the exact thread it
  rendered, so a decision can't land on a newer run someone else started);
  `approval_server` got a `_thread_config()` helper for both GET and POST.
  `case_id` is unchanged and still what `audit_events` joins on, so history
  stays continuous across runs. Verified end to end: run AC-003/DEL-06 →
  paused → REJECT → BLOCKED → run again → paused again on a distinct thread
  with the same case_id.

  **3. Order quantity now accounts for lead time and fill rate**
  (`graph/economics.py`, replacing `nodes._size_quantity`). The formula sized
  to `target_cover x velocity - available`, i.e. cover starting *today* — but
  goods only start covering demand when they land, so every order this system
  wrote under-delivered its own stated target by exactly
  `lead_time x velocity`. Measured on AC-004/DEL-01 (velocity 2.9, available
  12, order 29): a 2-day lead time gave 12.1 days of cover against a 14-day
  target, a 5-day lead time gave 9.1 and went to **-2.5 units** before
  arrival. Now sizes to `velocity x (target_cover + lead_time) - available`
  and grosses up by the supplier's `fill_rate`, which was being fetched,
  passed into the prompt, and used for nothing (0.90 fill means a 29-unit
  order lands ~26).

  **This inverted which supplier is cheapest, which is the real finding.**
  Because quantity now depends on lead time, a slower supplier needs more
  units. On AC-004/DEL-01: Standard Supplier ($450/unit, 3-day lead) needs 41
  units = $18,450; FastShip ($500/unit, 2-day lead) needs 36 = $18,000. Once
  lead-time demand is counted, "cheap but slow" is not cheap, and the
  cost-versus-speed trade-off the brief describes partly dissolves on its own.
  It also made the old "$1,100 to close a 1-unit gap" MOQ example disappear —
  that gap was itself an artefact of the under-sizing, not a real situation.

  **4. The buffer premium is now a code gate, not a prompt request.** A live
  run produced this approver-facing sentence:

      "The recommended option (FastShip Inc.) costs an additional 450.0 but
       provides an extra day of buffer ... a justified investment"

  Two failures at once. The computed extra cost was **$1,450** — the model
  dropped a digit while narrating arithmetic handed to it correctly. And
  "justified" was asserted against nothing: one day of sales for that product
  is 2.9 x $450 = $1,305 even at an impossible 100% margin, so the cheapest
  option won under *every* assumption. v1 had already tried adding a
  `cost_per_extra_buffer_day` figure and asking the prompt to cite it; asking
  a model to respect arithmetic is not the same as enforcing it.

  `graph/economics.py` now computes, per option: `units_actually_needed`,
  `extra_units_forced_by_supplier_minimum`, `days_of_cover_funded_by_this_order`,
  `effective_cost_per_delivered_unit`, `carrying_cost`,
  `expected_stockout_cost`, `all_in_cost_per_day_of_cover`, and a **verdict**.
  `nodes._validate_recommendation` **refuses** a pick whose verdict is not
  acceptable, routing into the existing one repair attempt. The Strategist
  prompt forbids claiming an option is worth it on the model's own authority,
  and — the important part — forbids the model stating *any* number not copied
  verbatim from the evidence, because every figure a human sees is now rendered
  from the data by code.

  **Revised 2026-09-12 (D29): the gate was enforcing the wrong comparison.**
  The first version of this rule ranked options on `total_cost` and scored each
  one pairwise against the cheapest — verdicts `cheapest_option`,
  `premium_justified`, `premium_not_justified`,
  `costs_more_but_arrives_no_earlier`, `free_upgrade`, with a premium justified
  only when `cost_per_extra_buffer_day <=
  expected_value_of_one_extra_buffer_day`. That contradicted the sizing
  immediately above it: quantity is per-supplier because the cover target runs
  from *arrival*, so a slower supplier legitimately needs more units, and
  `min(total_cost)` therefore compared different-sized baskets and called the
  smaller one cheaper. On AC-004/DEL-01 it forced FastShip's 37 units at
  $18,500 over Standard's 42 at $18,900 — $510.20 vs $478.72 per unit actually
  delivered. Ranking is now `all_in_cost_per_day_of_cover`, with carrying cost
  and each option's own expected stockout cost inside the figure; verdicts are
  `best_value_option`, `within_value_tolerance`, `worse_value_option`. Full
  reasoning, the rejected shared-horizon alternative, and the three guards that
  keep the new metric honest are in DECISIONS.md D29.

  One module, three consumers, one set of numbers: the prompt renders it, the
  gate enforces it, and `ui._approval_notes` displays it. The notes used to
  re-derive the shortfall by hand and drifted the moment lead-time demand
  entered the sizing, firing a minimum-order warning on correctly-sized
  orders — they now read the computed fields.

  **The margin assumption is declared, not invented.**
  `config.assumed_gross_margin_rate` (default 0.25, env
  `ASSUMED_GROSS_MARGIN_RATE`) exists because `products` is
  `(sku, name, category, active)` — this schema has **no selling price and no
  margin**, so profit per unit is not derivable and the question "is a day of
  stock worth more than the premium?" cannot be answered from data alone.
  It is emitted next to every figure it affects and appears in
  `economics.caveats`, so a grader can change one env var and watch the
  verdicts move. It replaces v1's `daily_unit_cost_exposure`, which was
  `velocity x unit_price` — procurement spend labelled as "exposure", which
  invited the model to reason about it as revenue. Contribution is also now
  keyed to the *lowest* unit price across options rather than each option's
  own price: the money lost to an empty shelf doesn't depend on who you buy
  from, and per-option pricing let a dearer supplier appear to protect more
  value, partly justifying itself.

  **Test fallout, all legitimate:** AC-004/DEL-03's order grew past DEL-03's
  remaining budget, so the write-failure test's case now fails closed on
  budget before reaching a human — correct for the fixture literally named
  "Over Budget", but it no longer exercises the write step, so that test moved
  to AC-003/DEL-07. Three test helpers assumed `thread_id == case_id` and now
  resolve via `latest_thread_id`. The phase6 module grew to 21 tests: the
  economics gate, the refusal path exercised directly against
  `_validate_recommendation`, a regression guard asserting cover-after-arrival
  meets target across lead times of 2/3/5/7 days, the fill-rate gross-up, and
  the minimum-order overshoot tested against explicit inputs rather than a
  fixture whose arithmetic legitimately moved.

- [ ] **Phase 6b — Docs + diagram** (next)
  - `design.md`, architecture diagram, one agent charter per agent, the
    tool-permission matrix, `submission/README.md`, `test_report.md`, and the
    required "what we deliberately did not make agentic" note
  - The tool-permission matrix needs a written defence, not just an empty
    grid: our agents receive **zero** tools by construction (every fact is
    pre-fetched by deterministic nodes and rendered into the prompt). That is
    the strongest least-privilege answer available, but an all-empty matrix
    reads as "never did the tool-boundary work" unless the choice is argued.
    Should also record that `tools/langchain_tools.py`'s `build_tool_lookup()`
    leaks `revalidate_approved_proposal` to agents (§5 defect #2) and that we
    avoided it by never binding tools at all — that catch currently lives
    only in this file, invisible to a grader.
  - Must state plainly that **stockout cost in currency is not derivable
    from this schema**: `products` is `sku, name, category, active` — no
    selling price, no cost, no margin. `unit_price` is acquisition cost, so
    any "value at risk" figure built from it is not lost revenue. Saying so
    is a stronger answer than shipping a proxy dressed up as one.

- [ ] **Phase 8 — Remaining decision-quality items** (identified, not built)
  What's left from the operational review after Phase 7. Measured against
  seeded data, see §9. Items 1, 3 and 6 of the original list are done.
  1. **No safety stock.** 30 daily sales rows per SKU exist, so σ is
     computable; we take the mean and discard the variance, which implicitly
     targets roughly a 50% service level. Deferred deliberately: σ needs the
     raw daily rows, which means a new read beyond the provided tools, and
     lead-time demand was the larger error.
  2. **Eligibility blends punctuality with product quality.**
     `get_vendor_performance` gates on `mean(on_time_rate, fill_rate,
     quality_score) >= 0.90` and `build_vendor_options` uses that single flag
     to answer a *timing* question. Verified: on_time 0.85 / fill 0.97 /
     quality 0.99 blends to 0.937 and passes as "reliable" despite missing
     committed dates 15% of the time. The deadline gate should key on
     `on_time_rate`; keep the blend as a separate advisory score. (Phase 7
     already routes the *real* `on_time_rate` into the premium arithmetic, so
     the blend now only affects the eligibility filter.)
  3. **`expected_arrival` is `now + lead_time_days`**, a point estimate
     treated as certain. Phase 7's `probability_delivery_is_late` softens this
     in the economics, but the arrival date itself still implies calendar
     certainty and the schema holds no history of how late late deliveries
     are.
  4. **`emit_audit`'s failure path writes into `state["error_detail"]`**, the
     same field real failures use, so an audit hiccup can clobber a genuine
     error message (routes read `error_code`, so it won't misroute).
  5. **The test suite takes ~10 minutes**, dominated by one live Vertex call
     and six full database reseeds (one per module). Should be a fast default
     run plus an opt-in `--live` marker; the reseed could be session-scoped
     with per-test transactions rather than module-scoped.
  6. **`NEEDS_INFORMATION` is terminal** (see `GAP_NEEDS_INFORMATION.md`):
     the system can say what's missing but offers no way to supply it and
     continue the same case. Needs either an intake `interrupt()` mirroring
     the approval gate, or a UI form that starts a corrected run. There is
     also no `notify_needs_information` to match `notify_blocked` /
     `notify_awaiting_approval`.
  7. **Freshness threshold** (see `GAP_NEEDS_INFORMATION.md`): 2 hours is the
     brief's number and governs, but `tools/inventory.py` says 48h and
     `policy.md` says 2 days, and the seeded data is bimodal (13 of 14
     snapshots under 1 hour, one at 78 hours) so any value from 2h to 72h
     behaves identically. Worth per-warehouse configurability and one
     documented source of truth — but note the brief is the authority here
     (D4), so this is a documentation and configurability task, not a licence
     to change the enforced value.

Rationale for this order (unchanged from Phase 0): the 40 rubric marks on
graph/approval/failure are reachable with **zero LLM calls**. Build and prove
that skeleton first (Phases 1–3), add intelligence last (Phase 4). A
stubbed-agent graph that passes its scenario tests after Phase 3 is already a
passing submission on the largest rubric weight; Phase 4 is what earns the
agent/tool-boundary and clarity marks (15 + 5).

**Next action:** Phase 6b (docs + diagram). Phase 6a shipped the operator UI,
the watchlist and audit playback it needed, the revision-cycle fix, and the
test-suite reset. Phase 7 fixed the UI theming, per-run thread identity, the
order-quantity formula, and moved the vendor-premium decision out of model
prose into a code gate. 45 tests across six modules (5 + 8 + 2 + 4 + 5 + 21).

Verification note, stated honestly: the last *whole-suite* run was 39 passed
/ 1 failed, where the single failure was the minimum-order test in the phase6
module. That module was then rewritten and run on its own: 21 passed. Every
module has therefore been observed green, but not within one invocation —
worth one clean `pytest submission/tests` before the submission is packaged.
That run takes ~10 minutes (see Phase 8 item 5). Phase 7 (decision
quality) is scoped in the roadmap above and is the work that would change
what actually gets ordered; 6b is what the rubric grades the existing work
through.

---

## 9. Operational review findings (2026-09-05)

Recorded because they are measured, not inferred, and because several are
defects in the *provided* package that our submission currently inherits in
silence. Numbers came from querying `database/inventra.db` directly and
running the provided tools against it.

**Schema limits (not fixable, must be stated in design.md):**
- `products` is `sku, name, category, active, created_at`. No selling price,
  no unit cost, no margin. **Cost of a stockout is not computable in
  currency.** `unit_price` is what we pay a vendor, so `velocity × unit_price`
  is procurement spend per day, not lost profit — naming it "exposure"
  invites the model to reason about it as revenue, which is the class of
  quietly-wrong number the brief forbids reaching a human.
- No `warehouses` table. DEL-01..DEL-09 exist only as strings inside
  `inventory_snapshots` / `sales_daily` / `monthly_budgets`.
- No holding/carrying cost → MOQ overbuy can be reported but not priced
  against the cost of holding it.
- No lead-time or PO-receipt history → no lead-time variance, and
  `on_time_rate` cannot be decomposed into "typically how late".
- Exactly one inventory snapshot per sku/warehouse → no stock trend, and
  revalidation's "stock version changed" check has no realistic trigger in
  this dataset.

**Measured behaviour worth keeping in `test_report.md`:**
- AC-001/DEL-01 and /DEL-04: 7-day trend gives 15.56 days cover (not at
  risk), 30-day gives 13.79 (at risk) against a 14-day target. The window
  choice flips the outcome between NO_ACTION and a purchase. Confirmed live:
  the real Gemini Demand agent chose the 7-day window and the case correctly
  closed NO_ACTION, where the stub chooses 30-day and it proceeds to
  approval. Same input, different defensible judgment — which is exactly why
  the approval screen now tells the approver the trends disagreed.
- Reliability blend across the seeded vendors: V-FAST 0.963, V-BALANCED
  0.933, V-CHEAP 0.910 (all eligible); V-SLOW 0.823, V-UNRELIABLE 0.723 (both
  excluded). AC-006 has only those two plus an expired V-FAST offer, which is
  why scenario 12 blocks.
