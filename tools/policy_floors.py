"""Narrow read/write access to explicit, auditable policy floors."""

import sqlite3
import uuid
from datetime import date, datetime

from domain.tool_models import PolicyFloor


def _get_db_connection(db_path: str | None = None):
    if db_path is None:
        from submission.config import config
        db_path = config.database_path
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def _model(row: sqlite3.Row) -> PolicyFloor:
    return PolicyFloor(
        rule_id=row["rule_id"], sku=row["sku"], warehouse_id=row["warehouse_id"],
        min_units=row["min_units"], min_cover_days=row["min_cover_days"],
        reason=row["reason"], source=row["source"], set_by=row["set_by"],
        effective_from=row["effective_from"], effective_to=row["effective_to"],
        active=bool(row["active"]), evidence_id=f"policy-floor:{row['rule_id']}",
        retrieved_at=datetime.utcnow(),
    )


def get_active_policy_floor(sku: str, warehouse_id: str, as_of: date | datetime | None = None) -> PolicyFloor | None:
    as_of = as_of or date.today()
    as_of_text = as_of.date().isoformat() if isinstance(as_of, datetime) else as_of.isoformat()
    conn = _get_db_connection()
    try:
        row = conn.execute(
            """SELECT * FROM policy_rules WHERE sku=? AND warehouse_id=? AND active=1
               AND effective_from <= ? AND (effective_to IS NULL OR effective_to >= ?)
               ORDER BY effective_from DESC LIMIT 1""",
            (sku, warehouse_id, as_of_text, as_of_text),
        ).fetchone()
        return _model(row) if row else None
    finally:
        conn.close()


def set_policy_floor(sku: str, warehouse_id: str, *, min_units: int | None = None,
                     min_cover_days: float | None = None, reason: str, source: str,
                     set_by: str, effective_from: date | None = None,
                     effective_to: date | None = None) -> PolicyFloor:
    if min_units is None and min_cover_days is None:
        raise ValueError("a policy floor needs min_units or min_cover_days")
    if not reason.strip() or not set_by.strip():
        raise ValueError("reason and set_by are required for a policy floor")
    rule_id = f"POL-{uuid.uuid4().hex[:12]}"
    start = (effective_from or date.today()).isoformat()
    end = effective_to.isoformat() if effective_to else None
    conn = _get_db_connection()
    try:
        conn.execute(
            "INSERT INTO policy_rules VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)",
            (rule_id, sku, warehouse_id, min_units, min_cover_days, reason, source, set_by, start, end),
        )
        conn.commit()
        row = conn.execute("SELECT * FROM policy_rules WHERE rule_id=?", (rule_id,)).fetchone()
        return _model(row)
    finally:
        conn.close()
