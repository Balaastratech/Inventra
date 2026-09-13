"""
Gap 5 proof: nodes.review_policy must not trust an AI verdict of PASS when
the deterministic evidence says the case is stale or the delivery misses
the projected stockout date -- same override discipline already applied to
budget. Exercised directly against nodes.review_policy with a hand-built
state and a stubbed agent forced to answer PASS, since a real run can never
reach this node with genuinely stale/deadline-missed data (fetch_evidence
and build_options already gate those upstream) -- this is the defense-in-
depth net, verified in isolation.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from domain.tool_models import BudgetPosition, ReplenishmentProposal, StockRisk
from submission.agents import stubs as stub_agents
from submission.agents.models import ChecklistVerdict, PolicyChecklistItem, PolicyQuestion, PolicyReview, PolicyVerdict
from submission.graph import nodes


@pytest.fixture(autouse=True)
def restore_stub_agents():
    yield
    nodes.set_agents(review_policy=stub_agents.review_policy_stub)


def _proposal(**overrides) -> ReplenishmentProposal:
    now = datetime.utcnow()
    base = dict(
        proposal_id="PROP-TEST",
        proposal_hash="hash",
        case_id="CASE-X",
        sku="AC-001",
        warehouse_id="DEL-01",
        stock_evidence_id="stock:1",
        sales_evidence_id="sales:1",
        vendor_evidence_ids=[],
        budget_evidence_id="budget:1",
        available_units=10,
        daily_velocity=1.0,
        target_cover_days=14,
        projected_stockout_date=now + timedelta(days=10),
        recommended_vendor_id="V-1",
        recommended_vendor_name="Test Vendor",
        quantity=20,
        unit_price=50.0,
        total_cost=1000.0,
        expected_arrival=now + timedelta(days=2),
        cost_vs_speed_trade_off=None,
        other_options_summary=None,
        budget_remaining=99000.0,
        policy_passed=False,
        policy_violations=[],
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


def _stub_pass(proposal: ReplenishmentProposal):
    """An agent that answers PASS on everything, including a fully-cited
    evidence_ids list -- so a test exercising the freshness/deadline
    override in isolation doesn't also (accidentally) trip the unrelated
    evidence_traceable override."""

    def _agent(state, last_error):
        checklist = [
            PolicyChecklistItem(question=q, verdict=ChecklistVerdict.PASS, rationale="looks fine")
            for q in PolicyQuestion
        ]
        return PolicyReview(
            case_id="CASE-X", proposal_id=proposal.proposal_id, verdict=PolicyVerdict.PASS,
            checklist=checklist, concerns=[], rationale="looks fine",
            evidence_ids=[proposal.stock_evidence_id, proposal.sales_evidence_id, proposal.budget_evidence_id],
        )
    return _agent


def test_stale_evidence_overrides_an_ai_pass_verdict():
    proposal = _proposal()
    risk = StockRisk(
        available_units=10, daily_velocity=1.0, cover_days=10,
        projected_stockout_date=proposal.projected_stockout_date,
        target_cover_days=14, at_risk=True, freshness_hours=100.0, stale=True,
    )
    state = {
        "case_id": "CASE-X", "trace_id": "T", "retry_counts": {},
        "proposal": proposal, "budget": _budget(), "risk": risk,
    }
    nodes.set_agents(review_policy=_stub_pass(proposal))

    nodes.review_policy(state)

    assert state["policy_review"].verdict.value == "BLOCKED"
    assert any("stale" in c.lower() for c in state["policy_review"].concerns)
    assert state["proposal"].policy_passed is False


def test_missed_deadline_overrides_an_ai_pass_verdict():
    now = datetime.utcnow()
    proposal = _proposal(expected_arrival=now + timedelta(days=20))  # after the stockout date
    risk = StockRisk(
        available_units=10, daily_velocity=1.0, cover_days=10,
        projected_stockout_date=now + timedelta(days=10),
        target_cover_days=14, at_risk=True, freshness_hours=1.0, stale=False,
    )
    state = {
        "case_id": "CASE-X", "trace_id": "T", "retry_counts": {},
        "proposal": proposal, "budget": _budget(), "risk": risk,
    }
    nodes.set_agents(review_policy=_stub_pass(proposal))

    nodes.review_policy(state)

    assert state["policy_review"].verdict.value == "BLOCKED"
    assert any("stockout" in c.lower() for c in state["policy_review"].concerns)


def test_fresh_on_time_evidence_leaves_an_ai_pass_verdict_alone():
    proposal = _proposal()
    risk = StockRisk(
        available_units=10, daily_velocity=1.0, cover_days=10,
        projected_stockout_date=proposal.projected_stockout_date,
        target_cover_days=14, at_risk=True, freshness_hours=1.0, stale=False,
    )
    state = {
        "case_id": "CASE-X", "trace_id": "T", "retry_counts": {},
        "proposal": proposal, "budget": _budget(), "risk": risk,
    }
    nodes.set_agents(review_policy=_stub_pass(proposal))

    nodes.review_policy(state)

    assert state["policy_review"].verdict.value == "PASS"


def test_policy_guidance_length_tripwire_fires_on_a_large_document(tmp_path, caplog):
    import logging

    from tools.policy import get_policy_guidance

    big_policy = tmp_path / "policy.md"
    big_policy.write_text("x" * 20_001)

    with caplog.at_level(logging.WARNING, logger="tools.policy"):
        get_policy_guidance("AC-001", "DEL-01", 14, policy_path=str(big_policy))

    assert any("tripwire" in r.message for r in caplog.records)
