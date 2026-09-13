"""
Additive test fixtures (PLAN.md D5). Never edits database/inventra.db's
provided rows or database/seed.py -- only INSERTs new, isolated
SKU+warehouse combinations so tests can exercise distinct approval flows
without colliding on case_id (which is derived from sku+warehouse_id alone,
so every automated test needs its own pair) or fighting over shared budget
rows (DEL-01's budget is shared by several starter-package scenarios; a
test that mutates it to simulate a concurrent spend would corrupt other
tests reading the same row).

Idempotent: safe to run against a freshly reseeded database.sqlite as many
times as needed (checks before inserting).
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta

DB_PATH = "database/inventra.db"

# (sku, warehouse_id, on_hand, reserved, daily_units_sold, purpose)
# Each clones an existing SKU's product/vendor-offer data onto a fresh,
# isolated warehouse -- vendor_offers and vendors are keyed by sku only
# (no warehouse_id column in schema.sql), so an existing SKU's offers apply
# automatically; only inventory/sales/budget need a new row per warehouse.
EXTRA_CASES = [
    ("AC-003", "DEL-02", 20, 5, 2, "revalidation/budget-change test (isolated, safe to mutate)"),
    ("AC-004", "DEL-03", 15, 3, 3, "write-failure test (monkeypatched write tool)"),
    ("AC-001", "DEL-04", 50, 10, 3, "human-rejection test"),
    ("AC-003", "DEL-05", 20, 5, 2, "email approval-link end-to-end test"),
    ("AC-003", "DEL-06", 20, 5, 2, "Phase 4: repair-then-succeed retry test"),
    ("AC-003", "DEL-07", 20, 5, 2, "Phase 4: attempts-exhausted fail-closed test"),
    ("AC-003", "DEL-08", 20, 5, 2, "Phase 4: semantic-validation-failure test"),
    ("AC-003", "DEL-10", 20, 5, 2, "Gap 1: NEEDS_INFORMATION pause/resume test"),
    ("AC-003", "DEL-13", 20, 5, 2, "Gap 7: REVISE-from-email round trip test"),
    ("AC-003", "DEL-14", 20, 5, 2, "Gap 9: agent memory write-path test"),
    ("AC-003", "DEL-15", 20, 5, 2, "Gap 9: agent memory read-path (second case) test"),
    ("AC-003", "DEL-16", 20, 5, 2, "Gap 8: vendor send disabled-by-default test"),
    ("AC-003", "DEL-17", 20, 5, 2, "Gap 8: vendor send enabled/idempotency test"),
    ("AC-003", "DEL-18", 20, 5, 2, "budget reservation/release test"),
    ("AC-003", "DEL-19", 20, 5, 2, "idempotency-key approver-independence test"),
    ("AC-003", "DEL-20", 20, 5, 2, "reorder guard test"),
    ("AC-003", "DEL-21", 20, 5, 2, "policy checklist repair-retry test"),
]

# Scenario 11 needs genuinely <3 sales observations in both windows -- no
# existing SKU produces that (AC-005's "new SKU" fixture actually has 6-14
# observations, PLAN.md defect #4). Handled separately from EXTRA_CASES
# since it needs a *sparse* sales history, not the standard 30-day one.
INSUFFICIENT_HISTORY_CASE = ("AC-003", "DEL-09")

# The two "disagreeing sales trends" tests used to point at AC-001/DEL-01
# and AC-001/DEL-04, which only disagreed because of the 2026-09-11
# tools/sales.py window-boundary bug -- every starter SKU sells at a
# genuinely uniform daily rate, so once that bug was fixed the 7-day and
# 30-day windows agree exactly and there is nothing left to disagree about.
# This fixture creates *real* disagreement instead: demand that actually
# slowed down recently, not a rounding artifact. 40 available, 4/day for
# the older 23 days (30-day average ~3.5, at risk against a 14-day target)
# and 2/day for the most recent 7 (7-day average 2.0, healthy).
TRENDING_CASE = ("AC-001", "DEL-22", 40, 0)


def _exists(conn, table, where, params):
    return conn.execute(f"SELECT 1 FROM {table} WHERE {where} LIMIT 1", params).fetchone() is not None


def _add_case(conn, now, sku, warehouse_id, on_hand, reserved, daily_units):
    if not _exists(conn, "inventory_snapshots", "sku=? AND warehouse_id=?", (sku, warehouse_id)):
        conn.execute(
            "INSERT INTO inventory_snapshots (snapshot_id, sku, warehouse_id, on_hand, reserved, "
            "confirmed_inbound, captured_at) VALUES (?,?,?,?,?,?,?)",
            (f"INV-{sku}-{warehouse_id}-1", sku, warehouse_id, on_hand, reserved, 0, now - timedelta(minutes=45)),
        )
    if not _exists(conn, "sales_daily", "sku=? AND warehouse_id=?", (sku, warehouse_id)):
        for i in range(30):
            conn.execute(
                "INSERT INTO sales_daily (sale_id, sale_date, sku, warehouse_id, units_sold) VALUES (?,?,?,?,?)",
                (f"SALE-{sku}-{warehouse_id}-{i}", (now - timedelta(days=30 - i)).date(), sku, warehouse_id, daily_units),
            )
    month = now.strftime("%Y-%m")
    if not _exists(conn, "monthly_budgets", "warehouse_id=? AND month=?", (warehouse_id, month)):
        conn.execute(
            "INSERT INTO monthly_budgets (budget_id, warehouse_id, month, budget_amount, spent_amount, "
            "committed_amount, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?)",
            (f"BUDGET-{warehouse_id}-{month}", warehouse_id, month, 50000, 30000, 5000, now, now),
        )


def _add_sparse_sales_case(conn, now, sku, warehouse_id, on_hand=20, reserved=5):
    """Scenario 11: only 2 sales_daily rows, both inside the last 7 days --
    below get_sales_velocity()'s <3-observation INSUFFICIENT_DATA threshold
    in *both* windows, unlike AC-005 which has plenty of history."""
    if not _exists(conn, "inventory_snapshots", "sku=? AND warehouse_id=?", (sku, warehouse_id)):
        conn.execute(
            "INSERT INTO inventory_snapshots (snapshot_id, sku, warehouse_id, on_hand, reserved, "
            "confirmed_inbound, captured_at) VALUES (?,?,?,?,?,?,?)",
            (f"INV-{sku}-{warehouse_id}-1", sku, warehouse_id, on_hand, reserved, 0, now - timedelta(minutes=45)),
        )
    if not _exists(conn, "sales_daily", "sku=? AND warehouse_id=?", (sku, warehouse_id)):
        for i in range(2):
            conn.execute(
                "INSERT INTO sales_daily (sale_id, sale_date, sku, warehouse_id, units_sold) VALUES (?,?,?,?,?)",
                (f"SALE-{sku}-{warehouse_id}-{i}", (now - timedelta(days=i + 1)).date(), sku, warehouse_id, 2),
            )
    month = now.strftime("%Y-%m")
    if not _exists(conn, "monthly_budgets", "warehouse_id=? AND month=?", (warehouse_id, month)):
        conn.execute(
            "INSERT INTO monthly_budgets (budget_id, warehouse_id, month, budget_amount, spent_amount, "
            "committed_amount, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?)",
            (f"BUDGET-{warehouse_id}-{month}", warehouse_id, month, 50000, 30000, 5000, now, now),
        )


def _add_trending_case(conn, now, sku, warehouse_id, on_hand, reserved, recent_rate, older_rate):
    """Genuinely time-varying demand: the most recent 7 (complete) days sell
    at `recent_rate`, the 23 days before that at `older_rate` -- so the
    7-day and 30-day windows disagree for a real reason, not a boundary
    bug. Dates run today-30 ... today-1 (matches tools/sales.py's window,
    which excludes today -- see the 2026-09-11 fix)."""
    if not _exists(conn, "inventory_snapshots", "sku=? AND warehouse_id=?", (sku, warehouse_id)):
        conn.execute(
            "INSERT INTO inventory_snapshots (snapshot_id, sku, warehouse_id, on_hand, reserved, "
            "confirmed_inbound, captured_at) VALUES (?,?,?,?,?,?,?)",
            (f"INV-{sku}-{warehouse_id}-1", sku, warehouse_id, on_hand, reserved, 0, now - timedelta(minutes=45)),
        )
    if not _exists(conn, "sales_daily", "sku=? AND warehouse_id=?", (sku, warehouse_id)):
        for days_ago in range(30, 0, -1):
            rate = recent_rate if days_ago <= 7 else older_rate
            conn.execute(
                "INSERT INTO sales_daily (sale_id, sale_date, sku, warehouse_id, units_sold) VALUES (?,?,?,?,?)",
                (f"SALE-{sku}-{warehouse_id}-{days_ago}", (now - timedelta(days=days_ago)).date(), sku, warehouse_id, rate),
            )
    month = now.strftime("%Y-%m")
    if not _exists(conn, "monthly_budgets", "warehouse_id=? AND month=?", (warehouse_id, month)):
        conn.execute(
            "INSERT INTO monthly_budgets (budget_id, warehouse_id, month, budget_amount, spent_amount, "
            "committed_amount, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?)",
            (f"BUDGET-{warehouse_id}-{month}", warehouse_id, month, 50000, 30000, 5000, now, now),
        )


def _populate_vendor_contact_emails(conn: sqlite3.Connection) -> None:
    """Gap 8's vendor-send capability is unreachable without a contact
    address on file. contact_email is a column we added (schema.sql), not
    part of the provided seed data, so setting it here is additive -- it
    fills in a value the starter package never populated, not an edit to a
    provided business fact. Idempotent: only fills rows that are still
    NULL, so re-running this doesn't clobber anything real."""
    conn.execute(
        "UPDATE vendors SET contact_email = LOWER(vendor_id) || '@example-vendor.test' "
        "WHERE contact_email IS NULL"
    )


def seed_extra(db_path: str = DB_PATH) -> None:
    conn = sqlite3.connect(db_path)
    now = datetime.utcnow()
    for sku, warehouse_id, on_hand, reserved, daily_units, _purpose in EXTRA_CASES:
        _add_case(conn, now, sku, warehouse_id, on_hand, reserved, daily_units)
    _add_sparse_sales_case(conn, now, *INSUFFICIENT_HISTORY_CASE)
    _add_trending_case(conn, now, *TRENDING_CASE, recent_rate=2, older_rate=4)
    _populate_vendor_contact_emails(conn)
    conn.commit()
    conn.close()


if __name__ == "__main__":
    seed_extra()
    print(f"Additive test fixtures ready ({len(EXTRA_CASES)} isolated cases).")
