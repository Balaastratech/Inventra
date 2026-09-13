"""
B3 proof: a created purchase request can be withdrawn.

Before this, create_purchase_request was a one-way door -- an order raised in
error or superseded by a change of plan could only be undone by editing the
database by hand, and nothing recorded that it had happened.

These tests exercise tools.execution.cancel_purchase_request directly. It is
deliberately outside the graph (by the time an order exists the case has
reached a terminal state, so there is no checkpoint to resume), which also
means it needs no model calls and no compiled graph here.
"""

from __future__ import annotations

import sqlite3
import uuid
from datetime import datetime

import pytest

from domain.tool_models import ErrorCode, PurchaseRequestStatus
from submission.config import config
from submission.portfolio import get_purchase_request
from submission.tests.reset_db import reset_business_state
from tools.execution import cancel_purchase_request, mark_vendor_send_status


@pytest.fixture(scope="module", autouse=True)
def clean_state():
    reset_business_state()
    yield


def _insert_request(status: str = "PENDING", case_id: str | None = None) -> tuple[str, str]:
    """Write a purchase_requests row directly.

    Going straight to SQL rather than running the graph is deliberate: this
    module is testing the cancellation rules, and a real run would need a
    human-approval interrupt plus three agent calls to produce the one row
    they operate on.
    """
    request_id = f"PR-{uuid.uuid4().hex[:12].upper()}"
    case_id = case_id or f"CASE-CANCEL-{uuid.uuid4().hex[:6].upper()}"
    now = datetime.utcnow()
    conn = sqlite3.connect(config.database_path)
    conn.execute(
        """
        INSERT INTO purchase_requests (
            request_id, case_id, vendor_id, sku, warehouse_id, quantity, unit_price,
            total_cost, status, idempotency_key, approved_by, approved_at, created_at
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            request_id, case_id, "V-FAST", "AC-001", "DEL-01", 10, 250.0, 2500.0,
            status, f"idem-{request_id}", "yuvraj", now, now,
        ),
    )
    conn.commit()
    conn.close()
    return request_id, case_id


def _status_of(request_id: str) -> str:
    conn = sqlite3.connect(config.database_path)
    row = conn.execute(
        "SELECT status FROM purchase_requests WHERE request_id = ?", (request_id,)
    ).fetchone()
    conn.close()
    return row[0]


def test_cancelling_a_pending_request_records_who_why_and_when():
    request_id, case_id = _insert_request()

    result = cancel_purchase_request(request_id, "yuvraj", "raised in error, duplicate of PR-0001")

    assert result.cancelled is True
    assert result.status is PurchaseRequestStatus.CANCELLED
    assert result.case_id == case_id
    assert result.error is None

    row = get_purchase_request(case_id)
    assert row["status"] == "CANCELLED"
    assert row["cancelled_by"] == "yuvraj"
    assert row["cancel_reason"] == "raised in error, duplicate of PR-0001"
    assert row["cancelled_at"] is not None, "a cancellation with no timestamp is not auditable"


def test_cancelling_writes_an_audit_event_naming_the_human():
    request_id, case_id = _insert_request()
    cancel_purchase_request(request_id, "priya", "supplier confirmed a shortage")

    conn = sqlite3.connect(config.database_path)
    rows = conn.execute(
        "SELECT actor, event_type, payload_json FROM audit_events WHERE case_id = ?", (case_id,)
    ).fetchall()
    conn.close()

    cancels = [r for r in rows if r[1] == "purchase_request_cancelled"]
    assert len(cancels) == 1, "the cancellation must leave exactly one audit trace"
    assert cancels[0][0] == "human:priya", "a write this consequential must name its author"
    assert "shortage" in cancels[0][2]


def test_a_second_cancellation_is_refused_and_does_not_overwrite_the_first():
    request_id, case_id = _insert_request()
    cancel_purchase_request(request_id, "yuvraj", "first reason")

    second = cancel_purchase_request(request_id, "someone-else", "second reason")

    assert second.cancelled is False
    assert second.error == ErrorCode.INVALID_INPUT
    assert second.status is PurchaseRequestStatus.CANCELLED
    row = get_purchase_request(case_id)
    assert row["cancelled_by"] == "yuvraj", "the original cancellation record must survive"
    assert row["cancel_reason"] == "first reason"


@pytest.mark.parametrize("status", ["CONFIRMED", "FAILED", "REJECTED"])
def test_only_a_pending_request_can_be_cancelled(status):
    request_id, _ = _insert_request(status=status)

    result = cancel_purchase_request(request_id, "yuvraj", "changed my mind")

    assert result.cancelled is False
    assert result.error == ErrorCode.INVALID_INPUT
    assert status in (result.error_details or "")
    assert _status_of(request_id) == status, "a refused cancellation must not alter the row"


def test_cancellation_is_refused_once_the_supplier_has_been_emailed():
    """The one refusal that is about the outside world rather than our own
    state: marking it cancelled locally would leave the supplier's records
    showing a live order."""
    request_id, _ = _insert_request()
    mark_vendor_send_status(request_id, "SENT")

    result = cancel_purchase_request(request_id, "yuvraj", "no longer needed")

    assert result.cancelled is False
    assert result.error == ErrorCode.INVALID_INPUT
    assert "supplier" in (result.error_details or "").lower()
    assert _status_of(request_id) == "PENDING"


def test_a_failed_vendor_send_does_not_block_cancellation():
    """Only a *successful* send creates the mismatch risk. A FAILED attempt
    means the supplier was never told, so cancelling is still safe."""
    request_id, _ = _insert_request()
    mark_vendor_send_status(request_id, "FAILED")

    result = cancel_purchase_request(request_id, "yuvraj", "not needed after all")

    assert result.cancelled is True
    assert _status_of(request_id) == "CANCELLED"


def test_unknown_request_is_reported_not_silently_ignored():
    result = cancel_purchase_request("PR-DOESNOTEXIST", "yuvraj", "typo")

    assert result.cancelled is False
    assert result.error == ErrorCode.NOT_FOUND


@pytest.mark.parametrize(
    "who, why",
    [("", "a reason"), ("   ", "a reason"), ("yuvraj", ""), ("yuvraj", "   ")],
)
def test_a_name_and_a_reason_are_both_required(who, why):
    request_id, _ = _insert_request()

    result = cancel_purchase_request(request_id, who, why)

    assert result.cancelled is False
    assert result.error == ErrorCode.INVALID_INPUT
    assert _status_of(request_id) == "PENDING", "an invalid request must not be applied"


def test_cancelling_releases_no_budget_and_says_so():
    """Guards the honest behaviour documented in cancel_purchase_request:
    create_purchase_request never increments committed_amount, so there is
    nothing to give back. If a future change starts reserving budget on
    create, this test should fail and be updated deliberately -- not quietly
    leave the two halves inconsistent."""
    conn = sqlite3.connect(config.database_path)
    before = conn.execute(
        "SELECT committed_amount FROM monthly_budgets WHERE warehouse_id = 'DEL-01'"
    ).fetchone()[0]
    conn.close()

    request_id, case_id = _insert_request()
    cancel_purchase_request(request_id, "yuvraj", "testing budget behaviour")

    conn = sqlite3.connect(config.database_path)
    after = conn.execute(
        "SELECT committed_amount FROM monthly_budgets WHERE warehouse_id = 'DEL-01'"
    ).fetchone()[0]
    rows = conn.execute(
        "SELECT payload_json FROM audit_events WHERE case_id = ? AND event_type = ?",
        (case_id, "purchase_request_cancelled"),
    ).fetchall()
    conn.close()

    assert after == before
    assert '"budget_released": false' in rows[0][0].lower(), (
        "the audit trail must state that no budget came back, so nobody assumes it did"
    )


def test_no_agent_can_reach_the_cancellation_tool():
    """Same boundary as create_purchase_request: cancelling is a write, so it
    must not be in any agent's tool set."""
    from submission.graph import nodes

    for name, agent_fn in nodes._AGENTS.items():
        source = getattr(agent_fn, "__code__", None)
        names = set(source.co_names) if source else set()
        assert "cancel_purchase_request" not in names, f"{name} can reach the cancellation write"
