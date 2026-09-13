from submission.config import config


def newsvendor_service_level(understock_cost_per_unit: float, overstock_cost_per_unit_per_period: float) -> float:
    if understock_cost_per_unit < 0 or overstock_cost_per_unit_per_period < 0:
        raise ValueError("costs must be non-negative")
    total = understock_cost_per_unit + overstock_cost_per_unit_per_period
    return .5 if total == 0 else understock_cost_per_unit / total


def bounded_service_level(raw_service_level: float, abc_class: str, floors: dict[str, float] | None = None, caps: dict[str, float] | None = None) -> float:
    floors, caps = floors or config.service_level_floor_by_class, caps or config.service_level_cap_by_class
    if abc_class not in floors or abc_class not in caps:
        raise ValueError(f"unknown ABC class {abc_class}")
    return min(caps[abc_class], max(floors[abc_class], raw_service_level))
