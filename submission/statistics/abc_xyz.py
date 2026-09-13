from submission.config import config


def consumption_value_12m(demand_12m_units: float, unit_cost: float) -> float:
    if demand_12m_units < 0 or unit_cost < 0:
        raise ValueError("consumption and unit cost must be non-negative")
    return demand_12m_units * unit_cost


def classify_abc(all_skus_consumption_value: dict[str, float], sku: str, a_threshold: float = config.abc_a_cumulative_pct, b_threshold: float = config.abc_b_cumulative_pct) -> tuple[str, float]:
    if sku not in all_skus_consumption_value:
        raise KeyError(f"{sku} is absent from the ABC portfolio")
    total = sum(max(0, value) for value in all_skus_consumption_value.values())
    if total <= 0:
        return "C", 1.0
    cumulative = 0.0
    for current_sku, value in sorted(all_skus_consumption_value.items(), key=lambda item: (-item[1], item[0])):
        cumulative += max(0, value) / total
        if current_sku == sku:
            return ("A" if cumulative <= a_threshold else "B" if cumulative <= b_threshold else "C"), cumulative
    raise AssertionError("unreachable")


def classify_xyz(cv: float | None, x_cutoff: float = config.xyz_x_cv_cutoff, y_cutoff: float = config.xyz_y_cv_cutoff) -> str:
    if cv is None or cv >= y_cutoff:
        return "Z"
    return "X" if cv < x_cutoff else "Y"
