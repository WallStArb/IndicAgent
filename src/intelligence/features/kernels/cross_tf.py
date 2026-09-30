"""Cross-timeframe kernels: the CTF source series, the higher-timeframe (HTF) as-of join, the
CTF pass-through, and the ret_div divergences (D-25).

Higher-timeframe bars are stamped at their period start. A lower-timeframe (LTF) row with bar
start s and bar end e may read an HTF bar only if that bar is closed by e, and a bar is known
closed no later than the next HTF bar's start. `ctf_series_by_close` builds the CTF series and
keys each value by the time its bar closed in one step, so no caller can hold a start-keyed
dict; `ctf_row_inputs` does the as-of lookup for every row. (Todo 243 found the start-keyed join
selecting a still-forming bar; 186-15 proved the batch path causal and made the causal form the
only one.) The 1d self-referential case reads the row's own bar, available at the row's close.
"""

from __future__ import annotations

import bisect
import math
from collections import deque
from collections.abc import Sequence
from datetime import datetime
from typing import TYPE_CHECKING, NamedTuple

import numpy as np

from src.intelligence.feature_cache import _HMM_K, _hmm_forward_step, _wilder_rsi_series
from src.intelligence.features.contract.registry import Alignment, ExternalInput, Kernel
from src.intelligence.features.kernels._primitives import constant_tf

if TYPE_CHECKING:
    from src.intelligence.feature_factory import FeatureFactoryConfig


class CtfRecord(NamedTuple):
    """4-field CTF payload keyed by HTF bar timestamp (Phase 151 Plan 05).

    Extends the original 3-field ctf_momentum/ctf_vwap_align/ctf_regime_align
    payload with htf_last_log_ret (the HTF bar's own causal log return),
    consumed by the ret_div_5m_1h/ret_div_1h_1d cross-TF divergences.
    NamedTuple with keyword-construction-only at every call site (mirroring
    CrossAssetRecord, Phase 151 Plan 04) -- positional unpacking of a growing
    tuple is exactly the drift risk both changes remove (Codex review
    precedent, see 151-04-SUMMARY.md).
    """

    ctf_momentum: float
    ctf_vwap_align: float
    ctf_regime_align: float
    htf_last_log_ret: float


def _build_ctf_series(
    htf_bars: list[dict],
    config: FeatureFactoryConfig,
) -> dict:
    """Build {htf_bar_period_start: CtfRecord} in O(n).

    Single-pass streaming computation: Wilder RSI + cumulative VWAP + HMM forward
    + causal HTF log return. Avoids O(n²) slice reprocessing. All values are
    causal — bar k uses only bars 0..k. Keys are period-start timestamps,
    matching `htf_bars[k]["ts"]` exactly; callers that need close-time keys (see
    `_compute_symbol_tf`'s todo-243 shift) remap after the fact.
    """
    n = len(htf_bars)
    if n < 2:
        return {}

    closes = np.array([b["close"] for b in htf_bars], dtype=float)
    highs = np.array([b["high"] for b in htf_bars], dtype=float)
    lows = np.array([b["low"] for b in htf_bars], dtype=float)
    volumes = np.array([b["volume"] for b in htf_bars], dtype=float)

    period = config.rsi_mid_period

    # ctf_momentum: Wilder RSI per bar, normalized to [-1, +1]. Single shared impl.
    rsi_series = _wilder_rsi_series(closes, period)
    ctf_mom = np.clip((rsi_series - 50.0) / 50.0, -1.0, 1.0)

    # ctf_vwap_align: sign(close - cumulative VWAP)
    typical = (highs + lows + closes) / 3.0
    cum_tp_vol = np.cumsum(typical * volumes)
    cum_vol = np.cumsum(volumes)
    vwap = np.where(cum_vol > 1e-10, cum_tp_vol / cum_vol, closes)
    ctf_vwap = np.where(closes > vwap + 1e-10, 1.0, np.where(closes < vwap - 1e-10, -1.0, 0.0))

    # ctf_regime_align: HMM forward pass — 0.0 (ranging) or 1.0 (trending)
    ctf_regime = np.zeros(n, dtype=float)
    hmm_alpha = np.full(_HMM_K, 1.0 / _HMM_K, dtype=float)
    log_rets = np.diff(np.log(np.maximum(closes, 1e-10)))
    log_rets = np.where(np.isfinite(log_rets), log_rets, 0.0)
    ret_buf: deque = deque(maxlen=20)
    obs_buf = np.zeros(2, dtype=float)
    for i, ret in enumerate(log_rets):
        ret_buf.append(float(ret))
        obs_buf[0] = float(ret)
        obs_buf[1] = float(np.std(ret_buf)) if len(ret_buf) >= 2 else 0.005
        _hmm_forward_step(obs_buf, hmm_alpha)
        label = int(np.argmax(hmm_alpha))
        ctf_regime[i + 1] = 0.0 if label == 0 else 1.0  # gradient-exempt: HMM state label

    # htf_last_log_ret (Phase 151 Plan 05): the HTF bar's own causal log
    # return, log(close[k] / close[k-1]), 0.0 at k=0 (no prior bar). Feeds
    # ret_div_5m_1h/ret_div_1h_1d -- distinct from ctf_momentum (Wilder RSI,
    # a smoothed multi-bar oscillator) and from log_rets above (that array's
    # length is n-1, unpadded; htf_last_log_ret is n-aligned and padded).
    htf_last_log_ret = np.concatenate(([0.0], log_rets))

    return {
        htf_bars[k]["ts"]: CtfRecord(
            ctf_momentum=float(ctf_mom[k]),
            ctf_vwap_align=float(ctf_vwap[k]),
            ctf_regime_align=float(ctf_regime[k]),
            htf_last_log_ret=float(htf_last_log_ret[k]),
        )
        for k in range(n)
    }


def _rekey_ctf_series_to_actual_close(ctf_by_ts: dict, tf: str, htf_tf: str) -> dict:
    """Re-key `_build_ctf_series`'s dict from HTF period-start to each bar's ACTUAL close
    (todo 243) -- the next HTF bar's own start, not a flat nominal-duration offset.

    Only applies to genuine cross-timeframe pairs (`tf != htf_tf`, e.g. 5m/15m->1h,
    1h->1d): the batch join (`bisect.bisect_right(ctf_ts_list, bar_ts) - 1` in
    FeatureFactory.compute_batch) would otherwise select a still-forming HTF bar for LTF
    rows inside its still-open window -- real lookahead. A flat offset (`ts + nominal
    duration`) is wrong for real partial bars: confirmed against production data, the
    RTH-session-opening 1h bar is a genuine 30-minute partial (e.g. 13:30-14:00 UTC), and
    a flat offset would overshoot its true close by 30 minutes, silently routing LTF rows
    in that overshoot window to a stale, older bar instead of the correct, already-closed
    one. The last HTF bar has no known successor in this dict and is dropped -- its true
    close isn't knowable from data on hand; the next backfill run picks it up once its
    successor bar exists.

    1d's self-referential case (`tf == htf_tf`) is returned unchanged: re-keying it would
    select the *prior* day's bar instead of the current, already-closed one -- see
    `FeatureFactoryConfig.ctf_higher_tf_map`'s docstring (feature_factory.py).
    """
    if tf == htf_tf:
        return ctf_by_ts
    ts_sorted = sorted(ctf_by_ts.keys())
    return {ts_sorted[i + 1]: ctf_by_ts[ts_sorted[i]] for i in range(len(ts_sorted) - 1)}


def _build_ltf_return_series(ltf_bars: list[dict], target_ts_list: list) -> dict:
    """Build {target_bar_ts: last 1m log return at-or-before target_bar_ts} in
    O(n+m), Phase 151 Plan 05 (todo 066) -- feeds ret_div_1m_5m.

    Single merge walk over two already-sorted-ascending timestamp lists
    (`ltf_bars` from `_fetch_bars_from_db`, `target_ts_list` the caller's 5m
    bar timestamps -- both fetched oldest-first per that function's own
    contract). Causal: a target timestamp only ever picks up a 1m bar whose
    own `ts` is <= the target timestamp, never one strictly after it -- the
    1m log return itself is `log(close[k] / close[k-1])` for that 1m bar, the
    same causal definitional formula as `_ret_lag_1` elsewhere in this
    codebase. No entry is emitted for a target timestamp with zero eligible
    (at-or-before) 1m bars yet (typically the very start of 1m coverage).
    """
    if not ltf_bars or not target_ts_list:
        return {}

    result: dict = {}
    closes = [float(b["close"]) for b in ltf_bars]
    ts_list = [b["ts"] for b in ltf_bars]
    n = len(ltf_bars)
    j = 0
    prev_close: float | None = None
    last_log_ret: float | None = None

    for target_ts in target_ts_list:
        while j < n and ts_list[j] <= target_ts:
            if prev_close is not None and prev_close > 0.0 and closes[j] > 0.0:
                last_log_ret = math.log(closes[j] / prev_close)
            prev_close = closes[j]
            j += 1
        if last_log_ret is not None:
            result[target_ts] = last_log_ret

    return result


def ctf_series_by_close(
    htf_bars: list[dict], config: FeatureFactoryConfig, tf: str, htf_tf: str
) -> dict:
    """{HTF close time: CtfRecord} for `tf` rows: build the series, then key each value by its
    bar's close (the next HTF bar's start). The only public constructor of a CTF series."""
    return _rekey_ctf_series_to_actual_close(_build_ctf_series(htf_bars, config), tf, htf_tf)


def ctf_row_inputs(
    row_ts: Sequence[datetime], ctf_by_ts: dict, ctf_ts_list: list
) -> dict[str, np.ndarray]:
    """The four HTF externals on the row grid: for each row the latest HTF value whose close key
    is at or before the row's bar start (a row is never given a bar that closes after it starts).

    `ext_ctf_*` are 0.0 before the first HTF close; `ext_htf_last_log_ret` is NaN there.
    """
    n = len(row_ts)
    momentum = np.zeros(n)
    vwap = np.zeros(n)
    regime = np.zeros(n)
    htf_ret = np.full(n, np.nan)
    for i, ts in enumerate(row_ts):
        idx = bisect.bisect_right(ctf_ts_list, ts) - 1
        if idx >= 0:
            value = ctf_by_ts[ctf_ts_list[idx]]
            momentum[i] = value.ctf_momentum
            vwap[i] = value.ctf_vwap_align
            regime[i] = value.ctf_regime_align
            htf_ret[i] = value.htf_last_log_ret
    return {
        "ext_ctf_momentum": momentum,
        "ext_ctf_vwap_align": vwap,
        "ext_ctf_regime_align": regime,
        "ext_htf_last_log_ret": htf_ret,
    }


EXTERNAL_INPUTS = (
    *(
        ExternalInput(name, np.dtype(np.float64), Alignment.HTF_ASOF_CLOSE)
        for name in (
            "ext_ctf_momentum",
            "ext_ctf_vwap_align",
            "ext_ctf_regime_align",
            "ext_htf_last_log_ret",
        )
    ),
    ExternalInput("ext_ltf_last_log_ret", np.dtype(np.float64), Alignment.LTF_ASOF_BAR_START),
)

_CTF_SOURCE_OUTPUTS = (
    "_ctf_momentum_src",
    "_ctf_vwap_align_src",
    "_ctf_regime_align_src",
    "_htf_last_log_ret_src",
)


def _compute_ctf_source(x, config):
    n = len(x["close"])
    bars = [
        {
            "ts": k,
            "high": float(x["high"][k]),
            "low": float(x["low"][k]),
            "close": float(x["close"][k]),
            "volume": float(x["volume"][k]),
        }
        for k in range(n)
    ]
    series = _build_ctf_series(bars, config)  # keyed by row index; {} below two bars
    out = {name: np.full(n, np.nan) for name in _CTF_SOURCE_OUTPUTS}
    for k, value in series.items():
        out["_ctf_momentum_src"][k] = value.ctf_momentum
        out["_ctf_vwap_align_src"][k] = value.ctf_vwap_align
        out["_ctf_regime_align_src"][k] = value.ctf_regime_align
        out["_htf_last_log_ret_src"][k] = value.htf_last_log_ret
    return out


def _compute_ctf_passthrough(x, config):
    return {
        "ctf_momentum": np.asarray(x["ext_ctf_momentum"], dtype=np.float64).copy(),
        "ctf_vwap_align": np.asarray(x["ext_ctf_vwap_align"], dtype=np.float64).copy(),
        "ctf_regime_align": np.asarray(x["ext_ctf_regime_align"], dtype=np.float64).copy(),
    }


def _compute_cross_tf_divergence(x, config):
    tf = constant_tf(x["tf"])
    own = np.asarray(x["ret_lag_1"], dtype=np.float64)
    htf = np.asarray(x["ext_htf_last_log_ret"], dtype=np.float64)
    ltf = np.asarray(x["ext_ltf_last_log_ret"], dtype=np.float64)
    nan = np.full(len(own), np.nan)
    return {
        "ret_div_5m_1h": own - htf if tf == "5m" else nan.copy(),
        "ret_div_1h_1d": own - htf if tf == "1h" else nan.copy(),
        "ret_div_1m_5m": ltf - own if tf == "5m" else nan.copy(),
    }


KERNELS = (
    Kernel(
        name="ctf_source",
        outputs=_CTF_SOURCE_OUTPUTS,
        inputs=("high", "low", "close", "volume"),
        memory=lambda config: 0,
        compute=_compute_ctf_source,
        path_dependent=True,
        path_dependent_reason=(
            "cumulative VWAP and the HMM forward pass run from the series start"
        ),
    ),
    Kernel(
        name="ctf_passthrough",
        outputs=("ctf_momentum", "ctf_vwap_align", "ctf_regime_align"),
        inputs=("ext_ctf_momentum", "ext_ctf_vwap_align", "ext_ctf_regime_align"),
        memory=lambda config: 0,
        compute=_compute_ctf_passthrough,
    ),
    Kernel(
        name="cross_tf_divergence",
        outputs=("ret_div_5m_1h", "ret_div_1h_1d", "ret_div_1m_5m"),
        inputs=("ret_lag_1", "tf", "ext_htf_last_log_ret", "ext_ltf_last_log_ret"),
        memory=lambda config: 0,
        compute=_compute_cross_tf_divergence,
    ),
)
