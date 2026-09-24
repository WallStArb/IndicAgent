"""Shared date-indexed panel (scripts/analysis/_date_panel.py)."""

import numpy as np

from scripts.analysis._date_panel import Panel, spearman


def test_spearman_drops_non_finite_pairs():
    x = np.array([1.0, 2.0, np.nan, 3.0, 4.0, 5.0])
    y = np.array([2.0, 1.0, 9.0, 4.0, np.nan, 5.0])
    keep = np.isfinite(x) & np.isfinite(y)
    assert spearman(x, y) == spearman(x[keep], y[keep])


def test_spearman_needs_four_pairs():
    assert np.isnan(spearman(np.array([1.0, 2.0, 3.0, np.nan]), np.arange(4.0)))


def _panel(scores, min_rows):
    n = len(scores)
    return Panel(
        np.zeros(n, dtype=np.int64),
        np.repeat(np.arange(20240101, 20240101 + n // 2), 2)[:n],
        scores,
        np.linspace(-1, 1, n),
        min_rows=min_rows,
    )


def test_family_counts_finite_score_rows_only():
    scores = np.full(10, np.nan)
    scores[:6] = np.arange(6.0)
    assert _panel(scores, min_rows=6).family == [0]
    assert _panel(scores, min_rows=7).family == []
