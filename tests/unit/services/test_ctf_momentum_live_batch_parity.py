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
do NOT prove live and batch select the identical HTF bar for a given LTF row -- see
`TestCtfBatchJoinLookaheadFix` below for that (todo 243, fixed 2026-08-03): batch's caller
(`_compute_symbol_tf` in backfill_feature_factory.py) now calls
`_rekey_ctf_series_to_actual_close()`, which re-keys `_build_ctf_series`'s dict to each
HTF bar's ACTUAL close -- the next HTF bar's own start, not a flat nominal-duration offset
-- for genuine cross-timeframe pairs (5m/15m->1h, 1h->1d) before the join's
`bisect.bisect_right(ctf_ts_list, bar_ts) - 1` runs, so it can no longer select a still-
forming bar. A flat offset was rejected during code review (2026-08-03): it silently
overshoots a real partial bar's true close (confirmed against production data -- the
RTH-session-opening 1h bar is a genuine 30-minute partial, e.g. 13:30-14:00 UTC), routing
LTF rows in the overshoot window to a stale, older bar. The 1d->1d self-referential case
is deliberately left on `_build_ctf_series`'s native period-start keys (re-keying it would
select the *prior* day's bar instead of the current, already-closed one).
"""

from __future__ import annotations

import bisect
from datetime import UTC, datetime, timedelta

import pytest

from services.backfill_feature_factory import _build_ctf_series, _rekey_ctf_series_to_actual_close
from services.feature_vector_pipeline import _assert_rsi_mid_period_fits_bar_history
from src.core.bar_normalizer import SOURCE_IBKR_NAMED
from src.core.schemas.bar_message import BarMessage, SessionType
from tests.unit.pipeline.pipeline_helpers import make_agent


def _to_bar_dicts(bars: list[BarMessage]) -> list[dict]:
    return [
        {
            "ts": b.ts,
            "open": b.open,
            "high": b.high,
            "low": b.low,
            "close": b.close,
            "volume": b.volume,
        }
        for b in bars
    ]


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

    batch_series = _build_ctf_series(_to_bar_dicts(htf_bars), agent._feature_factory_config)
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

    expected = _build_ctf_series(_to_bar_dicts(retained), agent._feature_factory_config)[
        retained[-1].ts
    ][0]
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


class TestCtfBatchJoinLookaheadFix:
    """Regression tests for todo 243 -- batch's LTF->HTF join selected the still-forming
    HTF bar, not the last one that had actually closed. Calls the real production
    function (`_rekey_ctf_series_to_actual_close`), not a duplicated re-key expression
    (code review finding, 2026-08-03), then joins with the same
    `bisect.bisect_right(ctf_ts_list, bar_ts) - 1` `_compute_symbol_tf` uses.
    """

    def _join(self, ctf_by_ts: dict, bar_ts: datetime):
        ctf_ts_list = sorted(ctf_by_ts.keys())
        idx = bisect.bisect_right(ctf_ts_list, bar_ts) - 1
        assert idx >= 0, "no closed HTF bar available at this bar_ts"
        return ctf_by_ts[ctf_ts_list[idx]]

    def test_cross_timeframe_join_selects_last_closed_bar_not_still_forming_one(self):
        """5m rows within an 1h bar's still-open window must resolve to the *prior*,
        fully-closed 1h bar -- not the one whose own close lies in the future relative to
        bar_ts (the exact lookahead todo 243 found). Uses N=period+6 bars so the
        second-to-last original bar (the one under test) has a real successor and isn't
        the dropped trailing bar."""
        period = 14
        htf_bars_msgs = _htf_bars("SPY", "1h", period + 6)
        htf_bars = _to_bar_dicts(htf_bars_msgs)
        config = make_agent()._feature_factory_config

        unshifted = _build_ctf_series(htf_bars, config)
        ctf_by_ts = _rekey_ctf_series_to_actual_close(unshifted, "5m", "1h")

        bar_before_forming_ts = htf_bars_msgs[-3].ts  # closed by the time the next test opens
        forming_bar_ts = htf_bars_msgs[-2].ts  # covers [forming_bar_ts, htf_bars_msgs[-1].ts)
        actual_close_ts = htf_bars_msgs[-1].ts  # the forming bar's real close (next bar's start)

        # A 5m row 5 minutes into the still-forming bar's window.
        bar_ts_mid_forming_window = forming_bar_ts + timedelta(minutes=5)
        selected = self._join(ctf_by_ts, bar_ts_mid_forming_window)

        assert selected == unshifted[bar_before_forming_ts], (
            "must select the prior, fully-closed HTF bar's values, not the still-forming "
            "one covering this bar_ts -- this is exactly todo 243's lookahead"
        )

        # At the exact instant the forming bar actually closes, it becomes the correct
        # selection.
        selected_at_close = self._join(ctf_by_ts, actual_close_ts)
        assert selected_at_close == unshifted[forming_bar_ts]

    def test_partial_bar_close_uses_actual_next_bar_start_not_flat_duration_offset(self):
        """The RTH-session-opening 1h bar is a genuine 30-minute partial in production
        (confirmed against market_data_ohlcv_tradeable, code review 2026-08-03) -- a flat
        `ts + 1h` offset would overshoot its true close by 30 minutes and route the 5m
        rows in that overshoot window to the stale, prior bar instead of the correct one.
        """
        period = 14
        htf_bars_msgs = _htf_bars("SPY", "1h", period + 5)
        # Shrink the last bar's gap to 30 minutes -- a partial bar, its true close is its
        # own ts + 30min, not + 1h.
        htf_bars_msgs[-1] = htf_bars_msgs[-1].model_copy(
            update={"ts": htf_bars_msgs[-2].ts + timedelta(minutes=30)}
        )
        htf_bars = _to_bar_dicts(htf_bars_msgs)
        config = make_agent()._feature_factory_config

        unshifted = _build_ctf_series(htf_bars, config)
        ctf_by_ts = _rekey_ctf_series_to_actual_close(unshifted, "5m", "1h")

        second_to_last_ts = htf_bars_msgs[-2].ts
        actual_close_ts = htf_bars_msgs[-1].ts  # 30 minutes after second_to_last_ts

        # Right at the true close (30 min later), the partial bar's values must already
        # be selectable -- a flat +1h offset would still be 30 minutes away from firing.
        selected_at_true_close = self._join(ctf_by_ts, actual_close_ts)
        assert selected_at_true_close == unshifted[second_to_last_ts], (
            "must resolve to the partial bar's own values at its true (30-min) close, "
            "not remain stuck on the prior bar until a flat 1h offset would have fired"
        )

    def test_1d_self_referential_join_unchanged_uses_own_bar_not_prior_day(self):
        """1d->1d must keep selecting the LTF row's own bar (no re-key) -- re-keying it
        like the cross-timeframe case would instead select yesterday's bar."""
        period = 14
        htf_bars_msgs = _htf_bars("TLT", "1d", period + 5)
        htf_bars = _to_bar_dicts(htf_bars_msgs)
        config = make_agent()._feature_factory_config

        ctf_by_ts = _rekey_ctf_series_to_actual_close(
            _build_ctf_series(htf_bars, config), "1d", "1d"
        )

        own_bar_ts = htf_bars_msgs[-1].ts
        selected = self._join(ctf_by_ts, own_bar_ts)
        assert selected == ctf_by_ts[own_bar_ts], (
            "1d self-referential join must resolve to the bar's own value, not a prior "
            "day's -- re-keying this case would be a regression, not a fix"
        )
