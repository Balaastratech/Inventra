"""
Pure routing functions: state in, a short label out. No I/O, no LLM calls,
no side effects — unit-testable without ever building the graph. workflow.py
maps each label to a destination node via add_conditional_edges' path_map.
"""

from __future__ import annotations

from domain.tool_models import ErrorCode
from submission.config import config
from submission.state.state import CaseState


def route_after_validate(state: CaseState) -> str:
    if state.get("error_code") is None:
        return "valid"
    attempts = state.get("retry_counts", {}).get("info_retry", 0)
    # Bounded the same way route_after_decision bounds REVISE: the resume
    # loop can bounce back here repeatedly, but not forever.
    return "retries_exhausted" if attempts >= config.max_info_retries else "invalid"


def route_after_product_check(state: CaseState) -> str:
    return "blocked" if state.get("error_code") is not None else "ok"


def route_after_evidence(state: CaseState) -> str:
    """Route thin sales history to a request for data; fail closed otherwise."""
    error_code = state.get("error_code")
    if error_code is None:
        return "ok"
    if error_code == ErrorCode.INSUFFICIENT_DATA:
        return "needs_information"
    return "blocked"


def route_after_target_cover(state: CaseState) -> str:
    if state.get("error_code") is not None:
        return "blocked"
    return "manual_target_required" if state.get("target_mode") == "MANUAL_COVER_REQUIRED" else "ready"


def route_after_demand_assessment(state: CaseState) -> str:
    assessment = state.get("demand_assessment")
    if assessment is None:
        return "blocked"  # retry budget exhausted -> fail closed
    if assessment.ambiguous:
        return "needs_information"
    return "ok"


def route_after_risk(state: CaseState) -> str:
    risk = state.get("risk")
    if risk is None:
        return "blocked"
    return "at_risk" if risk.at_risk else "no_action"


def route_after_options(state: CaseState) -> str:
    options = state.get("vendor_options")
    if not options or not options.eligible_options:
        return "blocked"
    return "ok"


def route_after_recommendation(state: CaseState) -> str:
    return "blocked" if state.get("replenishment_recommendation") is None else "ok"


def route_after_budget(state: CaseState) -> str:
    return "blocked" if state.get("error_code") is not None else "ok"


def route_after_policy_review(state: CaseState) -> str:
    review = state.get("policy_review")
    if review is None:
        return "blocked"
    return "blocked" if review.verdict.value == "BLOCKED" else "awaiting_approval"


def route_after_decision(state: CaseState) -> str:
    decision = state.get("approval_decision")
    if decision is None:
        return "blocked"
    if decision.decision == "REJECTED":
        return "rejected"
    if decision.decision == "EDIT":
        # Bounded separately from REVISE (config.max_human_edit_cycles): an
        # edit is a deterministic switch between options already on screen,
        # not another round of model reasoning. nodes.apply_human_edit
        # increments the counter, so this reads it before that node runs --
        # hence >= against the cap, not > as the REVISE branch below needs.
        if state.get("retry_counts", {}).get("human_edit", 0) >= config.max_human_edit_cycles:
            return "edit_limit_exceeded"
        return "edit"
    if decision.decision == "REVISE":
        # nodes.handle_decision has ALREADY incremented revision_count by the
        # time this route runs, so the comparison must be strictly greater
        # than the cap, not >=. With max_revision_cycles=1: the first REVISE
        # arrives here with count==1 and is allowed through (1 > 1 is false);
        # a second REVISE arrives with count==2 and is refused. Using >= here
        # made the very first REVISE fail the cap, which meant zero revisions
        # were possible and the "revise" edge in workflow.py was unreachable.
        if state.get("revision_count", 0) > config.max_revision_cycles:
            return "revision_limit_exceeded"
        return "revise"
    return "approved"


def route_after_human_edit(state: CaseState) -> str:
    """An edit naming an unknown or ineligible offer_id fails closed rather
    than guessing (nodes.apply_human_edit sets error_code for that case)."""
    return "blocked" if state.get("error_code") is not None else "ok"


def route_after_revalidation(state: CaseState) -> str:
    result = state.get("revalidation")
    if result is None:
        return "blocked"
    if result.all_checks_pass:
        return "pass"
    # Not every failed check is equally recoverable by a bounce (Gap 6):
    # a hash mismatch is structural -- the proposal doesn't match its own
    # content hash, which re-running risk assessment cannot fix -- so that
    # one fails closed immediately instead of spending the bounce on a
    # foregone conclusion. Budget, stock, and offer changes are all
    # genuinely re-checkable on a fresh read (scenario 7 explicitly expects
    # "case re-enters risk assessment with new facts" for a budget change
    # during the pause), so those still get the one bounce.
    if not result.hash_matches:
        return "blocked"
    # nodes.revalidate() already incremented retry_counts["revalidate"]
    # before this route runs, so 1 attempt-so-far means "first failure,
    # still have the one bounce"; 2+ means "already used it, block now."
    attempts = state.get("retry_counts", {}).get("revalidate", 0)
    return "retry_from_risk" if attempts <= 1 else "blocked"


def route_after_execution(state: CaseState) -> str:
    result = state.get("purchase_result")
    if result is None or result.error is not None:
        return "write_failed"
    from submission.config import config
    return "await_vendor_approval" if config.vendor_email_enabled else "success"


def route_after_vendor_decision(state: CaseState) -> str:
    decision = state.get("vendor_send_decision")
    if state.get("error_code") is not None or decision is None:
        return "blocked"
    return "success" if decision.decision == "APPROVED" else "cancelled"
