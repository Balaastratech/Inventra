"""
Real post-approval revalidation.

tools/execution.py::revalidate_approved_proposal is a stub in the provided
starter package -- it returns all_checks_pass=True unconditionally and never
touches the database (confirmed during Phase 0 investigation, PLAN.md §5
item 1). Scenario 7 (approval data changes during the pause) cannot pass
against it. This is our own implementation, called only from the
deterministic revalidate node in nodes.py -- never reachable by an agent.

Rechecks exactly what the brief requires (§1 Execution rule): inventory
freshness, offer validity, proposal hash, and budget -- immediately before
the write.
"""

from __future__ import annotations

from datetime import datetime

from domain.tool_models import ReplenishmentProposal, RevalidationResult
from tools.inventory import get_stock_position
from tools.policy import get_budget_position
from tools.vendors import list_vendor_offers

from submission.config import config
from submission.graph.hashing import compute_proposal_hash, hash_fields_from_proposal


def revalidate_proposal(proposal: ReplenishmentProposal) -> RevalidationResult:
    computed_hash = compute_proposal_hash(hash_fields_from_proposal(proposal))
    hash_matches = computed_hash == proposal.proposal_hash

    stock = get_stock_position(proposal.sku, proposal.warehouse_id)
    stock_valid = False
    if stock.error is None:
        # naive UTC to match stock.captured_at (see nodes.py fetch_evidence)
        freshness_hours = (datetime.utcnow() - stock.captured_at).total_seconds() / 3600
        stock_valid = freshness_hours <= config.data_freshness_hours

    offers = list_vendor_offers(proposal.sku)
    current_offer = next((o for o in offers.offers if o.vendor_id == proposal.recommended_vendor_id), None)
    offer_valid = current_offer is not None and current_offer.unit_price == proposal.unit_price

    # "Latest remaining monthly budget" (brief §1) -- always check the
    # current month, not whatever month the proposal happened to be drafted in.
    budget_month = datetime.utcnow().strftime("%Y-%m")
    budget = get_budget_position(proposal.warehouse_id, budget_month)
    budget_overage = proposal.total_cost - budget.remaining if budget.error is None else 0.0
    budget_within_tolerance = (
        budget.error is None
        and budget_overage > 0
        and budget.budget_amount > 0
        and budget_overage / budget.budget_amount <= config.over_budget_exception_tolerance
    )
    # Mirrors graph/nodes.py::_budget_overage's tolerance exactly. Without
    # this, a proposal policy review correctly let through as EXCEPTION
    # (over budget but within the 5% tolerance, human still decides) would
    # fail here on the identical numbers the moment a human approved it --
    # the EXCEPTION tier would never be approvable even with zero data
    # drift during the pause. Found live, 2026-09-13: an EXCEPTION-verdict
    # proposal ($10,350 cost, $9,000 remaining, $1,350/$50,000=2.7% over)
    # hard-failed revalidation with "short by $1,350.00" despite having
    # just been flagged-not-blocked for exactly that reason.
    budget_valid = budget.error is None and (budget_overage <= 0 or budget_within_tolerance)

    all_pass = hash_matches and stock_valid and offer_valid and budget_valid
    # Every message below states the exact numbers this function just read
    # from the database -- never a generic label -- so a human (or the UI)
    # can act on the real shortfall/mismatch instead of guessing at it, and
    # so re-checking after a fix is a fresh read of these same fields, not
    # someone's word that they made the change.
    problems = []
    if not hash_matches:
        problems.append(
            f"proposal_hash mismatch (approved {proposal.proposal_hash[:12]}..., "
            f"now computes {computed_hash[:12]}...) -- the proposal content changed after approval"
        )
    if not stock_valid:
        if stock.error is not None:
            problems.append(f"inventory snapshot unavailable ({stock.error.value})")
        else:
            problems.append(
                f"inventory snapshot is {freshness_hours:.1f}h old, over the "
                f"{config.data_freshness_hours:.0f}h freshness limit"
            )
    if not offer_valid:
        if current_offer is None:
            problems.append(f"vendor offer {proposal.recommended_vendor_id} is no longer available")
        else:
            problems.append(
                f"vendor offer price changed from ${proposal.unit_price:.2f} to "
                f"${current_offer.unit_price:.2f} per unit since approval"
            )
    if not budget_valid:
        if budget.error is not None:
            problems.append(f"budget position unavailable ({budget.error.value})")
        else:
            shortfall = proposal.total_cost - budget.remaining
            problems.append(
                f"insufficient remaining budget for {proposal.warehouse_id} ({budget_month}): "
                f"order costs ${proposal.total_cost:,.2f}, only ${budget.remaining:,.2f} remains "
                f"(budget ${budget.budget_amount:,.2f} - spent ${budget.spent_amount:,.2f} - "
                f"committed ${budget.committed_amount:,.2f}) -- short by ${shortfall:,.2f}"
            )

    return RevalidationResult(
        proposal_id=proposal.proposal_id,
        proposal_hash=proposal.proposal_hash,
        hash_matches=hash_matches,
        stock_valid=stock_valid,
        offer_valid=offer_valid,
        budget_valid=budget_valid,
        all_checks_pass=all_pass,
        error_details="; ".join(problems) if problems else None,
    )
