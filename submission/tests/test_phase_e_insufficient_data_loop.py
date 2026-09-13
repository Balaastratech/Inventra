"""Phase E regression tests for data-thin and undecidable demand cases."""

from __future__ import annotations

from datetime import date, datetime, timedelta

from domain.tool_models import ErrorCode, ProposalStatus, SalesVelocity, StockPosition
from submission.agents.models import DemandAssessment
from submission.graph import nodes, routes


def _fresh_stock() -> StockPosition:
    return StockPosition(
        snapshot_id="INV-E", sku="AC-003", warehouse_id="DEL-E",
        on_hand=20, reserved=5, confirmed_inbound=0,
        captured_at=datetime.utcnow() - timedelta(minutes=5),
        evidence_id="stock:INV-E", retrieved_at=datetime.utcnow(),
    )


def _thin_sales() -> SalesVelocity:
    return SalesVelocity(
        sku="AC-003", warehouse_id="DEL-E", window_7_days=0, window_30_days=0,
        observation_count_7=1, observation_count_30=2, evidence_id="",
        retrieved_at=datetime.utcnow(), error=ErrorCode.INSUFFICIENT_DATA,
    )


def test_insufficient_sales_history_routes_to_needs_information(monkeypatch):
    monkeypatch.setattr(nodes, "get_stock_position", lambda *_: _fresh_stock())
    monkeypatch.setattr(nodes, "get_sales_velocity", lambda *_: _thin_sales())
    monkeypatch.setattr("tools.parking.park_item", lambda *args: None)
    state = {"sku": "AC-003", "warehouse_id": "DEL-E", "case_id": "CASE-E", "trace_id": "T", "retry_counts": {}}

    nodes.fetch_evidence(state)

    assert state["status"] is ProposalStatus.NEEDS_INFORMATION
    assert routes.route_after_evidence(state) == "needs_information"
    assert "AC-003/DEL-E" in state["error_detail"]
    assert "2 short" in state["error_detail"]


def test_backfill_missing_sales_is_additive_safe(tmp_path):
    import sqlite3

    from database.seed import init_db
    from fixtures import fabricator

    db_path = tmp_path / "phase-e.db"
    init_db(str(db_path))
    start = date.today() - timedelta(days=2)
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "INSERT INTO sales_daily (sale_id, sale_date, sku, warehouse_id, units_sold) VALUES (?, ?, ?, ?, ?)",
            ("existing", start.isoformat(), "AC-003", "DEL-E", 1),
        )
        assert fabricator.backfill_missing_sales("AC-003", "DEL-E", start, date.today(), 4, conn) == 2
        assert fabricator.backfill_missing_sales("AC-003", "DEL-E", start, date.today(), 4, conn) == 0
        assert conn.execute("SELECT COUNT(*) FROM sales_daily").fetchone()[0] == 3


def test_insufficient_sales_history_creates_an_actionable_park(tmp_path, monkeypatch):
    from database.seed import init_db
    from submission.config import config
    from tools.parking import get_open_parked_items

    db_path = tmp_path / "phase-e-parking.db"
    init_db(str(db_path))
    monkeypatch.setattr(nodes, "get_stock_position", lambda *_: _fresh_stock())
    monkeypatch.setattr(nodes, "get_sales_velocity", lambda *_: _thin_sales())
    original_path = config.database_path
    object.__setattr__(config, "database_path", str(db_path))
    try:
        state = {"sku": "AC-003", "warehouse_id": "DEL-E", "case_id": "CASE-E", "trace_id": "T", "retry_counts": {}}
        nodes.fetch_evidence(state)
        parked = get_open_parked_items("DEL-E")
    finally:
        object.__setattr__(config, "database_path", original_path)

    assert len(parked) == 1
    assert parked[0].reason == "INSUFFICIENT_SALES_HISTORY"
    assert "AC-003/DEL-E" in parked[0].note
    assert "Backfill sales_daily" in parked[0].note


def test_ambiguous_window_pause_is_retired():
    from submission import app
    from submission.graph.workflow import build_graph

    assert "await_window_choice" not in build_graph().nodes
    assert not hasattr(app, "resume_demand_clarification")


def test_ambiguous_demand_is_parked_with_both_window_figures(tmp_path, monkeypatch):
    from database.seed import init_db
    from submission.config import config
    from tools.parking import get_open_parked_items

    db_path = tmp_path / "phase-e-ambiguous.db"
    init_db(str(db_path))
    original_path = config.database_path
    original_agent = nodes._AGENTS["assess_demand"]
    object.__setattr__(config, "database_path", str(db_path))
    nodes.set_agents(assess_demand=lambda state, last_error: DemandAssessment(
        case_id=state["case_id"], chosen_window_days=7, rationale="conflicting trends",
        ambiguous=True, clarification_needed="The two demand windows conflict.", evidence_ids=[],
    ))
    try:
        state = {
            "sku": "AC-003", "warehouse_id": "DEL-E", "case_id": "CASE-E", "trace_id": "T",
            "retry_counts": {},
            "sales": SalesVelocity(
                sku="AC-003", warehouse_id="DEL-E", window_7_days=2.0, window_30_days=4.5,
                observation_count_7=7, observation_count_30=30, evidence_id="sales:E", retrieved_at=datetime.utcnow(),
            ),
        }
        nodes.assess_demand(state)
        parked = get_open_parked_items("DEL-E")
    finally:
        nodes.set_agents(assess_demand=original_agent)
        object.__setattr__(config, "database_path", original_path)

    assert state["status"] is ProposalStatus.NEEDS_INFORMATION
    assert parked[0].reason == "AMBIGUOUS_DEMAND_SIGNAL"
    assert "2.0/day" in parked[0].note and "4.5/day" in parked[0].note


def test_backfill_then_fresh_graph_run_uses_the_configured_database(tmp_path):
    """The terminal thin-data case is retried as a new graph run after the
    precise missing period is backfilled. This also guards every sales read
    against silently using the repository's default database in tests."""
    import sqlite3
    import uuid

    from database.seed import init_db, seed_data
    from domain.tool_models import SkuPolicy
    from fixtures.fabricator import backfill_missing_sales
    from submission.config import config
    from submission.graph.workflow import compile_graph
    from submission.state.state import create_initial_state
    from tools.classification import upsert_sku_policy

    db_path = tmp_path / "phase-e-rerun.db"
    checkpoint_path = tmp_path / "phase-e-checkpoints.sqlite"
    warehouse_id = f"E-{uuid.uuid4().hex[:10]}"
    init_db(str(db_path))
    seed_data(str(db_path))
    now = datetime.utcnow().replace(microsecond=0)
    with sqlite3.connect(db_path) as conn:
        conn.execute("INSERT INTO warehouses VALUES (?, 'Phase E warehouse', 10)", (warehouse_id,))
        conn.execute(
            """INSERT INTO inventory_snapshots
               (snapshot_id, sku, warehouse_id, on_hand, reserved, confirmed_inbound, captured_at)
                   VALUES ('INV-E', 'AC-003', ?, 20, 5, 0, ?)""",
                (warehouse_id, now),
        )
        for days_ago in (1, 2):
            day = (now - timedelta(days=days_ago)).date()
            conn.execute(
                """INSERT INTO sales_daily
                   (sale_id, sale_date, sku, warehouse_id, units_sold)
                   VALUES (?, ?, 'AC-003', ?, 2)""",
                (f"SALE-E-{days_ago}", day, warehouse_id),
            )
        conn.execute(
            """INSERT INTO monthly_budgets
               (budget_id, warehouse_id, month, budget_amount, spent_amount, committed_amount, created_at, updated_at)
               VALUES ('BUDGET-E', ?, ?, 50000, 0, 0, ?, ?)""",
            (warehouse_id, now.strftime("%Y-%m"), now, now),
        )

    original_db, original_checkpoint = config.database_path, config.checkpointer_path
    object.__setattr__(config, "database_path", str(db_path))
    object.__setattr__(config, "checkpointer_path", str(checkpoint_path))
    try:
        # No explicit db_path: this proves Phase F's policy lookup follows
        # the same configured database as the sales re-fetch.
        upsert_sku_policy(SkuPolicy(
            sku="AC-003", warehouse_id=warehouse_id, as_of_date=now.date(),
            mean_daily_demand=2, derived_cover_days=14, maturity="PROVISIONAL",
        ))
        graph, conn = compile_graph()
        try:
            first = create_initial_state("AC-003", warehouse_id, 14)
            first_result = graph.invoke(first, config={"configurable": {"thread_id": first["thread_id"]}})
        finally:
            conn.close()
        assert first_result["status"] is ProposalStatus.NEEDS_INFORMATION

        start = (now - timedelta(days=29)).date()
        with sqlite3.connect(db_path) as conn:
            backfill_missing_sales(
                "AC-003", warehouse_id, start, (now - timedelta(days=1)).date(), 2, conn=conn,
            )

        graph, conn = compile_graph()
        try:
            retry = create_initial_state("AC-003", warehouse_id, 14)
            retry_result = graph.invoke(retry, config={"configurable": {"thread_id": retry["thread_id"]}})
        finally:
            conn.close()
    finally:
        object.__setattr__(config, "database_path", original_db)
        object.__setattr__(config, "checkpointer_path", original_checkpoint)

    # The fresh run passed the thin-history gate and re-fetched real rows.
    # Its policy is immature, so Phase F correctly asks only for cover days;
    # it must not re-park the item for missing sales or accept the old 14.
    assert retry_result.get("sales").error is None
    assert retry_result["target_mode"] == "MANUAL_COVER_REQUIRED"
    assert retry_result["target_cover_days"] is None
    assert retry_result["sales"].error is None
