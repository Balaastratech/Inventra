"""Focused Phase D proof: a second human gate protects vendor sends."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from langgraph.types import Command
from pydantic import ValidationError

from domain.tool_models import ApprovalDecision, ProposalStatus, VendorSendDecision
from submission.config import config
from submission.graph.workflow import compile_graph, latest_thread_id
from submission.state.state import create_initial_state
from submission.tests.reset_db import reset_business_state
from tools.execution import get_vendor_send_status


@pytest.fixture(scope="module", autouse=True)
def clean_state():
    reset_business_state()


@pytest.fixture(autouse=True)
def vendor_gate_enabled(monkeypatch):
    enabled = replace(config, vendor_email_enabled=True, email_enabled=False)
    monkeypatch.setattr("submission.config.config", enabled)
    monkeypatch.setattr("submission.graph.nodes.config", enabled)
    monkeypatch.setattr("submission.notifications.email.config", enabled)
    yield


def _approve_gate_one(graph, state):
    first = graph.invoke(state, config={"configurable": {"thread_id": state["thread_id"]}})
    payload = first["__interrupt__"][0].value
    return graph.invoke(Command(resume={
        "case_id": payload["case_id"], "proposal_id": payload["proposal_id"],
        "proposal_hash": payload["proposal_hash"], "decision": "APPROVED", "approver": "tester",
        "comments": None, "approved_at": datetime.now(timezone.utc).isoformat(),
    }), config={"configurable": {"thread_id": state["thread_id"]}})


def test_gate_one_rejection_requires_reason():
    with pytest.raises(ValidationError, match="requires a reason"):
        ApprovalDecision(case_id="C", proposal_id="P", proposal_hash="H", decision="REJECTED", approver="tester", approved_at=datetime.now(timezone.utc))


def test_vendor_rejection_requires_reason():
    with pytest.raises(ValidationError, match="requires a reason"):
        VendorSendDecision(request_id="PR-1", case_id="C", decision="REJECTED", approver="tester", approved_at=datetime.now(timezone.utc))


def test_gate_two_pauses_before_vendor_send_and_rejection_cancels_request():
    graph, conn = compile_graph()
    try:
        state = create_initial_state("AC-003", "DEL-01")
        gate_two = _approve_gate_one(graph, state)
        assert "__interrupt__" in gate_two
        payload = gate_two["__interrupt__"][0].value
        assert payload["kind"] == "vendor_send_approval"
        request_id = payload["request_id"]
        assert get_vendor_send_status(request_id) == (None, None)

        final = graph.invoke(Command(resume={
            "request_id": request_id, "case_id": payload["case_id"], "decision": "REJECTED",
            "approver": "tester", "reason": "Supplier is no longer approved", "approved_at": datetime.now(timezone.utc).isoformat(),
        }), config={"configurable": {"thread_id": state["thread_id"]}})
        assert final["status"] == ProposalStatus.PURCHASE_REQUEST_CANCELLED
    finally:
        conn.close()


def test_vendor_email_disabled_preserves_single_gate_flow(monkeypatch):
    disabled = replace(config, vendor_email_enabled=False, email_enabled=False)
    monkeypatch.setattr("submission.config.config", disabled)
    monkeypatch.setattr("submission.graph.nodes.config", disabled)
    from submission.graph.routes import route_after_execution
    assert route_after_execution({"purchase_result": SimpleNamespace(error=None)}) == "success"
