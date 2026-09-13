#!/usr/bin/env python
"""Reproducible Phase A demo data: rich history, not hand-written rows."""
from __future__ import annotations

import os
import random
import sqlite3
import sys
from datetime import datetime, timedelta
from pathlib import Path

# Running ``python database/seed.py`` makes ``database/`` the import root;
# add the repository root so the shared fixtures package remains available.
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from fixtures import fabricator

SCHEMA_PATH = Path(__file__).with_name("schema.sql")
WAREHOUSES = [("DEL-01", "Delhi Central", 18.0), ("MUM-01", "Mumbai Hub", 24.0), ("BLR-01", "Bengaluru Hub", 15.0), ("CHE-01", "Chennai Service", 20.0)]
VENDORS = [("V-FAST", "FastShip Inc.", 1, .95, .98, .96, "ORDERED", 15, "vuztral18@gmail.com"), ("V-CHEAP", "BudgetVendor Ltd.", 1, .92, .90, .91, "ORDERED", 45, "ravilan2389@gmail.com"), ("V-BALANCED", "Standard Supplier", 1, .93, .94, .93, "SHIPPED", 30, "earnwhop23@gmail.com"), ("V-SLOW", "SlowShip Co.", 1, .80, .85, .82, "ORDERED", 30, None), ("V-UNRELIABLE", "Shady Vendor LLC", 1, .70, .75, .72, "ORDERED", 60, None)]
CORE = [
    ("AC-001", "Air Conditioner Unit", "Appliances", "MATURE", 1200, .35, "legacy-3", 730, "DEL-01", 50, 10, 0),
    ("AC-002", "Air Conditioner Unit (Stale Data)", "Appliances", "MATURE", 1100, .35, "legacy-3", 730, "DEL-01", 40, 8, 0),
    ("AC-003", "Air Conditioner Unit (Speed Trade-off)", "Appliances", "MATURE", 1500, .35, "legacy-2", 730, "DEL-01", 20, 5, 0),
    ("AC-004", "Air Conditioner Unit (Over Budget)", "Appliances", "MATURE", 2200, .35, "legacy-3", 730, "DEL-01", 15, 3, 0),
    ("AC-005", "Air Conditioner Unit (New SKU)", "Appliances", "NEW", 900, .30, "legacy-2", 42, "DEL-01", 100, 10, 0),
    ("AC-006", "Air Conditioner Unit (Unreliable Vendor)", "Appliances", "MATURE", 1000, .35, "legacy-2", 730, "DEL-01", 12, 2, 0),
]
PROFILES = ["steady", "trending-up", "trending-down", "seasonal", "promo-spiky", "intermittent", "lumpy", "dead-eol"]


def _catalogue():
    rows = list(CORE)
    for index in range(29):
        profile = PROFILES[index % len(PROFILES)]
        # The lowest generated offer has a landed cost slightly above $102;
        # keep all synthetic selling prices above it so B10's negative-margin
        # data-integrity guard is exercised only by deliberate test fixtures.
        rows.append((f"SKU-{index + 1:03d}", f"{profile.title()} Demonstrator {index + 1}", "Service Parts", "EOL" if profile == "dead-eol" else "GROWTH" if profile == "trending-up" else "MATURE", 150 + index * 35, .005 + (index % 5) * .02, profile, 730, WAREHOUSES[index % 4][0], 40 + index * 3, 3, index % 8))
    return rows


def init_db(db_path="database/inventra.db"):
    """Initialize any target path from the canonical repository schema."""
    if os.path.exists(db_path): os.remove(db_path)
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
    conn.close()


def _offers(conn, sku, now):
    legacy = {
        "AC-001": [("OFFER-001-1", "V-FAST", 250, 5, 2), ("OFFER-001-2", "V-CHEAP", 200, 10, 5), ("OFFER-001-3", "V-BALANCED", 220, 5, 3)],
        "AC-002": [("OFFER-002-1", "V-FAST", 250, 5, 2), ("OFFER-002-2", "V-CHEAP", 200, 10, 5)],
        "AC-003": [("OFFER-003-1", "V-CHEAP", 180, 5, 7), ("OFFER-003-2", "V-FAST", 300, 3, 2)],
        "AC-004": [("OFFER-004-1", "V-FAST", 500, 3, 2), ("OFFER-004-2", "V-BALANCED", 450, 5, 3)],
        "AC-005": [("OFFER-005-1", "V-CHEAP", 200, 10, 5), ("OFFER-005-2", "V-FAST", 250, 5, 2)],
        "AC-006": [("OFFER-006-1", "V-UNRELIABLE", 150, 5, 3), ("OFFER-006-2", "V-SLOW", 160, 5, 4), ("OFFER-006-3", "V-FAST", 250, 5, 2)],
    }
    if sku in legacy:
        for offer_id, vendor, price, moq, lead in legacy[sku]:
            valid_until = now - timedelta(days=1) if offer_id == "OFFER-006-3" else now + timedelta(days=30)
            conn.execute("INSERT INTO vendor_offers (offer_id,vendor_id,sku,unit_price,moq,lead_time_days,valid_until,freight_flat,freight_per_unit,created_at) VALUES (?,?,?,?,?,?,?,?,?,?)", (offer_id, vendor, sku, price, moq, lead, valid_until, 15, .30, now - timedelta(days=2)))
        return
    for suffix, vendor, price, moq, lead, flat, unit in [("FAST", "V-FAST", 120, 3, 2, 25, .25), ("CHEAP", "V-CHEAP", 100, 5, 7, 10, .40), ("BAL", "V-BALANCED", 110, 5, 3, 15, .30)]:
        conn.execute("INSERT INTO vendor_offers (offer_id,vendor_id,sku,unit_price,moq,lead_time_days,valid_until,freight_flat,freight_per_unit,created_at) VALUES (?,?,?,?,?,?,?,?,?,?)", (f"OFFER-{sku}-{suffix}", vendor, sku, price, moq, lead, now + timedelta(days=30), flat, unit, now - timedelta(days=2)))


def _receipts(conn, sku, warehouse, now):
    for index in range(12):
        vendor = "V-BALANCED" if index % 2 else "V-CHEAP"
        promised = now - timedelta(days=180 - index * 12)
        late = 4 if vendor == "V-BALANCED" and index % 4 == 1 else 0
        fabricator.add_receipt(f"PO-{sku}-{index}", promised, promised + timedelta(days=late), 20, sku=sku, warehouse_id=warehouse, vendor_id=vendor, quantity_ordered=20, ordered_at=promised - timedelta(days=3), conn=conn)


def seed_data(db_path="database/inventra.db"):
    """Seed 35 SKUs, four warehouses, trade-offs, and measured receipt data."""
    random.seed(42); fabricator._RNG.seed(42)
    now = datetime.utcnow().replace(microsecond=0)
    conn = sqlite3.connect(db_path)
    try:
        for warehouse in WAREHOUSES: fabricator.upsert_warehouse(*warehouse, conn=conn)
        for vendor in VENDORS:
            conn.execute("INSERT INTO vendors (vendor_id,name,active,on_time_rate,fill_rate,quality_score,billing_basis,payment_terms_days,contact_email,created_at) VALUES (?,?,?,?,?,?,?,?,?,?)", (*vendor, now - timedelta(days=30)))
        for sku, name, category, lifecycle, price, volume, profile, days, warehouse, on_hand, reserved, inbound in _catalogue():
            conn.execute("INSERT INTO products (sku,name,category,active,selling_price,lifecycle,unit_volume_m3,created_at) VALUES (?,?,?,?,?,?,?,?)", (sku, name, category, 1, price, lifecycle, volume, now - timedelta(days=30)))
            fabricator.fabricate_history(sku, warehouse, days, profile, conn=conn)
            fabricator.set_position(sku, warehouse, on_hand, reserved, inbound, conn=conn)
            _offers(conn, sku, now); _receipts(conn, sku, warehouse, now)
        fabricator.set_carrying_inputs(.12, .03, .02, note="Seeded finance inputs", conn=conn)
        for warehouse_id, _name, _storage in WAREHOUSES:
            for moment in (now, now - timedelta(days=35)): fabricator.set_budget(warehouse_id, moment.strftime("%Y-%m"), 50000, 30000, 5000, conn=conn)
        fabricator.age_snapshot("AC-002", "DEL-01", 78, conn=conn)
        for sku, wh, units, cover, reason, source in [("AC-001", "DEL-01", 25, 8, "Key-account contractual SLA", "contract"), ("SKU-011", "BLR-01", 20, 4, "Warranty service-parts obligation", "warranty"), ("SKU-016", "CHE-01", 5, 2, "Legacy floor intentionally below demand", "legacy-policy"), ("SKU-021", "DEL-01", 500, 90, "Legacy floor intentionally above demand", "legacy-policy")]:
            conn.execute("INSERT INTO policy_rules VALUES (?,?,?,?,?,?,?,?,?,?,1)", (f"POL-{sku}-{wh}", sku, wh, units, cover, reason, source, "ops", now.date(), None))
        conn.commit()
    finally:
        conn.close()
    # Derived policy history is intentionally a separate implementation from
    # raw fact seeding, but the reproducible seeded database includes it.
    from database.backfill_classification import backfill_all
    backfill_all(db_path)


if __name__ == "__main__":
    init_db(); seed_data(); print("Database ready: database/inventra.db")
