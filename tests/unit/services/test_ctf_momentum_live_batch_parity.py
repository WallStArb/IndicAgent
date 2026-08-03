"""Regression tests for todo 241 -- ctf_momentum live/batch compute divergence.

Prior to this fix, feature_vector_pipeline.py's live path computed ctf_momentum as a
crude same-bar intrabar-return proxy `(close - open) / open`, while
backfill_feature_factory.py's batch/corpus path computed it as a causal Wilder RSI over
the mapped higher timeframe's own bars -- two different statistics sharing one column
name.

Scope note (code review finding #5, 2026-08-03): these tests confirm live's
_update_ctf_cache_from_htf_bar() shares the same underlying Wilder RSI implementation as
batch's _build_ctf_series() (both route through feature_cache._wilder_rsi_series /
_rsi_simple) and that propagation reaches every LTF cache the HTF bar feeds
(feature_cache._CTF_HIGHER_TF: 5m/15m -> 1h, 1h -> 1d, 1d -> 1d self-referential). They
do NOT prove live and batch select the identical HTF bar for a given LTF row -- that
join (feature_factory.py's `bisect.bisect_right(ctf_ts_list, bar_ts) - 1` against
period-start-stamped HTF bars) has an independently-discovered, unresolved lookahead
defect for 5m/15m/1h (filed separately, see docs/foundation/gotchas.md /
.planning/todos/pending/243-*.md) -- live's causal _bar_history-only read is correct and
therefore will NOT bit-match batch's current (buggy) join output for those three tfs.
Only the shared RSI/formula-level reuse is what these tests pin.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from services.backfill_feature_factory import _build_ctf_series
from services.feature_vector_pipeline import _assert_rsi_mid_period_fits_bar_history
from src.core.bar_normalizer import SOURCE_IBKR_NAMED
from src.core.schemas.bar_message import BarMessage, SessionType
from tests.unit.pipeline.pipeline_helpers import make_agent


def _htf_bars(symbol: str, tf: str, n: int, *, start_close: float = 100.0) -> list[BarMessage]:
    """n bars with a mixed up/down walk so Wilder RSI lands strictly inside (0, 100) --
    not a monotonic trend, which saturates RSI to 0/100 and ctf_momentum to exactly
    +-1.0, an equality assertion against a clipped constant that proves less than it
    appears to (code review finding #5)."""
    bars = []
    ts = datetime(2026, 3, 1, 0, 0, 0, tzinfo=UTC)
    step = timedelta(hours=1) if tf == "1h" else timedelta(days=1)
    close = start_close
    for i in range(n):
        # Net upward drift (so ctf_momentum lands positive, non-trivial) but with
        # periodic down-ticks so Wilder's avg_loss never stays exactly zero.
        close += 1.5 if i % 3 != 0 else -0.6
        bars.append(
            BarMessage(
                ts=ts + i * step,
                symbol=symbol,
                tf=tf,
                open=close - 0.5,
                high=close + 0.5,
                low=close - 1.0,
                close=close,
                volume=1000,
                source=SOURCE_IBKR_NAMED,
                session_type=SessionType.RTH,
            )
        )
    return bars


def test_ctf_momentum_uses_shared_wilder_rsi_not_intrabar_proxy():
    """Live-computed ctf_momentum must equal batch's per-HTF-bar Wilder RSI value --
    proves the shared-helper reuse, not the LTF join (see module docstring)."""
    agent = make_agent()
    period = agent._feature_factory_config.rsi_mid_period  # 14 per pipeline_helpers fixture

    htf_bars = _htf_bars("SPY", "1h", period + 5)
    for bar in htf_bars:
        agent._bar_history.append(bar)

    agent._update_ctf_cache_from_htf_bar("SPY", "1h", create_if_missing=True)

    live_value = agent._get_cache("SPY", "15m").ctf_momentum
    assert -1.0 < live_value < 1.0, "fixture must not saturate RSI to 0/100"

    batch_input = [
        {
            "ts": b.ts,
            "open": b.open,
            "high": b.high,
            "low": b.low,
            "close": b.close,
            "volume": b.volume,
        }
        for b in htf_bars
    ]
    batch_series = _build_ctf_series(batch_input, agent._feature_factory_config)
    expected = batch_series[htf_bars[-1].ts][0]  # (ctf_momentum, ctf_vwap_align, ctf_regime_align)

    assert live_value == expected, (
        "live ctf_momentum must exactly match batch's Wilder-RSI computation at the same "
        "HTF bar -- if this fails, live has drifted from the shared _rsi_simple/"
        "_wilder_rsi_series implementation (todo 241)"
    )
    old_proxy = (htf_bars[-1].close - htf_bars[-1].open) / htf_bars[-1].open
    assert abs(live_value - old_proxy) > 1e-6, (
        "must materially differ from the discarded intrabar-return proxy -- proves the "
        "fix is actually wired in, not a no-op"
    )


def test_ctf_momentum_propagates_to_all_ltf_caches_sharing_an_htf():
    """A single 1h bar must update both the 5m and 15m caches (feature_cache._CTF_HIGHER_TF)."""
    agent = make_agent()
    period = agent._feature_factory_config.rsi_mid_period

    for bar in _htf_bars("QQQ", "1h", period + 3):
        agent._bar_history.append(bar)

    agent._update_ctf_cache_from_htf_bar("QQQ", "1h", create_if_missing=True)

    cache_5m = agent._get_cache("QQQ", "5m")
    cache_15m = agent._get_cache("QQQ", "15m")
    assert cache_5m.ctf_momentum == cache_15m.ctf_momentum
    assert cache_5m.ctf_momentum != 0.0, "must have moved off the FeatureCache dataclass default"


def test_ctf_momentum_1d_is_self_referential_not_cross_timeframe():
    """1d has no HTF above it in this corpus -- _CTF_HIGHER_TF maps 1d -> 1d (todo 189).

    Live must reproduce this degenerate case identically to batch, not silently skip it.
    """
    agent = make_agent()
    period = agent._feature_factory_config.rsi_mid_period

    for bar in _htf_bars("TLT", "1d", period + 3):
        agent._bar_history.append(bar)

    agent._update_ctf_cache_from_htf_bar("TLT", "1d", create_if_missing=True)

    assert agent._get_cache("TLT", "1d").ctf_momentum != 0.0
    # 5m/15m never source from "1d" -- must be untouched (still cold).
    assert "TLT:5m" not in agent._feature_caches


def test_ctf_momentum_5m_bar_arrival_does_not_fire_update():
    """5m is never an HTF source (_CTF_HIGHER_TF's values are only "1h"/"1d") -- confirms
    the fixed live gate (`bar.tf in _CTF_LOWER_TFS`) no longer fires on 5m/15m arrivals the
    way the old, looser `bar.tf in ("15m", "1h", "4h", "1d")` condition incorrectly did.
    """
    from services.feature_vector_pipeline import _CTF_LOWER_TFS

    assert "5m" not in _CTF_LOWER_TFS
    assert "15m" not in _CTF_LOWER_TFS
    assert set(_CTF_LOWER_TFS) == {"1h", "1d"}


def test_ctf_momentum_truncates_to_bar_history_maxlen():
    """BarHistory silently drops bars beyond maxlen -- live's RSI must reflect only the
    most recent `maxlen` bars, matching what a real 200-bar-capped deployment would see
    (code review finding #5: buffer truncation was previously untested)."""
    agent = make_agent()
    maxlen = agent._bar_history.maxlen

    # Feed more bars than the buffer holds -- BarHistory evicts the oldest automatically.
    for bar in _htf_bars("IEF", "1h", maxlen + 50):
        agent._bar_history.append(bar)

    retained = agent._bar_history.get("IEF", "1h")
    assert len(retained) == maxlen, "BarHistory must have truncated to its configured maxlen"

    agent._update_ctf_cache_from_htf_bar("IEF", "1h", create_if_missing=True)
    live_value = agent._get_cache("IEF", "15m").ctf_momentum

    batch_input = [
        {
            "ts": b.ts,
            "open": b.open,
            "high": b.high,
            "low": b.low,
            "close": b.close,
            "volume": b.volume,
        }
        for b in retained
    ]
    expected = _build_ctf_series(batch_input, agent._feature_factory_config)[retained[-1].ts][0]
    assert live_value == expected, (
        "live must compute RSI over exactly the retained (truncated) window, matching "
        "batch computed over that same truncated set"
    )


def test_rsi_mid_period_within_buffer_passes():
    _assert_rsi_mid_period_fits_bar_history(rsi_mid_period=14, bar_history_maxlen=200)
    _assert_rsi_mid_period_fits_bar_history(rsi_mid_period=199, bar_history_maxlen=200)


def test_rsi_mid_period_exceeding_buffer_fails_loud():
    """An APR override that would silently zero ctf_momentum for every symbol (period +
    1 > BarHistory's maxlen) must fail loud at config-load time, not compute 0.0 forever
    (code review finding #4)."""
    with pytest.raises(AssertionError, match="ctf_momentum would silently compute as 0.0"):
        _assert_rsi_mid_period_fits_bar_history(rsi_mid_period=200, bar_history_maxlen=200)
    with pytest.raises(AssertionError):
        _assert_rsi_mid_period_fits_bar_history(rsi_mid_period=300, bar_history_maxlen=200)
