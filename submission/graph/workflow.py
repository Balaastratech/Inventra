"""
Wires the deterministic nodes (nodes.py) and pure routes (routes.py) into a
LangGraph StateGraph, with the one genuinely stateful piece: the human
approval interrupt.

interrupt() sits alone at the top of _await_approval so a resume only
re-runs that tiny node, not the side-effecting request_approval node before
it (audit write + email send) -- see PLAN.md D11 / research finding on
interrupt() node re-run semantics.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterable
from dataclasses import is_dataclass
from enum import Enum
from inspect import isclass

from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt
from pydantic import BaseModel

from domain.tool_models import ApprovalDecision, ErrorCode, ProposalStatus, VendorSendDecision
from submission.config import config
from submission.graph import nodes, routes
from submission.graph.support import emit_audit
from submission.state.state import RUN_SEPARATOR, CaseState


def _await_missing_info(state: CaseState) -> CaseState:
    """Pauses when validate_request finds a missing/invalid field (Gap 1).
    Same shape as _await_approval: interrupt() alone at the top so a resume
    only re-runs this tiny node, not validate_request before it.

    The resumed payload carries only the fields the caller wants to correct
    -- any field left out (None) keeps its current value, so a caller only
    has to supply what was actually wrong."""
    corrected = interrupt(
        {
            "kind": "needs_information",
            "case_id": state["case_id"],
            "detail": state.get("error_detail"),
            "sku": state.get("sku"),
            "warehouse_id": state.get("warehouse_id"),
        }
    )
    counts = state.setdefault("retry_counts", {})
    counts["info_retry"] = counts.get("info_retry", 0) + 1
    if corrected.get("sku"):
        state["sku"] = corrected["sku"]
    if corrected.get("warehouse_id"):
        state["warehouse_id"] = corrected["warehouse_id"]
    # target_cover_days is deliberately NOT accepted here (R11 / DG7): the
    # only route to a target is resolve_target_cover (derived) or
    # _await_manual_target_cover (the one named human exception). Accepting
    # it here would let a human bypass resolve_target_cover's maturity gate.
    state["error_code"] = None
    state["error_detail"] = None
    emit_audit(state, "system", "missing_information_provided", {"attempt": counts["info_retry"]})
    return state


def _await_manual_target_cover(state: CaseState) -> CaseState:
    """The sole numerical input allowed by Phase F: immature cover days."""
    payload = interrupt(
        {
            "kind": "manual_target_cover_days",
            "case_id": state["case_id"],
            "detail": state.get("error_detail"),
            "min_days": config.target_cover_min_days,
            "max_days": config.target_cover_max_days,
        }
    )
    if set(payload) != {"target_cover_days", "requested_by"}:
        return nodes._fail(
            state, ErrorCode.INVALID_INPUT,
            "Manual maturity handling requires a named person and only accepts days of stock; no other human-supplied number is allowed.",
        )
    cover = payload["target_cover_days"]
    if isinstance(cover, bool) or not isinstance(cover, int) or not config.target_cover_min_days <= cover <= config.target_cover_max_days:
        return nodes._fail(state, ErrorCode.INVALID_INPUT, "Manual days of stock must be a whole number within policy bounds.")
    requested_by = payload["requested_by"]
    if not isinstance(requested_by, str) or not requested_by.strip():
        return nodes._fail(state, ErrorCode.INVALID_INPUT, "Manual days of stock must be recorded against a named person.")
    requested_by = requested_by.strip()
    state["target_cover_days"] = cover
    state["target_provenance"] = f"human:{requested_by}"
    state["target_mode"] = "MANUAL_COVER_CONFIRMED"
    state["status"] = ProposalStatus.NEEDS_INFORMATION
    state["error_code"] = None
    state["error_detail"] = None
    emit_audit(state, f"human:{requested_by}", "manual_cover_days_provided", {"days": cover})
    return state


def _await_approval(state: CaseState) -> CaseState:
    proposal = state["proposal"]
    decision_payload = interrupt(
        {
            "case_id": state["case_id"],
            "proposal_id": proposal.proposal_id,
            "proposal_hash": proposal.proposal_hash,
            "sku": proposal.sku,
            "warehouse_id": proposal.warehouse_id,
            "recommended_vendor_name": proposal.recommended_vendor_name,
            "quantity": proposal.quantity,
            "total_cost": proposal.total_cost,
        }
    )
    decision = ApprovalDecision.model_validate(decision_payload)
    return nodes.handle_decision(state, decision)


def _await_vendor_approval(state: CaseState) -> CaseState:
    result = state["purchase_result"]
    proposal = state["proposal"]
    decision_payload = interrupt(
        {
            "kind": "vendor_send_approval",
            "case_id": state["case_id"],
            "request_id": result.request_id,
            "proposal_hash": proposal.proposal_hash,
            "recommended_vendor_name": proposal.recommended_vendor_name,
            "quantity": proposal.quantity,
            "total_cost": proposal.total_cost,
        }
    )
    return nodes.handle_vendor_decision(state, VendorSendDecision.model_validate(decision_payload))


def build_graph() -> StateGraph:
    graph = StateGraph(CaseState)

    for name, fn in [
        ("validate_request", nodes.validate_request),
        ("check_product", nodes.check_product),
        ("fetch_evidence", nodes.fetch_evidence),
        ("resolve_target_cover", nodes.resolve_target_cover),
        ("await_manual_target_cover", _await_manual_target_cover),
        ("assess_demand", nodes.assess_demand),
        ("compute_risk", nodes.compute_risk),
        ("fetch_vendor_evidence", nodes.fetch_vendor_evidence),
        ("build_options", nodes.build_options),
        ("recommend_vendor", nodes.recommend_vendor),
        ("fetch_budget_and_policy", nodes.fetch_budget_and_policy),
        ("draft_proposal", nodes.draft_proposal),
        ("review_policy", nodes.review_policy),
        ("request_approval", nodes.request_approval),
        ("await_approval", _await_approval),
        ("await_missing_info", _await_missing_info),
        ("prepare_revision", nodes.prepare_revision),
        ("apply_human_edit", nodes.apply_human_edit),
        ("invalidate_approval", nodes.invalidate_approval),
        ("revalidate", nodes.revalidate),
        ("execute_purchase", nodes.execute_purchase),
        ("request_vendor_approval", nodes.request_vendor_approval),
        ("await_vendor_approval", _await_vendor_approval),
        ("finalize_no_action", nodes.finalize_no_action),
        ("finalize_needs_information", nodes.finalize_needs_information),
        ("finalize_blocked", nodes.finalize_blocked),
        ("finalize_success", nodes.finalize_success),
        ("finalize_vendor_cancelled", nodes.finalize_vendor_cancelled),
    ]:
        graph.add_node(name, fn)

    graph.add_edge(START, "validate_request")
    graph.add_conditional_edges(
        "validate_request", routes.route_after_validate,
        {
            "valid": "check_product",
            "invalid": "await_missing_info",
            "retries_exhausted": "finalize_needs_information",
        },
    )
    graph.add_edge("await_missing_info", "validate_request")
    graph.add_conditional_edges(
        "check_product", routes.route_after_product_check,
        {"ok": "fetch_evidence", "blocked": "finalize_blocked"},
    )
    graph.add_conditional_edges(
        "fetch_evidence", routes.route_after_evidence,
        {"ok": "resolve_target_cover", "needs_information": "finalize_needs_information", "blocked": "finalize_blocked"},
    )
    graph.add_conditional_edges(
        "resolve_target_cover", routes.route_after_target_cover,
        {"ready": "assess_demand", "manual_target_required": "await_manual_target_cover", "blocked": "finalize_needs_information"},
    )
    graph.add_edge("await_manual_target_cover", "assess_demand")
    graph.add_conditional_edges(
        "assess_demand", routes.route_after_demand_assessment,
        {"ok": "compute_risk", "needs_information": "finalize_needs_information", "blocked": "finalize_blocked"},
    )
    graph.add_conditional_edges(
        "compute_risk", routes.route_after_risk,
        {"at_risk": "fetch_vendor_evidence", "no_action": "finalize_no_action", "blocked": "finalize_blocked"},
    )
    graph.add_edge("fetch_vendor_evidence", "build_options")
    graph.add_conditional_edges(
        "build_options", routes.route_after_options,
        {"ok": "recommend_vendor", "blocked": "finalize_blocked"},
    )
    graph.add_conditional_edges(
        "recommend_vendor", routes.route_after_recommendation,
        {"ok": "fetch_budget_and_policy", "blocked": "finalize_blocked"},
    )
    graph.add_conditional_edges(
        "fetch_budget_and_policy", routes.route_after_budget,
        {"ok": "draft_proposal", "blocked": "finalize_blocked"},
    )
    graph.add_edge("draft_proposal", "review_policy")
    graph.add_conditional_edges(
        "review_policy", routes.route_after_policy_review,
        {"awaiting_approval": "request_approval", "blocked": "finalize_blocked"},
    )
    graph.add_edge("request_approval", "await_approval")
    graph.add_conditional_edges(
        "await_approval", routes.route_after_decision,
        {
            "approved": "revalidate",
            "rejected": "finalize_blocked",
            # Bounded by config.max_revision_cycles (routes.route_after_decision).
            # Re-enters at evidence collection, not vendor selection: see
            # nodes.prepare_revision for why a revision must re-read stock.
            "revise": "prepare_revision",
            "revision_limit_exceeded": "finalize_blocked",
            # B8: the human picked a different eligible supplier outright.
            # Re-enters at draft_proposal, NOT fetch_evidence like a revision
            # does -- the evidence is unchanged and still fresh (the approver
            # is acting on the screen it produced); only the choice made from
            # it changed. Going back to draft_proposal means the hash, totals
            # and budget line are all recomputed, and review_policy runs
            # again before it can reach a human.
            "edit": "apply_human_edit",
            "edit_limit_exceeded": "finalize_blocked",
        },
    )
    graph.add_conditional_edges(
        "apply_human_edit", routes.route_after_human_edit,
        {"ok": "draft_proposal", "blocked": "finalize_blocked"},
    )
    graph.add_edge("prepare_revision", "fetch_evidence")
    graph.add_conditional_edges(
        "revalidate", routes.route_after_revalidation,
        {"pass": "execute_purchase", "retry_from_risk": "invalidate_approval", "blocked": "finalize_blocked"},
    )
    graph.add_edge("invalidate_approval", "compute_risk")
    graph.add_conditional_edges(
        "execute_purchase", routes.route_after_execution,
        {"success": "finalize_success", "await_vendor_approval": "request_vendor_approval", "write_failed": "finalize_blocked"},
    )
    graph.add_edge("request_vendor_approval", "await_vendor_approval")
    graph.add_conditional_edges(
        "await_vendor_approval", routes.route_after_vendor_decision,
        {"success": "finalize_success", "cancelled": "finalize_vendor_cancelled", "blocked": "finalize_blocked"},
    )

    for terminal in ("finalize_no_action", "finalize_needs_information", "finalize_blocked", "finalize_success", "finalize_vendor_cancelled"):
        graph.add_edge(terminal, END)

    return graph


def checkpoint_allowlist() -> tuple[type, ...]:
    """Every custom type that can legitimately appear in a checkpoint.

    Derived from the two modules that define them rather than hand-listed,
    so adding a field to CaseState can't silently break resume by forgetting
    to register its type here. JsonPlusSerializer accepts classes directly
    (it turns each into a (module, qualname) key internally), so passing the
    classes keeps this honest -- a renamed or deleted model becomes an import
    error here instead of a runtime deserialization failure after a pause.

    CaseState itself needs no entry: it is a TypedDict, so it is a plain dict
    at runtime.
    """
    from domain import tool_models
    from submission.agents import models as agent_models
    from submission.graph import economics, support

    allowed: list[type] = []
    for module in (tool_models, agent_models, economics, support):
        for obj in vars(module).values():
            if not isclass(obj) or obj.__module__ != module.__name__:
                continue  # skip re-exported imports
            if issubclass(obj, (BaseModel, Enum)) or is_dataclass(obj):
                allowed.append(obj)
    return tuple(allowed)


def latest_thread_ids(case_ids: Iterable[str]) -> dict[str, str]:
    """Batch form of latest_thread_id: one connection and one query for any
    number of cases, returning {case_id: newest thread_id} and omitting
    cases that have never been run.

    Exists because portfolio.list_pending_cases() resolves a thread id for
    every pending case, and the sidebar calls it on every Streamlit rerun --
    one connection per case against the same checkpoint file is both slow
    and a needless source of SQLite lock contention.

    Reads every distinct thread_id once and groups in Python rather than
    building an N-clause WHERE: the checkpoint table holds one row per run,
    not per event, so the set is small, and this keeps the matching rules in
    exactly one place instead of two query shapes that must agree.
    """
    case_ids = list(case_ids)
    if not case_ids:
        return {}
    conn = sqlite3.connect(config.checkpointer_path)
    try:
        rows = conn.execute("SELECT DISTINCT thread_id FROM checkpoints").fetchall()
    except sqlite3.OperationalError:
        # No checkpoints table yet: nothing has ever been run.
        return {}
    finally:
        conn.close()

    threads = [r[0] for r in rows]
    resolved: dict[str, str] = {}
    for case_id in case_ids:
        prefix = f"{case_id}{RUN_SEPARATOR}"
        # Same two-way match as the single-case form: `<case_id>#<timestamp>`
        # (current) and a bare `<case_id>` (checkpoints written before runs
        # had their own identity), so existing paused cases stay resumable.
        matching = [t for t in threads if t == case_id or t.startswith(prefix)]
        newest = max(matching, default=None)
        if newest is not None:
            resolved[case_id] = newest
    return resolved


def latest_thread_id(case_id: str) -> str | None:
    """The most recent run of a case, or None if it has never been run.

    Callers hold a business `case_id` (that's what the watchlist, the email
    links and the CLI all pass around) but the checkpointer is keyed by
    per-run `thread_id`. This resolves one to the other, newest first.

    Matches both `<case_id>#<timestamp>` (current) and a bare `<case_id>`
    (checkpoints written before runs had their own identity), so existing
    paused cases stay resumable. The timestamp suffix is fixed-width, so a
    plain max() is a chronological pick; and because `"CASE-X#..." >
    "CASE-X"`, a new run always outranks a legacy one.

    Delegates to latest_thread_ids so the matching rules above live in one
    implementation only -- the two forms can never drift apart.
    """
    return latest_thread_ids([case_id]).get(case_id)


def compile_graph():
    """Returns (compiled_graph, sqlite_connection). The connection is
    returned so the caller can close it on shutdown; keep it open for the
    life of the process otherwise. Both the CLI and approval_server call
    this against the same config.checkpointer_path file, so either process
    can resume a thread the other one paused (LangGraph's documented
    cross-process resume model -- the checkpoint lives on disk, not in a
    running graph object)."""
    conn = sqlite3.connect(config.checkpointer_path, check_same_thread=False)
    # An explicit allowlist, not allowed_msgpack_modules=True.
    #
    # True is LangGraph's *permissive* mode: it deserializes any type at all
    # and logs "Deserializing unregistered type ... This will be blocked in a
    # future version" for each one. It is also identical to passing nothing,
    # so the previous `True` here opted into nothing while looking like it
    # did. Two reasons that mattered:
    #
    #   1. Resume is the load-bearing behaviour of this whole submission. The
    #      warning says the permissive path gets blocked in a future release,
    #      at which point every paused case fails to resume -- a silent
    #      upgrade-triggered break of the human-approval gate.
    #   2. The permissive setting deserializes whatever is in the checkpoint
    #      file. JsonPlusSerializer's own docs note that an attacker who can
    #      write to the checkpoint database may be able to trigger code
    #      execution. "Our own models are trustworthy" is not the relevant
    #      question -- what the file *could* contain is.
    #
    # Naming the types fixes both and removes the log noise.
    serde = JsonPlusSerializer(allowed_msgpack_modules=checkpoint_allowlist())
    checkpointer = SqliteSaver(conn, serde=serde)
    compiled = build_graph().compile(checkpointer=checkpointer)
    return compiled, conn
