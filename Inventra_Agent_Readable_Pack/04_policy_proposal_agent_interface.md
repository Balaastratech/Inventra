---
document_id: inventra.policy_proposal_agent_interface
source_file: Policy_Proposal Agent Interface.pdf
source_type: pdf
source_role: agent_contract
authority: implementation_interface
implementation_path: submission/agents/policy.py
source_status: built_and_tested
conversion: cleaned_markdown
---

# Policy / Proposal Agent Interface

## Purpose
The Policy/Proposal Agent reviews upstream evidence, loads budget and policy guidance, creates a hash-locked proposal, and hands only a budget-valid proposal to human approval.

**Hard guardrail:** a budget shortfall is decided in deterministic code. The model cannot talk past it.

## LLM-call behavior
1. Before any model call, require Investigator evidence (`stock`, `sales`, `risk`) and an eligible Sourcing recommendation. Missing data -> `BLOCKED`, no model call.
2. First model attempt calls `get_budget_position` -> `get_policy_guidance` -> `draft_replenishment_proposal`, then drafts `ProposalOutput`.
3. Second attempt only for missing/schema-invalid output. Two failures -> fail closed.
4. `derive_policy_result()` compares real `proposal.total_cost` to real `budget.remaining` and writes `policy_passed` / `policy_violations`. The model's own budget judgment is discarded.

## Full call chain
1. `run_policy_proposal()` - `policy.py:158`
2. `build_policy_agent()` - `policy.py:96`
3. `invoke_with_repair()` - `_common.py` **LLM call site**
4. `get_budget_position(warehouse_id, budget_month)` - `tools/policy.py:25`
5. `get_policy_guidance(sku, warehouse_id, target_cover_days)` - `tools/policy.py:100`
6. `draft_replenishment_proposal(ProposalDraftInput)` - `tools/workflow.py:81`
   - Deterministic proposal construction and SHA-256 `proposal_hash`
   - Initial `policy_passed=False`
7. `extract_tool_evidence()` - `_common.py`
8. Pydantic validation of budget/proposal objects
9. `derive_policy_result()` - `policy.py:106`
10. `proposal.model_copy(update=...)` - `policy.py:223`

## Input
```text
case_id
sku
warehouse_id
stock
sales
risk
recommendation: VendorRecommendation
budget_month: str  # default: current month
```

## Output states
| Status | Meaning |
|---|---|
| `BLOCKED` | Missing upstream evidence, budget unavailable, cost exceeds remaining budget, or agent failure. |
| `AWAITING_APPROVAL` | Proposal cost fits remaining budget; continues to deterministic human-approval node. |

Visible blocked reasons:
```text
AGENT_FAILURE
BUDGET_UNAVAILABLE
OVER_BUDGET
```

On `AWAITING_APPROVAL`:
```text
proposal.policy_passed = True
proposal.policy_violations = []
```

## Handoff to human approval
```text
proposal (hash-locked)          -> prepare_approval_request(proposal=...)
proposal.policy_passed = True
case_id                         -> request_approval.case_id
reason (budget narrative)
evidence_ids                    -> audit_event_ids += evidence_ids
interrupt()                     -> pauses for a human
```

The approved proposal is hash-locked. The document states that `proposal_hash` is later checked by `revalidate_approved_proposal`.

## ProposalOutput fields visible in the source
| Field | Meaning |
|---|---|
| `case_id` / `sku` / `warehouse_id` | echoed identifiers |
| `status` | `PolicyStatus`, deterministically set |
| `reason` | narrative |
| `blocked_reason` | optional blocked reason |
| `proposal` | optional `ReplenishmentProposal` |
| `budget` | `BudgetPosition | None` in output diagram |
| `evidence_ids` | audit evidence references |

> **Source limitation:** the final field-reference table is physically clipped on the right in the PDF export. No missing right-column wording was fabricated.
