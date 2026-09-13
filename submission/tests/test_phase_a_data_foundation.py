"""Phase A data-foundation guarantees.

These tests exercise the additive schema, the new narrow tools, and the
fabricator against a disposable SQLite database.  They deliberately avoid the
graph: Phase A supplies facts; later phases decide how to use them.
"""

from __future__ import annotations

import sqlite3
import json
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from database.migrate import apply_migrations
from database.seed import init_db, seed_data


@pytest.fixture
def phase_a_db(tmp_path: Path) -> Path:
    path = tmp_path / "phase_a.db"
    init_db(str(path))
    return path


def _columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}


def test_migration_is_additive_idempotent_and_creates_phase_a_schema(tmp_path: Path):
    path = tmp_path / "legacy.db"
    conn = sqlite3.connect(path)
    conn.executescript(
        """
        CREATE TABLE products (sku TEXT PRIMARY KEY, name TEXT, category TEXT, active BOOLEAN, created_at TIMESTAMP);
        CREATE TABLE vendors (vendor_id TEXT PRIMARY KEY, name TEXT, active BOOLEAN, on_time_rate REAL, fill_rate REAL, quality_score REAL, created_at TIMESTAMP);
        CREATE TABLE vendor_offers (offer_id TEXT PRIMARY KEY, vendor_id TEXT, sku TEXT, unit_price REAL, moq INTEGER, lead_time_days INTEGER, valid_until TIMESTAMP, created_at TIMESTAMP);
        CREATE TABLE purchase_requests (request_id TEXT PRIMARY KEY);
        """
    )
    conn.close()

    applied = apply_migrations(str(path))
    assert "products.selling_price" in applied
    assert "vendors.billing_basis" in applied
    assert "vendor_offers.freight_flat" in applied
    assert apply_migrations(str(path)) == []

    conn = sqlite3.connect(path)
    assert {"warehouses", "stock_receipts", "sku_policy", "policy_rules", "parked_items", "carrying_cost_inputs"}.issubset(
        {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    )
    assert {"selling_price", "lifecycle", "unit_volume_m3"}.issubset(_columns(conn, "products"))
    assert {"billing_basis", "payment_terms_days"}.issubset(_columns(conn, "vendors"))
    assert {"freight_flat", "freight_per_unit"}.issubset(_columns(conn, "vendor_offers"))
    conn.close()


def test_seed_is_reproducible_complete_and_preserves_core_scenarios(tmp_path: Path):
    first = tmp_path / "first.db"
    second = tmp_path / "second.db"
    for path in (first, second):
        init_db(str(path))
        seed_data(str(path))

    def snapshot(path: Path):
        conn = sqlite3.connect(path)
        sales = conn.execute("SELECT sale_date, sku, warehouse_id, units_sold FROM sales_daily ORDER BY 1,2,3").fetchall()
        facts = conn.execute("SELECT sku, selling_price, lifecycle, unit_volume_m3 FROM products ORDER BY sku").fetchall()
        return conn, sales, facts

    conn1, sales1, facts1 = snapshot(first)
    conn2, sales2, facts2 = snapshot(second)
    assert sales1 == sales2
    assert facts1 == facts2
    assert conn1.execute("SELECT COUNT(*) FROM products").fetchone()[0] >= 35
    assert conn1.execute("SELECT COUNT(*) FROM warehouses").fetchone()[0] >= 3
    assert conn1.execute("SELECT COUNT(*) FROM sales_daily WHERE sale_date = date('now')").fetchone()[0] == 0
    assert conn1.execute("SELECT COUNT(*) FROM sales_daily GROUP BY sale_date, sku, warehouse_id HAVING COUNT(*) > 1").fetchone() is None
    assert conn1.execute("SELECT COUNT(*) FROM products WHERE selling_price IS NULL OR unit_volume_m3 IS NULL").fetchone()[0] == 0
    assert conn1.execute("SELECT COUNT(*) FROM warehouses WHERE storage_cost_per_m3_month IS NULL").fetchone()[0] == 0
    assert conn1.execute("SELECT COUNT(*) FROM vendors WHERE billing_basis IS NULL").fetchone()[0] == 0
    assert conn1.execute("SELECT COUNT(*) FROM stock_receipts").fetchone()[0] > 0
    assert {"AC-001", "AC-002", "AC-003", "AC-004", "AC-005", "AC-006"}.issubset({row[0] for row in facts1})
    conn1.close()
    conn2.close()
    scenarios = json.loads((Path("fixtures/scenarios.json")).read_text())
    assert len(scenarios["acceptance_scenarios"]) + len(scenarios["phase_a_scenarios"]) == 26
    assert {item["scenario_number"] for item in scenarios["phase_a_scenarios"]} == set(range(13, 27))


def test_fabricator_enforces_daily_uniqueness_and_records_its_changes(phase_a_db: Path):
    from fixtures.fabricator import fabricate_history, get_fabrication_log

    conn = sqlite3.connect(phase_a_db)
    conn.execute("INSERT INTO products (sku, name, category, active, selling_price, lifecycle, unit_volume_m3) VALUES ('TEST-1', 'Test', 'Test', 1, 10, 'MATURE', .01)")
    conn.commit()
    fabricate_history("TEST-1", "TEST-WH", 7, "steady", conn=conn)
    with pytest.raises(ValueError, match="duplicate sales row"):
        fabricate_history("TEST-1", "TEST-WH", 7, "steady", conn=conn)
    assert len(get_fabrication_log()) >= 1
    assert conn.execute("SELECT COUNT(*) FROM sales_daily WHERE sku='TEST-1'").fetchone()[0] == 7
    conn.close()


def test_warehouse_receipts_and_policy_floor_tools_return_raw_auditable_facts(phase_a_db: Path, monkeypatch):
    from tools import policy_floors, receipts, warehouses

    def connection():
        value = sqlite3.connect(phase_a_db)
        value.row_factory = sqlite3.Row
        return value

    for module in (policy_floors, receipts, warehouses):
        monkeypatch.setattr(module, "_get_db_connection", connection)

    conn = sqlite3.connect(phase_a_db)
    conn.execute("INSERT INTO products (sku, name, category, active) VALUES ('TEST-2', 'Test', 'Test', 1)")
    conn.execute("INSERT INTO warehouses VALUES ('WH-1', 'Warehouse one', 12.5)")
    now = datetime.utcnow()
    for index, late_days in enumerate((2, 4, 6, 8, 10)):
        promised = now - timedelta(days=30 - index)
        received = promised + timedelta(days=late_days)
        conn.execute(
            "INSERT INTO stock_receipts VALUES (?, ?, 'TEST-2', 'WH-1', 'V-1', 10, 10, ?, ?, ?, 5)",
            (f"R-{index}", f"PR-{index}", promised, promised, received),
        )
    conn.commit()
    conn.close()

    floor = policy_floors.set_policy_floor("TEST-2", "WH-1", min_units=20, min_cover_days=5, reason="Contractual SLA", source="contract", set_by="ops")
    assert floor.reason == "Contractual SLA"
    assert policy_floors.get_active_policy_floor("TEST-2", "WH-1").rule_id == floor.rule_id
    assert warehouses.get_warehouse("WH-1").storage_cost_per_m3_month == 12.5
    assert [item.warehouse_id for item in warehouses.list_warehouses()] == ["WH-1"]
    distribution = receipts.get_lateness_distribution("V-1", sku="TEST-2")
    assert distribution.n_observations == 5
    assert distribution.mean_late_days == 6.0
    assert distribution.p90_late_days >= distribution.p50_late_days
