from dataclasses import dataclass
from datetime import date
from typing import Protocol

from submission.config import config
from .windows import RegimeShift


class _PolicyLike(Protocol):
    active_class: str
    candidate_class: str | None
    candidate_since: date | None
    consecutive_confirmations: int


@dataclass(frozen=True)
class HysteresisResult:
    active_class: str
    candidate_class: str | None
    candidate_since: date | None
    consecutive_confirmations: int
    change_reason: str


_RANK = {"A": 3, "B": 2, "C": 1}


def apply_hysteresis(previous: _PolicyLike | None, computed_class: str, as_of: date, regime_shift: RegimeShift, promotion_confirmations: int = config.hysteresis_promotion_confirmations, downgrade_confirmations: int = config.hysteresis_downgrade_confirmations) -> HysteresisResult:
    if computed_class not in _RANK:
        raise ValueError("hysteresis only supports ABC classes")
    if previous is None or previous.active_class not in _RANK:
        return HysteresisResult(computed_class, None, None, 0, "initial classification")
    if computed_class == previous.active_class:
        return HysteresisResult(computed_class, None, None, 0, "classification confirmed")
    if regime_shift.is_significant and regime_shift.is_sustained:
        return HysteresisResult(computed_class, None, None, 0, f"regime shift bypass: {regime_shift.magnitude:.2g}x change, sustained across 2 windows")
    count = previous.consecutive_confirmations + 1 if previous.candidate_class == computed_class else 1
    threshold = promotion_confirmations if _RANK[computed_class] > _RANK[previous.active_class] else downgrade_confirmations
    if count >= threshold:
        return HysteresisResult(computed_class, None, None, 0, f"{count} consecutive confirmations")
    return HysteresisResult(previous.active_class, computed_class, previous.candidate_since or as_of, count, f"awaiting {threshold} confirmations")
