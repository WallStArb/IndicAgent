# Phase 163: VP/SR Structural Primitives - Research

**Author:** Fable 5 (initial dispatch, 2026-07-20) + Claude Sonnet 5 (follow-up verification,
same session) — see provenance notes per section below.

## Objective

Answer: what do we need to know to plan Phase 163 well? Specifically: how to implement real
computation for `poc_dist_atr`/`va_position`/`sr_support_dist`/`sr_resist_dist`, which have been
stuck at `FeatureCache` defaults since v3's inception.

## Section 1: Fable 5's original findings (2026-07-20)

**What the archived logic actually computes** (both operate on plain OHLCV bars — no ticks, no
intrabar data):

- `market_profile.py` (`MarketProfilePlugin`) is **not** a session volume profile despite the
  "session-level VP" label in `feature_cache.py`'s docstring. It bins the **last ~120 bars**
  (`InputSpec(lookback=120)`, `min_lookback=30`) into ~100 price buckets and counts **how many
  bars touch each bucket** (TPO — time-price-opportunity, a presence count) rather than
  weighting by actual traded volume. POC = highest-count bucket; VA = bucket range expanded
  until it holds 70% of total TPO count. `poc_dist_atr`/`va_position` fall straight out of that.
  It has an incremental path (`_compute_next_core`) that **only ever appends** to
  `volume_buckets` and never evicts — `bar_count` grows forever with no windowing, so the
  incremental state silently diverges from what `_compute_full_core` would produce on the same
  window. A literal port would carry that bug forward; it needs fixing, not copying.
- `support_resistance.py` finds local peaks/troughs (`find_peaks`/`find_troughs`, window=10) over
  a bounded per-timeframe lookback (60-120 bars via `_LOOKBACK_BY_TF`), clusters pivots within
  `ATR × 0.5` of each other, scores cluster strength by volume, and reports nearest
  support/resistance **as a percentage distance** (`resistance_dist_pct`/`support_dist_pct`), not
  ATR units. It's non-incremental (`compute_next` just calls `compute_full` again) — cheap,
  bounded, no state bugs.

**The codebase's own stated reason for these being null in batch is wrong.** Both
`feature_factory.py` (line ~3722) and `schemas.py` (line 1262) say VP/SR is "not computable from
OHLCV batch; requires I3 intraday injection." Neither archived plugin touches anything but
`high`/`low`/`close`/`volume` arrays over a bounded window — fully available from
`market_data_ohlcv_tradeable` in both live and backfill. There is no tick-data or I3-pipeline
dependency; that comment appears to be an inherited assumption, not a verified constraint.

**Wiring precedent already exists in v3** for exactly this shape of feature:
- `FeatureCache.update_wk_vwap()` (feature_cache.py:142) already does session-boundary-reset
  accumulation (resets at ISO-week change) — the exact template a session-anchored VP mutator
  (`update_session_vp()`) would follow, just keyed on
  `feature.session.ny_start_utc_hour/minute` (already an APR key, used by `_in_ny_session`)
  instead of ISO week.
- Bounded-window per-bar computation (CMF, CCI, vol_ratio, range_position) is already the pattern
  in both `compute()` and `compute_batch()` for windowed, non-series structural features — S/R
  fits this directly, no new cache mutator required at all since it's stateless per-window.
- `find_peaks`/`find_troughs` (`src/intelligence/utils.py`) are **live utility functions**, not
  archived — directly reusable.
- `poc_dist_atr`, `va_position`, `sr_support_dist`, `sr_resist_dist` already exist as
  `FeatureVector`/`FeatureCache` fields — no schema migration needed for the original 4, just
  populate them for real.

**Fable's original recommendation:** build now, as a lean reimplementation of
`market_profile.py`'s concept (session-anchored, volume-weighted, not TPO touch-count) — not a
literal port. See CONTEXT.md D-01/D-02 for how this was subsequently revised (Section 2 below).

## Section 2: Claude's follow-up verification (same session, after Fable's dispatch returned)

Prompted by the project owner asking "should we add any other VP/SR primitive calcs?" and
noting CLAUDE.md's Core Runtime Files section mentions a "Volume Profile" concept
(`poc_price`/`vah`/`val` session VP, `poc_price_rolling`/`vah_rolling`/`val_rolling` rolling VP)
that hadn't been checked against Fable's analysis yet.

**Finding: a second, more mature archived implementation exists that Fable's dispatch did not
surface** (Fable was directed specifically at `i3_structure`, which matches the target fields'
names but is not the only, or best, prior art):

- `src/intelligence/context/volume_profile.py` (`VolumeProfilePlugin`, `ctx_VolumeProfile`, I4
  tier, "migrated from I5Patterns in Phase 34-02") is self-contained (OHLCV + ATR only, no
  cross-plugin fusion), **non-incremental by construction** (`compute_next` just calls
  `compute_full` again — this is *why* it doesn't have `market_profile.py`'s unbounded-
  accumulator bug: it was never given an incremental path to get wrong), uses real
  volume-weighted histograms (not TPO touch-count — confirmed by reading `_compute_profile()`,
  which bins `volume[i]` directly), and computes both a session track (bars since 09:30 ET,
  reset each day) and a rolling 480-bar track in the same pass. Verified via full file read
  (307 lines) — no bugs found, logic is straightforward (50-bucket histogram, 70%
  cumulative-volume value-area rule, `np.quantile`-based HVN/LVN thresholds at 80th/20th
  percentile).
- Its 18 raw outputs cover the original 4-field scope's needs, but **not all 18 are valid
  FeatureVector columns** — a correction caught later in this same session (CONTEXT.md D-16):
  `poc_price`, `vah`, `val` (session track), `poc_price_rolling`, `vah_rolling`, `val_rolling`
  (480-bar rolling track), `nearest_hvn_above`/`nearest_hvn_below`, `nearest_lvn_above`/
  `nearest_lvn_below`, `nearest_hvn_level`, `nearest_lvn_level` are ALL raw price levels (e.g.
  `nearest_hvn_above = float(hvn_above.min())`), not ATR-normalized — non-stationary,
  non-comparable across symbols, not valid ML/IC features. Only `price_in_value_area` (flag),
  `va_width_atr` ((vah-val)/atr), `distance_to_vah_atr`, `distance_to_val_atr`, and the legacy
  `nearest_hvn_dist_atr`/`in_lvn` are correctly normalized/bounded in the source as-is. The
  directional HVN/LVN fields need converting to ATR-distance (`nearest_hvn_above_dist_atr =
  (nearest_hvn_above - close) / atr`, etc.) before being persisted — see D-16 for the corrected
  9-column field list this phase actually adds.
- `src/intelligence/context/sr_consensus.py` (`ctx_SRConsensus`, Phase 116) is also more
  sophisticated than `i3_structure/support_resistance.py` — verified via full file read (94
  lines) — but it is NOT self-contained: `compute_full()` reads `frames.get("i1")`,
  `frames.get("i3")`, `frames.get("i4")`, `frames.get("smc")` (other plugins' outputs) and calls
  `zone_engine.collect_sr_candidates()`, which aggregates candidate levels from swing points, fib
  zones, session levels, and SMC order-block/FVG plugins, plus synthetic round-number levels
  (`_round_candidates`), then picks the best cross-method-confirmed level via
  `find_best_level()` (prefers a "structurally diverse cluster," 2+ source tiers). This is a
  materially bigger porting job (the whole candidate-source constellation) than the standalone
  `i3_structure/support_resistance.py` pivot-clustering approach — confirmed deferred to a later
  phase (see CONTEXT.md D-14), not built here.

**Follow-up finding, prompted by the project owner asking about "institutional accumulation/
distribution" concepts and I5/I6 tiers:**

- `src/intelligence/archive/smc_context/` holds ~10 Smart Money Concepts plugins (order blocks,
  fair value gaps, liquidity sweeps, liquidity pools, supply/demand zones, AMD cycle,
  breaker/mitigation blocks, BOS/CHoCH, plus BOCPD change-point and a duplicate HMM regime
  plugin). Verified via `wc -l` + import-dependency grep across all 10 files: every one is
  self-contained (only depends on `src/intelligence/utils.py`'s `find_peaks`/`find_troughs`
  (re-exported via the tier's own `swing_utils.py`), `clamp`, `linear_ramp`, `freshness_decay` —
  all live, shared, small utility functions, not other archived plugins). ~2,484 lines total
  across files ranging 90-280 lines each. No cross-plugin dependency chain, unlike
  `ctx_SRConsensus`.
- This is out of Phase 163's scope — filed as **Phase 164 (SMC Institutional Footprint
  Primitives)**, see that phase's ROADMAP.md entry and (once planned) its own CONTEXT.md/
  RESEARCH.md. Phase 163's CONTEXT.md D-15 has the summary; full candidate-primitive-per-concept
  breakdown lives in Phase 164's own docs once `/gsd-plan-phase 164` runs.
- I5 (patterns: head-shoulders, triangles, flags, candlesticks, `KeyLevelReactionPlugin`) and I6
  (confluence: cross-timeframe FVG/OB alignment scores) tiers were reviewed and judged NOT
  atomic-primitive material — I5 is compound multi-bar pattern-matching (closer to signals/
  setups), I6 is aggregation across timeframes and across SMC atomics (matches Phase 151's
  Theory-Motivated Interaction Layer shape once the underlying SMC atomics exist, not a new
  atomic primitive of its own). Neither is in scope for Phase 163 or Phase 164.

## Section 3: What this means for Phase 163's actual plan

- **POC/VA port source:** `ctx_VolumeProfile` (`context/volume_profile.py`), not
  `i3_structure/market_profile.py`. Read `compute_full()` (lines 179-301) as the reference
  algorithm; the three private helpers (`_compute_profile`, `_compute_value_area`,
  `_compute_directional_nodes`) are directly reusable logic, adapted into
  `FeatureCache`/`feature_factory.py`'s own shape (session-boundary-reset mutator for the session
  track per `update_wk_vwap()`'s pattern, stateless windowed computation for the rolling track
  per CMF/CCI's pattern — the rolling track needs no session-reset state at all since it's
  always "last 480 bars").
- **S/R port source:** `i3_structure/support_resistance.py` (unchanged from Fable's original
  finding) — `ctx_SRConsensus` explicitly deferred (needs Phase 164's SMC atomics as inputs
  first).
- **New schema/migration work beyond the original 4 fields:** yes — `ctx_VolumeProfile`'s
  additional 14 fields need new `FeatureCache` dataclass fields, `FEATURE_VECTOR_DOMAIN` entries
  (tag `"structural"`), and new `feature_vectors` columns via migration (the original 4 already
  have columns; these don't).
