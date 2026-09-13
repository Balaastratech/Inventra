"""
A3 proof: DemandAssessment.clarification_needed was computed by the stub/
prompt, prompted for, and then silently discarded -- the ambiguous path
closed with a blank error_detail. Brief scenario 2 requires "NEEDS_INFORMATION
with one precise question," so nodes.assess_demand must actually surface it.

Also covers A6: observation counts and a refresh hint survive into the
stale-snapshot and insufficient-sales-history messages instead of being
computed and then dropped.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from domain.tool_models import ErrorCode, ProposalStatus, SalesVelocity, StockPosition
from submission.agents.models import DemandAssessment
from submission.graph import nodes


def _restore_stub():
    from submission.agents import stubs

    nodes.set_agents(assess_demand=stubs.assess_demand_stub)


def test_ambiguous_demand_surfaces_the_precise_question_not_a_blank_reason():
    nodes.set_agents(
        assess_demand=lambda state, last_error: DemandAssessment(
            case_id=state["case_id"],
            chosen_window_days=7,
            rationale="7d and 30d disagree sharply",
            ambiguous=True,
            clarification_needed="Sales jumped 5x in the last week -- is this a real demand shift or a data glitch?",
            evidence_ids=[],
        )
    )
    try:
        state = {"case_id": "CASE-X", "trace_id": "T", "retry_counts": {}}
        nodes.assess_demand(state)
    finally:
        _restore_stub()

    assert state["status"] == ProposalStatus.NEEDS_INFORMATION
    assert state["error_code"] == ErrorCode.INVALID_INPUT
    assert "5x in the last week" in state["error_detail"], (
        "the agent's own precise question must reach error_detail, not be discarded"
    )


def test_stale_snapshot_message_recommends_a_refresh():
    stock = StockPosition(
        snapshot_id="INV-1", sku="AC-001", warehouse_id="DEL-01",
        on_hand=10, reserved=0, confirmed_inbound=0,
        captured_at=datetime.utcnow() - timedelta(hours=100),
        evidence_id="stock:INV-1", retrieved_at=datetime.utcnow(),
    )
    import submission.graph.nodes as nodes_module
    from unittest.mock import patch

    state = {"sku": "AC-001", "warehouse_id": "DEL-01", "trace_id": "T", "case_id": "CASE-X", "retry_counts": {}}
    with patch.object(nodes_module, "get_stock_position", return_value=stock):
        nodes.fetch_evidence(state)

    assert state["error_code"] == ErrorCode.DATA_STALE
    assert "refresh" in state["error_detail"].lower()


def test_insufficient_sales_message_shows_observation_counts():
    import submission.graph.nodes as nodes_module
    from unittest.mock import patch

    stock = StockPosition(
        snapshot_id="INV-1", sku="AC-005", warehouse_id="DEL-01",
        on_hand=10, reserved=0, confirmed_inbound=0,
        captured_at=datetime.utcnow() - timedelta(minutes=20),
        evidence_id="stock:INV-1", retrieved_at=datetime.utcnow(),
    )
    sparse_sales = SalesVelocity(
        sku="AC-005", warehouse_id="DEL-01", window_7_days=0, window_30_days=0,
        observation_count_7=1, observation_count_30=2,
        evidence_id="", retrieved_at=datetime.utcnow(), error=ErrorCode.INSUFFICIENT_DATA,
    )
    state = {"sku": "AC-005", "warehouse_id": "DEL-01", "trace_id": "T", "case_id": "CASE-X", "retry_counts": {}}
    with patch.object(nodes_module, "get_stock_position", return_value=stock), \
         patch.object(nodes_module, "get_sales_velocity", return_value=sparse_sales), \
         patch("tools.parking.park_item"):
        nodes.fetch_evidence(state)

    assert state["error_code"] == ErrorCode.INSUFFICIENT_DATA
    assert state["status"] == ProposalStatus.NEEDS_INFORMATION
    assert "1 of last 7 days" in state["error_detail"]
    assert "2 of last 30 days" in state["error_detail"]
