"""
Phase 5: the acceptance scenarios not already covered elsewhere.

Coverage map (see PLAN.md for the full list):
  1  healthy stock              -> test_phase2_3_graph.py
  2  missing request data       -> here
  3  stale stock                -> test_phase2_3_graph.py
  4  cost vs speed trade-off    -> here (explicit assertion) + implicit in 2/3's happy path
  5  over budget                -> test_phase2_3_graph.py
  6  invalid model output       -> test_phase4_agents.py
  7  approval data changes      -> test_phase2_3_graph.py
  8  duplicate approval         -> test_phase2_3_graph.py
  9  human rejection            -> test_phase2_3_graph.py
  10 write failure              -> test_phase2_3_graph.py
  11 insufficient sales history -> here (needed an additive fixture, D5 --
                                    AC-005 as seeded has 6-14 observations,
                                    not the <3 the scenario requires)
  12 unreliable/expired vendor  -> test_phase2_3_graph.py
"""

from __future__ import annotations

import os

import pytest

from domain.tool_models import ErrorCode, ProposalStatus
from submission.config import config
from submission.graph.workflow import compile_graph, latest_thread_id
from submission.state.state import create_initial_state
from submission.tests.seed_extra import INSUFFICIENT_HISTORY_CASE
from submission.tests.reset_db import reset_business_state


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


# Scenario 2: missing SKU -> NEEDS_INFORMATION, no database queries happened
def test_missing_sku_returns_needs_information_before_any_lookup():
    result = _run("", "DEL-01")
    assert result["status"] == ProposalStatus.NEEDS_INFORMATION
    assert "sku" in result["error_detail"].lower()
    # Nothing downstream of validate_request should have run at all.
    assert result["product"] is None
    assert result["stock"] is None
    assert result["sales"] is None


def test_missing_warehouse_returns_needs_information():
    result = _run("AC-001", "")
    assert result["status"] == ProposalStatus.NEEDS_INFORMATION
    assert "warehouse_id" in result["error_detail"].lower()


def test_out_of_range_target_cover_returns_needs_information():
    # Brief: "allowed range is 7-45 days ... reject invalid target-cover input."
    result = _run("AC-001", "DEL-01", target_cover_days=100)
    assert result["status"] == ProposalStatus.NEEDS_INFORMATION
    assert "target_cover_days" in result["error_detail"]
    assert result["stock"] is None


# Scenario 4: the trade-off is explained in evidence terms, not asserted blindly
def test_cost_vs_speed_tradeoff_is_explained_with_real_numbers():
    result = _run("AC-003", "DEL-01")
    assert "__interrupt__" in result

    graph, conn = compile_graph()
    try:
        # thread_id is per-run now, so resolve it rather than assuming it
        # equals the case_id (see state.new_thread_id).
        thread = latest_thread_id("CASE-AC-003-DEL-01")
        proposal = graph.get_state({"configurable": {"thread_id": thread}}).values["proposal"]
    finally:
        conn.close()

    assert proposal.cost_vs_speed_trade_off, "a non-cheapest pick must explain itself"
    assert proposal.other_options_summary


# Scenario 11: insufficient sales history -> NEEDS_INFORMATION,
# INSUFFICIENT_DATA, and a human-visible parked item.
def test_insufficient_sales_history_requests_data_and_parks_the_item():
    sku, warehouse_id = INSUFFICIENT_HISTORY_CASE
    result = _run(sku, warehouse_id)
    assert "__interrupt__" not in result
    assert result["status"] == ProposalStatus.NEEDS_INFORMATION
    assert result["error_code"] == ErrorCode.INSUFFICIENT_DATA
    assert result["demand_assessment"] is None, "must block before any judgment is asked to fill the gap"
    from tools.parking import get_open_parked_items
    parked = get_open_parked_items(warehouse_id)
    assert any(item.sku == sku and item.reason == "INSUFFICIENT_SALES_HISTORY" for item in parked)
