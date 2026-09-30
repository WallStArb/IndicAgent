"""Canary control kernels (D-25)."""

from __future__ import annotations

import math
from datetime import datetime

import numpy as np

from src.core.rng import hash_key_to_int
from src.intelligence.features.contract.registry import Alignment, ExternalInput, Kernel
from src.intelligence.features.kernels._primitives import EPS, unique_datetimes

_CANARY_CONSTANT_VALUE: float = 1.0


_CANARY_NEAR_CONSTANT_EPSILON: float = 1e-6


def _canary_sub_seed(bar_ts: datetime, symbol: str, base_seed: int, offset: int) -> int:
    """Deterministic per-(symbol, bar) sub-seed derived from symbol + bar_ts +
    the APR base seed + a per-canary offset.

    2026-07-29 fix (todo 203): previously omitted `symbol` entirely -- every
    symbol received the IDENTICAL "random" draw at a given bar_ts, confirmed
    live in feature_vectors (bit-identical canary_noise_gaussian/uniform/
    near_constant across every pooled symbol at the same timestamp). Any
    cross-sectional measurement pooling multiple symbols (this project's own
    ic_engine.py _compute_cross_sectional_tf, or an ad hoc diagnostic doing the
    same) saw severe pseudo-replication as a result -- the true independent
    draw count per bar_ts was 1, not n_symbols, defeating these negative
    controls' entire purpose.

    The symbol component uses hash_key_to_int (src/core/rng.py) -- the shared
    Ring-0 primitive also used by ic_engine.py's _derive_worker_rng_seed(cell_key,
    bootstrap_seed) (extracted 2026-07-29 /simplify pass after this function
    independently re-derived the same MD5-hash-to-int idiom) -- stable across
    processes/interpreter versions (PYTHONHASHSEED-independent), required for
    ProcessPoolExecutor workers and the "same bar inputs + seed -> same value"
    determinism contract. The bar_ts/offset arithmetic component is unchanged from
    the original (still pure arithmetic, no hash() there either).
    """
    return _canary_seed(int(bar_ts.timestamp() * 1000), hash_key_to_int(symbol), base_seed, offset)


def _canary_seed(ts_int: int, symbol_hash: int, base_seed: int, offset: int) -> int:
    """`_canary_sub_seed` from its two per-row ingredients, so a caller hashes a symbol and
    converts a timestamp once instead of once per canary."""
    return (base_seed * 1_000_003 + ts_int * 97 + offset + symbol_hash) % (2**32)


def _canary_noise_gaussian(bar_ts: datetime, symbol: str, base_seed: int) -> float:
    """Pure Gaussian noise, N(0, 1) (offset=0). Negative control: must never
    carry IC."""
    rng = np.random.default_rng(_canary_sub_seed(bar_ts, symbol, base_seed, offset=0))
    return float(rng.standard_normal())


def _canary_noise_uniform(bar_ts: datetime, symbol: str, base_seed: int) -> float:
    """Pure Uniform[0, 1) noise (offset=1), independently seeded from the
    Gaussian canary. Two distributionally-distinct RNG sources both agreeing
    they are null is stronger pipeline-integrity evidence than one alone."""
    rng = np.random.default_rng(_canary_sub_seed(bar_ts, symbol, base_seed, offset=1))
    return float(rng.uniform(0.0, 1.0))


def _canary_near_constant(bar_ts: datetime, symbol: str, base_seed: int) -> float:
    """_CANARY_CONSTANT_VALUE plus tiny deterministic epsilon noise
    (offset=2) -- verifies degenerate near-zero-variance input handling
    without being bit-identical to the pure constant canary."""
    rng = np.random.default_rng(_canary_sub_seed(bar_ts, symbol, base_seed, offset=2))
    return _CANARY_CONSTANT_VALUE + _CANARY_NEAR_CONSTANT_EPSILON * float(rng.standard_normal())


def _canary_acausal_placebo(closes: np.ndarray, i: int, eps: float = EPS) -> float:
    """Deliberate look-ahead leak (positive control): pairs bar i with the
    close-to-close return realized from bars i+1 -> i+2 (the ret_lag_1 shape,
    forward-shifted). Against the executable open-to-open labels it is fully
    contained only in lookahead h >= 2 (open[i+1] -> open[i+h+1]); the h = 1
    label shares just the overnight gap close[i+1] -> open[i+2], so its IC
    peaks at h = 2 (1d pooled: ~0.32 at h=1, ~0.64 at h=2) and a small h = 1
    cell can miss significance. Detection checks gate on the containing
    lookahead (phase 179 V5). Falls back to 0.0 when the future bars don't exist yet (end of
    the batch series, or the live single-bar compute() path, which by
    definition has no future data -- see FeatureFactory.compute() docstring).
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
    n = len(inputs["ts"])
    per_row_symbol = len(symbols) == n
    default_symbol = str(symbols[0]) if len(symbols) else ""
    inverse, unique_dts = unique_datetimes(inputs["ts"])
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
        inputs=("ts", "symbol"),
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
