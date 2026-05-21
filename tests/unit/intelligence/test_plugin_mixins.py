"""Tests for src/intelligence/plugins/mixins.py.

Covers:
- wilders_update(): normal cases, edge cases (period=1, zero values), NaN propagation,
  negative values, period validation, and numerical stability.
- update_ema(): normal cases, alpha formula correctness, NaN propagation, span
  validation, and numerical stability.
- get_main_df(): valid/insufficient data, missing key, None values, exact min_bars
  boundary, empty DataFrame, and None frames argument.
"""

from __future__ import annotations

import math

import pandas as pd
import pytest

from src.intelligence.plugins.mixins import get_main_df, update_ema, wilders_update

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_df(n: int) -> pd.DataFrame:
    """Return a minimal DataFrame with ``n`` rows."""
    return pd.DataFrame({"close": range(n), "open": range(n), "high": range(n), "low": range(n)})


# ---------------------------------------------------------------------------
# TestWildersUpdate
# ---------------------------------------------------------------------------


class TestWildersUpdate:
    def test_normal_case(self):
        """(prev * (period-1) + new_val) / period."""
        result = wilders_update(10.0, 20.0, 14)
        expected = (10.0 * 13 + 20.0) / 14
        assert abs(result - expected) < 1e-10

    def test_period_one(self):
        """period=1 collapses to new_val (weight of prev is 0)."""
        result = wilders_update(10.0, 20.0, 1)
        assert result == pytest.approx(20.0)

    def test_nan_prev_propagates(self):
        """NaN in prev -> NaN out."""
        result = wilders_update(float("nan"), 20.0, 14)
        assert math.isnan(result)

    def test_nan_new_val_propagates(self):
        """NaN in new_val -> NaN out."""
        result = wilders_update(10.0, float("nan"), 14)
        assert math.isnan(result)

    def test_nan_both_propagates(self):
        """NaN in both args -> NaN out."""
        result = wilders_update(float("nan"), float("nan"), 14)
        assert math.isnan(result)

    def test_zero_values(self):
        """Zero inputs produce zero output."""
        result = wilders_update(0.0, 0.0, 14)
        assert result == pytest.approx(0.0)

    def test_negative_values(self):
        """Negative values handled correctly."""
        result = wilders_update(-5.0, -3.0, 14)
        expected = (-5.0 * 13 + (-3.0)) / 14
        assert abs(result - expected) < 1e-10

    def test_period_validation_zero(self):
        """period=0 raises ValueError."""
        with pytest.raises(ValueError):
            wilders_update(1.0, 2.0, 0)

    def test_period_validation_negative(self):
        """period=-1 raises ValueError."""
        with pytest.raises(ValueError):
            wilders_update(1.0, 2.0, -1)

    def test_numerical_stability(self):
        """1000 iterations with constant input converges to that constant."""
        constant = 42.0
        period = 14
        val = 0.0  # start far from constant
        for _ in range(1000):
            val = wilders_update(val, constant, period)
        # After 1000 Wilder's steps with constant input, must converge
        assert abs(val - constant) < 1e-6

    @pytest.mark.parametrize(
        "prev, new_val, period",
        [
            (100.0, 105.0, 7),
            (0.5, 1.5, 5),
            (1000.0, 999.0, 20),
        ],
    )
    def test_formula_parametrized(self, prev, new_val, period):
        """Formula holds across varied inputs."""
        expected = (prev * (period - 1) + new_val) / period
        assert wilders_update(prev, new_val, period) == pytest.approx(expected)


# ---------------------------------------------------------------------------
# TestUpdateEMA
# ---------------------------------------------------------------------------


class TestUpdateEMA:
    def test_normal_case(self):
        """alpha * current + (1-alpha) * prev_ema, alpha=2/(span+1)."""
        alpha = 2.0 / 21
        expected = alpha * 20.0 + (1 - alpha) * 10.0
        result = update_ema(20.0, 10.0, 20)
        assert result == pytest.approx(expected)

    def test_alpha_formula(self):
        """alpha is exactly 2 / (span + 1)."""
        span = 20
        alpha = 2.0 / (span + 1)
        # When prev_ema == current, result == current regardless of alpha
        assert update_ema(5.0, 5.0, span) == pytest.approx(5.0)
        # Verify alpha indirectly: result = alpha * c + (1-alpha) * p
        result = update_ema(20.0, 10.0, span)
        assert abs(result - (alpha * 20.0 + (1 - alpha) * 10.0)) < 1e-12

    def test_span_one_returns_current(self):
        """span=1 -> alpha=1.0 -> output equals current (no smoothing)."""
        result = update_ema(20.0, 10.0, 1)
        assert result == pytest.approx(20.0)

    def test_nan_current_propagates(self):
        """NaN current -> NaN out."""
        result = update_ema(float("nan"), 10.0, 20)
        assert math.isnan(result)

    def test_nan_prev_ema_propagates(self):
        """NaN prev_ema -> NaN out."""
        result = update_ema(20.0, float("nan"), 20)
        assert math.isnan(result)

    def test_span_validation_zero(self):
        """span=0 raises ValueError."""
        with pytest.raises(ValueError):
            update_ema(1.0, 2.0, 0)

    def test_span_validation_negative(self):
        """span=-5 raises ValueError."""
        with pytest.raises(ValueError):
            update_ema(1.0, 2.0, -5)

    def test_numerical_stability(self):
        """1000 iterations with constant input converges to that constant."""
        constant = 100.0
        span = 12
        val = 0.0
        for _ in range(1000):
            val = update_ema(constant, val, span)
        assert abs(val - constant) < 1e-4

    def test_zero_values(self):
        """Zero current and zero prev_ema produce zero."""
        result = update_ema(0.0, 0.0, 14)
        assert result == pytest.approx(0.0)

    @pytest.mark.parametrize(
        "current, prev_ema, span",
        [
            (50.0, 48.0, 12),
            (1.0, 2.0, 26),
            (0.001, 0.002, 9),
        ],
    )
    def test_formula_parametrized(self, current, prev_ema, span):
        """Formula holds across varied inputs."""
        alpha = 2.0 / (span + 1)
        expected = alpha * current + (1 - alpha) * prev_ema
        assert update_ema(current, prev_ema, span) == pytest.approx(expected)


# ---------------------------------------------------------------------------
# TestGetMainDf
# ---------------------------------------------------------------------------


class TestGetMainDf:
    def test_valid_dataframe_returns_df(self):
        """Returns df when len(df) >= min_bars."""
        df = _make_df(10)
        result = get_main_df({"main": df}, 5)
        assert result is df

    def test_insufficient_bars_returns_none(self):
        """Returns None when len(df) < min_bars."""
        df = _make_df(4)
        result = get_main_df({"main": df}, 5)
        assert result is None

    def test_missing_main_key_returns_none(self):
        """Returns None when 'main' key is absent from frames."""
        result = get_main_df({"other": _make_df(10)}, 5)
        assert result is None

    def test_none_main_value_returns_none(self):
        """Returns None when frames['main'] is None."""
        result = get_main_df({"main": None}, 5)
        assert result is None

    def test_exact_min_bars_returns_df(self):
        """Returns df when len(df) == min_bars exactly."""
        df = _make_df(5)
        result = get_main_df({"main": df}, 5)
        assert result is df

    def test_empty_dataframe_returns_none(self):
        """Returns None for an empty DataFrame (len 0 < any min_bars >= 1)."""
        df = pd.DataFrame()
        result = get_main_df({"main": df}, 1)
        assert result is None

    def test_none_frames_argument_returns_none(self):
        """Returns None when frames itself is None (not a dict)."""
        result = get_main_df(None, 5)
        assert result is None

    def test_non_dict_frames_returns_none(self):
        """Returns None when frames is not a dict (e.g. a list)."""
        result = get_main_df([1, 2, 3], 5)  # type: ignore[arg-type]
        assert result is None

    def test_empty_dict_returns_none(self):
        """Returns None for an empty dict (no 'main' key)."""
        result = get_main_df({}, 5)
        assert result is None

    def test_non_dataframe_main_returns_none(self):
        """Returns None when frames['main'] is not a DataFrame."""
        result = get_main_df({"main": [1, 2, 3, 4, 5]}, 3)
        assert result is None

    @pytest.mark.parametrize(
        "n_bars,min_bars,should_return",
        [
            (10, 10, True),  # exact boundary
            (9, 10, False),  # one below
            (11, 10, True),  # one above
            (0, 1, False),  # empty
            (1, 1, True),  # single bar
        ],
    )
    def test_boundary_parametrized(self, n_bars, min_bars, should_return):
        """Boundary conditions for len(df) vs min_bars."""
        df = _make_df(n_bars)
        result = get_main_df({"main": df}, min_bars)
        if should_return:
            assert result is df
        else:
            assert result is None


# ---------------------------------------------------------------------------
# TestSupportsIncrementalFlagCorrectness
# ---------------------------------------------------------------------------


def _get_all_registered_plugins() -> list[object]:
    """Return all plugin instances from every tier list in register_plugins."""
    import inspect

    from src.intelligence import register_plugins as rp

    all_names: set[str] = set()
    for tier_attr in (
        "TIER_I1",
        "TIER_I2",
        "TIER_I3",
        "TIER_I4",
        "TIER_I5",
        "TIER_SMC",
        "TIER_I6",
        "TIER_I7",
    ):
        tier_list = getattr(rp, tier_attr, [])
        all_names.update(tier_list)

    # Build plugin name -> plugin instance map from module-level plugin imports
    plugins_by_name: dict[str, object] = {}
    for attr_name in dir(rp):
        obj = getattr(rp, attr_name)
        # Check if it's a plugin instance (has .name, .supports_incremental, .compute_next)
        if (
            not inspect.isclass(obj)
            and hasattr(obj, "name")
            and hasattr(obj, "supports_incremental")
            and hasattr(obj, "compute_next")
            and isinstance(getattr(obj, "name", None), str)
        ):
            plugins_by_name[obj.name] = obj

    # Return only plugins that appear in tier lists
    return [plugins_by_name[name] for name in all_names if name in plugins_by_name]


class TestSupportsIncrementalFlagCorrectness:
    """Conformance tests ensuring supports_incremental flags match actual behavior."""

    def test_delegation_plugins_have_false_flag(self):
        """Regression test: CVD, OFI, MAComposite are delegation plugins and must have False flag."""
        from src.intelligence.composites.ma_composites import MACompositePlugin
        from src.intelligence.features.i1_indicators.cvd import CVDPlugin
        from src.intelligence.features.i1_indicators.ofi import OFIPlugin

        assert (
            CVDPlugin.supports_incremental is False
        ), "CVD uses delegation pattern (compute_next calls compute_full) — must be False"
        assert (
            OFIPlugin.supports_incremental is False
        ), "OFI uses delegation pattern (compute_next calls compute_full) — must be False"
        assert (
            MACompositePlugin.supports_incremental is False
        ), "MAComposite uses delegation pattern (compute_next calls compute_full) — must be False"

    def test_incremental_plugins_use_state_parameter(self):
        """Plugins with supports_incremental=True should not read self._state in compute_next body.

        A plugin that reads self._state in compute_next instead of the `state` parameter
        violates the protocol (PERF-03) and was the root cause of the bugs fixed in plan 03.
        We check the first 10 lines of compute_next body to catch obvious violations.

        Exemptions: HMM regime plugins use a legitimate self._model reference (not self._state),
        and BOCPD correctly returns _state in compute_next from the state parameter.
        """
        import inspect

        from src.intelligence.plugins.mixins import IncrementalMixin

        plugins = _get_all_registered_plugins()
        violations: list[str] = []

        for plugin in plugins:
            if not getattr(plugin, "supports_incremental", False):
                continue

            # Plugins using IncrementalMixin are governed by the mixin -- skip
            if isinstance(plugin, IncrementalMixin):
                continue

            plugin_cls = type(plugin)
            try:
                source = inspect.getsource(plugin_cls.compute_next)
            except (OSError, TypeError):
                continue

            # Remove the method signature line, focus on body
            lines = source.splitlines()
            body_lines = [line for line in lines if "def compute_next" not in line]
            first_body = "\n".join(body_lines[:10])

            # Flag plugins that read self._state in early compute_next body
            # (self._state in return statements or late lines is less critical)
            if (
                "self._state" in first_body
                and "state" not in inspect.signature(plugin_cls.compute_next).parameters
            ):
                violations.append(
                    f"{plugin_cls.__name__}: reads self._state in compute_next without accepting state= parameter"
                )

        assert not violations, "Plugins violating state parameter protocol:\n" + "\n".join(
            violations
        )

    def test_incremental_plugins_return_state(self):
        """Plugins with supports_incremental=True should return _state in compute_next.

        Without returning _state, the executor cannot thread state across bars and
        incremental mode silently does nothing useful.

        Plugins using IncrementalMixin are exempt -- the mixin guarantees _state return.
        """
        import inspect

        from src.intelligence.plugins.mixins import IncrementalMixin

        plugins = _get_all_registered_plugins()
        violations: list[str] = []

        for plugin in plugins:
            if not getattr(plugin, "supports_incremental", False):
                continue

            # IncrementalMixin guarantees _state return -- skip
            if isinstance(plugin, IncrementalMixin):
                continue

            plugin_cls = type(plugin)
            try:
                source = inspect.getsource(plugin_cls.compute_next)
            except (OSError, TypeError):
                continue

            # If compute_next body just delegates to compute_full, check compute_full instead
            # (delegation plugins should have supports_incremental=False, but as a safety net)
            if "compute_full" in source and "_state" not in source:
                violations.append(
                    f"{plugin_cls.__name__}: compute_next delegates to compute_full "
                    f"but returns no _state -- consider supports_incremental=False"
                )
                continue

            # Check that _state appears somewhere in the compute_next source
            if "_state" not in source:
                violations.append(
                    f"{plugin_cls.__name__}: compute_next has no _state reference "
                    f"(state will not be threaded across bars)"
                )

        assert (
            not violations
        ), "Plugins with supports_incremental=True missing _state in compute_next:\n" + "\n".join(
            violations
        )
