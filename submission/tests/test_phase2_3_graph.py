"""
Phase 2/3 end-to-end tests: real graph, real (reseeded + additively
extended) database, stubbed agents (Phase 4 swaps those). Proves the
skeleton + approval + execution boundary mechanics, independent of any LLM.

Every test uses a distinct sku+warehouse_id pair on purpose -- case_id is
derived from that pair alone (D8: stable case_id, no forking), so reusing
a pair across tests would collide on the same LangGraph thread. Where the
seeded starter data doesn't offer enough distinct at-risk+approvable
combinations, seed_extra.py adds isolated ones (PLAN.md D5) rather than
editing the provided seed.

Run: python database/seed.py && python -m submission.tests.seed_extra
     (first, or every case looks stale / fixtures are missing)
"""

from __future__ import annotations

import os
import sqlite3
from datetime import datetime, timezone

import pytest
from langgraph.types import Command

from domain.tool_models import ErrorCode, ProposalStatus
from submission.config import config
from submission.graph.workflow import compile_graph, latest_thread_id
from submission.state.state import create_initial_state
from submission.tests.reset_db import reset_business_state
from tools.execution import create_purchase_request


@pytest.fixture(scope="module", autouse=True)
def clean_state():
    # Full reset, not just the checkpoint file: two tests below leave
    # permanent marks on the database (a purchase_requests row, and DEL-02's
    # budget) that made the suite pass only on a freshly seeded database.
    # See submission/tests/reset_db.py.
    reset_business_state()
    yield


def _run(sku, warehouse_id, target_cover_days=None):
    graph, conn = compile_graph()
    try:
        state = create_initial_state(sku, warehouse_id, target_cover_days)
        return graph.invoke(state, config={"configurable": {"thread_id": state["thread_id"]}})
    finally:
        conn.close()


def _thread(case_id):
    """thread_id is per-run now (`<case_id>#<timestamp>`), so a business
    case_id has to be resolved to its latest checkpoint thread. Previously
    the two were the same string, which meant a finished case could never be
    re-run -- see state.new_thread_id."""
    thread = latest_thread_id(case_id)
    assert thread is not None, f"no checkpoint thread found for {case_id}"
    return {"configurable": {"thread_id": thread}}


def _resume(case_id, decision_payload):
    graph, conn = compile_graph()
    try:
        return graph.invoke(Command(resume=decision_payload), config=_thread(case_id))
    finally:
        conn.close()


def _proposal_for(case_id):
    graph, conn = compile_graph()
    try:
        return graph.get_state(_thread(case_id)).values["proposal"]
    finally:
        conn.close()


def _decision(case_id, proposal, decision, approver="tester", comments=None):
    return {
        "case_id": case_id,
        "proposal_id": proposal.proposal_id,
        "proposal_hash": proposal.proposal_hash,
        "decision": decision,
        "approver": approver,
        "comments": comments,
        "approved_at": datetime.now(timezone.utc).isoformat(),
    }


# Scenario 1: healthy stock -> NO_ACTION, sourcing never runs
def test_healthy_coverage_reaches_no_action():
    result = _run("AC-001", "DEL-01", target_cover_days=7)  # ~13-15d real coverage: healthy at a 7d target
    assert "__interrupt__" not in result
    assert result["status"] == ProposalStatus.NO_ACTION
    assert result["vendor_offers"] is None


# Scenario 3: stale snapshot -> BLOCKED, DATA_STALE
def test_stale_snapshot_blocks():
    result = _run("AC-002", "DEL-01")
    assert "__interrupt__" not in result
    assert result["status"] == ProposalStatus.BLOCKED
    assert result["error_code"] == ErrorCode.DATA_STALE


# Scenario 12: only unreliable/expired vendors -> BLOCKED, no eligible options
def test_unreliable_vendors_only_blocks():
    result = _run("AC-006", "DEL-01")
    assert "__interrupt__" not in result
    assert result["status"] == ProposalStatus.BLOCKED
    assert result["vendor_options"] is not None
    assert result["vendor_options"].eligible_options == []


# Scenarios 4 & 8: at-risk -> approval -> purchase created; duplicate
# create_purchase_request call with the same idempotency key is a no-op.
def test_approval_flow_creates_purchase_request_and_is_idempotent():
    result = _run("AC-003", "DEL-01")
    assert "__interrupt__" in result, "AC-003 should be at risk and pause for approval"
    payload = result["__interrupt__"][0].value
    case_id = payload["case_id"]

    proposal = _proposal_for(case_id)
    final = _resume(case_id, _decision(case_id, proposal, "APPROVED"))
    assert final["status"] == ProposalStatus.PURCHASE_REQUEST_CREATED
    assert final["purchase_result"].created is True

    idempotency_key = final["idempotency_key"]
    dup = create_purchase_request(proposal, idempotency_key, "tester")
    assert dup.created is False
    assert dup.request_id == final["purchase_result"].request_id

    conn = sqlite3.connect(config.database_path)
    count = conn.execute(
        "SELECT COUNT(*) FROM purchase_requests WHERE idempotency_key = ?", (idempotency_key,)
    ).fetchone()[0]
    conn.close()
    assert count == 1


# Scenario 5: proposal cost is far over remaining budget -> BLOCKED before
# ever reaching a human; no automatic write. (config.over_budget_exception_tolerance
# covers the *mild* overage case separately -- see nodes.review_policy.)
def test_far_over_budget_blocks_before_approval():
    result = _run("AC-004", "DEL-01", target_cover_days=45)  # max target -> large order -> far over budget
    assert "__interrupt__" not in result, "wildly over-budget should fail closed, not reach a human"
    assert result["status"] == ProposalStatus.BLOCKED
    assert result.get("purchase_result") is None
    assert "budget" in (result.get("error_detail") or "").lower()


# Scenario 9: human rejection -> BLOCKED, audited, no write.
def test_human_rejection_blocks_without_writing():
    result = _run("AC-001", "DEL-04", target_cover_days=14)  # mirrors AC-001/DEL-01's real ~13.8d coverage: at-risk
    assert "__interrupt__" in result
    payload = result["__interrupt__"][0].value
    case_id = payload["case_id"]
    proposal = _proposal_for(case_id)

    final = _resume(case_id, _decision(case_id, proposal, "REJECTED", comments="not now"))
    assert final["status"] == ProposalStatus.BLOCKED
    assert final.get("purchase_result") is None
    assert final["approval_decision"].decision == "REJECTED"


# Scenario 7 (fixtures/scenarios.json APPROVAL_DATA_CHANGE): facts change
# during the pause -> revalidation fails, old approval invalidated, case
# re-enters risk assessment with fresh evidence (bounded, one bounce --
# routes.route_after_revalidation), never writes against stale facts. Here
# the underlying fact (budget) is still bad after re-assessment, so the
# case correctly lands on BLOCKED (matching the fixture's expected_outcome)
# rather than a second pause -- the fixture doesn't require a re-pause,
# only that the stale approval never executes.
# Uses the isolated DEL-02 budget row so this mutation can't bleed into
# other tests sharing DEL-01's budget.
def test_budget_change_during_pause_invalidates_approval():
    result = _run("AC-003", "DEL-02")
    assert "__interrupt__" in result
    payload = result["__interrupt__"][0].value
    case_id = payload["case_id"]
    proposal = _proposal_for(case_id)

    conn = sqlite3.connect(config.database_path)
    conn.execute("UPDATE monthly_budgets SET spent_amount = budget_amount WHERE warehouse_id = 'DEL-02'")
    conn.commit()
    conn.close()

    final = _resume(case_id, _decision(case_id, proposal, "APPROVED"))

    assert final.get("purchase_result") is None, "must never write against a stale, now-invalid approval"
    assert final["status"] == ProposalStatus.BLOCKED
    assert final["retry_counts"].get("revalidate") == 1, "should have actually bounced through re-assessment once"
    # Blocked by the fresh policy review on the retry pass, not stuck
    # showing the original (now-cleared) revalidation failure message.
    assert "revalidation failed" not in (final.get("error_detail") or "").lower()


# Scenario 10: write failure -> WRITE_FAILED, never claims success
def test_write_failure_never_claims_success(monkeypatch):
    from domain.tool_models import PurchaseRequestResult, PurchaseRequestStatus

    def _boom(proposal, idempotency_key, approved_by):
        return PurchaseRequestResult(
            request_id="",
            case_id=proposal.case_id,
            status=PurchaseRequestStatus.FAILED,
            created=False,
            total_cost=0,
            error=ErrorCode.WRITE_FAILED,
            error_details="simulated database write failure",
        )

    import submission.graph.nodes as nodes_module

    monkeypatch.setattr(nodes_module, "create_purchase_request", _boom)

    # Was AC-004/DEL-03. Once order sizing began accounting for lead-time
    # demand (economics.size_order_quantity), AC-004's order grew from ~$13k
    # to ~$18k against DEL-03's $15k remaining budget, so the case now fails
    # closed on budget before it ever reaches a human -- correct behaviour for
    # the fixture literally named "Over Budget", but it means the case no
    # longer reaches the write step this test needs to exercise. AC-003/DEL-07
    # is at risk, affordable, and used by no other test.
    result = _run("AC-003", "DEL-07")
    assert "__interrupt__" in result
    payload = result["__interrupt__"][0].value
    case_id = payload["case_id"]
    proposal = _proposal_for(case_id)

    final = _resume(case_id, _decision(case_id, proposal, "APPROVED"))

    assert final["status"] == ProposalStatus.BLOCKED
    assert final["error_code"] == ErrorCode.WRITE_FAILED
    assert final["purchase_result"].created is False
