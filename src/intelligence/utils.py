"""Shared utilities for intelligence plugins."""

from __future__ import annotations

import math
from typing import Any

import numpy as np


def find_peaks(data: np.ndarray, n: int) -> list[int]:
    """Find local maxima using N-neighbor comparison.

    Uses >= so that a bar tying its neighbor still qualifies (common in
    futures tick data where highs cluster at round numbers).  Requires at
    least one strict inequality to avoid firing on every bar in a flat line.
    """
    peaks: list[int] = []
    for i in range(n, len(data) - n):
        if all(data[i] >= data[i - j] for j in range(1, n + 1)) and all(
            data[i] >= data[i + j] for j in range(1, n + 1)
        ):
            if any(data[i] > data[i - j] for j in range(1, n + 1)) or any(
                data[i] > data[i + j] for j in range(1, n + 1)
            ):
                peaks.append(i)
    return peaks


def find_troughs(data: np.ndarray, n: int) -> list[int]:
    """Find local minima using N-neighbor comparison.

    Uses <= with at least one strict inequality to handle ties without
    producing false positives on flat data.
    """
    troughs: list[int] = []
    for i in range(n, len(data) - n):
        if all(data[i] <= data[i - j] for j in range(1, n + 1)) and all(
            data[i] <= data[i + j] for j in range(1, n + 1)
        ):
            if any(data[i] < data[i - j] for j in range(1, n + 1)) or any(
                data[i] < data[i + j] for j in range(1, n + 1)
            ):
                troughs.append(i)
    return troughs


def is_num(x: Any) -> bool:
    """Check if value is a valid finite numeric type (rejects NaN and Inf)."""
    return isinstance(x, int | float) and math.isfinite(x)
