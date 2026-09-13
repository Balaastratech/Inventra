---
document_id: inventra.investigator_agent_interface
source_file: Investigator Agent Interface.pdf
source_type: pdf
source_role: agent_contract
authority: implementation_interface
implementation_path: submission/agents/investigator.py
source_status: built_and_tested
conversion: cleaned_markdown
---

# Investigator Agent Interface

## Purpose
The Investigator decides whether a stockout case needs sourcing at all. It validates the request, gathers read-only evidence, narrates the reason, and then lets deterministic code derive the authoritative status.

**Core invariant:** the LLM may choose tool calls and write prose, but the LLM's proposed status is discarded. `derive_status()` recomputes the branch decision from raw tool evidence.

## Input
```text
case_id: str
sku: str | None
warehouse_id: str | None
target_cover_days: int | None
```

## Pipeline
1. `validate_input()` rejects bad input before any tool call.
2. Call `get_product`, `get_stock_position`, `get_sales_velocity`, and `calculate_stock_risk`.
3. The LLM narrates a structured response.
4. One repair attempt is allowed if output is invalid; repeated invalid output fails closed.
5. `derive_status()` recomputes status from raw evidence; the model's status is discarded.

## Output states
Only `AT_RISK` continues to Sourcing.

| Status | Meaning | Important populated data |
|---|---|---|
| `NO_ACTION` | Coverage is healthy. | `product`, `stock`, `sales`, `risk`, `evidence_ids` |
| `NEEDS_INFORMATION` | Bad input or sales history too thin to trust. | `reason`, `error_code`; evidence depends on where the failure happened |
| `BLOCKED` | SKU/warehouse unresolvable, item inactive, or snapshot stale. | evidence where available; `risk` is present for `DATA_STALE` |
| `AT_RISK` | Coverage is shorter than target. | `product`, `stock`, `sales`, `risk`, `evidence_ids` |

## Handoff to Sourcing
```text
InvestigatorOutput.status = AT_RISK
case_id          -> Sourcing.case_id
sku              -> Sourcing.sku
warehouse_id     -> Sourcing.warehouse_id
risk: StockRisk  -> build_vendor_options(stock_risk=risk)
evidence_ids     -> audit_event_ids += evidence_ids
```

## InvestigatorOutput field reference
| Field | Type | Population rule |
|---|---|---|
| `case_id` | `str` | Always |
| `sku` / `warehouse_id` / `target_cover_days` | Optional | Echoed from input where available |
| `status` | `InvestigatorStatus` | Always; deterministic branch status |
| `reason` | `str` | Always; narrative |
| `missing_field` | `Optional[str]` | `NEEDS_INFORMATION` from bad input |
| `error_code` | `Optional[ErrorCode]` | Conditions include `NOT_FOUND`, `INACTIVE`, `DATA_STALE`, `INSUFFICIENT_DATA`, invalid output |
| `product` / `stock` / `sales` | Optional typed records | Populated after matching tool succeeds |
| `risk` | `Optional[StockRisk]` | Populated after valid product/stock/sales evidence; passed to Sourcing |

> **Source limitation:** the original PDF was exported from a horizontally scrollable browser artifact, so the far-right text of the final field table is physically clipped. No hidden text was invented.
