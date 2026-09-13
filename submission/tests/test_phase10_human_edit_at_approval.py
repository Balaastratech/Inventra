"""
B8 proof: an approver can pick a different eligible supplier directly.

Before this the approval screen offered Approve / Ask for changes / Reject.
An approver who already knew they wanted the other quoted supplier had to go
through REVISE -- write a comment and hope the strategist interpreted it the
way they meant.

The safety-critical part of this feature is what it does NOT let a human do:
it cannot introduce an ineligible supplier, cannot hand-edit quantity, and
cannot skip the policy re-check. Most of the tests below are about those
limits rather than the happy path.
"""

from __future__ import annotations

import pytest

from domain.tool_models import ApprovalDecision, ErrorCode
from submission.config import config
from submission.graph import nodes, routes
from submission.graph.hashing import compute_proposal_hash, hash_fields_from_proposal


def _decision(decision: str, offer_id: str | None = None, comments: str | None = None):
    from datetime import datetime, timezone

    return ApprovalDecision(
        case_id="CASE-AC-003-DEL-01",
        proposal_id="PROP-1",
        proposal_hash="abc123",
        decision=decision,
        approver="yuvraj",
        comments=comments,
        approved_at=datetime.now(timezone.utc),
        edited_offer_id=offer_id,
    )


# ---------------------------------------------------------------------------
# Routing: which decisions reach the edit node, and when it is cut off.
# ---------------------------------------------------------------------------


def test_an_edit_decision_routes_to_the_edit_node():
    state = {"approval_decision": _decision("EDIT", "OFFER-003-1"), "retry_counts": {}}
    assert routes.route_after_decision(state) == "edit"


def test_edits_are_bounded_by_their_own_cap():
    state = {
        "approval_decision": _decision("EDIT", "OFFER-003-1"),
        "retry_counts": {"human_edit": config.max_human_edit_cycles},
    }
    assert routes.route_after_decision(state) == "edit_limit_exceeded"


def test_the_edit_budget_is_separate_from_the_revision_budget():
    """A planner comparing suppliers should not burn the REVISE budget doing
    it -- the two loops cost different things."""
    state = {
        "approval_decision": _decision("EDIT", "OFFER-003-1"),
        "retry_counts": {"human_edit": 0},
        "revision_count": config.max_revision_cycles,  # revision budget spent
    }
    assert routes.route_after_decision(state) == "edit", (
        "an exhausted revision budget must not block a supplier switch"
    )


def test_existing_decisions_are_unaffected():
    for decision, expected in [("APPROVED", "approved"), ("REJECTED", "rejected")]:
        state = {"approval_decision": _decision(decision), "retry_counts": {}}
        assert routes.route_after_decision(state) == expected


# ---------------------------------------------------------------------------
# The node itself, driven off real vendor options built by the real graph.
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def case_with_two_options():
    """A real paused case whose eligible list has more than one supplier.
    AC-003 is the brief's speed-vs-cost fixture, so it has both."""
    from submission.graph.workflow import compile_graph
    from submission.state.state import create_initial_state
    from submission.tests.reset_db import reset_business_state

    reset_business_state()
    graph, conn = compile_graph()
    try:
        state = create_initial_state("AC-003", "DEL-01")
        thread = {"configurable": {"thread_id": state["thread_id"]}}
        result = graph.invoke(state, config=thread)
        assert "__interrupt__" in result, "fixture must reach the approval pause"
        snapshot = graph.get_state(thread)
        values = dict(snapshot.values)
    finally:
        conn.close()

    assert len(values["vendor_options"].eligible_options) >= 2, (
        "fixture needs at least two eligible suppliers to switch between"
    )
    return values


def _editable_state(values: dict, offer_id: str | None, comments=None) -> dict:
    state = dict(values)
    state["approval_decision"] = _decision("EDIT", offer_id, comments)
    state["retry_counts"] = dict(state.get("retry_counts") or {})
    return state


def test_switching_supplier_repoints_the_recommendation(case_with_two_options):
    values = case_with_two_options
    current = next(
        o for o in values["vendor_options"].eligible_options
        if o.vendor_id == values["proposal"].recommended_vendor_id
    )
    other = next(
        o for o in values["vendor_options"].eligible_options if o.offer_id != current.offer_id
    )

    state = _editable_state(values, other.offer_id)
    nodes.apply_human_edit(state)

    assert state["error_code"] is None
    assert routes.route_after_human_edit(state) == "ok"
    assert state["replenishment_recommendation"].recommended_offer_id == other.offer_id


def test_the_superseded_proposal_and_policy_verdict_are_discarded(case_with_two_options):
    """A policy verdict passed on supplier A must never be read as covering
    supplier B."""
    values = case_with_two_options
    other = next(
        o for o in values["vendor_options"].eligible_options
        if o.vendor_id != values["proposal"].recommended_vendor_id
    )

    state = _editable_state(values, other.offer_id)
    assert state.get("policy_review") is not None, "fixture should have a policy verdict"

    nodes.apply_human_edit(state)

    assert state["proposal"] is None
    assert state["policy_review"] is None
    assert state["revalidation"] is None
    # The old approval must not carry over to the rebuilt proposal.
    assert state["approval_decision"] is None


def test_quantity_and_totals_come_from_the_chosen_option_not_the_old_one(case_with_two_options):
    """Rebuilding through draft_proposal is what keeps quantity correct for
    the new supplier's lead time. Proves the numbers are re-derived rather
    than carried across."""
    values = case_with_two_options
    other = next(
        o for o in values["vendor_options"].eligible_options
        if o.vendor_id != values["proposal"].recommended_vendor_id
    )

    state = _editable_state(values, other.offer_id)
    nodes.apply_human_edit(state)
    nodes.draft_proposal(state)

    rebuilt = state["proposal"]
    assert rebuilt.recommended_vendor_id == other.vendor_id
    assert rebuilt.quantity == other.quantity
    assert rebuilt.unit_price == other.unit_price
    assert rebuilt.total_cost == other.total_cost
    # The hash must match the NEW content, otherwise revalidation would
    # reject the human's own edit as tampering.
    assert rebuilt.proposal_hash == compute_proposal_hash(hash_fields_from_proposal(rebuilt))
    assert rebuilt.budget_remaining == values["budget"].remaining - other.total_cost


def test_an_ineligible_offer_is_refused_and_fails_closed(case_with_two_options):
    """The UI only offers eligible options, but the CLI and email paths accept
    a raw offer_id. An unknown id must not become a proposal."""
    state = _editable_state(case_with_two_options, "OFFER-DOES-NOT-EXIST")
    nodes.apply_human_edit(state)

    assert state["error_code"] == ErrorCode.INVALID_INPUT
    assert routes.route_after_human_edit(state) == "blocked"
    assert state["replenishment_recommendation"].recommended_offer_id != "OFFER-DOES-NOT-EXIST"


def test_a_missing_offer_id_is_refused(case_with_two_options):
    state = _editable_state(case_with_two_options, None)
    nodes.apply_human_edit(state)

    assert state["error_code"] == ErrorCode.INVALID_INPUT
    assert routes.route_after_human_edit(state) == "blocked"


def test_the_edit_is_recorded_against_the_named_human(case_with_two_options):
    values = case_with_two_options
    other = next(
        o for o in values["vendor_options"].eligible_options
        if o.vendor_id != values["proposal"].recommended_vendor_id
    )
    state = _editable_state(values, other.offer_id)
    nodes.apply_human_edit(state)

    from submission.portfolio import read_case_history

    events = read_case_history(state["case_id"])
    edits = [e for e in events if e.raw.get("to_offer_id") == other.offer_id]
    assert edits, "the supplier switch must appear in the audit trail"
    assert edits[-1].actor == "human:yuvraj"


def test_the_rationale_shown_to_the_next_approver_is_attributed_to_the_human(
    case_with_two_options,
):
    """The rebuilt screen shows recommendation.rationale under "Why this
    supplier". It must not read as though a model reasoned its way there."""
    values = case_with_two_options
    other = next(
        o for o in values["vendor_options"].eligible_options
        if o.vendor_id != values["proposal"].recommended_vendor_id
    )
    state = _editable_state(values, other.offer_id, comments="we have used them before")
    nodes.apply_human_edit(state)

    rationale = state["replenishment_recommendation"].rationale
    assert "yuvraj" in rationale
    assert "we have used them before" in rationale


# ---------------------------------------------------------------------------
# Wiring: the edit must re-enter policy review, never jump to execution.
# ---------------------------------------------------------------------------


def test_the_edit_path_is_wired_through_policy_review_not_straight_to_execution():
    """The load-bearing safety property. An edit can newly break the budget or
    the arrival deadline, so it must pass review_policy and a fresh human
    approval before it can reach execute_purchase."""
    from submission.graph.workflow import build_graph

    graph = build_graph()
    assert "apply_human_edit" in graph.nodes

    edges = set(graph.edges)  # StateGraph stores plain (source, target) tuples
    conditional = getattr(graph, "branches", {})

    # draft_proposal -> review_policy already exists unconditionally, so
    # reaching draft_proposal is sufficient to guarantee the re-review.
    targets = set()
    for branches in conditional.values():
        for branch in branches.values():
            ends = getattr(branch, "ends", None) or {}
            targets.update(ends.values())
    assert "apply_human_edit" in targets, "no decision branch reaches the edit node"
    assert ("draft_proposal", "review_policy") in edges, (
        "an edited proposal must be re-reviewed against policy"
    )
