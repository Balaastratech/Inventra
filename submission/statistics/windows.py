from dataclasses import dataclass
from datetime import date, timedelta

from .demand import DemandStats


def rolling_12_months(as_of: date) -> tuple[date, date]:
    end = as_of.replace(day=1) - timedelta(days=1)
    # Twelve complete months ending with `end`: for an as-of date in
    # September 2026 that is September 2025 through August 2026.
    # The first included month has the same month number as `as_of`, one year
    # earlier (September 2025 through August 2026 for September 2026).
    start = date(as_of.year - 1, as_of.month, 1)
    return start, end


def recent_level_window(as_of: date, days: int = 30) -> tuple[date, date]:
    if days <= 0:
        raise ValueError("days must be positive")
    end = as_of - timedelta(days=1)
    return end - timedelta(days=days - 1), end


@dataclass(frozen=True)
class RegimeShift:
    magnitude: float
    is_significant: bool
    is_sustained: bool
    direction: str


def detect_regime_shift(recent_stats: DemandStats, baseline_stats: DemandStats, recent_subwindow_stats: list[DemandStats]) -> RegimeShift:
    baseline, recent = baseline_stats.mean_daily_demand, recent_stats.mean_daily_demand
    if baseline <= 0:
        direction = "increase" if recent > 0 else "none"
        return RegimeShift(float("inf") if recent else 1.0, recent > 0, recent > 0 and all(s.mean_daily_demand > 0 for s in recent_subwindow_stats[-2:]), direction)
    ratio = recent / baseline
    direction = "increase" if ratio >= 1.5 else "decrease" if ratio <= .67 else "none"
    sustained = len(recent_subwindow_stats) >= 2 and ((direction == "increase" and all(s.mean_daily_demand >= baseline * 1.5 for s in recent_subwindow_stats[-2:])) or (direction == "decrease" and all(s.mean_daily_demand <= baseline * .67 for s in recent_subwindow_stats[-2:])))
    return RegimeShift(ratio, direction != "none", sustained, direction)
