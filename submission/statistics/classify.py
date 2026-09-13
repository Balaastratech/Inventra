"""Thin database orchestration for deterministic monthly SKU policy records."""
from __future__ import annotations

import sqlite3
from datetime import date, timedelta

from domain.tool_models import SkuPolicy
from submission.config import config
from tools.classification import get_latest_sku_policy, upsert_sku_policy
from tools.cost_inputs import carrying_rate_per_day, contribution_per_unit
from ._descriptive import mean, pstdev
from .abc_xyz import classify_abc, classify_xyz, consumption_value_12m
from .demand import compute_demand_stats, croston_level
from .hysteresis import apply_hysteresis
from .maturity import assess_maturity
from .safety_stock import compute_reorder_point, compute_safety_stock, derived_cover_days, empirical_safety_stock
from .service_level import bounded_service_level, newsvendor_service_level
from .windows import detect_regime_shift, recent_level_window, rolling_12_months


def _daily(conn, sku: str, warehouse_id: str, start: date, end: date) -> list[int]:
    rows = conn.execute("SELECT sale_date, units_sold FROM sales_daily WHERE sku=? AND warehouse_id=? AND sale_date BETWEEN ? AND ?", (sku, warehouse_id, start.isoformat(), end.isoformat())).fetchall()
    values = {date.fromisoformat(str(row["sale_date"])): int(row["units_sold"]) for row in rows}
    return [values.get(start + timedelta(days=i), 0) for i in range((end-start).days+1)]


def _unit_cost(conn, sku: str) -> float | None:
    row = conn.execute("SELECT unit_price, freight_flat, freight_per_unit, moq FROM vendor_offers vo JOIN vendors v ON v.vendor_id=vo.vendor_id WHERE vo.sku=? AND v.active=1 AND vo.valid_until>=CURRENT_TIMESTAMP ORDER BY (unit_price + COALESCE(freight_per_unit,0) + COALESCE(freight_flat,0)/MAX(moq,1)) LIMIT 1", (sku,)).fetchone()
    if row: return float(row["unit_price"] + (row["freight_per_unit"] or 0) + (row["freight_flat"] or 0) / max(row["moq"], 1))
    receipt = conn.execute("SELECT quantity_ordered, quantity_received FROM stock_receipts WHERE sku=? ORDER BY received_at DESC LIMIT 1", (sku,)).fetchone()
    return None if not receipt or not receipt["quantity_received"] else 0.0  # no historical price is stored


def _lead_time(conn, sku: str, warehouse_id: str) -> tuple[float, float]:
    rows = conn.execute("SELECT lead_time_days_actual FROM stock_receipts WHERE sku=? AND warehouse_id=?", (sku, warehouse_id)).fetchall()
    values = [float(row[0]) for row in rows]
    if values: return mean(values), pstdev(values) if len(values) > 1 else 0.0
    offer = conn.execute("SELECT lead_time_days FROM vendor_offers WHERE sku=? ORDER BY lead_time_days LIMIT 1", (sku,)).fetchone()
    return (float(offer[0]) if offer else 0.0, 0.0)


def classify_portfolio(warehouse_id: str, as_of: date, conn: sqlite3.Connection | None = None, db_path: str = "database/inventra.db") -> list[SkuPolicy]:
    own = conn is None
    conn = conn or sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        pairs = conn.execute("SELECT DISTINCT sku FROM sales_daily WHERE warehouse_id=? AND sale_date<=? ORDER BY sku", (warehouse_id, as_of.isoformat())).fetchall()
        start12, end12 = rolling_12_months(as_of); recent_start, recent_end = recent_level_window(as_of)
        prepared = []
        for pair in pairs:
            sku = pair["sku"]
            history, recent = _daily(conn, sku, warehouse_id, start12, end12), _daily(conn, sku, warehouse_id, recent_start, recent_end)
            history_stats, recent_stats = compute_demand_stats(history), compute_demand_stats(recent)
            midpoint = recent_start + timedelta(days=(recent_end-recent_start).days // 2)
            substats = [compute_demand_stats(_daily(conn, sku, warehouse_id, recent_start, midpoint)), compute_demand_stats(_daily(conn, sku, warehouse_id, midpoint + timedelta(days=1), recent_end))]
            cost = _unit_cost(conn, sku)
            prepared.append((sku, history, history_stats, recent, recent_stats, detect_regime_shift(recent_stats, history_stats, substats), cost))
        # A new SKU is ranked on annualised observed consumption, not quietly
        # assigned C because it has existed for fewer than twelve months.
        values = {}
        for sku, history, _, _, _, _, cost in prepared:
            if cost is None:
                continue
            first_row = conn.execute("SELECT MIN(sale_date) FROM sales_daily WHERE sku=? AND warehouse_id=?", (sku, warehouse_id)).fetchone()
            first_date = date.fromisoformat(str(first_row[0])) if first_row and first_row[0] else start12
            observed_start = max(first_date, start12)
            observed_days = max(1, (end12 - observed_start).days + 1)
            values[sku] = consumption_value_12m(sum(history) * 365 / observed_days, cost)
        policies: list[SkuPolicy] = []
        for sku, history, history_stats, recent, stats, shift, cost in prepared:
            first = conn.execute("SELECT MIN(sale_date) FROM sales_daily WHERE sku=? AND warehouse_id=?", (sku, warehouse_id)).fetchone()[0]
            maturity, confidence = assess_maturity(date.fromisoformat(first) if first else None, as_of, stats.nonzero_observations)
            abc, share = classify_abc(values, sku) if sku in values else ("C", 1.0)
            previous = get_latest_sku_policy(sku, warehouse_id, as_of, db_path) if own else None
            hysteresis = apply_hysteresis(previous, abc, as_of, shift)
            level = stats.mean_daily_demand if stats.quadrant in {"SMOOTH", "ERRATIC"} else (lambda result: result[0] / result[1] if result[1] else 0)(croston_level(recent))
            lead, lead_std = _lead_time(conn, sku, warehouse_id)
            contribution = contribution_per_unit(sku, float(cost or 0), db_path) if cost is not None else None
            capital_rate, storage_rate, _carrying_basis = carrying_rate_per_day(sku, warehouse_id, db_path)
            holding = (float(cost or 0) * capital_rate + storage_rate) if cost is not None else 0.0
            service_class = hysteresis.active_class if maturity != "INSUFFICIENT" else "C"
            service = bounded_service_level(newsvendor_service_level(contribution or 0.0, holding), service_class)
            safety = (compute_safety_stock(service, lead, stats.std_daily_demand, level, lead_std)
                      if stats.quadrant in {"SMOOTH", "ERRATIC"}
                      else empirical_safety_stock(recent, lead, service, level))
            rop = compute_reorder_point(level, lead, safety)
            policy = SkuPolicy(sku=sku, warehouse_id=warehouse_id, as_of_date=as_of, mean_daily_demand=level, std_daily_demand=stats.std_daily_demand, cv=stats.cv, adi=stats.adi, cv_squared=stats.cv_squared_nonzero, demand_quadrant=stats.quadrant, abc_class=abc, xyz_class=classify_xyz(stats.cv), consumption_value_12m=values.get(sku, 0), cumulative_share=share, service_level=service, safety_stock_units=safety, reorder_point_units=rop, derived_cover_days=derived_cover_days(rop, level), statistical_target_units=rop, active_target_units=rop, maturity=maturity, confidence=confidence, candidate_class=hysteresis.candidate_class, candidate_since=hysteresis.candidate_since, consecutive_confirmations=hysteresis.consecutive_confirmations, active_class=hysteresis.active_class if maturity != "INSUFFICIENT" else "UNCLASSIFIED", change_reason=hysteresis.change_reason if maturity != "INSUFFICIENT" else "insufficient history: no permanent class")
            if own: upsert_sku_policy(policy, db_path)
            else:
                # Backfill calls with a shared connection; persist through the
                # same tested serializer after committing the raw seed data.
                policies.append(policy)
            policies.append(policy) if own else None
        return policies
    finally:
        if own: conn.close()
