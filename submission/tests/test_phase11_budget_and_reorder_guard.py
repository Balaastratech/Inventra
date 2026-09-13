"""
Three closed workflow gaps, 2026-09-11:

  * No reorder guard -- a re-run for the same sku/warehouse proposed a
    second order for stock already ordered, because confirmed_inbound is
    never written by this system. Fixed by folding open (PENDING)
    purchase_requests quantity into compute_risk's available_units.
  * Budget never reserved -- an approved order didn't reduce
    monthly_budgets.committed_amount, so a second case in the same month
    was judged affordable against money already spent. Fixed by
    create_purchase_request incrementing committed_amount and
    cancel_purchase_request releasing it.
  * Idempotency key was approver-scoped (proposal_hash:approver) -- the same
    proposal approved by two different people produced two purchase_requests
    rows. Fixed by keying on proposal_hash alone.

Uses DEL-18/19/20 (seed_extra.py) -- one warehouse per test, not shared.
proposal_hash is deterministic (sku, warehouse_id, quantity, unit_price,
vendor_id, target_cover_days -- no case_id or timestamp), so two runs
against the *same* warehouse in the same module produce byte-identical
proposals and collide on idempotency_key. That's a real, separate, narrow
edge case: a cancelled request's idempotency_key blocks a later identical
approval from creating a fresh row. It is intentionally not covered here.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

import pytest
from langgraph.types import Command

from domain.tool_models import ProposalStatus
from submission.config import config
from submission.graph.workflow import compile_graph, latest_thread_id
from submission.state.state import create_initial_state
from submission.tests.reset_db import reset_business_state
from tools.execution import cancel_purchase_request, create_purchase_request

SKU = "AC-003"


@pytest.fixture(scope="module", autouse=True)
def clean_state():
    reset_business_state()
    yield


def _run(warehouse):
    graph, conn = compile_graph()
    try:
        state = create_initial_state(SKU, warehouse)
        return graph.invoke(state, config={"configurable": {"thread_id": state["thread_id"]}})
    finally:
        conn.close()


def _resume(case_id, decision_payload):
    graph, conn = compile_graph()
    try:
        thread = latest_thread_id(case_id)
        return graph.invoke(Command(resume=decision_payload), config={"configurable": {"thread_id": thread}})
    finally:
        conn.close()


def _proposal_for(case_id):
    graph, conn = compile_graph()
    try:
        thread = latest_thread_id(case_id)
        return graph.get_state({"configurable": {"thread_id": thread}}).values["proposal"]
    finally:
        conn.close()


def _decision(case_id, proposal, approver="tester"):
    return {
        "case_id": case_id,
        "proposal_id": proposal.proposal_id,
        "proposal_hash": proposal.proposal_hash,
        "decision": "APPROVED",
        "approver": approver,
        "comments": None,
        "approved_at": datetime.now(timezone.utc).isoformat(),
    }


def _committed_amount(warehouse):
    conn = sqlite3.connect(config.database_path)
    row = conn.execute(
        "SELECT committed_amount FROM monthly_budgets WHERE warehouse_id = ?", (warehouse,)
    ).fetchone()
    conn.close()
    return row[0]


def test_approving_reserves_budget_and_cancelling_releases_it():
    warehouse = "DEL-18"
    before = _committed_amount(warehouse)

    result = _run(warehouse)
    assert "__interrupt__" in result, "AC-003/DEL-18 should be at risk and pause for approval"
    case_id = result["__interrupt__"][0].value["case_id"]
    proposal = _proposal_for(case_id)

    final = _resume(case_id, _decision(case_id, proposal))
    assert final["status"] == ProposalStatus.PURCHASE_REQUEST_CREATED
    request_id = final["purchase_result"].request_id

    reserved = _committed_amount(warehouse)
    assert reserved == pytest.approx(before + proposal.total_cost), (
        "approving must increment committed_amount by the proposal's total_cost"
    )

    cancel_purchase_request(request_id, "tester", "budget reservation test cleanup")

    released = _committed_amount(warehouse)
    assert released == pytest.approx(before), "cancelling must release exactly what was reserved"


def test_idempotency_key_is_approver_independent():
    warehouse = "DEL-19"
    result = _run(warehouse)
    assert "__interrupt__" in result
    case_id = result["__interrupt__"][0].value["case_id"]
    proposal = _proposal_for(case_id)

    final = _resume(case_id, _decision(case_id, proposal, approver="alice"))
    assert final["status"] == ProposalStatus.PURCHASE_REQUEST_CREATED

    # A different approver "approving" the identical proposal must dedupe to
    # the same row, not create a second one -- create_purchase_request's own
    # documented contract is idempotency on the proposal, not the approver.
    dup = create_purchase_request(proposal, proposal.proposal_hash, "bob")
    assert dup.created is False
    assert dup.request_id == final["purchase_result"].request_id


def test_reorder_guard_stops_a_duplicate_proposal_for_stock_already_ordered():
    warehouse = "DEL-20"
    # First run: at risk, approve, order created. Physical stock is
    # unchanged (no fulfillment in this system), so a naive re-run would see
    # the exact same on_hand/reserved and propose again.
    result = _run(warehouse)
    assert "__interrupt__" in result
    case_id = result["__interrupt__"][0].value["case_id"]
    proposal = _proposal_for(case_id)
    final = _resume(case_id, _decision(case_id, proposal))
    assert final["status"] == ProposalStatus.PURCHASE_REQUEST_CREATED

    # Second run, same sku/warehouse, same case_id, fresh thread ("the next
    # day"): the open PENDING order must be counted as available stock, so
    # the case is no longer at risk and does not propose a second order.
    second = _run(warehouse)
    assert "__interrupt__" not in second, (
        "an open order for this sku/warehouse must suppress a duplicate proposal"
    )
    assert second["status"] == ProposalStatus.NO_ACTION
