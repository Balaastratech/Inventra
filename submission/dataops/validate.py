"""Pure validation: spec + row -> list[str] errors. No DB writes here.

Each returned message names the field and the reason -- never a bare
"invalid" and never a raw traceback (G1-1). FK-existence and unique-key and
delete-dependent checks need a connection to look facts up in, so those take
one; everything else is pure.
"""

from __future__ import annotations

import sqlite3
from datetime import date, datetime

from submission.dataops.spec import DERIVED_TABLES, TABLE_SPECS, ColumnSpec, TableSpec


def _coerce(col: ColumnSpec, value):
    """Type-check/coerce one value against its column spec.

    Returns (coerced_value, error | None). A bool is never accepted where an
    int/float is required (Phase F's own _await_manual_target_cover already
    sets this precedent) because `isinstance(True, int)` is True in Python
    and would silently let a checkbox value through as 0/1.
    """
    if value is None or value == "":
        return None, None
    if col.type is bool:
        if isinstance(value, bool):
            return value, None
        # SQLite has no native boolean -- a row read back from the database
        # carries 0/1 ints for what was written as True/False. Accepted here
        # for that reason only; a genuine float/str is still rejected.
        if isinstance(value, int) and value in (0, 1):
            return bool(value), None
        return None, f"{col.display_label()} must be true/false"
    if col.type in (int, float) and isinstance(value, bool):
        return None, f"{col.display_label()} must be a number, not true/false"
    if col.type is int:
        try:
            coerced = int(value)
        except (TypeError, ValueError):
            return None, f"{col.display_label()} must be a whole number"
        return coerced, None
    if col.type is float:
        try:
            coerced = float(value)
        except (TypeError, ValueError):
            return None, f"{col.display_label()} must be a number"
        return coerced, None
    if col.type is date:
        if isinstance(value, date):
            return value, None
        try:
            return date.fromisoformat(str(value)), None
        except ValueError:
            return None, f"{col.display_label()} must be a valid date (YYYY-MM-DD)"
    return value, None


def _fk_exists(conn: sqlite3.Connection, table: str, column: str, value) -> bool:
    row = conn.execute(f"SELECT 1 FROM {table} WHERE {column}=? LIMIT 1", (value,)).fetchone()
    return row is not None


def validate_row(
    table: str,
    values: dict,
    conn: sqlite3.Connection,
    *,
    is_update: bool = False,
    existing_pk_value=None,
) -> list[str]:
    """Validate one row against its table spec. Returns a list of readable
    error strings; empty means the row may be written."""
    if table in DERIVED_TABLES:
        return [f"{table} is a derived table -- it has no write function (DG3). Edit its inputs and recompute."]
    spec = TABLE_SPECS.get(table)
    if spec is None:
        return [f"Unknown table: {table}"]

    errors: list[str] = []
    coerced: dict = {}
    for col in spec.columns:
        if col.auto:
            continue
        raw = values.get(col.name)
        if col.required and (raw is None or raw == ""):
            errors.append(f"{col.display_label()} is required")
            continue
        value, err = _coerce(col, raw)
        if err:
            errors.append(err)
            continue
        coerced[col.name] = value
        if value is None:
            continue
        if col.min_value is not None and isinstance(value, (int, float)) and value < col.min_value:
            errors.append(f"{col.display_label()} must be >= {col.min_value}")
        if col.max_value is not None and isinstance(value, (int, float)) and value > col.max_value:
            errors.append(f"{col.display_label()} must be <= {col.max_value}")
        if col.enum and value not in col.enum:
            errors.append(f"{col.display_label()} must be one of {', '.join(col.enum)}")
        if col.not_future and isinstance(value, date) and value > date.today():
            errors.append(f"{col.display_label()} cannot be in the future")
        if col.fk and not _fk_exists(conn, col.fk[0], col.fk[1], value):
            errors.append(f"{col.fk[0][:-1] if col.fk[0].endswith('s') else col.fk[0]} '{value}' does not exist")

    if errors:
        return errors

    # Date-range sanity, table-specific pairs.
    if table == "policy_rules":
        eff_from, eff_to = coerced.get("effective_from"), coerced.get("effective_to")
        if eff_from and eff_to and eff_to < eff_from:
            errors.append("effective_to cannot be before effective_from")
    if table == "stock_receipts":
        for a, b in (("ordered_at", "promised_at"), ("ordered_at", "received_at")):
            va, vb = values.get(a), values.get(b)
            if va and vb and str(vb) < str(va):
                errors.append(f"{b} cannot be before {a}")

    # R7: duplicate sales day, surfaced as an edit-that-row message rather
    # than a raw IntegrityError.
    if spec.unique and not is_update:
        where = " AND ".join(f"{col}=?" for col in spec.unique)
        params = tuple(coerced.get(col, values.get(col)) for col in spec.unique)
        row = conn.execute(f"SELECT 1 FROM {table} WHERE {where} LIMIT 1", params).fetchone()
        if row is not None:
            if table == "sales_daily":
                errors.append(
                    f"a row already exists for {coerced.get('sale_date')} / {coerced.get('sku')} / "
                    f"{coerced.get('warehouse_id')} -- edit that row instead"
                )
            else:
                errors.append(f"a row already exists for {dict(zip(spec.unique, params))} -- edit that row instead")

    # Warn-not-block: selling_price below the cheapest landed cost is a
    # business judgement (B10 already treats negative contribution as a
    # data error), so it is recorded as a warning, not a blocking error.
    if table == "products" and coerced.get("selling_price") is not None:
        cheapest = conn.execute(
            "SELECT MIN(unit_price + COALESCE(freight_per_unit,0)) FROM vendor_offers WHERE sku=?",
            (existing_pk_value or values.get("sku"),),
        ).fetchone()[0]
        if cheapest is not None and coerced["selling_price"] < cheapest:
            errors.append(
                f"WARNING: selling_price {coerced['selling_price']} is below the cheapest landed "
                f"cost {cheapest:.2f} -- this SKU would sell at a loss. Written, not blocked."
            )

    return errors


def is_warning_only(errors: list[str]) -> bool:
    return bool(errors) and all(e.startswith("WARNING:") for e in errors)


def dependent_row_counts(conn: sqlite3.Connection, table: str, pk_column: str, pk_value) -> dict[str, int]:
    """How many rows in other tables reference this row -- the delete guard."""
    spec = TABLE_SPECS.get(table)
    if spec is None or not spec.dependents:
        return {}
    counts = {}
    for dep_table, dep_column in spec.dependents:
        n = conn.execute(f"SELECT COUNT(*) FROM {dep_table} WHERE {dep_column}=?", (pk_value,)).fetchone()[0]
        if n:
            counts[dep_table] = n
    return counts
