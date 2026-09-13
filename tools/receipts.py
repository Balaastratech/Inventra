"""Measured stock-receipt history and lateness statistics."""

import sqlite3
import uuid
from datetime import datetime

from domain.tool_models import LatenessDistribution, StockReceipt
from submission.statistics._descriptive import mean


def _get_db_connection(db_path: str = "database/inventra.db"):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def _percentile(values: list[float], percentile: float) -> float:
    ordered = sorted(values)
    index = (len(ordered) - 1) * percentile
    low, high = int(index), min(int(index) + 1, len(ordered) - 1)
    return ordered[low] + (ordered[high] - ordered[low]) * (index - low)


def get_lateness_distribution(vendor_id: str, sku: str | None = None,
                              min_observations: int = 5,
                              db_path: str = "database/inventra.db") -> LatenessDistribution | None:
    conn = _get_db_connection(db_path)
    try:
        clauses, params = ["vendor_id=?"], [vendor_id]
        if sku:
            clauses.append("sku=?")
            params.append(sku)
        where = " AND ".join(clauses)
        rows = conn.execute(f"SELECT promised_at, received_at FROM stock_receipts WHERE {where}", params).fetchall()
        late = []
        on_time = 0
        for row in rows:
            delay = (datetime.fromisoformat(str(row["received_at"])) - datetime.fromisoformat(str(row["promised_at"]))).total_seconds() / 86400
            if delay > 0:
                late.append(delay)
            else:
                on_time += 1
        if len(late) < min_observations:
            return None
        return LatenessDistribution(
            vendor_id=vendor_id, sku=sku, n_observations=len(late),
            on_time_rate_measured=round(on_time / len(rows), 4) if rows else 0,
            mean_late_days=round(mean(late), 2), p50_late_days=round(_percentile(late, .5), 2),
            p90_late_days=round(_percentile(late, .9), 2),
            evidence_id=f"lateness:{vendor_id}:{sku or 'all'}", retrieved_at=datetime.utcnow(),
        )
    finally:
        conn.close()


def record_receipt(request_id: str | None, promised_at: datetime, received_at: datetime,
                   quantity_received: int, *, sku: str, warehouse_id: str, vendor_id: str,
                   quantity_ordered: int, ordered_at: datetime | None = None,
                   conn: sqlite3.Connection | None = None) -> StockReceipt:
    own_connection = conn is None
    conn = conn or _get_db_connection()
    try:
        receipt_id = f"RCPT-{uuid.uuid4().hex[:12]}"
        ordered_at = ordered_at or promised_at
        lead_time = (received_at - ordered_at).total_seconds() / 86400
        conn.execute("INSERT INTO stock_receipts VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                     (receipt_id, request_id, sku, warehouse_id, vendor_id, quantity_ordered,
                      quantity_received, ordered_at, promised_at, received_at, lead_time))
        if own_connection:
            conn.commit()
        return StockReceipt(receipt_id=receipt_id, request_id=request_id, sku=sku, warehouse_id=warehouse_id,
                            vendor_id=vendor_id, quantity_ordered=quantity_ordered,
                            quantity_received=quantity_received, ordered_at=ordered_at,
                            promised_at=promised_at, received_at=received_at,
                            lead_time_days_actual=lead_time, evidence_id=f"receipt:{receipt_id}",
                            retrieved_at=datetime.utcnow())
    finally:
        if own_connection:
            conn.close()
