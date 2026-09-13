"""
Shared workflow state for one Inventra case.

One CaseState per case_id / thread_id, persisted by the LangGraph
SqliteSaver checkpointer across the human-approval interrupt (and across a
process restart, since email approval links are handled by a separate
process — see graph/approval_server.py, Phase 3).

Reuses the starter package's Pydantic models (domain/tool_models.py) for
every field that already has a typed shape there, instead of redefining
them. The three new agent-judgment models live in agents/models.py.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Optional, TypedDict

from domain.tool_models import (
    ApprovalDecision,
    BudgetPosition,
    ErrorCode,
    PolicyGuidance,
    ProductRecord,
    ProposalStatus,
    PurchaseRequestResult,
    ReplenishmentProposal,
    RevalidationResult,
    SalesVelocity,
    StockPosition,
    StockRisk,
    SkuPolicy,
    VendorOfferList,
    VendorOptionList,
    VendorPerformanceList,
    VendorSendDecision,
)

from submission.agents.models import (
    DemandAssessment,
    PolicyReview,
    ReplenishmentRecommendation,
)

# Imported for real, not under TYPE_CHECKING: LangGraph resolves CaseState's
# annotations at runtime, so a forward reference here raises NameError when the
# graph is built. Safe -- graph/economics.py imports only submission.config, so
# there is no cycle back to this module.
from submission.graph.economics import OptionsEconomics


class CaseState(TypedDict, total=False):
    # --- Identity ---
    case_id: str
    thread_id: str
    trace_id: str

    # --- Validated request ---
    sku: str
    warehouse_id: str
    # Unset until fresh sales evidence and the SKU policy decide whether this
    # is derived (ESTABLISHED) or the one permitted manual cover-days input.
    target_cover_days: Optional[int]
    budget_month: str
    sku_policy_snapshot: Optional[SkuPolicy]
    target_reconciliation: Optional[object]
    policy_floor: Optional[object]
    target_provenance: str
    target_mode: str

    # --- Derived economics (deterministic; single source of truth shared by
    #     the Strategist prompt, the recommendation gate, and the UI) ---
    economics: Optional[OptionsEconomics]

    # --- Evidence (raw tool reads; kept for audit + revalidation, never mutated) ---
    product: Optional[ProductRecord]
    stock: Optional[StockPosition]
    sales: Optional[SalesVelocity]
    risk: Optional[StockRisk]
    vendor_offers: Optional[VendorOfferList]
    vendor_performance: Optional[VendorPerformanceList]
    vendor_options: Optional[VendorOptionList]
    budget: Optional[BudgetPosition]
    policy_guidance: Optional[PolicyGuidance]

    # --- Agent decisions (Pydantic-validated judgment, never raw dicts) ---
    demand_assessment: Optional[DemandAssessment]
    replenishment_recommendation: Optional[ReplenishmentRecommendation]
    proposal: Optional[ReplenishmentProposal]
    policy_review: Optional[PolicyReview]

    # --- Control ---
    status: ProposalStatus
    revision_count: int
    retry_counts: dict[str, int]  # node_name -> model attempts used so far
    error_code: Optional[ErrorCode]
    error_detail: Optional[str]

    # --- Human action ---
    approval_decision: Optional[ApprovalDecision]
    vendor_send_decision: Optional[VendorSendDecision]

    # --- Post-approval ---
    revalidation: Optional[RevalidationResult]

    # --- Outcome ---
    purchase_result: Optional[PurchaseRequestResult]
    idempotency_key: Optional[str]

    # --- Structured detail for the no-eligible-vendors BLOCKED case (Gap 2) ---
    vendor_rejection_detail: Optional[dict]


RUN_SEPARATOR = "#"


def new_case_id(sku: str, warehouse_id: str) -> str:
    """Stable business identity for a product at a warehouse.

    Never forks -- a revision bumps the proposal version, not this (D8). It
    is what audit_events rows join on, so every run of the same product at
    the same warehouse shares one case_id and one readable history.
    """
    return f"CASE-{sku}-{warehouse_id}"


def new_thread_id(case_id: str) -> str:
    """Per-run checkpoint identity: `<case_id>#<utc timestamp>`.

    thread_id used to be exactly case_id, which meant a case had one
    checkpoint thread for all time. Once a case reached a terminal state
    (rejected, blocked, ordered), starting the same product again resumed
    that finished thread instead of running fresh -- so a rejected product
    could never be re-examined. Harmless while the CLI was the only entry
    point and someone had to retype the SKU; a real bug the moment the
    watchlist gave people a button to click.

    The timestamp is fixed-width and UTC, so lexicographic order equals
    chronological order and `max()` over the matching thread ids finds the
    latest run without needing a separate index -- see
    graph.workflow.latest_thread_id.
    """
    return f"{case_id}{RUN_SEPARATOR}{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%f')}"


def create_initial_state(
    sku: str,
    warehouse_id: str,
    target_cover_days: Optional[int] = None,
    budget_month: Optional[str] = None,
    sku_policy_snapshot: Optional[SkuPolicy] = None,
) -> CaseState:
    """Build the starting state for a new case. No evidence fetched yet —
    that happens in the first deterministic node."""
    from submission.config import config

    case_id = new_case_id(sku, warehouse_id)
    now = datetime.now(timezone.utc)
    return CaseState(
        case_id=case_id,
        thread_id=new_thread_id(case_id),
        trace_id=str(uuid.uuid4()),
        sku=sku,
        warehouse_id=warehouse_id,
        # A caller-supplied value is retained only for backwards-compatible
        # internal state construction. resolve_target_cover never accepts it
        # as a public demand, quantity, or target override.
        target_cover_days=target_cover_days,
        budget_month=budget_month or now.strftime("%Y-%m"),
        sku_policy_snapshot=sku_policy_snapshot,
        target_reconciliation=None,
        policy_floor=None,
        target_provenance="pending",
        target_mode="UNRESOLVED",
        product=None,
        stock=None,
        sales=None,
        risk=None,
        vendor_offers=None,
        vendor_performance=None,
        vendor_options=None,
        economics=None,
        budget=None,
        policy_guidance=None,
        demand_assessment=None,
        replenishment_recommendation=None,
        proposal=None,
        policy_review=None,
        status=ProposalStatus.NEEDS_INFORMATION,
        revision_count=0,
        retry_counts={},
        error_code=None,
        error_detail=None,
        approval_decision=None,
        vendor_send_decision=None,
        revalidation=None,
        purchase_result=None,
        idempotency_key=None,
        vendor_rejection_detail=None,
    )
