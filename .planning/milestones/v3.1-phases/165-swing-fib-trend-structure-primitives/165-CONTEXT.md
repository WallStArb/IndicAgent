# Phase 165: Swing/Fib/Trend Structure Primitives - Context

**Gathered:** 2026-07-20
**Status:** Ready for planning
**Source:** Fable 5 dispatch (this session), verifying and extending a prior-session preliminary
survey recorded in ROADMAP.md's "### Phase 165" entry. Same transport as Phase 163's context
(conversation/dispatch, not a formal `/gsd-discuss-phase` session — equivalent rigor).

**Authoritative final scope (read this, not the historical narrative in RESEARCH.md, for the
actual column count):** 24 new `FeatureVector` columns from 4 files built now (`swing_detector.py`
7, `swing_momentum.py` 8 — 7 original + 1 volume-confirmation, D-15, `trend_structure.py` 6,
`fibonacci_zones.py` 4) + a 5th file (`session_levels.py`, 16 columns — 15 original + 1 gap-fill
flag, D-13) built as its own plan within this same phase due to a real session-boundary rewrite,
not a literal port = **41 total new columns if `session_levels.py` ships in this phase's
execution**. `macd_events.py` and `bocpd_changepoint.py` stay parked (0 columns, not this phase's
scope). Fibonacci extension levels (1.272/1.618/2.0) were considered and explicitly deferred, not
built (D-14) — see Deferred Ideas.

<domain>
## Phase Boundary

Port 5 of the 6 remaining `src/intelligence/features/i3_structure/` plugins Phase 163 didn't
cover (`market_profile.py`/`support_resistance.py` were 163's scope) into real v3 `FeatureVector`
primitives: `swing_detector.py`, `swing_momentum.py`, `trend_structure.py`,
`fibonacci_zones.py`, and `session_levels.py`. All five files were confirmed self-contained
(OHLCV + ATR only, no cross-plugin dependency once `fibonacci_zones.py`'s stale fallback is
deleted) and confirmed to have no better port source elsewhere in the codebase (unlike Phase
163's `market_profile.py`→`ctx_VolumeProfile` swap — checked `context/` and `archive/
smc_context/` directly, found none; see RESEARCH.md Section 3).

Four sub-scopes:
1. **Swing detection** — `swing_detector.py`: most-recent confirmed swing high/low
   (`find_peaks`/`find_troughs`, N=5 window), HH/HL/LH/LL classification, age in bars. Feeds
   `swing_high_dist_atr`/`swing_low_dist_atr` (replacing raw-price `swing_high`/`swing_low`) plus
   5 already-valid fields, **minus 2 raw-index fields dropped entirely** (D-02 below).
2. **Swing momentum** — `swing_momentum.py`: amplitude/velocity of the last 3 confirmed swings
   from its own independent (not shared) peak/trough detection. 7 fields, all already valid
   shape once `swing_velocity_trend`'s string enum is numerically encoded (D-03), plus 1 new field
   (`swing_volume_confirmation`, D-15 — a free column off the same swing-leg computation).
3. **Trend structure** — `trend_structure.py`: directional leg-counting classification (bullish
   vs. bearish swing-pair majority), structural integrity (swing-overlap cleanliness), price
   position within the recent swing range. 6 fields, all already relative/bounded — **but two
   silent-wrong-answer bugs (D-01) must be fixed before port, not carried forward.**
4. **Fibonacci zones + Session levels** — `fibonacci_zones.py` (4 valid fields kept, 8 raw-
   price/intermediate fields dropped, D-04; extension levels considered and deferred, D-14) and
   `session_levels.py` (a genuine session-boundary rewrite, not a port — D-06 through D-09, plus
   1 new field `gap_filled`, D-13), sequenced as separate plans within this same phase.

**Deliberately parked, not silently dropped:**
- `macd_events.py` — v3's live `FeatureVector` has zero MACD fields (verified directly against
  the dataclass at `schemas.py:1204-1483`, not the archived `I3Structure`/`I1Indicators` Pydantic
  models earlier in the same file). Porting an "events" layer with no underlying indicator to
  fire events off is the wrong shape of work for this phase, and MACD itself is a momentum-
  oscillator primitive, not a swing/fib/trend structural one — belongs in a different phase if
  ever built (D-10).
- `bocpd_changepoint.py` (`archive/smc_context/`) — confirmed still correctly parked. Genuinely
  distinct regime-detection paradigm (Bayesian online changepoint vs. per-symbol HMM), already
  self-documents a real O(R) algorithmic cost floor (~77ms p95 at `max_run_length=200`) that needs
  its own latency benchmark before being assigned any phase (D-11).

</domain>

<decisions>
## Implementation Decisions

### Correctness bugs to fix during the port (highest priority — do not carry these forward)

- **D-01: `trend_structure.py` and `swing_detector.py` both manufacture fake-but-numeric "no
  signal" values instead of nulling out.** `trend_structure.py`'s early return on
  `len(swing_highs) < 2 or len(swing_lows) < 2` currently returns a full dict of plausible-looking
  defaults (`trend_direction=0.0`, `price_position=0.5`, etc.) instead of signaling "insufficient
  data." `swing_detector.py` does the same per-field (`sh_price = ... if swing_highs else 0.0`;
  `high_type = 0.0` when `len(swing_highs) < 2`). This is the identical failure shape to the bug
  Phase 163 was built to fix (`FeatureCache` stub defaults reading as real IC-zero measurements
  for 5,510 cells) — the difference is these two plugins manufacture the fake value themselves
  rather than inheriting it from an unpopulated cache field. **Fix: every field in both plugins'
  `FeatureVector` mapping must be `float | None` (matching the existing `poc_dist_atr: float |
  None` precedent), and both early-return/default-assignment branches must emit `None` per field,
  never a numeric placeholder.** `swing_momentum.py` and `fibonacci_zones.py` do NOT have this bug
  (both correctly return `{}` on insufficient data) — no change needed there beyond the normal
  raw-price conversion.

### Field-list corrections beyond the prior survey

- **D-02: Drop `swing_high_idx`/`swing_low_idx` entirely — not valid `FeatureVector` columns and
  not mentioned by the prior survey at all.** These are raw bar-array positional indices (e.g.
  `47`), invalid for the same reason a raw price is invalid (non-stationary, non-comparable
  across windows of different lengths, which vary by timeframe and by how much history the batch
  path happened to load) — and fully redundant with `swing_high_age_bars`/`swing_low_age_bars`
  (`n_bars - 1 - idx`, the derived valid version of the same information). Confirmed via
  `context/anchored_vwap.py`'s consumption of `i3.get("swing_high_idx")` (line 89) that the only
  historical use for the raw index was as an internal anchor point for a downstream calculation,
  never as a standalone feature — reinforcing they should never have been persisted columns.
- **D-03: `swing_velocity_trend` (string enum `"accelerating"`/`"decelerating"`/`"stable"`)
  becomes `swing_velocity_bias: Literal[-1, 0, 1] | None`** — `+1` = accelerating (velocities
  shrinking, swings happening faster), `-1` = decelerating, `0` = stable, matching the existing
  `struct_accel_bias` categorical convention in the same file.
- **D-04: `fibonacci_zones.py` drops all 8 raw-price/intermediate fields
  (`fib_swing_high`, `fib_swing_low`, `fib_236`, `fib_382`, `fib_500`, `fib_618`, `fib_786`,
  `nearest_fib_level`), adds none new.** Converting all 5 individual fib levels to their own
  `_dist_atr` columns (the prior survey's implied fix) would reproduce Phase 163's D-17 exact-
  collinearity finding five times over — adjacent fib ratios are evenly spaced along the same
  `swing_range`, so e.g. `dist_atr(fib_236)` and `dist_atr(fib_382)` differ by a *constant*
  `0.146 × swing_range / atr` per bar, near-total redundancy. `nearest_fib_ratio` +
  `nearest_fib_dist_atr` already jointly encode the useful compressed signal (which of the 5
  canonical ratios is nearest, and how far). Unlike Phase 163's D-18 rolling-track addition, there
  is no comparably distinct new economic hypothesis hiding in the unused levels here — don't add
  them speculatively.
- **D-05: Delete `fibonacci_zones.py`'s cross-plugin fallback entirely, don't "resolve it in
  place."** The `i3.get("swing_high")`/`swing_low` read with a rolling-high/low fallback exists
  because the old wave-based pipeline couldn't guarantee `swing_detector.py` ran first in the same
  pass. v3's `compute()`/`compute_batch()` is a single deterministic in-process function — compute
  swing high/low once per bar as local Python values, feed both `swing_detector`'s own fields and
  `fibonacci_zones`'s fib-level math from that same computation. No fallback branch needed at all.

### APR keys (migrate-as-you-go — this phase's surface is bigger than the prior survey found)

- **D-06: New namespace `feature.swing.*`** — `feature.swing.pivot_window` (int, default 5,
  `[conventional]`), shared by `swing_detector.py` AND `trend_structure.py` since both call
  `find_peaks(high, self.neighbor)`/`find_troughs(low, self.neighbor)` with the literal same
  `neighbor: int = 5` default today — one shared key, not two, since it's the same operation.
- **New namespace `feature.trend_structure.*`** — `feature.trend_structure.atr_strength_divisor`
  (float, default 5.0, the divisor the prior survey already found) AND
  `feature.trend_structure.range_lookback_bars` (int, default 20, the `high[-20:]`/`low[-20:]`
  slice the prior survey missed — see RESEARCH.md Finding A/Section 1). Two keys, not one.
- **New namespace `feature.swing_momentum.*`** — six keys, none flagged by the prior survey:
  `feature.swing_momentum.confirm_n` (default 3, deliberately separate from
  `feature.swing.pivot_window` — different calculation, self-contained by design, don't force
  unification), `feature.swing_momentum.max_extremes` (default 6; note in the APR description that
  it must stay even — represents 3 complete swings), `feature.swing_momentum.reference_bars`
  (default 20), `feature.swing_momentum.speed_factor_min`/`speed_factor_max` (defaults 0.1/3.0),
  `feature.swing_momentum.energy_divisor` (default 3.0), `feature.swing_momentum.intensity_ramp_lo`/
  `intensity_ramp_hi` (defaults 1.0/2.0).
- **New namespace `feature.fib.*`** — `feature.fib.cluster_atr_divisor` (default 2.0, from
  `atr_14 / 2.0` in the cluster-threshold calc) and `feature.fib.cluster_fallback_divisor`
  (default 20.0, from `swing_range / 20.0`, used only when ATR is unavailable). The 5 fib ratios
  themselves (0.236/0.382/0.5/0.618/0.786) are APR-exempt — definitional mathematical constants
  (Fibonacci retracement ratios), same exemption class as "the 5 in `momentum_z_5`" per CLAUDE.md.
- **New namespace `feature.session_levels.*`** (for D-06/D-09's rewrite) — no bar-count keys at
  all (that's the bug being removed); needs `feature.session_levels.asia_start_et_hour`/
  `asia_end_et_hour` (defaults 20/4, `[conventional]`, matching the existing hardcoded values —
  APR-backed for consistency with the `feature.session.ny_start_utc_hour` precedent even though
  the underlying convention, like NY market hours, is effectively definitional).

### `session_levels.py` — real rewrite, own plan within this phase, not its own phase

- **D-07: The bug is real and confirmed, but narrower than the ROADMAP survey implied.**
  `_SESSION_BARS=390`/`_WEEK_BARS=1950`/`_OVERNIGHT_BARS=60` assume 1-minute bars. v3 doesn't run
  FeatureVector computation at 1m at all (live depths are 5m/15m/1h/1d) — so this isn't "wrong on
  other timeframes," it's wrong on every timeframe v3 actually uses. Verified magnitude at each:
  390 bars ≈ 5 sessions at 5m, ≈15 sessions at 15m, ≈60 sessions (~12 weeks) at 1h, ≈390 calendar
  days (~1.5yr) at 1d. **But** the Asian-session sub-feature (lines 164-177, 244-255, 365-376) is
  already timestamp-based (`ZoneInfo`-converted ET hour masking, no bar-count) and therefore
  already correct and timeframe-agnostic — only `prior_session_*`/`overnight_*`/`weekly_*` need
  the rewrite. Standard raw-price→ATR-distance conversion is sufficient for Asian H/L, same as
  every other file in this phase.
- **D-08: Rewrite `prior_session_*`/`overnight_*` via a session-boundary-transition `FeatureCache`
  mutator, timestamp-based, following Phase 163's planned `update_session_vp()` pattern and
  reusing the existing `_in_ny_session()`-style hour/minute comparison** (`feature_factory.py:
  1560`) rather than bar counts. Detect a new session by the `_in_ny_session(bar_ts)` transition
  0→1 (or an ET-calendar-date change), not `bar_count mod _SESSION_BARS`. "Overnight" becomes the
  block of bars where `_in_ny_session == 0` since the last session close, not a fixed 60-bar
  count.
- **D-09: Rewrite `weekly_pivot`/`weekly_r1`/`weekly_r2`/`weekly_s1`/`weekly_s2` by extending the
  existing ISO-week-boundary accumulator, not building a second parallel one.**
  `FeatureCache.update_wk_vwap()` (`feature_cache.py:142-165`) already resets on
  `bar_ts.isocalendar()` year/week change (`self._wk_year_week`) — extend this same reset check to
  also track weekly running high/low/close (three new `_wk_*` accumulator fields alongside the
  existing `_wk_tp_vol_sum`/`_wk_vol_sum`), rather than inventing a second weekly-boundary
  mechanism. Deliberately not folded into a single combined method — keep `update_wk_vwap()`'s
  existing signature/call site intact, add the weekly-pivot tracking as a sibling method or an
  extension of the same reset block, planner's discretion on exact shape.
- **Decision: this is its own plan within Phase 165, not its own phase.** The rewrite is real
  engineering work (a new session-boundary-transition mutator, unlike the other 4 files' pure
  ATR-conversion-and-wire), but every primitive it needs already exists from Phase 163 (the
  `FeatureCache` mutator pattern, `_in_ny_session()`, the ISO-week accumulator) — there is no real
  dependency gap that would justify separate-phase coordination overhead. Sequence it as the last
  plan in this phase (after the other 4 files' shared-swing-computation plan), since it shares no
  code with them.

### Files parked, not assigned to this phase

- **D-10: `macd_events.py` stays parked.** Confirmed zero MACD fields exist anywhere in the live
  `FeatureVector` (`schemas.py:1204-1483`) — grepped `feature_factory.py` directly, no hits.
  Porting the events-layer plugin first would mean building MACD itself as an undeclared side
  effect, a materially different and larger scope than "events on an existing indicator," and a
  domain-naming mismatch (MACD is a momentum oscillator, not swing/fib/trend structure). The
  `nearest_support` cross-plugin dependency is confirmed real but not the actual blocker — once
  Phase 163 ships `sr_support_dist` (already an ATR-distance under D-16, not a raw price), the
  fix is simpler than the original code: `neg_support = 1 if sr_support_dist < threshold else 0`,
  no `abs(close - nearest_support)/atr` recompute needed. Revisit only if/when MACD itself becomes
  a wanted primitive in its own oscillator-family phase.
- **D-11: `bocpd_changepoint.py` stays parked, confirmed correctly.** Read in full — the file's own
  header comment already documents the O(R) forward-pass cost (~77ms p95 at `max_run_length=200`)
  as an algorithmic floor, not a bug to fix. Genuinely distinct regime-detection paradigm from
  both this phase (swing/fib/trend) and Phase 164 (SMC institutional footprint). Needs a
  standalone latency benchmark at 58-ETF × 4-TF backfill scale before being assigned any phase —
  gated on that benchmark, not on redesign risk. **Housekeeping note, not a scope item:** found
  `src/intelligence/features/smc_context/bocpd_changepoint.py` is a byte-identical stray duplicate
  of `archive/smc_context/bocpd_changepoint.py` (confirmed via `diff`, zero output) — the
  `features/smc_context/` directory is mostly a dead leftover copy of the archive except
  `hmm_regime.py`, which is genuinely still imported live (`pipeline/executor.py:937`). Worth a
  one-line cleanup todo eventually, not part of this phase.

### Promotion bar — same discipline as Phase 163's D-07, extended to new near-neighbors

- **D-12: This phase's `price_position` (from `trend_structure.py`) joins the existing "position
  within a range" family** Phase 163's D-07 already screened `va_position` against
  (`bb_pct_b_fast/slow`, `price_percentile_fast/slow`, `stoch_k_fast/slow`). Found during this
  research: `context/premium_discount.py`'s `smc_PremiumDiscount` plugin (Phase 164's territory)
  independently computes `premium_discount_pct = clamp((close - equilibrium)/half_range)` where
  `equilibrium = (swing_high + swing_low)/2` — algebraically `2 × (price_position - 0.5)` using
  the same underlying swing-range concept. Whatever incremental-IC evaluation this phase's fields
  eventually get MUST test `price_position` against `va_position` (Phase 163) too, not only the
  original D-07 family — this near-neighbor family is now three members deep across two phases.
  This phase's own scope stops at "correct, real, non-constant values computed and persisted,"
  same as Phase 163's D-07 — the incremental-IC test itself runs via `ic_engine`/corpus pipeline
  whenever that next runs, not as bespoke work in this phase.

### Complementary additions found via a later council-style rigor pass (2026-07-20, same session)

Three tangential ideas were proposed after the main research pass. Each was tested against
CLAUDE.md's 5-step mandate (question the requirement before accelerating) and the project's
"resist overfitting"/"earn promotion through proof" principles before being accepted or deferred
— not accepted on "seems useful" grounds alone.

- **D-13: `session_levels.py` gains one new field, `gap_filled` (flag).** Tests whether price has
  traded back through `prior_session_close` at any point since the session open (`session_low <=
  prior_session_close <= session_high`, checked against the running session high/low the D-08
  mutator already tracks — zero new state needed, just a comparison against existing accumulator
  fields). Survives the rigor test on two grounds: (1) it is NOT derivable post-hoc from the
  stored feature vector, since `prior_session_close`/session high/low are raw prices and (per
  D-16's rule, inherited from Phase 163) never persisted as columns themselves — only their ATR-
  distance companions are — so the fact of a gap being filled is genuinely new, non-recoverable
  information; (2) it is a companion to exactly one existing field (`opening_gap_pct`), not a
  second member of an unproven family. **Deliberately NOT adding a paired
  `bars_since_gap_fill` column** — one concept, one column; a velocity companion can be added
  later if the flag itself shows real IC, not speculatively bundled in now.
- **D-14 (deferred, not built): Fibonacci extension levels (1.272/1.618/2.0), ADR-style
  continuation targets beyond the swing range.** Rejected for this phase's initial build, unlike
  D-13/D-15, on a different failure mode: this is not a free column off computation already
  happening — it requires genuinely new logic (a second ratio family, new `feature.fib.
  extension_ratios` APR key) — AND the base 4 fib-retracement fields (D-04's scope) have zero IC
  evidence yet. Building extensions now would scale an already-unproven technical-analysis
  hypothesis family before its first member clears any incremental-IC test — the "don't
  accelerate in the wrong direction" failure CLAUDE.md's 5-step mandate exists to catch, and a
  clean example of the "resist overfitting" principle applied at build time rather than after the
  fact. **Correct sequencing: ship the base 4 fib fields, measure them via `ic_engine`, and only
  then revisit extensions if `nearest_fib_ratio`/`nearest_fib_dist_atr` show real incremental IC.**
  Cheap to add later — `swing_high`/`swing_low` will already be local values in `compute()`/
  `compute_batch()` by then (D-05), so this is a low-regret deferral, not a lost opportunity.
- **D-15: `swing_momentum.py` gains one new field, `swing_volume_confirmation` (unbounded ratio,
  same normalization class as `swing_amplitude_ratio`/`vol_ratio`/`garch_ratio`).** Mean volume
  over the bar-index range spanning the most recent confirmed swing leg (`last6[-2].idx` to
  `last6[-1].idx` — indices the plugin's `_detect_extremes()` already computes for the amplitude
  calc) divided by mean volume over the full lookback window. Survives the rigor test cleanly:
  true zero-marginal-cost column off a computation this phase is building regardless (same
  category as Phase 163's D-18/D-19 "free field" pattern, not scope creep), and it adds a
  genuinely orthogonal dimension — participation/conviction behind a price move — that nothing
  else in this phase's scope measures. Directly analogous to the same volume-weighting insight
  that made Phase 163 discard TPO touch-count in favor of real volume for the VP work (D-13 of
  163-CONTEXT.md).

### Claude's Discretion
- Exact `FeatureCache` internal state shape for the session-boundary mutator (D-08) and the
  extended weekly accumulator (D-09) — general shape only, matching `update_wk_vwap()`'s existing
  pattern.
- Whether to add a `nearest_session_level_type` categorical companion field to
  `session_levels.py`'s rewritten `nearest_level_dist_atr` (which of prior-high/prior-low/weekly-
  pivot/R1/R2/S1/S2 is nearest) — cheap, analogous to `nearest_fib_ratio`, not required.
- Whether `swing_detector`'s pivot window and `trend_structure`'s pivot window literally share one
  `ConfigService` key (D-06 recommends yes) vs. two independently-settable keys that happen to
  default to the same value — either is APR-compliant; sharing is simpler and matches "same
  function, same call."

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Port sources (direct port, no better source exists — see RESEARCH.md Section 3)
- `src/intelligence/features/i3_structure/swing_detector.py` (`SwingDetectorPlugin`) — read in
  full (95 lines). `compute_full()` is the reference algorithm; `find_peaks`/`find_troughs` from
  `src/intelligence/utils.py` do the actual pivot detection (live, shared, not archived).
- `src/intelligence/features/i3_structure/swing_momentum.py` (`SwingMomentumPlugin`) — read in
  full (258 lines). `compute_full()` (lines 62-134), `_detect_extremes()` (144-179, its own
  independent peak/trough logic), `_compute_amplitudes()`/`_compute_velocities()`/
  `_compute_accel_bias()` are the reusable sub-steps.
- `src/intelligence/features/i3_structure/trend_structure.py` (`TrendStructurePlugin`) — read in
  full (181 lines). `compute_full()` (lines 35-146) is the reference algorithm — **the
  `len(swing_highs) < 2 or len(swing_lows) < 2` branch at lines 48-56 is the D-01 bug to fix, not
  copy.**
- `src/intelligence/features/i3_structure/fibonacci_zones.py` (`FibonacciZonesPlugin`) — read in
  full (108 lines). `compute_full()` (lines 40-102) — **lines 50-59's `i3.get("swing_high")`
  fallback is the D-05 dead weight to delete, not resolve-in-place.**
- `src/intelligence/features/i3_structure/session_levels.py` (`SessionLevelsPlugin`) — read in
  full (435 lines). `_compute_full_core()` (58-179), `_seed_state()` (181-272), `_compute_next_core()`
  (274-432) — **lines 22-24's `_SESSION_BARS`/`_WEEK_BARS`/`_OVERNIGHT_BARS` are the D-07 bug;
  lines 164-177/244-255/365-376's Asian-session ET-hour masking is already correct, do not
  rewrite.**

### Superseded/context-only references
- `src/intelligence/features/i3_structure/support_resistance.py` — Phase 163's port source, read
  for shared-convention context (window/cluster-radius APR pattern, `find_peaks`/`find_troughs`
  usage). `window: int = 10` here vs. this phase's `neighbor: int = 5` in swing_detector/
  trend_structure — deliberately not unified (D-06 only unifies swing_detector/trend_structure
  with each other, not with support_resistance's separately-scoped S/R clustering window).
- `src/intelligence/context/session_context.py` (`ctx_SessionContext`) — read in full (328 lines).
  A distinct, already-live-ish (though not wired into `feature_factory.py`) **time-of-day** session
  plugin — not a substitute for `session_levels.py`'s **price-pivot** concept. Confirmed via grep
  that it is not imported by `feature_factory.py`; v3's live `in_ny_session` comes from
  `feature_factory.py`'s own `_in_ny_session()` (line 1560), not this plugin. Read only so this
  phase's `session_levels.py` work isn't confused with it.
- `src/intelligence/archive/smc_context/premium_discount.py` (`smc_PremiumDiscount`, Phase 164's
  territory — **path correction**: not under `context/`, verified directly; also byte-identical
  duplicated at `src/intelligence/features/smc_context/premium_discount.py`, same stray-duplicate
  pattern as `bocpd_changepoint.py`, D-11) — read in full. Not a port source for this phase, but
  its `premium_discount_pct` is the D-12 near-neighbor finding for the promotion-bar note.
- `src/intelligence/archive/smc_context/bocpd_changepoint.py` — read in full (294 lines), D-11's
  parking confirmation. Byte-identical duplicate at `src/intelligence/features/smc_context/
  bocpd_changepoint.py` (confirmed via `diff`) — housekeeping note only, not this phase's scope.

### v3 wiring templates (the pattern to follow — same as Phase 163's)
- `src/intelligence/feature_cache.py` — `FeatureCache` dataclass. `update_wk_vwap()` (lines
  142-165) is the direct template for D-09's weekly-pivot extension (ISO-week-boundary reset,
  `self._wk_year_week` check) — extend this same accumulator rather than building a second one.
  `advance_bar()` (167-182) is the per-bar call-site pattern both live pipeline and backfill
  already use.
- `src/intelligence/feature_factory.py` — `_in_ny_session()` (line 1560) is the exact-session-
  boundary-detection template for D-08 (UTC hour/minute comparison against
  `config.ny_session_start_utc_hour`/`_minute`/`config.ny_session_end_utc_hour`, themselves APR
  keys `feature.session.ny_start_utc_hour`/`ny_start_utc_minute`/`ny_end_utc_hour`, already live).
  `FEATURE_VECTOR_DOMAIN` dict (lines 58-83+) — new fields tag as `"structural"`, following the
  existing `poc_dist_atr`/`va_position`/`sr_support_dist`/`sr_resist_dist` entries (lines 80-83).
- `src/intelligence/schemas.py` — `FeatureVector` dataclass, lines 1204-1483 (the live one — do
  NOT confuse with `I3Structure` Pydantic model at lines 228-341, which is dead/archived and
  happens to share several field names with this phase's plugin outputs by coincidence of both
  deriving from the same original plugin naming). `poc_dist_atr: float | None` (line 1263) is the
  nullable-field precedent D-01's fix must follow.
- `production/migrations/169_feature_registry.sql` — `feature_registry` table schema. **Use
  `group_name='session'`, `tier='2_theory'` for all Phase 165 new fields** (matching
  `poc_dist_atr`/`va_position`/`sr_support_dist`/`sr_resist_dist`'s own registry rows, lines
  226-229 — NOT `group_name='structure'`, which is reserved for simple 0-atomic bar-anatomy
  fields like `range_position`/`bar_close_pos`). `normalization` vocabulary confirmed from
  existing rows: `'z_scored'` for signed/symmetric-around-zero distances (e.g. `poc_dist_atr`),
  `'unbounded_ratio'` for always-non-negative distances (e.g. `dist_from_high_fast`, which uses
  `abs()`/one-sided-by-construction), `'bounded_signed'` for `[-1,1]`/categorical `{-1,0,1}` fields
  (e.g. `close_vs_open_direction`), `'bounded_unsigned'` for `[0,1]`/binary-flag fields (e.g.
  `in_ny_session`).
- `src/intelligence/trading/atr_utils.py` — `get_atr(features)` (line 17), already used by every
  file in this phase for ATR access; no new ATR computation needed.
- `src/intelligence/utils.py` — `find_peaks`/`find_troughs` (lines 15-67), live, directly reusable
  — the shared canonical pivot-detection primitive confirmed to have no better alternative
  anywhere in the codebase (RESEARCH.md Section 3).
- `src/intelligence/utils/gradient_utils.py` — `linear_ramp()` (lines 41-48), already used by
  `swing_momentum.py`; its two magic-number arguments (D-06's `feature.swing_momentum.
  intensity_ramp_lo`/`_hi`) are what need APR-backing, not the function itself.

### Phase 163 cross-reference (shared conventions this phase reuses)
- `.planning/milestones/v3.1-phases/163-vp-sr-structural-primitives/163-CONTEXT.md` — D-01 through D-19. D-16's
  raw-price rule, D-03's `update_session_vp()` mutator pattern, D-07's promotion-bar discipline,
  and D-19's "don't discard free fields from a clustering pass you already have to run" reasoning
  all directly inform this phase's D-02/D-08/D-12/D-04 decisions above.
- `.planning/milestones/v3.1-phases/163-vp-sr-structural-primitives/163-RESEARCH.md` — Sections 1-3, template for
  this document's depth/structure.

### Phase 164 cross-reference (sibling phase, near-neighbor overlap only)
- `.planning/ROADMAP.md` "Phase 164: SMC Institutional Footprint Primitives" — `smc_PremiumDiscount`
  (D-12's near-neighbor finding) lives there, not this phase. No hard dependency either direction.

### Todo / roadmap cross-references
- `.planning/ROADMAP.md` "### Phase 165" entry — the prior-session preliminary survey this
  document verifies, corrects, and extends. Read for what changed (RESEARCH.md Sections 1-2).

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `find_peaks`/`find_troughs` (`src/intelligence/utils.py`) — confirmed canonical, no better
  alternative exists anywhere in the codebase (checked `context/` and both `smc_context`
  directories). `swing_detector.py`/`trend_structure.py` already call these directly; no new
  pivot-detection code needed, just APR-back the window argument (D-06).
- `get_atr()` (`src/intelligence/trading/atr_utils.py`) — already used by every file in this
  phase; ATR-normalization reuses this, no new ATR computation needed.
- `FeatureCache.update_wk_vwap()`'s `_wk_year_week` ISO-boundary check (`feature_cache.py:142-165`)
  — extend, don't duplicate, for D-09's weekly-pivot rollup.
- `market_data_ohlcv_tradeable` — the view both live and batch paths already read OHLCV from; no
  new data-access pattern needed for any of the 5 files.

### Established Patterns
- Session-boundary-reset accumulation: `update_wk_vwap()` (ISO week) — template for both D-08
  (NY-session boundary) and D-09 (extending the same ISO-week accumulator with high/low/close).
- Stateless windowed computation inline in `compute()`/`compute_batch()`: the pattern
  `swing_detector.py`/`swing_momentum.py`/`trend_structure.py`/`fibonacci_zones.py` all already
  fit (bounded-lookback, no cross-bar state needed) — same shape as Phase 163's S/R computation.
- Nullable `FeatureVector` fields (`float | None`): `poc_dist_atr`'s existing precedent — D-01's
  fix for `trend_structure`/`swing_detector` follows this exactly.
- APR migrate-as-you-go: `_config_service` module-level pattern / `cfg.get_sync(key, fallback)`
  per CLAUDE.md; six new namespaces needed (`feature.swing.*`, `feature.trend_structure.*`,
  `feature.swing_momentum.*`, `feature.fib.*`, `feature.session_levels.*`, plus reuse of the
  existing `feature.session.*`).

### Integration Points
- `FeatureCache` dataclass (`feature_cache.py`) — needs new fields for D-08's session-boundary
  mutator state and D-09's weekly high/low/close accumulators. Unlike Phase 163's original 4
  fields, **none of this phase's fields pre-exist as stub columns** — every one is genuinely new
  (no `poc_dist_atr`-style "just populate the stub" shortcut available here).
- `FEATURE_VECTOR_DOMAIN` dict (`feature_factory.py`) — needs 41 new entries (25 from the 4
  direct-port files, incl. D-15's `swing_volume_confirmation` + 16 from `session_levels.py`, incl.
  D-13's `gap_filled`), all tagged `"structural"`.
- `compute()` (live) and `compute_batch()` (backfill) — both need all 5 files' computation wired
  in from scratch; recommend one shared local computation of swing high/low per bar (D-05) feeding
  both `swing_detector`'s own output and `fibonacci_zones`'s fib-level math, to avoid computing
  `find_peaks`/`find_troughs` twice per bar for the same underlying pivots.
- `feature_registry` (migration) — 41 new rows, `group_name='session'`, `tier='2_theory'` for all
  (see Canonical References above for the exact `normalization` vocabulary per field shape).

</code_context>

<specifics>
## Specific Ideas

This phase closes out the same "port the rest of `i3_structure`" survey that produced Phase 163,
and is also the other half of the dependency chain Phase 163's D-14 named: `ctx_SRConsensus`
(deferred in 163) depends on swing points, fib zones, and session levels as candidate S/R sources
alongside Phase 164's SMC atomics — this phase is what makes that richer S/R system buildable
later, once both 165 and 164 exist. Not a reason to rush either; just the reason this phase's
`ROADMAP.md` registration explicitly calls it out as "the other missing link in that chain."

The project owner's implicit framing (via the ROADMAP survey) was "port everything that's cheap
and clean, park what needs a bigger prerequisite" — confirmed as the right instinct; this
research mostly validates that framing while correcting the specific file-by-file execution
(especially the two silent-wrong-answer bugs in D-01, which the original survey's "valid as-is"
language would have let through unnoticed).

</specifics>

<deferred>
## Deferred Ideas

- **`macd_events.py` and the MACD indicator itself** (D-10) — park until/unless MACD becomes a
  wanted primitive in its own momentum/oscillator-family phase. Not this phase's naming-system
  domain (structural swing/fib/trend geometry vs. an oscillator-event layer).
- **`bocpd_changepoint.py`** (D-11) — needs a standalone latency benchmark at 58-ETF × 4-TF
  backfill scale before being assigned to any phase. Real Renaissance-style value (assumption-
  light online regime-break detection) once the cost question is answered.
- **`ctx_SRConsensus`'s richer, cross-method-confirmed S/R system** (referenced in
  `163-CONTEXT.md`'s D-14 — a different document's D-14, not this phase's own D-14 below; the
  numbering coincidence is unrelated) — this phase is one of its two remaining prerequisites
  (alongside Phase 164's SMC atomics); still not built until both exist and a phase is explicitly
  scoped for it.
- **Fibonacci extension levels (1.272/1.618/2.0)** (this phase's own D-14) — deferred, not built,
  because the base 4 fib-retracement fields have zero IC evidence yet; building extensions now
  would scale an unproven hypothesis family before its first member is measured. Revisit only if
  `nearest_fib_ratio`/`nearest_fib_dist_atr` clear the incremental-IC promotion bar.
- **`bars_since_gap_fill` velocity companion to `gap_filled`** (D-13) — deliberately not bundled
  in now (one concept, one column); revisit only if `gap_filled` itself shows real IC.
- **Running the actual incremental-IC promotion test** (D-12, extending Phase 163's D-07) — this
  phase builds and wires the primitives so they produce real values; the IC measurement itself
  runs through the existing `ic_engine`/corpus pipeline on whatever cadence that next runs, not as
  a bespoke script in this phase's scope.
- **`nearest_session_level_type` categorical companion** (Claude's Discretion note above) — cheap
  addition, not required; revisit if `nearest_level_dist_atr` shows real IC and interpretability
  of *which* level matters.
- **Housekeeping: stray duplicate `src/intelligence/features/smc_context/` directory** (D-11's
  note) — mostly a dead leftover copy of `archive/smc_context/`, except the live `hmm_regime.py`.
  Worth a one-line cleanup todo, explicitly not part of this phase.

</deferred>

---

*Phase: 165-Swing/Fib/Trend Structure Primitives*
*Context gathered: 2026-07-20 via Fable 5 dispatch*
