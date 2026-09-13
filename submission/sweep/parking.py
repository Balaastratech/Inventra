from __future__ import annotations

from domain.tool_models import ParkedItemRecord, SkuPolicy
from tools.parking import park_item


def maybe_park(policy: SkuPolicy, sku: str, warehouse_id: str) -> ParkedItemRecord:
    observations = round(policy.confidence * 60) if policy.confidence else 0
    note = (f"{sku}/{warehouse_id} is {policy.maturity}: {observations} estimated observations; "
            f"mean={policy.mean_daily_demand:.2f}, cv={policy.cv}, adi={policy.adi}, "
            f"quadrant={policy.demand_quadrant}. More history is required before autonomous ordering.")
    return park_item(sku, warehouse_id, "INSUFFICIENT_MATURITY", note)
