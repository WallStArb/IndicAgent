"""Tests for src/intelligence/statistics/panel_null.py (Phase 179 pre-registration section 7)."""

from __future__ import annotations

import numpy as np
import pytest

from src.intelligence.statistics.panel_null import (
    admissible_shifts,
    shift_panel,
    westfall_young_adjusted_p,
)


class TestAdmissibleShifts:
    def test_enumerates_closed_interval(self) -> None:
        np.testing.assert_array_equal(admissible_shifts(10, 3), [3, 4, 5, 6, 7])

    def test_count_matches_prereg_scale(self) -> None:
        # ~3,250 sessions with a 63 floor gives n - 2*63 + 1 shifts.
        assert len(admissible_shifts(3250, 63)) == 3250 - 2 * 63 + 1

    def test_symmetric_single_shift(self) -> None:
        np.testing.assert_array_equal(admissible_shifts(6, 3), [3])

    def test_panel_too_short_raises(self) -> None:
        with pytest.raises(ValueError, match="no admissible shift"):
            admissible_shifts(5, 3)

    def test_memory_drops_wrapped_copies_that_read_the_target(self) -> None:
        # out[t] = panel[(t - k) mod n]: for t < k the copy comes from t + (n - k) sessions
        # later, whose window reaches back `memory` sessions; n - k must exceed it.
        np.testing.assert_array_equal(
            admissible_shifts(20, 3, memory=5), [3, 4, 5, 6, 7, 8, 9, 10, 11, 12]
        )
        assert (20 - admissible_shifts(20, 3, memory=5) > 5).all()

    def test_memory_too_long_raises(self) -> None:
        with pytest.raises(ValueError, match="no admissible shift"):
            admissible_shifts(10, 3, memory=5)

    def test_min_shift_below_one_raises(self) -> None:
        # k = 0 is the observed alignment, never a null draw.
        with pytest.raises(ValueError, match="min_shift"):
            admissible_shifts(10, 0)


class TestShiftPanel:
    def test_all_symbols_move_together(self) -> None:
        # out[t] = panel[(t - k) mod n] row for row, so each date's cross-section (NaN cells
        # included) moves intact. Panel synchrony is the property todo 372 found broken.
        rng = np.random.default_rng(0)
        panel = rng.normal(size=(50, 7))
        panel[rng.random(panel.shape) < 0.1] = np.nan
        shifted = shift_panel(panel, 17)
        for t in range(50):
            np.testing.assert_array_equal(shifted[t], panel[(t - 17) % 50])

    def test_does_not_mutate_input(self) -> None:
        panel = np.arange(6, dtype=float).reshape(3, 2)
        before = panel.copy()
        shift_panel(panel, 1)
        np.testing.assert_array_equal(panel, before)

    def test_rejects_non_2d(self) -> None:
        with pytest.raises(ValueError, match="2-D"):
            shift_panel(np.arange(5.0), 1)

    def test_rejects_out_of_range_shift(self) -> None:
        panel = np.zeros((5, 2))
        for k in (0, 5, -1):
            with pytest.raises(ValueError, match="shift"):
                shift_panel(panel, k)


class TestWestfallYoung:
    def test_single_arm_equals_plain_permutation_p(self) -> None:
        null = np.array([[0.1], [0.5], [0.9], [1.3], [-0.2]])
        # Two of five null draws are >= 0.9, so p = (1 + 2) / (1 + 5).
        np.testing.assert_allclose(westfall_young_adjusted_p(np.array([0.9]), null), [3 / 6])

    def test_hand_computed_two_arms(self) -> None:
        # Arm 0 null: mean 0, sd 1 (ddof=0). Arm 1 null: mean 10, sd 2.
        null = np.array([[-1.0, 8.0], [1.0, 12.0], [-1.0, 12.0], [1.0, 8.0]])
        observed = np.array([1.0, 13.0])
        # Z null rows: (-1,-1), (1,1), (-1,1), (1,-1) -> max per row: -1, 1, 1, 1.
        # Z_obs = (1, 1.5). Arm 0: #{M >= 1} = 3 -> 4/5. Arm 1: #{M >= 1.5} = 0 -> 1/5.
        np.testing.assert_allclose(westfall_young_adjusted_p(observed, null), [4 / 5, 1 / 5])

    def test_adjusted_p_never_below_unadjusted(self) -> None:
        rng = np.random.default_rng(1)
        null = rng.normal(size=(500, 3))
        observed = np.array([1.5, 2.0, 0.3])
        adj = westfall_young_adjusted_p(observed, null)
        for j in range(3):
            raw = westfall_young_adjusted_p(observed[[j]], null[:, [j]])[0]
            assert adj[j] >= raw

    def test_identical_arms_pay_no_multiplicity(self) -> None:
        # Perfectly correlated arms: max-stat adjustment equals the unadjusted p (Holm would triple it).
        rng = np.random.default_rng(2)
        col = rng.normal(size=400)
        null = np.column_stack([col, col, col])
        observed = np.array([2.0, 2.0, 2.0])
        raw = westfall_young_adjusted_p(observed[[0]], null[:, [0]])[0]
        np.testing.assert_allclose(westfall_young_adjusted_p(observed, null), [raw] * 3)

    def test_invariant_to_arm_scale(self) -> None:
        rng = np.random.default_rng(3)
        null = rng.normal(size=(300, 2))
        observed = np.array([1.0, 2.2])
        scale = np.array([1.0, 1000.0])
        shift = np.array([0.0, -50.0])
        np.testing.assert_allclose(
            westfall_young_adjusted_p(observed, null),
            westfall_young_adjusted_p(observed * scale + shift, null * scale + shift),
        )

    def test_extreme_observed_hits_resolution_floor(self) -> None:
        null = np.random.default_rng(4).normal(size=(99, 2))
        np.testing.assert_allclose(
            westfall_young_adjusted_p(np.array([50.0, 50.0]), null), [0.01, 0.01]
        )

    @pytest.mark.parametrize(
        ("observed", "null"),
        [
            ([0.5, 2.5], [[0.0, 1.0], [np.nan, 2.0], [1.0, 3.0]]),
            ([np.inf, 1.0], [[0.0, 1.0], [1.0, 2.0]]),
        ],
    )
    def test_non_finite_input_raises(self, observed: list, null: list) -> None:
        with pytest.raises(ValueError, match="non-finite"):
            westfall_young_adjusted_p(np.array(observed), np.array(null))

    @pytest.mark.parametrize("value", [1.0, 0.1])
    def test_degenerate_null_raises(self, value: float) -> None:
        # 0.1 repeated has a float-rounded sd of ~1e-17, not 0; it must still be caught.
        null = np.column_stack([np.full(7, value), np.arange(7.0)])
        with pytest.raises(ValueError, match="zero variance"):
            westfall_young_adjusted_p(np.array([value, 1.0]), null)

    def test_shape_mismatch_raises(self) -> None:
        with pytest.raises(ValueError, match="shape"):
            westfall_young_adjusted_p(np.array([1.0, 2.0]), np.zeros((5, 3)))
