"""
B2 proof: list_pending_cases() is the operator's actual to-do list --
cases currently paused for AWAITING_APPROVAL or NEEDS_INFORMATION -- not
just "everything ever opened" (list_cases()). B1 proof: a pending case
that has been waiting longer than config.data_freshness_hours is flagged,
since it will fail revalidation the moment someone acts on it.
"""

from __future__ import annotations

from dataclasses import replace

from domain.tool_models import ProposalStatus
from submission.config import config
from submission.graph.workflow import compile_graph
from submission.portfolio import list_pending_cases
from submission.state.state import create_initial_state
from submission.tests.reset_db import reset_business_state

import pytest


@pytest.fixture(scope="module", autouse=True)
def clean_state():
    reset_business_state()
    yield


def _run(sku, warehouse_id, target_cover_days=None):
    graph, conn = compile_graph()
    try:
        state = create_initial_state(sku, warehouse_id, target_cover_days)
        return graph.invoke(state, config={"configurable": {"thread_id": state["thread_id"]}})
    finally:
        conn.close()


def test_awaiting_approval_case_appears_in_the_pending_queue():
    result = _run("AC-003", "DEL-01")
    assert "__interrupt__" in result
    case_id = result["__interrupt__"][0].value["case_id"]

    pending = {c["case_id"]: c for c in list_pending_cases()}
    assert case_id in pending
    assert pending[case_id]["status"] == "AWAITING_APPROVAL"
    assert pending[case_id]["sku"] == "AC-003"
    assert pending[case_id]["warehouse_id"] == "DEL-01"


def test_finished_case_does_not_appear_in_the_pending_queue():
    result = _run("AC-001", "DEL-01", target_cover_days=7)  # healthy -> NO_ACTION, terminal
    assert result["status"] == ProposalStatus.NO_ACTION

    pending_ids = {c["case_id"] for c in list_pending_cases()}
    assert result["case_id"] not in pending_ids


def test_pending_case_waiting_past_the_freshness_window_is_flagged_stale(monkeypatch):
    import submission.portfolio as portfolio_module

    result = _run("AC-003", "DEL-06")
    assert "__interrupt__" in result
    case_id = result["__interrupt__"][0].value["case_id"]

    # A case that just paused has waited ~0 hours; force the threshold below
    # that so it must be flagged, without needing to fake a real delay.
    monkeypatch.setattr(portfolio_module, "config", replace(config, data_freshness_hours=0.0))

    pending = {c["case_id"]: c for c in list_pending_cases()}
    assert pending[case_id]["likely_stale"] is True
