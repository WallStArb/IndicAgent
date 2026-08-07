"""FeatureCache — mutable state container for slow-changing features.

Holds regime-level, session-level, cross-asset, and CTF state that
compute() reads per bar. Updated by the caller (IntelligencePipeline or
backfill job), never mutated inside FeatureFactory.compute().

Cross-asset proxy instruments (D-08, confirmed at planning time):
- vix_z: SPY trailing realized volatility z-score (VXX/VIXY absent from the
  58-ETF universe; SPY realized-vol is the available proxy).
- flight_quality: TLT/SPY relative-return divergence (positive = risk-off).
- yield_slope_z: z-score of TLT/SHY return ratio (2Y-10Y curve proxy).
All three are populated via update_cross_asset() and read by compute().
Phase 138 IC will judge these proxies.
"""

from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import numpy as np

from src.core.bar_accumulator import _RTH_CLOSE_ET, _RTH_OPEN_ET
from src.intelligence.context.session_context import _et_from_utc
from src.intelligence.utils import safe_corr

if TYPE_CHECKING:
    from src.intelligence.feature_factory import FeatureFactoryConfig


@dataclass
class FeatureCache:
    """Mutable state container for FeatureFactory.compute().

    Regime-level fields are refreshed every regime_cache_refresh_bars bars
    via refresh_regime(). CTF fields are updated when an HTF bar arrives.
    Cross-asset fields are updated via update_cross_asset(). Session-level
    fields are reset at session open by the caller.
    """

    # Regime-level (refreshed every N bars via refresh_regime())
    hmm_regime_prob: float = 0.0
    hmm_entropy: float = 0.0
    hurst: float = 0.5
    shannon: float = 1.0
    garch_ratio: float = 1.0
    hma_slope_z: float = 0.0
    adx: float = 0.0
    bars_since_regime_refresh: int = 0

    # Cross-asset cached from cross-asset ETF bars (updated via update_cross_asset()).
    # Same 5 fields, same _compute_cross_asset() implementation, as CrossAssetState
    # below (see that class's docstring for why the fields are declared twice instead
    # of shared via inheritance).
    vix_z: float = 0.0  # SPY realized-vol proxy (VXX/VIXY absent from universe)
    flight_quality: float = 0.0  # TLT/SPY divergence
    yield_slope_z: float = 0.0  # TLT/SHY ratio z-score
    _spy_realized_vol_history: deque = field(default_factory=lambda: deque(maxlen=500), repr=False)
    _yield_ratio_history: deque = field(default_factory=lambda: deque(maxlen=500), repr=False)
    # Cross-asset — Spread/Beta Atomics (Phase 151 Plan 04, todos 123/180).
    # tip_tlt_ret_z/hyg_lqd_ret_z/sb_corr_* are symbol-independent, same
    # update_cross_asset() broadcast mechanism as the 3 fields above.
    # equity_beta_z/rate_beta_z default None here (per FeatureVector's own
    # contract: None means "not measured", never a fake numeric placeholder --
    # schemas.py's docstring is explicit that a self-regression beta is
    # nullable BY DESIGN). No SPY/TLT special-case is needed at cache level
    # (unlike the other symbol-independent fields above): None is already the
    # correct value for every symbol until the live-path wiring lands (batch:
    # _build_symbol_beta_series; live: not yet wired, plan 151-09 left this
    # explicitly out of scope, see todo 264). Previously defaulted to 0.0,
    # which fabricated a fake "zero beta" indistinguishable from a genuine
    # measurement on every live-serving row (code review WR-03, Phase 151
    # post-execution review).
    tip_tlt_ret_z: float = 0.0
    hyg_lqd_ret_z: float = 0.0
    sb_corr_fast: float = 0.0
    sb_corr_slow: float = 0.0
    sb_corr_z: float = 0.0
    equity_beta_z: float | None = None
    rate_beta_z: float | None = None
    # maxlen=2520 matches the true APR ceiling for each backing zscore_window
    # key (migration 289: feature.tip_tlt/hyg_lqd/sb_corr/factor_beta.zscore_window,
    # all max_value=2520) -- a smaller maxlen would silently truncate the live
    # path below whatever an ML tuner configures, while the batch path
    # (build_cross_asset_series) always sizes to the full configured window.
    # Same bug class this codebase already found and fixed once (migration
    # 256, CR-02); code review WR-02, Phase 151 post-execution review.
    _tip_tlt_ratio_history: deque = field(default_factory=lambda: deque(maxlen=2520), repr=False)
    _hyg_lqd_ratio_history: deque = field(default_factory=lambda: deque(maxlen=2520), repr=False)
    _sb_corr_history: deque = field(default_factory=lambda: deque(maxlen=2520), repr=False)
    _equity_beta_history: deque = field(default_factory=lambda: deque(maxlen=2520), repr=False)
    _rate_beta_history: deque = field(default_factory=lambda: deque(maxlen=2520), repr=False)
    # sb_corr_fast/slow need SPY/TLT's own raw log-return history to compute a
    # rolling correlation (Rule 2 addition beyond the plan's literal 5-deque
    # list -- the correlation is structurally uncomputable without persisting
    # the return series somewhere; documented as a deviation in the SUMMARY).
    _sb_spy_log_ret_history: deque = field(default_factory=lambda: deque(maxlen=500), repr=False)
    _sb_tlt_log_ret_history: deque = field(default_factory=lambda: deque(maxlen=500), repr=False)

    # CTF from HTF cached state (populated when HTF bar arrives)
    ctf_momentum: float = 0.0
    ctf_vwap_align: float = 0.0
    ctf_regime_align: float = 0.0

    # HMM duration and weekly VWAP (updated by caller per bar)
    hmm_duration: float = 0.0  # bars in current HMM discrete regime state
    above_wk_vwap: float = 0.0  # 1.0 if close > weekly VWAP, else 0.0

    # Session-level VP (reset at session open by caller)
    poc_dist_atr: float = 0.0
    va_position: float = 0.5
    sr_support_dist: float = 0.0
    sr_resist_dist: float = 0.0

    # AMD Cycle state (Phase 164), populated by update_overnight_range().
    # amd_phase is NOT cached here -- it's derived statelessly from bar_ts
    # via _amd_phase_ordinal() in feature_factory.py, with no cache read.
    # RAW state here: amd_manipulation_detected/amd_distribution_direction/
    # manip_strength are set unclamped by the mutator per 164-RESEARCH.md.
    amd_manipulation_detected: float = 0.0
    amd_distribution_direction: float = 0.0
    manip_strength: float = 0.0

    # Internal rolling history for regime features (HMA, ADX z-score)
    _hma_slope_history: deque = field(default_factory=lambda: deque(maxlen=500), repr=False)
    _adx_raw_history: deque = field(default_factory=lambda: deque(maxlen=500), repr=False)

    # Internal state for hmm_duration tracking
    _hmm_regime_label: int = field(default=-1, repr=False)

    # Internal accumulators for weekly VWAP
    _wk_tp_vol_sum: float = field(default=0.0, repr=False)
    _wk_vol_sum: float = field(default=0.0, repr=False)
    _wk_year_week: tuple = field(default=(-1, -1), repr=False)  # (iso_year, iso_week)

    # Internal accumulators for weekly high/low/close + prior-completed-week
    # snapshot (Phase 165 Plan 04, D-09). Extends update_wk_vwap()'s existing
    # _wk_year_week reset block rather than building a second parallel
    # weekly-boundary mechanism -- these three run alongside
    # _wk_tp_vol_sum/_wk_vol_sum and reset on the same ISO-week transition.
    # _prior_wk_* are the PRIOR COMPLETED week's snapshot (pivot-point
    # convention: never the week in progress, which would be partially
    # self-referential via its own close) -- None until a first full week
    # has rolled over.
    _wk_high: float | None = field(default=None, repr=False)
    _wk_low: float | None = field(default=None, repr=False)
    _wk_close: float | None = field(default=None, repr=False)
    _prior_wk_high: float | None = field(default=None, repr=False)
    _prior_wk_low: float | None = field(default=None, repr=False)
    _prior_wk_close: float | None = field(default=None, repr=False)

    # Internal accumulators for AMD overnight-range tracking (Phase 164 Plan 01,
    # analogous to the weekly-VWAP accumulators above). _overnight_day is the
    # calendar date (UTC) on which the current accumulation cycle began -- see
    # update_overnight_range() for the cycle-key derivation.
    _overnight_high: float | None = field(default=None, repr=False)
    _overnight_low: float | None = field(default=None, repr=False)
    _overnight_day: object = field(default=None, repr=False)

    # Internal accumulator for session volume profile (Phase 163 Plan 01, D-03).
    # Non-incremental: the full histogram is recomputed over these accumulated
    # bars on every update_session_vp() call (sidesteps market_profile.py's
    # unbounded-accumulator bug, D-01). Reset at the NY session boundary.
    _sess_bars: list = field(default_factory=list, repr=False)  # [(high, low, close, volume), ...]
    _session_day: object = field(default=None, repr=False)  # ET calendar date of current session

    # Internal RAW-level session-VP results (NOT FeatureVector fields — D-16
    # forbids persisting raw price levels; Plan 02 derives ATR-distance outputs
    # from these plus the compute-path atr_val).
    _sess_poc: float | None = field(default=None, repr=False)
    _sess_vah: float | None = field(default=None, repr=False)
    _sess_val: float | None = field(default=None, repr=False)
    _sess_hvn_above: float | None = field(default=None, repr=False)
    _sess_hvn_below: float | None = field(default=None, repr=False)
    _sess_lvn_above: float | None = field(default=None, repr=False)
    _sess_lvn_below: float | None = field(default=None, repr=False)
    _sess_hvn_nearest: float | None = field(default=None, repr=False)  # legacy nearest_hvn_level
    _sess_price_in_va: float = field(default=0.0, repr=False)
    _sess_in_lvn: float = field(default=0.0, repr=False)

    # Internal state for session_levels.py's D-08 rewrite (Phase 165 Plan 04).
    # NEVER FeatureVector fields -- Plan 05 derives the 16 ATR-normalized/
    # bounded session_levels columns from this raw state in compute(); no
    # atr_val is available in a mutator (same division of labour as
    # update_session_vp()/_derive_session_vp()).
    #
    # _sl_overnight_high/_sl_overnight_low track a DIFFERENT window from
    # Phase 164's _overnight_high/_overnight_low/_overnight_day (the AMD
    # 20:00-UTC accumulation-phase window): this is the ET non-RTH block of
    # bars between one session close and the next session open. The two are
    # deliberately tracked separately, never unified -- sharing state between
    # two conceptually different "overnight" windows would silently corrupt
    # both.
    #
    # _sl_session_day is a separate key from Phase 163's _session_day for the
    # same reason: two mutators sharing one boundary key would each see "no
    # change" after the other flips it first, silently breaking both resets.
    _sl_session_day: object = field(default=None, repr=False)  # ET session day key
    _sl_session_open: float | None = field(
        default=None, repr=False
    )  # open of first bar this session day
    _sl_session_high: float | None = field(default=None, repr=False)  # running high since that open
    _sl_session_low: float | None = field(default=None, repr=False)  # running low since that open
    _sl_session_close: float | None = field(
        default=None, repr=False
    )  # latest close within current session day
    _sl_prior_session_high: float | None = field(default=None, repr=False)
    _sl_prior_session_low: float | None = field(default=None, repr=False)
    _sl_prior_session_close: float | None = field(default=None, repr=False)
    _sl_gap_filled: float = field(default=0.0, repr=False)  # D-13 latch, reset each session day
    _sl_on_acc_high: float | None = field(
        default=None, repr=False
    )  # running non-RTH accumulator, current block
    _sl_on_acc_low: float | None = field(default=None, repr=False)
    _sl_overnight_high: float | None = field(
        default=None, repr=False
    )  # frozen at last completed session rollover
    _sl_overnight_low: float | None = field(default=None, repr=False)
    _sl_asia_day: object = field(
        default=None, repr=False
    )  # ET date the current Asian block started
    _sl_asia_high: float | None = field(default=None, repr=False)
    _sl_asia_low: float | None = field(default=None, repr=False)

    def refresh_regime(self, bars: list[dict], config: FeatureFactoryConfig) -> None:
        """Recompute regime-level features from bars and update cache.

        Called by the pipeline every config.regime_cache_refresh_bars bars.
        Extracts forward-only cores (no backward smoother, D-07).

        Parameters
        ----------
        bars:
            Full bar history available to the pipeline (list of OHLCV dicts).
        config:
            Frozen config with all tunable parameters from APR.
        """
        if len(bars) < config.min_bars_warmup:
            self.bars_since_regime_refresh = 0
            return

        closes = np.array([b["close"] for b in bars], dtype=float)
        highs = np.array([b["high"] for b in bars], dtype=float)
        lows = np.array([b["low"] for b in bars], dtype=float)

        # --- Hurst exponent (R/S analysis, forward-only) ---
        window = min(config.hurst_window, len(closes))
        self.hurst = _hurst_rs(closes[-window:])

        # --- Shannon entropy of log-return distribution ---
        self.shannon = _shannon_entropy(closes)

        # --- GARCH(1,1) sigma / realized vol ratio ---
        self.garch_ratio = _garch_ratio(closes, config.garch_window)

        # hmm_regime_prob/hmm_entropy/hmm_duration deliberately NOT computed here
        # (removed 2026-07-30, todo 207): this K=3 forward-filter HMM had zero
        # live consumer once FeatureFactory stopped echoing it into FeatureVector
        # -- regime_writer.py's fitted, BIC-selected K=5 HMM is the sole writer
        # of those 3 columns. Running a full-history forward pass every
        # regime_cache_refresh_bars cycle for a value nobody read was pure waste
        # (the mechanism this removed: _hmm_forward_2d, a Python-loop
        # forward-algorithm pass over the entire close series -- its lower-level
        # helper _hmm_forward_step is kept, still used by
        # backfill_feature_factory.py's unrelated ctf_regime_align computation).
        # self.hmm_regime_prob/hmm_entropy remain declared on FeatureCache at
        # their dataclass defaults, permanently inert. self.hmm_duration and
        # self._hmm_regime_label are ALSO now inert, but not "at their default"
        # in the same sense -- advance_bar() no longer increments hmm_duration
        # (its only reset, on regime-state change, lived here and was removed
        # the same day) and _hmm_regime_label is simply never written again.
        # All 4 kept declared (not deleted) to bound this change's blast radius
        # to the compute engine; safe to delete outright in a future pass.

        # --- HMA slope z-score ---
        hma_val = _hma(closes, config.hma_period)
        hma_prev = _hma(closes[:-1], config.hma_period)
        if math.isfinite(hma_val) and math.isfinite(hma_prev):
            slope = hma_val - hma_prev
            self._hma_slope_history.append(slope)
        self.hma_slope_z = _zscore_from_deque(
            self._hma_slope_history,
            config.momentum_zscore_window,
        )

        # --- ADX (raw value, 0-100) ---
        adx_val = _adx(highs, lows, closes, config.adx_period)
        self.adx = adx_val

        self.bars_since_regime_refresh = 0

    def update_wk_vwap(
        self,
        bar_ts: datetime,
        high: float,
        low: float,
        close: float,
        volume: float,
    ) -> None:
        """Update weekly VWAP state and set above_wk_vwap from current bar.

        Resets accumulators at ISO week boundary. Called by the pipeline or backfill
        once per bar, after FeatureFactory.compute().

        Also tracks weekly high/low/close and the prior-completed-week
        snapshot (Phase 165 Plan 04, D-09) inside this SAME reset block,
        rather than building a second parallel weekly-boundary mechanism.
        Two points a future reader needs:

        - Weekly pivot levels are derived (in Plan 05) from the PRIOR
          COMPLETED week's high/low/close, not the week in progress. Using
          the running week would make the pivot partially self-referential
          (its `close` component is the current bar) and would re-anchor
          intraweek; prior-week anchoring is the standard pivot-point
          convention and is causally clean.
        - update_wk_vwap() is called from advance_bar(), which runs AFTER
          compute(). On the first bar of a new ISO week, compute() therefore
          still reads the week-before-last's snapshot -- a one-bar LAG at
          each week boundary. This is accepted deliberately: a lag can only
          ever withhold information, never leak future information, so it is
          the safe direction. Do not "fix" it by moving the weekly reset
          into a pre-compute mutator; that would duplicate the ISO-week
          boundary mechanism D-09 exists to prevent.
        """
        iso = bar_ts.isocalendar()
        year_week = (iso.year, iso.week)
        if year_week != self._wk_year_week:
            self._wk_tp_vol_sum = 0.0
            self._wk_vol_sum = 0.0
            self._wk_year_week = year_week
            if self._wk_high is not None:
                self._prior_wk_high = self._wk_high
                self._prior_wk_low = self._wk_low
                self._prior_wk_close = self._wk_close
            self._wk_high = None
            self._wk_low = None
            self._wk_close = None
        self._wk_high = high if self._wk_high is None else max(self._wk_high, high)
        self._wk_low = low if self._wk_low is None else min(self._wk_low, low)
        self._wk_close = close
        typical = (high + low + close) / 3.0
        self._wk_tp_vol_sum += typical * volume
        self._wk_vol_sum += volume
        wk_vwap = self._wk_tp_vol_sum / self._wk_vol_sum if self._wk_vol_sum > 1e-10 else close
        self.above_wk_vwap = float(close > wk_vwap)

    def update_session_vp(
        self,
        bar_ts: datetime,
        high: float,
        low: float,
        close: float,
        volume: float,
        config: FeatureFactoryConfig,
    ) -> None:
        """Update session-anchored volume-profile state (POC/VAH/VAL/HVN/LVN raw levels).

        Ported from ctx_VolumeProfile (D-13), non-incremental by design: recomputes
        the full volume-weighted histogram over the accumulated session bars on every
        call (sidesteps market_profile.py's unbounded-accumulator bug, D-01; matches
        ctx_VolumeProfile's own non-incremental design). Resets the accumulator at the
        NY session boundary using the existing feature.session.ny_start_utc_hour/minute
        APR key (the same UTC-hour comparison _in_ny_session already uses) to detect
        "at/after today's open", combined with the ET calendar date (via _et_from_utc)
        to identify the session -- the exact session-boundary-reset shape as
        update_wk_vwap's ISO-week reset, keyed on ET session day instead. Called once
        per bar by both the live pipeline and backfill (call sites added in Plan 02);
        this mutator computes only -- no ATR-normalized outputs (no atr_val available
        here), Plan 02 derives poc_dist_atr / *_dist_atr / va_width_atr /
        distance_to_vah|val_atr in compute() from the raw levels stored here plus the
        compute-path atr_val.
        """
        ts = bar_ts if bar_ts.tzinfo is not None else bar_ts.replace(tzinfo=UTC)
        et = _et_from_utc(ts)
        # DST-aware by construction (todo 178 WR-02): compares ET wall-clock time directly
        # against 9:30 ET (the session open, a fixed exchange fact -- not a UTC-hour APR
        # value like ny_session_start_utc_hour, which only equals 9:30 ET during EDT and is
        # off by an hour during EST). Unlike _in_ny_session()/_opening_range() (read-only
        # calendar flags where a ~1hr/2x-yearly DST-week discrepancy is an accepted,
        # documented limitation), this comparison gates a STATEFUL accumulator reset
        # (_sess_bars) -- a misfire corrupts VP inputs for the affected bars, not just one
        # flag's value, so this call site gets the DST-correct comparison.
        et_date = et.date()
        session_day = et_date if et.time() >= _RTH_OPEN_ET else et_date - timedelta(days=1)
        if session_day != self._session_day:
            self._sess_bars = []
            self._session_day = session_day

        self._sess_bars.append((float(high), float(low), float(close), float(volume)))

        arr = np.array(self._sess_bars, dtype=float)
        s_high, s_low, s_close, s_volume = arr[:, 0], arr[:, 1], arr[:, 2], arr[:, 3]

        n_buckets = config.session_vp_n_buckets
        profile = _compute_session_vp_profile(s_high, s_low, s_close, s_volume, n_buckets)
        if profile is None:
            self._reset_session_vp_state()
            return

        vol_hist, bucket_prices, bucket_size, price_min = profile
        total_vol = float(vol_hist.sum())
        if total_vol == 0:
            self._reset_session_vp_state()
            return

        poc_price, vah, val = _compute_session_value_area(
            vol_hist, bucket_prices, config.session_vp_value_area_pct
        )
        directional = _compute_session_directional_nodes(
            vol_hist,
            bucket_prices,
            float(close),
            config.session_vp_hvn_threshold,
            config.session_vp_lvn_threshold,
        )

        nonzero = vol_hist[vol_hist > 0]
        if len(nonzero) == 0:
            in_lvn_flag = 0.0
        else:
            vol_threshold_low = float(np.quantile(nonzero, config.session_vp_lvn_threshold))
            cur_bucket = int(np.clip((close - price_min) / bucket_size, 0, n_buckets - 1))
            in_lvn_flag = 1.0 if vol_hist[cur_bucket] <= vol_threshold_low else 0.0

        price_in_va = 1.0 if val is not None and vah is not None and val <= close <= vah else 0.0

        self._sess_poc = poc_price
        self._sess_vah = vah
        self._sess_val = val
        self._sess_hvn_above = directional.get("nearest_hvn_above")
        self._sess_hvn_below = directional.get("nearest_hvn_below")
        self._sess_lvn_above = directional.get("nearest_lvn_above")
        self._sess_lvn_below = directional.get("nearest_lvn_below")
        self._sess_hvn_nearest = directional.get("nearest_hvn_level")
        self._sess_price_in_va = price_in_va
        self._sess_in_lvn = in_lvn_flag

    def _reset_session_vp_state(self) -> None:
        """Clear session-VP raw-level state (degenerate histogram: zero price range or zero volume)."""
        self._sess_poc = None
        self._sess_vah = None
        self._sess_val = None
        self._sess_hvn_above = None
        self._sess_hvn_below = None
        self._sess_lvn_above = None
        self._sess_lvn_below = None
        self._sess_hvn_nearest = None
        self._sess_price_in_va = 0.0
        self._sess_in_lvn = 0.0

    # Retires the archived session_levels.py plugin's bar-count session
    # detection outright (D-07) -- that plugin's three magic-number constants
    # (a 1-minute-bar assumption, wrong on every timeframe v3 actually runs:
    # ~5 sessions of bars at 5m, ~15 sessions at 15m, ~60 sessions/~12 weeks
    # at 1h, ~1.5 years of calendar days at 1d) exist nowhere below; every
    # boundary decision here is timestamp-driven via _et_from_utc +
    # _RTH_OPEN_ET/_RTH_CLOSE_ET instead.
    def update_session_levels(
        self,
        bar_ts: datetime,
        open_: float,
        high: float,
        low: float,
        close: float,
        config: FeatureFactoryConfig,
    ) -> None:
        """Track session/overnight/Asian-block/weekly-adjacent state for session_levels.py's
        D-08 rewrite (Phase 165 Plan 04), timestamp-driven throughout -- NO bar count
        appears anywhere in this method (see the retirement note immediately above
        this method for the three archived constants this replaces and their real
        per-timeframe magnitudes).

        Follows update_session_vp()'s ET-wall-clock session-day derivation exactly
        (same DST-correctness rationale: this gates a STATEFUL accumulator reset, so
        a DST misfire would corrupt state, not just one read-only flag). Never
        raises, on any input (naive datetime, zero prices, a single bar, sparse
        history).

        Overnight here is a DIFFERENT window from Phase 164's AMD
        _overnight_high/_overnight_low/_overnight_day (the 20:00-UTC accumulation
        phase): this is the ET non-RTH block of bars between one session's close
        and the next session's open. The two windows are deliberately tracked
        separately via the _sl_ prefix -- see the field-block comment above.

        ATR-normalized outputs (the 16 FeatureVector columns) are derived in
        compute() by Plan 05, never here -- no atr_val is available in a mutator,
        the same division of labour as update_session_vp()/_derive_session_vp().
        """
        ts = bar_ts if bar_ts.tzinfo is not None else bar_ts.replace(tzinfo=UTC)
        et = _et_from_utc(ts)
        et_date = et.date()
        session_day = et_date if et.time() >= _RTH_OPEN_ET else et_date - timedelta(days=1)
        in_rth = _RTH_OPEN_ET <= et.time() < _RTH_CLOSE_ET

        if session_day != self._sl_session_day:
            if self._sl_session_day is not None:
                self._sl_prior_session_high = self._sl_session_high
                self._sl_prior_session_low = self._sl_session_low
                self._sl_prior_session_close = self._sl_session_close
                if self._sl_on_acc_high is not None:
                    self._sl_overnight_high = self._sl_on_acc_high
                    self._sl_overnight_low = self._sl_on_acc_low
            self._sl_on_acc_high = None
            self._sl_on_acc_low = None
            self._sl_gap_filled = 0.0
            self._sl_session_open = open_
            self._sl_session_high = high
            self._sl_session_low = low
            self._sl_session_day = session_day
        else:
            self._sl_session_high = (
                high if self._sl_session_high is None else max(self._sl_session_high, high)
            )
            self._sl_session_low = (
                low if self._sl_session_low is None else min(self._sl_session_low, low)
            )
        self._sl_session_close = close

        if not in_rth:
            self._sl_on_acc_high = (
                high if self._sl_on_acc_high is None else max(self._sl_on_acc_high, high)
            )
            self._sl_on_acc_low = (
                low if self._sl_on_acc_low is None else min(self._sl_on_acc_low, low)
            )

        if (
            self._sl_prior_session_close is not None
            and self._sl_session_low is not None
            and self._sl_session_high is not None
            and self._sl_session_low <= self._sl_prior_session_close <= self._sl_session_high
        ):
            self._sl_gap_filled = 1.0

        asia_start = config.session_levels_asia_start_et_hour
        asia_end = config.session_levels_asia_end_et_hour
        if et.hour >= asia_start or et.hour < asia_end:
            asia_day = et_date if et.hour >= asia_start else et_date - timedelta(days=1)
            if asia_day != self._sl_asia_day:
                self._sl_asia_high = None
                self._sl_asia_low = None
                self._sl_asia_day = asia_day
            self._sl_asia_high = (
                high if self._sl_asia_high is None else max(self._sl_asia_high, high)
            )
            self._sl_asia_low = low if self._sl_asia_low is None else min(self._sl_asia_low, low)

    def advance_bar(
        self,
        bar_ts: datetime,
        high: float,
        low: float,
        close: float,
        volume: float,
    ) -> None:
        """Update all per-bar mutable state after FeatureFactory.compute().

        Called once per bar by the pipeline and backfill. Encapsulates:
        - Weekly VWAP accumulation and above_wk_vwap flag

        hmm_duration counter increment removed 2026-07-30 (todo 207): its only
        reset (on HMM state change, in refresh_regime()) was removed the same
        day as dead compute, so incrementing without ever resetting would have
        made this a monotonically-increasing counter forever rather than
        staying inert like the other 2 removed hmm_* fields.
        """
        self.update_wk_vwap(bar_ts, high, low, close, volume)

    def update_cross_asset(
        self,
        spy_bars: list[dict],
        tlt_bars: list[dict],
        shy_bars: list[dict],
        tip_bars: list[dict],
        hyg_bars: list[dict],
        lqd_bars: list[dict],
        config: FeatureFactoryConfig,
    ) -> None:
        """Populate vix_z/flight_quality/yield_slope_z plus Phase 151 Plan 04's 5
        symbol-independent cross-asset additions from available ETF OHLCV bars.

        Called when cross-asset HTF bars arrive. All features are computed from
        OHLCV only -- no tick data, no live frames injection. The original 3
        fields delegate to _compute_cross_asset(), the sole implementation of
        that math (shared with CrossAssetState below, which is deliberately
        NOT extended with this plan's 5 new fields -- CrossAssetState exists
        for callers needing only the original 3, see its class docstring).
        tip_tlt_ret_z/hyg_lqd_ret_z are structural copies of the yield_slope_z
        block above (pairwise log-return spread, z-scored over their own
        distinct APR window -- never config.yield_curve_zscore_window, per
        todo 123's review). sb_corr_fast/slow/z are a rolling Pearson
        correlation between SPY and TLT log returns, theory-free like
        hurst/skewness (no directional interpretation attached to sign).
        equity_beta_z/rate_beta_z are NOT touched here -- they are per-symbol
        and populated by a different mechanism (batch:
        _build_symbol_beta_series; live: not yet wired, plan 151-09).

        Parameters
        ----------
        spy_bars: SPY bar history (for vix_z proxy, flight_quality, sb_corr)
        tlt_bars: TLT bar history (for flight_quality, yield_slope_z, sb_corr)
        shy_bars: SHY bar history (for yield_slope_z)
        tip_bars: TIP bar history (for tip_tlt_ret_z)
        hyg_bars: HYG bar history (for hyg_lqd_ret_z)
        lqd_bars: LQD bar history (for hyg_lqd_ret_z)
        config: Frozen FeatureFactoryConfig with zscore windows
        """
        _compute_cross_asset(self, spy_bars, tlt_bars, shy_bars, config)

        # tip_tlt_ret_z: structural copy of the yield_slope_z block in
        # _compute_cross_asset() above -- pairwise log-return spread,
        # z-scored over its OWN distinct window (never yield_curve_zscore_window).
        if len(tip_bars) >= 2 and len(tlt_bars) >= 2:
            n = min(len(tip_bars), len(tlt_bars))
            tip_closes = np.array([b["close"] for b in tip_bars[-n:]], dtype=float)
            tlt_closes = np.array([b["close"] for b in tlt_bars[-n:]], dtype=float)
            tip_rets = np.diff(np.log(np.maximum(tip_closes, 1e-10)))
            tlt_rets = np.diff(np.log(np.maximum(tlt_closes, 1e-10)))
            min_len = min(len(tip_rets), len(tlt_rets))
            if min_len > 0:
                ratio = float(tip_rets[-1]) - float(tlt_rets[-1])
                self._tip_tlt_ratio_history.append(ratio)
            self.tip_tlt_ret_z = _zscore_from_deque(
                self._tip_tlt_ratio_history, config.tip_tlt_zscore_window
            )

        # hyg_lqd_ret_z: same structural copy, HYG/LQD instead of TIP/TLT.
        if len(hyg_bars) >= 2 and len(lqd_bars) >= 2:
            n = min(len(hyg_bars), len(lqd_bars))
            hyg_closes = np.array([b["close"] for b in hyg_bars[-n:]], dtype=float)
            lqd_closes = np.array([b["close"] for b in lqd_bars[-n:]], dtype=float)
            hyg_rets = np.diff(np.log(np.maximum(hyg_closes, 1e-10)))
            lqd_rets = np.diff(np.log(np.maximum(lqd_closes, 1e-10)))
            min_len = min(len(hyg_rets), len(lqd_rets))
            if min_len > 0:
                ratio = float(hyg_rets[-1]) - float(lqd_rets[-1])
                self._hyg_lqd_ratio_history.append(ratio)
            self.hyg_lqd_ret_z = _zscore_from_deque(
                self._hyg_lqd_ratio_history, config.hyg_lqd_zscore_window
            )

        # sb_corr_fast/slow/z: rolling Pearson correlation between SPY and TLT
        # log returns. Theory-free (same class as hurst/skewness) -- no
        # directional interpretation attached to the sign, here or in
        # formula_short. The deque accumulates the FAST value only (per plan);
        # sb_corr_z z-scores that fast-window series.
        if len(spy_bars) >= 2 and len(tlt_bars) >= 2:
            n = min(len(spy_bars), len(tlt_bars))
            spy_closes = np.array([b["close"] for b in spy_bars[-n:]], dtype=float)
            tlt_closes = np.array([b["close"] for b in tlt_bars[-n:]], dtype=float)
            spy_rets = np.diff(np.log(np.maximum(spy_closes, 1e-10)))
            tlt_rets = np.diff(np.log(np.maximum(tlt_closes, 1e-10)))
            min_len = min(len(spy_rets), len(tlt_rets))
            if min_len > 0:
                self._sb_spy_log_ret_history.append(float(spy_rets[-1]))
                self._sb_tlt_log_ret_history.append(float(tlt_rets[-1]))
                fast_n = min(config.sb_corr_window_fast, len(self._sb_spy_log_ret_history))
                slow_n = min(config.sb_corr_window_slow, len(self._sb_spy_log_ret_history))
                spy_arr = np.array(self._sb_spy_log_ret_history)
                tlt_arr = np.array(self._sb_tlt_log_ret_history)
                self.sb_corr_fast = safe_corr(spy_arr[-fast_n:], tlt_arr[-fast_n:])
                self.sb_corr_slow = safe_corr(spy_arr[-slow_n:], tlt_arr[-slow_n:])
                self._sb_corr_history.append(self.sb_corr_fast)
                self.sb_corr_z = _zscore_from_deque(
                    self._sb_corr_history, config.sb_corr_zscore_window
                )

    def update_overnight_range(
        self,
        bar_ts: datetime,
        high: float,
        low: float,
        config: FeatureFactoryConfig,
    ) -> None:
        """Track the AMD accumulation-phase overnight high/low with UTC boundary reset.

        Ported from AMDCyclePlugin (src/intelligence/archive/smc_context/amd_cycle.py),
        ICT Accumulation/Manipulation/Distribution cycle: the accumulation phase
        (feature.smc.amd.accum_start_utc_hour, default 20:00 UTC, through end of
        calendar day) builds an overnight high/low range that the manipulation
        phase (00:00 UTC through feature.smc.amd.manip_end_utc_hour, default
        10:00 UTC) then tests via a breach-then-reverse sweep.

        Session-boundary-reset shape follows update_wk_vwap() exactly (D-13
        precedent), keyed on a UTC-hour-derived accumulation-cycle date instead
        of ISO week: bars during accumulation (hour >= accum_start_utc_hour)
        belong to the cycle that started TODAY (UTC date); bars during
        manipulation/distribution (hour < accum_start_utc_hour) belong to the
        cycle that started YESTERDAY (the overnight range formed the prior
        evening). When the cycle key changes, _overnight_high/_overnight_low
        reset and per-cycle flags (amd_manipulation_detected,
        amd_distribution_direction) clear so the next cycle fires fresh —
        matching AMDCyclePlugin's per-day flag reset.

        Manipulation-detection adaptation: this mutator's signature carries only
        high/low (no close), so the archived "breach then close back inside the
        range" reversal test is adapted to an intrabar high/low proxy: an upside
        sweep is high > overnight_high AND low < overnight_high within the SAME
        bar (wicked back below); a downside sweep is the mirror. manip_strength
        is set as the RAW (unclamped) breach-depth ratio — Plan 04's compute()
        derivation applies the [0,1] clamp and the amd_phase ordinal encoding;
        this mutator only tracks overnight range + manipulation-phase transition
        state, per 164-RESEARCH.md Pitfall 3/4.

        All thresholds read from `config` (feature.smc.amd.* APR keys) — zero
        hardcoded constants, per CLAUDE.md's APR mandate.

        NOT YET INVOKED anywhere in this plan — call sites (compute_batch loop,
        live per-bar handler, warm-up replay block) are added in Plan 04
        alongside AMD's compute() derivation.
        """
        ts = bar_ts if bar_ts.tzinfo is not None else bar_ts.replace(tzinfo=UTC)
        hour = ts.hour
        accum_start = config.smc_amd_accum_start_utc_hour
        manip_end = config.smc_amd_manip_end_utc_hour

        # Cycle key: the UTC calendar date on which the current accumulation
        # window began. Accumulation bars (hour >= accum_start) belong to
        # today's cycle; manipulation/distribution bars (hour < accum_start)
        # belong to the cycle that started the PRIOR calendar day.
        cycle_day = ts.date() if hour >= accum_start else (ts.date() - timedelta(days=1))

        if cycle_day != self._overnight_day:
            self._overnight_high = None
            self._overnight_low = None
            self._overnight_day = cycle_day
            self.amd_manipulation_detected = 0.0
            self.amd_distribution_direction = 0.0

        if hour >= accum_start:
            prior_high = self._overnight_high
            prior_low = self._overnight_low
            self._overnight_high = high if prior_high is None else max(prior_high, high)
            self._overnight_low = low if prior_low is None else min(prior_low, low)
            return

        on_high = self._overnight_high
        on_low = self._overnight_low
        if on_high is None or on_low is None:
            return
        on_range = on_high - on_low

        # Manipulation detection only runs during the manipulation-phase window
        # and only once per cycle (matches AMDCyclePlugin's manipulation_done
        # gate) -- once fired, the range is held for the rest of the cycle.
        if hour < manip_end and self.amd_manipulation_detected == 0.0:
            if high > on_high and low < on_high:
                # Upside sweep then wick back inside the range -> bearish distribution expected
                self.amd_manipulation_detected = 1.0
                self.manip_strength = (high - on_high) / on_range if on_range > 0 else 0.0
                self.amd_distribution_direction = -1.0
            elif low < on_low and high > on_low:
                # Downside sweep then wick back inside the range -> bullish distribution expected
                self.amd_manipulation_detected = 1.0
                self.manip_strength = (on_low - low) / on_range if on_range > 0 else 0.0
                self.amd_distribution_direction = 1.0


# ---------------------------------------------------------------------------
# Cross-asset broadcast state (todo 222) -- a minimal sibling of FeatureCache for
# callers that need only vix_z/flight_quality/yield_slope_z (e.g.
# feature_vector_pipeline.py's shared per-tf broadcast state, computed once per
# genuinely-new SPY/TLT/SHY bar and copied onto every symbol's own FeatureCache)
# rather than paying for FeatureCache's other ~87 unrelated fields. Declares the
# same 5 fields as FeatureCache directly (not shared via inheritance -- 5 field
# declarations is cheaper than a dedicated base class); update_cross_asset() on
# both classes delegates to _compute_cross_asset() below, the one shared
# implementation of the math.
# ---------------------------------------------------------------------------


@dataclass
class CrossAssetState:
    """vix_z/flight_quality/yield_slope_z + the 2 internal histories update_cross_asset()
    needs -- see module comment above for why this exists alongside FeatureCache.
    """

    vix_z: float = 0.0
    flight_quality: float = 0.0
    yield_slope_z: float = 0.0
    _spy_realized_vol_history: deque = field(default_factory=lambda: deque(maxlen=500), repr=False)
    _yield_ratio_history: deque = field(default_factory=lambda: deque(maxlen=500), repr=False)

    def update_cross_asset(
        self,
        spy_bars: list[dict],
        tlt_bars: list[dict],
        shy_bars: list[dict],
        config: FeatureFactoryConfig,
    ) -> None:
        """Populate vix_z/flight_quality/yield_slope_z -- see FeatureCache.update_cross_asset()
        for the parameter contract; both delegate to _compute_cross_asset() below."""
        _compute_cross_asset(self, spy_bars, tlt_bars, shy_bars, config)


def _compute_cross_asset(
    state: FeatureCache | CrossAssetState,
    spy_bars: list[dict],
    tlt_bars: list[dict],
    shy_bars: list[dict],
    config: FeatureFactoryConfig,
) -> None:
    """Compute vix_z/flight_quality/yield_slope_z onto `state` from ETF OHLCV bars.

    Shared implementation behind both FeatureCache.update_cross_asset() and
    CrossAssetState.update_cross_asset(). See either method's docstring for the
    parameter contract.
    """
    window = config.vix_zscore_window

    # vix_z: SPY trailing realized volatility z-score (proxy for VIX)
    if len(spy_bars) >= 2:
        spy_closes = np.array([b["close"] for b in spy_bars], dtype=float)
        spy_returns = np.diff(np.log(np.maximum(spy_closes, 1e-10)))
        rv_window = min(config.cross_asset_rv_window, len(spy_returns))
        realized_vol = float(np.std(spy_returns[-rv_window:]))
        state._spy_realized_vol_history.append(realized_vol)
        state.vix_z = _zscore_from_deque(state._spy_realized_vol_history, window)

    # flight_quality: TLT/SPY relative-return divergence (positive = risk-off)
    if len(tlt_bars) >= 2 and len(spy_bars) >= 2:
        n = min(len(tlt_bars), len(spy_bars))
        tlt_closes = np.array([b["close"] for b in tlt_bars[-n:]], dtype=float)
        spy_closes_n = np.array([b["close"] for b in spy_bars[-n:]], dtype=float)
        tlt_ret = float(tlt_closes[-1] / tlt_closes[0] - 1.0) if tlt_closes[0] > 0 else 0.0
        spy_ret = float(spy_closes_n[-1] / spy_closes_n[0] - 1.0) if spy_closes_n[0] > 0 else 0.0
        state.flight_quality = tlt_ret - spy_ret

    # yield_slope_z: TLT/SHY return ratio z-score (2Y-10Y proxy)
    yzw = config.yield_curve_zscore_window
    if len(tlt_bars) >= 2 and len(shy_bars) >= 2:
        n = min(len(tlt_bars), len(shy_bars))
        tlt_closes = np.array([b["close"] for b in tlt_bars[-n:]], dtype=float)
        shy_closes = np.array([b["close"] for b in shy_bars[-n:]], dtype=float)
        tlt_rets = np.diff(np.log(np.maximum(tlt_closes, 1e-10)))
        shy_rets = np.diff(np.log(np.maximum(shy_closes, 1e-10)))
        min_len = min(len(tlt_rets), len(shy_rets))
        if min_len > 0:
            ratio = float(tlt_rets[-1]) - float(shy_rets[-1])
            state._yield_ratio_history.append(ratio)
        state.yield_slope_z = _zscore_from_deque(state._yield_ratio_history, yzw)


# ---------------------------------------------------------------------------
# Pure computation helpers (used by update_session_vp) — ported from
# src/intelligence/context/volume_profile.py (ctx_VolumeProfile, D-13). Logic is
# unchanged from the source plugin's _compute_profile / _compute_value_area /
# _compute_directional_nodes; only the previously-hardcoded constants
# (_N_BUCKETS/_HVN_THRESHOLD/_LVN_THRESHOLD) are now explicit parameters sourced
# from FeatureFactoryConfig (APR contract) instead of module-level constants.
# ---------------------------------------------------------------------------


def _compute_session_vp_profile(
    high: np.ndarray,
    low: np.ndarray,
    close_arr: np.ndarray,
    volume: np.ndarray,
    n_buckets: int,
) -> tuple[np.ndarray, np.ndarray, float, float] | None:
    """Build a volume-weighted price histogram over the given bars.

    Returns (vol_hist, bucket_prices, bucket_size, price_min), or None when the
    session's high-low range is degenerate (zero width).
    """
    typical = (high + low + close_arr) / 3.0
    price_min = float(low.min())
    price_max = float(high.max())
    price_range = price_max - price_min
    if price_range <= 0:
        return None
    bucket_size = price_range / n_buckets
    bucket_idx = np.clip(
        ((typical - price_min) / bucket_size).astype(int),
        0,
        n_buckets - 1,
    )
    vol_hist = np.bincount(bucket_idx, weights=volume, minlength=n_buckets)
    bucket_prices = price_min + (np.arange(n_buckets) + 0.5) * bucket_size
    return vol_hist, bucket_prices, bucket_size, price_min


def _compute_session_value_area(
    vol_hist: np.ndarray,
    bucket_prices: np.ndarray,
    value_area_pct: float,
) -> tuple[float | None, float | None, float | None]:
    """Compute POC, VAH, VAL from the histogram via the cumulative-volume rule.

    Bug fix vs. the ported source (ctx_VolumeProfile._compute_value_area, D-13):
    the source breaks ties in `np.argsort(vol_hist)[::-1]` in whatever order the
    (non-stable-for-ties) sort implementation happens to produce, which can place
    the POC's own bucket AFTER the 70%-cumulative-volume cutoff when several
    buckets tie for the maximum volume -- silently violating VAL <= POC <= VAH
    (Rule 1: found during verification via a synthetic round-trip price path that
    produced exact volume ties across ~19 buckets; real OHLCV data rarely ties
    exactly, but a silently-broken invariant is a Renaissance-grade correctness
    bug regardless of how rarely it triggers). Fixed by tie-breaking on distance
    from the POC bucket (closest-to-POC first) via np.lexsort, which guarantees
    the POC's own bucket -- distance 0, the unique minimum -- is always selected
    first, so it is always a member of va_buckets and the invariant always holds.
    """
    total_vol = vol_hist.sum()
    if total_vol == 0:
        return None, None, None
    poc_idx = int(np.argmax(vol_hist))
    poc_price = float(bucket_prices[poc_idx])
    target_vol = total_vol * value_area_pct
    tie_break = np.abs(np.arange(len(vol_hist)) - poc_idx)
    sorted_idx = np.lexsort((tie_break, -vol_hist))
    cumvol = 0.0
    va_buckets: set[int] = set()
    for idx in sorted_idx:
        cumvol += vol_hist[idx]
        va_buckets.add(int(idx))
        if cumvol >= target_vol:
            break
    vah = float(bucket_prices[max(va_buckets)]) if va_buckets else poc_price
    val = float(bucket_prices[min(va_buckets)]) if va_buckets else poc_price
    return poc_price, vah, val


def _compute_session_directional_nodes(
    vol_hist: np.ndarray,
    bucket_prices: np.ndarray,
    close: float,
    hvn_threshold: float,
    lvn_threshold: float,
) -> dict[str, float | None]:
    """Compute directional HVN/LVN (nearest above/below close) and the legacy nearest HVN."""
    nonzero_vols = vol_hist[vol_hist > 0]
    if len(nonzero_vols) == 0:
        return {}
    vol_threshold_high = np.quantile(nonzero_vols, hvn_threshold)
    vol_threshold_low = np.quantile(nonzero_vols, lvn_threshold)

    hvn_mask = vol_hist >= vol_threshold_high
    lvn_mask = (vol_hist > 0) & (vol_hist <= vol_threshold_low)

    result: dict[str, float | None] = {}

    if hvn_mask.any():
        hvn_prices = bucket_prices[hvn_mask]
        hvn_above = hvn_prices[hvn_prices > close]
        hvn_below = hvn_prices[hvn_prices <= close]
        result["nearest_hvn_above"] = float(hvn_above.min()) if len(hvn_above) > 0 else None
        result["nearest_hvn_below"] = float(hvn_below.max()) if len(hvn_below) > 0 else None
        result["nearest_hvn_level"] = float(hvn_prices[np.argmin(np.abs(hvn_prices - close))])
    else:
        result["nearest_hvn_above"] = None
        result["nearest_hvn_below"] = None
        result["nearest_hvn_level"] = None

    if lvn_mask.any():
        lvn_prices = bucket_prices[lvn_mask]
        lvn_above = lvn_prices[lvn_prices > close]
        lvn_below = lvn_prices[lvn_prices <= close]
        result["nearest_lvn_above"] = float(lvn_above.min()) if len(lvn_above) > 0 else None
        result["nearest_lvn_below"] = float(lvn_below.max()) if len(lvn_below) > 0 else None
    else:
        result["nearest_lvn_above"] = None
        result["nearest_lvn_below"] = None

    return result


# ---------------------------------------------------------------------------
# Pure computation helpers (used by refresh_regime)
# ---------------------------------------------------------------------------

# NOTE: the CTF (cross-timeframe) higher-timeframe source mapping formerly lived here
# as a hardcoded module constant (_CTF_HIGHER_TF). Migrated to APR (todo 242, migration
# 305) -- now FeatureFactoryConfig.ctf_higher_tf_map (src/intelligence/feature_factory.py,
# feature.ctf.higher_tf_map). backfill_feature_factory.py and feature_vector_pipeline.py
# both read it from their own FeatureFactoryConfig instance, not from this module.


def _wilder_rsi_series(closes: np.ndarray, period: int) -> np.ndarray:
    """Wilder RSI at every bar index. Length == len(closes). Cold-start entries = 50.0.

    Single source of truth for Wilder smoothing. _rsi_simple is a thin wrapper.
    Used by both the live-path scalar accessor and the batch CTF series builder.
    """
    n = len(closes)
    out = np.full(n, 50.0, dtype=float)
    if n < period + 1:
        return out
    deltas = np.diff(closes.astype(float))
    gains = np.where(deltas > 0, deltas, 0.0)
    losses = np.where(deltas < 0, -deltas, 0.0)
    alpha = 1.0 / period
    avg_gain = float(np.mean(gains[:period]))
    avg_loss = float(np.mean(losses[:period]))
    for i in range(period, len(gains)):
        avg_gain = alpha * float(gains[i]) + (1.0 - alpha) * avg_gain
        avg_loss = alpha * float(losses[i]) + (1.0 - alpha) * avg_loss
        if avg_loss < 1e-10:
            rsi = 100.0 if avg_gain > 0 else 50.0
        else:
            rsi = 100.0 - 100.0 / (1.0 + avg_gain / avg_loss)
        out[i + 1] = float(np.clip(rsi, 0.0, 100.0))
    return out


def _rsi_simple(closes: np.ndarray, period: int) -> float:
    """Terminal Wilder RSI scalar. Thin wrapper over _wilder_rsi_series."""
    return float(_wilder_rsi_series(closes, period)[-1])


def _hurst_rs(close: np.ndarray, min_window: int = 16) -> float:
    """Rescaled range (R/S) estimate of the Hurst exponent.

    Extracted from src/intelligence/context/hurst_exponent.py.
    Returns 0.5 (random walk neutral) on insufficient data or constant series.
    """
    n = len(close)
    if n < min_window:
        return 0.5
    log_returns = np.diff(np.log(np.maximum(close, 1e-10)))
    if len(log_returns) < min_window:
        return 0.5
    mean_r = np.mean(log_returns)
    deviations = np.cumsum(log_returns - mean_r)
    r = float(np.max(deviations) - np.min(deviations))
    s = float(np.std(log_returns, ddof=1))
    if s <= 0 or r <= 0:
        return 0.5
    rs = r / s
    if rs <= 0:
        return 0.5
    return float(min(1.0, max(0.0, np.log(rs) / np.log(n))))


def _shannon_entropy(close: np.ndarray, n_bins: int = 10) -> float:
    """Normalised Shannon entropy of log-return distribution.

    Extracted from src/intelligence/context/shannon_entropy.py.
    Returns 1.0 on insufficient data.
    """
    log_returns = np.diff(np.log(np.maximum(close, 1e-10)))
    if len(log_returns) < 10:
        return 1.0
    valid_returns = log_returns[np.isfinite(log_returns)]
    if len(valid_returns) < 10:
        return 1.0
    counts, _ = np.histogram(valid_returns, bins=n_bins)
    probs = counts / counts.sum()
    probs = probs[probs > 0]
    if len(probs) == 0:
        return 1.0
    raw_entropy = float(-np.sum(probs * np.log2(probs)))
    max_entropy = float(np.log2(n_bins))
    return raw_entropy / max_entropy if max_entropy > 0 else 1.0


def _garch_ratio(close: np.ndarray, window: int) -> float:
    """GARCH(1,1) sigma / realized_vol ratio.

    Simplified extraction from src/intelligence/context/garch_volatility.py.
    Uses default GARCH parameters (omega=0.00001, alpha=0.10, beta=0.85).
    Returns 1.0 on cold start.
    """
    n = min(window, len(close))
    if n < 10:
        return 1.0
    close_w = close[-n:]
    log_returns = np.log(np.maximum(close_w[1:], 1e-10) / np.maximum(close_w[:-1], 1e-10))
    log_returns = np.where(np.isfinite(log_returns), log_returns, 0.0)
    omega, alpha, beta = 0.00001, 0.10, 0.85
    init_w = min(20, len(log_returns))
    sigma2 = float(np.var(log_returns[:init_w]))
    if sigma2 == 0.0:
        denom = 1 - alpha - beta
        sigma2 = omega / denom if denom > 1e-10 else omega
    realized_buf: deque = deque(maxlen=20)
    for r in log_returns:
        sigma2 = omega + alpha * r**2 + beta * sigma2
        realized_buf.append(float(r))
    garch_sigma = math.sqrt(max(sigma2, 0.0))
    realized_vol = float(np.std(list(realized_buf))) if len(realized_buf) >= 2 else garch_sigma
    return garch_sigma / realized_vol if realized_vol > 1e-10 else 1.0


# HMM default parameters (forward-only, 2D). _hmm_forward_2d (the higher-level
# refresh_regime() wrapper) and _hmm_entropy were removed 2026-07-30 (todo 207,
# dead compute -- see refresh_regime()'s comment above), but _hmm_forward_step
# and these 3 arrays + _HMM_K stay: services/backfill_feature_factory.py's
# CTF regime-alignment computation (ctf_regime_align, a live FeatureVector
# field, distinct from the removed hmm_regime_prob/hmm_entropy/hmm_duration)
# imports and calls _hmm_forward_step directly on higher-timeframe bars, a
# genuinely different consumer of the same low-level forward-algorithm step.
_HMM_A = np.array(
    [
        [0.95, 0.025, 0.025],
        [0.03, 0.94, 0.03],
        [0.03, 0.03, 0.94],
    ]
)
_HMM_MEANS_2D = np.array(
    [
        [0.0, 0.005],  # Ranging
        [0.001, 0.008],  # Trending up
        [-0.001, 0.012],  # Trending down
    ]
)
_HMM_VARS_2D = np.array(
    [
        [0.0001, 0.001],
        [0.0002, 0.002],
        [0.0003, 0.003],
    ]
)
_HMM_K = 3


def _hmm_forward_step(obs: np.ndarray, alpha: np.ndarray) -> None:
    """In-place forward algorithm step. No backward smoother (D-07).

    Parameters
    ----------
    obs: 2D observation vector [log_return, realized_vol]
    alpha: K-dim state probability vector (mutated in place)
    """
    means = _HMM_MEANS_2D
    variances = _HMM_VARS_2D
    D = len(obs)
    diff = obs - means  # (K, D)
    log_emit = -0.5 * np.sum(diff * diff / variances, axis=1)
    log_emit -= 0.5 * np.sum(np.log(variances), axis=1)
    log_emit -= 0.5 * D * math.log(2 * math.pi)

    log_alpha = np.log(np.maximum(alpha, 1e-300))
    log_alpha_new = np.zeros(_HMM_K)
    for k in range(_HMM_K):
        log_trans = log_alpha + np.log(np.maximum(_HMM_A[:, k], 1e-300))
        max_lt = float(np.max(log_trans))
        log_alpha_new[k] = max_lt + math.log(float(np.sum(np.exp(log_trans - max_lt))))
    log_alpha_new += log_emit
    # Normalize to get probabilities
    max_val = float(np.max(log_alpha_new))
    unnorm = np.exp(log_alpha_new - max_val)
    total = float(np.sum(unnorm))
    if total > 1e-300:
        alpha[:] = unnorm / total
    else:
        alpha[:] = 1.0 / _HMM_K


def _wma(series: np.ndarray, k: int) -> float:
    """Weighted Moving Average over last k values. Returns NaN if insufficient."""
    if len(series) < k:
        return float("nan")
    tail = series[-k:]
    weights = np.arange(1, k + 1, dtype=float)
    return float(np.dot(weights, tail) / weights.sum())


def _hma(close: np.ndarray, period: int) -> float:
    """Hull Moving Average (current value). Returns NaN on insufficient data."""
    if len(close) < period:
        return float("nan")
    half = period // 2
    sqrt_n = int(round(math.sqrt(period)))
    # Build diff buffer for last sqrt_n bars
    buf: deque = deque(maxlen=sqrt_n)
    start = len(close) - sqrt_n
    if start < period - 1:
        return float("nan")
    for i in range(start, len(close)):
        sub = close[: i + 1]
        wh = _wma(sub, half)
        wf = _wma(sub, period)
        if math.isfinite(wh) and math.isfinite(wf):
            buf.append(2.0 * wh - wf)
    if len(buf) < sqrt_n:
        return float("nan")
    return _wma(np.array(list(buf)), sqrt_n)


def _adx(high: np.ndarray, low: np.ndarray, close: np.ndarray, period: int) -> float:
    """Compute ADX using Wilder's smoothing. Returns 0.0 on insufficient data.

    Simplified extraction from src/intelligence/features/i1_indicators/adx.py.
    """
    n = len(close)
    if n < period * 2 + 1:
        return 0.0
    # True Range
    prev_close = close[:-1]
    curr_high = high[1:]
    curr_low = low[1:]
    tr = np.maximum(
        curr_high - curr_low,
        np.maximum(np.abs(curr_high - prev_close), np.abs(curr_low - prev_close)),
    )
    # Directional movement
    up_move = high[1:] - high[:-1]
    down_move = low[:-1] - low[1:]
    plus_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0.0)
    minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0.0)
    # Wilder's smoothing
    alpha = 1.0 / period
    sm_tr = float(np.sum(tr[:period]))
    sm_plus = float(np.sum(plus_dm[:period]))
    sm_minus = float(np.sum(minus_dm[:period]))
    dx_vals: list[float] = []
    for i in range(period, len(tr)):
        sm_tr = sm_tr - sm_tr / period + float(tr[i])
        sm_plus = sm_plus - sm_plus / period + float(plus_dm[i])
        sm_minus = sm_minus - sm_minus / period + float(minus_dm[i])
        if sm_tr < 1e-10:
            continue
        plus_di = 100.0 * sm_plus / sm_tr
        minus_di = 100.0 * sm_minus / sm_tr
        di_sum = plus_di + minus_di
        if di_sum < 1e-10:
            dx_vals.append(0.0)
        else:
            dx_vals.append(100.0 * abs(plus_di - minus_di) / di_sum)
    if len(dx_vals) < period:
        return 0.0
    adx_val = float(np.mean(dx_vals[-period:]))
    return min(100.0, max(0.0, adx_val))


def _zscore_from_deque(history: deque, window: int) -> float:
    """Compute z-score of most-recent value in deque against rolling window.

    Returns 0.0 if insufficient data or near-zero std.
    """
    if len(history) < window:
        return 0.0
    arr = np.array(list(history)[-window:])
    std = float(arr.std())
    if std < 1e-8:
        return 0.0
    return float((float(history[-1]) - float(arr.mean())) / std)
