"""Create / update / delete per input table (G1-2).

Single entry point for every write the data console makes: validate, then
either refuse-with-reasons or write inside one transaction and log to
data_change_log. Never raw SQL from the screen (DG2) -- this module IS the
one SQL surface, and it always goes through validate_row first.

Delegates to fixtures/fabricator.py where a function already exists
(sales_daily, products, vendors, vendor_offers); falls back to a generic
parameterized statement, built from the same TABLE_SPECS the validator
reads, for the remaining tables.
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import date, datetime

from submission.dataops.spec import DERIVED_TABLES, SYSTEM_MANAGED_TABLES, TABLE_SPECS
from submission.dataops.validate import dependent_row_counts, is_warning_only, validate_row


class WriteRejected(Exception):
    def __init__(self, errors: list[str]):
        super().__init__("; ".join(errors))
        self.errors = errors


def _ensure_operator_writable(table: str) -> None:
    if table in SYSTEM_MANAGED_TABLES:
        raise WriteRejected([
            f"{table} is managed by the supplier data source and is read-only for operators. "
            "The replenishment agent can only use supplier data it receives."
        ])


def _connect(db_path: str | None = None) -> sqlite3.Connection:
    from submission.config import config

    conn = sqlite3.connect(db_path or config.database_path)
    conn.row_factory = sqlite3.Row
    return conn


def _row_dict(conn: sqlite3.Connection, table: str, pk_column: str, pk_value) -> dict | None:
    row = conn.execute(f"SELECT * FROM {table} WHERE {pk_column}=?", (pk_value,)).fetchone()
    return dict(row) if row else None


def _json_default(value):
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return str(value)


def _log_change(conn: sqlite3.Connection, *, changed_by: str, table: str, row_key: str,
                 action: str, before: dict | None, after: dict | None, note: str = "") -> None:
    if not changed_by or not changed_by.strip():
        raise WriteRejected(["changed_by (operator name) is required for every write"])
    conn.execute(
        "INSERT INTO data_change_log (change_id, changed_by, table_name, row_key, action, before_json, after_json, note) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (
            f"CHG-{uuid.uuid4().hex[:12]}", changed_by.strip(), table, row_key, action,
            json.dumps(before, default=_json_default) if before is not None else None,
            json.dumps(after, default=_json_default) if after is not None else None,
            note,
        ),
    )


def _generate_pk(table: str) -> str:
    prefixes = {
        "inventory_snapshots": "INV", "sales_daily": "SALE", "vendor_offers": "OFFER",
        "monthly_budgets": "BUDGET", "stock_receipts": "RCPT", "policy_rules": "POL",
        "carrying_cost_inputs": "CCI",
    }
    return f"{prefixes.get(table, table.upper())}-{uuid.uuid4().hex[:12]}"


def create_row(table: str, values: dict, *, changed_by: str, db_path: str | None = None) -> dict:
    _ensure_operator_writable(table)
    if table in DERIVED_TABLES:
        raise WriteRejected([f"{table} is a derived table -- it has no write function (DG3)."])
    spec = TABLE_SPECS[table]
    conn = _connect(db_path)
    try:
        errors = validate_row(table, values, conn)
        blocking = [e for e in errors if not e.startswith("WARNING:")]
        if blocking:
            raise WriteRejected(blocking)

        row = dict(values)
        pk = row.get(spec.primary_key)
        if not pk:
            pk = _generate_pk(table)
            row[spec.primary_key] = pk

        _dispatch_create(conn, table, row)
        conn.commit()
        after = _row_dict(conn, table, spec.primary_key, pk)
        _log_change(conn, changed_by=changed_by, table=table, row_key=str(pk),
                    action="CREATE", before=None, after=after,
                    note="; ".join(e for e in errors if e.startswith("WARNING:")))
        conn.commit()
        return after
    finally:
        conn.close()


def update_row(table: str, pk_value, values: dict, *, changed_by: str, db_path: str | None = None) -> dict:
    _ensure_operator_writable(table)
    if table in DERIVED_TABLES:
        raise WriteRejected([f"{table} is a derived table -- it has no write function (DG3)."])
    spec = TABLE_SPECS[table]
    conn = _connect(db_path)
    try:
        before = _row_dict(conn, table, spec.primary_key, pk_value)
        if before is None:
            raise WriteRejected([f"no {table} row with {spec.primary_key}={pk_value}"])

        merged = {**before, **values}
        errors = validate_row(table, merged, conn, is_update=True, existing_pk_value=pk_value)
        blocking = [e for e in errors if not e.startswith("WARNING:")]
        if blocking:
            raise WriteRejected(blocking)  # all-or-nothing: row left byte-identical

        _dispatch_update(conn, table, pk_value, merged)
        conn.commit()
        after = _row_dict(conn, table, spec.primary_key, pk_value)
        _log_change(conn, changed_by=changed_by, table=table, row_key=str(pk_value),
                    action="UPDATE", before=before, after=after,
                    note="; ".join(e for e in errors if e.startswith("WARNING:")))
        conn.commit()
        return after
    finally:
        conn.close()


def delete_row(table: str, pk_value, *, changed_by: str, db_path: str | None = None) -> None:
    _ensure_operator_writable(table)
    if table in DERIVED_TABLES:
        raise WriteRejected([f"{table} is a derived table -- it has no write function (DG3)."])
    spec = TABLE_SPECS[table]
    conn = _connect(db_path)
    try:
        before = _row_dict(conn, table, spec.primary_key, pk_value)
        if before is None:
            raise WriteRejected([f"no {table} row with {spec.primary_key}={pk_value}"])

        dependents = dependent_row_counts(conn, table, spec.primary_key, pk_value)
        if dependents:
            named = ", ".join(f"{n} {t} row(s)" for t, n in dependents.items())
            raise WriteRejected([f"cannot delete: {named} still reference this row"])

        _dispatch_delete(conn, table, pk_value, before)
        conn.commit()
        _log_change(conn, changed_by=changed_by, table=table, row_key=str(pk_value),
                    action="DELETE", before=before, after=None)
        conn.commit()
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Dispatch: delegate to fabricator where it already has the primitive,
# otherwise fall back to a spec-driven generic statement.
# ---------------------------------------------------------------------------

def _generic_insert(conn: sqlite3.Connection, table: str, row: dict) -> None:
    spec = TABLE_SPECS[table]
    columns = [c.name for c in spec.columns]
    placeholders = ", ".join("?" for _ in columns)
    conn.execute(
        f"INSERT INTO {table} ({', '.join(columns)}) VALUES ({placeholders})",
        tuple(row.get(c) for c in columns),
    )


def _generic_update(conn: sqlite3.Connection, table: str, pk_value, row: dict) -> None:
    spec = TABLE_SPECS[table]
    columns = [c.name for c in spec.columns if c.name != spec.primary_key]
    assignments = ", ".join(f"{c}=?" for c in columns)
    conn.execute(
        f"UPDATE {table} SET {assignments} WHERE {spec.primary_key}=?",
        tuple(row.get(c) for c in columns) + (pk_value,),
    )


def _dispatch_create(conn: sqlite3.Connection, table: str, row: dict) -> None:
    from fixtures import fabricator

    if table == "products":
        fabricator.create_product(
            row["sku"], row["name"], row["category"], active=bool(row.get("active", True)),
            selling_price=row.get("selling_price"), lifecycle=row.get("lifecycle"),
            unit_volume_m3=row.get("unit_volume_m3"), conn=conn,
        )
    elif table == "vendors":
        fabricator.create_vendor(
            row["vendor_id"], row["name"], active=bool(row.get("active", True)),
            on_time_rate=row.get("on_time_rate", 1.0), fill_rate=row.get("fill_rate", 1.0),
            quality_score=row.get("quality_score", 1.0), billing_basis=row.get("billing_basis"),
            payment_terms_days=row.get("payment_terms_days"), notes=row.get("notes"),
            contact_email=row.get("contact_email"), conn=conn,
        )
    elif table == "vendor_offers":
        fabricator.create_vendor_offer(
            row["offer_id"], row["vendor_id"], row["sku"], row["unit_price"], row["moq"],
            row["lead_time_days"], row["valid_until"], freight_flat=row.get("freight_flat"),
            freight_per_unit=row.get("freight_per_unit"), conn=conn,
        )
    elif table == "warehouses":
        fabricator.upsert_warehouse(row["warehouse_id"], row["name"], row["storage_cost_per_m3_month"], conn=conn)
    elif table == "sales_daily":
        fabricator.backfill_missing_sales(
            row["sku"], row["warehouse_id"], date.fromisoformat(str(row["sale_date"])),
            date.fromisoformat(str(row["sale_date"])), int(row["units_sold"]), conn=conn,
        )
    else:
        _generic_insert(conn, table, row)


def _dispatch_update(conn: sqlite3.Connection, table: str, pk_value, row: dict) -> None:
    from fixtures import fabricator

    if table == "sales_daily":
        fabricator.update_sales_day(row["sku"], row["warehouse_id"], row["sale_date"], row["units_sold"], conn=conn)
    elif table == "warehouses":
        fabricator.upsert_warehouse(row["warehouse_id"], row["name"], row["storage_cost_per_m3_month"], conn=conn)
    else:
        _generic_update(conn, table, pk_value, row)


def _dispatch_delete(conn: sqlite3.Connection, table: str, pk_value, before: dict) -> None:
    from fixtures import fabricator

    if table == "products":
        fabricator.delete_product(pk_value, conn=conn)
    elif table == "vendors":
        fabricator.delete_vendor(pk_value, conn=conn)
    elif table == "vendor_offers":
        fabricator.delete_vendor_offer(pk_value, conn=conn)
    elif table == "warehouses":
        fabricator.delete_warehouse(pk_value, conn=conn)
    elif table == "sales_daily":
        fabricator.delete_sales_day(before["sku"], before["warehouse_id"], before["sale_date"], conn=conn)
    elif table == "inventory_snapshots":
        fabricator.delete_inventory_snapshot(pk_value, conn=conn)
    elif table == "monthly_budgets":
        fabricator.delete_monthly_budget(pk_value, conn=conn)
    elif table == "stock_receipts":
        fabricator.delete_stock_receipt(pk_value, conn=conn)
    elif table == "carrying_cost_inputs":
        fabricator.delete_carrying_cost_inputs(pk_value, conn=conn)
    elif table == "policy_rules":
        conn.execute("DELETE FROM policy_rules WHERE rule_id=?", (pk_value,))
    else:
        spec = TABLE_SPECS[table]
        conn.execute(f"DELETE FROM {table} WHERE {spec.primary_key}=?", (pk_value,))
