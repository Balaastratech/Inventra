"""Narrow persistence operations for the human-visible parking queue."""
from __future__ import annotations

import sqlite3
import uuid
from datetime import datetime

from domain.tool_models import ParkedItemRecord
from submission.config import config


def _connect(db_path: str | None = None):
    conn = sqlite3.connect(db_path or config.database_path)
    conn.row_factory = sqlite3.Row
    return conn


def _model(row: sqlite3.Row) -> ParkedItemRecord:
    values = dict(row)
    for name in ("parked_at", "resolved_at"):
        if values.get(name) and isinstance(values[name], str):
            values[name] = datetime.fromisoformat(values[name])
    return ParkedItemRecord(**values)


def park_item(sku: str, warehouse_id: str, reason: str, note: str = "", db_path: str | None = None) -> ParkedItemRecord:
    with _connect(db_path) as conn:
        existing = conn.execute("SELECT * FROM parked_items WHERE sku=? AND warehouse_id=? AND resolved_at IS NULL ORDER BY parked_at DESC LIMIT 1", (sku, warehouse_id)).fetchone()
        if existing:
            return _model(existing)
        park_id = f"PARK-{uuid.uuid4().hex[:12].upper()}"
        now = datetime.utcnow().isoformat()
        conn.execute("INSERT INTO parked_items (park_id,sku,warehouse_id,reason,parked_at,note) VALUES (?,?,?,?,?,?)", (park_id, sku, warehouse_id, reason, now, note))
        conn.commit()
        return _model(conn.execute("SELECT * FROM parked_items WHERE park_id=?", (park_id,)).fetchone())


def get_open_parked_items(warehouse_id: str | None = None, db_path: str | None = None) -> list[ParkedItemRecord]:
    sql, params = "SELECT * FROM parked_items WHERE resolved_at IS NULL", ()
    if warehouse_id:
        sql += " AND warehouse_id=?"; params = (warehouse_id,)
    sql += " ORDER BY parked_at DESC"
    with _connect(db_path) as conn:
        return [_model(row) for row in conn.execute(sql, params)]


def resolve_park(park_id: str, resolved_by: str, resolution: str, db_path: str | None = None) -> ParkedItemRecord:
    if not resolved_by.strip() or not resolution.strip():
        raise ValueError("resolved_by and resolution are required")
    with _connect(db_path) as conn:
        conn.execute("UPDATE parked_items SET resolved_at=?, resolved_by=?, note=CASE WHEN note='' THEN ? ELSE note || '\nResolution: ' || ? END WHERE park_id=? AND resolved_at IS NULL", (datetime.utcnow().isoformat(), resolved_by.strip(), resolution.strip(), resolution.strip(), park_id))
        conn.commit()
        row = conn.execute("SELECT * FROM parked_items WHERE park_id=?", (park_id,)).fetchone()
    if not row:
        raise ValueError(f"Unknown parked item {park_id}")
    return _model(row)
