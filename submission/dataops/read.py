"""Generic paged table reads (input + derived) for the G1 screens."""

from __future__ import annotations

import sqlite3

from submission.dataops.spec import DERIVED_TABLES, TABLE_SPECS


def _connect(db_path: str | None = None) -> sqlite3.Connection:
    from submission.config import config

    conn = sqlite3.connect(db_path or config.database_path)
    conn.row_factory = sqlite3.Row
    return conn


def all_table_names() -> list[str]:
    return list(TABLE_SPECS.keys()) + list(DERIVED_TABLES)


def count_table_rows(table: str, *, db_path: str | None = None) -> int:
    """Return the number of rows without loading the table into the UI."""
    conn = _connect(db_path)
    try:
        return int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
    finally:
        conn.close()


def read_table_row(table: str, pk_value, *, db_path: str | None = None) -> dict | None:
    """Fetch one input-table row by its declared primary key."""
    spec = TABLE_SPECS.get(table)
    if spec is None:
        return None
    conn = _connect(db_path)
    try:
        row = conn.execute(
            f"SELECT * FROM {table} WHERE {spec.primary_key}=?", (pk_value,)
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def read_table(table: str, *, limit: int = 200, offset: int = 0, db_path: str | None = None) -> list[dict]:
    conn = _connect(db_path)
    try:
        order = ""
        spec = TABLE_SPECS.get(table)
        if spec is not None:
            order = f"ORDER BY {spec.primary_key}"
        rows = conn.execute(f"SELECT * FROM {table} {order} LIMIT ? OFFSET ?", (limit, offset)).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def read_change_log(*, table: str | None = None, limit: int = 200, db_path: str | None = None) -> list[dict]:
    conn = _connect(db_path)
    try:
        sql = "SELECT * FROM data_change_log"
        params: tuple = ()
        if table:
            sql += " WHERE table_name=?"
            params = (table,)
        sql += " ORDER BY changed_at DESC LIMIT ?"
        rows = conn.execute(sql, params + (limit,)).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()
