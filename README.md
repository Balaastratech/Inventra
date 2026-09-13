# Inventra: Multi-Agent Stockout Resolution System

## The Challenge

Design a multi-agent system that helps a regional inventory planner prevent warehouse stockouts. The system must:

1. **Investigate** one SKU at one warehouse
2. **Assess** stock risk based on current inventory and sales velocity
3. **Prepare** a grounded replenishment proposal with vendor options
4. **Check** policy compliance (budget, reliability, timing)
5. **Pause** for human approval with full context
6. **Revalidate** after approval (facts may have changed)
7. **Execute** the purchase request safely, idempotently, and only after approval

## What You Get (Provided)

Root-level folders contain:
- ✅ SQLite database with seeded test data
- ✅ Read-only tools for inventory, sales, vendors, and policy
- ✅ Pydantic models for all tool inputs/outputs
- ✅ 12 acceptance test scenarios
- ✅ Database schema and seeder script

## What You Must Design (Submission)

The `submission/` folder (you create) must include:
- 🔧 **Agents** (2–4) — Each with clear objective, limited tools, validated output
- 💾 **State** — Persistent shared state across approval pauses
- 📊 **Graph** — LangGraph workflow with branching, pause/resume, and safe writes
- 📋 **Tests** — All 12 scenarios + at least 3 failure paths
- 📖 **Docs** — Architecture diagram, agent charters, design trade-offs

---

## File Structure

```
inventra/
├── Inventra_Student_Design_Challenge.docx   ← Problem brief
├── README.md                                ← This file
├── .env.example                             ← Config template
├── __init__.py
│
├── database/                                ← PROVIDED
│   ├── schema.sql
│   ├── inventra.db                          ← Seeded SQLite
│   └── seed.py
│
├── domain/                                  ← PROVIDED
│   ├── __init__.py
│   └── tool_models.py                       ← Pydantic schemas
│
├── tools/                                   ← PROVIDED (read-only)
│   ├── __init__.py
│   ├── inventory.py
│   ├── sales.py
│   ├── vendors.py
│   ├── policy.py
│   └── execution.py
│
├── fixtures/                                ← PROVIDED
│   ├── __init__.py
│   └── scenarios.json                       ← Test data (12 scenarios)
│
└── submission/                              ← YOU CREATE
    ├── README.md
    ├── design.md
    ├── app.py
    ├── state/
    └── ...
```

---

## Setup

### 1. Initialize the Database

```bash
python database/seed.py
```

This creates `database/inventra.db` with seeded test data covering all acceptance scenarios.

### 2. Copy Configuration

```bash
cp .env.example .env
# Edit .env with your LLM credentials and settings
```

### 3. Install Dependencies

```bash
pip install -r requirements.txt  # Your student submission will specify this
```

---

## Provided Tools

### Read-Only Tools

All tools return `retrieved_at` (UTC timestamp) and `evidence_id` (audit reference).

#### Inventory (`tools/inventory.py`)
- `get_product(sku)` → `ProductRecord`
- `get_stock_position(sku, warehouse_id)` → `StockPosition`
- `calculate_stock_risk(available_units, daily_velocity, target_cover_days, captured_at)` → `StockRisk` ✓ Deterministic

#### Sales (`tools/sales.py`)
- `get_sales_velocity(sku, warehouse_id, windows=(7,30))` → `SalesVelocity`

#### Vendors (`tools/vendors.py`)
- `list_vendor_offers(sku)` → `VendorOfferList`
- `get_vendor_performance(vendor_ids)` → `VendorPerformanceList`
- `build_vendor_options(stock_risk, vendor_offers, vendor_performance)` → `VendorOptionList` ✓ Deterministic

#### Policy (`tools/policy.py`)
- `get_budget_position(warehouse_id, budget_month)` → `BudgetPosition`
- `get_policy_guidance(sku, warehouse_id, target_cover_days)` → `PolicyGuidance`

### Write-Only Tools (Deterministic Nodes Only)

⚠️ **No LLM agents may call these.**

#### Execution (`tools/execution.py`)
- `revalidate_approved_proposal(proposal_id, proposal_hash)` → `RevalidationResult`
- `create_purchase_request(proposal, idempotency_key, approved_by)` → `PurchaseRequestResult`
- `append_audit_event(case_id, trace_id, actor, event_type, payload)` → `AuditEventResult`

---

## Tool Guarantees

Every tool that reads from the database provides:

1. **`retrieved_at`** — UTC timestamp when data was retrieved
2. **`evidence_id`** — Unique reference ID for audit trail (format: `domain:details`)
3. **Typed error codes** — Standard `ErrorCode` enum, never free-form text
4. **No secrets in output** — Vendor names are untrusted data, not instructions

**Example:**
```python
stock = get_stock_position("AC-001", "DEL-01")
# Returns:
# StockPosition(
#     snapshot_id="INV-AC001-1",
#     on_hand=50, reserved=10, confirmed_inbound=0,
#     available = 50 - 10 + 0 = 40 units,
#     evidence_id="stock:INV-AC001-1",
#     retrieved_at=2026-08-30T07:42:00Z
# )
```

## Key Constraints

### 1. No Generic SQL
- ✅ Use provided read tools
- ❌ No `SELECT *` or arbitrary SQL to LLM agents
- ❌ No direct database connection credentials

### 2. Calculation Authority
- ✅ Use `calculate_stock_risk()` for stock math
- ✅ Use `build_vendor_options()` for option comparison
- ❌ Agents cannot invent stock levels, prices, or reliability scores

### 3. Write Safety
- ✅ Only deterministic (non-LLM) nodes call write tools
- ✅ Only after explicit human approval
- ✅ Only after successful revalidation
- ❌ Never from within an LLM agent
- ❌ Never before human approval pause

### 4. Approval is an Interrupt
- ✅ Pause execution with durable case ID and thread state
- ✅ Wait for explicit human decision (APPROVED / REJECTED)
- ❌ Never infer approval from chat text
- ❌ Never auto-approve

### 5. Idempotent Writes
- ✅ Use idempotency key to prevent duplicates
- ✅ Database UNIQUE constraint on `idempotency_key`
- ✅ Same approval resumed twice creates one purchase request
- ❌ Never write without idempotency key

---

## Acceptance Scenarios

The database includes 12 test scenarios:

1. **Healthy stock** — NO_ACTION, no vendor analysis
2. **Missing data** — NEEDS_INFORMATION, specific field error
3. **Stale stock** — BLOCKED, DATA_STALE
4. **Cost vs. speed** — Proposal explains trade-off with evidence
5. **Over budget** — BLOCKED or exception, no auto-write
6. **Invalid model output** — One repair attempt, then fail closed
7. **Approval data changes** — Old approval invalidated, revalidation fails
8. **Duplicate approval** — One purchase request via idempotency key
9. **Human rejection** — BLOCKED, not rejected silently
10. **Write failure** — WRITE_FAILED, no partial data
11. **Insufficient history** — INSUFFICIENT_DATA, not invented
12. **Unreliable vendor** — No eligible options, BLOCKED

Load these with:
```python
import json
with open("fixtures/scenarios.json") as f:
    scenarios = json.load(f)["acceptance_scenarios"]
```

---

## What You Design

Your submission must include:

- ✅ **Agents** — 2–4 specialized agents with justified objectives
- ✅ **State** — Persistent shared state across nodes (`state/state.py`)
- ✅ **Graph** — LangGraph workflow with pause/resume and revalidation
- ✅ **Contracts** — Pydantic models for agent output validation
- ✅ **Approval** — Human interrupt with durable pause/resume
- ✅ **Tests** — All 12 scenarios plus 3+ failure paths
- ✅ **Audit Trail** — Reconstructable decision history
- ✅ **Documentation** — Architecture diagram and agent charters

---

## What You Do NOT Design

- ❌ Inventory database or seeded data (we provide this)
- ❌ Read-only tool implementations (we provide these)
- ❌ Pydantic models for tool I/O (we provide these)
- ❌ Generic SQL or direct database access
- ❌ A chat interface (simple CLI or Streamlit is fine)
- ❌ Weather APIs, RAG, vector databases, or extra frameworks

---

## Success Criteria

- ✅ All 12 acceptance scenarios have passing tests
- ✅ Authoritative numbers come from tools, not LLM
- ✅ Approval is explicit and resumable
- ✅ Revalidation blocks stale approvals
- ✅ Idempotency prevents duplicate requests
- ✅ Audit events reconstruct every decision
- ✅ Agents cannot call write tools
- ✅ Each agent has a clear reason to exist
- ✅ Code is clean, understandable, and defensible

---

## Troubleshooting

### Database doesn't exist
```bash
python database/seed.py
```

### Import errors
```bash
# Ensure all __init__.py files exist
# Check PYTHONPATH includes the project root
python -c "from domain.tool_models import ProductRecord; print('OK')"
```

### Timestamp issues
- All tool timestamps are UTC
- Use `datetime.utcnow()` in your code
- Store and compare as datetime objects, not strings

### Pydantic validation errors
- Check that agent output matches the declared schema
- Use `model_validate()` to debug
- The error message will pinpoint the missing/wrong field

---

## Next Steps

1. Read the problem brief in `Inventra_Student_Design_Challenge.docx`
2. Set up: `python database/seed.py`
3. Explore the database and load test scenarios
4. Design your agent boundaries and tool permissions
5. Create `submission/state/state.py` for shared state
6. Build your LangGraph workflow
7. Implement each agent with clear prompts and output validation
8. Test against all 12 acceptance scenarios
9. Write clear design documentation

Good luck! 🚀
