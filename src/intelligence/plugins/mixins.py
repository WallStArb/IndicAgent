"""Shared utility functions for I1-I7 plugins.

Pure, module-level functions with no side effects. Any plugin can import and
use these directly without inheritance or registration.

NaN propagation contract
------------------------
Both ``wilders_update`` and ``update_ema`` propagate NaN: any NaN input
produces NaN output with no silent fallback. This matches the inline behavior
found in ATR, RSI, MFI, and MACD before extraction.

get_main_df contract
--------------------
Returns ``None`` (never raises) when data is insufficient. Callers MUST check
the return value and handle ``None`` appropriately -- typically ``return {}``
for plugins.
"""

from __future__ import annotations

import math
from typing import Any

import pandas as pd

__all__ = ["wilders_update", "update_ema", "get_main_df", "incremental_compute", "IncrementalMixin"]


def wilders_update(prev: float, new_val: float, period: int) -> float:
    """Apply one step of Wilder's smoothing.

    Formula: ``(prev * (period - 1) + new_val) / period``

    NaN rule: NaN in -> NaN out. If either ``prev`` or ``new_val`` is NaN,
    the function returns ``float("nan")`` immediately with no computation.
    This matches the inline guard found in ATR's Wilder's smoothing loop
    (``pd.notna`` check before using the result).

    Usage example (ATR incremental update)::

        new_atr = wilders_update(s["prev_atr"], tr, period)

    Args:
        prev:    Previous smoothed value (e.g. previous ATR or avg_gain).
        new_val: Current raw value to smooth in (e.g. current True Range).
        period:  Wilder smoothing period. Must be >= 1.

    Returns:
        Updated smoothed value, or ``float("nan")`` if either input is NaN.

    Raises:
        ValueError: If ``period < 1``.
    """
    if period < 1:
        raise ValueError(f"period must be >= 1, got {period}")
    if math.isnan(prev):
        return float("nan")
    if math.isnan(new_val):
        return float("nan")
    return (prev * (period - 1) + new_val) / period


def update_ema(current: float, prev_ema: float, span: int) -> float:
    """Apply one step of exponential moving average (EMA) smoothing.

    Formula: ``alpha * current + (1 - alpha) * prev_ema``
    where ``alpha = 2 / (span + 1)``.

    NaN rule: NaN in either arg -> NaN out. If ``current`` or ``prev_ema``
    is NaN, the function returns ``float("nan")`` immediately. This matches
    the inline EMA update chains in MACD (fast, slow, and signal EMAs are
    always seeded from valid full-computation values, so a NaN here indicates
    a real error -- no silent fallback is appropriate).

    Usage example (MACD fast EMA update)::

        s["ema_fast"] = update_ema(new_close, s["ema_fast"], fast)

    Args:
        current:  Current bar value (e.g. close price).
        prev_ema: Previous EMA value. Must be a valid float (not NaN) for
                  correct operation; NaN propagates as an error indicator.
        span:     EMA span (number of periods). Must be >= 1.
                  ``alpha = 2 / (span + 1)``; span=1 gives alpha=1.0 (no
                  smoothing -- output equals ``current``).

    Returns:
        Updated EMA value, or ``float("nan")`` if either input is NaN.

    Raises:
        ValueError: If ``span < 1``.
    """
    if span < 1:
        raise ValueError(f"span must be >= 1, got {span}")
    if math.isnan(current):
        return float("nan")
    if math.isnan(prev_ema):
        return float("nan")
    alpha = 2.0 / (span + 1)
    return alpha * current + (1.0 - alpha) * prev_ema


def get_main_df(frames: dict[str, Any] | None, min_bars: int) -> pd.DataFrame | None:
    """Extract the primary OHLCV DataFrame from a plugin ``frames`` dict.

    Returns ``None`` when data is insufficient. Callers MUST check for
    ``None`` and handle appropriately. The typical plugin pattern is::

        df = get_main_df(frames, self.min_lookback)
        if df is None:
            return {}

    Returns ``None`` when:
    - ``frames`` is ``None`` or not a dict
    - ``frames["main"]`` is missing or not a DataFrame
    - ``len(frames["main"]) < min_bars``

    This function never raises. It is a pure guard -- no data is modified.

    Args:
        frames:   Plugin frames dict (typically passed directly from
                  ``compute_full``/``compute_next``). May be ``None``.
        min_bars: Minimum number of rows required in ``frames["main"]``.
                  Use the plugin's ``min_lookback`` value here.

    Returns:
        The ``frames["main"]`` DataFrame if it satisfies the length guard.
        Returns None when ``frames`` is missing, not a dict, ``frames["main"]``
        is absent or not a DataFrame, or ``len(frames["main"]) < min_bars``.
    """
    if not isinstance(frames, dict):
        return None
    df = frames.get("main")
    if df is None or not isinstance(df, pd.DataFrame):
        return None
    if len(df) < min_bars:
        return None
    return df


def incremental_compute(plugin: Any, frames: dict, state: dict) -> tuple[dict, dict]:
    """Canonical per-bar plugin dispatch for batch/replay paths.

    Mirrors ``executor._timed_plugin_call`` (executor.py:152-168) without the
    timing/OTel layer. Seeds via ``compute_full`` on the first bar (when state
    is empty) and switches to ``compute_next`` thereafter for plugins that
    declare ``supports_incremental``.

    The PERF-03 ``_state`` contract is enforced (loud crash over silent state
    loss): an incremental plugin that returns a non-empty result without
    ``_state`` raises ``ValueError``.

    Args:
        plugin:  Plugin instance (I1-I7). Resolved by the caller.
        frames:  Plugin frames dict (contains 'main' DataFrame + tier features).
        state:   Per-plugin state dict for this (plugin, symbol, tf). Empty on
                 the first bar; populated thereafter by the caller's write-back.

    Returns:
        (signal_dict, state_dict) — signal_dict never contains ``_state``;
        state_dict is the updated per-plugin state to persist for the next bar.
        signal_dict is ``{}`` when the plugin has insufficient data.
    """
    supports_inc = getattr(plugin, "supports_incremental", False)
    if supports_inc and state:
        result = plugin.compute_next(frames, state=state)
    else:
        result = plugin.compute_full(frames)
    result = result or {}
    if supports_inc and result:
        if "_state" not in result:
            raise ValueError(
                f"{getattr(plugin, 'name', type(plugin).__name__)}: incremental "
                f"plugins MUST return _state in result dict."
            )
    new_state = result.pop("_state", state)
    return result, new_state


class IncrementalMixin:
    """Owns fallback-to-full and _state return contract for incremental plugins.

    PERF-03: All subclasses are confirmed PERF-03 compliant -- they use the
    state= parameter from the executor and write _state back in compute_next().
    The mixin guarantees this via the compute_next() implementation.

    State ownership model (MUTABLE IN-PLACE CONTRACT):
    - State is a plain dict, passed by reference to _compute_next_core.
    - Plugins MUTATE state in place: state["key"] = new_value.
    - The mixin attaches the SAME state dict back to output: result["_state"] = state.
    - _compute_next_core MUST NOT return a new state dict -- it mutates the one it receives.
    - This matches the existing ATR pattern: s["prev_atr"] = new_atr; s["prev_close"] = close.
    - Deques, lists, and nested dicts in state are all valid -- mutation is by reference.

    Executor window contract:
    - The executor (executor.py line 322-328) passes the same `frames` dict to both
      compute_full and compute_next via functools.partial. There is no per-call frame slicing.
    - Therefore compute_next's fallback to compute_full(frames) is semantically correct:
      it receives the full historical frames, not incremental single-bar windows.

    Plugins implementing this mixin must provide:
    - _compute_full_core(frames) -> dict: Pure computation, returns outputs only (no _state).
      Returns {} when insufficient data.
    - _compute_next_core(frames, state) -> dict: Pure incremental computation.
      State is guaranteed non-None and non-empty (mixin guarantees this).
      Mutate state in place -- do NOT create a new state dict.
      Returns {} when computation cannot proceed.
    - _seed_state(frames) -> dict: Extract state from full computation for incremental seeding.
      Returns the initial state dict (may be empty {} if no state needed).

    The mixin provides:
    - compute_full(frames, *, state=None): Calls _compute_full_core, attaches _state via _seed_state.
    - compute_next(frames, *, state=None): Falls back to compute_full if state is None,
      else calls _compute_next_core and attaches _state (the same mutated dict).
    """

    # PERF-03 migration flag: all IncrementalMixin subclasses are compliant because
    # the mixin itself enforces the state read/writeback contract via compute_next().
    _state_migration_complete: bool = True

    # fast_path flag: IncrementalMixin subclasses use compute_next() so fast_path
    # does not apply (they have persistent state). Default False; non-incremental
    # plugins may set this to True after P99 latency verification (Plan 05).
    fast_path: bool = False

    def compute_full(self, frames: dict, *, state: dict | None = None) -> dict:
        """Run full computation and attach seeded state.

        Calls _compute_full_core for pure domain computation, then calls
        _seed_state to extract incremental state from the result. Always
        attaches _state to the output dict.

        Args:
            frames: Plugin frames dict (contains 'main' DataFrame and optional
                    context frames).
            state:  Optional external dict to populate with seeded state.
                    When provided, mutated in place for backward compatibility.

        Returns:
            Output dict from _compute_full_core with _state attached. Returns {}
            when _compute_full_core returns {} (insufficient data).
        """
        result = self._compute_full_core(frames)
        if not result:
            return {}
        seeded_state = self._seed_state(frames)
        result["_state"] = seeded_state
        if state is not None:
            state.update(seeded_state)
        return result

    def compute_next(self, frames: dict, *, state: dict | None = None) -> dict:
        """Run incremental computation using cached state.

        Falls back to compute_full when state is None. Uses `state is None`
        (not truthiness) -- an empty dict {} is a valid state and must NOT
        trigger fallback. Calls _compute_next_core with the guaranteed non-None
        state, then attaches the same (mutated) state dict back to the output.

        Args:
            frames: Plugin frames dict. Executor passes the same full historical
                    frames to both compute_full and compute_next (no slicing).
            state:  Cached state dict from previous call. Must be None (triggers
                    fallback to compute_full) or a dict (passed to _compute_next_core).

        Returns:
            Output dict from _compute_next_core with _state attached. Returns {}
            when _compute_next_core returns {} (insufficient data or missing keys).
        """
        if state is None:
            return self.compute_full(frames)
        result = self._compute_next_core(frames, state)
        if not result:
            return {}
        result["_state"] = state
        return result

    def _compute_full_core(self, frames: dict) -> dict:
        """Pure full computation returning outputs only (no _state key).

        Implement in subclass. Returns {} when data is insufficient.

        Args:
            frames: Plugin frames dict (contains 'main' DataFrame).

        Returns:
            Dict of computed output values. Do NOT include _state -- the mixin
            attaches state via _seed_state after this call.

        Raises:
            NotImplementedError: Subclass must implement this method.
        """
        raise NotImplementedError(
            f"{type(self).__name__} must implement _compute_full_core(frames) -> dict"
        )

    def _compute_next_core(self, frames: dict, state: dict) -> dict:
        """Pure incremental computation that mutates state in place.

        Implement in subclass. State is guaranteed non-None when called by the
        mixin. Mutate state in place (state["key"] = new_value) -- do NOT
        create or return a new state dict. Returns {} when computation cannot
        proceed (e.g. missing state keys or insufficient data).

        Args:
            frames: Plugin frames dict (contains 'main' DataFrame).
            state:  Mutable state dict from previous call. Guaranteed non-None.
                    Mutate in place: state["prev_atr"] = new_atr, etc.

        Returns:
            Dict of computed output values. Do NOT include _state -- the mixin
            attaches state (the same mutated dict) after this call.

        Raises:
            NotImplementedError: Subclass must implement this method.
        """
        raise NotImplementedError(
            f"{type(self).__name__} must implement _compute_next_core(frames, state) -> dict"
        )

    def _seed_state(self, frames: dict) -> dict:
        """Extract incremental state from frames after full computation.

        Implement in subclass. Called by compute_full after _compute_full_core
        succeeds. Returns the initial state dict used to seed the first
        compute_next call.

        Args:
            frames: Plugin frames dict (contains 'main' DataFrame). Same frames
                    passed to _compute_full_core so subclass can re-read the data
                    to extract state values.

        Returns:
            Initial state dict for incremental seeding. May be empty {} if the
            plugin needs no persistent state.

        Raises:
            NotImplementedError: Subclass must implement this method.
        """
        raise NotImplementedError(
            f"{type(self).__name__} must implement _seed_state(frames) -> dict"
        )
