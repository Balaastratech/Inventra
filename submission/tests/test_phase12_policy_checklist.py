"""
Policy review upgrade, 2026-09-11: a single free-text verdict was replaced
with an 8-row checklist, one row per policy.md review question, schema-
enforced (PolicyReview.checklist must cover every PolicyQuestion exactly
once -- see submission/agents/models.py). nodes.review_policy then code-
overrides every row that is mechanically checkable from state already on
hand, the same "LLM judgment is not authoritative" discipline the budget
check has always used. Only tradeoff_explained is left as the agent's own
call -- it is a narrative judgment ("which tradeoff is being made"), not a
fact the graph can independently verify.

The new, previously-unenforced check is evidence_traceable (policy.md
question 8): an empty or hallucinated evidence_ids list now fails closed,
where before nothing checked it at all.

Same isolation style as test_phase9_policy_hardening.py: exercises
nodes.review_policy directly against a hand-built state, since a real run
can't manufacture a hallucinated-evidence agent response.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from domain.tool_models import BudgetPosition, ReplenishmentProposal, StockRisk
from submission.agents import stubs as stub_agents
from submission.agents.models import (
    ChecklistVerdict,
    PolicyChecklistItem,
    PolicyQuestion,
    PolicyReview,
    PolicyVerdict,
)
from submission.graph import nodes
from submission.graph.workflow import compile_graph
from submission.state.state import create_initial_state
from submission.tests.reset_db import reset_business_state


@pytest.fixture(scope="module", autouse=True)
def clean_state():
    reset_business_state()
    yield


@pytest.fixture(autouse=True)
def restore_stub_agents():
    yield
    nodes.set_agents(review_policy=stub_agents.review_policy_stub)


def _proposal(**overrides) -> ReplenishmentProposal:
    now = datetime.utcnow()
    base = dict(
        proposal_id="PROP-TEST", proposal_hash="hash", case_id="CASE-X",
        sku="AC-001", warehouse_id="DEL-01",
        stock_evidence_id="stock:1", sales_evidence_id="sales:1",
        vendor_evidence_ids=["offer:V1"], budget_evidence_id="budget:1",
        available_units=10, daily_velocity=1.0, target_cover_days=14,
        projected_stockout_date=now + timedelta(days=10),
        recommended_vendor_id="V-1", recommended_vendor_name="Test Vendor",
        quantity=20, unit_price=50.0, total_cost=1000.0,
        expected_arrival=now + timedelta(days=2),
        cost_vs_speed_trade_off=None, other_options_summary=None,
        budget_remaining=99000.0, policy_passed=False, policy_violations=[],
        created_at=now,
    )
    base.update(overrides)
    return ReplenishmentProposal(**base)


def _budget() -> BudgetPosition:
    return BudgetPosition(
        warehouse_id="DEL-01", month="2026-01", budget_amount=100000,
        spent_amount=0, committed_amount=0, remaining=100000,
        retrieved_at=datetime.utcnow(), evidence_id="budget:1",
    )


def _fresh_on_time_risk(proposal: ReplenishmentProposal) -> StockRisk:
    return StockRisk(
        available_units=10, daily_velocity=1.0, cover_days=10,
        projected_stockout_date=proposal.projected_stockout_date,
        target_cover_days=14, at_risk=True, freshness_hours=1.0, stale=False,
    )


def _state(proposal, risk):
    return {
        "case_id": "CASE-X", "trace_id": "T", "retry_counts": {},
        "proposal": proposal, "budget": _budget(), "risk": risk,
    }


def _agent_with(evidence_ids: list[str], tradeoff_verdict=ChecklistVerdict.PASS, tradeoff_rationale="agent's own call"):
    def _agent(state, last_error):
        checklist = [
            PolicyChecklistItem(
                question=q,
                verdict=tradeoff_verdict if q == PolicyQuestion.TRADEOFF_EXPLAINED else ChecklistVerdict.PASS,
                rationale=tradeoff_rationale if q == PolicyQuestion.TRADEOFF_EXPLAINED else "agent said fine",
            )
            for q in PolicyQuestion
        ]
        return PolicyReview(
            case_id="CASE-X", proposal_id=state["proposal"].proposal_id, verdict=PolicyVerdict.PASS,
            checklist=checklist, concerns=[], rationale="looks fine", evidence_ids=evidence_ids,
        )
    return _agent


def test_evidence_traceable_fails_closed_on_empty_evidence_ids():
    proposal = _proposal()
    state = _state(proposal, _fresh_on_time_risk(proposal))
    nodes.set_agents(review_policy=_agent_with(evidence_ids=[]))

    nodes.review_policy(state)

    review = state["policy_review"]
    assert review.verdict.value == "BLOCKED"
    row = next(i for i in review.checklist if i.question == PolicyQuestion.EVIDENCE_TRACEABLE)
    assert row.verdict == ChecklistVerdict.FAIL
    assert any("evidence" in c.lower() for c in review.concerns)


def test_evidence_traceable_fails_closed_on_a_hallucinated_id():
    proposal = _proposal()
    state = _state(proposal, _fresh_on_time_risk(proposal))
    nodes.set_agents(review_policy=_agent_with(evidence_ids=["stock:1", "made-up-id-not-in-evidence"]))

    nodes.review_policy(state)

    review = state["policy_review"]
    assert review.verdict.value == "BLOCKED"
    row = next(i for i in review.checklist if i.question == PolicyQuestion.EVIDENCE_TRACEABLE)
    assert row.verdict == ChecklistVerdict.FAIL


def test_evidence_traceable_passes_with_real_evidence_ids():
    proposal = _proposal()
    state = _state(proposal, _fresh_on_time_risk(proposal))
    nodes.set_agents(review_policy=_agent_with(evidence_ids=["stock:1", "sales:1", "budget:1", "offer:V1"]))

    nodes.review_policy(state)

    review = state["policy_review"]
    assert review.verdict.value == "PASS"
    row = next(i for i in review.checklist if i.question == PolicyQuestion.EVIDENCE_TRACEABLE)
    assert row.verdict == ChecklistVerdict.PASS


def test_tradeoff_explained_is_the_only_row_left_to_the_agent():
    proposal = _proposal()
    state = _state(proposal, _fresh_on_time_risk(proposal))
    nodes.set_agents(
        review_policy=_agent_with(
            evidence_ids=["stock:1", "sales:1", "budget:1", "offer:V1"],
            tradeoff_verdict=ChecklistVerdict.FAIL,
            tradeoff_rationale="the agent's own concern about the trade-off, verbatim",
        )
    )

    nodes.review_policy(state)

    review = state["policy_review"]
    tradeoff_row = next(i for i in review.checklist if i.question == PolicyQuestion.TRADEOFF_EXPLAINED)
    assert tradeoff_row.verdict == ChecklistVerdict.FAIL
    assert tradeoff_row.rationale == "the agent's own concern about the trade-off, verbatim"
    # Every other row went through the deterministic override and does NOT
    # carry the agent's generic "agent said fine" rationale.
    other_rows = [i for i in review.checklist if i.question != PolicyQuestion.TRADEOFF_EXPLAINED]
    assert all(i.rationale != "agent said fine" for i in other_rows)
    # tradeoff_explained is descriptive, not a hard gate -- a FAIL there
    # must not by itself block the case (unlike freshness/deadline/evidence).
    assert review.verdict.value == "PASS"


def test_checklist_always_covers_every_question_after_override():
    proposal = _proposal()
    state = _state(proposal, _fresh_on_time_risk(proposal))
    nodes.set_agents(review_policy=_agent_with(evidence_ids=["stock:1", "sales:1", "budget:1", "offer:V1"]))

    nodes.review_policy(state)

    questions = {item.question for item in state["policy_review"].checklist}
    assert questions == set(PolicyQuestion)


def _run(sku, warehouse_id):
    graph, conn = compile_graph()
    try:
        state = create_initial_state(sku, warehouse_id)
        return graph.invoke(state, config={"configurable": {"thread_id": state["thread_id"]}})
    finally:
        conn.close()


def test_incomplete_checklist_fails_validation_and_repair_retries():
    """An agent that omits a question is a schema failure like any other --
    same one-repair-then-proceed discipline as scenario 6."""
    calls = {"n": 0}

    def flaky_review(state, last_error):
        calls["n"] += 1
        if calls["n"] == 1:
            assert last_error is None
            incomplete = [
                PolicyChecklistItem(question=q, verdict=ChecklistVerdict.PASS, rationale="ok")
                for q in list(PolicyQuestion)[:-1]  # one short -- fails PolicyReview's own validator
            ]
            return PolicyReview(
                case_id=state["case_id"], proposal_id=state["proposal"].proposal_id,
                verdict=PolicyVerdict.PASS, checklist=incomplete, concerns=[], rationale="ok",
                evidence_ids=[],
            )
        assert last_error is not None and "checklist" in last_error.lower()
        return stub_agents.review_policy_stub(state, last_error)

    nodes.set_agents(review_policy=flaky_review)
    result = _run("AC-003", "DEL-21")

    assert calls["n"] == 2
    assert "__interrupt__" in result, "should still reach approval after the repair succeeded"
