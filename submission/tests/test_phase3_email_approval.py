"""
D11 proof: the reply/link-based approval actually works end to end --
GET renders a confirm page without deciding anything, POST executes the
decision exactly once, a replayed POST is rejected. Uses FastAPI's
TestClient (bundled with FastAPI, no server process needed) against the
same compiled graph + checkpointer the CLI uses.
"""

from __future__ import annotations

import os
from dataclasses import replace

import pytest
from fastapi.testclient import TestClient

from domain.tool_models import ProposalStatus
from submission.config import config
from submission.graph.workflow import compile_graph, latest_thread_id
from submission.portfolio import read_case_history
from submission.state.state import create_initial_state
from submission.tests.reset_db import reset_business_state


@pytest.fixture(scope="module", autouse=True)
def clean_state():
    # Full reset: this module's end-to-end test writes a real
    # purchase_requests row, whose idempotency key is deterministic, so
    # without a reseed it only asserts created=True on the first ever run.
    reset_business_state()
    yield


@pytest.fixture(autouse=True)
def no_agent_wiring(monkeypatch):
    """This test is about the token/approval-server mechanics, not agent
    judgment -- it doesn't care whether stub or real agents are behind the
    graph. approval_server.execute() calls wire_agents() on every POST,
    though, and that flips a process-wide flag: once it fires for real
    (this environment has Vertex configured), every OTHER test in the
    session that shares this process would start hitting a live LLM
    instead of the fast, deterministic Phase 2/3 stubs. Stub it out here so
    this test file can't change behavior for tests that run after it."""
    import submission.graph.approval_server as approval_server_module

    monkeypatch.setattr(approval_server_module, "wire_agents", lambda: None)


@pytest.fixture()
def token_secret(monkeypatch):
    import submission.notifications.tokens as tokens_module

    monkeypatch.setattr(tokens_module, "config", replace(config, approval_token_secret="test-only-secret"))
    return tokens_module


def test_email_approval_link_end_to_end(token_secret):
    from submission.graph.approval_server import app

    graph, conn = compile_graph()
    try:
        state = create_initial_state("AC-003", "DEL-05")
        result = graph.invoke(state, config={"configurable": {"thread_id": state["thread_id"]}})
    finally:
        conn.close()

    assert "__interrupt__" in result
    payload = result["__interrupt__"][0].value
    case_id = payload["case_id"]

    token = token_secret.make_token(case_id, payload["proposal_hash"], "APPROVED", "tester@example.com")
    client = TestClient(app)

    get_resp = client.get("/decide", params={"token": token})
    assert get_resp.status_code == 200
    assert "Confirm" in get_resp.text
    assert "APPROVED" in get_resp.text

    graph, conn = compile_graph()
    try:
        mid_snapshot = graph.get_state({"configurable": {"thread_id": latest_thread_id(case_id)}})
        assert mid_snapshot.next, "GET must never decide anything -- case should still be paused"
    finally:
        conn.close()

    post_resp = client.post("/decide", data={"token": token})
    assert post_resp.status_code == 200
    assert "Recorded" in post_resp.text

    replay_resp = client.post("/decide", data={"token": token})
    assert "Already decided" in replay_resp.text

    graph, conn = compile_graph()
    try:
        final_snapshot = graph.get_state({"configurable": {"thread_id": latest_thread_id(case_id)}})
        assert final_snapshot.values["status"] == ProposalStatus.PURCHASE_REQUEST_CREATED
        assert final_snapshot.values["purchase_result"].created is True
    finally:
        conn.close()


def test_revise_from_email_round_trip_carries_the_submitted_comment(token_secret):
    """Gap 7: the email must offer REVISE, not just APPROVE/REJECT, and the
    approver's typed comment must reach the graph -- not the old hardcoded
    "via email link" placeholder, which would leave the revision with no
    actual instruction to act on."""
    from submission.graph.approval_server import app

    graph, conn = compile_graph()
    try:
        state = create_initial_state("AC-003", "DEL-13")
        result = graph.invoke(state, config={"configurable": {"thread_id": state["thread_id"]}})
    finally:
        conn.close()

    assert "__interrupt__" in result
    payload = result["__interrupt__"][0].value
    case_id = payload["case_id"]

    token = token_secret.make_token(case_id, payload["proposal_hash"], "REVISE", "tester@example.com")
    client = TestClient(app)

    get_resp = client.get("/decide", params={"token": token})
    assert get_resp.status_code == 200
    assert "textarea" in get_resp.text
    assert "Request changes" in get_resp.text

    post_resp = client.post("/decide", data={"token": token, "comments": "prefer the cheaper supplier"})
    assert post_resp.status_code == 200
    assert "Recorded" in post_resp.text

    graph, conn = compile_graph()
    try:
        final_snapshot = graph.get_state({"configurable": {"thread_id": latest_thread_id(case_id)}})
    finally:
        conn.close()

    events = [
        e for e in read_case_history(case_id)
        if e.raw.get("approver_comment") == "prefer the cheaper supplier"
    ]
    assert events, "the approver's typed comment from the email form must reach the audit trail"


def test_malformed_token_rejected(token_secret):
    from submission.graph.approval_server import app

    client = TestClient(app)
    resp = client.get("/decide", params={"token": "not-a-real-token"})
    assert resp.status_code == 200
    assert "invalid" in resp.text.lower()
