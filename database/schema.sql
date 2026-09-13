-- Inventra Multi-Agent Stockout Resolution System
-- Database Schema
-- SQLite 3.x

-- ============================================================================
-- PRODUCTS
-- ============================================================================
CREATE TABLE IF NOT EXISTS products (
    sku TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    category TEXT NOT NULL,
    active BOOLEAN NOT NULL DEFAULT 1,
    selling_price REAL,
    lifecycle TEXT,
    unit_volume_m3 REAL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- ============================================================================
-- WAREHOUSES
-- ============================================================================
CREATE TABLE IF NOT EXISTS warehouses (
    warehouse_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    storage_cost_per_m3_month REAL NOT NULL
);

-- ============================================================================
-- INVENTORY SNAPSHOTS
-- ============================================================================
CREATE TABLE IF NOT EXISTS inventory_snapshots (
    snapshot_id TEXT PRIMARY KEY,
    sku TEXT NOT NULL,
    warehouse_id TEXT NOT NULL,
    on_hand INTEGER NOT NULL,
    reserved INTEGER NOT NULL,
    confirmed_inbound INTEGER NOT NULL,
    captured_at TIMESTAMP NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (sku) REFERENCES products(sku),
    UNIQUE(sku, warehouse_id, captured_at)
);

CREATE INDEX IF NOT EXISTS idx_inventory_snapshots_sku_warehouse 
    ON inventory_snapshots(sku, warehouse_id);
CREATE INDEX IF NOT EXISTS idx_inventory_snapshots_captured_at 
    ON inventory_snapshots(captured_at);

-- ============================================================================
-- SALES HISTORY
-- ============================================================================
CREATE TABLE IF NOT EXISTS sales_daily (
    sale_id TEXT PRIMARY KEY,
    sale_date DATE NOT NULL,
    sku TEXT NOT NULL,
    warehouse_id TEXT NOT NULL,
    units_sold INTEGER NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (sku) REFERENCES products(sku),
    UNIQUE(sale_date, sku, warehouse_id)
);

CREATE INDEX IF NOT EXISTS idx_sales_daily_sku_warehouse 
    ON sales_daily(sku, warehouse_id);
CREATE INDEX IF NOT EXISTS idx_sales_daily_date 
    ON sales_daily(sale_date);

-- ============================================================================
-- VENDORS
-- ============================================================================
CREATE TABLE IF NOT EXISTS vendors (
    vendor_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    active BOOLEAN NOT NULL DEFAULT 1,
    on_time_rate REAL NOT NULL,  -- 0.0 to 1.0
    fill_rate REAL NOT NULL,      -- 0.0 to 1.0
    quality_score REAL NOT NULL,  -- 0.0 to 1.0
    notes TEXT,                   -- Untrusted data; not instructions
    contact_email TEXT,           -- Ops-maintained; never populated from evidence/agent text (Gap 8)
    billing_basis TEXT,
    payment_terms_days INTEGER,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_vendors_active ON vendors(active);

-- ============================================================================
-- VENDOR OFFERS
-- ============================================================================
CREATE TABLE IF NOT EXISTS vendor_offers (
    offer_id TEXT PRIMARY KEY,
    vendor_id TEXT NOT NULL,
    sku TEXT NOT NULL,
    unit_price REAL NOT NULL,
    moq INTEGER NOT NULL,  -- Minimum Order Quantity
    lead_time_days INTEGER NOT NULL,
    valid_until TIMESTAMP NOT NULL,
    freight_flat REAL,
    freight_per_unit REAL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (vendor_id) REFERENCES vendors(vendor_id),
    FOREIGN KEY (sku) REFERENCES products(sku),
    UNIQUE(vendor_id, sku, valid_until)
);

CREATE INDEX IF NOT EXISTS idx_vendor_offers_sku ON vendor_offers(sku);
CREATE INDEX IF NOT EXISTS idx_vendor_offers_vendor ON vendor_offers(vendor_id);
CREATE INDEX IF NOT EXISTS idx_vendor_offers_valid_until ON vendor_offers(valid_until);

-- ============================================================================
-- MONTHLY BUDGETS
-- ============================================================================
CREATE TABLE IF NOT EXISTS monthly_budgets (
    budget_id TEXT PRIMARY KEY,
    warehouse_id TEXT NOT NULL,
    month TEXT NOT NULL,  -- YYYY-MM format
    budget_amount REAL NOT NULL,
    spent_amount REAL NOT NULL DEFAULT 0,
    committed_amount REAL NOT NULL DEFAULT 0,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(warehouse_id, month)
);

CREATE INDEX IF NOT EXISTS idx_monthly_budgets_warehouse_month 
    ON monthly_budgets(warehouse_id, month);

-- ============================================================================
-- STOCK RECEIPTS AND PHASE B CLASSIFICATION INPUTS
-- ============================================================================
CREATE TABLE IF NOT EXISTS stock_receipts (
    receipt_id TEXT PRIMARY KEY,
    request_id TEXT,
    sku TEXT NOT NULL,
    warehouse_id TEXT NOT NULL,
    vendor_id TEXT NOT NULL,
    quantity_ordered INTEGER NOT NULL,
    quantity_received INTEGER NOT NULL,
    ordered_at TIMESTAMP NOT NULL,
    promised_at TIMESTAMP NOT NULL,
    received_at TIMESTAMP NOT NULL,
    lead_time_days_actual REAL NOT NULL,
    FOREIGN KEY (sku) REFERENCES products(sku)
);
CREATE INDEX IF NOT EXISTS idx_stock_receipts_vendor_sku ON stock_receipts(vendor_id, sku);

CREATE TABLE IF NOT EXISTS sku_policy (
    sku TEXT NOT NULL,
    warehouse_id TEXT NOT NULL,
    as_of_date DATE NOT NULL,
    mean_daily_demand REAL, std_daily_demand REAL, cv REAL, adi REAL, cv_squared REAL,
    demand_quadrant TEXT, abc_class TEXT, xyz_class TEXT, consumption_value_12m REAL,
    cumulative_share REAL, service_level REAL, safety_stock_units REAL,
    reorder_point_units REAL, derived_cover_days REAL, statistical_target_units REAL,
    active_target_units REAL, maturity TEXT, confidence REAL,
    candidate_class TEXT, candidate_since DATE, consecutive_confirmations INTEGER,
    active_class TEXT, change_reason TEXT,
    UNIQUE(sku, warehouse_id, as_of_date),
    FOREIGN KEY (sku) REFERENCES products(sku)
);

CREATE TABLE IF NOT EXISTS policy_rules (
    rule_id TEXT PRIMARY KEY,
    sku TEXT NOT NULL,
    warehouse_id TEXT NOT NULL,
    min_units INTEGER,
    min_cover_days REAL,
    reason TEXT NOT NULL,
    source TEXT NOT NULL,
    set_by TEXT NOT NULL,
    effective_from DATE NOT NULL,
    effective_to DATE,
    active BOOLEAN NOT NULL DEFAULT 1,
    FOREIGN KEY (sku) REFERENCES products(sku)
);
CREATE INDEX IF NOT EXISTS idx_policy_rules_active ON policy_rules(sku, warehouse_id, active);

CREATE TABLE IF NOT EXISTS parked_items (
    park_id TEXT PRIMARY KEY,
    sku TEXT NOT NULL,
    warehouse_id TEXT NOT NULL,
    reason TEXT NOT NULL,
    parked_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    resolved_at TIMESTAMP,
    resolved_by TEXT,
    note TEXT,
    FOREIGN KEY (sku) REFERENCES products(sku)
);

CREATE TABLE IF NOT EXISTS sweep_runs (
    sweep_id TEXT PRIMARY KEY,
    started_at TIMESTAMP NOT NULL,
    completed_at TIMESTAMP,
    warehouse_ids TEXT NOT NULL,
    pairs_examined INTEGER NOT NULL DEFAULT 0,
    candidates_found INTEGER NOT NULL DEFAULT 0,
    parked_count INTEGER NOT NULL DEFAULT 0,
    deferred_for_budget_count INTEGER NOT NULL DEFAULT 0,
    cases_opened INTEGER NOT NULL DEFAULT 0,
    reminders_sent INTEGER NOT NULL DEFAULT 0,
    total_model_calls_estimate INTEGER NOT NULL DEFAULT 0,
    detail_json TEXT
);

CREATE TABLE IF NOT EXISTS carrying_cost_inputs (
    input_id TEXT PRIMARY KEY,
    cost_of_capital_annual_rate REAL NOT NULL,
    insurance_annual_rate REAL NOT NULL,
    shrinkage_annual_rate REAL NOT NULL,
    effective_from DATE NOT NULL UNIQUE,
    set_by TEXT NOT NULL,
    note TEXT
);

-- ============================================================================
-- PURCHASE REQUESTS
-- ============================================================================
CREATE TABLE IF NOT EXISTS purchase_requests (
    request_id TEXT PRIMARY KEY,
    case_id TEXT NOT NULL,
    vendor_id TEXT NOT NULL,
    sku TEXT NOT NULL,
    warehouse_id TEXT NOT NULL,
    quantity INTEGER NOT NULL,
    unit_price REAL NOT NULL,
    total_cost REAL NOT NULL,
    status TEXT NOT NULL,  -- PENDING, CONFIRMED, REJECTED, CANCELLED, FAILED
    idempotency_key TEXT NOT NULL UNIQUE,
    approved_by TEXT,
    approved_at TIMESTAMP,
    vendor_sent_at TIMESTAMP,      -- Phase 8: when the vendor PO email was sent, if ever
    vendor_send_status TEXT,       -- Phase 8: SENT, FAILED, or NULL (never attempted / disabled)
    vendor_reminder_count INTEGER NOT NULL DEFAULT 0,
    vendor_last_reminded_at TIMESTAMP,
    cancelled_at TIMESTAMP,        -- B3: when a human cancelled it, if ever
    cancelled_by TEXT,             -- B3: named human who cancelled; never an agent
    cancel_reason TEXT,            -- B3: why, required by cancel_purchase_request
    committed_budget_month TEXT,   -- month whose monthly_budgets.committed_amount this
                                    -- request reserved, so cancel releases the same month
                                    -- it committed rather than "the current month"
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (vendor_id) REFERENCES vendors(vendor_id),
    FOREIGN KEY (sku) REFERENCES products(sku)
);

CREATE INDEX IF NOT EXISTS idx_purchase_requests_case_id ON purchase_requests(case_id);
CREATE INDEX IF NOT EXISTS idx_purchase_requests_status ON purchase_requests(status);
CREATE INDEX IF NOT EXISTS idx_purchase_requests_idempotency_key ON purchase_requests(idempotency_key);

-- ============================================================================
-- AUDIT EVENTS
-- ============================================================================
CREATE TABLE IF NOT EXISTS audit_events (
    event_id TEXT PRIMARY KEY,
    case_id TEXT NOT NULL,
    trace_id TEXT NOT NULL,
    actor TEXT NOT NULL,  -- "system", "agent:*", "human:*"
    event_type TEXT NOT NULL,  -- "risk_assessed", "proposal_prepared", "approved", etc.
    payload_json TEXT NOT NULL,  -- JSON-encoded event details
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_audit_events_case_id ON audit_events(case_id);
CREATE INDEX IF NOT EXISTS idx_audit_events_trace_id ON audit_events(trace_id);
CREATE INDEX IF NOT EXISTS idx_audit_events_created_at ON audit_events(created_at);

-- One delivery per unchanged terminal lifecycle event. This prevents a
-- continuous monitor from re-emailing the same healthy/blocked result.
CREATE TABLE IF NOT EXISTS notification_deliveries (
    case_id TEXT NOT NULL,
    event_type TEXT NOT NULL,
    fingerprint TEXT NOT NULL,
    sent_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (case_id, event_type, fingerprint)
);

-- ============================================================================
-- AGENT MEMORY SIGNALS (Gap 9: preference-learning store)
-- ============================================================================
CREATE TABLE IF NOT EXISTS agent_memory_signals (
    id TEXT PRIMARY KEY,
    entity_type TEXT NOT NULL,     -- "vendor", etc.
    entity_key TEXT NOT NULL,      -- e.g. vendor_id
    signal_type TEXT NOT NULL,     -- "human_rejected", "late_delivery", etc.
    signal_text TEXT NOT NULL,
    weight REAL NOT NULL DEFAULT 1.0,
    source_case_id TEXT NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_agent_memory_signals_entity
    ON agent_memory_signals(entity_type, entity_key);

-- ============================================================================
-- DATA CHANGE LOG (Phase G / DG5: durable, restart-surviving change log for
-- the G1 data console -- the fabricator's in-memory _LOG does not survive a
-- process restart, so this is the persisted record of who changed what.)
-- ============================================================================
CREATE TABLE IF NOT EXISTS data_change_log (
    change_id TEXT PRIMARY KEY,
    changed_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    changed_by TEXT NOT NULL,
    table_name TEXT NOT NULL,
    row_key TEXT NOT NULL,
    action TEXT NOT NULL,  -- CREATE, UPDATE, DELETE, BACKFILL
    before_json TEXT,
    after_json TEXT,
    note TEXT
);

CREATE INDEX IF NOT EXISTS idx_data_change_log_table ON data_change_log(table_name);
CREATE INDEX IF NOT EXISTS idx_data_change_log_changed_at ON data_change_log(changed_at);
