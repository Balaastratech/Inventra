"""
Gap 9 proof: a human rejection with a stated reason is written as a durable
signal against the rejected vendor, and a later case involving that same
vendor sees it as additive context in the strategist's prompt payload.

Uses two different warehouses for the same SKU (AC-003) on purpose --
vendor_offers/vendors are keyed by SKU only, not warehouse (schema.sql has
no warehouse_id column on either table), so the same vendor_id is a
candidate option on both cases. Asserted against the prompt-building
function's own output, never against live LLM behaviour.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

import pytest
from langgraph.types import Command

from submission.config import config
from submission.graph.workflow import compile_graph, latest_thread_id
from submission.prompts.strategist import build_user_message
from submission.state.state import create_initial_state
from submission.tests.reset_db import reset_business_state


@pytest.fixture(scope="module", autouse=True)
def clean_state():
    reset_business_state()
    yield


def _run(sku, warehouse_id):
    graph, conn = compile_graph()
    try:
        state = create_initial_state(sku, warehouse_id)
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


def test_rejection_writes_a_signal_and_a_later_case_sees_it_in_the_prompt():
    # Case 1: reach approval, reject with a stated reason.
    first = _run("AC-003", "DEL-14")
    assert "__interrupt__" in first
    payload = first["__interrupt__"][0].value
    case_id = payload["case_id"]
    rejected_vendor_id = None

    graph, conn = compile_graph()
    try:
        proposal = graph.get_state({"configurable": {"thread_id": latest_thread_id(case_id)}}).values["proposal"]
        rejected_vendor_id = proposal.recommended_vendor_id
    finally:
        conn.close()

    decision = {
        "case_id": case_id,
        "proposal_id": payload["proposal_id"],
        "proposal_hash": payload["proposal_hash"],
        "decision": "REJECTED",
        "approver": "tester",
        "comments": "this vendor was late on our last three orders",
        "approved_at": datetime.now(timezone.utc).isoformat(),
    }
    _resume(case_id, decision)

    conn = sqlite3.connect(config.database_path)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT * FROM agent_memory_signals WHERE entity_type='vendor' AND entity_key=?",
        (rejected_vendor_id,),
    ).fetchall()
    conn.close()
    assert rows, "a rejection with a stated reason must be written to agent_memory_signals"
    assert rows[0]["signal_type"] == "human_rejected"
    assert "late on our last three orders" in rows[0]["signal_text"]
    assert rows[0]["source_case_id"] == case_id

    # Case 2: a fresh case for the same SKU at a different warehouse. Vendor
    # offers are keyed by SKU only, so the same vendor is a candidate again.
    second = _run("AC-003", "DEL-15")
    assert "__interrupt__" in second
    graph, conn = compile_graph()
    try:
        second_case_id = second["__interrupt__"][0].value["case_id"]
        values = graph.get_state({"configurable": {"thread_id": latest_thread_id(second_case_id)}}).values
    finally:
        conn.close()

    candidate_ids = {o.vendor_id for o in values["vendor_options"].eligible_options}
    assert rejected_vendor_id in candidate_ids, "test setup: the rejected vendor must be a candidate again"

    prompt = build_user_message(values)
    assert "PRIOR CONTEXT" in prompt
    assert "late on our last three orders" in prompt
    assert rejected_vendor_id in prompt
