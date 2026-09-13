"""
Sales Tools
Read-only tools for sales velocity and historical demand.
"""

import sqlite3
from datetime import date, datetime, timedelta
from typing import Tuple
from domain.tool_models import (
    SalesVelocity,
    DemandHistory,
    ErrorCode,
)


def get_daily_sales_series(sku: str, warehouse_id: str, start_date: date, end_date: date) -> DemandHistory:
    """Read inclusive calendar-day demand, representing missing rows as zero."""
    if end_date < start_date:
        raise ValueError("end_date must not precede start_date")
    conn = _get_db_connection()
    try:
        rows = conn.execute("SELECT sale_date, units_sold FROM sales_daily WHERE sku=? AND warehouse_id=? AND sale_date BETWEEN ? AND ?", (sku, warehouse_id, start_date.isoformat(), end_date.isoformat())).fetchall()
        by_day = {date.fromisoformat(str(row["sale_date"])): int(row["units_sold"]) for row in rows}
        days = (end_date - start_date).days + 1
        values = [by_day.get(start_date + timedelta(days=index), 0) for index in range(days)]
        return DemandHistory(sku=sku, warehouse_id=warehouse_id, start_date=start_date, end_date=end_date, daily_units=values, evidence_id=f"sales-history:{sku}:{warehouse_id}:{start_date}:{end_date}", retrieved_at=datetime.utcnow())
    finally:
        conn.close()


def get_first_sale_date(sku: str, warehouse_id: str) -> date | None:
    conn = _get_db_connection()
    try:
        row = conn.execute("SELECT MIN(sale_date) AS first_sale FROM sales_daily WHERE sku=? AND warehouse_id=?", (sku, warehouse_id)).fetchone()
        return date.fromisoformat(str(row["first_sale"])) if row and row["first_sale"] else None
    finally:
        conn.close()


def _get_db_connection(db_path: str | None = None):
    """Get a connection to the active application database."""
    if db_path is None:
        from submission.config import config

        db_path = config.database_path
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def get_sales_velocity(
    sku: str,
    warehouse_id: str,
    windows: Tuple[int, int] = (7, 30)
) -> SalesVelocity:
    """
    Calculate average daily sales for given time windows.
    
    Returns daily average for each window (e.g., 7-day and 30-day).
    Returns INSUFFICIENT_DATA if history is inadequate (< 3 observations).
    Returns evidence_id and timestamp for all reads.
    
    Args:
        sku: Product SKU
        warehouse_id: Warehouse identifier
        windows: Tuple of day windows to analyze (default: (7, 30))
    
    Returns:
        SalesVelocity with calculated averages or error
    """
    try:
        conn = _get_db_connection()
        cursor = conn.cursor()
        
        # Window is the last N *complete* calendar days, ending yesterday --
        # not today. `today` can never have a complete sales_daily row (the
        # nightly batch that would write it hasn't run yet), so a window
        # that included today was always averaging N units of demand over
        # N-1 real days of coverage, a permanent ~1/N low bias on every SKU,
        # every day. Dividing by calendar days is still correct (a true
        # zero-sales day must count as zero, since stock drains on calendar
        # time) -- only the boundary was wrong, not the formula.
        today = datetime.utcnow().date()
        yesterday = today - timedelta(days=1)
        start_7_days = yesterday - timedelta(days=windows[0] - 1)
        start_30_days = yesterday - timedelta(days=windows[1] - 1)

        # Query 7-day window
        cursor.execute(
            """
            SELECT COUNT(*) as count, COALESCE(SUM(units_sold), 0) as total
            FROM sales_daily
            WHERE sku = ? AND warehouse_id = ? AND sale_date >= ? AND sale_date <= ?
            """,
            (sku, warehouse_id, start_7_days, yesterday)
        )
        row_7 = cursor.fetchone()
        count_7 = row_7["count"]
        total_7 = row_7["total"]
        avg_7 = total_7 / windows[0] if windows[0] > 0 else 0

        # Query 30-day window
        cursor.execute(
            """
            SELECT COUNT(*) as count, COALESCE(SUM(units_sold), 0) as total
            FROM sales_daily
            WHERE sku = ? AND warehouse_id = ? AND sale_date >= ? AND sale_date <= ?
            """,
            (sku, warehouse_id, start_30_days, yesterday)
        )
        row_30 = cursor.fetchone()
        count_30 = row_30["count"]
        total_30 = row_30["total"]
        avg_30 = total_30 / windows[1] if windows[1] > 0 else 0
        
        conn.close()
        
        # Check for insufficient data (require at least 3 observations per window)
        if count_7 < 3 or count_30 < 3:
            return SalesVelocity(
                sku=sku,
                warehouse_id=warehouse_id,
                window_7_days=0,
                window_30_days=0,
                observation_count_7=count_7,
                observation_count_30=count_30,
                evidence_id="",
                retrieved_at=datetime.utcnow(),
                error=ErrorCode.INSUFFICIENT_DATA,
            )
        
        return SalesVelocity(
            sku=sku,
            warehouse_id=warehouse_id,
            window_7_days=round(avg_7, 2),
            window_30_days=round(avg_30, 2),
            observation_count_7=count_7,
            observation_count_30=count_30,
            evidence_id=f"sales:{sku}:{warehouse_id}",
            retrieved_at=datetime.utcnow(),
        )
    except Exception as e:
        return SalesVelocity(
            sku=sku,
            warehouse_id=warehouse_id,
            window_7_days=0,
            window_30_days=0,
            observation_count_7=0,
            observation_count_30=0,
            evidence_id="",
            retrieved_at=datetime.utcnow(),
            error=ErrorCode.UNKNOWN_ERROR,
        )
