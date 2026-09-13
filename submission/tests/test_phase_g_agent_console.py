"""
Phase G / G2: the agent console (submission/ui.py, evolved in place -- DG1)
and the R11 fixes that belong to Phase G (DG6, DG7). No Streamlit rendering
here -- these exercise portfolio.py and workflow.py directly, which is what
actually enforces the behaviour the plan's exit criteria describe.
"""

from __future__ import annotations

import ast
import sqlite3
from datetime import date, datetime, timedelta
from pathlib import Path

import pytest

from database.seed import init_db
from submission.config import config
from submission.portfolio import list_pending_cases, scan_portfolio


@pytest.fixture
def db(tmp_path):
    path = tmp_path / "phase-g-agent.db"
    init_db(str(path))
    original = config.database_path
    object.__setattr__(config, "database_path", str(path))
    now = datetime.utcnow().isoformat()
    with sqlite3.connect(path) as conn:
        conn.execute("INSERT INTO warehouses VALUES ('WH','Warehouse',10)")
        conn.execute(
            "INSERT INTO products (sku,name,category,active,selling_price,lifecycle,unit_volume_m3) "
            "VALUES ('FAST','Fast mover','C',1,100,'MATURE',1)"
        )
        conn.execute(
            "INSERT INTO products (sku,name,category,active,selling_price,lifecycle,unit_volume_m3) "
            "VALUES ('SLOW','Slow mover','C',1,100,'MATURE',1)"
        )
        conn.execute(
            "INSERT INTO products (sku,name,category,active,selling_price,lifecycle,unit_volume_m3) "
            "VALUES ('NOPOL','No policy yet','C',1,100,'MATURE',1)"
        )
        for sku, on_hand in (("FAST", 100), ("SLOW", 100), ("NOPOL", 100)):
            conn.execute(
                "INSERT INTO inventory_snapshots (snapshot_id,sku,warehouse_id,on_hand,reserved,confirmed_inbound,captured_at) "
                "VALUES (?, ?, 'WH', ?, 0, 0, ?)",
                (f"INV-{sku}", sku, on_hand, now),
            )
            for days_ago in (1, 2, 3, 4, 5):
                conn.execute(
                    "INSERT INTO sales_daily (sale_id,sale_date,sku,warehouse_id,units_sold) VALUES (?,?,?,?,?)",
                    (f"SALE-{sku}-{days_ago}", (date.today() - timedelta(days=days_ago)).isoformat(), sku, "WH", 5),
                )
        # FAST derives a short target; SLOW derives a long one. NOPOL has no
        # sku_policy row at all.
        for sku, cover, target_units in (("FAST", 7, 35), ("SLOW", 40, 200)):
            conn.execute(
                """INSERT INTO sku_policy (sku, warehouse_id, as_of_date, mean_daily_demand, std_daily_demand,
                   cumulative_share, service_level, safety_stock_units, consecutive_confirmations,
                   reorder_point_units, derived_cover_days, consumption_value_12m, maturity, confidence,
                   demand_quadrant, abc_class, xyz_class, active_class, change_reason)
                   VALUES (?, 'WH', ?, 5, 1, 1, .95, 5, 1, ?, ?, 1000, 'ESTABLISHED', .9, 'SMOOTH', 'A', 'X', 'A', '')""",
                (sku, date.today().isoformat(), target_units, cover),
            )
    try:
        yield path
    finally:
        object.__setattr__(config, "database_path", original)


def test_watchlist_uses_each_skus_own_derived_target(db):
    rows = {r.sku: r for r in scan_portfolio(None, "WH")}
    assert "7-day" in rows["FAST"].target_basis_label
    assert "40-day" in rows["SLOW"].target_basis_label
    assert rows["FAST"].target_basis_label != rows["SLOW"].target_basis_label


def test_watchlist_never_silently_defaults_to_the_config_target(db):
    rows = {r.sku: r for r in scan_portfolio(None, "WH")}
    assert "not yet derived" in rows["NOPOL"].target_basis_label
    assert str(config.target_cover_default_days) not in rows["NOPOL"].target_basis_label.split("—")[0]


def test_missing_info_resume_no_longer_accepts_a_cover_target():
    import inspect

    from submission.app import resume_missing_info

    params = inspect.signature(resume_missing_info).parameters
    assert "target_cover_days" not in params


def test_resume_missing_info_payload_omits_target_cover_days():
    source = Path("submission/graph/workflow.py").read_text()
    tree = ast.parse(source)
    func = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "_await_missing_info")
    body_source = ast.get_source_segment(source, func)
    assert '"target_cover_days"' not in body_source


def test_pending_queue_distinguishes_manual_cover_from_missing_fields(db):
    """Structural guard for DG8: list_pending_cases must expose target_mode
    so the queue (and the screen it feeds) can branch on it, since
    MANUAL_COVER_REQUIRED and a missing-fields pause share the same
    NEEDS_INFORMATION status string."""
    import inspect

    source = inspect.getsource(list_pending_cases)
    assert "target_mode" in source


def test_park_queue_rows_carry_sku_warehouse_and_a_date_range(db):
    from tools.parking import get_open_parked_items, park_item

    park_item("FAST", "WH", "INSUFFICIENT_SALES_HISTORY", note="Backfill sales_daily for FAST/WH from 2026-01-01 to 2026-01-10", db_path=str(db))
    items = get_open_parked_items("WH", db_path=str(db))
    assert items[0].sku == "FAST"
    assert items[0].warehouse_id == "WH"
    assert "2026-01-01" in items[0].note and "2026-01-10" in items[0].note


def test_sweep_history_reads_back_what_run_sweep_recorded(db):
    from tools.sweep_runs import get_sweep_history, record_sweep_run

    record_sweep_run(
        warehouse_ids=["WH"], pairs_examined=3, candidates_found=1, parked_count=1,
        deferred_for_budget_count=0, cases_opened=0, reminders_sent=0,
        total_model_calls_estimate=0, detail=[{"sku": "FAST"}], db_path=str(db),
    )
    history = get_sweep_history(db_path=str(db))
    assert history[0].pairs_examined == 3
    assert history[0].detail == [{"sku": "FAST"}]
