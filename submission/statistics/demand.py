from dataclasses import dataclass
from math import sqrt

from submission.config import config
from ._descriptive import mean, pstdev


@dataclass(frozen=True)
class DemandStats:
    mean_daily_demand: float
    std_daily_demand: float
    cv: float | None
    adi: float | None
    cv_squared_nonzero: float | None
    zero_demand_days: int
    nonzero_observations: int
    quadrant: str


def classify_quadrant(adi: float | None, cv_squared: float | None, adi_cutoff: float, cv_squared_cutoff: float) -> str:
    # All-zero demand has no interval/size variance; it is explicitly treated
    # as intermittent rather than inventing a smooth demand signal.
    if adi is None or cv_squared is None:
        return "INTERMITTENT"
    if adi < adi_cutoff:
        return "SMOOTH" if cv_squared < cv_squared_cutoff else "ERRATIC"
    return "INTERMITTENT" if cv_squared < cv_squared_cutoff else "LUMPY"


def compute_demand_stats(daily_units: list[int], adi_cutoff: float = config.quadrant_adi_cutoff, cv_squared_cutoff: float = config.quadrant_cv_squared_cutoff) -> DemandStats:
    if not daily_units:
        return DemandStats(0, 0, None, None, None, 0, 0, "INTERMITTENT")
    if any(unit < 0 for unit in daily_units):
        raise ValueError("demand observations cannot be negative")
    average = mean(daily_units)
    deviation = pstdev(daily_units) if len(daily_units) > 1 else 0.0
    nonzero = [unit for unit in daily_units if unit > 0]
    cv = deviation / average if average else None
    adi = len(daily_units) / len(nonzero) if nonzero else None
    nz_mean = mean(nonzero) if nonzero else 0
    nz_std = pstdev(nonzero) if len(nonzero) > 1 else 0.0
    cv_squared = (nz_std / nz_mean) ** 2 if nz_mean else None
    return DemandStats(average, deviation, cv, adi, cv_squared, len(daily_units)-len(nonzero), len(nonzero), classify_quadrant(adi, cv_squared, adi_cutoff, cv_squared_cutoff))


def croston_level(daily_units: list[int], alpha: float = .1) -> tuple[float, float]:
    """Return Croston demand-size and interval estimates for nonzero events."""
    if not 0 < alpha <= 1:
        raise ValueError("alpha must be in (0, 1]")
    events = [(index + 1, value) for index, value in enumerate(daily_units) if value > 0]
    if not events:
        return (0.0, 0.0)
    last_day, size = events[0]
    interval = float(last_day)
    for day, demand in events[1:]:
        gap = day - last_day
        size += alpha * (demand - size)
        interval += alpha * (gap - interval)
        last_day = day
    return (size, interval)
