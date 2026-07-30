"""Unit tests for ops_broadcast_feature_audit.py's pure classification logic
(2026-07-29, follow-up to todo 203).

vix_z/yield_slope_z were confirmed bit-identical across every symbol at a given
bar_ts -- correctly, since they're legitimately single macro series broadcast to
every row. Any significance test that pools symbols together has the same
pseudo-replication exposure as the (buggy) canaries for any feature with this
structure. This script classifies which active features have it, empirically.
No DB, no asyncio -- pure function tests only.
"""

from __future__ import annotations

import numpy as np

from scripts.ops.alpha.ops_broadcast_feature_audit import _classify_broadcast


class TestClassifyBroadcast:
    def test_identical_values_across_symbols_classified_broadcast(self) -> None:
        values_by_bar_ts = {
            "t1": np.array([1.5, 1.5, 1.5]),
            "t2": np.array([2.0, 2.0, 2.0]),
        }
        assert _classify_broadcast(values_by_bar_ts, epsilon=1e-9) is True

    def test_varying_values_classified_not_broadcast(self) -> None:
        values_by_bar_ts = {"t1": np.array([1.5, 1.6, 1.4])}
        assert _classify_broadcast(values_by_bar_ts, epsilon=1e-9) is False

    def test_single_bar_ts_with_variance_fails_even_if_others_pass(self) -> None:
        values_by_bar_ts = {
            "t1": np.array([1.5, 1.5, 1.5]),
            "t2": np.array([2.0, 2.1, 2.0]),
        }
        assert _classify_broadcast(values_by_bar_ts, epsilon=1e-9) is False

    def test_bar_ts_with_fewer_than_two_symbols_is_skipped(self) -> None:
        values_by_bar_ts = {"t1": np.array([1.5])}
        assert _classify_broadcast(values_by_bar_ts, epsilon=1e-9) is True

    def test_nan_values_excluded_before_comparison(self) -> None:
        values_by_bar_ts = {"t1": np.array([1.5, 1.5, np.nan])}
        assert _classify_broadcast(values_by_bar_ts, epsilon=1e-9) is True

    def test_epsilon_tolerance_allows_tiny_float_noise(self) -> None:
        values_by_bar_ts = {"t1": np.array([1.5, 1.5 + 1e-12])}
        assert _classify_broadcast(values_by_bar_ts, epsilon=1e-9) is True

    def test_epsilon_tolerance_rejects_real_difference(self) -> None:
        values_by_bar_ts = {"t1": np.array([1.5, 1.5001])}
        assert _classify_broadcast(values_by_bar_ts, epsilon=1e-9) is False

    def test_empty_dict_classified_broadcast_vacuously(self) -> None:
        """No bar_ts groups to compare -- nothing contradicts 'broadcast', matching
        the loop's natural behavior (never entered, returns the initial True)."""
        assert _classify_broadcast({}, epsilon=1e-9) is True
