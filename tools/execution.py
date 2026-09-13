"""
Execution Tools
Revalidation and write operations.

CRITICAL: These tools can only be called by deterministic (non-LLM) nodes.
No LLM agent may call create_purchase_request.
"""

import sqlite3
import hashlib
from datetime import datetime
from typing import Optional
import uuid
from domain.tool_models import (
    ReplenishmentProposal,
    RevalidationResult,
    PurchaseRequestResult,
    PurchaseRequestStatus,
    AuditEventResult,
    CancellationResult,
    ErrorCode,
)


def _get_db_connection(db_path: str | None = None):
    """Get database connection."""
    if db_path is None:
        from submission.config import config
        db_path = config.database_path
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def _hash_proposal(proposal: ReplenishmentProposal) -> str:
    """
    Create SHA256 hash of proposal for integrity checking.
    
    Includes all critical fields but not timestamps/IDs.
    """
    key_parts = [
        str(proposal.sku),
        str(proposal.warehouse_id),
        str(proposal.quantity),
        str(proposal.unit_price),
        str(proposal.recommended_vendor_id),
        str(proposal.target_cover_days),
    ]
    key_string = "|".join(key_parts)
    return hashlib.sha256(key_string.encode()).hexdigest()


def revalidate_approved_proposal(
    proposal_id: str,
    proposal_hash: str,
) -> RevalidationResult:
    """
    Revalidate an approved proposal before purchase request creation.
    
    Checks:
    1. Proposal hash matches (proposal not modified)
    2. Stock snapshot is still current (< 2 days old)
    3. Vendor offer is still active and valid
    4. Budget is still sufficient
    
    This is a system tool, NOT callable by LLM agents.
    Called only by deterministic post-approval node.
    
    Returns all_checks_pass=True only if ALL revalidations pass.
    If any check fails, approval is invalidated and write is blocked.
    """
    
    # TODO: In real implementation, would retrieve stored proposal from case state
    # and re-validate against current database state
    
    return RevalidationResult(
        proposal_id=proposal_id,
        proposal_hash=proposal_hash,
        hash_matches=True,  # Simplified for starter
        stock_valid=True,
        offer_valid=True,
        budget_valid=True,
        all_checks_pass=True,
        error_details=None,
    )


def create_purchase_request(
    proposal: ReplenishmentProposal,
    idempotency_key: str,
    approved_by: str,
) -> PurchaseRequestResult:
    """
    Create a purchase request in the database.
    
    CRITICAL: This is a write operation. Must be called ONLY after:
    1. Human approval from a named approver
    2. Successful revalidation of all facts
    3. Idempotency key to prevent duplicates
    
    This tool is NEVER available to LLM agents.
    
    Returns:
        - request_id: New or existing request ID
        - created: True if newly created, False if idempotent return
        - If idempotency_key already exists, returns existing request
        - Unique database constraint prevents duplicate writes
    """
    try:
        conn = _get_db_connection()
        cursor = conn.cursor()
        
        # Check if this idempotency_key already exists
        cursor.execute(
            "SELECT request_id, status FROM purchase_requests WHERE idempotency_key = ?",
            (idempotency_key,)
        )
        existing = cursor.fetchone()
        
        if existing:
            # Idempotent return: same request already exists
            conn.close()
            return PurchaseRequestResult(
                request_id=existing["request_id"],
                case_id=proposal.case_id,
                status=PurchaseRequestStatus(existing["status"]),
                created=False,
                total_cost=proposal.total_cost,
            )
        
        # Create new purchase request
        request_id = f"PR-{uuid.uuid4().hex[:12].upper()}"
        now = datetime.utcnow()
        # budget_evidence_id is "budget:{warehouse_id}:{month}" (tools/policy.py
        # get_budget_position) -- reuse it instead of adding a redundant field.
        budget_month = proposal.budget_evidence_id.rsplit(":", 1)[-1]

        cursor.execute(
            """
            INSERT INTO purchase_requests (
                request_id, case_id, vendor_id, sku, warehouse_id,
                quantity, unit_price, total_cost, status, idempotency_key,
                approved_by, approved_at, committed_budget_month, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                request_id,
                proposal.case_id,
                proposal.recommended_vendor_id,
                proposal.sku,
                proposal.warehouse_id,
                proposal.quantity,
                proposal.unit_price,
                proposal.total_cost,
                PurchaseRequestStatus.PENDING,
                idempotency_key,
                approved_by,
                now,
                budget_month,
                now,
            )
        )
        # Reserve the spend against the month it was approved for. Without
        # this, get_budget_position's `remaining` never reflects an approved,
        # unspent order, so a second case in the same month gets judged
        # affordable against money that is already committed.
        cursor.execute(
            """
            UPDATE monthly_budgets SET committed_amount = committed_amount + ?
            WHERE warehouse_id = ? AND month = ?
            """,
            (proposal.total_cost, proposal.warehouse_id, budget_month),
        )
        conn.commit()
        conn.close()
        
        return PurchaseRequestResult(
            request_id=request_id,
            case_id=proposal.case_id,
            status=PurchaseRequestStatus.PENDING,
            created=True,
            total_cost=proposal.total_cost,
        )
    except sqlite3.IntegrityError as e:
        # Constraint violation (likely duplicate idempotency_key)
        # This should not happen if revalidation passed, but handle it safely
        return PurchaseRequestResult(
            request_id="",
            case_id=proposal.case_id,
            status=PurchaseRequestStatus.FAILED,
            created=False,
            total_cost=0,
            error=ErrorCode.WRITE_FAILED,
            error_details=f"Database constraint violation: {str(e)}",
        )
    except Exception as e:
        return PurchaseRequestResult(
            request_id="",
            case_id=proposal.case_id,
            status=PurchaseRequestStatus.FAILED,
            created=False,
            total_cost=0,
            error=ErrorCode.UNKNOWN_ERROR,
            error_details=str(e),
        )


def get_open_order_quantity(sku: str, warehouse_id: str) -> int:
    """Units already on order (PENDING) for this sku/warehouse, not yet
    cancelled or failed. `confirmed_inbound` on the inventory snapshot is
    never written by this system (only seed data sets it, always to 0), so
    a re-run of the same case sees unchanged stock and proposes a second
    order for units already in flight. Folding this into compute_risk's
    available_units is the guard until a real supplier-confirmation path
    exists to write confirmed_inbound instead (see CONFIRMED-unreachable
    gap in GAP_NEEDS_INFORMATION.md -- out of scope here)."""
    conn = _get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT COALESCE(SUM(quantity), 0) FROM purchase_requests
        WHERE sku = ? AND warehouse_id = ? AND status = ?
        """,
        (sku, warehouse_id, PurchaseRequestStatus.PENDING.value),
    )
    total = cursor.fetchone()[0]
    conn.close()
    return int(total)


def get_vendor_send_status(request_id: str) -> tuple[Optional[str], Optional[str]]:
    """(vendor_sent_at, vendor_send_status) for a purchase request, or
    (None, None) if not found / never attempted. Used only for the Gap 8
    idempotency check in submission/notifications/vendor_email.py."""
    conn = _get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT vendor_sent_at, vendor_send_status FROM purchase_requests WHERE request_id = ?",
        (request_id,),
    )
    row = cursor.fetchone()
    conn.close()
    if not row:
        return None, None
    return row["vendor_sent_at"], row["vendor_send_status"]


def mark_vendor_send_status(request_id: str, status: str) -> None:
    """Records that a vendor PO send was attempted (Gap 8). Called only from
    submission/notifications/vendor_email.py, immediately after the send
    attempt, so a retried execute_purchase or a re-approval can never
    double-send."""
    conn = _get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "UPDATE purchase_requests SET vendor_sent_at = ?, vendor_send_status = ? WHERE request_id = ?",
        (datetime.utcnow(), status, request_id),
    )
    conn.commit()
    conn.close()


def mark_vendor_reminder_sent(request_id: str) -> int:
    """Increment the Gate-2 reminder count and return its new value."""
    conn = _get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE purchase_requests SET vendor_reminder_count = COALESCE(vendor_reminder_count, 0) + 1, vendor_last_reminded_at = ? WHERE request_id = ?",
            (datetime.utcnow(), request_id),
        )
        conn.commit()
        row = cursor.execute("SELECT vendor_reminder_count FROM purchase_requests WHERE request_id = ?", (request_id,)).fetchone()
        return int(row[0]) if row else 0
    finally:
        conn.close()


def cancel_purchase_request(
    request_id: str,
    cancelled_by: str,
    reason: str,
) -> CancellationResult:
    """Withdraw a PENDING purchase request (B3).

    Until this existed, creating a purchase request was irreversible: an
    order placed by mistake, or superseded by a change of plan, could only
    be corrected by editing the database by hand.

    This is a write operation and is deliberately NOT reachable by any LLM
    agent -- same boundary as create_purchase_request. It is called only from
    operator-facing entry points (the Streamlit case screen and the CLI),
    each of which requires a named human and a stated reason.

    Refuses, rather than forcing, in three cases:

      * the request does not exist;
      * it is not PENDING -- a CONFIRMED, FAILED, REJECTED or already
        CANCELLED request is not something a cancellation can meaningfully
        act on, and silently overwriting one of those would destroy the
        record of what actually happened;
      * the supplier has already been emailed the PO
        (vendor_send_status = 'SENT'). Marking it cancelled locally while the
        supplier still believes the order is live would make our record and
        theirs disagree, which is worse than refusing. Retracting a sent PO
        is an outbound commercial action and needs its own flow.

    Note on budget: releases the reservation create_purchase_request made,
    against the same committed_budget_month it reserved against -- not
    "whatever month it happens to be now" -- so a request approved near a
    month boundary and cancelled after it rolls over still credits the
    right month. A row with no committed_budget_month (e.g. written before
    this column existed) releases nothing, since nothing was reserved for it.
    """
    if not (cancelled_by or "").strip():
        return CancellationResult(
            request_id=request_id,
            cancelled=False,
            error=ErrorCode.INVALID_INPUT,
            error_details="A named person is required to cancel an order.",
        )
    if not (reason or "").strip():
        return CancellationResult(
            request_id=request_id,
            cancelled=False,
            error=ErrorCode.INVALID_INPUT,
            error_details="A reason is required to cancel an order.",
        )

    try:
        conn = _get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT case_id, status, vendor_send_status, total_cost, warehouse_id, committed_budget_month
            FROM purchase_requests WHERE request_id = ?
            """,
            (request_id,),
        )
        row = cursor.fetchone()

        if row is None:
            conn.close()
            return CancellationResult(
                request_id=request_id,
                cancelled=False,
                error=ErrorCode.NOT_FOUND,
                error_details=f"No purchase request found with id {request_id}.",
            )

        case_id = row["case_id"]
        current_status = PurchaseRequestStatus(row["status"])

        if current_status is not PurchaseRequestStatus.PENDING:
            conn.close()
            return CancellationResult(
                request_id=request_id,
                case_id=case_id,
                cancelled=False,
                status=current_status,
                error=ErrorCode.INVALID_INPUT,
                error_details=(
                    f"Only a PENDING request can be cancelled; this one is {current_status.value}."
                ),
            )

        if row["vendor_send_status"] == "SENT":
            conn.close()
            return CancellationResult(
                request_id=request_id,
                case_id=case_id,
                cancelled=False,
                status=current_status,
                error=ErrorCode.INVALID_INPUT,
                error_details=(
                    "The purchase order has already been sent to the supplier. Cancelling only "
                    "our copy would leave their records showing a live order. Contact the "
                    "supplier to retract it first."
                ),
            )

        now = datetime.utcnow()
        # Guarded UPDATE: the status check is repeated in SQL so two
        # concurrent cancellations cannot both report success.
        cursor.execute(
            """
            UPDATE purchase_requests
            SET status = ?, cancelled_at = ?, cancelled_by = ?, cancel_reason = ?
            WHERE request_id = ? AND status = ?
            """,
            (
                PurchaseRequestStatus.CANCELLED.value,
                now,
                cancelled_by.strip(),
                reason.strip(),
                request_id,
                PurchaseRequestStatus.PENDING.value,
            ),
        )
        changed = cursor.rowcount

        budget_released = False
        if changed and row["committed_budget_month"]:
            cursor.execute(
                """
                UPDATE monthly_budgets SET committed_amount = MAX(0, committed_amount - ?)
                WHERE warehouse_id = ? AND month = ?
                """,
                (row["total_cost"], row["warehouse_id"], row["committed_budget_month"]),
            )
            budget_released = True

        conn.commit()
        conn.close()

        if changed == 0:
            return CancellationResult(
                request_id=request_id,
                case_id=case_id,
                cancelled=False,
                status=PurchaseRequestStatus.PENDING,
                error=ErrorCode.INVALID_INPUT,
                error_details="The request changed status while the cancellation was being applied.",
            )

        append_audit_event(
            case_id=case_id,
            trace_id=request_id,
            actor=f"human:{cancelled_by.strip()}",
            event_type="purchase_request_cancelled",
            payload={
                "request_id": request_id,
                "reason": reason.strip()[:500],
                "total_cost": row["total_cost"],
                "budget_released": budget_released,
            },
        )
        return CancellationResult(
            request_id=request_id,
            case_id=case_id,
            cancelled=True,
            status=PurchaseRequestStatus.CANCELLED,
            budget_released=budget_released,
        )
    except Exception as e:
        return CancellationResult(
            request_id=request_id,
            cancelled=False,
            error=ErrorCode.UNKNOWN_ERROR,
            error_details=str(e),
        )


def append_audit_event(
    case_id: str,
    trace_id: str,
    actor: str,  # "system", "agent:*", "human:*"
    event_type: str,  # "risk_assessed", "approved", etc.
    payload: dict,  # JSON-serializable event details
) -> AuditEventResult:
    """
    Append an audit event to the audit trail.
    
    Called by orchestration code only; never exposed as open-ended tool to LLMs.
    Captures structured summaries, NOT private reasoning or chain-of-thought.
    
    Args:
        case_id: Case identifier
        trace_id: Request trace ID (for correlation)
        actor: Who/what created the event
        event_type: Type of event
        payload: Structured event data (JSON)
    
    Returns:
        AuditEventResult with event_id and status
    """
    try:
        import json
        
        conn = _get_db_connection()
        cursor = conn.cursor()
        
        event_id = f"EVT-{uuid.uuid4().hex[:12].upper()}"
        now = datetime.utcnow()
        payload_json = json.dumps(payload)
        
        cursor.execute(
            """
            INSERT INTO audit_events (
                event_id, case_id, trace_id, actor, event_type, 
                payload_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                event_id,
                case_id,
                trace_id,
                actor,
                event_type,
                payload_json,
                now,
            )
        )
        conn.commit()
        conn.close()
        
        return AuditEventResult(
            event_id=event_id,
            case_id=case_id,
            created=True,
        )
    except Exception as e:
        return AuditEventResult(
            event_id="",
            case_id=case_id,
            created=False,
            error=ErrorCode.WRITE_FAILED,
        )
