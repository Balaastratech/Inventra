---
document_id: inventra.sourcing_agent_interface
source_file: Sourcing Agent Interface.pdf
source_type: pdf
source_role: agent_contract
authority: implementation_interface
implementation_path: submission/agents/sourcing.py
source_status: built_and_tested
conversion: cleaned_markdown
---

# Sourcing Agent Interface

## Purpose
The Sourcing Agent is entered only for an already confirmed at-risk case. It evaluates vendor evidence and returns either a grounded eligible recommendation or a blocked result.

**Core invariant:** the model may narrate the trade-off, but deterministic code decides `ELIGIBLE` vs `BLOCKED`.

## LLM-call behavior
1. Precondition: `risk: StockRisk` must exist. Missing risk -> `BLOCKED`; no model call.
2. First model attempt calls `list_vendor_offers` -> `get_vendor_performance` -> `build_vendor_options` -> `recommend_vendor_option`, then drafts `SourcingOutput`.
3. A second model attempt occurs only for missing/schema-invalid output. Two failures -> fail closed.
4. `derive_sourcing_result()` recomputes `ELIGIBLE` / `BLOCKED` from typed raw tool results; model status is discarded.

## Full call chain
1. `run_sourcing()` - `sourcing.py:158`
2. `build_sourcing_agent()` - `sourcing.py:88`
3. `invoke_with_repair()` - `_common.py` **LLM call site**
4. `list_vendor_offers(sku)` - `tools/vendors.py:28`
5. `get_vendor_performance(vendor_ids)` - `tools/vendors.py:106`
6. `build_vendor_options(stock_risk, offers, performance)` - `tools/vendors.py:173`
7. `recommend_vendor_option(case_id, sku, warehouse_id, options, strategy)` - `tools/workflow.py:29`
8. `extract_tool_evidence()` - `_common.py`
9. Pydantic validation of vendor result objects
10. `derive_sourcing_result()` - `sourcing.py:98`
11. `_collect_evidence_ids()` - `sourcing.py:136`

## Input
```text
case_id: str
sku: str
warehouse_id: str
risk: StockRisk
strategy: str = "balanced"
```

## Output states
| Status | Meaning |
|---|---|
| `BLOCKED` | Missing risk, vendor data unavailable, no option meets deadline + reliability, or no recommendation. |
| `ELIGIBLE` | At least one vendor option clears deadline and reliability; continues to Policy/Proposal. |

Visible blocked reasons:
```text
AGENT_FAILURE
VENDOR_OFFERS_UNAVAILABLE
VENDOR_PERFORMANCE_UNAVAILABLE
NO_ELIGIBLE_VENDOR
NO_RECOMMENDATION
```

## Handoff to Policy/Proposal
```text
case_id                          -> Policy.case_id
sku / warehouse_id              -> Policy.sku / warehouse_id
recommendation.recommended_option
                                 -> draft_replenishment_proposal(recommendation=...)
reason (trade-off narrative)    -> proposal trade-off text
evidence_ids                    -> audit_event_ids += evidence_ids
```

The recommended vendor's price, quantity, and arrival date remain typed `VendorOption` data and are not re-derived by another LLM.

## SourcingOutput fields visible across the source
```text
case_id
sku
warehouse_id
strategy
status
reason
recommendation
vendor_options
evidence_ids
blocked_reason
```

> **Source limitation:** the final field-reference table is physically clipped on the right in the PDF export. The field list above uses only fields visible elsewhere in the same source.
