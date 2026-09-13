"""Phase F: only an immature, evidence-backed case may ask for cover days."""

from __future__ import annotations

from datetime import date
import inspect

from domain.tool_models import ProposalStatus, SkuPolicy
from submission.graph import nodes, routes


def _policy(maturity: str, cover: float | None = 18.0) -> SkuPolicy:
    return SkuPolicy(
        sku="AC-F", warehouse_id="DEL-F", as_of_date=date.today(),
        mean_daily_demand=3.0, derived_cover_days=cover, maturity=maturity,
    )


def _state(policy: SkuPolicy, supplied_cover: int | None = None) -> dict:
    return {
        "sku": "AC-F", "warehouse_id": "DEL-F", "case_id": "CASE-F",
        "trace_id": "TRACE-F", "retry_counts": {}, "sku_policy_snapshot": policy,
        "target_cover_days": supplied_cover,
    }


def test_established_policy_overrides_any_pre_supplied_cover_days():
    state = _state(_policy("ESTABLISHED", 19.6), supplied_cover=7)

    nodes.resolve_target_cover(state)

    assert routes.route_after_target_cover(state) == "ready"
    assert state["target_cover_days"] == 20
    assert state["target_provenance"] == "derived:sku_policy"


def test_provisional_policy_requires_the_single_manual_cover_days_input():
    state = _state(_policy("PROVISIONAL"))

    nodes.resolve_target_cover(state)

    assert routes.route_after_target_cover(state) == "manual_target_required"
    assert state["status"] is ProposalStatus.NEEDS_INFORMATION
    assert state["target_cover_days"] is None
    assert state["target_provenance"] == "pending_manual_cover_days"


def test_insufficient_maturity_with_valid_velocity_also_requires_cover_days_only():
    state = _state(_policy("INSUFFICIENT"))

    nodes.resolve_target_cover(state)

    assert routes.route_after_target_cover(state) == "manual_target_required"


def test_manual_target_resume_rejects_any_extra_human_number(monkeypatch):
    from submission.graph import workflow

    state = _state(_policy("PROVISIONAL"))
    monkeypatch.setattr(
        workflow,
        "interrupt",
        lambda _payload: {"target_cover_days": 21, "requested_by": "Yuvraj", "demand_rate": 99},
    )

    workflow._await_manual_target_cover(state)

    assert state["status"] is ProposalStatus.BLOCKED
    assert "only accepts days of stock" in state["error_detail"]


def test_manual_target_resume_requires_a_named_person(monkeypatch):
    from submission.graph import workflow

    state = _state(_policy("PROVISIONAL"))
    monkeypatch.setattr(workflow, "interrupt", lambda _payload: {"target_cover_days": 21})

    workflow._await_manual_target_cover(state)

    assert state["status"] is ProposalStatus.BLOCKED
    assert "named person" in state["error_detail"]


def test_manual_target_resume_records_named_human_provenance(monkeypatch):
    from submission.graph import workflow

    state = _state(_policy("PROVISIONAL"))
    monkeypatch.setattr(
        workflow,
        "interrupt",
        lambda _payload: {"target_cover_days": 21, "requested_by": "Yuvraj"},
    )

    workflow._await_manual_target_cover(state)

    assert state["target_cover_days"] == 21
    assert state["target_provenance"] == "human:Yuvraj"


def test_manual_cover_warning_names_the_person_who_set_the_target():
    from submission.ui_messages import manual_cover_warning

    assert manual_cover_warning(
        {"target_mode": "MANUAL_COVER_CONFIRMED", "target_provenance": "human:Yuvraj"}
    ) == (
        "There is not enough sales history for this product; the cover target "
        "was set by Yuvraj, not derived from data."
    )


def test_public_case_entrypoint_does_not_accept_a_target_or_order_quantity():
    from submission.app import run_case

    assert list(inspect.signature(run_case).parameters) == ["sku", "warehouse_id"]
