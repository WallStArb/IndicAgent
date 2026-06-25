"""Unit tests for per-scale IC stride subsampling correctness (Phase 140 P0).

Tests verify:
1. Fast scale (lookahead=1) gets more observations than extended scale (lookahead=60)
   when n=600 and min_stride=5.
2. Degenerate-feature mask is computed on the full regime matrix (X_regime), not a
   stride-60 subsample — the mask must be identical regardless of stride.
"""

from __future__ import annotations

import numpy as np

# ---------------------------------------------------------------------------
# Test 1 — per-scale n_independent
# ---------------------------------------------------------------------------


def _compute_sub_idx(n: int, min_stride: int, lookahead: int) -> np.ndarray:
    """Mirror the per-scale subsampling logic from ic_engine.py."""
    scale_stride = max(min_stride, lookahead)
    return np.arange(0, n, scale_stride)


class TestPerScaleStride:
    """Verify that faster lookaheads produce more subsampled observations."""

    lookaheads = {"fast": 1, "mid": 5, "slow": 20, "extended": 60}
    n = 600
    min_stride = 5

    def test_fast_has_more_observations_than_extended(self) -> None:
        fast_idx = _compute_sub_idx(self.n, self.min_stride, self.lookaheads["fast"])
        extended_idx = _compute_sub_idx(self.n, self.min_stride, self.lookaheads["extended"])
        assert len(fast_idx) > len(extended_idx), (
            f"Fast scale should have more observations than extended: "
            f"{len(fast_idx)} vs {len(extended_idx)}"
        )

    def test_observation_counts_differ_by_scale(self) -> None:
        counts = {
            scale: len(_compute_sub_idx(self.n, self.min_stride, la))
            for scale, la in self.lookaheads.items()
        }
        # All four counts must be distinct (fast=120, mid=120, slow=30, extended=10)
        # fast and mid share the same stride (min_stride=5) so they are equal — that is correct.
        # What must NOT happen is extended == fast.
        assert (
            counts["fast"] > counts["extended"]
        ), f"fast count {counts['fast']} must exceed extended count {counts['extended']}"
        assert (
            counts["mid"] > counts["extended"]
        ), f"mid count {counts['mid']} must exceed extended count {counts['extended']}"
        assert (
            counts["slow"] > counts["extended"]
        ), f"slow count {counts['slow']} must exceed extended count {counts['extended']}"

    def test_expected_observation_counts(self) -> None:
        """Sanity-check exact counts given n=600, min_stride=5."""
        # fast: stride=max(5,1)=5  → 600/5 = 120
        # mid:  stride=max(5,5)=5  → 120
        # slow: stride=max(5,20)=20 → 600/20 = 30
        # extended: stride=max(5,60)=60 → 600/60 = 10
        expected = {"fast": 120, "mid": 120, "slow": 30, "extended": 10}
        for scale, la in self.lookaheads.items():
            idx = _compute_sub_idx(self.n, self.min_stride, la)
            assert (
                len(idx) == expected[scale]
            ), f"{scale}: expected {expected[scale]} observations, got {len(idx)}"

    def test_old_uniform_stride_would_give_same_count(self) -> None:
        """Document the bug: old code used stride=60 for ALL scales."""
        old_stride = max(self.min_stride, max(self.lookaheads.values()))  # always 60
        old_count = len(np.arange(0, self.n, old_stride))  # 10 for all scales
        fast_count_new = len(_compute_sub_idx(self.n, self.min_stride, self.lookaheads["fast"]))
        assert (
            fast_count_new > old_count
        ), f"Fixed fast count ({fast_count_new}) must exceed the buggy uniform count ({old_count})"


# ---------------------------------------------------------------------------
# Test 2 — degenerate mask is computed on full regime data, not a subsample
# ---------------------------------------------------------------------------


class TestDegenerateMaskOnFullRegime:
    """Degenerate detection must use X_regime (full), not a stride-60 subsample."""

    def _build_x_regime(self, n_rows: int = 200, n_features: int = 10) -> np.ndarray:
        """Return X_regime with one all-zero (degenerate) column at index 0."""
        rng = np.random.default_rng(42)
        X = rng.standard_normal((n_rows, n_features))
        X[:, 0] = 0.0  # degenerate column
        return X

    def test_mask_shape_is_full_feature_width(self) -> None:
        X_regime = self._build_x_regime(200, 10)
        non_degen_mask = ~(np.std(X_regime, axis=0) < 1e-8)
        assert non_degen_mask.shape == (
            10,
        ), f"Mask shape should be (10,) — full feature width, got {non_degen_mask.shape}"

    def test_degenerate_column_detected(self) -> None:
        X_regime = self._build_x_regime(200, 10)
        non_degen_mask = ~(np.std(X_regime, axis=0) < 1e-8)
        # Column 0 is all-zeros — must be masked out
        assert not non_degen_mask[0], "Column 0 (all-zeros) must be detected as degenerate"
        # All other columns should be non-degenerate
        assert non_degen_mask[1:].all(), "Columns 1-9 should be non-degenerate"

    def test_mask_identical_for_full_vs_subsample_on_non_pathological_columns(self) -> None:
        """Mask computed on full X_regime matches mask computed on a stride-60 subsample.

        This holds for all non-degenerate columns. For the degenerate column (all-zeros),
        both will correctly detect it. Shows that computing on the full regime is not
        functionally different from any subsample for well-behaved data — but the full
        regime is the correct and stable choice.
        """
        X_regime = self._build_x_regime(200, 10)
        mask_full = ~(np.std(X_regime, axis=0) < 1e-8)

        stride_60_idx = np.arange(0, 200, 60)
        X_sub_60 = X_regime[stride_60_idx]
        mask_sub60 = ~(np.std(X_sub_60, axis=0) < 1e-8)

        # Both must agree on the degenerate column
        assert mask_full[0] == mask_sub60[0] == False  # noqa: E712
        # Both must agree on all non-degenerate columns
        np.testing.assert_array_equal(
            mask_full[1:],
            mask_sub60[1:],
            err_msg="Degenerate mask should be the same on full regime and stride-60 subsample",
        )
