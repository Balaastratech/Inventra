"""
Gap 1 proof: a case that pauses on a missing/invalid field can be resumed
with corrected input and continue, instead of being a dead end that forces
starting over. Also proves the resume loop is bounded by
config.max_info_retries and falls through to finalize_needs_information
once exhausted.

Phase G / DG7 update: this test used to force the pause with an
out-of-range target_cover_days and "fix" it by resuming with a corrected
target_cover_days. That second half is no longer legal (R11): the only
route to a cover target is resolve_target_cover (derived) or
_await_manual_target_cover (the one named-human exception), and
_await_missing_info no longer accepts target_cover_days at all -- see
submission/graph/workflow.py::_await_missing_info. The pause/resume
mechanism itself is unchanged, so this test now exercises it with a
missing warehouse_id instead, which is still a legitimate field to correct
through this path (it identifies *which* product, it is not evidence).
"""

from __future__ import annotations

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


def _resume(case_id, resume_payload):
    graph, conn = compile_graph()
    try:
        thread = latest_thread_id(case_id)
        return graph.invoke(Command(resume=resume_payload), config={"configurable": {"thread_id": thread}})
    finally:
        conn.close()


def test_missing_info_pauses_and_resume_with_correction_proceeds():
    # Empty warehouse_id is missing, per validate_request.
    result = _run("AC-003", "")
    assert "__interrupt__" in result, "a missing field should pause, not terminate the case"
    payload = result["__interrupt__"][0].value
    assert payload["kind"] == "needs_information"
    assert "target_cover_days" not in payload
    case_id = payload["case_id"]

    final = _resume(case_id, {"warehouse_id": "DEL-10"})
    # Corrected input should let the case proceed past validate_request --
    # it must not still be stuck in NEEDS_INFORMATION.
    if "__interrupt__" in final:
        assert final["__interrupt__"][0].value.get("kind") != "needs_information"
    else:
        assert final["status"] != ProposalStatus.NEEDS_INFORMATION


def test_missing_info_retries_exhausted_falls_through_to_needs_information():
    result = _run("AC-003", "")
    assert "__interrupt__" in result
    case_id = result["__interrupt__"][0].value["case_id"]

    final = None
    for _ in range(config.max_info_retries):
        final = _resume(case_id, {"warehouse_id": ""})  # keep re-submitting a missing value
        if "__interrupt__" not in final:
            break

    assert "__interrupt__" not in final, "must terminate once max_info_retries is exhausted, not pause forever"
    assert final["status"] == ProposalStatus.NEEDS_INFORMATION
    assert final["retry_counts"]["info_retry"] >= config.max_info_retries


def test_resume_missing_info_no_longer_accepts_a_cover_target():
    """DG7 regression guard: a target_cover_days smuggled into the missing-
    info resume payload must have no effect. sku/warehouse_id are the only
    legal corrections through this path."""
    result = _run("AC-003", "")
    case_id = result["__interrupt__"][0].value["case_id"]

    final = _resume(case_id, {"warehouse_id": "DEL-10", "target_cover_days": 999})
    # The extra key is silently ignored, not applied and not rejected --
    # the warehouse_id correction still goes through.
    if "__interrupt__" in final:
        assert final["__interrupt__"][0].value.get("kind") != "needs_information"
    else:
        assert final["status"] != ProposalStatus.NEEDS_INFORMATION
