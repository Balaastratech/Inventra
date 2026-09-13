from datetime import date, datetime, timedelta
import sqlite3

import pytest

from submission.statistics.abc_xyz import classify_abc, classify_xyz
from submission.statistics.demand import classify_quadrant, compute_demand_stats, croston_level
from submission.statistics.hysteresis import apply_hysteresis
from submission.statistics.maturity import assess_maturity
from submission.statistics.normal import inverse_normal_cdf
from submission.statistics.safety_stock import compute_reorder_point, compute_safety_stock, derived_cover_days, empirical_safety_stock
from submission.statistics.service_level import bounded_service_level, newsvendor_service_level
from submission.statistics.windows import detect_regime_shift, recent_level_window, rolling_12_months
from database.seed import init_db
from submission.statistics.classify import classify_portfolio
from submission.config import config
from tools.cost_inputs import carrying_rate_per_day, contribution_per_unit, landed_unit_cost, load_cost_inputs
from domain.tool_models import VendorOffer, VendorOption, VendorPerformance, VendorPerformanceList, StockRisk, LatenessDistribution
from submission.graph.economics import EconomicsInputs, evaluate_options


def test_inverse_normal_known_values_and_stats_classification():
    assert inverse_normal_cdf(0.5) == pytest.approx(0.0, abs=1e-9)
    assert inverse_normal_cdf(0.95) == pytest.approx(1.64485, abs=1e-4)
    stats = compute_demand_stats([0, 2, 0, 2])
    assert stats.adi == pytest.approx(2.0)
    assert stats.cv_squared_nonzero == 0
    assert stats.quadrant == "INTERMITTENT"
    assert croston_level([0, 2, 0, 2])[0] > 0


@pytest.mark.parametrize(
    ("adi", "cv2", "expected"),
    [(1.0, 0.1, "SMOOTH"), (1.0, 0.5, "ERRATIC"), (2.0, 0.1, "INTERMITTENT"), (2.0, 0.5, "LUMPY")],
)
def test_quadrants(adi, cv2, expected):
    assert classify_quadrant(adi, cv2, 1.32, 0.49) == expected


def test_windows_abc_xyz_maturity_service_and_stock_math():
    assert rolling_12_months(date(2026, 9, 12)) == (date(2025, 9, 1), date(2026, 8, 31))
    assert recent_level_window(date(2026, 9, 12), 30) == (date(2026, 8, 13), date(2026, 9, 11))
    assert classify_abc({"a": 75, "b": 17, "c": 8}, "a")[0] == "A"
    assert classify_xyz(0.3) == "X"
    assert assess_maturity(date(2025, 1, 1), date(2026, 1, 1), 60) == ("ESTABLISHED", 1.0)
    assert newsvendor_service_level(9, 1) == 0.9
    assert bounded_service_level(0.2, "A") == 0.95
    safety = compute_safety_stock(0.95, 5, 2, 10, 1)
    assert safety > 0
    assert compute_reorder_point(10, 5, safety) == pytest.approx(50 + safety)
    assert derived_cover_days(50, 10) == 5
    assert derived_cover_days(50, 0) is None
    assert empirical_safety_stock([0, 10, 0, 10], 2, .95, 5) >= 0


def test_regime_shift_and_hysteresis():
    baseline = compute_demand_stats([10] * 30)
    recent = compute_demand_stats([20] * 30)
    shift = detect_regime_shift(recent, baseline, [recent, recent])
    assert shift.is_significant and shift.is_sustained and shift.direction == "increase"
    first = apply_hysteresis(None, "B", date(2026, 1, 31), shift)
    assert first.active_class == "B"
    second = apply_hysteresis(first, "A", date(2026, 2, 28), shift)
    assert second.active_class == "A"
    assert "regime shift bypass" in second.change_reason


def test_classify_portfolio_persists_a_monthly_policy(tmp_path):
    db_path = tmp_path / "phase-b.db"
    init_db(str(db_path))
    as_of = date.today()
    with sqlite3.connect(db_path) as conn:
        conn.execute("INSERT INTO warehouses VALUES ('WH', 'Warehouse', 10)")
        conn.execute("INSERT INTO products (sku,name,category,active,selling_price,lifecycle,unit_volume_m3) VALUES ('S1','One','C',1,100,'MATURE',1)")
        conn.execute("INSERT INTO vendors (vendor_id,name,active,on_time_rate,fill_rate,quality_score,billing_basis) VALUES ('V','Vendor',1,.95,.98,.95,'ORDERED')")
        conn.execute("INSERT INTO vendor_offers (offer_id,vendor_id,sku,unit_price,moq,lead_time_days,valid_until,freight_flat,freight_per_unit) VALUES ('O','V','S1',50,1,2,?,0,0)", ((datetime.utcnow() + timedelta(days=3)).isoformat(),))
        conn.execute("INSERT INTO carrying_cost_inputs VALUES ('I',.1,.01,.01,?,'ops','test')", ((as_of - timedelta(days=1)).isoformat(),))
        for offset in range(370):
            day = as_of - timedelta(days=offset + 1)
            conn.execute("INSERT INTO sales_daily (sale_id,sale_date,sku,warehouse_id,units_sold) VALUES (?,?,?,?,?)", (f'S{offset}', day.isoformat(), 'S1', 'WH', 4))
    policies = classify_portfolio('WH', as_of, db_path=str(db_path))
    assert len(policies) == 1
    assert policies[0].reorder_point_units > 0
    with sqlite3.connect(db_path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM sku_policy").fetchone()[0] == 1


def test_measured_cost_inputs_have_independent_provenance(tmp_path):
    db_path = tmp_path / "cost-inputs.db"
    init_db(str(db_path))
    today = datetime.utcnow()
    with sqlite3.connect(db_path) as conn:
        conn.execute("INSERT INTO warehouses VALUES ('WH', 'Warehouse', 30)")
        conn.execute("INSERT INTO products (sku,name,category,active,selling_price,lifecycle,unit_volume_m3) VALUES ('S1','One','C',1,100,'MATURE',2)")
        conn.execute("INSERT INTO vendors (vendor_id,name,active,on_time_rate,fill_rate,quality_score,billing_basis) VALUES ('V','Vendor',1,.95,.98,.95,'SHIPPED')")
        conn.execute("INSERT INTO vendor_offers (offer_id,vendor_id,sku,unit_price,moq,lead_time_days,valid_until,freight_flat,freight_per_unit) VALUES ('O','V','S1',50,10,2,?,20,1)", ((today + timedelta(days=3)).isoformat(),))
        conn.execute("INSERT INTO carrying_cost_inputs VALUES ('I',.1,.02,.03,?,'ops','test')", (today.date().isoformat(),))
        for index in range(5):
            promised = today - timedelta(days=20-index)
            conn.execute("INSERT INTO stock_receipts VALUES (?,?,?,?,?,?,?,?,?,?,?)", (f'R{index}', None, 'S1', 'WH', 'V', 10, 10, (promised-timedelta(days=2)).isoformat(), promised.isoformat(), (promised+timedelta(days=4)).isoformat(), 6))
    original_path = config.database_path
    object.__setattr__(config, "database_path", str(db_path))
    try:
        offer = VendorOffer(offer_id='O', vendor_id='V', vendor_name='Vendor', unit_price=50, moq=10, lead_time_days=2, valid_until=today + timedelta(days=3), active=True, evidence_id='offer:O', freight_flat=20, freight_per_unit=1)
        assert landed_unit_cost(offer, 10) == 53
        assert contribution_per_unit('S1', 53) == 47
        capital, storage, basis = carrying_rate_per_day('S1', 'WH')
        assert capital == pytest.approx(.15 / 365)
        assert storage == pytest.approx(2)
        assert basis == 'measured'
        inputs = load_cost_inputs('S1', 'WH', ['V'])
        assert inputs.margin_basis == inputs.carrying_basis == 'measured'
        assert inputs.lateness_basis_by_vendor['V'] == 'measured'
        assert inputs.billing_basis_by_vendor['V'] == 'SHIPPED'
        with sqlite3.connect(db_path) as conn:
            conn.execute("UPDATE products SET lifecycle='EOL' WHERE sku='S1'")
        capital_with_eol, _, _ = carrying_rate_per_day('S1', 'WH')
        assert capital_with_eol == pytest.approx((.15 + config.eol_obsolescence_annual_rate) / 365)
    finally:
        object.__setattr__(config, "database_path", original_path)


def test_economics_prefers_fully_measured_inputs_without_assumption_caveats():
    now = datetime.utcnow()
    risk = StockRisk(available_units=2, daily_velocity=2, cover_days=1, projected_stockout_date=now + timedelta(days=10), target_cover_days=7, at_risk=True, freshness_hours=1, stale=False)
    option = VendorOption(offer_id='O', vendor_id='V', vendor_name='Vendor', quantity=20, unit_price=50, total_cost=1000, lead_time_days=2, expected_arrival=now + timedelta(days=2), meets_deadline=True, reliable=True, eligible=True, freight_flat=20, freight_per_unit=1)
    performance = VendorPerformanceList(vendors=[VendorPerformance(vendor_id='V', vendor_name='Vendor', on_time_rate=.95, fill_rate=.98, quality_score=.95, reliability=.96, eligible=True, evidence_id='vendor:V')], retrieved_at=now)
    lateness = LatenessDistribution(vendor_id='V', sku='S1', n_observations=5, on_time_rate_measured=.95, mean_late_days=4, p50_late_days=4, p90_late_days=4, evidence_id='late:V', retrieved_at=now)
    inputs = EconomicsInputs(47, 'measured', .15 / 365, 2, 'measured', {'V': lateness}, {'V': 'measured'}, {'V': 'SHIPPED'})
    result = evaluate_options(risk, [option], performance, inputs)
    assert result.caveats == []
    assert result.options[0].margin_basis == result.options[0].carrying_basis == 'measured'
    assert result.options[0].lateness_basis == result.options[0].billing_basis == 'measured'
    assert result.options[0].effective_cost_per_delivered_unit == pytest.approx(52 / .98, abs=.01)
