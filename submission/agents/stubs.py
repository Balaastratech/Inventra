"""
Phase 2 placeholder agents -- hardcoded, deterministic, zero LLM cost.

Same call signature the real LLM-backed agents will use in Phase 4:
(state, last_error) -> <output model>. Swapping a stub for the real agent
in graph/nodes.py is a one-line change; nothing else in the graph moves.

These intentionally do NOT try to be clever. Their only job right now is to
prove the graph's routing, approval, and execution mechanics work end to
end before any agent judgment is real -- see PLAN.md Phase 2 rationale.
"""

from __future__ import annotations

from submission.agents.models import (
    ChecklistVerdict,
    DemandAssessment,
    PolicyChecklistItem,
    PolicyQuestion,
    PolicyReview,
    PolicyVerdict,
    ReplenishmentRecommendation,
    SourcingStrategy,
)
from submission.state.state import CaseState


def assess_demand_stub(state: CaseState, last_error: str | None) -> DemandAssessment:
    sales = state["sales"]
    w7, w30 = sales.window_7_days, sales.window_30_days
    # Flag ambiguity only on a large disagreement between windows -- a real
    # judgment call for Phase 4's agent; the stub uses a blunt threshold so
    # the NEEDS_INFORMATION path stays reachable for skeleton testing.
    disagreement = abs(w7 - w30) / max(w30, 0.01)
    ambiguous = disagreement > 0.75
    chosen = 7 if w7 >= w30 else 30
    return DemandAssessment(
        case_id=state["case_id"],
        chosen_window_days=chosen,
        rationale=(
            f"stub: 7d={w7}/day, 30d={w30}/day, disagreement={disagreement:.0%}; "
            f"chose {chosen}-day window (Phase 4 replaces this with a real judgment)."
        ),
        ambiguous=ambiguous,
        clarification_needed=(
            "7-day and 30-day sales velocity disagree substantially; confirm which window to trust."
            if ambiguous
            else None
        ),
        evidence_ids=[sales.evidence_id],
    )


def recommend_vendor_stub(state: CaseState, last_error: str | None) -> ReplenishmentRecommendation:
    options = state["vendor_options"]
    eligible = options.eligible_options
    # Stub strategy: the best-value eligible option, as computed in
    # graph/economics.py -- lowest all-in cost per day of cover.
    #
    # This used to be min(total_cost), which was wrong for the same reason the
    # real ranking was: order quantities differ per supplier (the target is N
    # days of cover from arrival, so a slower supplier funds more days of
    # demand), so the smallest invoice is not the cheapest purchase. Once
    # economics started ranking on cost per day of cover, this stub began
    # picking options the validation gate correctly refused, and every graph
    # test that walks past recommend_vendor failed closed. The real Strategist
    # agent (Phase 4) explains the choice and may prefer a within-tolerance
    # option that arrives earlier; the stub just takes the winner.
    economics = state.get("economics")
    chosen = None
    if economics is not None:
        chosen = next(
            (o for o in eligible if o.offer_id == economics.best_value_offer_id), None
        )
    if chosen is None:  # defensive: economics not computed (direct unit-test invocation)
        chosen = min(eligible, key=lambda o: o.total_cost)
    return ReplenishmentRecommendation(
        case_id=state["case_id"],
        recommended_offer_id=chosen.offer_id,
        strategy=SourcingStrategy.CHEAPEST,
        rationale=(
            f"stub: picked best-value eligible option {chosen.offer_id} "
            f"(${chosen.total_cost:.2f}, arrives {chosen.expected_arrival.date()}); "
            f"Phase 4 replaces this with a real cost/speed trade-off judgment."
        ),
        other_options_summary=f"{len(eligible)} eligible option(s) considered",
        evidence_ids=[o.offer_id for o in eligible],
    )


def review_policy_stub(state: CaseState, last_error: str | None) -> PolicyReview:
    proposal = state["proposal"]
    # Stub always passes every row; nodes.review_policy still overrides the
    # mechanically-checkable rows (and budget specifically against
    # config.over_budget_exception_tolerance) regardless of what the agent
    # says -- brief: "LLM budget judgment is not authoritative."
    checklist = [
        PolicyChecklistItem(
            question=question,
            verdict=ChecklistVerdict.PASS,
            rationale="stub: no concern raised (Phase 4 replaces this with a real policy.md read).",
        )
        for question in PolicyQuestion
    ]
    return PolicyReview(
        case_id=state["case_id"],
        proposal_id=proposal.proposal_id,
        verdict=PolicyVerdict.PASS,
        checklist=checklist,
        concerns=[],
        rationale="stub: no policy concerns raised (Phase 4 replaces this with a real policy.md read).",
        evidence_ids=[proposal.budget_evidence_id],
    )
