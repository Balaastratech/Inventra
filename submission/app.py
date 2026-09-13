"""
CLI entry point. Minimal on purpose (Phase 6 adds the Streamlit approval
screen on top of the same functions) -- the brief explicitly does not
reward a large dashboard, and this needs to demonstrably work before it
needs to look like anything.

Usage:
    python -m submission.app run AC-001 DEL-01
    python -m submission.app resume CASE-AC-001-DEL-01 APPROVED "Yuvraj" ["comment"]
    python -m submission.app resume CASE-AC-001-DEL-01 REJECTED "Yuvraj" ["comment"]
    python -m submission.app resume CASE-AC-001-DEL-01 REVISE   "Yuvraj" "go with the cheaper one"
    python -m submission.app edit   CASE-AC-001-DEL-01 OFFER-001-2 "Yuvraj" "earlier arrival is worth the premium"
    python -m submission.app resume-info CASE-AC-001-DEL-01 AC-001 DEL-01
    python -m submission.app resume-manual-cover CASE-AC-001-DEL-01 14 "Yuvraj"
    python -m submission.app pending
    python -m submission.app sweep [warehouse_id]
    python -m submission.app cancel PR-XXXXXXXXXXXX "your name" "why you are cancelling"

The operator-facing screen is `streamlit run submission/ui.py`, which calls
the same run_case / resume_case / load_case functions below -- so the CLI
and the UI can never drift into behaving differently.
"""

from __future__ import annotations

import sys
from datetime import datetime, timezone

from langgraph.types import Command

from domain.tool_models import ProposalStatus
from submission.graph.workflow import compile_graph, latest_thread_id
from submission.agents.wiring import wire_agents
from submission.state.state import create_initial_state


def run_case(sku: str, warehouse_id: str) -> dict:
    wire_agents()
    graph, conn = compile_graph()
    try:
        state = create_initial_state(sku, warehouse_id)
        thread_config = {"configurable": {"thread_id": state["thread_id"]}}
        result = graph.invoke(state, config=thread_config)
        return result
    finally:
        conn.close()


def resume_case(
    case_id: str,
    decision: str,
    approver: str,
    comments: str | None = None,
    thread_id: str | None = None,
    edited_offer_id: str | None = None,
    chosen_target_basis: str | None = None,
) -> dict:
    """Apply a human decision to a paused case.

    Callers pass the business `case_id`; the checkpointer is keyed by per-run
    `thread_id`, so the latest run is resolved unless one is given explicitly
    (the UI passes the exact thread it displayed, which avoids acting on a
    newer run someone else started while the page was open).
    """
    if edited_offer_id is not None and not (comments or "").strip():
        raise ValueError("Choosing a supplier requires a recorded reason.")
    wire_agents()
    graph, conn = compile_graph()
    try:
        thread = thread_id or latest_thread_id(case_id)
        if thread is None:
            raise RuntimeError(f"Case {case_id} has never been run (no checkpoint to resume).")
        thread_config = {"configurable": {"thread_id": thread}}
        snapshot = graph.get_state(thread_config)
        if not snapshot.next:
            raise RuntimeError(f"Case {case_id} is not paused for approval (nothing to resume).")
        proposal = snapshot.values["proposal"]
        decision_payload = {
            "case_id": case_id,
            "proposal_id": proposal.proposal_id,
            "proposal_hash": proposal.proposal_hash,
            "decision": decision,
            "approver": approver,
            "comments": comments,
            "approved_at": datetime.now(timezone.utc).isoformat(),
            # Only meaningful for decision="EDIT"; nodes.apply_human_edit
            # validates it against this case's eligible options.
            "edited_offer_id": edited_offer_id,
            "chosen_target_basis": chosen_target_basis,
        }
        result = graph.invoke(Command(resume=decision_payload), config=thread_config)
        return result
    finally:
        conn.close()


def resume_vendor_send(
    case_id: str, decision: str, approver: str, reason: str | None = None, thread_id: str | None = None,
) -> dict:
    """Apply the separate Gate-2 decision to an awaiting purchase request."""
    wire_agents()
    graph, conn = compile_graph()
    try:
        thread = thread_id or latest_thread_id(case_id)
        if thread is None:
            raise RuntimeError(f"Case {case_id} has never been run (no checkpoint to resume).")
        thread_config = {"configurable": {"thread_id": thread}}
        snapshot = graph.get_state(thread_config)
        if not snapshot.next or snapshot.values.get("status") != ProposalStatus.AWAITING_VENDOR_APPROVAL:
            raise RuntimeError(f"Case {case_id} is not paused for vendor-send approval.")
        purchase_result = snapshot.values["purchase_result"]
        return graph.invoke(Command(resume={
            "request_id": purchase_result.request_id, "case_id": case_id, "decision": decision,
            "approver": approver, "reason": reason, "approved_at": datetime.now(timezone.utc).isoformat(),
        }), config=thread_config)
    finally:
        conn.close()


def resume_missing_info(
    case_id: str,
    sku: str | None = None,
    warehouse_id: str | None = None,
    thread_id: str | None = None,
) -> dict:
    """Apply corrected input to a case paused for NEEDS_INFORMATION (Gap 1).

    Sibling to resume_case rather than an overload of it: resume_case is
    typed around ApprovalDecision and this pause carries raw corrected
    fields instead. Any field left None keeps its current value -- a caller
    only has to supply what was actually wrong.
    """
    wire_agents()
    graph, conn = compile_graph()
    try:
        thread = thread_id or latest_thread_id(case_id)
        if thread is None:
            raise RuntimeError(f"Case {case_id} has never been run (no checkpoint to resume).")
        thread_config = {"configurable": {"thread_id": thread}}
        snapshot = graph.get_state(thread_config)
        if not snapshot.next:
            raise RuntimeError(f"Case {case_id} is not paused for missing information (nothing to resume).")
        resume_payload = {"sku": sku, "warehouse_id": warehouse_id}
        result = graph.invoke(Command(resume=resume_payload), config=thread_config)
        return result
    finally:
        conn.close()


def resume_manual_cover(
    case_id: str,
    target_cover_days: int,
    requested_by: str,
    thread_id: str | None = None,
) -> dict:
    """Resume only the evidence-backed immature-maturity cover-days pause."""
    wire_agents()
    graph, conn = compile_graph()
    try:
        thread = thread_id or latest_thread_id(case_id)
        if thread is None:
            raise RuntimeError(f"Case {case_id} has never been run (no checkpoint to resume).")
        snapshot = graph.get_state({"configurable": {"thread_id": thread}})
        if not snapshot.next:
            raise RuntimeError(f"Case {case_id} is not paused for manual cover days.")
        return graph.invoke(
            Command(resume={"target_cover_days": target_cover_days, "requested_by": requested_by}),
            config={"configurable": {"thread_id": thread}},
        )
    finally:
        conn.close()


def load_case(case_id: str, thread_id: str | None = None) -> tuple[dict, bool]:
    """Read a case's current state straight from the checkpoint.

    Returns (state_values, is_awaiting_approval). Used by ui.py so the
    approval screen can show the full proposal, the agents' reasoning and
    the policy review -- the interrupt payload only carries the handful of
    fields the CLI needs to print a one-line summary.

    Resolves the latest run of the case unless an explicit thread_id is
    given. Read-only: opens the checkpointer, reads, closes. Never resumes.
    """
    thread = thread_id or latest_thread_id(case_id)
    if thread is None:
        return {}, False
    graph, conn = compile_graph()
    try:
        snapshot = graph.get_state({"configurable": {"thread_id": thread}})
        return dict(snapshot.values or {}), bool(snapshot.next)
    finally:
        conn.close()


def cancel_order(request_id: str, cancelled_by: str, reason: str):
    """Withdraw a PENDING purchase request.

    Thin pass-through to tools.execution.cancel_purchase_request, kept here
    so the CLI and the Streamlit screen enter through one function -- the same
    reason run_case/resume_case live here rather than in either front end.
    No graph involvement: by the time an order exists the case has reached a
    terminal state, so there is no checkpoint to resume.
    """
    from tools.execution import cancel_purchase_request

    return cancel_purchase_request(request_id, cancelled_by, reason)


def run_sweep(warehouse_id: str | None = None):
    """Run the deterministic autonomous monitor from the CLI or UI."""
    from submission.sweep.run import run_sweep as _run_sweep
    return _run_sweep(warehouse_id)


def _print_cancellation(result) -> None:
    if result.cancelled:
        print(f"CANCELLED -- request {result.request_id}")
        print(f"  case {result.case_id}")
        if result.budget_released:
            print("  note: the budget reserved for this order has been released")
        else:
            print("  note: no budget was released (this order never reserved any)")
        return
    print(f"NOT CANCELLED -- request {result.request_id}")
    print(f"  {result.error.value if result.error else 'UNKNOWN'}: {result.error_details}")
    if result.status is not None:
        print(f"  current status remains {result.status.value}")


def _print_pending() -> None:
    """The CLI half of the "what is waiting on me" question.

    portfolio.list_pending_cases() already did this work for the Streamlit
    sidebar; the CLI simply had no way to ask, so an operator working from a
    terminal had to already know a case_id to resume anything. Same function,
    same live checkpoint resolution -- so the two entry points cannot report
    different queues.
    """
    from submission.portfolio import list_pending_cases

    pending = list_pending_cases()
    if not pending:
        print("Nothing is waiting on a human right now.")
        return

    print(f"{len(pending)} case(s) waiting on a human:\n")
    for c in pending:
        waited = (
            f"{c['waiting_hours']:.1f}h" if c.get("waiting_hours") is not None else "unknown"
        )
        stale = "  [STALE -- will likely fail revalidation]" if c.get("likely_stale") else ""
        print(f"  {c['case_id']}")
        print(f"    status    {c['status']}")
        print(f"    product   {c.get('sku') or '?'} at {c.get('warehouse_id') or '?'}")
        print(f"    waiting   {waited}{stale}")
        print(f"    thread    {c['thread_id']}")
        if c["status"] == "AWAITING_APPROVAL":
            print(f'    resume    python -m submission.app resume {c["case_id"]} APPROVED "your name"')
        elif c["status"] == "NEEDS_INFORMATION":
            print(
                f"    resume    python -m submission.app resume-info {c['case_id']} "
                "<sku> <warehouse_id>"
            )
        elif c["status"] == "AWAITING_VENDOR_APPROVAL":
            print(f'    resume    python -m submission.app approve-vendor-send {c["case_id"]} "your name"')
        print()


def _print_result(result: dict) -> None:
    if "__interrupt__" in result:
        payload = result["__interrupt__"][0].value
        if payload.get("kind") == "needs_information":
            print(f"NEEDS_INFORMATION -- case {payload['case_id']}")
            print(f"  {payload.get('detail')}")
            print("  resume with: python -m submission.app resume-info "
                  f"{payload['case_id']} <sku> <warehouse_id>")
            return
        if payload.get("kind") == "manual_target_cover_days":
            print(f"MANUAL COVER DAYS NEEDED -- case {payload['case_id']}")
            print(f"  {payload.get('detail')}")
            print("  resume with: python -m submission.app resume-manual-cover "
                  f"{payload['case_id']} <days_of_stock> \"your name\"")
            return
        if payload.get("kind") == "vendor_send_approval":
            print(f"AWAITING_VENDOR_APPROVAL -- case {payload['case_id']}")
            print(f"  request {payload['request_id']}: {payload['recommended_vendor_name']}, {payload['quantity']} units, ${payload['total_cost']}")
            print("  approve with: python -m submission.app approve-vendor-send " f"{payload['case_id']} \"your name\"")
            return
        print(f"AWAITING_APPROVAL -- case {payload['case_id']}")
        print(f"  proposal {payload['proposal_id']} ({payload['proposal_hash'][:12]}...)")
        print(f"  {payload['recommended_vendor_name']}: {payload['quantity']} units, ${payload['total_cost']}")
        print("  resume with: python -m submission.app resume "
              f"{payload['case_id']} APPROVED \"your name\"")
        return

    status: ProposalStatus = result.get("status")
    print(f"{status.value if status else 'UNKNOWN'} -- case {result.get('case_id')}")
    if result.get("error_detail"):
        print(f"  {result.get('error_code')}: {result['error_detail']}")
    if result.get("purchase_result"):
        pr = result["purchase_result"]
        print(f"  request_id={pr.request_id} created={pr.created} total_cost={pr.total_cost}")


def main() -> None:
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    command = sys.argv[1]
    if command == "run":
        sku, warehouse_id = sys.argv[2], sys.argv[3]
        _print_result(run_case(sku, warehouse_id))
    elif command == "resume":
        case_id, decision, approver = sys.argv[2], sys.argv[3], sys.argv[4]
        comments = sys.argv[5] if len(sys.argv) > 5 else None
        _print_result(resume_case(case_id, decision, approver, comments))
    elif command == "edit":
        case_id, offer_id, approver = sys.argv[2], sys.argv[3], sys.argv[4]
        reason = sys.argv[5] if len(sys.argv) > 5 else None
        if not reason or not reason.strip():
            print('usage: python -m submission.app edit <case_id> <eligible_offer_id> "your name" "reason"')
            sys.exit(1)
        _print_result(resume_case(case_id, "EDIT", approver, reason, edited_offer_id=offer_id))
    elif command in {"approve-vendor-send", "reject-vendor-send"}:
        case_id, approver = sys.argv[2], sys.argv[3]
        reason = sys.argv[4] if len(sys.argv) > 4 else None
        decision = "APPROVED" if command == "approve-vendor-send" else "REJECTED"
        _print_result(resume_vendor_send(case_id, decision, approver, reason))
    elif command == "resume-info":
        case_id = sys.argv[2]
        sku = sys.argv[3] if len(sys.argv) > 3 else None
        warehouse_id = sys.argv[4] if len(sys.argv) > 4 else None
        _print_result(resume_missing_info(case_id, sku, warehouse_id))
    elif command == "resume-manual-cover":
        _print_result(resume_manual_cover(sys.argv[2], int(sys.argv[3]), sys.argv[4]))
    elif command == "edit-target":
        case_id, basis, approver = sys.argv[2], sys.argv[3], sys.argv[4]
        comments = sys.argv[5] if len(sys.argv) > 5 else None
        _print_result(resume_case(case_id, "EDIT", approver, comments, chosen_target_basis=basis))
    elif command == "pending":
        _print_pending()
    elif command == "sweep":
        run = run_sweep(sys.argv[2] if len(sys.argv) > 2 else None)
        print(f"SWEEP {run.sweep_id}: {run.cases_opened} case(s) opened, {run.parked_count} parked, {run.deferred_for_budget_count} deferred.")
    elif command == "cancel":
        if len(sys.argv) < 5:
            print('usage: python -m submission.app cancel <request_id> "your name" "reason"')
            sys.exit(1)
        _print_cancellation(cancel_order(sys.argv[2], sys.argv[3], sys.argv[4]))
    else:
        print(__doc__)
        sys.exit(1)


if __name__ == "__main__":
    main()
