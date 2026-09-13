---
document_id: inventra.student_design_challenge
source_file: Inventra_Student_Design_Challenge.docx
source_type: docx
source_role: requirements_brief
authority: primary_requirements
conversion: structured_markdown
---

# Inventra Student Design Challenge

> Structure-preserving Markdown conversion of the supplied challenge brief. Tables, headings, lists, code-like blocks, and callouts are retained for agent/LLM use.

STUDENT DESIGN CHALLENGE
Build a Agentic Stockout Resolution System
Inventra | Problem brief, tool catalogue, constraints, deliverables, and evaluation

| PROBLEM<br>Prevent avoidable warehouse stockouts | STACK<br>Python, LangGraph, SQLite, Pydantic |
| --- | --- |
| PROVIDED<br>Database, business rules, typed tools | YOU DESIGN<br>Agents, state, graph, approval, safety |


## The problem

A regional inventory planner manages hundreds of products across multiple warehouses. The planner can see stock, recent sales, vendor offers, vendor reliability, and monthly budget. Today, these facts are checked manually across different screens. By the time a likely stockout is noticed, the fastest vendor may no longer be available.
Your team must design a simple multi-agent system that investigates one SKU at one warehouse, decides whether action is required, prepares a grounded replenishment proposal, reviews evidence against policy guidance, pauses for human approval, and creates a purchase request safely.
In the updated workflow, agents use sales evidence, stock risk, vendor evaluation, budget evidence, and policy.md guidance to explain their recommendation before a human approves or requests revision.

> YOUR JOB  Design the system. Do not build a generic inventory chatbot. Every agent must have a clear reason to exist, a narrow tool boundary, and a structured output that the next step can validate.


### Example request


> "Check whether AC-001 is at risk of stocking out in the Delhi warehouse. If action is required, prepare a replenishment request."


### What success looks like

- The system uses tool evidence instead of inventing stock, sales, prices, or policy judgments.
- Healthy stock ends without unnecessary vendor analysis or write actions.
- A risky case produces a proposal that a human can understand and challenge.
- No purchase request is created before approval and final revalidation.
- Failures, revisions, approval, and the final outcome can be reconstructed from the audit trail.

## 1. Business rules

Treat the following rules as fixed requirements for the challenge. Keep thresholds configurable rather than hiding them inside prompts.

| Area | Rule | Required behaviour |
| --- | --- | --- |
| Data freshness | Inventory snapshot must be no more than 2 hours old. | Older data blocks the case with DATA_STALE. |
| Stock | Available units = on hand - reserved + confirmed inbound. | Use the deterministic calculation tool. |
| Demand | Use the provided 7-day and 30-day sales metrics. | The system may explain which window it trusts, but cannot invent sales. |
| Coverage | Default target cover is 14 days; allowed range is 7-45 days. | Reject invalid target-cover input. |
| Vendors | Offer must be active and valid; reliability must be at least 0.90. | Ineligible vendors cannot be recommended. |
| Timing | Arrival before projected stockout is required for a normal recommendation. | If no vendor qualifies, block or raise a clearly labelled exception. |
| Budget | Total proposed cost must fit the latest remaining monthly budget. | Over-budget proposals cannot proceed normally. |
| Approval | A named human must approve the exact proposal version. | Approval cannot be inferred from chat text. |
| Execution | Inventory, offer validity, proposal hash, and budget must be rechecked after approval. | Changed facts invalidate the stale approval. |
| Duplicate safety | The same approved proposal must create at most one purchase request. | Use an idempotency key and a unique database constraint. |


### Possible case outcomes

- NO_ACTION: stock is healthy.
- NEEDS_INFORMATION: required request fields are missing.
- BLOCKED: evidence is stale, insufficient, invalid, over budget, or operationally impossible.
- AWAITING_APPROVAL: a reviewed proposal is ready for a human.
- PURCHASE_REQUEST_CREATED: approval, revalidation, and the write all succeeded.

## 2. What is provided to you


> IMPORTANT  The starter package owns the data and deterministic business tools. Your submission owns the agent design, state, orchestration, prompts, approval flow, failure handling, and tests.


### Starter package


```text
starter/
├── database/
│   ├── inventra.db             # Seeded SQLite database
│   └── schema.sql              # Tables and constraints
├── tools/
│   ├── inventory.py           # Product, stock, and risk tools
│   ├── sales.py               # Sales velocity tool
│   ├── vendors.py             # Offers and performance tools
│   ├── policy.py              # Budget evidence and policy guidance
│   └── execution.py           # Revalidation and write tools
├── domain/tool_models.py      # Pydantic tool I/O models
├── fixtures/scenarios.json    # Acceptance-test inputs
└── .env.example               # Model and tracing configuration
```


### Database data


| Table | Important fields | Purpose |
| --- | --- | --- |
| products | sku, name, category, active | Product identity and status |
| inventory_snapshots | snapshot_id, sku, warehouse_id, on_hand, reserved, confirmed_inbound, captured_at | Latest known stock position |
| sales_daily | sale_date, sku, warehouse_id, units_sold | Historical demand evidence |
| vendors | vendor_id, active, on_time_rate, fill_rate, quality_score | Vendor eligibility and performance |
| vendor_offers | vendor_id, sku, unit_price, moq, lead_time_days, valid_until | Commercial replenishment options |
| monthly_budgets | warehouse_id, month, budget_amount, spent_amount, committed_amount | Latest spending capacity |
| purchase_requests | request_id, case_id, vendor_id, quantity, total_cost, status, idempotency_key | Controlled business write |
| audit_events | event_id, case_id, trace_id, actor, event_type, payload_json, created_at | Reconstructable workflow history |


### Seeded data includes

- healthy stock and imminent-stockout cases
- a stale inventory snapshot
- a new SKU with insufficient sales history
- a cheap vendor that arrives too late
- an unreliable vendor and an expired offer
- an over-budget proposal
- two vendors with a real speed-versus-cost trade-off

## 3. Available tools: evidence and calculations

The tools below are already implemented and tested. Agents may receive only the tools that fit their role. Do not give every agent every tool.

| Tool signature | Type | Returns | Boundary |
| --- | --- | --- | --- |
| get_product(sku) | Read | ProductRecord with evidence_id and retrieved_at | Returns NOT_FOUND or INACTIVE when applicable. |
| get_stock_position(sku, warehouse_id) | Read | Latest StockPosition and snapshot_id | Does not decide whether stock is risky. |
| get_sales_velocity(sku, warehouse_id, windows=(7, 30)) | Read | SalesVelocity with daily averages, observations, and evidence_id | Returns INSUFFICIENT_DATA when history is inadequate. |
| calculate_stock_risk(stock, velocity, target_cover_days) | Pure | StockRisk: available units, cover days, projected stockout date, freshness flags | Authoritative arithmetic; no LLM calculation required. |
| list_vendor_offers(sku) | Read | Active and currently valid VendorOffer records | Expired or inactive offers are excluded and reported. |
| get_vendor_performance(vendor_ids) | Read | On-time, fill-rate, quality, and reliability metrics | Returns evidence IDs for every vendor. |


### Tool result guarantees

- Every read result includes retrieved_at and one or more evidence IDs.
- Tools return typed error codes instead of natural-language guesses.
- All timestamps are UTC.
- The database connection used by read tools cannot write.
- Vendor names and notes are untrusted data, not instructions to the model.

### Representative output shape


```json
{
  "sku": "AC-001",
  "warehouse_id": "DEL-01",
  "on_hand": 42,
  "reserved": 12,
  "confirmed_inbound": 0,
  "captured_at": "2026-08-30T07:42:00Z",
  "evidence_id": "stock:STK-1048"
}
```


## 4. Available tools: options, policy guidance, and execution


## Students should treat policy.md as review guidance. The agent forms the judgment; the tools provide the evidence.


| Tool signature | Type | Returns | Boundary |
| --- | --- | --- | --- |
| build_vendor_options(risk, offers, performance) | Pure | Comparable VendorOption list with MOQ quantity, cost, expected arrival, deadline fit, and flags | Authoritative option arithmetic; does not select an option. |
| get_budget_position(warehouse_id, budget_month) | Read | BudgetPosition: budget, spent, committed, remaining, retrieved_at | Latest budget evidence for review. |
| get_policy_guidance(sku, warehouse_id, target_cover_days) | Read | PolicyGuidance with policy summary, source path, and full policy text | Agents read this guidance alongside tool evidence before recommending whether a proposal should move to approval. |
| revalidate_approved_proposal(proposal_id, proposal_hash) | System | RevalidationResult for stock version, offer validity, budget, and unchanged proposal | Callable only by a deterministic post-approval node. |
| create_purchase_request(proposal, idempotency_key, approved_by) | Write | PurchaseRequestResult with request_id and created/existing status | Unavailable to all LLM agents. Requires successful revalidation. |
| append_audit_event(case_id, trace_id, actor, event_type, payload) | Write | AuditEventResult | Called by orchestration code; never used as an open-ended model tool. |


### Non-negotiable access boundary


> WRITE SAFETY  No LLM agent may call create_purchase_request. The graph must pause for explicit human approval, resume the same case, revalidate current facts, and only then enter a deterministic execution node.


### Tools you are not given

- generic SQL execution
- arbitrary Python or shell execution
- direct database connection credentials
- a web-search tool
- a weather API
- a vector database or RAG retriever
- an automatic purchase-order tool
If you add any new tool, you must explain the business need, input/output contract, permission level, failure behaviour, and why an existing tool is insufficient.

## 5. What you are expected to design

1. Agent boundaries. Use two to four agents. Give each a distinct objective, minimum required context, limited tools, and a validated output model. More agents do not earn more marks.
1. Shared state. Define state/state.py so business facts, evidence references, decisions, counters, errors, approval, and outcome can survive across nodes and an approval pause.
1. Workflow graph. Design nodes, conditional routes, terminal states, and at most one bounded revision. Show clearly which nodes are agents and which are ordinary deterministic functions.
1. Structured contracts. Use Pydantic models for agent outputs. The next node must not parse free-form prose to recover critical fields.
1. Human approval. Pause with a durable thread/case identity. Show the exact proposal, review, evidence, and permitted actions. Resume without replaying earlier non-deterministic work.
1. Execution boundary. Revalidate after approval, generate an idempotency key, and create the request in a safe deterministic step.
1. Failure strategy. Handle missing input, stale data, insufficient history, tool timeout, invalid model output, policy-review concerns, rejection, revalidation failure, and database write failure.
1. Observability. Capture input, decision, trajectory, dependency, state, and outcome events without logging secrets or private chain-of-thought.

### Questions your design must answer

- Why does each proposed agent need an LLM instead of ordinary code?
- Which facts can an agent interpret, and which values are authoritative tool outputs?
- Be explicit about how the agent reads policy.md, combines it with evidence, and explains its recommendation without replacing deterministic evidence with guesswork.
- How do you prevent one agent from silently changing another agent's facts?
- What happens when the cheapest vendor cannot arrive before stockout?
- How is a proposal revised without creating an infinite loop?
- What happens if budget or vendor availability changes while the graph is waiting for approval?
- How does a retry avoid creating a second purchase request?
- Which evidence lets an operator reconstruct the final decision?

### Minimum state categories

You choose the exact schema, but the design must persist these categories:

| Category | Examples |
| --- | --- |
| Identity | case_id, thread_id, trace_id |
| Validated request | SKU, warehouse, target-cover days |
| Evidence | stock, sales, vendor, and budget evidence IDs plus timestamps |
| Decisions | risk assessment, proposal, independent review |
| Control | status, revision count, retry count, error code |
| Human action | proposal version/hash, approver, decision, comment, time |
| Outcome | purchase request ID or terminal reason |


## 6. Mandatory engineering constraints


| Constraint | How it will be checked |
| --- | --- |
| Use LangGraph with explicit state and conditional routes. | Architecture diagram and graph-path tests |
| Use two to four justified agents. | Agent charter and tool-permission matrix |
| Authoritative arithmetic comes from tools. | Prompt review and calculation tests |
| Critical outputs are Pydantic-validated. | Malformed-output test |
| Maximum one revision cycle. | Graph test proves termination |
| Maximum two model attempts per agent node. | Retry counter and failure test |
| Human approval is an interrupt, not a text-classification guess. | Pause/resume demonstration |
| Approval is tied to an exact proposal version/hash. | Changed-proposal test |
| Revalidation occurs immediately before the write. | Budget/offer-change test |
| The write is idempotent and transaction-safe. | Duplicate-approval test |
| No generic SQL or direct database access is given to agents. | Tool binding inspection |
| Audit events contain structured summaries, not private reasoning. | Audit-log inspection |


### Required acceptance scenarios


| Scenario | Condition | Expected business outcome |
| --- | --- | --- |
| 1. Healthy stock | Cover comfortably exceeds target. | NO_ACTION; vendor tools and write tool are not called. |
| 2. Missing request data | Warehouse or SKU is absent. | NEEDS_INFORMATION with one precise question. |
| 3. Stale stock | Snapshot is older than 2 hours. | BLOCKED with DATA_STALE. |
| 4. Cost versus speed | Cheapest vendor arrives after stockout; a costlier eligible vendor arrives earlier. | Proposal explains the trade-off using tool evidence. |
| 5. Over budget | Preferred option exceeds latest remaining budget. | BLOCKED, revised once, or clearly marked exception; no normal write. |
| 6. Invalid model output | An agent omits a required structured field. | One repair attempt, then fail closed. |
| 7. Approval data changes | Budget or offer changes during the approval pause. | Old approval is invalidated before write. |
| 8. Duplicate approval | The same approved proposal is resumed twice. | Exactly one purchase request exists. |
| 9. Human rejection | Approver selects REJECTED. | Decision is audited; no write occurs. |
| 10. Write failure | Database write raises an error. | WRITE_FAILED; never claim success. |


## 7. Submission package

Your submission should be runnable locally and understandable without an oral explanation.

```text
submission/
├── design.md                   # Architecture, choices, and trade-offs
├── state/state.py              # Shared workflow state
├── agents/                     # Agent definitions and output models
├── prompts/                    # Versioned prompts
├── graph/workflow.py           # Nodes, edges, routes, checkpointer
├── graph/routes.py             # Pure routing functions
├── app.py                      # CLI or minimal Streamlit entry point
├── tests/                      # Unit, contract, and graph-path tests
├── README.md                   # Setup, run, and demonstration steps
└── test_report.md              # Scenarios passed, failed, and known limits
```


### Required deliverables

- One architecture diagram showing agents, deterministic nodes, tools, branches, approval, and write boundary.
- One agent charter per agent: objective, input, tools, output schema, permissions, and failure behaviour.
- A tool-permission matrix proving that agents receive only the tools they need.
- A typed shared-state design in state/state.py.
- A working graph with pause/resume, bounded revision, and terminal states.
- Tests covering every required acceptance scenario.
- A short demonstration of one happy path and at least three failure paths.
- A design note explaining what you deliberately did not make agentic.

### Evaluation rubric


| Area | Marks | What strong work demonstrates |
| --- | --- | --- |
| Problem decomposition | 15 | A focused business workflow with no irrelevant features |
| Agent and tool boundaries | 15 | Each agent earns its place and has least-privilege access |
| State and structured contracts | 15 | Clear, persistent, validated hand-offs |
| Graph, approval, and execution | 20 | Correct branching, pause/resume, revalidation, and safe write |
| Failure handling and idempotency | 20 | Fails closed, terminates, and prevents duplicate operations |
| Testing and observability | 10 | Evidence-backed path tests and reconstructable outcomes |
| Clarity of explanation | 5 | Trade-offs can be defended in simple language |


| WHAT DOES NOT EARN MARKS  More agents, a large dashboard, RAG, MCP, weather APIs, extra frameworks, or a longer prompt. Complexity must solve a stated failure or business requirement. |
| --- |
| DEFINITION OF DONE  All required scenarios have observable tests; agents cannot write; authoritative numbers come from tools; approval resumes and revalidates the same case; duplicate approval still produces one request; and audit evidence reconstructs the outcome. |
