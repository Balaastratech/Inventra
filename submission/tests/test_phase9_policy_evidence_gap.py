"""
Real-run bug proof: a live run had the Policy Reviewer wrongly BLOCK a
correct AC-004/DEL-01 proposal. It cross-checked the Strategist's cost
claim against raw vendor_offers (unit_price only, no quantity), assumed
every vendor's order was the same size, and "found" a contradiction that
wasn't real -- this system prices a different quantity per vendor on
purpose (a slower delivery needs more units to cover the transit time), so
unit_price x an assumed shared quantity is never a valid comparison.

Fix (prompts/policy.py v2): hand the Policy Reviewer the same already-sized
vendor_options + economics block the Strategist and approval screen use, so
it has a correct number to cite instead of a gap to fill with a guess.
"""

from __future__ import annotations

import json

import pytest

from submission.graph.workflow import compile_graph
from submission.prompts.policy import build_user_message
from submission.state.state import create_initial_state
from submission.tests.reset_db import reset_business_state


@pytest.fixture(scope="module", autouse=True)
def clean_state():
    reset_business_state()
    yield


def _state_at_policy_review(sku, warehouse_id, target_cover_days=None):
    """Runs the real graph with stub agents up to (and including)
    draft_proposal, then reads back the state review_policy would see --
    without actually invoking the (stubbed) Policy Reviewer, so this is a
    pure evidence-bundle check, not a live-model assertion."""
    from submission.graph import nodes

    captured = {}
    real_review_policy = nodes._AGENTS["review_policy"]

    def _capture_and_delegate(state, last_error):
        captured["state"] = dict(state)
        return real_review_policy(state, last_error)

    nodes.set_agents(review_policy=_capture_and_delegate)
    try:
        graph, conn = compile_graph()
        try:
            state = create_initial_state(sku, warehouse_id, target_cover_days)
            graph.invoke(state, config={"configurable": {"thread_id": state["thread_id"]}})
        finally:
            conn.close()
    finally:
        from submission.agents import stubs

        nodes.set_agents(review_policy=stubs.review_policy_stub)

    assert "state" in captured, "review_policy must have been reached"
    return captured["state"]


def test_policy_reviewer_receives_the_same_sized_vendor_options_the_strategist_used():
    state = _state_at_policy_review("AC-004", "DEL-01", target_cover_days=14)
    prompt = build_user_message(state)

    # The evidence block is fenced JSON inside the rendered prompt text.
    json_text = prompt.split("```json\n", 1)[1].rsplit("\n```", 1)[0]
    evidence = json.loads(json_text)

    assert "vendor_options" in evidence and evidence["vendor_options"], (
        "must receive the already-sized VendorOption list, not just raw vendor_offers"
    )
    for option in evidence["vendor_options"]:
        assert "quantity" in option and "total_cost" in option

    assert "economics" in evidence and evidence["economics"] is not None
    # The reviewer needs the comparison the pick was actually made on, which is
    # cost per day of cover -- not total_cost, since quantities differ per
    # supplier by design. See graph/economics.py.
    assert "best_value_offer_id" in evidence["economics"]
    assert evidence["economics"]["ranking_basis"] == "all_in_cost_per_day_of_cover"

    # The old evidence is still present (needed for validity/reliability
    # checks) -- this is additive, not a replacement.
    assert "vendor_offers" in evidence


def test_policy_system_prompt_forbids_cross_vendor_price_math_from_raw_offers():
    from submission.prompts.policy import SYSTEM

    assert "vendor_offers" in SYSTEM
    assert "not a basis for comparing cost" in SYSTEM or "NOT a basis for comparing cost" in SYSTEM
