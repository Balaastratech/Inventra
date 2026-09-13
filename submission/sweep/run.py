from __future__ import annotations

from datetime import date, datetime

from domain.tool_models import SweepRun
from submission.sweep.candidates import ExclusionReason, detect_candidates
from submission.sweep.ranking import allocate_budget
from tools.sweep_runs import record_sweep_run


def execute_candidate(candidate, budget_month: str) -> dict:
    """Invoke the existing graph once with the sweep's derived state."""
    from submission.agents.wiring import wire_agents
    from submission.graph.workflow import compile_graph
    from submission.state.state import create_initial_state
    wire_agents()
    state = create_initial_state(candidate.sku, candidate.warehouse_id,
        target_cover_days=round(candidate.policy.derived_cover_days) if candidate.policy.derived_cover_days else None,
        budget_month=budget_month, sku_policy_snapshot=candidate.policy)
    graph, conn = compile_graph()
    try:
        return graph.invoke(state, config={"configurable": {"thread_id": state["thread_id"]}})
    finally:
        conn.close()


def run_sweep(warehouse_id: str | None = None, as_of: date | None = None) -> SweepRun:
    from tools.warehouses import list_warehouses
    started, as_of = datetime.utcnow(), as_of or date.today()
    warehouses = [warehouse_id] if warehouse_id else [item.warehouse_id for item in list_warehouses()]
    budget_month, detail = as_of.strftime("%Y-%m"), []
    examined = found = parked = deferred = opened = reminders = 0
    for wh in warehouses:
        candidates, exclusions = detect_candidates(wh, as_of)
        examined += len(candidates) + len(exclusions); found += len(candidates)
        parked += sum(item.reason is ExclusionReason.INSUFFICIENT_MATURITY for item in exclusions)
        detail.extend({"sku": item.sku, "warehouse_id": wh, "outcome": "excluded", "reason": item.reason.value} for item in exclusions)
        for item in exclusions:
            if item.reason is ExclusionReason.CASE_ALREADY_OPEN:
                from submission.sweep.resweep import check_in_flight_case
                action = check_in_flight_case(item.sku, wh)
                if action is not None:
                    if action.kind == "VENDOR_SEND_REMINDER":
                        from submission.app import load_case
                        from submission.notifications.email import notify_vendor_approval_reminder
                        from tools.execution import mark_vendor_reminder_sent
                        values, waiting = load_case(action.case_id, action.thread_id)
                        if waiting and values.get("purchase_result") is not None:
                            reminder_count = mark_vendor_reminder_sent(values["purchase_result"].request_id)
                            notify_vendor_approval_reminder(values, reminder_count)
                            reminders += 1
                    elif action.kind == "REMINDER":
                        reminders += 1
                    detail.append({"sku": item.sku, "warehouse_id": wh, "outcome": action.kind, "detail": action.message, "thread_id": action.thread_id})
        allocation = allocate_budget(candidates, wh, budget_month)
        deferred += len(allocation.deferred)
        detail.extend({"sku": candidate.sku, "warehouse_id": wh, "outcome": "deferred", "reason": reason} for candidate, reason in allocation.deferred)
        for candidate in allocation.approved:
            result = execute_candidate(candidate, budget_month)
            status = result.get("status")
            status = status.value if hasattr(status, "value") else str(status or "AWAITING_APPROVAL")
            did_open = "__interrupt__" in result or status == "AWAITING_APPROVAL"
            opened += int(did_open)
            detail.append({"sku": candidate.sku, "warehouse_id": wh, "outcome": "opened" if did_open else status, "thread_id": result.get("thread_id")})
    return record_sweep_run(warehouse_ids=warehouses, pairs_examined=examined, candidates_found=found,
        parked_count=parked, deferred_for_budget_count=deferred, cases_opened=opened, reminders_sent=reminders,
        total_model_calls_estimate=opened * 3, detail=detail, started_at=started, completed_at=datetime.utcnow())
