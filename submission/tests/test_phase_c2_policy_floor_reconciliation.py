from __future__ import annotations

from datetime import datetime

from domain.tool_models import PolicyFloor


def _floor(units: int) -> PolicyFloor:
    return PolicyFloor(rule_id="F", sku="S", warehouse_id="W", min_units=units,
                       reason="SLA", source="contract", set_by="ops", effective_from=datetime(2026, 1, 1),
                       active=True, evidence_id="floor:F", retrieved_at=datetime.utcnow())


def test_reconcile_target_prefers_statistical_target_when_it_exceeds_floor():
    from submission.graph.support import reconcile_target
    result = reconcile_target(25, _floor(10), 5)
    assert result.active_target_units == 25
    assert result.basis == "STATISTICAL"
    assert result.excess_or_shortfall_units == -15
    assert "insufficient" in result.explanation.lower()


def test_reconcile_target_honours_higher_policy_floor_and_quantifies_excess():
    from submission.graph.support import reconcile_target
    result = reconcile_target(10, _floor(25), 2)
    assert result.active_target_units == 25
    assert result.basis == "POLICY_FLOOR"
    assert result.excess_or_shortfall_units == 15
    assert "excess" in result.explanation.lower()


def test_policy_review_contract_has_a_policy_floor_question():
    import pytest
    from submission.agents.models import ChecklistVerdict, POLICY_QUESTION_TEXT, PolicyChecklistItem, PolicyQuestion, PolicyReview, PolicyVerdict
    assert PolicyQuestion.POLICY_FLOOR in POLICY_QUESTION_TEXT
    checklist = [PolicyChecklistItem(question=question, verdict=ChecklistVerdict.PASS, rationale="tested") for question in PolicyQuestion]
    review = PolicyReview(case_id="C", proposal_id="P", verdict=PolicyVerdict.PASS, checklist=checklist, rationale="tested")
    assert len(review.checklist) == 9
    with pytest.raises(ValueError):
        PolicyReview(case_id="C", proposal_id="P", verdict=PolicyVerdict.PASS, checklist=checklist[:-1], rationale="tested")


def test_below_floor_target_is_an_explicit_policy_exception(monkeypatch):
    from submission.agents.models import ChecklistVerdict, PolicyChecklistItem, PolicyQuestion, PolicyReview, PolicyVerdict
    from submission.graph import nodes
    from submission.tests.test_phase12_policy_checklist import _fresh_on_time_risk, _proposal, _state

    proposal = _proposal(policy_floor_units=25, statistical_target_units=10, active_target_units=10, target_basis="STATISTICAL")
    state = _state(proposal, _fresh_on_time_risk(proposal))
    monkeypatch.setattr(nodes, "emit_audit", lambda *args, **kwargs: None)
    monkeypatch.setattr("submission.graph.support.emit_audit", lambda *args, **kwargs: None)
    def reviewer(current, _error):
        return PolicyReview(case_id="CASE-X", proposal_id=proposal.proposal_id, verdict=PolicyVerdict.PASS,
            checklist=[PolicyChecklistItem(question=q, verdict=ChecklistVerdict.PASS, rationale="agent") for q in PolicyQuestion],
            rationale="agent", evidence_ids=["stock:1", "sales:1", "budget:1", "offer:V1"])
    nodes.set_agents(review_policy=reviewer)
    nodes.review_policy(state)
    assert state["policy_review"].verdict.value == "EXCEPTION"


def test_target_basis_edit_reprices_through_existing_edit_cycle(monkeypatch):
    from datetime import timedelta
    from domain.tool_models import ApprovalDecision, VendorOption, VendorOptionList
    from submission.agents.models import ReplenishmentRecommendation, SourcingStrategy
    from submission.graph import nodes
    from submission.tests.test_phase12_policy_checklist import _fresh_on_time_risk, _proposal

    proposal = _proposal(policy_floor_units=25, statistical_target_units=10, active_target_units=25, target_basis="POLICY_FLOOR")
    option = VendorOption(offer_id="O", vendor_id="V", vendor_name="Vendor", quantity=25, unit_price=1,
        total_cost=25, lead_time_days=1, expected_arrival=datetime.utcnow() + timedelta(days=1),
        meets_deadline=True, reliable=True, eligible=True)
    state = {
        "case_id": "CASE-X", "trace_id": "T", "retry_counts": {}, "proposal": proposal,
        "risk": _fresh_on_time_risk(proposal), "vendor_options": VendorOptionList(options=[option], eligible_options=[option]),
        "replenishment_recommendation": ReplenishmentRecommendation(case_id="CASE-X", recommended_offer_id="O", strategy=SourcingStrategy.BALANCED, rationale="existing"),
        "target_reconciliation": type("R", (), {"explanation": "policy", "active_target_units": 25, "basis": "POLICY_FLOOR"})(),
        "approval_decision": ApprovalDecision(case_id="CASE-X", proposal_id=proposal.proposal_id, proposal_hash=proposal.proposal_hash,
            decision="EDIT", approver="Yuvraj", approved_at=datetime.utcnow(), chosen_target_basis="STATISTICAL"),
    }
    monkeypatch.setattr(nodes, "build_options", lambda state: state)
    monkeypatch.setattr(nodes, "emit_audit", lambda *args, **kwargs: None)
    nodes.apply_human_edit(state)
    assert state["target_cover_days"] == 10
    assert state["target_provenance"] == "human:Yuvraj"
    assert state["proposal"] is None
