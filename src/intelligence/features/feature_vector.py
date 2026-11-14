"""FeatureVector, the per-bar output of the streaming FeatureFactory, and FeatureVectorRecord,
its Kafka envelope. The rebuild writer's row contract
(`features/feature_vector_persistence.py`) takes its field order from FeatureVector.
"""

from __future__ import annotations

import dataclasses
from datetime import datetime


@dataclasses.dataclass(frozen=True)
class FeatureVector:
    """300 orthogonal feature primitives computed per bar by FeatureFactory.
    See the "Groups and field order are binding" breakdown below (ends in
    "Total: 300") for full group-by-group provenance -- that breakdown is
    the maintained source of truth; keep it (not this line) in sync when
    fields are added.

    Frozen dataclass (not Pydantic) per D-08: pure-function output, no IO,
    immutable after construction. Numeric fields are `float | None` and
    most have no default, so every field must be supplied by the caller; a
    value that cannot be computed is None (no_fill), never a fallback. A
    numeric placeholder for
    "insufficient data" (e.g. the archived plugins' trend_direction=0.0,
    price_position=0.5) is exactly the todo-153 silent-wrong-answer failure
    mode this codebase already paid to discover once; None means "not
    measured," never a fake measurement. The 3 Optional cross-sectional
    fields are ranks that were never implemented — always None (todo 103).

    Groups and field order are binding (schema column names in feature_vectors):
      Momentum (7): fast/mid/slow return z-scores, range, intra-bar close position, gap, reversal z
      Volume/flow (8): informed flow, volume, OFI, OFI divergence, CVD slope, CMF, rel volume, VWAP dev
      Volatility (2): ATR z-score, short/long vol ratio
      Session-level (21, 4 original + 17 Phase 163 Plan 01): volume profile POC/VA,
        S/R proximity, directional HVN/LVN ATR-distances, value-area width/bounds,
        rolling-track POC divergence, S/R cluster strength/age/count (D-13/D-16/D-17/D-18/D-19)
      Regime-level (10): HMM prob/entropy/duration, Hurst, Shannon, GARCH ratio, HMA slope, ADX, Aroon fast/slow
      Oscillators (6): RSI and CCI at fast/mid/slow scales
      Cross-asset (10: 3 original + 7 Phase 151 Plan 04): VIX z-score, flight-to-quality,
        yield slope, TIP/TLT and HYG/LQD spread z-scores, stock-bond correlation
        fast/slow/z, equity/rate factor betas (2 nullable, see field comments)
      Named Interaction Primitives (5, Phase 151 Plan 05, todos 066/104): the 5
        pre-specified, Fable-reviewed tier-1 interaction candidates -- 2 cross-TF
        return divergences (ret_div_5m_1h/1h_1d, nullable + timeframe-pinned,
        see field comments) + 2 calendar event flags (opex_flag, quad_witching_flag,
        non-nullable, no market-holiday table by design)
      Theory-Motivated Interactions (10, Phase 151 Plan 06): momentum_vol_regime_product,
        momentum_trend_product, breakout_volume_product, reversion_hurst_product,
        quarter_momentum_product, variance_ratio_momentum_product, illiquidity_momentum_product,
        yield_slope_momentum_product, vix_reversion_product, efficiency_volume_product --
        10 curated compound features, each a single product of two tier-0 columns with a
        stated finance-theory hypothesis (see field comments); missing when a parent is, and a
        non-finite product of finite parents is missing too, counted by _guard_counted
      Calendar (17: 11 original + 6 Phase 151 Plan 01 Task 1): NY/London session, overlap, power hour, opening range, weekly VWAP, dow sin/cos, month position, quarter position, days to month end, quarter cycle sin/cos, TDOM sin/cos, minute-of-hour sin/cos
      Velocity Primitives (4, Phase 151 Plan 01 Task 2): momentum_z_velocity_fast/mid/slow, vwap_dev_sigma_velocity -- first-difference-then-re-z-scored construction of an already-computed z-score series (same shape as vol_velocity_z)
      Velocity Primitives Extension (6, todo 320): rsi_velocity_fast/mid/slow, ofi_z_velocity, cvd_slope_z_velocity, volume_z_velocity -- same construction as the 4 fields above, applied to the RSI/OFI/CVD/volume families
      Earnings-Season Calendar Primitive (2, Phase 176 Plan 03, todo 353, migration 350):
        earnings_season_flag (tier-1 event flag, 1.0 iff days_since_quarter_end falls within
        the APR-configured [feature.earnings_season.start_days, feature.earnings_season.end_days]
        window, else 0.0) + days_since_quarter_end (tier-1 continuous companion, raw calendar
        days since the most recent quarter end) -- declared as ONE contiguous run immediately
        after the Velocity Primitives Extension block so feature_vector_persistence.py's
        _EARNINGS_SEASON_FIELD_NAMES derived slice covers exactly this block
      Recency / Statistical Atomics (11, Phase 151 Plan 03, todo 180): bars_since_high/low_fast/slow,
        bars_since_52w_high/low, bars_since_extreme_move_fast/slow, bars_since_vol_spike_fast/slow
        (bars_since_high/low_* and bars_since_52w_* are BOUNDED rolling-window statistics in
        [0, window-1], never expanding; the four event counters are right-censored: None when no
        event is known inside the window, todo 584 rule 2),
        abs_ret_autocorr_1
        (lag-1 autocorrelation of |log returns| -- volatility clustering, distinct from the signed
        ret_autocorr_1 below)
      Cross-timeframe (3): momentum/VWAP/regime alignment from HTF cache
      Statistical/liquidity (4): Amihud illiquidity, 52w high distance, return skewness, return autocorrelation
      Bar Anatomy Ratios (8, Phase 142.5 Plan 01): body/wick ratios, range vs ATR, direction, overnight gap(+z), range efficiency
      Lagged Return Series (6, Phase 142.5 Plan 01): ret_lag_1/2/3 + fast/mid/slow gradient windows
      Open-to-Close Split (4, Phase 142.5 Plan 01): open_ret, intraday_ret, open_vs_intraday, session_time_pos
      Temporal Coordinates (10, Phase 142.5 Plan 02): hour_of_day/week_of_month/day_of_month/week_of_year sin+cos, month_sin/cos
      Volume Structure (12, Phase 142.5 Plan 02): vol_acceleration, dollar_vol_z, vol_range_ratio, vol_trend_ratio, up_vol_ratio_fast/slow, vol_percentile, vol_persistence, vol_std_z, mfi_fast/slow, obv_z
      Breakout Distance (12, Phase 142.5 Plan 05): dist_from_high/low_fast/slow, range_pct_fast/slow, stoch_k_fast/slow, price_percentile_fast/slow, efficiency_ratio_fast/slow
      Return Distribution (7, Phase 142.5 Plan 03): ret_kurtosis_z_fast/slow, ret_autocorr_1/5, updown_ratio_fast/slow, streak_z
      Realized Variance / Volatility (14, Phase 142.5 Plan 03): realized_var_ratio_fast/slow, range_to_close, true_range_pct, vol_of_vol, high_low_corr, variance_ratio_fast/slow, vol_asymmetry_z, bb_pct_b_fast/slow, hv_z_fast/slow, hv_ratio
      Alternative Volatility Estimators (3, Phase 142.5 Plan 04): parkinson_vol_z, garman_klass_vol_z, yang_zhang_vol_z
      Volatility Dynamics (5, Phase 142.5 Plan 04): parkinson/garman_klass/yang_zhang_vol_velocity, vol_velocity_z, intraday_noise_ratio
      Price-Volume Interactions (8, Phase 142.5 Plan 05.5): vol_body_product, ret_vol_product_fast, price_vol_corr_fast/slow, range_vol_product, up_vol_body_diff, ret_vol_ratio_fast, vol_skew_product
      Session-level — Swing/Fib/Trend/Session Structure (41, Phase 165 Plan 01):
        swing detection (7), trend structure (6), swing momentum (8), fibonacci
        zones (4), session levels (11). All `float | None` with NO default
        (D-01 nullable-field fix -- see class-level docstring paragraph above),
        placed immediately before the defaulted canary block below (dataclass
        field ordering requires every non-defaulted field to precede every
        defaulted one). All ATR-distance/bounded/count/categorical placeholders
        (None until Plans 02-04 wire real compute logic); never a raw price
        level or raw bar index (D-02/D-04).
      Canary / Control Predictors (5, Phase 143.1 Plan 02, todo 068): canary_noise_gaussian, canary_noise_uniform, canary_constant, canary_near_constant, canary_acausal_placebo
      Session-level — Smart Money Concepts (32, Phase 164 Plan 01): order blocks (4),
        breaker/mitigation blocks (3), fair value gaps (3), liquidity sweeps (4),
        liquidity pools (5), supply/demand zones (7), BOS/CHoCH (6).
        All ATR-distance/bounded/count/ordinal placeholders (None until Plans 02-04
        wire real compute logic); never a raw price level (D-16).
      Cross-sectional (3, nullable): momentum/volume/volatility rank z-scores
      Total: 300 (251 required [164 + 41 Swing/Fib/Trend/Session Structure +
      6 Calendar Cycle/TDOM/Minute + 4 Velocity Primitives + 6 Velocity
      Primitives Extension (todo 320) + 11 Recency/Statistical Atomics + 5
      Cross-asset Spread/Beta (non-nullable) + 2 Calendar Event Flags
      (non-nullable) + 10 Theory-Motivated Interactions (non-nullable) + 2
      Earnings-Season Calendar Primitive (non-nullable, Phase 176 Plan 03,
      todo 353),
      Phase 151 Plans 01 + 03 + 04 + 05 + 06 + todo 320 + Phase 176 Plan 03]
      + 49 optional [3 cross-sectional + 5 canary + 32 SMC + 2 Cross-asset
      factor betas (Phase 151 Plan 04, nullable for the factor proxy's own
      self-regression) + 2 Cross-TF divergences (Phase 151 Plan 05, nullable
      -- timeframe-pinned, None where the pair is undefined), all defaulted/
      nullable for cold-start/construction-site blast-radius,
      degenerate-self-regression, or timeframe-undefined reasons -- see
      Canary field comments, the Smart Money Concepts block comment, and the
      Cross-asset Spread/Beta and Named Interaction Primitives field comments
      above])
    """

    # Momentum (7 total: 5 original + 2 new scale-named)
    momentum_z_fast: float | None  # fast-scale return z-score (APR: feature.momentum.window_fast)
    momentum_z_mid: float | None  # mid-scale return z-score (APR: feature.momentum.window_mid)
    range_position: float | None
    bar_close_pos: float | None
    gap_z: float | None
    momentum_z_slow: float | None  # slow-scale return z-score (APR: feature.momentum.window_slow)
    momentum_reversal_z: float | None  # 1-bar return z-score (concept-named: short-term reversal)
    # Volume and order flow (8)
    informed_flow: float | None
    volume_z: float | None
    ofi_z: float | None
    ofi_div: float | None
    cvd_slope_z: float | None
    cmf: float | None
    rel_volume: float | None
    vwap_dev_sigma: float | None  # zero-spread window -> None (D1 rule 5, todo 584 4c)
    # Volatility (2) - part of bar-level computation
    atr_z: float | None
    vol_ratio: float | None
    # Session-level (21: 4 original + 12 VP + 5 S/R, Phase 163) — session
    # volume-profile + support/resistance structural features, computed from
    # OHLCV in both live and batch (D-05: no I3/tick-data dependency exists;
    # the prior comment claiming batch-unavailability was an inherited,
    # never-verified assumption).
    poc_dist_atr: float | None
    va_position: float | None
    sr_support_dist: float | None
    sr_resist_dist: float | None
    # Session-level — Volume Profile (12, Phase 163 Plan 01, D-13/D-16/D-17/D-18)
    nearest_hvn_above_dist_atr: float | None
    nearest_hvn_below_dist_atr: float | None
    nearest_lvn_above_dist_atr: float | None
    nearest_lvn_below_dist_atr: float | None
    price_in_value_area: float | None
    in_lvn: float | None
    va_width_atr: float | None
    distance_to_vah_atr: float | None
    distance_to_val_atr: float | None
    nearest_hvn_dist_atr: float | None
    poc_rolling_dist_atr: float | None
    poc_session_rolling_divergence_atr: float | None
    # Session-level — Support/Resistance (5, Phase 163 Plan 01, D-19)
    resistance_strength: float | None
    support_strength: float | None
    resistance_age_bars: float | None
    support_age_bars: float | None
    sr_level_count: float | None
    # Regime-level (11). hmm_regime_prob/hmm_entropy/hmm_duration are always
    # None from FeatureFactory -- regime_writer.py is the sole writer of
    # these 3 columns (todo 207, 2026-07-30), same as `regime` itself.
    hmm_regime_prob: float | None
    hmm_entropy: float | None
    hmm_duration: float | None
    # The five bar statistics are missing (None) before the first regime refresh and on a window
    # too short or too degenerate to define them, never a neutral 0.5/1.0/0.0 (D1 rule 5,
    # todo 584).
    hurst: float | None
    shannon: float | None
    garch_ratio: float | None
    hma_slope_z: float | None
    adx: float | None
    aroon_fast: float | None
    aroon_slow: float | None
    # Oscillators (6)
    rsi_fast: float | None
    rsi_mid: float | None
    rsi_slow: float | None
    cci_fast: float | None
    cci_mid: float | None
    cci_slow: float | None
    # Cross-asset (3)
    vix_z: float | None
    flight_quality: float | None
    yield_slope_z: float | None
    # Calendar (10: 9 original + 2 new, minus in_london_kz)
    in_ny_session: float | None
    in_overlap: float | None
    power_hour: float | None
    opening_range: float | None
    above_wk_vwap: float
    dow_sin: float
    dow_cos: float
    month_position: float
    quarter_position: (
        float | None
    )  # position within calendar quarter [0, 1]; earnings/rebalancing cycle
    days_to_month_end: float | None  # (days remaining to month end) / (days in month) [0, 1]
    # Calendar — Cycle/TDOM/Minute Coordinates (6, Phase 151 Plan 01, todo 104).
    # First circular harmonic / trading-day-of-month / minute-of-hour, all pure
    # functions of bar_ts (no bars array). This block is immediately followed
    # by Plan 01 Task 2's 4 velocity fields so both form one contiguous
    # 10-field run consumed by feature_vector_persistence.py's
    # _PHASE151_CALENDAR_VELOCITY_FIELD_NAMES index-range slice.
    quarter_cycle_sin: float | None  # sin(2*pi*quarter_position); reuses _quarter_position()
    quarter_cycle_cos: float | None  # cos(2*pi*quarter_position); reuses _quarter_position()
    tdom_sin: float | None  # sin(2*pi*trading_day_of_month/weekdays_in_month)
    tdom_cos: float | None  # cos(2*pi*trading_day_of_month/weekdays_in_month)
    minute_of_hour_sin: (
        float | None
    )  # sin(2*pi*bar_ts.minute/60); constant at 1h/1d by construction
    minute_of_hour_cos: (
        float | None
    )  # cos(2*pi*bar_ts.minute/60); constant at 1h/1d by construction
    # Velocity Primitives (4, Phase 151 Plan 01 Task 2, todo 123). First-
    # difference-then-re-z-scored construction of an already-computed
    # z-score series (identical shape to vol_velocity_z, reuses
    # _vol_velocity_z_series_full).
    momentum_z_velocity_fast: (
        float | None
    )  # zscore(diff(momentum_z_fast)) (APR: feature.momentum_velocity.window)
    momentum_z_velocity_mid: (
        float | None
    )  # zscore(diff(momentum_z_mid)) (APR: feature.momentum_velocity.window)
    momentum_z_velocity_slow: (
        float | None
    )  # zscore(diff(momentum_z_slow)) (APR: feature.momentum_velocity.window)
    vwap_dev_sigma_velocity: (
        float | None
    )  # zscore(diff(vwap_dev_sigma)) (APR: feature.vwap_velocity.window)
    # Velocity Primitives Extension (6, todo 320, 2026-08-15). Same
    # first-difference-then-re-z-scored construction as the 4 fields above
    # (reuses _vol_velocity_z_series_full byte-identically), applied to 3
    # oscillator/flow families the original Phase 151 Plan 01 sweep didn't
    # reach: RSI (3 gradients, one shared window) and the two single-field
    # order-flow z-scores OFI/CVD-slope. volume_z_velocity closes the gap
    # vol_acceleration left (a crude 1-bar V_t/V_{t-1} ratio, not a proper
    # z-scored velocity like every other _velocity field). adx_velocity was
    # considered and dropped from this batch: adx has no precomputed
    # full-history array (it's sourced from cache.adx, a stateful
    # incremental indicator external to _precompute_series) -- reusing this
    # helper on it would require a new _adx_series_full() vectorized
    # implementation first, a separate task, not a clean application of the
    # existing pattern.
    rsi_velocity_fast: float | None  # zscore(diff(rsi_fast)) (APR: feature.rsi_velocity.window)
    rsi_velocity_mid: float | None  # zscore(diff(rsi_mid)) (APR: feature.rsi_velocity.window)
    rsi_velocity_slow: float | None  # zscore(diff(rsi_slow)) (APR: feature.rsi_velocity.window)
    ofi_z_velocity: float | None  # zscore(diff(ofi_z)) (APR: feature.ofi_velocity.window)
    cvd_slope_z_velocity: (
        float | None
    )  # zscore(diff(cvd_slope_z)) (APR: feature.cvd_velocity.window)
    volume_z_velocity: float | None  # zscore(diff(volume_z)) (APR: feature.volume_velocity.window)
    # Earnings-Season Calendar Primitive (2, Phase 176 Plan 03, todo 353,
    # migration 350). Declared as ONE contiguous run immediately after the
    # Velocity Primitives Extension block so feature_vector_persistence.py's
    # _EARNINGS_SEASON_FIELD_NAMES derived slice covers exactly this block.
    # Both non-nullable floats, always computable from bar_ts alone -- see
    # _days_since_quarter_end/_earnings_season_flag's docstrings for the
    # exact formulas.
    earnings_season_flag: (
        float | None
    )  # 1.0 iff days_since_quarter_end in [feature.earnings_season.start_days, feature.earnings_season.end_days], else 0.0
    days_since_quarter_end: (
        float
        | None  # raw calendar days since the most recent quarter end (Mar 31/Jun 30/Sep 30/Dec 31)
    )
    # Recency / Statistical Atomics (11, Phase 151 Plan 03, todo 180). The
    # event-recency axis: bars_since_* are BOUNDED rolling-window statistics
    # in [0, window-1] (never an expanding lookback -- see class-level
    # boundedness note), abs_ret_autocorr_1 is volatility-clustering
    # (magnitude autocorrelation, distinct from the signed ret_autocorr_1
    # above). Declared as one contiguous run immediately after the Plan 01
    # velocity block so feature_vector_persistence.py's
    # _PHASE151_RECENCY_FIELD_NAMES derived slice covers exactly this block.
    bars_since_high_fast: (
        float | None  # bars since rolling-max(high, dist_window_fast); [0, dist_window_fast-1]
    )
    bars_since_high_slow: (
        float | None  # bars since rolling-max(high, dist_window_slow); [0, dist_window_slow-1]
    )
    bars_since_low_fast: (
        float | None  # bars since rolling-min(low, dist_window_fast); [0, dist_window_fast-1]
    )
    bars_since_low_slow: (
        float | None  # bars since rolling-min(low, dist_window_slow); [0, dist_window_slow-1]
    )
    bars_since_52w_high: (
        float | None  # bars since rolling-max(high, high_52w_window); [0, high_52w_window-1]
    )
    bars_since_52w_low: (
        float | None  # bars since rolling-min(low, high_52w_window); [0, high_52w_window-1]
    )
    bars_since_extreme_move_fast: (
        float | None
    )  # bars since |log_ret| > sigma_threshold*rolling_std, fast window (APR: feature.bars_since_extreme_move.sigma_threshold)
    bars_since_extreme_move_slow: (
        float | None
    )  # bars since |log_ret| > sigma_threshold*rolling_std, slow window (APR: feature.bars_since_extreme_move.sigma_threshold)
    bars_since_vol_spike_fast: (
        float | None
    )  # bars since rel_volume > vol_spike_threshold, fast window (APR: feature.bars_since_vol_spike.threshold)
    bars_since_vol_spike_slow: (
        float | None
    )  # bars since rel_volume > vol_spike_threshold, slow window (APR: feature.bars_since_vol_spike.threshold)
    abs_ret_autocorr_1: (
        float | None
    )  # lag-1 Pearson autocorrelation of |log returns| (volatility clustering), bounded [-1,1] (definitional, no APR)
    # Cross-asset — Spread/Beta Atomics (7, Phase 151 Plan 04, todos 123/180).
    # tip_tlt_ret_z/hyg_lqd_ret_z/sb_corr_* are symbol-independent (same value
    # broadcast to every symbol on a given date, like vix_z above).
    # equity_beta_z/rate_beta_z are per-SYMBOL and nullable BY DESIGN: a
    # self-regression (SPY vs SPY, TLT vs TLT) is degenerate (beta identically
    # 1), so None is emitted for the factor proxy's own beta against itself
    # rather than a silently-wrong constant 1.0.
    tip_tlt_ret_z: (
        float | None
    )  # zscore(log_ret(TIP) - log_ret(TLT)) (APR: feature.tip_tlt.zscore_window)
    hyg_lqd_ret_z: (
        float | None
    )  # zscore(log_ret(HYG) - log_ret(LQD)) (APR: feature.hyg_lqd.zscore_window)
    sb_corr_fast: (
        float | None
    )  # rolling Pearson(log_ret(SPY), log_ret(TLT)), fast window (APR: feature.sb_corr.window_fast)
    sb_corr_slow: (
        float | None
    )  # rolling Pearson(log_ret(SPY), log_ret(TLT)), slow window (APR: feature.sb_corr.window_slow)
    sb_corr_z: float | None  # zscore(sb_corr_fast) (APR: feature.sb_corr.zscore_window)
    equity_beta_z: (
        float | None
    )  # zscore(rolling OLS slope of symbol daily log_ret on SPY daily log_ret); None for SPY itself (APR: feature.factor_beta.window / .zscore_window)
    rate_beta_z: (
        float | None
    )  # zscore(rolling OLS slope of symbol daily log_ret on TLT daily log_ret); None for TLT itself (APR: feature.factor_beta.window / .zscore_window)
    # Named Interaction Primitives (5, Phase 151 Plan 05, todos 066/104) --
    # the 5 pre-specified, Fable-reviewed tier-1 interaction candidates from
    # ROADMAP's consolidated roster. ret_div_5m_1h/1h_1d are
    # `float | None` with NO default (required-but-nullable, same idiom as
    # equity_beta_z/rate_beta_z above): each is pinned to the LOWER
    # timeframe of its pair and is None everywhere else -- None means "this
    # tf pair is undefined here," never a fake 0.0 divergence (which would
    # be indistinguishable from "the two timeframes actually agree").
    # opex_flag/quad_witching_flag are
    # non-nullable floats (1.0/0.0), always computable from bar_ts alone --
    # see the two helper functions' docstrings for the exact formulas.
    ret_div_5m_1h: (
        float | None
    )  # own 5m log return - last 1h log return; populated at tf=="5m" only
    ret_div_1h_1d: (
        float | None
    )  # own 1h log return - last 1d log return; populated at tf=="1h" only
    opex_flag: (
        float
        | None  # 1.0 iff dow==Friday AND week_of_month==3 (monthly options expiration), else 0.0
    )
    quad_witching_flag: (
        float
        | None  # 1.0 iff opex_flag==1.0 AND month % 3 == 0 (quarterly quad-witching), else 0.0
    )
    # Theory-Motivated Interactions (10, Phase 151 Plan 06). 10 curated
    # compound features, each a SINGLE operation (product) on two numeric
    # tier-0 columns, each carrying a one-sentence finance-theory hypothesis
    # (concept_registry.description). All ten are float | None and go through
    # _missing_product: a missing (NaN) parent makes the product missing
    # (D1 rule 5, todo 584); only a non-finite product of finite parents
    # trips the counted tripwire (_guard_counted). hv_ratio/adx/hurst/
    # variance_ratio_fast/vix_z/yield_slope_z are the numeric tier-0 proxies
    # substituting for the "regime label" candidate sources named in ROADMAP
    # (categorical regime strings cannot be a product operand) -- Open
    # Question 2's resolution, see plan doc.
    momentum_vol_regime_product: (
        float | None
    )  # momentum_z_fast * hv_ratio; momentum carries more strongly when realized vol is contracting (low-vol anomaly, Frazzini & Pedersen 2014)
    momentum_trend_product: (
        float | None
    )  # momentum_z_fast * adx; momentum persists when trend strength is high, decays into noise when choppy
    breakout_volume_product: (
        float | None
    )  # dist_from_high_fast * volume_z; a breakout confirmed by abnormal volume continues more often than an unconfirmed one
    reversion_hurst_product: (
        float | None
    )  # momentum_reversal_z * hurst; short-term reversal is stronger when the series is anti-persistent (Hurst < 0.5)
    quarter_momentum_product: (
        float | None
    )  # quarter_position * momentum_z_fast; quarter-end window dressing/dealer gamma unwind amplify existing momentum into the quarter close
    variance_ratio_momentum_product: (
        float | None
    )  # variance_ratio_fast * momentum_z_fast; momentum is informative in trending microstructure, noise in mean-reverting
    illiquidity_momentum_product: (
        float | None
    )  # amihud_illiq_z * momentum_z_fast; illiquidity amplifies price impact, so identical order flow moves price further and momentum persists longer
    yield_slope_momentum_product: (
        float | None
    )  # yield_slope_z * momentum_z_fast; term-structure regime conditions equity momentum (carry-times-term-structure candidate source)
    vix_reversion_product: (
        float | None
    )  # vix_z * momentum_reversal_z; the short-term reversal premium is larger in high-volatility regimes where liquidity provision is compensated more
    efficiency_volume_product: (
        float | None
    )  # efficiency_ratio_fast * volume_z; directional efficiency confirmed by volume distinguishes a real trend from directionless drift
    # Cross-timeframe (3)
    ctf_momentum: float | None
    ctf_vwap_align: float | None
    ctf_regime_align: float | None
    # Statistical / liquidity (4)
    amihud_illiq_z: float | None
    high_52w_dist: float | None
    ret_skew_z: float | None
    ret_acf1_z: float | None
    # Renaissance Primitives — Bar Anatomy Ratios (8, Phase 142.5 Plan 01)
    body_ratio: float | None  # (C - O) / (H - L), bounded [-1, 1]
    upper_wick_ratio: float | None  # (H - max(O,C)) / (H - L), bounded [0, 1]
    lower_wick_ratio: float | None  # (min(O,C) - L) / (H - L), bounded [0, 1]
    range_vs_atr: float | None  # (H - L) / ATR_N, unbounded positive
    close_vs_open_direction: float  # sign(C - O), categorical {-1, 0, 1}
    overnight_gap: float | None  # (O - prev_C) / prev_C, unbounded
    overnight_gap_z: float | None  # z-score of overnight_gap (APR: feature.overnight_gap.window)
    range_efficiency: float | None  # abs(C - prev_C) / (H - L), bounded [0, 1]
    # Renaissance Primitives — Lagged Return Series (6, Phase 142.5 Plan 01)
    ret_lag_1: float | None  # log(C_t / C_{t-1}), definitional
    ret_lag_2: float | None  # log(C_t / C_{t-2}), definitional
    ret_lag_3: float | None  # log(C_t / C_{t-3}), definitional
    ret_lag_fast: float | None  # log(C_t / C_{t-N}) (APR: feature.ret_lag.fast)
    ret_lag_mid: float | None  # log(C_t / C_{t-N}) (APR: feature.ret_lag.mid)
    ret_lag_slow: float | None  # log(C_t / C_{t-N}) (APR: feature.ret_lag.slow)
    # Renaissance Primitives — Open-to-Close Split (4, Phase 142.5 Plan 01)
    open_ret: float | None  # log(O_t / prev_C), overnight component
    intraday_ret: float | None  # log(C_t / O_t), intraday component
    open_vs_intraday: float | None  # open_ret - intraday_ret
    session_time_pos: float | None  # continuous [0, 1] position within the NY session
    # Renaissance Primitives — Temporal Coordinates (10, Phase 142.5 Plan 02)
    hour_of_day_sin: float | None  # sin(2*pi*(hour+minute/60)/24), bounded [-1, 1]
    hour_of_day_cos: float | None  # cos(2*pi*(hour+minute/60)/24), bounded [-1, 1]
    week_of_month_sin: float  # sin(2*pi*week/5), week=(day-1)//7+1, bounded [-1, 1]
    week_of_month_cos: float  # cos(2*pi*week/5), week=(day-1)//7+1, bounded [-1, 1]
    day_of_month_sin: float  # sin(2*pi*day/31), bounded [-1, 1]
    day_of_month_cos: float  # cos(2*pi*day/31), bounded [-1, 1]
    week_of_year_sin: float  # sin(2*pi*isocalendar_week/52), bounded [-1, 1]
    week_of_year_cos: float  # cos(2*pi*isocalendar_week/52), bounded [-1, 1]
    month_sin: (
        float  # sin(2*pi*month/12), bounded [-1, 1] (NEW pair; only month_position existed before)
    )
    month_cos: (
        float  # cos(2*pi*month/12), bounded [-1, 1] (NEW pair; only month_position existed before)
    )
    # Renaissance Primitives — Volume Structure (12, Phase 142.5 Plan 02)
    vol_acceleration: float | None  # V_t / V_{t-1}, unbounded positive (APR: none, bar-relative)
    dollar_vol_z: float | None  # z-score of (V*C) (APR: feature.dollar_vol.window)
    vol_range_ratio: (
        float | None
    )  # V_t/(H-L) normalized over N (APR: feature.vol_range_ratio.window)
    vol_trend_ratio: float | None  # vol_MA_fast/vol_MA_slow (APR: feature.vol_trend.fast/.slow)
    up_vol_ratio_fast: (
        float | None
    )  # sum(V|C>O)/sum(V), bounded [0,1] (APR: feature.up_vol_ratio.fast)
    up_vol_ratio_slow: (
        float | None
    )  # sum(V|C>O)/sum(V), bounded [0,1] (APR: feature.up_vol_ratio.slow)
    vol_percentile: (
        float
        | None  # rolling percentile rank of V_t, bounded [0,1] (APR: feature.vol_percentile.window)
    )
    vol_persistence: (
        float
        | None  # lag-1 autocorrelation of V, bounded [-1,1] (APR: feature.vol_persistence.window)
    )
    vol_std_z: float | None  # z-score of rolling std(V) (APR: feature.vol_std.window)
    mfi_fast: float | None  # Money Flow Index, bounded [0,100] (APR: feature.mfi.fast)
    mfi_slow: float | None  # Money Flow Index, bounded [0,100] (APR: feature.mfi.slow)
    obv_z: float | None  # z-score of OBV (APR: feature.obv.window)
    # Renaissance Primitives — Breakout Distance (14, Phase 142.5 Plan 05)
    dist_from_high_fast: (
        float
        | None  # (rolling_high-C)/ATR, unbounded non-neg (APR: feature.breakout.dist_window_fast)
    )
    dist_from_high_slow: (
        float
        | None  # (rolling_high-C)/ATR, unbounded non-neg (APR: feature.breakout.dist_window_slow)
    )
    dist_from_low_fast: (
        float
        | None  # (C-rolling_low)/ATR, unbounded non-neg (APR: feature.breakout.dist_window_fast)
    )
    dist_from_low_slow: (
        float
        | None  # (C-rolling_low)/ATR, unbounded non-neg (APR: feature.breakout.dist_window_slow)
    )
    range_pct_fast: (
        float | None
    )  # (rolling_high-rolling_low)/C, unbounded non-neg (APR: feature.breakout.range_window_fast)
    range_pct_slow: (
        float | None
    )  # (rolling_high-rolling_low)/C, unbounded non-neg (APR: feature.breakout.range_window_slow)
    stoch_k_fast: (
        float | None  # (C-L_N)/(H_N-L_N), bounded [0,1] (APR: feature.breakout.stoch_window_fast)
    )
    stoch_k_slow: (
        float | None  # (C-L_N)/(H_N-L_N), bounded [0,1] (APR: feature.breakout.stoch_window_slow)
    )
    price_percentile_fast: (
        float | None
    )  # rolling percentile rank of C, bounded [0,1] (APR: feature.breakout.percentile_window_fast)
    price_percentile_slow: (
        float | None
    )  # rolling percentile rank of C, bounded [0,1] (APR: feature.breakout.percentile_window_slow)
    efficiency_ratio_fast: (
        float | None
    )  # Kaufman ER, bounded [0,1] (0=chop,1=trend) (APR: feature.breakout.efficiency_window_fast)
    efficiency_ratio_slow: (
        float | None
    )  # Kaufman ER, bounded [0,1] (0=chop,1=trend) (APR: feature.breakout.efficiency_window_slow)
    # Renaissance Primitives — Return Distribution (7, Phase 142.5 Plan 03)
    ret_kurtosis_z_fast: (
        float | None
    )  # z-score of rolling excess kurtosis (APR: feature.ret_kurtosis.fast)
    ret_kurtosis_z_slow: (
        float | None
    )  # z-score of rolling excess kurtosis (APR: feature.ret_kurtosis.slow)
    ret_autocorr_1: (
        float
        | None  # lag-1 Pearson autocorrelation of log returns, bounded [-1,1] (definitional, no APR)
    )
    ret_autocorr_5: (
        float
        | None  # lag-5 Pearson autocorrelation of log returns, bounded [-1,1] (definitional, no APR)
    )
    updown_ratio_fast: (
        float
        | None  # count(up)/count(down) returns, unbounded non-neg (APR: feature.updown_ratio.fast)
    )
    updown_ratio_slow: (
        float
        | None  # count(up)/count(down) returns, unbounded non-neg (APR: feature.updown_ratio.slow)
    )
    streak_z: (
        float | None
    )  # z-score of signed directional streak length (APR: feature.streak.window)
    # Renaissance Primitives — Realized Variance / Volatility (14, Phase 142.5 Plan 03)
    realized_var_ratio_fast: (
        float | None
    )  # var(ret,fast)/var(ret,slow), unbounded non-neg (APR: feature.realized_var.fast/slow)
    realized_var_ratio_slow: (
        float | None
    )  # var(ret,fast)/var(ret,slow), unbounded non-neg (APR: feature.realized_var.fast/slow)
    range_to_close: float | None  # (H-L)/C, unbounded non-neg (no APR)
    true_range_pct: float | None  # TR/C, unbounded non-neg (no APR)
    vol_of_vol: float | None  # z-score of rolling std(atr_z) (APR: feature.vol_of_vol.window)
    high_low_corr: (
        float | None  # correlation of H and L, bounded [-1,1] (APR: feature.high_low_corr.window)
    )
    variance_ratio_fast: (
        float | None
    )  # Lo-MacKinlay VR, unbounded non-neg, ~1.0 under random walk (APR: feature.variance_ratio.fast)
    variance_ratio_slow: (
        float | None
    )  # Lo-MacKinlay VR, unbounded non-neg, ~1.0 under random walk (APR: feature.variance_ratio.slow)
    vol_asymmetry_z: (
        float | None
    )  # z-score of std(ret|up)/std(ret|down) (APR: feature.vol_asymmetry.window)
    bb_pct_b_fast: (
        float | None
    )  # (C-lower_band)/(upper_band-lower_band) (APR: feature.bb_pct_b.fast)
    bb_pct_b_slow: (
        float | None
    )  # (C-lower_band)/(upper_band-lower_band) (APR: feature.bb_pct_b.slow)
    hv_z_fast: (
        float | None
    )  # z-score of close-to-close historical volatility (APR: feature.hv.fast)
    hv_z_slow: (
        float | None
    )  # z-score of close-to-close historical volatility (APR: feature.hv.slow)
    hv_ratio: (
        float
        | None  # hv_fast / rolling_mean(hv, N), unbounded non-neg (APR: feature.hv.ratio_window)
    )
    # Renaissance Primitives — Alternative Volatility Estimators (3, Phase 142.5 Plan 04)
    parkinson_vol_z: (
        float | None
    )  # z-score of rolling-avg ln(H/L)^2/(4ln2) (APR: feature.parkinson_vol.window/.zscore_window)
    garman_klass_vol_z: (
        float | None
    )  # z-score of rolling-avg GK term (APR: feature.garman_klass_vol.window/.zscore_window)
    yang_zhang_vol_z: (
        float | None
    )  # z-score of rolling YZ variance estimator (APR: feature.yang_zhang_vol.window/.zscore_window)
    # Renaissance Primitives — Volatility Dynamics (5, Phase 142.5 Plan 04)
    parkinson_vol_velocity: (
        float | None
    )  # parkinson_vol_z_t - parkinson_vol_z_{t-1}, unbounded (no APR)
    garman_klass_vol_velocity: (
        float | None
    )  # garman_klass_vol_z_t - garman_klass_vol_z_{t-1}, unbounded (no APR)
    yang_zhang_vol_velocity: (
        float | None
    )  # yang_zhang_vol_z_t - yang_zhang_vol_z_{t-1}, unbounded (no APR)
    vol_velocity_z: (
        float | None
    )  # z-score of rolling atr_z velocity (APR: feature.vol_velocity.window)
    intraday_noise_ratio: (
        float | None
    )  # sum(|ret|)/|net_ret| over session, unbounded non-neg (APR: feature.intraday_noise.window)
    # Renaissance Primitives — Price-Volume Interactions (8, Phase 142.5 Plan 05.5)
    vol_body_product: float | None  # body_ratio * volume_z, unbounded symmetric around 0 (no APR)
    ret_vol_product_fast: (
        float | None
    )  # ret_lag_fast * volume_z, unbounded symmetric around 0 (no APR)
    price_vol_corr_fast: (
        float | None
    )  # rolling Pearson(|log ret|, volume), bounded [-1,1] (APR: feature.price_vol_corr.fast)
    price_vol_corr_slow: (
        float | None
    )  # rolling Pearson(|log ret|, volume), bounded [-1,1] (APR: feature.price_vol_corr.slow)
    range_vol_product: (
        float | None
    )  # range_vs_atr * volume_z, unbounded symmetric around 0 (no APR)
    up_vol_body_diff: (
        float | None
    )  # up_vol_ratio_fast - body_ratio, missing when body_ratio is (no APR)
    ret_vol_ratio_fast: float | None  # ret_lag_fast / atr_z, unbounded symmetric around 0 (no APR)
    vol_skew_product: float | None  # ret_skew_z * volume_z, unbounded symmetric around 0 (no APR)
    # Swing/Fib/Trend/Session Structure (41, Phase 165 Plan 01). D-01 nullable
    # fix: every field here is `float | None` with NO default, ported from the
    # archived i3_structure plugins with their silent-numeric-default bug
    # fixed at the type level (the archived swing_detector.py/trend_structure.py
    # emit fake-plausible placeholders like trend_direction=0.0/price_position=0.5
    # when insufficient data exists to measure anything real -- the same
    # failure mode already fixed once for poc_dist_atr/va_position/
    # sr_support_dist/sr_resist_dist, todo 153). This block must precede the
    # defaulted canary block below -- Python dataclass field ordering forbids a
    # non-defaulted field after a defaulted one.
    # Swing Detection (7, Phase 165 Plan 02, D-01/D-02)
    swing_high_dist_atr: float | None
    swing_low_dist_atr: float | None
    swing_high_type: float | None
    swing_low_type: float | None
    swing_pattern: float | None
    swing_high_age_bars: float | None
    swing_low_age_bars: float | None
    # Trend Structure (6, Phase 165 Plan 02, D-01 nullable-fix)
    trend_direction: float | None
    trend_strength: float | None
    trend_leg_count: float | None
    structure_integrity: float | None
    price_position: float | None
    trend_duration_bars: float | None
    # Swing Momentum (8, Phase 165 Plan 03, D-03/D-15)
    swing_amplitude_ratio: float | None
    swing_amplitude_expanding: float | None
    swing_amplitude_intensity: float | None
    swing_velocity_bars: float | None
    swing_velocity_bias: float | None
    struct_energy: float | None
    struct_accel_bias: float | None
    swing_volume_confirmation: float | None
    # Fibonacci Zones (4, Phase 165 Plan 03, D-04/D-05)
    nearest_fib_ratio: float | None
    nearest_fib_dist_atr: float | None
    fib_cluster_strength: float | None
    in_fib_discount_zone: float | None
    # Session Levels (11, Phase 165 Plan 04, D-07..D-09/D-13)
    prior_session_high_dist_atr: float | None
    prior_session_low_dist_atr: float | None
    prior_session_close_dist_atr: float | None
    opening_gap_pct: float | None
    weekly_pivot_dist_atr: float | None
    weekly_r1_dist_atr: float | None
    weekly_r2_dist_atr: float | None
    weekly_s1_dist_atr: float | None
    weekly_s2_dist_atr: float | None
    nearest_level_dist_atr: float | None
    gap_filled: float | None
    # Canary / Control Predictors (5, Phase 143.1 Plan 02, todo 068) — genuine
    # FeatureVector fields (not measurement-time-only diagnostics), so
    # concept_registry (domain='feature')'s row-count/name-set alignment gates
    # stay satisfied. is_control=true rows, status='candidate' (never promoted)
    # in concept_registry -- second line of defense beyond is_control. Negative controls (noise,
    # constant, near-constant) must never clear an IC significance gate; the
    # acausal placebo positive control must clear one spectacularly, proving
    # this pipeline can detect look-ahead leakage. See ops_canary_integrity_assert.py.
    # Defaulted (unlike the rest of this dataclass) purely to avoid a blast
    # radius across every pre-existing hardcoded FeatureVector(...) test
    # constructor in the suite -- every real compute path (compute()/
    # compute_batch()/_cold_start_vector()) always supplies an explicit value.
    canary_noise_gaussian: float | None = (
        0.0  # seeded N(0,1) (APR: alpha.ic.canary_rng_seed), negative control
    )
    canary_noise_uniform: float | None = (
        0.0  # seeded Uniform[0,1), independent sub-seed of same APR key, negative control
    )
    canary_constant: float | None = (
        1.0  # fixed literal (no APR -- definitional degenerate-input control), negative control
    )
    canary_near_constant: float | None = (
        1.0  # literal + tiny deterministic epsilon noise, negative control
    )
    canary_acausal_placebo: float | None = (
        0.0  # existing feature deliberately paired against a forward-shifted return window (look-ahead leak), positive control
    )
    # Session-level — Smart Money Concepts (32, Phase 164 Plan 01). Defaulted
    # to None (unlike the Phase 163 session block above, which has no default)
    # because this block is placed after the canary block above, which already
    # has defaults -- Python dataclass field ordering requires every field
    # following a defaulted field to also carry a default. This is also
    # semantically correct: every value here is a genuine placeholder (no
    # compute logic exists yet) until Plans 02-04 replace None with real
    # computed values, matching the canary fields' own "defaulted to avoid a
    # blast radius across every pre-existing hardcoded FeatureVector(...) test
    # constructor" rationale. Order Blocks (4) / Breaker+Mitigation (3) / FVG
    # (3) / Liquidity Sweeps (4) / Liquidity Pools (5) / Supply-Demand Zones
    # (7) / BOS-CHoCH (6) = 32.
    ob_bull_dist_atr: float | None = None
    ob_bear_dist_atr: float | None = None
    ob_strength: float | None = None
    ob_mitigated_flag: float | None = None
    breaker_dist_atr: float | None = None
    breaker_block_active: float | None = None
    ob_mitigation_pct: float | None = None
    fvg_dist_atr: float | None = None
    fvg_size_atr: float | None = None
    fvg_open_count: float | None = None
    sweep_strength: float | None = None
    reclaim_velocity: float | None = None
    bars_since_last_sweep: float | None = None
    bsl_dist_atr: float | None = None
    ssl_dist_atr: float | None = None
    bsl_touches: float | None = None
    ssl_touches: float | None = None
    pool_count: float | None = None
    demand_dist_atr: float | None = None
    supply_dist_atr: float | None = None
    demand_freshness: float | None = None
    supply_freshness: float | None = None
    active_demand_zones: float | None = None
    active_supply_zones: float | None = None
    zone_friction_score: float | None = None
    bos_strength: float | None = None
    choch_strength: float | None = None
    bos_direction: float | None = None
    choch_direction: float | None = None
    smc_trend_direction: float | None = None
    bars_since_last_shift: float | None = None
    # Cross-sectional (3, nullable — never implemented; always None (todo 103,
    # confirmed 2026-07-27). The "Phase 139 enrichment pass" this comment used to
    # cite doesn't exist as a real, planned unit of work — deferred pending real
    # cross-sectional rank feature design (same category as Phase 151/164).
    momentum_rank_z: float | None = None  # cross-sectional momentum rank z-score
    volume_rank_z: float | None = None  # cross-sectional volume rank z-score
    volatility_rank_z: float | None = None  # cross-sectional volatility rank z-score


@dataclasses.dataclass(frozen=True)
class FeatureVectorRecord:
    """Wire envelope for Kafka transport: FeatureVector + persistence metadata.

    Published by IntelligencePipeline after FeatureFactory.compute().
    Consumed by feature_writer for persistence to feature_vectors hypertable.

    regime_label_source is always 'filtered' per D-07 (forward Viterbi only;
    backward smoother banned to prevent lookahead bias in IC measurement).
    """

    symbol: str
    tf: str
    bar_ts: datetime  # UTC bar open timestamp
    pipeline_version: str  # e.g. "3.0.0"
    feature_factory_version: str  # e.g. "1.0.0"; bump on any compute algorithm change
    regime: str | None  # HMM state label: "ranging", "trending_up", "trending_down"
    regime_label_source: str  # always "filtered" (D-07)
    vector: FeatureVector
