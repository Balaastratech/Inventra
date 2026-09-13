---
document_id: inventra.technical_review
source_file: Inventra_Technical_Review.pptx
source_type: pptx
source_role: implementation_review
authority: implementation_snapshot_2026-08-30
conversion: slide_text_to_markdown
---

# Inventra Technical Review

> Structure-preserving Markdown conversion of the supplied PowerPoint. Each slide is represented as a section and layout-dependent text is normalized into reading order.


## Slide 1: TECHNICAL REVIEW

Inventra
Multi-Agent Stockout Resolution System
Three narrow-scope LLM agents hand a case to each other through a LangGraph state machine. A human approves once. Every database write happens in code the agents never touch.
3
LLM agents
13
graph nodes
12
acceptance scenarios
26/26
tests passing
Student Design Challenge · 30 August 2026

## Slide 2: 01 · THE PROBLEM

Prevent stockouts without a human babysitting every SKU
For every case (one SKU at one warehouse), the system must:
- Investigate current stock, sales velocity, and risk
- Source a grounded, policy-eligible vendor option
- Prepare a replenishment proposal
- Check policy compliance — budget, reliability, timing
- Pause for a named human's approval, with full context
- Revalidate after approval — facts may have changed
- Execute the purchase — safely, idempotently, once
EVERY CASE ENDS IN EXACTLY ONE OF FOUR STATES
NO_ACTION
Coverage is healthy — nothing to do.
NEEDS_INFORMATION
Something's missing or unclear — ask, don't guess.
BLOCKED
A check failed: stale data, no vendor, over budget, human said no.
PURCHASE_REQUEST_CREATED
Every check passed and a named person approved it.

## Slide 3: 02 · DESIGN PRINCIPLE

Agents for judgment calls, not for data fetches
The brief caps the system at 2–4 agents — more agents earn no extra credit. The instinct to decompose to the lowest level was correct; the unit of decomposition was the problem.
FINE-GRAINED → NODES & TOOLS
Product, stock, sales, risk math, vendor offers, vendor performance, option-building, budget — each is one indexed read or one pure calculation. No ambiguity to resolve, so no LLM.
COARSE-GRAINED → 3 AGENTS
One agent per judgment call a human planner would actually push back on — not per data-fetch step. Each must answer: why does this need a model instead of ordinary code?
1
Investigator
Which sales-velocity window to trust when the 7-day and 30-day figures disagree.
2
Sourcing
Cost vs. speed vs. stockout-risk buffer — is the price gap worth the margin it buys?
3
Policy / Proposal
Does this evidence bundle satisfy policy — hard block, or a labelled exception?

## Slide 4: 03 · ARCHITECTURE

One case, one path to a database write
Intake
Investigate
Source
- Review
- Policy
- Request
- Approval
- Execute
- Purchase
agent — LLM proposes, code decides    ■ deterministic — plain code, no model
EVERY CASE LANDS IN EXACTLY ONE TERMINAL STATE
NO_ACTION
NEEDS_INFORMATION
BLOCKED
PURCHASE_REQUEST_CREATED
Five different failure reasons all exit through the same finalize · BLOCKED terminal — only one path in the whole graph reaches PURCHASE_REQUEST_CREATED.
13
registered nodes
3
invoke an agent
1
write in the whole system
26/26
tests passing

## Slide 5: 04 · GUARDRAIL PATTERN

The model narrates. Code decides.
Each agent's LLM call is bound to the same raw tool evidence as a plain Python function sitting right next to it. The function — not the model — decides the status that leaves the node.
RAW TOOL EVIDENCE
get_product()
get_stock_position()
get_sales_velocity()
calculate_stock_risk()
Investigator Agent (LLM)
status: NO_ACTION
✗ discarded
reason: "coverage is…"
✓ kept as prose only
derive_status()
plain Python, no model call — status: authoritative
InvestigatorOutput
- status ← derive_status()
- reason ← LLM prose
- evidence_ids ← tool calls
This pattern repeats identically in the Sourcing and Policy/Proposal agents. One repair attempt on invalid output — then fail closed.

## Slide 6: 05 · CONTRACTS

Nothing gets re-typed by an LLM in transit
case_id, sku, and warehouse_id pass through every handoff unchanged. The one substantive object each agent produces is handed to the next agent as a typed tool argument — never re-derived from prose.
1
Investigator
status = AT_RISK
passes forward as a typed object:
risk: StockRisk
consumed as a tool argument, not re-typed:
build_vendor_options(stock_risk=risk)
2
Sourcing
status = ELIGIBLE
passes forward as a typed object:
recommendation: VendorRecommendation
consumed as a tool argument, not re-typed:
draft_replenishment_proposal(recommendation=…)
3
Policy / Proposal
status = AWAITING_APPROVAL
passes forward as a typed object:
proposal (hash-locked)
consumed as a tool argument, not re-typed:
prepare_approval_request(proposal=…)

## Slide 7: 06 · APPROVAL & EXECUTION

The system can say no by itself. It can never say yes by itself.
1
Durable interrupt
interrupt() pauses the graph, checkpointed under case_id as the LangGraph thread id — the pause survives minutes, days, or a process restart.
2
Hash-locked proposal
Approval is bound to an exact proposal version and hash. Nothing about cost, vendor, or timing can silently change after a human signs off.
3
Revalidate before write
revalidate() re-checks price, stock, and budget immediately before execute_purchase. A failing check invalidates the approval and loops back to Investigate.
4
Idempotent write
A deterministic idempotency_key plus a DB unique constraint means the same approval resumed twice creates exactly one purchase_requests row.
create_purchase_request is imported directly into graph.py from tools/execution.py — it is never added to any agent's tool list, so no LLM has a way to reach it.

## Slide 8: 07 · STATUS

26/26 tests passing against the real compiled graph
SCENARIO COVERAGE (SELECTED)
Full 12-scenario matrix plus 3 failure paths in test_report.md.
ISSUES CAUGHT DURING INVESTIGATION
- revalidate_approved_proposal() was a stub that always returned true — implemented real revalidation
- Freshness threshold disagreed 4 ways across the brief, config, policy.md, and code — unified to one constant
- A revision forked case_id instead of bumping a proposal version — fixed to keep case_id stable
- Two acceptance fixtures didn't actually trigger their scenario as seeded — added fixture rows, never edited provided seed data

| Scenario | Outcome | Mechanism |
| --- | --- | --- |
| Healthy stock | NO_ACTION | Investigator ends the case before Sourcing runs |
| Stale inventory snapshot | BLOCKED | derive_status() checks risk.stale |
| Over-budget proposal | BLOCKED | Policy node compares cost to budget.remaining in code |
| Approval data changes mid-pause | BLOCKED | revalidate() fails → routes back to Investigator |
| Duplicate approval resume | CREATED | Deterministic idempotency_key + DB unique constraint |
| Human rejection | BLOCKED | handle_decision on REJECTED, audit logs approver |


## Slide 9: 08 · NEXT STEPS

What's done, what's open
DONE
- Contracts — state, agent output models, config, error enums
- Deterministic skeleton — full graph, all 5 terminal states reachable, zero LLM cost
- Approval & execution boundary — interrupt, checkpointer, real revalidation, idempotent write, audit
- All three real agents wired to LLM calls with retry-once-then-fail-closed
OPEN
- Scenario 6 — repair-then-fail-closed path for invalid model output not yet wired
- LLM provider selection — decision pending
- Over-budget exception handling — decision pending
- Docs — design.md, architecture diagram, agent charters, tool-permission matrix, test report
40 of the rubric's 100 marks — graph, approval, failure handling, idempotency — are reachable with zero LLM calls, and already proven by the passing test suite.