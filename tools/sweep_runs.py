"""Auditable persistence for autonomous sweep summaries."""
from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime

from domain.tool_models import SweepRun
from submission.config import config


def _connect(db_path: str | None = None):
    conn = sqlite3.connect(db_path or config.database_path)
    conn.row_factory = sqlite3.Row
    return conn


def _model(row: sqlite3.Row) -> SweepRun:
    values = dict(row)
    values["warehouse_ids"] = json.loads(values["warehouse_ids"])
    values["detail"] = json.loads(values.pop("detail_json") or "[]")
    for name in ("started_at", "completed_at"):
        if values.get(name) and isinstance(values[name], str):
            values[name] = datetime.fromisoformat(values[name])
    return SweepRun(**values)


def record_sweep_run(*, warehouse_ids: list[str], pairs_examined: int, candidates_found: int,
                     parked_count: int, deferred_for_budget_count: int, cases_opened: int,
                     reminders_sent: int, total_model_calls_estimate: int, detail: list[dict],
                     started_at: datetime | None = None, completed_at: datetime | None = None,
                     db_path: str | None = None) -> SweepRun:
    sweep_id, started = f"SWEEP-{uuid.uuid4().hex[:12].upper()}", started_at or datetime.utcnow()
    completed = completed_at or datetime.utcnow()
    with _connect(db_path) as conn:
        conn.execute("""INSERT INTO sweep_runs (sweep_id,started_at,completed_at,warehouse_ids,pairs_examined,candidates_found,parked_count,deferred_for_budget_count,cases_opened,reminders_sent,total_model_calls_estimate,detail_json)
                        VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""", (sweep_id, started.isoformat(), completed.isoformat(), json.dumps(warehouse_ids), pairs_examined, candidates_found, parked_count, deferred_for_budget_count, cases_opened, reminders_sent, total_model_calls_estimate, json.dumps(detail, default=str)))
        conn.commit()
        return _model(conn.execute("SELECT * FROM sweep_runs WHERE sweep_id=?", (sweep_id,)).fetchone())


def get_sweep_history(limit: int = 20, db_path: str | None = None) -> list[SweepRun]:
    with _connect(db_path) as conn:
        rows = conn.execute("SELECT * FROM sweep_runs ORDER BY started_at DESC LIMIT ?", (limit,)).fetchall()
    return [_model(row) for row in rows]
