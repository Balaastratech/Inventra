"""Read-only measured cost inputs shared by policy classification and economics."""
from __future__ import annotations

import sqlite3
from typing import Iterable

from submission.config import config
from tools.receipts import get_lateness_distribution


def _connect(db_path: str | None = None):
    conn = sqlite3.connect(db_path or config.database_path)
    conn.row_factory = sqlite3.Row
    return conn


def contribution_per_unit(sku: str, landed_cost: float, db_path: str | None = None) -> float | None:
    with _connect(db_path) as conn:
        row = conn.execute("SELECT selling_price FROM products WHERE sku=?", (sku,)).fetchone()
    if not row or row["selling_price"] is None:
        return None
    contribution = float(row["selling_price"]) - landed_cost
    if contribution < 0:
        raise ValueError(f"selling price is below landed cost for {sku}")
    return contribution


def carrying_rate_per_day(sku: str, warehouse_id: str, db_path: str | None = None) -> tuple[float, float, str]:
    with _connect(db_path) as conn:
        finance = conn.execute("SELECT cost_of_capital_annual_rate, insurance_annual_rate, shrinkage_annual_rate FROM carrying_cost_inputs ORDER BY effective_from DESC LIMIT 1").fetchone()
        storage = conn.execute("SELECT p.unit_volume_m3, p.lifecycle, w.storage_cost_per_m3_month FROM products p JOIN warehouses w WHERE p.sku=? AND w.warehouse_id=?", (sku, warehouse_id)).fetchone()
    base_capital = ((finance["cost_of_capital_annual_rate"] + finance["insurance_annual_rate"] + finance["shrinkage_annual_rate"]) / 365) if finance else config.assumed_annual_carrying_rate / 365
    lifecycle = storage["lifecycle"] if storage else None
    obsolescence = config.eol_obsolescence_annual_rate if lifecycle == "EOL" else config.declining_obsolescence_annual_rate if lifecycle == "DECLINING" else 0.0
    capital = base_capital + obsolescence / 365
    storage_measured = bool(storage and storage["unit_volume_m3"] is not None and storage["storage_cost_per_m3_month"] is not None)
    storage_rate = (storage["unit_volume_m3"] * storage["storage_cost_per_m3_month"] / 30) if storage_measured else 0.0
    return float(capital), float(storage_rate), "measured" if finance and storage_measured else "assumed"


def landed_unit_cost(offer, quantity_being_priced: int = 1) -> float:
    if quantity_being_priced <= 0:
        raise ValueError("quantity_being_priced must be positive")
    return float(offer.unit_price) + float(getattr(offer, "freight_per_unit", None) or 0) + float(getattr(offer, "freight_flat", None) or 0) / quantity_being_priced


def load_cost_inputs(sku: str, warehouse_id: str, vendor_ids: Iterable[str], db_path: str | None = None):
    from submission.graph.economics import EconomicsInputs
    vendor_ids = list(vendor_ids)
    active_db_path = db_path or config.database_path
    capital, storage, carrying_basis = carrying_rate_per_day(sku, warehouse_id, active_db_path)
    with _connect(active_db_path) as conn:
        rows = conn.execute("SELECT vendor_id, billing_basis FROM vendors WHERE vendor_id IN (%s)" % ",".join("?" for _ in vendor_ids), vendor_ids).fetchall() if vendor_ids else []
        cheapest = conn.execute("SELECT unit_price, freight_flat, freight_per_unit, moq FROM vendor_offers WHERE sku=? AND valid_until>=CURRENT_TIMESTAMP ORDER BY unit_price + COALESCE(freight_per_unit, 0) + COALESCE(freight_flat, 0) / MAX(moq, 1) LIMIT 1", (sku,)).fetchone()
    billing = {row["vendor_id"]: row["billing_basis"] for row in rows if row["billing_basis"] in {"ORDERED", "SHIPPED"}}
    lateness = {vendor: get_lateness_distribution(vendor, sku, db_path=active_db_path) for vendor in vendor_ids}
    landed = (float(cheapest["unit_price"]) + float(cheapest["freight_per_unit"] or 0) + float(cheapest["freight_flat"] or 0) / max(int(cheapest["moq"]), 1)) if cheapest else None
    contribution = contribution_per_unit(sku, landed, active_db_path) if landed is not None else None
    return EconomicsInputs(contribution, "measured" if contribution is not None else "assumed", capital, storage, carrying_basis, lateness, {vendor: "measured" if value else "assumed" for vendor, value in lateness.items()}, billing)
