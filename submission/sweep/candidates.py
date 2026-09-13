from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
from enum import Enum

from domain.tool_models import PolicyFloor, SkuPolicy
from submission.config import config
from submission.statistics.classify import classify_portfolio
from tools.classification import get_latest_policies_for_warehouse
from tools.execution import get_open_order_quantity
from tools.inventory import get_product, get_stock_position
from tools.policy_floors import get_active_policy_floor


@dataclass(frozen=True)
class Candidate:
    sku: str; warehouse_id: str; policy: SkuPolicy; policy_floor: PolicyFloor | None
    current_position: int; trigger: str; urgency_score: float


class ExclusionReason(str, Enum):
    DATA_STALE = "stale snapshot"; CASE_ALREADY_OPEN = "already has a pending case awaiting a human"
    SUFFICIENT_ON_ORDER = "already on order in sufficient quantity"; INACTIVE = "product inactive/EOL"
    INSUFFICIENT_MATURITY = "maturity INSUFFICIENT -- parked, not excluded"
    ALREADY_PARKED = "already parked pending human data resolution"
    HEALTHY = "current position covers reorder point and any policy floor"


@dataclass(frozen=True)
class ExclusionRecord:
    sku: str; warehouse_id: str; reason: ExclusionReason; detail: str


def _stale(captured_at) -> bool:
    if isinstance(captured_at, str): captured_at = datetime.fromisoformat(captured_at)
    if captured_at.tzinfo is not None: captured_at = captured_at.astimezone(timezone.utc).replace(tzinfo=None)
    return (datetime.utcnow() - captured_at).total_seconds() / 3600 > config.data_freshness_hours


def _has_pending_case(sku: str, warehouse_id: str) -> bool:
    from submission.portfolio import list_pending_cases
    return any(item.get("sku") == sku and item.get("warehouse_id") == warehouse_id for item in list_pending_cases())


def detect_candidates(warehouse_id: str, as_of: date | None = None) -> tuple[list[Candidate], list[ExclusionRecord]]:
    as_of = as_of or date.today()
    # Refresh is deliberate.  A test or an offline operator can supply an
    # already materialized policy table; then the same bulk read is used.
    classify_portfolio(warehouse_id, as_of, db_path=config.database_path)
    from tools.parking import get_open_parked_items
    open_parked_skus = {item.sku for item in get_open_parked_items(warehouse_id)}
    candidates, exclusions = [], []
    for policy in get_latest_policies_for_warehouse(warehouse_id, as_of):
        if policy.sku in open_parked_skus:
            exclusions.append(ExclusionRecord(
                policy.sku, warehouse_id, ExclusionReason.ALREADY_PARKED,
                "Waiting on a human to resolve an open parked item.",
            ))
            continue
        product = get_product(policy.sku)
        if not product.active:
            exclusions.append(ExclusionRecord(policy.sku, warehouse_id, ExclusionReason.INACTIVE, "Product is inactive or EOL.")); continue
        stock = get_stock_position(policy.sku, warehouse_id)
        if stock.error is not None or _stale(stock.captured_at):
            exclusions.append(ExclusionRecord(policy.sku, warehouse_id, ExclusionReason.DATA_STALE, "Stock snapshot is missing or stale.")); continue
        if policy.maturity == "INSUFFICIENT":
            from submission.sweep.parking import maybe_park
            maybe_park(policy, policy.sku, warehouse_id)
            exclusions.append(ExclusionRecord(policy.sku, warehouse_id, ExclusionReason.INSUFFICIENT_MATURITY, "Parked for additional demand history.")); continue
        open_units = get_open_order_quantity(policy.sku, warehouse_id)
        position = stock.on_hand - stock.reserved + stock.confirmed_inbound + open_units
        floor = get_active_policy_floor(policy.sku, warehouse_id, as_of)
        floor_units = max(float(floor.min_units or 0), float(floor.min_cover_days or 0) * policy.mean_daily_demand) if floor else 0.0
        threshold = max(float(policy.reorder_point_units), floor_units)
        if position >= threshold:
            reason = ExclusionReason.SUFFICIENT_ON_ORDER if open_units else ExclusionReason.HEALTHY
            exclusions.append(ExclusionRecord(policy.sku, warehouse_id, reason, f"Position {position} covers threshold {threshold:.2f}.")); continue
        if _has_pending_case(policy.sku, warehouse_id):
            exclusions.append(ExclusionRecord(policy.sku, warehouse_id, ExclusionReason.CASE_ALREADY_OPEN, "A paused human-action case already exists.")); continue
        trigger = "BOTH" if position < policy.reorder_point_units and position < floor_units else "POLICY_FLOOR" if position < floor_units else "REORDER_POINT"
        from submission.sweep.ranking import urgency_score
        provisional = Candidate(policy.sku, warehouse_id, policy, floor, position, trigger, 0.0)
        candidates.append(Candidate(policy.sku, warehouse_id, policy, floor, position, trigger, urgency_score(provisional)))
    return candidates, exclusions
