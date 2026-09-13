"""
Agent Memory Tools (Gap 9)

Preference-learning store: a durable record of prior human decisions the
strategist can be reminded of on a later case, so the system doesn't keep
re-proposing something a human already rejected for a stated reason.

Read-only for the prompt-building side (summarize_memory_for_prompt);
record_signal is the only writer, called from deterministic graph nodes
only -- never an LLM-callable tool, same boundary as append_audit_event.
Best-effort: a memory-write failure must never block a case, matching
graph/support.emit_audit's discipline.
"""

from __future__ import annotations

import sqlite3
import uuid
from datetime import datetime


def _get_db_connection(db_path: str = "database/inventra.db"):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def record_signal(
    entity_type: str,
    entity_key: str,
    signal_type: str,
    signal_text: str,
    source_case_id: str,
    weight: float = 1.0,
) -> None:
    """Best-effort write. Never raises -- a memory-write failure must not
    block the case any more than an audit-write failure does."""
    try:
        conn = _get_db_connection()
        conn.execute(
            """
            INSERT INTO agent_memory_signals
                (id, entity_type, entity_key, signal_type, signal_text, weight, source_case_id, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                f"MEM-{uuid.uuid4().hex[:12].upper()}",
                entity_type,
                entity_key,
                signal_type,
                signal_text[:500],
                weight,
                source_case_id,
                datetime.utcnow(),
            ),
        )
        conn.commit()
        conn.close()
    except Exception:
        pass


def summarize_memory_for_prompt(sku: str, warehouse_id: str, candidate_vendor_ids: list[str]) -> str:
    """Short natural-language digest of prior signals about the given
    vendor candidates. Returns "" when there is nothing relevant, so
    callers can append the result unconditionally without an extra branch.

    Deliberately narrow: only vendor signals for the vendors actually in
    play on this case, most recent first. Not built as a general-purpose
    cross-case query surface -- an agent tool here would be exactly the
    generic-SQL access the brief forbids.
    """
    if not candidate_vendor_ids:
        return ""
    conn = _get_db_connection()
    placeholders = ",".join("?" for _ in candidate_vendor_ids)
    rows = conn.execute(
        f"""
        SELECT entity_key, signal_type, signal_text, source_case_id, created_at
        FROM agent_memory_signals
        WHERE entity_type = 'vendor' AND entity_key IN ({placeholders})
        ORDER BY created_at DESC
        LIMIT 10
        """,
        candidate_vendor_ids,
    ).fetchall()
    conn.close()
    if not rows:
        return ""
    lines = [
        f"- vendor {row['entity_key']} ({row['signal_type']}, case {row['source_case_id']}): {row['signal_text']}"
        for row in rows
    ]
    return "Prior signals about these vendors from earlier cases:\n" + "\n".join(lines)
