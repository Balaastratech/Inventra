# Inventra — Design

Architecture, agent charters, tool-permission matrix, state design, and the
trade-offs behind them. Written to be read without an oral explanation, per
brief §7.

## 1. System summary

One case = one SKU at one warehouse. Three narrow-scope LLM agents hand the
case to each other through a LangGraph state machine; every other node is
plain deterministic Python. A human approves once, by name, tied to an
exact proposal version; every database write happens in code the agents
never touch.

```
Investigator (deterministic) → Demand Analyst (LLM) → risk math (deterministic)
  → Sourcing evidence (deterministic) → Strategist (LLM) → economics gate (deterministic)
  → budget + policy evidence (deterministic) → Policy Reviewer (LLM)
  → human approval (interrupt) → revalidate (deterministic) → write (deterministic)
```

## 2. The guardrail pattern: the model narrates, code decides

Every judgment an agent is allowed to make is bounded by a plain Python
function sitting right next to it, which computes the authoritative answer
independently and either enforces or overrides the agent's output. This
repeats at every agent boundary:

| Agent | Judgment it owns | Deterministic gate that enforces/overrides it |
|---|---|---|
| Demand Analyst | Which sales window (7d/30d) to trust | `calculate_stock_risk` (tool) computes cover days from whichever window the agent names — the agent picks a window, never a number |
| Sourcing Strategist | Cost vs. speed vs. stockout-buffer trade-off | `graph/economics.py::evaluate_options` ranks options on all-in cost per day of cover and computes a `verdict` per option in code; `nodes._validate_recommendation` refuses any recommendation whose verdict isn't `best_value_option`/`within_value_tolerance`, forcing one repair attempt |
| Policy Reviewer | Does the evidence bundle satisfy policy.md | `nodes.review_policy` overrides the verdict to `BLOCKED` in code for over-budget, stale evidence, and missed-deadline — regardless of what the agent said |

This exists because of a real failure during development: a live run had the
Strategist agent narrate an extra-cost figure of `$450` for an option whose
computed extra cost was `$1,450` — the model dropped a digit while restating
arithmetic it had been handed correctly, then called the (wrong) number "a
justified investment." Two failures, one root cause: the model was
authoring a number in prose instead of reading a computed one. Fixed by
making the whole class of pattern impossible — an agent may only *cite* a
figure that already exists in its evidence bundle, and it is not the
authority on whether its own choice was acceptable.

## 3. Architecture diagram

```mermaid
flowchart TD
    START([START]) --> VR[validate_request]
    VR -- valid --> CP[check_product]
    VR -- invalid --> AMI[await_missing_info\n[interrupt]]
    VR -- retries exhausted --> FNI1[finalize: NEEDS_INFORMATION]
    AMI --> VR

    CP -- ok --> FE[fetch_evidence]
    CP -- blocked --> FB[finalize: BLOCKED]

    FE -- ok --> AD["assess_demand (LLM: Demand Analyst)"]
    FE -- insufficient sales history --> FNI1
    FE -- blocked --> FB

    AD -- ok --> CR[compute_risk]
    AD -- "windows disagree; parked" --> FNI1
    AD -- blocked --> FB

    CR -- at risk --> FVE[fetch_vendor_evidence]
    CR -- healthy --> FNA[finalize: NO_ACTION]
    CR -- blocked --> FB

    FVE --> BO[build_options]
    BO -- ok --> RV["recommend_vendor (LLM: Sourcing Strategist)"]
    BO -- no eligible vendor --> FB

    RV -- ok --> FBP[fetch_budget_and_policy]
    RV -- blocked --> FB

    FBP -- ok --> DP[draft_proposal]
    FBP -- blocked --> FB

    DP --> RP["review_policy (LLM: Policy Reviewer)"]
    RP -- awaiting approval --> RA[request_approval]
    RP -- blocked --> FB

    RA --> AA[await_approval\n[interrupt]]
    AA -- approved --> REVAL[revalidate]
    AA -- rejected --> FB
    AA -- "revise, bounded 1x" --> PR[prepare_revision]
    AA -- "revision limit exceeded" --> FB
    AA -- "edit, bounded 3x" --> AHE[apply_human_edit]
    AA -- "edit limit exceeded" --> FB
    PR --> FE
    AHE -- ok --> DP
    AHE -- blocked --> FB

    REVAL -- pass --> EP[execute_purchase]
    REVAL -- stock/offer changed, one bounce --> IA[invalidate_approval]
    REVAL -- hash/budget changed, fail closed --> FB
    IA --> CR

    EP -- success --> FS[finalize: PURCHASE_REQUEST_CREATED]
    EP -- write failed --> FB

    FNA --> END([END])
    FNI1 --> END
    FB --> END
    FS --> END
```

**Write invariant:** exactly one path in the whole graph reaches
`execute_purchase`, and it is gated by human `APPROVED` + passing
revalidation. No LLM agent's output is ever wired to a tool that writes.

## 4. Agent charters

### 4.1 Demand Analyst (`assess_demand`)

- **Objective.** Given raw 7-day and 30-day sales averages, decide which
  window better reflects current demand, and flag when the two windows
  disagree enough that picking one is a real judgment call rather than a
  default.
- **Why an LLM, not code.** "Which trend do I believe" is exactly the kind
  of ambiguous read a human planner disputes in practice — a pure rule
  (e.g. "always trust 7-day") would silently make that call invisible.
- **Input.** `SalesVelocity` (both windows + observation counts), plus `sku`,
  `warehouse_id`, `target_cover_days`, the `product` record and the `stock`
  snapshot — see `prompts/demand.py::build_user_message`. No vendor and no budget
  data; it needs neither.

  **Closed, 2026-09-11.** The agent receives `stock` and `target_cover_days`,
  but the system prompt forbids it from computing cover days, so it can
  never tell on its own whether its window choice is *consequential* --
  its ambiguity test is framed on relative disagreement between the two
  velocities, not on whether the choice flips the outcome. A SKU sitting on
  the threshold used to get a non-deterministic result as a consequence
  (AC-001's windows once differed by only 12.8% yet gave 15.56d cover
  (healthy) versus 13.79d (at risk) against a 14-day target — this specific
  example is now stale, since the `tools/sales.py` window-boundary fix in
  the same pass made every uniform-rate SKU's two windows agree exactly).
  `nodes._override_ambiguity_if_windows_disagree_on_risk` closes the gap
  itself, independent of that: it computes risk under both windows in code
  and forces `ambiguous=true` whenever they disagree on `at_risk`,
  regardless of what the agent concluded -- the same override discipline
  the policy checklist uses. `portfolio.scan_portfolio()` already resolved
  the watchlist side of this correctly (worse-of-both-windows, labelled
  `Borderline`); the graph now matches it instead of the two disagreeing.
- **Tools.** None (see §5 — this system hands agents evidence, not tool
  access; see design note in §7).
- **Output schema.** `DemandAssessment` (`agents/models.py`) — `case_id`,
  `chosen_window_days` (7 or 30), `rationale`, `ambiguous: bool`,
  `clarification_needed: str | None`, `evidence_ids`. `extra="forbid"`.
- **Permissions.** Cannot compute cover days, cannot decide `at_risk`
  (`calculate_stock_risk`, a tool, does both from whichever window it
  names).
- **Failure behaviour.** Schema-invalid output → one repair attempt
  (`graph/support.invoke_agent_with_retry`) → `BLOCKED` on a second
  failure. `ambiguous=True` → `NEEDS_INFORMATION`, carrying the agent's own
  `clarification_needed` text as the case's `error_detail` (not discarded).

### 4.2 Sourcing Strategist (`recommend_vendor`)

- **Objective.** Given a list of already-eligible vendor options (each
  already priced, sized, and reliability/deadline-filtered by code) and a
  computed `economics` block scoring every option's premium against the
  cheapest one, pick one and explain the trade-off in terms a planner can
  challenge.
- **Why an LLM, not code.** Choosing whether a faster-but-dearer option's
  premium is worth the stockout-risk buffer it buys is a business judgment,
  not an arithmetic one — the arithmetic (§2) is already done before this
  agent runs.
- **Input.** `StockRisk`, eligible `VendorOption` list, the `economics`
  block (`graph/economics.py::OptionsEconomics`), an optional
  `PRIOR CONTEXT` section (Gap 9 — recent human-rejection/revision signals
  about these same vendors), and an optional `REVISION REQUEST` section
  (Gap 1/D8 — a human's stated reason for a REVISE decision).
- **Tools.** None (evidence-only, same as above).
- **Output schema.** `ReplenishmentRecommendation` — `recommended_offer_id`,
  `strategy` (`cheapest`/`fastest`/`balanced`), `rationale`,
  `other_options_summary`, `evidence_ids`. `extra="forbid"`.
- **Permissions.** Cannot invent a price, quantity, or arrival date (all
  come from the `VendorOption` the code already built); cannot choose an
  option whose code-computed `verdict` isn't acceptable
  (`nodes._validate_recommendation`).
- **Failure behaviour.** Same repair-once-then-fail-closed loop.
  Semantically-wrong output (an invented `offer_id`, or an option whose
  verdict the economics gate refuses) is caught by `validate=` in
  `invoke_agent_with_retry` and treated as a validation failure, triggering
  the same one repair attempt.

### 4.3 Policy Reviewer (`review_policy`)

- **Objective.** Read `policy.md`'s narrative guidance alongside the full
  evidence bundle for the drafted proposal, and decide `PASS` / `BLOCKED` /
  `EXCEPTION` — an independent second opinion on the Strategist's pick.
- **Why an LLM, not code.** `policy.md` is prose guidance covering eight
  review questions (freshness, risk, sales sufficiency, vendor validity,
  trade-off rationale, deadline, budget, evidence traceability) — applying
  prose guidance to a evidence bundle is a reading comprehension task, not
  an arithmetic one.
- **Input.** Full `policy_text`, the drafted `ReplenishmentProposal`, and
  every item on policy.md's own "required evidence" checklist (product,
  stock, sales, risk, vendor offers, vendor performance, budget).
- **Tools.** None (evidence-only).
- **Output schema.** `PolicyReview` — `case_id`, `proposal_id`, `verdict`
  (`PolicyVerdict` enum, not free text), **`checklist: list[PolicyChecklistItem]`
  constrained to exactly 8 entries**, `concerns: list[str]`, `rationale`,
  `evidence_ids`. `extra="forbid"`.

  The checklist replaces a single blended verdict with **one row per policy.md
  review question**, and a Pydantic `model_validator`
  (`_checklist_covers_every_question_exactly_once`) rejects any output that
  misses a question or duplicates one. A question therefore cannot be silently
  skipped by the model or buried inside a paragraph. `nodes.review_policy` then
  force-overrides **7 of the 8** rows with the deterministically provable answer
  — freshness, at-risk, sales sufficiency, vendor validity,
  arrival-beats-stockout, budget fit, evidence traceability — leaving only
  `tradeoff_explained` as the agent's own judgment, because "which tradeoff is
  being made" is a narrative call rather than a fact with a computable answer.
  A `FAIL` on freshness, arrival-beats-stockout or evidence-traceability forces
  `BLOCKED` with no exception path.
- **Permissions.** Cannot edit the proposal, only verdict + concerns.
  Budget, freshness, and deadline-vs-stockout are never this agent's final
  call — `nodes.review_policy` recomputes all three in code and overrides
  the verdict to `BLOCKED` if the agent's answer disagrees with the
  computed fact (Gap 5). Concretely: `over_budget and not within_tolerance`
  → forced `BLOCKED`; `risk.stale` → forced `BLOCKED`; computed
  `meets_deadline is False` → forced `BLOCKED`. An `EXCEPTION` label is
  only permitted within `config.over_budget_exception_tolerance` (5%).
- **Failure behaviour.** Same repair-once-then-fail-closed loop, plus the
  `tools/policy.py` length tripwire (logs a warning if `policy.md` exceeds
  ~20k characters, so growth of the document becomes visible instead of
  silently degrading accuracy — deliberately not chunking/RAG while the
  doc is this short).

## 5. Tool-permission matrix

This system does not give agents live tool-calling ability at all — a
stricter posture than "give each agent only the tools it needs." Every
deterministic node calls the tools it needs *before* invoking an agent, and
hands the agent only the resulting evidence inside its prompt (see
`prompts/_shared.py::render_evidence`). An agent physically cannot call
`create_purchase_request`, `append_audit_event`, `revalidate_approved_proposal`,
or any other tool, because no agent has a tool binding — `call_structured()`
(`agents/llm.py`) invokes the model with a system+user prompt and a
Pydantic response schema only, never a tool list.

| Tool | Called by | Reachable from an agent? |
|---|---|---|
| `get_product`, `get_stock_position`, `get_sales_velocity`, `calculate_stock_risk` | `nodes.check_product`, `nodes.fetch_evidence`, `nodes.compute_risk` (deterministic) | No |
| `list_vendor_offers`, `get_vendor_performance`, `build_vendor_options` | `nodes.fetch_vendor_evidence`, `nodes.build_options` (deterministic) | No |
| `get_budget_position`, `get_policy_guidance` | `nodes.fetch_budget_and_policy` (deterministic) | No |
| `revalidate_approved_proposal` (starter stub; real revalidation in `graph/revalidation.py`) | `nodes.revalidate` (deterministic, post-approval only) | No |
| `create_purchase_request` | `nodes.execute_purchase` (deterministic, only after human approval + passing revalidation) | **No — never** |
| `append_audit_event` | `graph/support.emit_audit`, called by every deterministic node | No |
| `get_vendor_contact_email`, vendor PO send (Gap 8) | `submission/notifications/vendor_email.py`, called only from `execute_purchase` | No |

Evidence each agent actually receives (least-privilege by evidence, not by
tool binding):

| Agent | Evidence in its prompt |
|---|---|
| Demand Analyst | `SalesVelocity` only |
| Sourcing Strategist | `StockRisk`, eligible `VendorOption`s, `economics` block, prior-rejection signals, revision request |
| Policy Reviewer | Full bundle: product, stock, sales, risk, vendor offers, vendor performance, budget, policy text |

## 6. State design (`state/state.py`)

`CaseState` (a `TypedDict`) persists every category the brief requires:

| Category | Fields |
|---|---|
| Identity | `case_id`, `thread_id`, `trace_id` |
| Validated request | `sku`, `warehouse_id`, `target_cover_days`, `budget_month` |
| Evidence | `product`, `stock`, `sales`, `vendor_offers`, `vendor_performance`, `budget`, `policy_guidance` (each carries its own `evidence_id`/timestamp) |
| Decisions | `demand_assessment`, `risk`, `vendor_options`, `economics`, `replenishment_recommendation`, `proposal`, `policy_review` |
| Control | `status`, `revision_count`, `retry_counts` (per-node attempt counters), `error_code`, `error_detail` |
| Human action | `approval_decision` (proposal hash, approver, decision, comment, time) |
| Outcome | `purchase_result`, `idempotency_key`, `vendor_rejection_detail` (Gap 2 structured BLOCKED detail) |

`case_id` is stable per (sku, warehouse) and never forks across a revision
(D8) — `thread_id` is a per-*run* identity (`case_id#<timestamp>`) so a
finished case can be re-investigated without resuming a dead thread. Every
custom type that can appear in a paused checkpoint is registered in
`workflow.checkpoint_allowlist()`, derived by introspection rather than
hand-listed, so a new field added to `CaseState` fails at allowlist-build
time instead of at a silent deserialization warning months later
(`test_checkpoint_allowlist_covers_everything_a_paused_case_stores`).

## 7. What was deliberately not made agentic

- **Every tool call.** No agent has tool-calling ability at all (§5) —
  stronger than "narrow tool boundary," this removes the boundary question
  entirely.
- **Cost, quantity, arrival date, and the proposal hash.** All computed in
  `graph/economics.py` / `graph/hashing.py`; an agent may only cite them.
- **Which supplier is the better buy.** `graph/economics.py::evaluate_options`
  ranks every eligible option on `all_in_cost_per_day_of_cover` — the order's
  cost divided by the days of demand it actually funds, with inventory
  carrying cost and that supplier's own expected stockout cost already inside
  the figure — and assigns a verdict; the Strategist explains the verdict,
  never overrules it. See §2 for the model-was-wrong story that motivated the
  gate.

  Explicitly **not** ranked on `total_cost`. Order quantity is sized per
  supplier from that supplier's lead time, because the target is N days of
  cover *once the goods land*, so a slower supplier legitimately needs more
  units. Ranking on the invoice total therefore compared different-sized
  baskets and called the smaller one cheaper: on AC-004/DEL-01 it preferred
  FastShip's 37 units at $18,500 over Standard's 42 at $18,900, even though
  Standard is $478.72 per unit delivered against FastShip's $510.20 and the
  extra units are simply more days of demand served. `total_cost` is still the
  basis for the budget check — it is the cash committed — it is just not a
  supplier comparison. Regression test:
  `test_the_smallest_invoice_is_not_the_best_value`.

  Because delivery risk is priced inside each option's score, there is no
  separate "is the premium justified" judgment left. What remains for the agent
  is a bounded near-tie: an option within `config.vendor_value_tolerance_rate`
  of the winner that also arrives earlier carries `within_value_tolerance` and
  may be preferred. The gate bounds the judgment rather than deleting it.
- **Budget arithmetic, freshness, and deadline-vs-stockout.** All
  three are agent-advisory only; code recomputes and can override every one
  (§4.3).
- **The portfolio watchlist ranking, the audit-trail playback, and the
  pending-approval queue** (`submission/portfolio.py`). Deterministic reads
  and plain sentence templates — an LLM here would risk misdescribing what
  the system actually did, which is exactly the one place a hallucination
  would directly mislead an auditor.
- **Freshness threshold, revalidation logic, idempotency key.** Pure
  configuration and deterministic code (`submission/config.py`,
  `graph/revalidation.py`, `tools/execution.py`).

## 8. Key decisions and trade-offs (see PLAN.md for the full log)

- **D3 — no Anthropic.** `MODEL_PROVIDER` is `vertex` (default, ADC auth),
  `gemini` (AI Studio key), or `openai` — never a fourth option.
- **D4-REVISED (2026-09-06) — freshness threshold.** The brief's own
  business-rules table says 2 hours; `policy.md` (what the Policy Reviewer
  actually reads every run) says "2 days." Project owner's explicit call:
  policy.md is authoritative for this one value (`data_freshness_hours =
  48.0`), because an agent reasoning against a policy document that
  contradicts the enforced code is a worse failure mode than a threshold
  that reads more permissively than the brief's number. Configurable via
  `DATA_FRESHNESS_HOURS` env var for a grader who wants the literal 2h
  reading — see `submission/config.py`'s module docstring.
- **D6 — SqliteSaver, not Postgres.** Single-process app; Postgres would be
  over-engineering for this scale.
- **D7/D11 — two approval surfaces, one graph.** Streamlit (`submission/ui.py`)
  and signed one-click email links (`submission/graph/approval_server.py`)
  both resume the same `Command(resume=...)` call against the same
  checkpoint file — whichever arrives first wins, the other is rejected as
  already-used.
- **D8 — revision bumps a proposal version, not the case_id.** A starter
  reference notebook forked `case_id` on revision, splitting the audit
  trail across two IDs that never joined. Fixed to keep `case_id` stable.
- **D9 — over-budget exception path.** Default `BLOCKED`; a bounded
  "flagged exception" only within `config.over_budget_exception_tolerance`
  (5%), and even then the human approver has final say.
- **Gap 6 (2026-09-06) — revalidation retry, restored per Scenario 7.**
  Only a proposal-hash mismatch fails closed immediately (structural — a
  retry cannot fix a hash that doesn't match its own content). Budget,
  stock, and offer changes all get the one bounce back to `compute_risk`,
  matching `fixtures/scenarios.json`'s `APPROVAL_DATA_CHANGE` scenario
  verbatim ("case re-enters risk assessment with new facts"). An earlier
  pass of this fix wrongly widened the fail-closed set to include budget;
  reverted after re-reading the fixture.
- **Gap 8 — vendor ordering built; enabled 2026-09-13.** The capability
  (`submission/notifications/vendor_email.py`) is complete — strictly
  templated from validated proposal fields only (plus a read-only product
  name / warehouse name lookup for legibility, still never agent-generated
  text), idempotent on `purchase_requests.vendor_send_status`, reachable
  only from `execute_purchase`. `config.vendor_email_enabled` defaulted
  `False` pending a go-live review; it is now `true` in this deployment's
  `.env` after that review, since sending a real PO to a vendor is a genuine
  commercial action, not a reversible one — re-check this flag before
  running unattended. See `submission/TEST_RESULTS.md` for the live send
  trace and `submission/README.md` §12 for the current template contents.

## 9. Observability

`audit_events` carries structured summaries only (event type + a small
payload dict) — never a model's private reasoning or raw prompt/response
text (`graph/support.emit_audit`'s docstring states this explicitly, and
`test_case_history_is_readable_and_leaks_no_reasoning` asserts no
`rationale`/`reasoning`/`thoughts` key ever appears in a stored payload).

`agents/llm.py::call_structured` is the one chokepoint every agent call
goes through regardless of provider, and is instrumented at that single
point: structured per-call logging (role, provider, model, duration,
success/failure — reads the starter's own `LOG_LEVEL`/`LOG_FORMAT` env
names) plus optional LangSmith tracing (`langsmith.traceable`, active only
if `LANGCHAIN_TRACING_V2` is set and the package is installed — a no-op
otherwise, so nobody needs a LangSmith account to run the suite). This
matters specifically because `MODEL_PROVIDER=vertex` calls the raw
`google-genai` SDK directly (see `agents/llm.py`'s module docstring) —
LangChain's own auto-instrumentation never sees that path, so tracing had
to be wired explicitly rather than left to the framework default.
