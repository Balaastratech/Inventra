"""
Gap 2 proof: NO_ACTION, NEEDS_INFORMATION (once the resume loop truly
gives up) and BLOCKED (no eligible vendors) all actively notify, and the
BLOCKED case includes a per-vendor breakdown instead of one flat sentence.

send_email is monkeypatched at the module level (same technique as
test_phase3_email_approval.py's token-secret fixture) so no real SMTP call
is made; config.email_enabled is flipped the same way, since it is a frozen
dataclass.
"""

from __future__ import annotations

from dataclasses import replace

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


@pytest.fixture()
def sent_emails(monkeypatch):
    import submission.notifications.email as email_module

    monkeypatch.setattr(email_module, "config", replace(config, email_enabled=True))
    calls: list[tuple[str, str]] = []
    monkeypatch.setattr(email_module, "send_email", lambda subject, body: calls.append((subject, body)) or True)
    return calls


def _run(sku, warehouse_id, target_cover_days=None):
    graph, conn = compile_graph()
    try:
        state = create_initial_state(sku, warehouse_id, target_cover_days)
        return graph.invoke(state, config={"configurable": {"thread_id": state["thread_id"]}})
    finally:
        conn.close()


def _resume(case_id, resume_payload):
    graph, conn = compile_graph()
    try:
        thread = latest_thread_id(case_id)
        return graph.invoke(Command(resume=resume_payload), config={"configurable": {"thread_id": thread}})
    finally:
        conn.close()


def test_send_email_failure_does_not_crash_the_case(monkeypatch):
    """A live run hit Gmail's daily sending limit (SMTPDataError 550) mid-
    case; because send_email() let the exception propagate, it crashed the
    entire graph.invoke() -- a BLOCKED case never finished because its own
    notification failed to send. Notifications are fire-and-forget and must
    never take the case down with them (same discipline as emit_audit)."""
    import smtplib

    import submission.notifications.email as email_module

    monkeypatch.setattr(email_module, "config", replace(config, email_enabled=True))

    def _boom(*args, **kwargs):
        raise smtplib.SMTPDataError(550, b"5.4.5 Daily user sending limit exceeded")

    monkeypatch.setattr(email_module.smtplib, "SMTP", _boom)

    # Must not raise -- this is the whole point of the fix.
    result = email_module.send_email("subject", "<p>body</p>")
    assert result is False


def test_healthy_monitor_result_is_recorded_but_never_emails(sent_emails):
    result = _run("AC-001", "DEL-01", target_cover_days=7)  # healthy at a 7d target
    assert result["status"] == ProposalStatus.NO_ACTION

    matching = [c for c in sent_emails if "No order needed" in c[0]]
    assert not matching, f"healthy monitor results must be silent, got {sent_emails}"


def test_notify_needs_information_fires_once_when_retries_exhausted(sent_emails):
    result = _run("AC-003", "DEL-10", target_cover_days=999)
    assert "__interrupt__" in result
    case_id = result["__interrupt__"][0].value["case_id"]

    final = None
    for _ in range(config.max_info_retries):
        final = _resume(case_id, {"target_cover_days": 999})
        if "__interrupt__" not in final:
            break

    assert "__interrupt__" not in final
    assert final["status"] == ProposalStatus.NEEDS_INFORMATION

    matching = [c for c in sent_emails if "More information needed" in c[0]]
    assert len(matching) == 1, f"expected exactly one NEEDS_INFORMATION email, got {sent_emails}"


def test_notify_blocked_explains_revalidation_failure_to_the_approver(sent_emails):
    import sqlite3
    from datetime import datetime, timezone

    result = _run("AC-003", "DEL-02")
    assert "__interrupt__" in result
    payload = result["__interrupt__"][0].value
    case_id = payload["case_id"]

    conn = sqlite3.connect(config.database_path)
    conn.execute("UPDATE monthly_budgets SET spent_amount = budget_amount WHERE warehouse_id = 'DEL-02'")
    conn.commit()
    conn.close()

    decision = {
        "case_id": case_id,
        "proposal_id": payload["proposal_id"],
        "proposal_hash": payload["proposal_hash"],
        "decision": "APPROVED",
        "approver": "tester",
        "comments": None,
        "approved_at": datetime.now(timezone.utc).isoformat(),
    }
    final = _resume(case_id, decision)
    assert final["status"] == ProposalStatus.BLOCKED

    matching = [c for c in sent_emails if "Blocked" in c[0]]
    assert matching, f"expected a BLOCKED email, got {sent_emails}"
    body = matching[-1][1]
    assert "Your approval could not be honored" in body


def test_notify_blocked_reports_per_vendor_reasons_not_flat_sentence(sent_emails):
    result = _run("AC-006", "DEL-01")  # only unreliable/expired vendors
    assert result["status"] == ProposalStatus.BLOCKED
    assert result["vendor_options"].eligible_options == []

    matching = [c for c in sent_emails if "Blocked" in c[0]]
    assert len(matching) == 1, f"expected exactly one BLOCKED email, got {sent_emails}"
    _, body = matching[0]
    # Per-vendor breakdown, not the old flat sentence alone.
    assert "<table" in body
    assert any(v in body for v in ("SlowShip", "Shady Vendor"))
    assert "reliability" in body.lower() or "deadline" in body.lower()
