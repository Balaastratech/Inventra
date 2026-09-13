#!/usr/bin/env python
"""
Idempotent, additive migrations for an existing inventra.db.

Run: python database/migrate.py

Why this exists separately from schema.sql: schema.sql is the source of
truth, but database/seed.py's init_db() applies it by *deleting and
recreating* the database. That is right for tests (reset_db.py wants a known
starting point) and wrong for a database that already holds real audit
history and purchase requests someone cares about.

Every migration here must be safe to run repeatedly -- check first, then
alter -- so running it twice is a no-op rather than an error. Nothing here
drops or rewrites data.
"""

from __future__ import annotations

import sqlite3
import sys

# (table, column, column definition) -- appended with ALTER TABLE ADD COLUMN
# only when the column is absent. SQLite cannot add a NOT NULL column without
# a default, so everything here is nullable by design.
_ADDITIVE_COLUMNS = [
    # B3: cancelling a PENDING purchase request.
    ("purchase_requests", "cancelled_at", "TIMESTAMP"),
    ("purchase_requests", "cancelled_by", "TEXT"),
    ("purchase_requests", "cancel_reason", "TEXT"),
    # Budget reservation: the month create_purchase_request committed
    # against, so cancel_purchase_request releases the same month.
    ("purchase_requests", "committed_budget_month", "TEXT"),
    # Phase D: reminders while a created request awaits vendor-send approval.
    ("purchase_requests", "vendor_reminder_count", "INTEGER DEFAULT 0"),
    ("purchase_requests", "vendor_last_reminded_at", "TIMESTAMP"),
    # Phase A: measured economics inputs.
    ("products", "selling_price", "REAL"),
    ("products", "lifecycle", "TEXT"),
    ("products", "unit_volume_m3", "REAL"),
    ("vendors", "billing_basis", "TEXT"),
    ("vendors", "payment_terms_days", "INTEGER"),
    ("vendor_offers", "freight_flat", "REAL"),
    ("vendor_offers", "freight_per_unit", "REAL"),
    ("sku_policy", "statistical_target_units", "REAL"),
    ("sku_policy", "active_target_units", "REAL"),
]

_ADDITIVE_TABLES = [
    ("warehouses", "CREATE TABLE IF NOT EXISTS warehouses (warehouse_id TEXT PRIMARY KEY, name TEXT NOT NULL, storage_cost_per_m3_month REAL NOT NULL)"),
    ("stock_receipts", "CREATE TABLE IF NOT EXISTS stock_receipts (receipt_id TEXT PRIMARY KEY, request_id TEXT, sku TEXT NOT NULL, warehouse_id TEXT NOT NULL, vendor_id TEXT NOT NULL, quantity_ordered INTEGER NOT NULL, quantity_received INTEGER NOT NULL, ordered_at TIMESTAMP NOT NULL, promised_at TIMESTAMP NOT NULL, received_at TIMESTAMP NOT NULL, lead_time_days_actual REAL NOT NULL)"),
    ("sku_policy", "CREATE TABLE IF NOT EXISTS sku_policy (sku TEXT NOT NULL, warehouse_id TEXT NOT NULL, as_of_date DATE NOT NULL, mean_daily_demand REAL, std_daily_demand REAL, cv REAL, adi REAL, cv_squared REAL, demand_quadrant TEXT, abc_class TEXT, xyz_class TEXT, consumption_value_12m REAL, cumulative_share REAL, service_level REAL, safety_stock_units REAL, reorder_point_units REAL, derived_cover_days REAL, statistical_target_units REAL, active_target_units REAL, maturity TEXT, confidence REAL, candidate_class TEXT, candidate_since DATE, consecutive_confirmations INTEGER, active_class TEXT, change_reason TEXT, UNIQUE(sku, warehouse_id, as_of_date))"),
    ("policy_rules", "CREATE TABLE IF NOT EXISTS policy_rules (rule_id TEXT PRIMARY KEY, sku TEXT NOT NULL, warehouse_id TEXT NOT NULL, min_units INTEGER, min_cover_days REAL, reason TEXT NOT NULL, source TEXT NOT NULL, set_by TEXT NOT NULL, effective_from DATE NOT NULL, effective_to DATE, active BOOLEAN NOT NULL DEFAULT 1)"),
    ("parked_items", "CREATE TABLE IF NOT EXISTS parked_items (park_id TEXT PRIMARY KEY, sku TEXT NOT NULL, warehouse_id TEXT NOT NULL, reason TEXT NOT NULL, parked_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP, resolved_at TIMESTAMP, resolved_by TEXT, note TEXT)"),
    ("sweep_runs", "CREATE TABLE IF NOT EXISTS sweep_runs (sweep_id TEXT PRIMARY KEY, started_at TIMESTAMP NOT NULL, completed_at TIMESTAMP, warehouse_ids TEXT NOT NULL, pairs_examined INTEGER NOT NULL DEFAULT 0, candidates_found INTEGER NOT NULL DEFAULT 0, parked_count INTEGER NOT NULL DEFAULT 0, deferred_for_budget_count INTEGER NOT NULL DEFAULT 0, cases_opened INTEGER NOT NULL DEFAULT 0, reminders_sent INTEGER NOT NULL DEFAULT 0, total_model_calls_estimate INTEGER NOT NULL DEFAULT 0, detail_json TEXT)"),
    ("carrying_cost_inputs", "CREATE TABLE IF NOT EXISTS carrying_cost_inputs (input_id TEXT PRIMARY KEY, cost_of_capital_annual_rate REAL NOT NULL, insurance_annual_rate REAL NOT NULL, shrinkage_annual_rate REAL NOT NULL, effective_from DATE NOT NULL UNIQUE, set_by TEXT NOT NULL, note TEXT)"),
    # Phase G / DG5: durable change log for the data console (fabricator._LOG
    # is in-memory only and does not survive a restart).
    ("data_change_log", "CREATE TABLE IF NOT EXISTS data_change_log (change_id TEXT PRIMARY KEY, changed_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP, changed_by TEXT NOT NULL, table_name TEXT NOT NULL, row_key TEXT NOT NULL, action TEXT NOT NULL, before_json TEXT, after_json TEXT, note TEXT)"),
    ("notification_deliveries", "CREATE TABLE IF NOT EXISTS notification_deliveries (case_id TEXT NOT NULL, event_type TEXT NOT NULL, fingerprint TEXT NOT NULL, sent_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP, PRIMARY KEY (case_id, event_type, fingerprint))"),
]


def _existing_columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}


def apply_migrations(db_path: str = "database/inventra.db") -> list[str]:
    """Bring db_path up to date with schema.sql's additive columns.

    Returns the list of changes actually applied, so callers (and the CLI
    below) can report "already up to date" honestly instead of implying work
    was done.
    """
    applied: list[str] = []
    conn = sqlite3.connect(db_path)
    try:
        for table, statement in _ADDITIVE_TABLES:
            if table not in {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}:
                conn.execute(statement)
                applied.append(table)
        for table, column, coltype in _ADDITIVE_COLUMNS:
            if not _existing_columns(conn, table):
                # Table absent entirely: this database predates it, and
                # creating it here would duplicate schema.sql. Skip loudly.
                print(f"  skipped {table}.{column}: table {table} does not exist", file=sys.stderr)
                continue
            if column in _existing_columns(conn, table):
                continue
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {coltype}")
            applied.append(f"{table}.{column}")
        conn.commit()
    finally:
        conn.close()
    return applied


if __name__ == "__main__":
    path = sys.argv[1] if len(sys.argv) > 1 else "database/inventra.db"
    print(f"Migrating {path}")
    changes = apply_migrations(path)
    if changes:
        for change in changes:
            print(f"  added {change}")
        print(f"{len(changes)} column(s) added.")
    else:
        print("Already up to date; nothing to do.")
