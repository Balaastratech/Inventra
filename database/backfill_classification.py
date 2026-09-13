"""Idempotent oldest-first historical SKU-policy backfill."""
from __future__ import annotations

import sqlite3
from datetime import date

from submission.statistics.classify import classify_portfolio
from tools.classification import upsert_sku_policy


def _month_end(year: int, month: int) -> date:
    from calendar import monthrange
    return date(year, month, monthrange(year, month)[1])


def backfill_all(db_path: str = "database/inventra.db", months: int = 24) -> None:
    today = date.today(); month = today.month - 1 or 12; year = today.year if today.month > 1 else today.year - 1
    month_ends = []
    for _ in range(months):
        month_ends.append(_month_end(year, month)); month = month - 1 or 12; year -= 1 if month == 12 else 0
    with sqlite3.connect(db_path) as conn:
        warehouses = [row[0] for row in conn.execute("SELECT DISTINCT warehouse_id FROM sales_daily")]
    for as_of in reversed(month_ends):
        for warehouse in warehouses:
            for policy in classify_portfolio(warehouse, as_of, db_path=db_path): upsert_sku_policy(policy, db_path)
