"""
Gap 8 proof: the vendor-ordering capability is fully built, but stays
disabled by default (config.vendor_email_enabled). When forced on for a
test, the outbound message contains only whitelisted, code-computed fields
-- never agent-authored text -- and a retried write can never send twice.
"""

from __future__ import annotations

import sqlite3
from dataclasses import replace
from datetime import datetime, timezone

import pytest
from langgraph.types import Command

from domain.tool_models import ProposalStatus
from submission.config import config
from submission.graph.workflow import compile_graph, latest_thread_id
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


def _approve(case_id, payload):
    decision = {
        "case_id": case_id,
        "proposal_id": payload["proposal_id"],
        "proposal_hash": payload["proposal_hash"],
        "decision": "APPROVED",
        "approver": "tester",
        "comments": None,
        "approved_at": datetime.now(timezone.utc).isoformat(),
    }
    return _resume(case_id, decision)


def test_vendor_send_not_even_attempted_while_flag_is_off(monkeypatch):
    import submission.graph.nodes as nodes_module

    assert config.vendor_email_enabled is False, "test relies on the real default"
    calls = []
    monkeypatch.setattr(nodes_module, "send_purchase_order", lambda *a, **k: calls.append((a, k)) or True)

    result = _run("AC-003", "DEL-16")
    assert "__interrupt__" in result
    payload = result["__interrupt__"][0].value
    final = _approve(payload["case_id"], payload)

    assert final["status"] == ProposalStatus.PURCHASE_REQUEST_CREATED
    assert calls == [], "vendor send must not even be attempted while the flag is off"


def test_vendor_send_when_enabled_uses_only_whitelisted_fields_and_is_idempotent(monkeypatch):
    import submission.graph.nodes as nodes_module
    import submission.notifications.vendor_email as vendor_email_module

    patched = replace(config, vendor_email_enabled=True)
    monkeypatch.setattr(nodes_module, "config", patched)
    monkeypatch.setattr(vendor_email_module, "config", patched)

    result = _run("AC-003", "DEL-17")
    assert "__interrupt__" in result
    payload = result["__interrupt__"][0].value
    case_id = payload["case_id"]

    graph, conn = compile_graph()
    try:
        proposal = graph.get_state({"configurable": {"thread_id": latest_thread_id(case_id)}}).values["proposal"]
    finally:
        conn.close()

    conn = sqlite3.connect(config.database_path)
    conn.execute(
        "UPDATE vendors SET contact_email = ? WHERE vendor_id = ?",
        ("vendor@example.com", proposal.recommended_vendor_id),
    )
    conn.commit()
    conn.close()

    sent = []
    monkeypatch.setattr(
        vendor_email_module,
        "_send_vendor_email",
        lambda to_address, subject, body: sent.append((to_address, subject, body)) or True,
    )

    final = _approve(case_id, payload)
    assert final["status"] == ProposalStatus.PURCHASE_REQUEST_CREATED
    assert len(sent) == 1, f"expected exactly one vendor send, got {sent}"

    to_address, subject, body = sent[0]
    assert to_address == "vendor@example.com"
    # Whitelisted fields only -- no agent-authored text could ever appear
    # here even if it were injected upstream.
    assert str(proposal.quantity) in body
    assert str(proposal.unit_price) in body
    assert "rationale" not in body.lower()
    if proposal.cost_vs_speed_trade_off:
        assert proposal.cost_vs_speed_trade_off not in body

    # Idempotency: a retried write with the same idempotency key must never
    # trigger a second vendor send.
    from tools.execution import create_purchase_request
    from submission.notifications.vendor_email import send_purchase_order

    dup = create_purchase_request(proposal, final["idempotency_key"], "tester")
    assert dup.created is False
    send_purchase_order(proposal, dup)
    assert len(sent) == 1, "a retried write must never trigger a second vendor send"
