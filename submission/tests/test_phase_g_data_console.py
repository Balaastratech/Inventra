"""
Phase G / G1: the data console's write layer (dataops). Pure functional
tests against an isolated database -- no Streamlit rendering (AppTest is
reserved for the shape assertions the plan calls out; this file exercises
spec, validate, write and read directly, which is what actually enforces
the behaviour).
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from database.seed import init_db
from submission.config import config
from submission.dataops.spec import DERIVED_TABLES, SYSTEM_MANAGED_TABLES, TABLE_SPECS
from submission.dataops.write import WriteRejected, create_row, delete_row, update_row
from submission.dataops.read import count_table_rows, read_change_log, read_table, read_table_row


@pytest.fixture
def db(tmp_path):
    path = tmp_path / "phase-g.db"
    init_db(str(path))
    original = config.database_path
    original_checkpoint = config.checkpointer_path
    object.__setattr__(config, "database_path", str(path))
    object.__setattr__(config, "checkpointer_path", str(tmp_path / "phase-g-checkpoints.sqlite"))
    import sqlite3

    with sqlite3.connect(path) as conn:
        conn.execute("INSERT INTO warehouses VALUES ('WH','Warehouse',10)")
        conn.execute(
            "INSERT INTO products (sku,name,category,active,selling_price,lifecycle,unit_volume_m3) "
            "VALUES ('SKU1','Widget','C',1,100,'MATURE',1)"
        )
        conn.execute(
            "INSERT INTO vendors (vendor_id,name,active,on_time_rate,fill_rate,quality_score,billing_basis) "
            "VALUES ('V1','Vendor One',1,.95,.95,.9,'ORDERED')"
        )
        conn.execute(
            "INSERT INTO inventory_snapshots (snapshot_id,sku,warehouse_id,on_hand,reserved,confirmed_inbound,captured_at) "
            "VALUES ('INV1','SKU1','WH',50,0,0,?)",
            (__import__("datetime").datetime.utcnow().isoformat(),),
        )
    try:
        yield path
    finally:
        object.__setattr__(config, "database_path", original)
        object.__setattr__(config, "checkpointer_path", original_checkpoint)


def test_every_input_table_has_a_spec_and_no_derived_table_does():
    expected_inputs = {
        "products", "warehouses", "inventory_snapshots", "sales_daily", "vendors",
        "vendor_offers", "monthly_budgets", "stock_receipts", "policy_rules",
        "carrying_cost_inputs",
    }
    assert set(TABLE_SPECS.keys()) == expected_inputs
    assert set(DERIVED_TABLES) == {
        "sku_policy", "parked_items", "sweep_runs", "purchase_requests",
        "audit_events", "agent_memory_signals",
    }
    assert not expected_inputs & set(DERIVED_TABLES)
    assert set(SYSTEM_MANAGED_TABLES) == {"vendors", "vendor_offers"}


def test_table_count_supports_pagination_without_loading_all_rows(db):
    assert count_table_rows("products") == 1
    create_row("products", {"sku": "SKU2", "name": "Widget 2", "category": "C", "active": True},
               changed_by="tester")
    assert count_table_rows("products") == 2


def test_row_lookup_finds_the_exact_record_selected_for_an_action(db):
    row = read_table_row("products", "SKU1")
    assert row is not None
    assert row["name"] == "Widget"
    assert read_table_row("products", "NOT-THERE") is None


def test_supplier_master_data_is_not_operator_writable(db):
    with pytest.raises(WriteRejected) as exc:
        create_row("vendors", {"vendor_id": "V2", "name": "Bad", "active": True,
                                "on_time_rate": 1.5, "fill_rate": .9, "quality_score": .9}, changed_by="tester")
    assert any("supplier data source" in e for e in exc.value.errors)


def test_validation_rejects_a_bool_where_an_int_is_required(db):
    with pytest.raises(WriteRejected) as exc:
        create_row("inventory_snapshots", {"sku": "SKU1", "warehouse_id": "WH",
                                            "on_hand": True, "reserved": 0, "confirmed_inbound": 0},
                    changed_by="tester")
    assert any("must be a number" in e for e in exc.value.errors)


def test_supplier_offers_are_not_operator_writable(db):
    with pytest.raises(WriteRejected) as exc:
        create_row("vendor_offers", {"vendor_id": "V-DOES-NOT-EXIST", "sku": "SKU1",
                                      "unit_price": 10, "moq": 1, "lead_time_days": 3,
                                      "valid_until": "2027-01-01"}, changed_by="tester")
    assert any("supplier data source" in e for e in exc.value.errors)


def test_duplicate_sales_day_is_refused_with_an_edit_that_row_message(db):
    create_row("sales_daily", {"sale_date": date(2026, 1, 1), "sku": "SKU1",
                                "warehouse_id": "WH", "units_sold": 5}, changed_by="tester")
    with pytest.raises(WriteRejected) as exc:
        create_row("sales_daily", {"sale_date": date(2026, 1, 1), "sku": "SKU1",
                                    "warehouse_id": "WH", "units_sold": 9}, changed_by="tester")
    assert any("edit that row instead" in e for e in exc.value.errors)


def test_reversed_date_range_and_future_sale_date_are_refused(db):
    with pytest.raises(WriteRejected) as exc:
        create_row("sales_daily", {"sale_date": date.today() + timedelta(days=1), "sku": "SKU1",
                                    "warehouse_id": "WH", "units_sold": 1}, changed_by="tester")
    assert any("future" in e for e in exc.value.errors)

    with pytest.raises(WriteRejected) as exc:
        create_row("policy_rules", {"sku": "SKU1", "warehouse_id": "WH", "min_units": 5,
                                     "reason": "test", "source": "test", "set_by": "tester",
                                     "effective_from": date(2026, 6, 1), "effective_to": date(2026, 1, 1),
                                     "active": True}, changed_by="tester")
    assert any("effective_to cannot be before" in e for e in exc.value.errors)


def test_selling_price_below_landed_cost_warns_but_writes(db):
    # Supplier quotes arrive through the source integration, not the operator
    # write layer being tested here.
    import sqlite3
    with sqlite3.connect(db) as conn:
        conn.execute(
            "INSERT INTO vendor_offers (offer_id,vendor_id,sku,unit_price,moq,lead_time_days,valid_until) VALUES ('O1','V1','SKU1',500,1,3,'2027-01-01')"
        )
    after = update_row("products", "SKU1", {"selling_price": 50}, changed_by="tester")
    assert after["selling_price"] == 50
    log = read_change_log(table="products")
    assert any("below the cheapest landed cost" in (row["note"] or "") for row in log)


def test_deleting_a_referenced_product_is_refused_with_the_dependent_count(db):
    create_row("sales_daily", {"sale_date": date(2026, 1, 2), "sku": "SKU1",
                                "warehouse_id": "WH", "units_sold": 3}, changed_by="tester")
    with pytest.raises(WriteRejected) as exc:
        delete_row("products", "SKU1", changed_by="tester")
    assert any("sales_daily" in e for e in exc.value.errors)


def test_a_rejected_multi_field_edit_leaves_the_row_unchanged(db):
    create_row("warehouses", {"warehouse_id": "WH2", "name": "Two", "storage_cost_per_m3_month": 5},
               changed_by="tester")
    before = read_table("warehouses")
    with pytest.raises(WriteRejected):
        update_row("warehouses", "WH2", {"storage_cost_per_m3_month": -1}, changed_by="tester")
    after = read_table("warehouses")
    assert before == after


def test_every_write_records_a_data_change_log_row_with_before_and_after(db):
    create_row("warehouses", {"warehouse_id": "WH3", "name": "Three", "storage_cost_per_m3_month": 5},
               changed_by="alice")
    update_row("warehouses", "WH3", {"storage_cost_per_m3_month": 9}, changed_by="alice")
    log = read_change_log(table="warehouses")
    assert {row["action"] for row in log} == {"CREATE", "UPDATE"}
    update_entry = next(r for r in log if r["action"] == "UPDATE")
    assert update_entry["changed_by"] == "alice"
    assert "5" in update_entry["before_json"]
    assert "9" in update_entry["after_json"]


def test_a_write_without_an_operator_name_is_refused(db):
    with pytest.raises(WriteRejected):
        create_row("warehouses", {"warehouse_id": "WH4", "name": "Four", "storage_cost_per_m3_month": 5},
                   changed_by="")


def test_derived_tables_expose_no_write_function(db):
    for table in DERIVED_TABLES:
        with pytest.raises(WriteRejected):
            create_row(table, {"anything": 1}, changed_by="tester")


def test_backfilling_the_named_range_then_rerunning_produces_a_proposal_from_the_new_rows(db):
    """The R11 keystone test, following the same fresh-run pattern as
    test_phase_e_insufficient_data_loop.py's
    test_backfill_then_fresh_graph_run_uses_the_configured_database: a case
    that pauses on thin history is re-run from scratch (DG9) after real rows
    are written through dataops, and the number the graph reads back
    (get_sales_velocity's window average) matches what was just written --
    proving it came from a database re-read, not a value carried in memory."""
    from domain.tool_models import ProposalStatus
    from submission.graph.workflow import compile_graph
    from submission.state.state import create_initial_state

    # Thin history: 1 observation -> INSUFFICIENT_DATA.
    create_row("sales_daily", {"sale_date": date.today() - timedelta(days=1), "sku": "SKU1",
                                "warehouse_id": "WH", "units_sold": 4}, changed_by="tester")

    graph, conn = compile_graph()
    try:
        first = create_initial_state("SKU1", "WH")
        first_result = graph.invoke(first, config={"configurable": {"thread_id": first["thread_id"]}})
    finally:
        conn.close()
    assert first_result["status"] is ProposalStatus.NEEDS_INFORMATION
    assert first_result["sales"].error is not None

    # Backfill a real, named 30-day range through dataops at a known rate.
    start = date.today() - timedelta(days=30)
    end = date.today() - timedelta(days=2)  # day-1 already has a row (4 units)
    for offset in range((end - start).days + 1):
        d = start + timedelta(days=offset)
        create_row("sales_daily", {"sale_date": d, "sku": "SKU1", "warehouse_id": "WH", "units_sold": 6},
                   changed_by="tester")

    graph, conn = compile_graph()
    try:
        retry = create_initial_state("SKU1", "WH")
        retry_result = graph.invoke(retry, config={"configurable": {"thread_id": retry["thread_id"]}})
    finally:
        conn.close()

    # The fresh run re-read sales_daily and now has enough observations.
    assert retry_result["sales"].error is None
    # 29 days at 6 units + 1 day at 4 units, over a 30-day window.
    expected = (29 * 6 + 4) / 30
    assert retry_result["sales"].window_30_days == pytest.approx(expected, abs=0.01)


def test_migration_is_idempotent_for_data_change_log(tmp_path):
    from database.migrate import apply_migrations

    path = tmp_path / "legacy2.db"
    init_db(str(path))
    import sqlite3

    with sqlite3.connect(path) as conn:
        conn.execute("DROP TABLE IF EXISTS data_change_log")
        conn.execute("DROP TABLE IF EXISTS notification_deliveries")
        conn.commit()

    first = apply_migrations(str(path))
    assert "data_change_log" in first
    assert "notification_deliveries" in first
    assert apply_migrations(str(path)) == []
