from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from tools.cost_inputs import landed_unit_cost
from tools.policy import get_budget_position


def urgency_score(candidate) -> float:
    demand = candidate.policy.mean_daily_demand
    cover = candidate.current_position / demand if demand > 0 else 0.0
    return float(candidate.policy.consumption_value_12m) / max(cover, 0.1)


def estimate_candidate_cost(candidate) -> float:
    """Cheap, conservative proxy used only to reserve a place in the sweep."""
    import sqlite3
    from submission.config import config

    with sqlite3.connect(config.database_path) as conn:
        row = conn.execute("""SELECT unit_price, freight_flat, freight_per_unit, moq
                              FROM vendor_offers WHERE sku=? AND valid_until >= ?
                              ORDER BY unit_price + COALESCE(freight_per_unit, 0) + COALESCE(freight_flat, 0) / MAX(moq, 1) LIMIT 1""", (candidate.sku, datetime.utcnow().isoformat())).fetchone()
    if not row:
        return float("inf")
    class Offer: pass
    offer = Offer(); offer.unit_price, offer.freight_flat, offer.freight_per_unit = row[0], row[1], row[2]
    return max(0.0, float(candidate.policy.reorder_point_units) * landed_unit_cost(offer, max(1, int(candidate.policy.reorder_point_units))))


@dataclass(frozen=True)
class BudgetAllocationResult:
    approved: list
    deferred: list[tuple]


def allocate_budget(candidates: list, warehouse_id: str, budget_month: str) -> BudgetAllocationResult:
    budget = get_budget_position(warehouse_id, budget_month)
    if budget.error is not None:
        return BudgetAllocationResult([], [(candidate, f"Budget unavailable: {budget.error.value}") for candidate in candidates])
    approved, deferred, running = [], [], float(budget.committed_amount + budget.spent_amount)
    for candidate in sorted(candidates, key=urgency_score, reverse=True):
        estimated = estimate_candidate_cost(candidate)
        if running + estimated <= budget.budget_amount:
            approved.append(candidate); running += estimated
        else:
            remaining = budget.budget_amount - running
            deferred.append((candidate, f"Budget would be exceeded: estimated ${estimated:,.2f} against ${remaining:,.2f} remaining after {len(approved)} higher-priority candidate(s)."))
    return BudgetAllocationResult(approved, deferred)
