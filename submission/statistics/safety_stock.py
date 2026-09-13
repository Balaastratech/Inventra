import math
from typing import Any

from .normal import inverse_normal_cdf


def compute_safety_stock(service_level: float, lead_time_days: float, demand_std: float, demand_mean: float, lead_time_std: float) -> float:
    if min(lead_time_days, demand_std, demand_mean, lead_time_std) < 0:
        raise ValueError("stock inputs must be non-negative")
    return inverse_normal_cdf(service_level) * math.sqrt(lead_time_days * demand_std**2 + demand_mean**2 * lead_time_std**2)


def compute_reorder_point(demand_mean: float, lead_time_days: float, safety_stock: float) -> float:
    return max(0.0, demand_mean * lead_time_days + safety_stock)


def derived_cover_days(reorder_point_units: float, demand_mean: float) -> float | None:
    return None if demand_mean <= 0 else reorder_point_units / demand_mean


def empirical_safety_stock(daily_units: list[int], lead_time_days: float, service_level: float, demand_level: float) -> float:
    """Distribution-free safety stock for intermittent/lumpy demand.

    It uses every observed rolling lead-time demand total (rather than applying
    a normal z-score to sparse, zero-inflated data), so Croston items never
    receive a false normality claim.
    """
    if not daily_units or demand_level <= 0:
        return 0.0
    width = max(1, int(math.ceil(lead_time_days)))
    totals = [sum(daily_units[index:index + width]) for index in range(max(1, len(daily_units) - width + 1))]
    ordered = sorted(totals)
    index = min(len(ordered) - 1, max(0, math.ceil(service_level * len(ordered)) - 1))
    return max(0.0, float(ordered[index]) - demand_level * lead_time_days)


def lead_time_variance_from_receipts(distribution: Any | None, fallback_lead_time_days: float, fallback_on_time_rate: float) -> tuple[float, float, str]:
    """Convert measured late-day distribution to mean/std lead time estimates.

    Receipt data contains late-day quantiles rather than every lead time; p90-p50
    is an honest bounded dispersion proxy. Sparse data retains the configured
    vendor lead time and a clearly-labelled on-time-rate fallback.
    """
    if distribution is None:
        return fallback_lead_time_days, max(0.0, 1 - fallback_on_time_rate), "assumed"
    mean_lead = fallback_lead_time_days + (1 - distribution.on_time_rate_measured) * distribution.mean_late_days
    std = max(0.0, (distribution.p90_late_days - distribution.p50_late_days) / 1.28155)
    return mean_lead, std, "measured"
