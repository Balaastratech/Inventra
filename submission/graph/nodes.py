"""
Deterministic graph nodes plus the three agent-call sites. All business
arithmetic here comes from the provided tools/ package unmodified, except
one documented correction (see _size_quantity below, PLAN.md defect #11).

Agent functions are swappable via set_agents() so Phase 4 can drop in real
LLM calls without touching this file or workflow.py.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta

from domain.tool_models import (
    ApprovalDecision,
    ErrorCode,
    ProposalStatus,
    ReplenishmentProposal,
    VendorSendDecision,
)
from tools.execution import cancel_purchase_request, create_purchase_request, get_open_order_quantity
from tools.classification import get_latest_sku_policy
from tools.inventory import calculate_stock_risk, get_product, get_stock_position
from tools.memory import record_signal
from tools.policy import get_budget_position, get_policy_guidance
from tools.policy_floors import get_active_policy_floor
from tools.sales import get_sales_velocity
from tools.vendors import build_vendor_options, get_vendor_performance, list_vendor_offers

from submission.agents import stubs as _stub_agents
from submission.agents.models import (
    ChecklistVerdict,
    DemandAssessment,
    POLICY_QUESTION_TEXT,
    PolicyChecklistItem,
    PolicyQuestion,
    PolicyReview,
    ReplenishmentRecommendation,
    SourcingStrategy,
)
from submission.config import config
from submission.graph.economics import (
    ACCEPTABLE_VERDICTS,
    evaluate_options,
    size_order_quantity,
)
from submission.graph.hashing import compute_proposal_hash
from submission.graph.revalidation import revalidate_proposal
from submission.graph.support import emit_audit, invoke_agent_with_retry, reconcile_target
from submission.notifications.email import (
    notify_awaiting_approval,
    notify_blocked,
    notify_needs_information,
    notify_outcome,
    notify_vendor_approval_needed,
)
from submission.notifications.vendor_email import send_purchase_order


def _cover_text(cover_days: float | None) -> str:
    return "cover is not meaningful at zero demand" if cover_days is None else f"{cover_days:.1f}d cover"
from submission.state.state import CaseState

# --- Pluggable agents: Phase 2 stubs by default, Phase 4 swaps via set_agents() ---
_AGENTS = {
    "assess_demand": _stub_agents.assess_demand_stub,
    "recommend_vendor": _stub_agents.recommend_vendor_stub,
    "review_policy": _stub_agents.review_policy_stub,
}


def set_agents(**kwargs) -> None:
    _AGENTS.update(kwargs)


def _fail(state: CaseState, code: ErrorCode, detail: str, status: ProposalStatus = ProposalStatus.BLOCKED) -> CaseState:
    state["error_code"] = code
    state["error_detail"] = detail
    state["status"] = status
    return state


# ============================================================================
# Intake
# ============================================================================

def validate_request(state: CaseState) -> CaseState:
    missing = []
    if not state.get("sku"):
        missing.append("sku")
    if not state.get("warehouse_id"):
        missing.append("warehouse_id")
    cover = state.get("target_cover_days")
    if cover is not None and not (config.target_cover_min_days <= cover <= config.target_cover_max_days):
        missing.append(
            f"target_cover_days (must be {config.target_cover_min_days}-{config.target_cover_max_days}, got {cover})"
        )

    if missing:
        detail = f"Missing or invalid field(s): {', '.join(missing)}"
        _fail(state, ErrorCode.INVALID_INPUT, detail, ProposalStatus.NEEDS_INFORMATION)
        emit_audit(state, "system", "needs_information", {"missing": missing})
    else:
        emit_audit(state, "system", "request_validated", {"sku": state["sku"], "warehouse_id": state["warehouse_id"]})
    return state


def check_product(state: CaseState) -> CaseState:
    product = get_product(state["sku"])
    state["product"] = product
    if product.error is not None:
        _fail(state, product.error, f"Product lookup failed: {product.error.value}")
        emit_audit(state, "system", "product_check_failed", {"error": product.error.value})
    else:
        emit_audit(state, "system", "product_verified", {"evidence_id": product.evidence_id})
    return state


def fetch_evidence(state: CaseState) -> CaseState:
    """Stock + sales reads, plus our own freshness gate (2 days / 48h,
    matching policy.md review question 1 -- see config.data_freshness_hours)."""
    stock = get_stock_position(state["sku"], state["warehouse_id"])
    state["stock"] = stock
    if stock.error is not None:
        _fail(state, stock.error, f"Stock lookup failed: {stock.error.value}")
        emit_audit(state, "system", "stock_check_failed", {"error": stock.error.value})
        return state

    # naive UTC on purpose: stock.captured_at is naive (from the provided
    # tool's datetime.utcnow()); mixing in an aware datetime here would raise.
    freshness_hours = (datetime.utcnow() - stock.captured_at).total_seconds() / 3600
    if freshness_hours > config.data_freshness_hours:
        _fail(
            state,
            ErrorCode.DATA_STALE,
            f"Inventory snapshot is {freshness_hours:.1f}h old, exceeds {config.data_freshness_hours}h "
            "threshold. Refresh the inventory snapshot for this SKU/warehouse and retry.",
        )
        emit_audit(state, "system", "data_stale", {"freshness_hours": round(freshness_hours, 2)})
        return state

    sales = get_sales_velocity(state["sku"], state["warehouse_id"])
    state["sales"] = sales
    if sales.error is not None:
        yesterday = datetime.utcnow().date() - timedelta(days=1)
        start_7 = yesterday - timedelta(days=6)
        start_30 = yesterday - timedelta(days=29)
        deficit_7 = max(0, 3 - sales.observation_count_7)
        deficit_30 = max(0, 3 - sales.observation_count_30)
        detail = (
            f"Sales history is too thin to plan against for {state['sku']}/{state['warehouse_id']}: "
            f"from {start_7} to {yesterday} (last 7 days), {sales.observation_count_7} of last 7 days "
            f"were recorded (need at least 3, {deficit_7} short); from {start_30} to {yesterday} "
            f"(last 30 days), {sales.observation_count_30} of last 30 days were recorded "
            f"(need at least 3, {deficit_30} short). Backfill sales_daily across the missing dates, then re-run this case."
        )
        _fail(
            state,
            sales.error,
            detail,
            ProposalStatus.NEEDS_INFORMATION if sales.error == ErrorCode.INSUFFICIENT_DATA else ProposalStatus.BLOCKED,
        )
        if sales.error == ErrorCode.INSUFFICIENT_DATA:
            from tools.parking import park_item

            park_item(state["sku"], state["warehouse_id"], "INSUFFICIENT_SALES_HISTORY", detail)
        emit_audit(
            state,
            "system",
            "sales_check_failed",
            {
                "error": sales.error.value,
                "observation_count_7": sales.observation_count_7,
                "observation_count_30": sales.observation_count_30,
            },
        )
        return state

    emit_audit(
        state,
        "system",
        "evidence_gathered",
        {"stock_evidence_id": stock.evidence_id, "sales_evidence_id": sales.evidence_id},
    )
    return state


def resolve_target_cover(state: CaseState) -> CaseState:
    """Resolve target cover only after sales evidence is usable.

    ESTABLISHED records are entirely policy-derived.  PROVISIONAL and
    INSUFFICIENT records may ask a person for one constrained value: days of
    stock to hold.  This node deliberately ignores any value supplied when a
    case was initially constructed, so no public entrypoint can smuggle a
    human demand rate, target units, or order quantity into the arithmetic.
    """
    policy = state.get("sku_policy_snapshot") or get_latest_sku_policy(
        state["sku"], state["warehouse_id"]
    )
    if policy is None:
        _fail(
            state, ErrorCode.INSUFFICIENT_DATA,
            f"No SKU policy is available for {state['sku']}/{state['warehouse_id']}. "
            "Refresh sku_policy from sales_daily, then re-run this case.",
            ProposalStatus.NEEDS_INFORMATION,
        )
        return state
    state["sku_policy_snapshot"] = policy
    maturity = policy.maturity.upper()
    if maturity == "ESTABLISHED":
        derived = policy.derived_cover_days
        if derived is None:
            _fail(state, ErrorCode.INSUFFICIENT_DATA, "Established SKU policy has no derived_cover_days.")
            return state
        cover = round(derived)
        if not config.target_cover_min_days <= cover <= config.target_cover_max_days:
            _fail(state, ErrorCode.INVALID_INPUT, f"Derived cover target {cover} is outside policy bounds.")
            return state
        state["target_cover_days"] = cover
        state["target_provenance"] = "derived:sku_policy"
        state["target_mode"] = "DERIVED"
        emit_audit(state, "system", "target_cover_derived", {"maturity": maturity, "days": cover})
        return state
    if maturity in {"PROVISIONAL", "INSUFFICIENT"}:
        state["target_cover_days"] = None
        state["target_provenance"] = "pending_manual_cover_days"
        state["target_mode"] = "MANUAL_COVER_REQUIRED"
        state["status"] = ProposalStatus.NEEDS_INFORMATION
        state["error_code"] = None
        state["error_detail"] = (
            f"{state['sku']}/{state['warehouse_id']} has {maturity.lower()} demand maturity. "
            "Recent sales velocity is available; enter only the days of stock to hold. "
            "Demand rate, target units, and order quantity remain system-computed."
        )
        emit_audit(state, "system", "manual_cover_days_requested", {"maturity": maturity})
        return state
    _fail(state, ErrorCode.INSUFFICIENT_DATA, f"Unknown SKU policy maturity {policy.maturity!r}.")
    return state


def _override_ambiguity_if_windows_disagree_on_risk(
    state: CaseState, assessment: DemandAssessment
) -> DemandAssessment:
    """The agent's own ambiguity test is framed on relative disagreement
    between the two velocity numbers ("do they differ so much that picking
    one is a guess?"), not on whether the choice is consequential. Two
    windows can differ 40% and both land safely healthy, or differ 13% and
    decide whether an order gets placed -- see design.md Sec4.1's "Known
    gap", found by observing AC-001 flip between healthy and at-risk across
    identical seed data depending only on which window the model picked.

    Forces ambiguous=true whenever compute_risk would actually disagree on
    at_risk between the two windows, regardless of what the agent
    concluded -- same override discipline as the policy checklist: a fact
    the graph can compute deterministically is never left to the agent's
    own judgment call. Only ever sets ambiguous; never clears an agent's
    own ambiguous=true, and never fires when the agent already asked."""
    if assessment.ambiguous:
        return assessment
    stock, sales = state["stock"], state["sales"]
    open_order_units = get_open_order_quantity(state["sku"], state["warehouse_id"])
    available_units = stock.on_hand - stock.reserved + stock.confirmed_inbound + open_order_units
    risk_7 = calculate_stock_risk(
        available_units=available_units,
        daily_velocity=sales.window_7_days,
        target_cover_days=state["target_cover_days"],
        snapshot_captured_at=stock.captured_at,
        stale_threshold_hours=config.data_freshness_hours,
    )
    risk_30 = calculate_stock_risk(
        available_units=available_units,
        daily_velocity=sales.window_30_days,
        target_cover_days=state["target_cover_days"],
        snapshot_captured_at=stock.captured_at,
        stale_threshold_hours=config.data_freshness_hours,
    )
    if risk_7.at_risk == risk_30.at_risk:
        return assessment
    return assessment.model_copy(
        update={
            "ambiguous": True,
            "clarification_needed": (
                f"The 7-day sales trend ({sales.window_7_days}/day, {_cover_text(risk_7.cover_days)}) "
                f"and the 30-day trend ({sales.window_30_days}/day, {_cover_text(risk_30.cover_days)}) "
                f"disagree on whether this SKU is at risk against a {state['target_cover_days']}-day "
                "target -- which trend should this order plan against?"
            ),
        }
    )


def assess_demand(state: CaseState) -> CaseState:
    result, error = invoke_agent_with_retry(state, "assess_demand", _AGENTS["assess_demand"], DemandAssessment)
    if result is None:
        _fail(state, ErrorCode.UNKNOWN_ERROR, f"Demand assessment failed after retry: {error}")
        return state
    result = _override_ambiguity_if_windows_disagree_on_risk(state, result)
    state["demand_assessment"] = result
    if result.ambiguous:
        # Surface the agent's own precise question instead of silently
        # dropping it. Brief scenario 2 requires "NEEDS_INFORMATION with one
        # precise question" -- DemandAssessment.clarification_needed exists
        # specifically to carry it, but nothing downstream previously read
        # it, so this case closed with a blank reason.
        _fail(
            state,
            ErrorCode.INVALID_INPUT,
            result.clarification_needed or "The demand signal is ambiguous and needs clarification.",
            ProposalStatus.NEEDS_INFORMATION,
        )
        sales = state.get("sales")
        note = (
            f"{result.clarification_needed or 'Demand signal ambiguous.'} "
            f"7-day trend: {getattr(sales, 'window_7_days', '?')}/day "
            f"({getattr(sales, 'observation_count_7', '?')} observations); "
            f"30-day trend: {getattr(sales, 'window_30_days', '?')}/day "
            f"({getattr(sales, 'observation_count_30', '?')} observations)."
        )
        if state.get("sku") and state.get("warehouse_id"):
            from tools.parking import park_item

            park_item(state["sku"], state["warehouse_id"], "AMBIGUOUS_DEMAND_SIGNAL", note)
        emit_audit(state, "system", "demand_ambiguous", {"question": result.clarification_needed})
    return state


def compute_risk(state: CaseState) -> CaseState:
    assessment = state["demand_assessment"]
    stock, sales = state["stock"], state["sales"]
    # confirmed_inbound never gets written by this system (no supplier
    # confirmation path), so an approved-but-unconfirmed order is otherwise
    # invisible here and a re-run proposes a duplicate. Reorder guard: count
    # it the same as confirmed_inbound until a real confirmation path exists.
    open_order_units = get_open_order_quantity(state["sku"], state["warehouse_id"])
    available_units = stock.on_hand - stock.reserved + stock.confirmed_inbound + open_order_units
    velocity = sales.window_7_days if assessment.chosen_window_days == 7 else sales.window_30_days

    risk = calculate_stock_risk(
        available_units=available_units,
        daily_velocity=velocity,
        target_cover_days=state["target_cover_days"],
        snapshot_captured_at=stock.captured_at,
        stale_threshold_hours=config.data_freshness_hours,
    )
    state["risk"] = risk
    emit_audit(
        state,
        "system",
        "risk_assessed",
        {
            "at_risk": risk.at_risk,
            "cover_days": round(risk.cover_days, 2) if risk.cover_days is not None else None,
            "available_units": available_units,
            "open_order_units": open_order_units,
        },
    )
    return state


# ============================================================================
# Sourcing
# ============================================================================

def fetch_vendor_evidence(state: CaseState) -> CaseState:
    offers = list_vendor_offers(state["sku"])
    state["vendor_offers"] = offers
    vendor_ids = list({o.vendor_id for o in offers.offers})
    performance = get_vendor_performance(vendor_ids) if vendor_ids else get_vendor_performance([])
    state["vendor_performance"] = performance
    emit_audit(
        state,
        "system",
        "vendor_evidence_gathered",
        {"offer_count": len(offers.offers), "vendor_count": len(vendor_ids)},
    )
    return state


def build_options(state: CaseState) -> CaseState:
    risk = state["risk"]
    raw = build_vendor_options(risk, state["vendor_offers"], state["vendor_performance"])
    # VendorOption (the tool's output) doesn't carry moq -- only the source
    # VendorOffer does -- so the fix has to look it up by offer_id.
    moq_by_offer = {o.offer_id: o.moq for o in state["vendor_offers"].offers}
    # Same for fill_rate, which lives on vendor performance. It was being
    # fetched and never used; a 0.90 fill rate means a 29-unit order lands
    # about 26 units short of what was asked for.
    fill_by_vendor = {v.vendor_id: v.fill_rate for v in state["vendor_performance"].vendors}

    def _corrected(option):
        moq = moq_by_offer.get(option.offer_id, option.quantity)
        # Quantity is now per-supplier, because it depends on that supplier's
        # lead time -- a slower delivery means more stock drains before it
        # lands. See economics.size_order_quantity for why the previous
        # formula systematically under-ordered by lead_time x velocity.
        quantity = size_order_quantity(
            available_units=risk.available_units,
            daily_velocity=risk.daily_velocity,
            target_cover_days=state["target_cover_days"],
            moq=moq,
            lead_time_days=option.lead_time_days,
            fill_rate=fill_by_vendor.get(option.vendor_id),
        )
        return option.model_copy(update={"quantity": quantity, "total_cost": round(quantity * option.unit_price, 2)})

    corrected_options = [_corrected(o) for o in raw.options]
    corrected_eligible = [o for o in corrected_options if o.eligible]
    fixed = raw.model_copy(
        update={
            "options": corrected_options,
            "eligible_options": corrected_eligible,
            # VendorOptionList.cheapest_option is the provided model's field
            # and keeps its documented meaning: lowest total cost. It is not
            # the recommendation basis -- economics.best_value_offer_id is,
            # because quantities differ per supplier by design and the smallest
            # invoice is not the cheapest purchase. See graph/economics.py.
            "cheapest_option": min(corrected_options, key=lambda o: o.total_cost, default=None),
            "fastest_option": min(corrected_options, key=lambda o: o.lead_time_days, default=None),
        }
    )
    state["vendor_options"] = fixed

    if not corrected_eligible:
        # Per-vendor breakdown so notify_blocked / the UI can say WHICH
        # option failed on reliability vs. deadline instead of one flat
        # sentence (Gap 2 / BLOCKED-vagueness fix).
        perf_by_vendor = {v.vendor_id: v for v in state["vendor_performance"].vendors}
        considered = []
        for o in corrected_options:
            perf = perf_by_vendor.get(o.vendor_id)
            reasons = []
            if not o.meets_deadline:
                reasons.append("arrives after the projected stockout date")
            if not o.reliable:
                reasons.append(
                    f"reliability {perf.reliability:.0%} is below the "
                    f"{config.vendor_reliability_min:.0%} minimum"
                    if perf is not None
                    else "reliability data unavailable"
                )
            considered.append(
                {
                    "vendor_name": o.vendor_name,
                    "offer_id": o.offer_id,
                    "meets_deadline": o.meets_deadline,
                    "reliable": o.reliable,
                    "reasons": reasons,
                }
            )
        state["vendor_rejection_detail"] = {
            "considered": considered,
            "expired_count": state["vendor_offers"].expired_count,
            "inactive_count": state["vendor_offers"].inactive_count,
        }
        _fail(state, ErrorCode.INVALID_INPUT, "No eligible vendor options (reliability or deadline).")
        emit_audit(
            state,
            "system",
            "no_eligible_vendors",
            {
                "total_options": len(corrected_options),
                "expired_count": state["vendor_offers"].expired_count,
                "inactive_count": state["vendor_offers"].inactive_count,
            },
        )
        return state

    # Score the options once, here, and keep the result in state. The prompt,
    # the validation gate and the approval screen all read this same object,
    # so there is exactly one set of numbers in play.
    economics = evaluate_options(risk, corrected_eligible, state["vendor_performance"])
    state["economics"] = economics
    emit_audit(
        state,
        "system",
        "vendor_options_built",
        {
            "eligible_count": len(corrected_eligible),
            # Both are recorded on purpose: they can legitimately differ, and
            # when they do, the audit trail should show that the pick was made
            # on cost per day of cover rather than on the smaller invoice.
            "best_value_offer_id": economics.best_value_offer_id,
            "cheapest_total_cash_offer_id": economics.cheapest_offer_id,
            "ranking_basis": economics.ranking_basis,
            "verdicts": {o.offer_id: o.verdict for o in economics.options},
        },
    )
    return state


def _validate_recommendation(state: CaseState, rec: ReplenishmentRecommendation) -> str | None:
    """Semantic checks beyond the schema. Returning a string triggers one
    repair attempt (support.invoke_agent_with_retry), same as a validation
    error; a second failure fails the case closed."""
    eligible_ids = {o.offer_id for o in state["vendor_options"].eligible_options}
    if rec.recommended_offer_id not in eligible_ids:
        return f"recommended_offer_id {rec.recommended_offer_id!r} is not one of the eligible options {eligible_ids}"

    # Enforce the value rule rather than merely asking for it in the prompt.
    # Every eligible option already arrives before the projected stockout, and
    # graph/economics.py has already priced each option's own delivery risk and
    # carrying cost into one comparable figure -- all-in cost per day of cover.
    # The agent may not overrule that arithmetic. Without this gate a live run
    # recommended paying $1,450 extra to protect roughly $23 of expected
    # contribution and called it "a justified investment".
    #
    # Note the ranking is deliberately NOT total_cost: order quantities differ
    # per supplier because the target is N days of cover from arrival, so a
    # slower supplier funds more days of demand and needs more units. Ranking
    # on total spend compared different-sized baskets and forced the pick to
    # the smaller invoice even when it was worse per unit delivered.
    economics = state.get("economics") or evaluate_options(
        state["risk"], state["vendor_options"].eligible_options, state["vendor_performance"]
    )
    chosen = economics.by_offer(rec.recommended_offer_id)
    if chosen is not None and chosen.verdict not in ACCEPTABLE_VERDICTS:
        best = economics.by_offer(economics.best_value_offer_id)
        return (
            f"{rec.recommended_offer_id} is not an acceptable choice: {chosen.verdict_explanation} "
            f"Choose {economics.best_value_offer_id} "
            f"({best.vendor_name if best else 'the best-value option'}) unless you can point "
            f"to a computed figure in the economics block that says otherwise."
        )
    return None


def recommend_vendor(state: CaseState) -> CaseState:
    result, error = invoke_agent_with_retry(
        state,
        "recommend_vendor",
        _AGENTS["recommend_vendor"],
        ReplenishmentRecommendation,
        validate=lambda rec: _validate_recommendation(state, rec),
    )
    if result is None:
        _fail(state, ErrorCode.UNKNOWN_ERROR, f"Vendor recommendation failed after retry: {error}")
        return state
    state["replenishment_recommendation"] = result
    return state


# ============================================================================
# Policy / proposal
# ============================================================================

def fetch_budget_and_policy(state: CaseState) -> CaseState:
    budget = get_budget_position(state["warehouse_id"], state["budget_month"])
    state["budget"] = budget
    guidance = get_policy_guidance(state["sku"], state["warehouse_id"], state["target_cover_days"])
    state["policy_guidance"] = guidance
    policy = state.get("sku_policy_snapshot")
    statistical = (policy.statistical_target_units or policy.active_target_units or policy.reorder_point_units) if policy else 0.0
    floor = get_active_policy_floor(state["sku"], state["warehouse_id"])
    state["policy_floor"] = floor
    state["target_reconciliation"] = reconcile_target(statistical, floor, policy.mean_daily_demand if policy else 0.0)
    if budget.error is not None:
        _fail(state, budget.error, f"Budget lookup failed: {budget.error.value}")
        emit_audit(state, "system", "budget_check_failed", {"error": budget.error.value})
        return state
    emit_audit(state, "system", "budget_and_policy_loaded", {"budget_evidence_id": budget.evidence_id})
    return state


def draft_proposal(state: CaseState) -> CaseState:
    rec = state["replenishment_recommendation"]
    option = next(o for o in state["vendor_options"].eligible_options if o.offer_id == rec.recommended_offer_id)
    stock, sales, risk, budget = state["stock"], state["sales"], state["risk"], state["budget"]

    hash_fields = {
        "sku": state["sku"],
        "warehouse_id": state["warehouse_id"],
        "quantity": option.quantity,
        "unit_price": option.unit_price,
        "recommended_vendor_id": option.vendor_id,
        "target_cover_days": state["target_cover_days"],
    }

    reconciliation = state.get("target_reconciliation")
    policy = state.get("sku_policy_snapshot")
    floor = state.get("policy_floor")
    floor_units = max(float(getattr(floor, "min_units", None) or 0), float(getattr(floor, "min_cover_days", None) or 0) * (policy.mean_daily_demand if policy else risk.daily_velocity)) if floor else None
    proposal = ReplenishmentProposal(
        proposal_id=f"PROP-{uuid.uuid4().hex[:12].upper()}",
        proposal_hash=compute_proposal_hash(hash_fields),
        case_id=state["case_id"],
        sku=state["sku"],
        warehouse_id=state["warehouse_id"],
        stock_evidence_id=stock.evidence_id,
        sales_evidence_id=sales.evidence_id,
        vendor_evidence_ids=rec.evidence_ids,
        budget_evidence_id=budget.evidence_id,
        available_units=risk.available_units,
        daily_velocity=risk.daily_velocity,
        target_cover_days=state["target_cover_days"],
        projected_stockout_date=risk.projected_stockout_date,
        recommended_vendor_id=option.vendor_id,
        recommended_vendor_name=option.vendor_name,
        quantity=option.quantity,
        unit_price=option.unit_price,
        total_cost=option.total_cost,
        expected_arrival=option.expected_arrival,
        cost_vs_speed_trade_off=rec.rationale,
        other_options_summary=rec.other_options_summary,
        budget_remaining=budget.remaining - option.total_cost,
        policy_passed=False,  # set for real once review_policy runs
        policy_violations=[],
        policy_floor_units=floor_units,
        statistical_target_units=(policy.statistical_target_units or policy.active_target_units or policy.reorder_point_units if policy else None),
        active_target_units=(reconciliation.active_target_units if reconciliation else None),
        target_basis=(reconciliation.basis if reconciliation else "STATISTICAL"),
        target_provenance=state.get("target_provenance", "derived"),
        created_at=datetime.utcnow(),
    )
    state["proposal"] = proposal
    emit_audit(
        state,
        "system",
        "proposal_drafted",
        {"proposal_id": proposal.proposal_id, "proposal_hash": proposal.proposal_hash, "total_cost": proposal.total_cost},
    )
    return state


def _validate_policy_review(state: CaseState, review: PolicyReview) -> str | None:
    if review.proposal_id != state["proposal"].proposal_id:
        return f"proposal_id {review.proposal_id!r} does not match the proposal under review {state['proposal'].proposal_id!r}"
    return None


def _budget_overage(proposal: ReplenishmentProposal, budget) -> tuple[bool, float, bool]:
    over_budget = proposal.total_cost > budget.remaining
    overage = proposal.total_cost - budget.remaining
    # Measured against the total monthly budget, not "remaining" -- remaining
    # can be zero or already negative (a warehouse that's already overspent),
    # and dividing by that would either crash or silently flip the sign,
    # making any overage look "within tolerance". budget_amount is stable.
    within_tolerance = (
        over_budget
        and budget.budget_amount > 0
        and overage / budget.budget_amount <= config.over_budget_exception_tolerance
    )
    return over_budget, overage, within_tolerance


def _known_evidence_ids(proposal: ReplenishmentProposal, state: CaseState) -> set[str]:
    """Every evidence_id (and, for offers, offer_id) the Policy Reviewer was
    actually shown -- prompts/policy.py::build_user_message forwards the
    full vendor_offers/vendor_options/vendor_performance bundle, not just
    the subset the Strategist happened to cite on the final proposal. A
    first version of this check only looked at proposal.vendor_evidence_ids
    and produced false BLOCKED verdicts on real Vertex output the very
    first time it ran against a live case: the reviewer correctly cited a
    vendor_offers[].evidence_id or a vendor_options[].offer_id that this
    function didn't yet know about. Falls back to just the proposal-derived
    ids when state doesn't carry the fuller bundle (unit tests that hand-
    build a minimal state), which is also correct there.

    Second live-run gap, found 2026-09-13: prompts/policy.py's evidence
    bundle also includes `product` (state["product"]), and the reviewer
    correctly cites product.evidence_id (e.g. "product:SKU-009") when it
    references what's at risk -- but this function never added it to the
    known set, so a fully honest, well-grounded citation was rejected as
    untraceable. This was the actual cause of the majority of live BLOCKED
    verdicts on genuinely valid proposals (not a Strategist/prompt defect,
    which was the first hypothesis) -- confirmed by comparing a real
    PolicyReview.evidence_ids output against this function's return value
    on a live blocked case.
    """
    ids = {proposal.stock_evidence_id, proposal.sales_evidence_id, proposal.budget_evidence_id}
    ids.update(proposal.vendor_evidence_ids)
    product = state.get("product")
    if product is not None:
        ids.add(product.evidence_id)
    offers = state.get("vendor_offers")
    if offers is not None:
        for offer in offers.offers:
            ids.add(offer.evidence_id)
            ids.add(offer.offer_id)
    options = state.get("vendor_options")
    if options is not None:
        ids.update(option.offer_id for option in options.options)
    performance = state.get("vendor_performance")
    if performance is not None:
        ids.update(vendor.evidence_id for vendor in performance.vendors)
    return ids


def _override_policy_checklist(
    checklist: list[PolicyChecklistItem],
    proposal: ReplenishmentProposal,
    budget,
    risk,
    evidence_ids: list[str],
    state: CaseState,
) -> tuple[list[PolicyChecklistItem], list[str]]:
    """Force every mechanically-checkable row to the value the graph's own
    deterministic state already proves, regardless of what the agent
    answered -- same override discipline this node already applies to
    budget (brief: "LLM budget judgment is not authoritative"), extended to
    every policy.md question that has a real fact behind it instead of just
    budget/freshness/deadline. tradeoff_explained is the only row left
    untouched: "which tradeoff is being made" is a narrative judgment, not
    a fact this graph can independently verify.

    Returns (overridden_checklist, extra_concerns) -- extra_concerns holds
    one human-readable line per row this function flips to FAIL, so the
    reason surfaces in the top-level concerns list too, not just the table.
    """
    over_budget, overage, within_tolerance = _budget_overage(proposal, budget)
    meets_deadline = risk.projected_stockout_date is None or proposal.expected_arrival <= risk.projected_stockout_date
    known_ids = _known_evidence_ids(proposal, state)
    traceable = bool(evidence_ids) and all(eid in known_ids for eid in evidence_ids)

    forced: dict[PolicyQuestion, tuple[ChecklistVerdict, str]] = {
        PolicyQuestion.FRESHNESS: (
            ChecklistVerdict.FAIL if risk.stale else ChecklistVerdict.PASS,
            f"Inventory snapshot is stale ({risk.freshness_hours:.1f}h old): policy.md review "
            "question 1 requires blocking regardless of the reviewer's verdict."
            if risk.stale
            else f"Snapshot is {risk.freshness_hours:.1f}h old, within the freshness threshold.",
        ),
        # Structurally guaranteed by the time this node runs: compute_risk
        # already required at_risk=True, and the graph already blocks on
        # insufficient sales history or zero eligible vendors before
        # draft_proposal is ever reached, so re-litigating either fact here
        # would be redundant, not an independent check.
        PolicyQuestion.AT_RISK: (
            ChecklistVerdict.PASS,
            "Case only reaches policy review when compute_risk found the SKU at risk.",
        ),
        PolicyQuestion.SALES_SUFFICIENCY: (
            ChecklistVerdict.PASS,
            "Case only reaches policy review with sufficient sales history to size an order.",
        ),
        PolicyQuestion.VENDOR_VALIDITY: (
            ChecklistVerdict.PASS,
            "The recommended option came from vendor_options.eligible_options, already filtered "
            "for offer validity and vendor reliability.",
        ),
        PolicyQuestion.ARRIVAL_BEATS_STOCKOUT: (
            ChecklistVerdict.PASS if meets_deadline else ChecklistVerdict.FAIL,
            f"Expected arrival {proposal.expected_arrival} is on or before the projected stockout "
            f"{risk.projected_stockout_date}."
            if meets_deadline
            else f"Expected arrival {proposal.expected_arrival} is after the projected stockout "
            f"{risk.projected_stockout_date}: policy.md review question 6 requires blocking "
            "regardless of the reviewer's verdict.",
        ),
        PolicyQuestion.BUDGET_FIT: (
            ChecklistVerdict.PASS if not over_budget else ChecklistVerdict.FAIL,
            (
                f"Total cost {proposal.total_cost} exceeds remaining budget {budget.remaining} by "
                f"{overage:.2f}, within the {config.over_budget_exception_tolerance:.0%} exception "
                "tolerance -- flagged, not auto-approved."
                if over_budget and within_tolerance
                else f"Over budget: cost {proposal.total_cost} exceeds remaining {budget.remaining}."
                if over_budget
                else f"Total cost {proposal.total_cost} fits within remaining budget {budget.remaining}."
            ),
        ),
        PolicyQuestion.EVIDENCE_TRACEABLE: (
            ChecklistVerdict.PASS if traceable else ChecklistVerdict.FAIL,
            f"{len(evidence_ids)} evidence id(s) cited, all matching this proposal's stock/sales/"
            "budget/vendor evidence."
            if traceable
            else f"{len(evidence_ids)} evidence id(s) cited, but none (or the list was empty) match "
            "this proposal's actual evidence: policy.md review question 8 requires blocking.",
        ),
        PolicyQuestion.POLICY_FLOOR: (
            ChecklistVerdict.PASS if proposal.policy_floor_units is None or (proposal.active_target_units or 0) >= proposal.policy_floor_units else ChecklistVerdict.FAIL,
            "The active target respects the active policy floor." if proposal.policy_floor_units is None or (proposal.active_target_units or 0) >= proposal.policy_floor_units else "The selected target is below the active policy floor; human exception required.",
        ),
    }

    new_items: list[PolicyChecklistItem] = []
    extra_concerns: list[str] = []
    for item in checklist:
        override = forced.get(item.question)
        if override is None:
            new_items.append(item)  # tradeoff_explained: left as the agent's own judgment
            continue
        verdict, rationale = override
        new_items.append(PolicyChecklistItem(question=item.question, verdict=verdict, rationale=rationale))
        if verdict == ChecklistVerdict.FAIL:
            extra_concerns.append(f"{POLICY_QUESTION_TEXT[item.question]} -- {rationale}")

    return new_items, extra_concerns


def review_policy(state: CaseState) -> CaseState:
    result, error = invoke_agent_with_retry(
        state,
        "review_policy",
        _AGENTS["review_policy"],
        PolicyReview,
        validate=lambda review: _validate_policy_review(state, review),
    )
    if result is None:
        _fail(state, ErrorCode.UNKNOWN_ERROR, f"Policy review failed after retry: {error}")
        return state

    proposal, budget, risk = state["proposal"], state["budget"], state["risk"]
    checklist, forced_concerns = _override_policy_checklist(
        result.checklist, proposal, budget, risk, result.evidence_ids, state
    )
    concerns = list(result.concerns) + forced_concerns

    over_budget, overage, within_tolerance = _budget_overage(proposal, budget)
    verdict = result.verdict.value
    # Budget arithmetic is never the agent's call to make (brief: "LLM
    # budget judgment is not authoritative") -- code overrides the verdict
    # here regardless of what the agent said. This escalation (BLOCKED vs.
    # EXCEPTION) is a judgment about *how bad* the overage is, distinct from
    # the checklist's plain PASS/FAIL "does it fit" row above.
    if over_budget and not within_tolerance:
        verdict = "BLOCKED"
    elif over_budget and within_tolerance and verdict == "PASS":
        verdict = "EXCEPTION"

    # Every row that can only ever mean "block, no exception" -- unlike
    # budget, which has a tolerated middle ground -- forces BLOCKED
    # regardless of what the agent's overall verdict said.
    row_verdict = {item.question: item.verdict for item in checklist}
    for question in (PolicyQuestion.FRESHNESS, PolicyQuestion.ARRIVAL_BEATS_STOCKOUT, PolicyQuestion.EVIDENCE_TRACEABLE):
        if row_verdict[question] == ChecklistVerdict.FAIL:
            verdict = "BLOCKED"
    # A human may deliberately select the statistical target below an active
    # floor, but it is never a quiet PASS: the proposal remains reviewable as
    # an explicit, audited exception (D18).
    if row_verdict.get(PolicyQuestion.POLICY_FLOOR) == ChecklistVerdict.FAIL and verdict != "BLOCKED":
        verdict = "EXCEPTION"

    state["policy_review"] = result.model_copy(
        update={"verdict": type(result.verdict)(verdict), "checklist": checklist, "concerns": concerns}
    )
    state["proposal"] = proposal.model_copy(
        update={"policy_passed": verdict != "BLOCKED", "policy_violations": concerns}
    )
    emit_audit(
        state,
        "system",
        "policy_reviewed",
        {
            "verdict": verdict,
            "concerns": concerns,
            "checklist": [{"question": item.question.value, "verdict": item.verdict.value} for item in checklist],
        },
    )
    if verdict == "BLOCKED":
        _fail(state, ErrorCode.INVALID_INPUT, f"Policy review blocked: {'; '.join(concerns) or 'see policy guidance'}")
    return state


# ============================================================================
# Approval, revalidation, execution
# ============================================================================

def request_approval(state: CaseState) -> CaseState:
    """Deterministic. The actual pause (interrupt()) happens in
    graph/workflow.py's node wrapper, not here, so this function stays unit
    -testable without a compiled graph."""
    state["status"] = ProposalStatus.AWAITING_APPROVAL
    emit_audit(
        state,
        "system",
        "approval_requested",
        {"proposal_id": state["proposal"].proposal_id, "proposal_hash": state["proposal"].proposal_hash},
    )
    notify_awaiting_approval(state)
    return state


def handle_decision(state: CaseState, decision: ApprovalDecision) -> CaseState:
    state["approval_decision"] = decision
    emit_audit(
        state,
        f"human:{decision.approver}",
        "decision_recorded",
        {"decision": decision.decision, "proposal_hash": decision.proposal_hash},
    )
    if decision.decision == "REVISE":
        state["revision_count"] = state.get("revision_count", 0) + 1
    # Gap 9: a rejection or revision request with a stated reason is durable
    # signal, not just an audit line -- record it against the vendor that
    # was rejected so a later case on the same product can be reminded of
    # it (see prompts/strategist.py's memory digest).
    proposal = state.get("proposal")
    # An EDIT counts too, and is arguably the strongest of the three: the
    # human did not just object, they named the supplier they wanted instead.
    # Recorded against the vendor being switched away from -- that is the one
    # a later case on this product should hesitate over.
    signal_types = {
        "REJECTED": "human_rejected",
        "REVISE": "human_requested_revision",
        "EDIT": "human_switched_vendor",
    }
    if decision.decision in signal_types and decision.comments and proposal is not None:
        record_signal(
            entity_type="vendor",
            entity_key=proposal.recommended_vendor_id,
            signal_type=signal_types[decision.decision],
            signal_text=decision.comments,
            source_case_id=state["case_id"],
        )
    return state


def apply_human_edit(state: CaseState) -> CaseState:
    """Swap the proposal to a different eligible supplier the human picked
    directly, instead of asking the strategist to re-reason (B8).

    Why EDIT exists alongside REVISE. REVISE hands a comment back to the
    model and hopes it interprets it the way the approver meant; a planner who
    already knows they want the other quoted supplier had no way to just say
    so. This is that path: deterministic, no model call for the switch itself.

    What a human may and may not change, and why the line is here:

      * Supplier -- yes. That is the judgment call the approver is
        best placed to make, and every candidate has already passed the
        deterministic eligibility gates (reliability, arrival before
        stockout, offer not expired) in build_options.
      * Quantity -- no, and deliberately not exposed. Order quantity is
        derived per supplier by economics.size_order_quantity from velocity,
        that supplier's lead time, fill rate and MOQ. Switching supplier
        therefore re-sizes the order automatically and correctly. Letting a
        human type a number over that would reintroduce exactly the
        hand-computed figure this system exists to eliminate, and would
        silently invalidate the economics block that the approval notes and
        the policy reviewer both read.

    The chosen option is not required to be the cheapest or economically
    optimal one -- a human is allowed to overrule the arithmetic. It is
    required to be *eligible*. The premium and buffer trade-off is then
    re-surfaced on the rebuilt approval screen by _approval_notes, so an
    override is visible rather than quiet.

    Everything downstream is rebuilt, not patched: this only rewrites the
    recommendation, then the case re-enters draft_proposal, which recomputes
    quantity, unit_price, total_cost, budget_remaining and the proposal hash
    from the chosen option -- and review_policy runs again, so an edit that
    breaks the budget or the arrival deadline is caught by the same
    code-enforced checks as the original. The approver must then re-approve;
    their earlier approval was bound to the old hash and revalidation's
    hash_matches check enforces that.
    """
    decision = state.get("approval_decision")
    offer_id = getattr(decision, "edited_offer_id", None)
    chosen_basis = getattr(decision, "chosen_target_basis", None)
    if chosen_basis:
        allowed = {"POLICY_FLOOR", "STATISTICAL", "STATISTICAL_MINIMUM"}
        if chosen_basis not in allowed:
            _fail(state, ErrorCode.INVALID_INPUT, f"{chosen_basis!r} is not a supported target basis.")
            return state
        proposal = state.get("proposal")
        targets = {
            "POLICY_FLOOR": proposal.policy_floor_units if proposal else None,
            "STATISTICAL": proposal.statistical_target_units if proposal else None,
            "STATISTICAL_MINIMUM": proposal.statistical_target_units if proposal else None,
        }
        target_units = targets[chosen_basis]
        demand = state["risk"].daily_velocity if state.get("risk") else 0
        if target_units is None or demand <= 0:
            _fail(state, ErrorCode.INVALID_INPUT, "The selected target basis has no computable demand target.")
            return state
        # Convert the selected computed unit target to the graph's existing
        # day-cover input and rebuild every supplier option deterministically.
        state["target_cover_days"] = max(config.target_cover_min_days, min(config.target_cover_max_days, round(float(target_units) / demand)))
        state["target_provenance"] = f"human:{decision.approver}" if decision else "human:unknown"
        build_options(state)
        reconciliation = state.get("target_reconciliation")
        if reconciliation is not None:
            from submission.graph.support import TargetReconciliation
            state["target_reconciliation"] = TargetReconciliation(float(target_units), chosen_basis, float(target_units) - float(proposal.statistical_target_units or 0), reconciliation.explanation)
    options = state.get("vendor_options")
    eligible = list(options.eligible_options) if options else []
    desired_offer = offer_id or getattr(state.get("replenishment_recommendation"), "recommended_offer_id", None)
    chosen = next((o for o in eligible if o.offer_id == desired_offer), None)

    counts = state.setdefault("retry_counts", {})
    counts["human_edit"] = counts.get("human_edit", 0) + 1

    if chosen is None:
        # Defence in depth: the UI only offers eligible options, but the
        # email/CLI paths accept a raw offer_id. An unknown or ineligible id
        # must never become a proposal -- fail closed rather than falling
        # back to a "closest match".
        _fail(
            state,
            ErrorCode.INVALID_INPUT,
            f"{desired_offer!r} is not one of this case's eligible supplier options "
            f"({', '.join(o.offer_id for o in eligible) or 'none'}).",
        )
        emit_audit(
            state,
            f"human:{decision.approver}" if decision else "human",
            "proposal_edit_rejected",
            {"requested_offer_id": offer_id, "attempt": counts["human_edit"]},
        )
        return state

    previous = state.get("proposal")
    previous_offer_id = getattr(state.get("replenishment_recommendation"), "recommended_offer_id", None)

    approver = decision.approver if decision else "unknown"
    state["replenishment_recommendation"] = ReplenishmentRecommendation(
        case_id=state["case_id"],
        recommended_offer_id=chosen.offer_id,
        strategy=SourcingStrategy.BALANCED,
        # Attributed to the human, not dressed up as agent reasoning: this
        # string is shown to the next approver as "why this supplier".
        rationale=(
            f"Supplier chosen directly by {approver}"
            + (f": {decision.comments}" if decision and decision.comments else ".")
        ),
        other_options_summary=(
            f"Replaced {previous_offer_id} after human review."
            if previous_offer_id and previous_offer_id != chosen.offer_id
            else None
        ),
        evidence_ids=[chosen.offer_id],
    )

    # Discard everything derived from the superseded pick. Keeping the stale
    # proposal or policy review would let a later node read a verdict that
    # was passed on a different supplier.
    state["proposal"] = None
    state["policy_review"] = None
    state["revalidation"] = None
    state["approval_decision"] = None
    state["error_code"] = None
    state["error_detail"] = None

    emit_audit(
        state,
        f"human:{approver}",
        "proposal_edited_by_human",
        {
            "from_offer_id": previous_offer_id,
            "to_offer_id": chosen.offer_id,
            "to_vendor": chosen.vendor_name,
            "previous_total_cost": getattr(previous, "total_cost", None),
            "new_quantity": chosen.quantity,
            "new_total_cost": chosen.total_cost,
            "attempt": counts["human_edit"],
        },
    )
    return state


def prepare_revision(state: CaseState) -> CaseState:
    """Entered when a human picks REVISE. Bounded to config.max_revision_cycles
    by routes.route_after_decision, which has already counted this one.

    Two things this has to get right:

    1. Clear the derived work being replaced (recommendation, proposal,
       policy review, any stale revalidation) but KEEP approval_decision --
       the approver's comment is the entire input to the revision, and
       prompts/strategist.py reads it from there. Clearing it would make
       the revision re-run the same agent on the same evidence and produce
       the same answer.
    2. Send the case back through evidence collection, not straight back to
       vendor selection. A human pause can exceed config.data_freshness_hours
       (48h/2 days, per policy.md), especially over a weekend or a backlog of
       approvals, so the pre-pause stock snapshot cannot be assumed fresh;
       re-recommending against it risks spending model calls on a proposal
       that dies at revalidation. Re-reading also means a genuinely stale
       snapshot blocks here, at intake, with DATA_STALE -- which is the
       honest outcome.
    """
    state["replenishment_recommendation"] = None
    state["proposal"] = None
    state["policy_review"] = None
    state["revalidation"] = None
    state["error_code"] = None
    state["error_detail"] = None
    decision = state.get("approval_decision")
    emit_audit(
        state,
        f"human:{decision.approver}" if decision else "system",
        "revision_requested",
        {
            "revision_count": state.get("revision_count", 0),
            # A named human's written instruction, not model reasoning --
            # this belongs in the audit trail so the revision can be
            # explained later. Truncated so a long paste can't bloat the row.
            "approver_comment": ((decision.comments if decision else None) or "")[:500],
        },
    )
    return state


def invalidate_approval(state: CaseState) -> CaseState:
    emit_audit(state, "system", "approval_invalidated", {"reason": state.get("error_detail")})
    state["approval_decision"] = None
    state["proposal"] = None
    # Clear the stale failure before looping back to compute_risk -- every
    # route_after_* function below treats error_code as "did THIS node just
    # fail", so a leftover revalidation error would wrongly short-circuit
    # every subsequent node on the retry pass, not just the one that
    # actually failed.
    state["error_code"] = None
    state["error_detail"] = None
    return state


def revalidate(state: CaseState) -> CaseState:
    result = revalidate_proposal(state["proposal"])
    state["revalidation"] = result
    emit_audit(state, "system", "revalidated", {"all_checks_pass": result.all_checks_pass, "detail": result.error_details})
    if not result.all_checks_pass:
        counts = state.setdefault("retry_counts", {})
        counts["revalidate"] = counts.get("revalidate", 0) + 1
        _fail(state, ErrorCode.INVALID_INPUT, f"Revalidation failed: {result.error_details}")
    return state


def execute_purchase(state: CaseState) -> CaseState:
    proposal = state["proposal"]
    # Keyed on proposal_hash alone, not proposal_hash:approver -- the same
    # proposal approved by two different people must still dedupe to one
    # purchase_requests row (create_purchase_request's own contract).
    # Approver-scoping made that collide only by coincidence; see
    # "Idempotency Key Is Approver-Scoped" in GAP_NEEDS_INFORMATION.md.
    idempotency_key = state.get("idempotency_key") or proposal.proposal_hash
    state["idempotency_key"] = idempotency_key

    result = create_purchase_request(
        proposal=proposal,
        idempotency_key=idempotency_key,
        approved_by=state["approval_decision"].approver,
    )
    state["purchase_result"] = result
    emit_audit(
        state,
        "system",
        "purchase_request_created" if result.error is None else "write_failed",
        {"request_id": result.request_id, "created": result.created, "error": result.error.value if result.error else None},
    )
    if result.error is not None:
        _fail(state, result.error, result.error_details or "Write failed")
    else:
        state["status"] = ProposalStatus.PURCHASE_REQUEST_CREATED
    return state


def request_vendor_approval(state: CaseState) -> CaseState:
    """Prepare Gate 2. The following workflow node owns the interrupt."""
    result = state.get("purchase_result")
    if result is None or result.error is not None:
        _fail(state, ErrorCode.WRITE_FAILED, "Cannot request vendor approval without a purchase request.")
        return state
    state["status"] = ProposalStatus.AWAITING_VENDOR_APPROVAL
    emit_audit(state, "system", "vendor_approval_requested", {"request_id": result.request_id})
    notify_vendor_approval_needed(state)
    return state


def handle_vendor_decision(state: CaseState, decision: VendorSendDecision) -> CaseState:
    result = state.get("purchase_result")
    if result is None or result.request_id != decision.request_id:
        _fail(state, ErrorCode.INVALID_INPUT, "Vendor-send decision does not match this purchase request.")
        return state
    state["vendor_send_decision"] = decision
    emit_audit(state, f"human:{decision.approver}", "vendor_send_decision_recorded", {
        "request_id": decision.request_id, "decision": decision.decision, "reason": decision.reason,
    })
    if decision.decision == "APPROVED":
        try:
            sent = send_purchase_order(state["proposal"], result)
            emit_audit(state, "system", "vendor_send_succeeded" if sent else "vendor_send_not_sent", {"request_id": result.request_id})
        except Exception as exc:
            emit_audit(state, "system", "vendor_send_failed", {"request_id": result.request_id, "error": str(exc)})
        state["status"] = ProposalStatus.PURCHASE_REQUEST_CREATED
        return state
    cancellation = cancel_purchase_request(result.request_id, decision.approver, decision.reason or "")
    if not cancellation.cancelled:
        _fail(state, cancellation.error or ErrorCode.WRITE_FAILED, cancellation.error_details or "Could not cancel purchase request.")
        return state
    proposal = state.get("proposal")
    if proposal is not None:
        record_signal("vendor", proposal.recommended_vendor_id, "human_rejected", decision.reason or "", state["case_id"])
    state["status"] = ProposalStatus.PURCHASE_REQUEST_CANCELLED
    return state


# ============================================================================
# Terminal nodes
# ============================================================================

def finalize_no_action(state: CaseState) -> CaseState:
    state["status"] = ProposalStatus.NO_ACTION
    emit_audit(state, "system", "case_closed", {"status": "NO_ACTION"})
    # Healthy monitor results belong in sweep history/audit, not email.  The
    # monitor is expected to find the same healthy SKU repeatedly.
    return state


def finalize_needs_information(state: CaseState) -> CaseState:
    state["status"] = ProposalStatus.NEEDS_INFORMATION
    emit_audit(state, "system", "case_closed", {"status": "NEEDS_INFORMATION", "detail": state.get("error_detail")})
    notify_needs_information(state)
    return state


def finalize_blocked(state: CaseState) -> CaseState:
    state["status"] = ProposalStatus.BLOCKED
    emit_audit(
        state,
        "system",
        "case_closed",
        {"status": "BLOCKED", "error_code": state.get("error_code").value if state.get("error_code") else None,
         "detail": state.get("error_detail")},
    )
    notify_blocked(state)
    return state


def finalize_success(state: CaseState) -> CaseState:
    emit_audit(state, "system", "case_closed", {"status": "PURCHASE_REQUEST_CREATED"})
    notify_outcome(state)
    return state


def finalize_vendor_cancelled(state: CaseState) -> CaseState:
    state["status"] = ProposalStatus.PURCHASE_REQUEST_CANCELLED
    emit_audit(state, "system", "case_closed", {"status": "PURCHASE_REQUEST_CANCELLED", "detail": state.get("vendor_send_decision").reason if state.get("vendor_send_decision") else None})
    notify_blocked(state)
    return state
