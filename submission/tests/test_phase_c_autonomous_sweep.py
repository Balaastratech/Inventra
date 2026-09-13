from __future__ import annotations

from datetime import date, datetime, timedelta
import sqlite3

import pytest

from database.seed import init_db
from domain.tool_models import SkuPolicy
from submission.config import config


@pytest.fixture
def sweep_db(tmp_path):
    path = tmp_path / "phase-c.db"
    init_db(str(path))
    original = config.database_path
    object.__setattr__(config, "database_path", str(path))
    try:
        with sqlite3.connect(path) as conn:
            conn.execute("INSERT INTO warehouses VALUES ('WH', 'Warehouse', 10)")
            conn.execute("INSERT INTO products (sku,name,category,active,selling_price,lifecycle,unit_volume_m3) VALUES ('RISK','Risk','C',1,100,'MATURE',1)")
            conn.execute("INSERT INTO products (sku,name,category,active,selling_price,lifecycle,unit_volume_m3) VALUES ('PARK','Park','C',1,100,'MATURE',1)")
            now = datetime.utcnow().isoformat()
            conn.execute("INSERT INTO inventory_snapshots (snapshot_id,sku,warehouse_id,on_hand,reserved,confirmed_inbound,captured_at) VALUES ('I-R','RISK','WH',2,0,0,?)", (now,))
            conn.execute("INSERT INTO inventory_snapshots (snapshot_id,sku,warehouse_id,on_hand,reserved,confirmed_inbound,captured_at) VALUES ('I-P','PARK','WH',2,0,0,?)", (now,))
            for sku, maturity, reorder, value in (("RISK", "ESTABLISHED", 10, 1000), ("PARK", "INSUFFICIENT", 10, 50)):
                conn.execute(
                    """INSERT INTO sku_policy (sku, warehouse_id, as_of_date, mean_daily_demand, std_daily_demand,
                       cumulative_share, service_level, safety_stock_units, consecutive_confirmations,
                       reorder_point_units, derived_cover_days, consumption_value_12m, maturity, confidence,
                       demand_quadrant, abc_class, xyz_class, active_class, change_reason)
                       VALUES (?, 'WH', ?, 2, 1, 1, .95, 1, 1, ?, 14, ?, ?, .8, 'SMOOTH', 'A', 'X', 'A', '')""",
                    (sku, date.today().isoformat(), reorder, value, maturity),
                )
            conn.execute("INSERT INTO monthly_budgets (budget_id,warehouse_id,month,budget_amount,spent_amount,committed_amount) VALUES ('B', 'WH', ?, 100, 0, 0)", (date.today().strftime('%Y-%m'),))
        yield path
    finally:
        object.__setattr__(config, "database_path", original)


def test_bulk_policy_read_and_warehouse_source(sweep_db):
    from tools.classification import get_latest_policies_for_warehouse
    from submission.portfolio import list_warehouses

    assert {p.sku for p in get_latest_policies_for_warehouse("WH")} == {"RISK", "PARK"}
    assert list_warehouses() == ["WH"]


def test_detects_risk_and_parks_insufficient_maturity(sweep_db, monkeypatch):
    from submission.sweep.candidates import ExclusionReason, detect_candidates

    # Classification is already represented by the fixture; the detector's
    # refresh seam is separately tested by Phase B.
    monkeypatch.setattr("submission.sweep.candidates.classify_portfolio", lambda *args, **kwargs: [])
    candidates, exclusions = detect_candidates("WH", date.today())

    assert [candidate.sku for candidate in candidates] == ["RISK"]
    assert any(item.reason is ExclusionReason.INSUFFICIENT_MATURITY for item in exclusions)
    with sqlite3.connect(sweep_db) as conn:
        assert conn.execute("SELECT COUNT(*) FROM parked_items WHERE sku='PARK'").fetchone()[0] == 1


def test_detect_candidates_excludes_an_already_parked_sku(sweep_db, monkeypatch):
    from submission.sweep.candidates import ExclusionReason, detect_candidates
    from tools.parking import park_item

    monkeypatch.setattr("submission.sweep.candidates.classify_portfolio", lambda *args, **kwargs: [])
    park_item("RISK", "WH", "INSUFFICIENT_SALES_HISTORY", "Backfill recent sales before retrying.")
    candidates, exclusions = detect_candidates("WH", date.today())

    assert "RISK" not in [candidate.sku for candidate in candidates]
    assert any(item.sku == "RISK" and item.reason is ExclusionReason.ALREADY_PARKED for item in exclusions)


def test_budget_allocation_is_ranked_and_cumulative(sweep_db, monkeypatch):
    from submission.sweep.candidates import Candidate
    from submission.sweep.ranking import allocate_budget
    from tools.classification import get_latest_policies_for_warehouse

    policy = get_latest_policies_for_warehouse("WH")[0]
    first = Candidate("FIRST", "WH", policy.model_copy(update={"consumption_value_12m": 1000}), None, 1, "REORDER_POINT", 0)
    second = Candidate("SECOND", "WH", policy.model_copy(update={"consumption_value_12m": 10}), None, 1, "REORDER_POINT", 0)
    monkeypatch.setattr("submission.sweep.ranking.estimate_candidate_cost", lambda candidate: 60)

    allocation = allocate_budget([second, first], "WH", date.today().strftime("%Y-%m"))
    assert [candidate.sku for candidate in allocation.approved] == ["FIRST"]
    assert allocation.deferred[0][0].sku == "SECOND"
    assert "Budget would be exceeded" in allocation.deferred[0][1]


def test_parking_is_idempotent_and_sweep_records_round_trip(sweep_db):
    from submission.sweep.parking import maybe_park
    from tools.classification import get_latest_policies_for_warehouse
    from tools.sweep_runs import get_sweep_history, record_sweep_run

    policy = next(item for item in get_latest_policies_for_warehouse("WH") if item.sku == "PARK")
    first = maybe_park(policy, "PARK", "WH")
    second = maybe_park(policy, "PARK", "WH")
    assert second.park_id == first.park_id

    run = record_sweep_run(warehouse_ids=["WH"], pairs_examined=2, candidates_found=1,
                           parked_count=1, deferred_for_budget_count=0, cases_opened=0,
                           reminders_sent=0, total_model_calls_estimate=0, detail=[{"sku": "PARK"}])
    assert get_sweep_history(1)[0].sweep_id == run.sweep_id


def test_run_sweep_invokes_only_preallocated_candidates_and_records_result(sweep_db, monkeypatch):
    from submission.sweep.candidates import Candidate
    from submission.sweep.ranking import BudgetAllocationResult
    from submission.sweep.run import run_sweep
    from tools.classification import get_latest_policies_for_warehouse

    policy = next(item for item in get_latest_policies_for_warehouse("WH") if item.sku == "RISK")
    candidate = Candidate("RISK", "WH", policy, None, 2, "REORDER_POINT", 1.0)
    monkeypatch.setattr("submission.sweep.run.detect_candidates", lambda *_: ([candidate], []))
    monkeypatch.setattr("submission.sweep.run.allocate_budget", lambda *_: BudgetAllocationResult([candidate], []))
    invoked = []
    def execute(actual, month):
        invoked.append((actual.sku, month))
        return {"__interrupt__": [], "thread_id": "T"}
    monkeypatch.setattr("submission.sweep.run.execute_candidate", execute)

    run = run_sweep("WH", date.today())
    assert invoked == [("RISK", date.today().strftime("%Y-%m"))]
    assert run.cases_opened == run.candidates_found == 1
    assert run.total_model_calls_estimate == 3


def test_resweep_returns_reminder_or_revalidation_decision(monkeypatch):
    from submission.sweep.resweep import check_in_flight_case

    monkeypatch.setattr("submission.portfolio.list_pending_cases", lambda: [{
        "case_id": "CASE-RISK-WH", "thread_id": "T", "sku": "RISK", "warehouse_id": "WH",
        "status": "AWAITING_APPROVAL", "likely_stale": False,
    }])
    assert check_in_flight_case("RISK", "WH").kind == "REMINDER"
    monkeypatch.setattr("submission.portfolio.list_pending_cases", lambda: [{
        "case_id": "CASE-RISK-WH", "thread_id": "T", "sku": "RISK", "warehouse_id": "WH",
        "status": "AWAITING_APPROVAL", "likely_stale": True,
    }])
    assert check_in_flight_case("RISK", "WH").kind == "REVALIDATION_NEEDED"
