"""Read-only access to the Phase A warehouse facts."""

import sqlite3
from datetime import datetime

from domain.tool_models import Warehouse


def _get_db_connection(db_path: str | None = None):
    from submission.config import config
    db_path = db_path or config.database_path
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def _model(row: sqlite3.Row) -> Warehouse:
    return Warehouse(
        warehouse_id=row["warehouse_id"], name=row["name"],
        storage_cost_per_m3_month=row["storage_cost_per_m3_month"],
        evidence_id=f"warehouse:{row['warehouse_id']}", retrieved_at=datetime.utcnow(),
    )


def get_warehouse(warehouse_id: str, db_path: str | None = None) -> Warehouse | None:
    conn = _get_db_connection(db_path)
    try:
        row = conn.execute("SELECT * FROM warehouses WHERE warehouse_id=?", (warehouse_id,)).fetchone()
        return _model(row) if row else None
    finally:
        conn.close()


def list_warehouses(db_path: str | None = None) -> list[Warehouse]:
    conn = _get_db_connection(db_path)
    try:
        return [_model(row) for row in conn.execute("SELECT * FROM warehouses ORDER BY warehouse_id")]
    finally:
        conn.close()
