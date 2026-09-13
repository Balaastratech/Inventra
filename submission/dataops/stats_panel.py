"""Assemble the live statistics view for one sku/warehouse (G1-5).

Reads Phase B's already-derived sku_policy record plus the current stock
position -- it does not recompute the statistics itself (that is
submission.statistics + submission/sweep, run at classification time). The
"recompute" action re-runs classify_portfolio for the warehouse and upserts
the result, so the effect of a data edit is visible without waiting for the
next sweep.
"""

from __future__ import annotations

from datetime import date


def get_live_stats(sku: str, warehouse_id: str) -> dict:
    from tools.classification import get_latest_sku_policy
    from tools.inventory import get_stock_position

    policy = get_latest_sku_policy(sku, warehouse_id)
    stock = get_stock_position(sku, warehouse_id)
    return {
        "policy": policy,
        "current_position": None if stock.error else stock.on_hand - stock.reserved + stock.confirmed_inbound,
        "stock_error": stock.error.value if stock.error else None,
    }


def recompute(warehouse_id: str, as_of: date | None = None) -> int:
    """Re-run Phase B classification for a warehouse and persist the
    result, so a data-console edit's effect is immediately visible rather
    than waiting for the next sweep. Returns the number of SKUs updated."""
    from submission.statistics.classify import classify_portfolio
    from tools.classification import upsert_sku_policy

    policies = classify_portfolio(warehouse_id, as_of or date.today())
    for policy in policies:
        upsert_sku_policy(policy)
    return len(policies)
