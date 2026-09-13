"""Narrow read/write access to Phase B's derived sku_policy records."""
from __future__ import annotations

import sqlite3
from datetime import date

from domain.tool_models import SkuPolicy

_COLUMNS = ("sku warehouse_id as_of_date mean_daily_demand std_daily_demand cv adi cv_squared demand_quadrant abc_class xyz_class consumption_value_12m cumulative_share service_level safety_stock_units reorder_point_units derived_cover_days statistical_target_units active_target_units maturity confidence candidate_class candidate_since consecutive_confirmations active_class change_reason").split()


def _connect(db_path: str | None = None):
    from submission.config import config
    conn = sqlite3.connect(db_path or config.database_path); conn.row_factory = sqlite3.Row; return conn


def _model(row: sqlite3.Row) -> SkuPolicy:
    values = dict(row)
    for field in ("as_of_date", "candidate_since"):
        if values.get(field): values[field] = date.fromisoformat(str(values[field]))
    return SkuPolicy(**values)


def get_latest_sku_policy(sku: str, warehouse_id: str, before_as_of: date | None = None, db_path: str | None = None) -> SkuPolicy | None:
    sql, params = "SELECT %s FROM sku_policy WHERE sku=? AND warehouse_id=?" % ", ".join(_COLUMNS), [sku, warehouse_id]
    if before_as_of: sql += " AND as_of_date < ?"; params.append(before_as_of.isoformat())
    with _connect(db_path) as conn: row = conn.execute(sql + " ORDER BY as_of_date DESC LIMIT 1", params).fetchone()
    return _model(row) if row else None


def get_latest_policies_for_warehouse(
    warehouse_id: str, before_as_of: date | None = None, db_path: str | None = None
) -> list[SkuPolicy]:
    """Return one latest policy row per SKU for a warehouse.

    The window function makes this a single bulk read, rather than an N+1
    loop over ``get_latest_sku_policy`` during an autonomous sweep.
    """
    from submission.config import config

    cutoff = (before_as_of or date.today()).isoformat()
    sql = """
        SELECT %s FROM (
            SELECT %s, ROW_NUMBER() OVER (PARTITION BY sku ORDER BY as_of_date DESC) AS row_number
            FROM sku_policy WHERE warehouse_id=? AND as_of_date <= ?
        ) WHERE row_number=1 ORDER BY sku
    """ % (", ".join(_COLUMNS), ", ".join(_COLUMNS))
    with _connect(db_path or config.database_path) as conn:
        rows = conn.execute(sql, (warehouse_id, cutoff)).fetchall()
    return [_model(row) for row in rows]


def get_sku_policy_history(sku: str, warehouse_id: str, db_path: str | None = None) -> list[SkuPolicy]:
    with _connect(db_path) as conn: rows = conn.execute("SELECT %s FROM sku_policy WHERE sku=? AND warehouse_id=? ORDER BY as_of_date" % ", ".join(_COLUMNS), (sku, warehouse_id)).fetchall()
    return [_model(row) for row in rows]


def upsert_sku_policy(policy: SkuPolicy, db_path: str | None = None) -> SkuPolicy:
    values = policy.model_dump(); values["as_of_date"] = values["as_of_date"].isoformat()
    if values.get("candidate_since"): values["candidate_since"] = values["candidate_since"].isoformat()
    marks = ", ".join("?" for _ in _COLUMNS)
    updates = ", ".join(f"{column}=excluded.{column}" for column in _COLUMNS if column not in {"sku", "warehouse_id", "as_of_date"})
    sql = "INSERT INTO sku_policy (%s) VALUES (%s) ON CONFLICT(sku, warehouse_id, as_of_date) DO UPDATE SET %s" % (", ".join(_COLUMNS), marks, updates)
    with _connect(db_path) as conn: conn.execute(sql, [values.get(column) for column in _COLUMNS]); conn.commit()
    return policy
