"""
Inventra Tool Models
Pydantic schemas for all tool inputs and outputs.
All models are typed and validated.
"""

from pydantic import BaseModel, Field, model_validator
from typing import Optional, List
from datetime import date, datetime
from enum import Enum


# ============================================================================
# ENUMS
# ============================================================================

class ErrorCode(str, Enum):
    """Typed error codes returned by tools."""
    NOT_FOUND = "NOT_FOUND"
    INACTIVE = "INACTIVE"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"
    DATA_STALE = "DATA_STALE"
    INVALID_INPUT = "INVALID_INPUT"
    UNAUTHORIZED = "UNAUTHORIZED"
    WRITE_FAILED = "WRITE_FAILED"
    UNKNOWN_ERROR = "UNKNOWN_ERROR"


class ProposalStatus(str, Enum):
    """Workflow outcome status."""
    NO_ACTION = "NO_ACTION"
    NEEDS_INFORMATION = "NEEDS_INFORMATION"
    BLOCKED = "BLOCKED"
    AWAITING_APPROVAL = "AWAITING_APPROVAL"
    AWAITING_VENDOR_APPROVAL = "AWAITING_VENDOR_APPROVAL"
    PURCHASE_REQUEST_CREATED = "PURCHASE_REQUEST_CREATED"
    PURCHASE_REQUEST_CANCELLED = "PURCHASE_REQUEST_CANCELLED"


class PurchaseRequestStatus(str, Enum):
    """Purchase request lifecycle.

    Note on PENDING: nothing in this system moves a request out of PENDING
    automatically. There is no vendor-confirmation callback and no
    goods-received step, so CONFIRMED is reachable only if some future
    process (or a person) sets it. PENDING therefore means "written and not
    yet cancelled" -- never "the supplier acknowledged it".

    CANCELLED is a human-only, deliberate withdrawal of a PENDING request
    (see tools.execution.cancel_purchase_request). It is distinct from
    REJECTED, which reads as "the supplier declined", and from FAILED, which
    means the write itself did not succeed.
    """
    PENDING = "PENDING"
    CONFIRMED = "CONFIRMED"
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"
    FAILED = "FAILED"


# ============================================================================
# INVENTORY TOOLS
# ============================================================================

class ProductRecord(BaseModel):
    """Result of get_product()."""
    sku: str = Field(..., description="Product SKU")
    name: str = Field(..., description="Product name")
    category: str = Field(..., description="Product category")
    active: bool = Field(..., description="Whether product is active")
    evidence_id: str = Field(..., description="Tool evidence ID")
    retrieved_at: datetime = Field(..., description="UTC timestamp when data was retrieved")
    error: Optional[ErrorCode] = Field(None, description="Error code if lookup failed")


# ============================================================================
# PHASE A DATA FOUNDATION TOOLS
# ============================================================================

class Warehouse(BaseModel):
    warehouse_id: str
    name: str
    storage_cost_per_m3_month: float
    evidence_id: str
    retrieved_at: datetime
    error: Optional[ErrorCode] = None


class StockReceipt(BaseModel):
    receipt_id: str
    request_id: Optional[str] = None
    sku: str
    warehouse_id: str
    vendor_id: str
    quantity_ordered: int
    quantity_received: int
    ordered_at: datetime
    promised_at: datetime
    received_at: datetime
    lead_time_days_actual: float
    evidence_id: str
    retrieved_at: datetime
    error: Optional[ErrorCode] = None


class LatenessDistribution(BaseModel):
    vendor_id: str
    sku: Optional[str] = None
    n_observations: int
    on_time_rate_measured: float
    mean_late_days: float
    p50_late_days: float
    p90_late_days: float
    evidence_id: str
    retrieved_at: datetime
    error: Optional[ErrorCode] = None


class PolicyFloor(BaseModel):
    rule_id: str
    sku: str
    warehouse_id: str
    min_units: Optional[int] = None
    min_cover_days: Optional[float] = None
    reason: str
    source: str
    set_by: str
    effective_from: datetime
    effective_to: Optional[datetime] = None
    active: bool
    evidence_id: str
    retrieved_at: datetime
    error: Optional[ErrorCode] = None


class StockPosition(BaseModel):
    """Result of get_stock_position()."""
    snapshot_id: str = Field(..., description="Unique inventory snapshot ID")
    sku: str = Field(..., description="Product SKU")
    warehouse_id: str = Field(..., description="Warehouse identifier")
    on_hand: int = Field(..., description="Units physically in warehouse")
    reserved: int = Field(..., description="Units reserved for other orders")
    confirmed_inbound: int = Field(..., description="Units in transit, confirmed")
    captured_at: datetime = Field(..., description="UTC timestamp when snapshot was taken")
    evidence_id: str = Field(..., description="Tool evidence ID")
    retrieved_at: datetime = Field(..., description="UTC timestamp when data was retrieved")
    error: Optional[ErrorCode] = Field(None, description="Error code if lookup failed")


class SalesVelocity(BaseModel):
    """Result of get_sales_velocity()."""
    sku: str = Field(..., description="Product SKU")
    warehouse_id: str = Field(..., description="Warehouse identifier")
    window_7_days: float = Field(..., description="Average units sold per day, last 7 days")
    window_30_days: float = Field(..., description="Average units sold per day, last 30 days")
    observation_count_7: int = Field(..., description="Number of sales records in 7-day window")
    observation_count_30: int = Field(..., description="Number of sales records in 30-day window")
    evidence_id: str = Field(..., description="Tool evidence ID")
    retrieved_at: datetime = Field(..., description="UTC timestamp when data was retrieved")
    error: Optional[ErrorCode] = Field(None, description="Error code if lookup failed")


class DemandHistory(BaseModel):
    """Zero-filled daily demand over an explicit inclusive date range."""
    sku: str
    warehouse_id: str
    start_date: date
    end_date: date
    daily_units: List[int]
    evidence_id: str
    retrieved_at: datetime
    error: Optional[ErrorCode] = None


class SkuPolicy(BaseModel):
    sku: str
    warehouse_id: str
    as_of_date: date
    mean_daily_demand: float = 0
    std_daily_demand: float = 0
    cv: Optional[float] = None
    adi: Optional[float] = None
    cv_squared: Optional[float] = None
    demand_quadrant: str = "SMOOTH"
    abc_class: str = "C"
    xyz_class: str = "Z"
    consumption_value_12m: float = 0
    cumulative_share: float = 1
    service_level: float = 0
    safety_stock_units: float = 0
    reorder_point_units: float = 0
    derived_cover_days: Optional[float] = None
    statistical_target_units: Optional[float] = None
    active_target_units: Optional[float] = None
    maturity: str = "INSUFFICIENT"
    confidence: float = 0
    candidate_class: Optional[str] = None
    candidate_since: Optional[date] = None
    consecutive_confirmations: int = 0
    active_class: str = "C"
    change_reason: str = ""


class ParkedItemRecord(BaseModel):
    park_id: str
    sku: str
    warehouse_id: str
    reason: str
    parked_at: datetime
    resolved_at: Optional[datetime] = None
    resolved_by: Optional[str] = None
    note: str = ""


class SweepRun(BaseModel):
    sweep_id: str
    started_at: datetime
    completed_at: Optional[datetime] = None
    warehouse_ids: list[str]
    pairs_examined: int = 0
    candidates_found: int = 0
    parked_count: int = 0
    deferred_for_budget_count: int = 0
    cases_opened: int = 0
    reminders_sent: int = 0
    total_model_calls_estimate: int = 0
    detail: list[dict] = Field(default_factory=list)


class StockRisk(BaseModel):
    """Result of calculate_stock_risk() - pure deterministic calculation."""
    available_units: int = Field(..., description="on_hand - reserved + confirmed_inbound")
    daily_velocity: float = Field(..., description="Daily sales rate used (user-selected window)")
    cover_days: Optional[float] = Field(None, description="Days of supply at current velocity, or undefined at zero demand")
    projected_stockout_date: Optional[datetime] = Field(None, description="Projected date when stock reaches 0")
    target_cover_days: int = Field(..., description="Target coverage days (user input)")
    at_risk: bool = Field(..., description="True if cover_days < target_cover_days")
    freshness_hours: float = Field(..., description="Hours since inventory snapshot was captured")
    stale: bool = Field(..., description="True if freshness_hours > 48 (2-day stale threshold)")


# ============================================================================
# SALES TOOLS
# ============================================================================
class SalesInput(BaseModel):
    """Input to get_sales_velocity()."""
    sku: str = Field(..., description="Product SKU")
    warehouse_id: str = Field(..., description="Warehouse identifier")
    windows: tuple = Field(default=(7, 30), description="Day windows for analysis")


class ProductInput(BaseModel):
    """Input to get_product()."""
    sku: str = Field(..., description="Product SKU")


class StockPositionInput(BaseModel):
    """Input to get_stock_position()."""
    sku: str = Field(..., description="Product SKU")
    warehouse_id: str = Field(..., description="Warehouse identifier")


class StockRiskInput(BaseModel):
    """Input to calculate_stock_risk()."""
    available_units: int = Field(..., description="Current available units")
    daily_velocity: float = Field(..., description="Daily sales rate")
    target_cover_days: int = Field(..., ge=7, le=45, description="Target coverage days (7-45)")
    snapshot_captured_at: datetime = Field(..., description="UTC timestamp of the inventory snapshot")


# ============================================================================
# VENDOR TOOLS
# ============================================================================

class VendorOffer(BaseModel):
    """Single vendor offer for a SKU."""
    offer_id: str = Field(..., description="Unique offer ID")
    vendor_id: str = Field(..., description="Vendor identifier")
    vendor_name: str = Field(..., description="Vendor name")
    unit_price: float = Field(..., description="Price per unit")
    moq: int = Field(..., description="Minimum order quantity")
    lead_time_days: int = Field(..., description="Expected lead time in days")
    valid_until: datetime = Field(..., description="Offer expiration time (UTC)")
    active: bool = Field(..., description="Whether offer is currently active")
    evidence_id: str = Field(..., description="Tool evidence ID")
    freight_flat: Optional[float] = None
    freight_per_unit: Optional[float] = None


class VendorOfferList(BaseModel):
    """Result of list_vendor_offers()."""
    sku: str = Field(..., description="Product SKU")
    offers: List[VendorOffer] = Field(..., description="Active, valid vendor offers")
    expired_count: int = Field(default=0, description="Number of expired offers (excluded)")
    inactive_count: int = Field(default=0, description="Number of offers from inactive vendors")
    retrieved_at: datetime = Field(..., description="UTC timestamp when data was retrieved")
    evidence_id: str = Field(..., description="Tool evidence ID")
    error: Optional[ErrorCode] = Field(None, description="Error code if lookup failed")


class VendorPerformance(BaseModel):
    """Performance metrics for a single vendor."""
    vendor_id: str = Field(..., description="Vendor identifier")
    vendor_name: str = Field(..., description="Vendor name")
    on_time_rate: float = Field(..., ge=0.0, le=1.0, description="Fraction of on-time deliveries")
    fill_rate: float = Field(..., ge=0.0, le=1.0, description="Fraction of orders fully fulfilled")
    quality_score: float = Field(..., ge=0.0, le=1.0, description="Quality rating")
    reliability: float = Field(..., ge=0.0, le=1.0, description="Combined reliability (average of metrics)")
    eligible: bool = Field(..., description="True if reliability >= 0.90")
    evidence_id: str = Field(..., description="Tool evidence ID")


class VendorPerformanceList(BaseModel):
    """Result of get_vendor_performance()."""
    vendors: List[VendorPerformance] = Field(..., description="Performance metrics by vendor ID")
    retrieved_at: datetime = Field(..., description="UTC timestamp when data was retrieved")
    error: Optional[ErrorCode] = Field(None, description="Error code if lookup failed")


class VendorOption(BaseModel):
    """Comparable vendor option for replenishment (output of build_vendor_options())."""
    offer_id: str = Field(..., description="Reference to vendor offer")
    vendor_id: str = Field(..., description="Vendor identifier")
    vendor_name: str = Field(..., description="Vendor name")
    quantity: int = Field(..., description="Order quantity (respects MOQ)")
    unit_price: float = Field(..., description="Price per unit")
    total_cost: float = Field(..., description="Quantity * unit_price")
    lead_time_days: int = Field(..., description="Expected lead time")
    expected_arrival: datetime = Field(..., description="Projected arrival date (now + lead_time)")
    meets_deadline: bool = Field(..., description="True if arrival before projected stockout")
    reliable: bool = Field(..., description="True if vendor reliability >= 0.90")
    eligible: bool = Field(..., description="True if both meets_deadline and reliable")
    flag_cheapest: bool = Field(default=False, description="True if lowest cost option")
    flag_fastest: bool = Field(default=False, description="True if earliest arrival")
    freight_flat: Optional[float] = None
    freight_per_unit: Optional[float] = None


class BuildVendorOptionsInput(BaseModel):
    """Input to build_vendor_options()."""
    stock_risk: StockRisk = Field(..., description="Risk assessment output")
    vendor_offers: VendorOfferList = Field(..., description="Available offers")
    vendor_performance: VendorPerformanceList = Field(..., description="Vendor reliability")


class VendorOffersInput(BaseModel):
    """Input to list_vendor_offers()."""
    sku: str = Field(..., description="Product SKU")


class VendorPerformanceInput(BaseModel):
    """Input to get_vendor_performance()."""
    vendor_ids: List[str] = Field(..., description="Vendor IDs to evaluate")


class VendorOptionList(BaseModel):
    """Result of build_vendor_options() - pure deterministic calculation."""
    options: List[VendorOption] = Field(..., description="Comparable, sorted by cost")
    eligible_options: List[VendorOption] = Field(..., description="Options that meet deadline and reliability")
    cheapest_option: Optional[VendorOption] = Field(None, description="Lowest-cost option (may not be eligible)")
    fastest_option: Optional[VendorOption] = Field(None, description="Earliest arrival (may not be cheapest)")
    
    class Config:
        json_schema_extra = {
            "example": {
                "options": [],
                "eligible_options": [],
                "cheapest_option": None,
                "fastest_option": None,
            }
        }


class VendorRecommendationInput(BaseModel):
    """Input to choose a recommended vendor option."""
    case_id: str = Field(..., description="Case identifier")
    sku: str = Field(..., description="Product SKU")
    warehouse_id: str = Field(..., description="Warehouse identifier")
    vendor_options: VendorOptionList = Field(..., description="Comparable vendor options")
    strategy: str = Field(
        default="balanced",
        description="Selection strategy: balanced, cheapest, or fastest",
    )


class VendorRecommendation(BaseModel):
    """Recommended vendor option with human-readable reasoning."""
    case_id: str = Field(..., description="Case identifier")
    sku: str = Field(..., description="Product SKU")
    warehouse_id: str = Field(..., description="Warehouse identifier")
    strategy: str = Field(..., description="Strategy used for recommendation")
    recommended_option: Optional[VendorOption] = Field(None, description="Chosen option")
    rationale: str = Field(..., description="Plain-English explanation of the recommendation")
    blocked: bool = Field(default=False, description="True if no valid option is available")
    blocked_reason: Optional[str] = Field(None, description="Why the recommendation is blocked")


# ============================================================================
# POLICY TOOLS
# ============================================================================

class BudgetPosition(BaseModel):
    """Result of get_budget_position()."""
    warehouse_id: str = Field(..., description="Warehouse identifier")
    month: str = Field(..., description="Month in YYYY-MM format")
    budget_amount: float = Field(..., description="Total monthly budget")
    spent_amount: float = Field(..., description="Already spent in month")
    committed_amount: float = Field(..., description="Committed via pending requests")
    remaining: float = Field(..., description="budget_amount - spent_amount - committed_amount")
    retrieved_at: datetime = Field(..., description="UTC timestamp when data was retrieved")
    evidence_id: str = Field(..., description="Tool evidence ID")
    error: Optional[ErrorCode] = Field(None, description="Error code if lookup failed")


class BudgetPositionInput(BaseModel):
    """Input to get_budget_position()."""
    warehouse_id: str = Field(..., description="Warehouse identifier")
    budget_month: str = Field(..., description="Month in YYYY-MM format")


class PolicyGuidanceInput(BaseModel):
    """Input to get_policy_guidance()."""
    sku: str = Field(..., description="Product SKU under review")
    warehouse_id: str = Field(..., description="Warehouse identifier under review")
    target_cover_days: int = Field(..., ge=7, le=45, description="Requested target coverage days")


class PolicyGuidance(BaseModel):
    """Agent-readable policy instructions loaded from policy.md."""
    policy_version: str = Field(..., description="Simple policy version label")
    source_path: str = Field(..., description="Local path of the policy document")
    summary: str = Field(..., description="Short overview of how the agent should use the policy")
    policy_text: str = Field(..., description="Full policy guidance text")
    retrieved_at: datetime = Field(..., description="UTC timestamp when policy guidance was loaded")


# ============================================================================
# EXECUTION TOOLS
# ============================================================================

class RevalidationResult(BaseModel):
    """Result of revalidate_approved_proposal() - must check after approval."""
    proposal_id: str = Field(..., description="Original proposal identifier")
    proposal_hash: str = Field(..., description="Hash of original proposal")
    hash_matches: bool = Field(..., description="True if current proposal matches stored hash")
    stock_valid: bool = Field(..., description="True if stock snapshot is still current")
    offer_valid: bool = Field(..., description="True if offer is still active and valid")
    budget_valid: bool = Field(..., description="True if budget still sufficient")
    all_checks_pass: bool = Field(..., description="True if stock, offer, and budget all valid")
    error_details: Optional[str] = Field(None, description="Description of any failed check")


class RevalidationInput(BaseModel):
    """Input to revalidate_approved_proposal()."""
    proposal_id: str = Field(..., description="Original proposal identifier")
    proposal_hash: str = Field(..., description="Hash of the approved proposal")


class PurchaseRequestResult(BaseModel):
    """Result of create_purchase_request()."""
    request_id: str = Field(..., description="New or existing purchase request ID")
    case_id: str = Field(..., description="Case identifier")
    status: PurchaseRequestStatus = Field(..., description="Request status")
    created: bool = Field(..., description="True if newly created, False if idempotent return")
    total_cost: float = Field(..., description="Total cost of request")
    error: Optional[ErrorCode] = Field(None, description="Error code if write failed")
    error_details: Optional[str] = Field(None, description="Detailed error message")


class PurchaseRequestInput(BaseModel):
    """Input to create_purchase_request()."""
    proposal: "ReplenishmentProposal" = Field(..., description="Approved proposal to convert into a request")
    idempotency_key: str = Field(..., description="Unique key preventing duplicate writes")
    approved_by: str = Field(..., description="Named human approver")


class CancellationResult(BaseModel):
    """Result of cancel_purchase_request() (B3).

    `status` is the request's status *after* the attempt, so a refused
    cancellation still reports what the request actually is -- a caller
    should never have to guess whether a failure left it PENDING or not.
    """
    request_id: str = Field(..., description="Purchase request the cancellation targeted")
    case_id: Optional[str] = Field(None, description="Case the request belongs to, if found")
    cancelled: bool = Field(..., description="True only if this call moved it to CANCELLED")
    status: Optional[PurchaseRequestStatus] = Field(
        None, description="Status after the attempt; None if the request was not found"
    )
    error: Optional[ErrorCode] = Field(None, description="Error code if the cancellation was refused")
    error_details: Optional[str] = Field(None, description="Why it was refused, in plain language")
    budget_released: bool = Field(
        False, description="True if cancelling released a prior budget reservation back to monthly_budgets"
    )


class AuditEventResult(BaseModel):
    """Result of append_audit_event()."""
    event_id: str = Field(..., description="Unique event ID")
    case_id: str = Field(..., description="Case identifier")
    created: bool = Field(..., description="True if event was successfully logged")
    error: Optional[ErrorCode] = Field(None, description="Error code if write failed")


class AuditEventInput(BaseModel):
    """Input to append_audit_event()."""
    case_id: str = Field(..., description="Case identifier")
    trace_id: str = Field(..., description="Trace identifier for correlation")
    actor: str = Field(..., description="Who emitted the event")
    event_type: str = Field(..., description="Structured event type")
    payload: dict = Field(..., description="JSON-serializable event body")


# ============================================================================
# PROPOSAL MODELS
# ============================================================================

class ReplenishmentProposal(BaseModel):
    """Complete replenishment proposal for human review."""
    proposal_id: str = Field(..., description="Unique proposal identifier")
    proposal_hash: str = Field(..., description="SHA256 hash for integrity checking")
    case_id: str = Field(..., description="Case identifier")
    sku: str = Field(..., description="Product SKU")
    warehouse_id: str = Field(..., description="Warehouse identifier")
    
    # Evidence
    stock_evidence_id: str = Field(..., description="Inventory snapshot evidence ID")
    sales_evidence_id: str = Field(..., description="Sales velocity evidence ID")
    vendor_evidence_ids: List[str] = Field(default=[], description="Vendor offer evidence IDs")
    budget_evidence_id: str = Field(..., description="Budget position evidence ID")
    
    # Current facts
    available_units: int = Field(..., description="Current available stock")
    daily_velocity: float = Field(..., description="Daily sales rate")
    target_cover_days: int = Field(..., description="Target coverage days")
    projected_stockout_date: datetime = Field(..., description="When stock reaches zero")
    
    # Recommendation
    recommended_vendor_id: str = Field(..., description="Selected vendor ID")
    recommended_vendor_name: str = Field(..., description="Selected vendor name")
    quantity: int = Field(..., description="Order quantity")
    unit_price: float = Field(..., description="Unit price")
    total_cost: float = Field(..., description="Total cost")
    expected_arrival: datetime = Field(..., description="Expected delivery date")
    
    # Rationale
    cost_vs_speed_trade_off: Optional[str] = Field(None, description="Explanation if not cheapest")
    other_options_summary: Optional[str] = Field(None, description="Summary of alternatives considered")
    
    # Policy
    budget_remaining: float = Field(..., description="Budget remaining after this proposal")
    policy_passed: bool = Field(..., description="True if the reviewer judged the proposal acceptable under policy guidance")
    policy_violations: List[str] = Field(default=[], description="Policy concerns identified during human or agent review")
    policy_floor_units: Optional[float] = None
    statistical_target_units: Optional[float] = None
    active_target_units: Optional[float] = None
    target_basis: str = "STATISTICAL"
    target_provenance: str = "derived"
    
    created_at: datetime = Field(..., description="When proposal was created")


class ProposalDraftInput(BaseModel):
    """Input to create a replenishment proposal draft."""
    case_id: str = Field(..., description="Case identifier")
    sku: str = Field(..., description="Product SKU")
    warehouse_id: str = Field(..., description="Warehouse identifier")
    target_cover_days: int = Field(..., ge=7, le=45, description="Target coverage days")
    stock: StockPosition = Field(..., description="Latest stock snapshot")
    sales: SalesVelocity = Field(..., description="Sales evidence")
    risk: StockRisk = Field(..., description="Risk assessment")
    budget: BudgetPosition = Field(..., description="Budget position")
    recommendation: VendorRecommendation = Field(..., description="Chosen vendor recommendation")


class HumanReviewInput(BaseModel):
    """Input to record a human review action."""
    case_id: str = Field(..., description="Case identifier")
    proposal: ReplenishmentProposal = Field(..., description="Proposal under review")
    approver: str = Field(..., description="Named human reviewer")
    decision: str = Field(..., description="APPROVED, REJECTED, or REVISE")
    comments: Optional[str] = Field(None, description="Human feedback")


class HumanReviewResult(BaseModel):
    """Normalized human review outcome."""
    case_id: str = Field(..., description="Case identifier")
    proposal_id: str = Field(..., description="Proposal identifier")
    decision: str = Field(..., description="APPROVED, REJECTED, or REVISE")
    approver: str = Field(..., description="Named human reviewer")
    comments: Optional[str] = Field(None, description="Human feedback")
    next_status: ProposalStatus = Field(..., description="What the workflow should do next")
    review_summary: str = Field(..., description="Short summary for operators or audit")
    reviewed_at: datetime = Field(..., description="When the review was recorded")


class ApprovalRequestInput(BaseModel):
    """Input to prepare an approval request."""
    proposal: ReplenishmentProposal = Field(..., description="Proposal to package for human approval")


class ApprovalRequest(BaseModel):
    """Human approval request (pause point)."""
    case_id: str = Field(..., description="Case/thread identifier")
    proposal: ReplenishmentProposal = Field(..., description="The proposal to approve")
    approval_required: bool = Field(default=True, description="This is an approval pause")


class ApprovalDecision(BaseModel):
    """Human's approval decision (resume input)."""
    case_id: str = Field(..., description="Case identifier being approved")
    proposal_id: str = Field(..., description="Proposal being approved")
    proposal_hash: str = Field(..., description="Hash of proposal (integrity check)")
    decision: str = Field(
        ...,
        description=(
            "'APPROVED', 'REJECTED', 'REVISE' (send it back for the strategist to "
            "re-reason with comments), or 'EDIT' (human picks a different eligible "
            "supplier directly; requires edited_offer_id)"
        ),
    )
    edited_offer_id: Optional[str] = Field(
        None,
        description="For decision='EDIT': offer_id of the eligible option the human chose instead",
    )
    chosen_target_basis: Optional[str] = Field(None, description="Computed target basis selected during a human EDIT")
    approver: str = Field(..., description="Name/ID of human approver")
    # Comments may be shown to an LLM only for a one-round revision.  Keep the
    # audited human input small enough that it cannot be used to exhaust that
    # model context.  This is enforced here as well as in the UI, because CLI
    # and email-link callers use this same resume model.
    comments: Optional[str] = Field(None, max_length=500, description="Approver comments (maximum 500 characters)")
    approved_at: datetime = Field(..., description="When approval was given (UTC)")

    @model_validator(mode="after")
    def rejected_decisions_require_comments(self):
        if self.decision == "REJECTED" and not (self.comments or "").strip():
            raise ValueError("A rejection requires a reason in comments.")
        return self


class VendorSendDecision(BaseModel):
    """Human decision at Gate 2, after the purchase request exists."""
    request_id: str
    case_id: str
    decision: str = Field(..., description="'APPROVED' sends the PO; 'REJECTED' cancels it")
    approver: str
    reason: Optional[str] = Field(None, max_length=500, description="Recorded rejection reason (maximum 500 characters)")
    approved_at: datetime

    @model_validator(mode="after")
    def validate_vendor_decision(self):
        if self.decision not in {"APPROVED", "REJECTED"}:
            raise ValueError("Vendor-send decision must be APPROVED or REJECTED.")
        if not self.approver.strip():
            raise ValueError("A vendor-send decision requires an approver.")
        if self.decision == "REJECTED" and not (self.reason or "").strip():
            raise ValueError("A vendor-send rejection requires a reason.")
        return self


PurchaseRequestInput.model_rebuild()
ProposalDraftInput.model_rebuild()
HumanReviewInput.model_rebuild()
ApprovalRequestInput.model_rebuild()
