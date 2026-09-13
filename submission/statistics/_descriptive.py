"""Small descriptive-statistics helpers safe to import from Streamlit.

The package containing this file is named ``submission.statistics``.  When
Streamlit launches ``submission/ui.py``, it places ``submission`` ahead of
the standard library on ``sys.path``.  An import such as ``from statistics
import mean`` would then resolve to this package rather than Python's
standard-library ``statistics`` module.  Keep the two tiny operations used by
the application here so that UI imports are unambiguous.
"""

from __future__ import annotations

from math import sqrt
from typing import Sequence


def mean(values: Sequence[int | float]) -> float:
    """Return the arithmetic mean of one or more numeric values."""
    if not values:
        raise ValueError("mean requires at least one data point")
    return sum(values) / len(values)


def pstdev(values: Sequence[int | float]) -> float:
    """Return population standard deviation (matching statistics.pstdev)."""
    if not values:
        raise ValueError("pstdev requires at least one data point")
    average = mean(values)
    return sqrt(sum((value - average) ** 2 for value in values) / len(values))
