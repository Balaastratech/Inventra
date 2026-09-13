"""Deterministic, explainable data fabricator for Phase A demo scenarios."""

from __future__ import annotations

import math
import random
import sqlite3
import uuid
from datetime import datetime, timedelta

_RNG = random.Random(42)
_LOG: list[dict] = []


def get_fabrication_log() -> list[dict]:
    return list(_LOG)


def _log(action: str, **details) -> None:
    _LOG.append({"at": datetime.utcnow().isoformat(), "action": action, **details})


def _connection(conn: sqlite3.Connection | None):
    return conn, conn is None


def _insert_or_raise(conn: sqlite3.Connection, sql: str, params: tuple, *, duplicate_label: str | None = None) -> None:
    try:
        conn.execute(sql, params)
    except sqlite3.IntegrityError as exc:
        if duplicate_label and "sales_daily" in str(exc):
            raise ValueError(f"duplicate sales row refused: {duplicate_label}") from exc
        raise


def _demand(profile: str, day: int, days: int) -> int:
    configs = {
        "legacy-3": (3, 0.0, 0.0, 0.0, 0.0), "legacy-2": (2, 0.0, 0.0, 0.0, 0.0),
        "steady": (8, 0.0, 0.05, 0.0, 0.0), "trending-up": (4, 0.02, .10, 0.0, 0.0),
        "trending-down": (12, -0.015, .08, 0.0, 0.0), "seasonal": (8, 0.0, .08, .45, 0.0),
        "promo-spiky": (5, 0.0, .12, 0.0, 0.0), "intermittent": (3, 0.0, .1, 0.0, .62),
        "lumpy": (18, 0.0, .2, 0.0, .78), "brand-new": (6, .01, .1, 0.0, 0.0),
        "dead-eol": (9, -.04, .08, 0.0, 0.0),
    }
    if profile not in configs:
        raise ValueError(f"unknown demand profile: {profile}")
    base, trend, noise, seasonal, zero_probability = configs[profile]
    if profile == "brand-new" and day < days - 42:
        return 0
    if profile == "dead-eol" and day > days * .75:
        return 0
    value = base + trend * day + base * seasonal * math.sin(2 * math.pi * day / 365)
    value *= 1.10 if day % 7 in (1, 2, 3, 4, 5) else .80
    if profile == "promo-spiky" and day % 90 in range(5):
        value *= 4
    if _RNG.random() < zero_probability:
        return 0
    return max(0, round(value * (1 + _RNG.gauss(0, noise))))


def fabricate_history(sku: str, warehouse_id: str, days: int, profile: str,
                      conn: sqlite3.Connection | None = None) -> None:
    if days <= 0:
        raise ValueError("days must be positive")
    if conn is None:
        conn = sqlite3.connect("database/inventra.db")
        close = True
    else:
        close = False
    try:
        yesterday = datetime.utcnow().date() - timedelta(days=1)
        for offset in range(days):
            sale_date = yesterday - timedelta(days=days - 1 - offset)
            _insert_or_raise(conn, "INSERT INTO sales_daily (sale_id, sale_date, sku, warehouse_id, units_sold) VALUES (?, ?, ?, ?, ?)",
                             (f"SALE-{sku}-{warehouse_id}-{sale_date.isoformat()}", sale_date, sku, warehouse_id,
                              _demand(profile, offset, days)),
                             duplicate_label=f"{sale_date}/{sku}/{warehouse_id}")
        conn.commit()
        _log("fabricate_history", sku=sku, warehouse_id=warehouse_id, days=days, profile=profile)
    finally:
        if close:
            conn.close()


def backfill_missing_sales(
    sku: str,
    warehouse_id: str,
    start_date,
    end_date,
    units_per_day: int,
    conn: sqlite3.Connection | None = None,
) -> int:
    """Fill absent daily-sales rows in an inclusive date range.

    Unlike :func:`fabricate_history`, this deliberately treats an existing
    row as success: it is for repairing a partial history, not replacing it.
    Returns the number of rows inserted.
    """
    if end_date < start_date:
        raise ValueError("end_date must not precede start_date")
    if units_per_day < 0:
        raise ValueError("units_per_day must not be negative")
    own = conn is None
    if conn is None:
        from submission.config import config

        conn = sqlite3.connect(config.database_path)
    try:
        added = 0
        day = start_date
        while day <= end_date:
            cursor = conn.execute(
                """INSERT OR IGNORE INTO sales_daily
                   (sale_id, sale_date, sku, warehouse_id, units_sold)
                   VALUES (?, ?, ?, ?, ?)""",
                (f"SALE-{sku}-{warehouse_id}-{day.isoformat()}", day.isoformat(), sku, warehouse_id, units_per_day),
            )
            added += cursor.rowcount
            day += timedelta(days=1)
        if own:
            conn.commit()
        _log("backfill_missing_sales", sku=sku, warehouse_id=warehouse_id,
             start=str(start_date), end=str(end_date), added=added)
        return added
    finally:
        if own:
            conn.close()


def set_position(sku: str, warehouse_id: str, on_hand: int, reserved: int = 0,
                 confirmed_inbound: int = 0, conn: sqlite3.Connection | None = None) -> None:
    own = conn is None
    conn = conn or sqlite3.connect("database/inventra.db")
    try:
        now = datetime.utcnow()
        conn.execute("INSERT INTO inventory_snapshots VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                     (f"INV-{uuid.uuid4().hex[:12]}", sku, warehouse_id, on_hand, reserved,
                      confirmed_inbound, now, now))
        if own: conn.commit()
        _log("set_position", sku=sku, warehouse_id=warehouse_id, on_hand=on_hand)
    finally:
        if own: conn.close()


def set_cover_days(sku: str, warehouse_id: str, days: float, conn: sqlite3.Connection | None = None) -> None:
    own = conn is None
    conn = conn or sqlite3.connect("database/inventra.db")
    try:
        end = datetime.utcnow().date() - timedelta(days=1)
        start = end - timedelta(days=29)
        total = conn.execute("SELECT COALESCE(SUM(units_sold), 0) FROM sales_daily WHERE sku=? AND warehouse_id=? AND sale_date BETWEEN ? AND ?", (sku, warehouse_id, start, end)).fetchone()[0]
        set_position(sku, warehouse_id, math.ceil(total / 30 * days), conn=conn)
    finally:
        if own:
            conn.commit(); conn.close()


def age_snapshot(sku: str, warehouse_id: str, hours: float, conn: sqlite3.Connection | None = None) -> None:
    own = conn is None; conn = conn or sqlite3.connect("database/inventra.db")
    try:
        row = conn.execute("SELECT snapshot_id FROM inventory_snapshots WHERE sku=? AND warehouse_id=? ORDER BY captured_at DESC LIMIT 1", (sku, warehouse_id)).fetchone()
        if not row: raise ValueError("no inventory snapshot to age")
        conn.execute("UPDATE inventory_snapshots SET captured_at=? WHERE snapshot_id=?", (datetime.utcnow() - timedelta(hours=hours), row[0]))
        if own: conn.commit()
        _log("age_snapshot", sku=sku, warehouse_id=warehouse_id, hours=hours)
    finally:
        if own: conn.close()


def expire_offer(offer_id: str, conn: sqlite3.Connection | None = None) -> None:
    _update("vendor_offers", "valid_until", datetime.utcnow() - timedelta(days=1), "offer_id", offer_id, conn, "expire_offer")


def set_vendor_reliability(vendor_id: str, on_time_rate=None, fill_rate=None, quality_score=None, conn=None) -> None:
    own = conn is None; conn = conn or sqlite3.connect("database/inventra.db")
    try:
        for column, value in (("on_time_rate", on_time_rate), ("fill_rate", fill_rate), ("quality_score", quality_score)):
            if value is not None: conn.execute(f"UPDATE vendors SET {column}=? WHERE vendor_id=?", (value, vendor_id))
        if own: conn.commit()
        _log("set_vendor_reliability", vendor_id=vendor_id)
    finally:
        if own: conn.close()


def _update(table, column, value, key, key_value, conn, action):
    own = conn is None; conn = conn or sqlite3.connect("database/inventra.db")
    try:
        conn.execute(f"UPDATE {table} SET {column}=? WHERE {key}=?", (value, key_value))
        if own: conn.commit()
        _log(action, **{key: key_value})
    finally:
        if own: conn.close()


def set_budget(warehouse_id, month, amount, spent=0, committed=0, conn=None):
    own = conn is None; conn = conn or sqlite3.connect("database/inventra.db")
    try:
        now = datetime.utcnow(); conn.execute("INSERT OR REPLACE INTO monthly_budgets VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (f"BUDGET-{warehouse_id}-{month}", warehouse_id, month, amount, spent, committed, now, now))
        if own: conn.commit()
        _log("set_budget", warehouse_id=warehouse_id, month=month)
    finally:
        if own: conn.close()


def upsert_warehouse(warehouse_id, name, storage_cost_per_m3_month, conn=None):
    own = conn is None; conn = conn or sqlite3.connect("database/inventra.db")
    try:
        conn.execute("INSERT OR REPLACE INTO warehouses VALUES (?, ?, ?)", (warehouse_id, name, storage_cost_per_m3_month))
        if own: conn.commit()
        _log("upsert_warehouse", warehouse_id=warehouse_id)
    finally:
        if own: conn.close()


def set_selling_price(sku, price, conn=None): _update("products", "selling_price", price, "sku", sku, conn, "set_selling_price")
def set_storage_cost(warehouse_id, rate, conn=None): _update("warehouses", "storage_cost_per_m3_month", rate, "warehouse_id", warehouse_id, conn, "set_storage_cost")
def set_billing_basis(vendor_id, basis, conn=None):
    if basis not in {"ORDERED", "SHIPPED"}: raise ValueError("billing basis must be ORDERED or SHIPPED")
    _update("vendors", "billing_basis", basis, "vendor_id", vendor_id, conn, "set_billing_basis")
def set_freight(offer_id, flat, per_unit, conn=None):
    own = conn is None; conn = conn or sqlite3.connect("database/inventra.db")
    try:
        conn.execute("UPDATE vendor_offers SET freight_flat=?, freight_per_unit=? WHERE offer_id=?", (flat, per_unit, offer_id))
        if own: conn.commit()
        _log("set_freight", offer_id=offer_id)
    finally:
        if own: conn.close()


def set_carrying_inputs(capital, insurance, shrinkage, set_by="finance", note="", effective_from=None, conn=None):
    own = conn is None; conn = conn or sqlite3.connect("database/inventra.db")
    try:
        conn.execute("INSERT OR REPLACE INTO carrying_cost_inputs VALUES (?, ?, ?, ?, ?, ?, ?)",
                     (f"CCI-{uuid.uuid4().hex[:12]}", capital, insurance, shrinkage, (effective_from or datetime.utcnow().date()).isoformat(), set_by, note))
        if own: conn.commit()
        _log("set_carrying_inputs")
    finally:
        if own: conn.close()


def add_receipt(*args, conn=None, **kwargs):
    from tools.receipts import record_receipt
    result = record_receipt(*args, conn=conn, **kwargs)
    _log("add_receipt", receipt_id=result.receipt_id)
    return result


# ---------------------------------------------------------------------------
# Phase G CRUD primitives -- the fabricator was scenario-shaped, not
# CRUD-shaped (create/delete for products/vendors/offers, an editable
# sales_daily row, lifecycle/unit_volume_m3 setters, policy-rule deactivate).
# submission/dataops/write.py delegates to these rather than duplicating SQL.
# ---------------------------------------------------------------------------

def create_product(sku, name, category, *, active=True, selling_price=None,
                    lifecycle=None, unit_volume_m3=None, conn=None):
    own = conn is None; conn = conn or sqlite3.connect("database/inventra.db")
    try:
        conn.execute(
            "INSERT INTO products (sku,name,category,active,selling_price,lifecycle,unit_volume_m3) VALUES (?,?,?,?,?,?,?)",
            (sku, name, category, int(bool(active)), selling_price, lifecycle, unit_volume_m3),
        )
        if own: conn.commit()
        _log("create_product", sku=sku)
    finally:
        if own: conn.close()


def delete_product(sku, conn=None):
    own = conn is None; conn = conn or sqlite3.connect("database/inventra.db")
    try:
        conn.execute("DELETE FROM products WHERE sku=?", (sku,))
        if own: conn.commit()
        _log("delete_product", sku=sku)
    finally:
        if own: conn.close()


def set_product_lifecycle(sku, lifecycle, conn=None):
    if lifecycle not in {"NEW", "GROWTH", "MATURE", "DECLINING", "EOL"}:
        raise ValueError("lifecycle must be NEW|GROWTH|MATURE|DECLINING|EOL")
    _update("products", "lifecycle", lifecycle, "sku", sku, conn, "set_product_lifecycle")


def set_unit_volume(sku, unit_volume_m3, conn=None):
    _update("products", "unit_volume_m3", unit_volume_m3, "sku", sku, conn, "set_unit_volume")


def create_vendor(vendor_id, name, *, active=True, on_time_rate=1.0, fill_rate=1.0,
                   quality_score=1.0, billing_basis="ORDERED", payment_terms_days=None,
                   notes=None, contact_email=None, conn=None):
    own = conn is None; conn = conn or sqlite3.connect("database/inventra.db")
    try:
        conn.execute(
            """INSERT INTO vendors (vendor_id,name,active,on_time_rate,fill_rate,quality_score,notes,
                                    contact_email,billing_basis,payment_terms_days)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (vendor_id, name, int(bool(active)), on_time_rate, fill_rate, quality_score,
             notes, contact_email, billing_basis, payment_terms_days),
        )
        if own: conn.commit()
        _log("create_vendor", vendor_id=vendor_id)
    finally:
        if own: conn.close()


def delete_vendor(vendor_id, conn=None):
    own = conn is None; conn = conn or sqlite3.connect("database/inventra.db")
    try:
        conn.execute("DELETE FROM vendors WHERE vendor_id=?", (vendor_id,))
        if own: conn.commit()
        _log("delete_vendor", vendor_id=vendor_id)
    finally:
        if own: conn.close()


def create_vendor_offer(offer_id, vendor_id, sku, unit_price, moq, lead_time_days,
                         valid_until, *, freight_flat=None, freight_per_unit=None, conn=None):
    own = conn is None; conn = conn or sqlite3.connect("database/inventra.db")
    try:
        conn.execute(
            """INSERT INTO vendor_offers (offer_id,vendor_id,sku,unit_price,moq,lead_time_days,
                                          valid_until,freight_flat,freight_per_unit)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (offer_id, vendor_id, sku, unit_price, moq, lead_time_days,
             valid_until, freight_flat, freight_per_unit),
        )
        if own: conn.commit()
        _log("create_vendor_offer", offer_id=offer_id)
    finally:
        if own: conn.close()


def delete_vendor_offer(offer_id, conn=None):
    own = conn is None; conn = conn or sqlite3.connect("database/inventra.db")
    try:
        conn.execute("DELETE FROM vendor_offers WHERE offer_id=?", (offer_id,))
        if own: conn.commit()
        _log("delete_vendor_offer", offer_id=offer_id)
    finally:
        if own: conn.close()


def update_sales_day(sku, warehouse_id, sale_date, units_sold, conn=None):
    """Edit an existing sales_daily row (backfill_missing_sales is additive-
    only; this is the explicit single-day correction the G1 editor needs)."""
    own = conn is None; conn = conn or sqlite3.connect("database/inventra.db")
    try:
        conn.execute(
            "UPDATE sales_daily SET units_sold=? WHERE sku=? AND warehouse_id=? AND sale_date=?",
            (units_sold, sku, warehouse_id, str(sale_date)),
        )
        if own: conn.commit()
        _log("update_sales_day", sku=sku, warehouse_id=warehouse_id, sale_date=str(sale_date))
    finally:
        if own: conn.close()


def delete_sales_day(sku, warehouse_id, sale_date, conn=None):
    own = conn is None; conn = conn or sqlite3.connect("database/inventra.db")
    try:
        conn.execute(
            "DELETE FROM sales_daily WHERE sku=? AND warehouse_id=? AND sale_date=?",
            (sku, warehouse_id, str(sale_date)),
        )
        if own: conn.commit()
        _log("delete_sales_day", sku=sku, warehouse_id=warehouse_id, sale_date=str(sale_date))
    finally:
        if own: conn.close()


def deactivate_policy_floor(rule_id, conn=None):
    _update("policy_rules", "active", 0, "rule_id", rule_id, conn, "deactivate_policy_floor")


def delete_warehouse(warehouse_id, conn=None):
    own = conn is None; conn = conn or sqlite3.connect("database/inventra.db")
    try:
        conn.execute("DELETE FROM warehouses WHERE warehouse_id=?", (warehouse_id,))
        if own: conn.commit()
        _log("delete_warehouse", warehouse_id=warehouse_id)
    finally:
        if own: conn.close()


def delete_inventory_snapshot(snapshot_id, conn=None):
    own = conn is None; conn = conn or sqlite3.connect("database/inventra.db")
    try:
        conn.execute("DELETE FROM inventory_snapshots WHERE snapshot_id=?", (snapshot_id,))
        if own: conn.commit()
        _log("delete_inventory_snapshot", snapshot_id=snapshot_id)
    finally:
        if own: conn.close()


def delete_monthly_budget(budget_id, conn=None):
    own = conn is None; conn = conn or sqlite3.connect("database/inventra.db")
    try:
        conn.execute("DELETE FROM monthly_budgets WHERE budget_id=?", (budget_id,))
        if own: conn.commit()
        _log("delete_monthly_budget", budget_id=budget_id)
    finally:
        if own: conn.close()


def delete_stock_receipt(receipt_id, conn=None):
    own = conn is None; conn = conn or sqlite3.connect("database/inventra.db")
    try:
        conn.execute("DELETE FROM stock_receipts WHERE receipt_id=?", (receipt_id,))
        if own: conn.commit()
        _log("delete_stock_receipt", receipt_id=receipt_id)
    finally:
        if own: conn.close()


def delete_carrying_cost_inputs(input_id, conn=None):
    own = conn is None; conn = conn or sqlite3.connect("database/inventra.db")
    try:
        conn.execute("DELETE FROM carrying_cost_inputs WHERE input_id=?", (input_id,))
        if own: conn.commit()
        _log("delete_carrying_cost_inputs", input_id=input_id)
    finally:
        if own: conn.close()
