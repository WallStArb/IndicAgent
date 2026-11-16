"""Canary control kernels (D-25)."""

from __future__ import annotations

import math

import numpy as np

from src.core.rng import hash_key_to_int
from src.intelligence.features.contract.registry import Alignment, ExternalInput, Kernel
from src.intelligence.features.kernels._primitives import EPS, unique_datetimes

# These two numbers define the control predictors, they are not tunables (APR-exempt: statistical
# concept definitions, like the 5 in momentum_z_5). canary_constant is the value 1.0 on every row;
# canary_near_constant is 1.0 plus 1e-6 times a standard normal draw, a column that is constant to
# within numerical noise. Changing either redefines the control and invalidates every recorded
# reading of it.
_CANARY_CONSTANT_VALUE: float = 1.0
_CANARY_NEAR_CONSTANT_EPSILON: float = 1e-6


def _canary_seed(ts_int: int, symbol_hash: int, base_seed: int, offset: int) -> int:
    """The per-(symbol, bar) canary seed from its two per-row ingredients, so a caller hashes a
    symbol and converts a timestamp once instead of once per canary."""
    return (base_seed * 1_000_003 + ts_int * 97 + offset + symbol_hash) % (2**32)


def _canary_acausal_placebo(closes: np.ndarray, i: int, eps: float = EPS) -> float:
    """Deliberate look-ahead leak (positive control): pairs bar i with the
    close-to-close return realized from bars i+1 -> i+2 (the ret_lag_1 shape,
    forward-shifted). Against the executable open-to-open labels it is fully
    contained only in lookahead h >= 2 (open[i+1] -> open[i+h+1]); the h = 1
    label shares just the overnight gap close[i+1] -> open[i+2], so its IC
    peaks at h = 2 (1d pooled: ~0.32 at h=1, ~0.64 at h=2) and a small h = 1
    cell can miss significance. Detection checks gate on the containing
    lookahead (phase 179 V5). Falls back to 0.0 when the future bars don't exist yet (end of
    the batch series, or the deleted live single-bar path, which by
    definition had no future data).
    """
    if i + 2 >= len(closes) or closes[i + 1] <= eps or closes[i + 2] <= eps:
        return 0.0
    return float(math.log(closes[i + 2] / closes[i + 1]))


# ---------------------------------------------------------------------------
# Kernels
# ---------------------------------------------------------------------------

EXTERNAL_INPUTS = (ExternalInput("symbol", np.dtype(object), Alignment.CONSTANT_PER_SERIES),)


def _compute_noise(inputs, config):
    """The three noise canaries; each value is `_canary_noise_*` of (bar datetime, symbol, seed).

    The symbol hash and the millisecond timestamp are computed once per distinct symbol and
    per distinct timestamp, and a repeated (timestamp, symbol) row reuses its draws. Each draw
    still comes from its own `default_rng` on the same sub-seed, in the same order.
    """
    symbols = inputs["symbol"]
    n = len(inputs["ts_dt"])
    per_row_symbol = len(symbols) == n
    default_symbol = str(symbols[0]) if len(symbols) else ""
    inverse, unique_dts = unique_datetimes(inputs["ts_dt"])
    ts_ms = [int(bar_ts.timestamp() * 1000) for bar_ts in unique_dts]
    seed = config.canary_rng_seed
    symbol_hashes: dict[str, int] = {}
    drawn: dict[tuple[int, str], tuple[float, float, float]] = {}
    gaussian, uniform, near_constant = np.empty(n), np.empty(n), np.empty(n)
    for i in range(n):
        sym = str(symbols[i]) if per_row_symbol else default_symbol
        key = (int(inverse[i]), sym)
        values = drawn.get(key)
        if values is None:
            if sym not in symbol_hashes:
                symbol_hashes[sym] = hash_key_to_int(sym)
            ts_int, symbol_hash = ts_ms[key[0]], symbol_hashes[sym]
            values = drawn[key] = (
                float(
                    np.random.default_rng(
                        _canary_seed(ts_int, symbol_hash, seed, 0)
                    ).standard_normal()
                ),
                float(
                    np.random.default_rng(_canary_seed(ts_int, symbol_hash, seed, 1)).uniform(
                        0.0, 1.0
                    )
                ),
                _CANARY_CONSTANT_VALUE
                + _CANARY_NEAR_CONSTANT_EPSILON
                * float(
                    np.random.default_rng(
                        _canary_seed(ts_int, symbol_hash, seed, 2)
                    ).standard_normal()
                ),
            )
        gaussian[i], uniform[i], near_constant[i] = values
    return {
        "canary_noise_gaussian": gaussian,
        "canary_noise_uniform": uniform,
        "canary_near_constant": near_constant,
    }


def _compute_constant(inputs, config):
    return {"canary_constant": np.full(len(inputs["ts"]), _CANARY_CONSTANT_VALUE)}


def _compute_acausal_placebo(inputs, config):
    closes = inputs["close"]
    return {
        "canary_acausal_placebo": np.array(
            [_canary_acausal_placebo(closes, i) for i in range(len(closes))]
        )
    }


KERNELS = (
    Kernel(
        name="canary_noise",
        outputs=("canary_noise_gaussian", "canary_noise_uniform", "canary_near_constant"),
        inputs=("ts_dt", "symbol"),
        memory=lambda config: 0,
        compute=_compute_noise,
    ),
    Kernel(
        name="canary_constant",
        outputs=("canary_constant",),
        inputs=("ts",),
        memory=lambda config: 0,
        compute=_compute_constant,
    ),
    Kernel(
        name="canary_acausal_placebo",
        outputs=("canary_acausal_placebo",),
        inputs=("close",),
        memory=lambda config: 0,
        compute=_compute_acausal_placebo,
        # Positive control: it reads closes[i + 1] and closes[i + 2] by design, proving the
        # causality probe detects lookahead on a real registered kernel.
        acausal_control=True,
    ),
)
