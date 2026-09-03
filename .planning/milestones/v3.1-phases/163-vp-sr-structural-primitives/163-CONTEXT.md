# Phase 163: VP/SR Structural Primitives - Context

**Gathered:** 2026-07-20
**Status:** Ready for planning
**Source:** Conversation discussion (project owner + Fable 5 dispatch), not a formal /gsd-discuss-phase session — equivalent rigor, different transport.

**Authoritative final scope (read this, not the historical narrative below, for the actual column count):** 21 total structural `FeatureVector` fields — 4 original + 17 new (12 VP per D-16/D-17/D-18 + 5 S/R per D-19). The prose below and the decision log accumulated this incrementally across three review rounds (9→10→12 for VP, then +5 for S/R) — every intermediate count you'll read is a historical snapshot, not a live figure.

<domain>
## Phase Boundary

Implement real computation for the 4 structural feature columns (`poc_dist_atr`, `va_position`,
`sr_support_dist`, `sr_resist_dist`) that have been permanently stuck at constant `FeatureCache`
defaults since the v3.0 rebuild — nothing has ever computed real values for them, in either the
live or batch path, despite the columns existing in `feature_vectors`/`FeatureVector` and being
scored every corpus run (`feature_ic_scores.ic_value=0` for all 5,510 cells is a constant-input
artifact, not a real IC measurement). This closes todo 153
(`.planning/todos/pending/153-vp-sr-features-null-in-batch-corpus.md`).

Two independent sub-features:
1. **POC/value-area** — session-anchored, volume-weighted price-bucket histogram. Point of
   control (POC) = highest-volume bucket; value area (VA) = bucket range expanded until it holds
   a configurable fraction (default 70%) of total volume. Feeds `poc_dist_atr` (distance from
   close to POC, ATR-normalized) and `va_position` (bounded [0,1] position within the VA band).
   **Scope widened same session (D-13/D-16 below):** port the richer, already-working
   `ctx_VolumeProfile` (I4) plugin instead of the thinner `i3_structure/market_profile.py`
   originally identified — adds ATR-normalized directional HVN/LVN distances, `va_width_atr`,
   `distance_to_vah_atr`/`distance_to_val_atr`, `price_in_value_area` (9 new columns beyond the
   original 4, per D-16's correction — raw price levels like `poc_price`/`vah`/`val` are
   intermediate values, not persisted as ML features) at the same computation/porting cost, since
   it's the same underlying histogram with more outputs read off it.
2. **Support/resistance** — rolling-window local-pivot clustering. Feeds `sr_support_dist`/
   `sr_resist_dist` (distance from close to nearest support/resistance cluster, ATR-normalized).
   Deliberately staying with the simple self-contained approach, not `ctx_SRConsensus`'s
   multi-plugin confluence system (see D-14). **Scope widened later session (D-19 below):** the
   same clustering pass also yields `resistance_strength`/`support_strength` (volume-weighted),
   `resistance_age_bars`/`support_age_bars`, and `sr_level_count` at effectively zero extra cost —
   5 new columns beyond the 2 distance fields.

</domain>

<decisions>
## Implementation Decisions

### Do not port the archived plugins literally
- **D-01:** The real computation logic exists only in the archived v2.x plugin
  (`src/intelligence/features/i3_structure/market_profile.py`,
  `src/intelligence/features/i3_structure/support_resistance.py`), which was never connected to
  v3. Fable's 2026-07-20 analysis (this phase's RESEARCH.md) found `market_profile.py` has a real
  correctness bug worth not inheriting: its incremental path (`_compute_next_core`) only ever
  appends to `volume_buckets` and never evicts, so `bar_count` grows unbounded and silently
  diverges from what `_compute_full_core` would produce on the same window. It also uses TPO
  touch-count (how many bars touch each price bucket) rather than actual traded volume — a
  weaker proxy than doing this properly now that we're rebuilding it anyway.
- **D-02:** `support_resistance.py` is clean and reusable as a reference (bounded window,
  `find_peaks`/`find_troughs` are already live utilities in `src/intelligence/utils.py`, not
  archived) but reports distance as a raw percentage (`resistance_dist_pct`/`support_dist_pct`),
  not ATR units — the new implementation must convert to ATR units to match this phase's schema
  fields' implied normalization (dividing by the already-computed `atr_val`).

### Reimplementation approach (not a literal port)
- **D-03: POC/VA** — session-anchored (reset at NY session open), volume-weighted price-bucket
  histogram — actual traded volume per bucket, not TPO touch-count. New
  `FeatureCache.update_session_vp(bar_ts, high, low, close, volume, config)` mutator, called once
  per bar by both the live pipeline and backfill — same call-site pattern as `advance_bar`/
  `update_wk_vwap`. `FeatureCache.update_wk_vwap()` (feature_cache.py:142) is the direct wiring
  template: it already does session-boundary-reset accumulation (resets at ISO-week change); the
  new mutator follows the same shape, keyed on session boundary
  (`feature.session.ny_start_utc_hour/minute`, the existing APR key used by `_in_ny_session`)
  instead of ISO week.
- **D-04: Support/Resistance** — bounded rolling-window (~60-120 bars per timeframe, matching the
  archived plugin's `_LOOKBACK_BY_TF` shape) pivot clustering via the live `find_peaks`/
  `find_troughs` utilities. **No cache mutator needed** — this is stateless per-window, computed
  directly inline in `compute()`/`compute_batch()`, the same pattern already used for CMF/CCI/
  `range_position` (windowed, non-series structural features that don't need session-boundary
  state).
- **D-05:** Remove the "requires I3 intraday injection" `None`-branch in `compute_batch()`
  (`feature_factory.py` ~line 3722) and the matching stale comment in `schemas.py` (~line 1262).
  Both are factually wrong — neither archived plugin touches anything beyond `high`/`low`/
  `close`/`volume` arrays over a bounded window, all available from
  `market_data_ohlcv_tradeable` in both live and backfill paths. There is no tick-data or I3
  pipeline dependency; that comment was an inherited, never-verified assumption.

### APR keys (migrate-as-you-go, new namespaces)
- **D-06:** All new thresholds go under `feature.session_vp.*` / `feature.sr.*` — direct
  APR-backed copies of the archived plugin's hardcoded constants (value-area coverage fraction
  default 0.70 `[conventional]`, bucket count / tick-size divisor, pivot window default 10,
  cluster radius multiplier default 0.5 × ATR, S/R lookback per timeframe). No new hardcoded
  numeric constants in `src/` or `services/` per CLAUDE.md's APR mandate.

### Promotion bar — this is the load-bearing decision from this session's discussion
- **D-07:** Standalone IC>0 is NOT sufficient promotion evidence for the original 4 features, and
  the same standard applies to D-13's additional `ctx_VolumeProfile` fields (`va_width_atr`,
  `distance_to_vah_atr`/`distance_to_val_atr`, HVN/LVN distances) once they exist. The project
  owner and Claude jointly identified that `vwap_dev_sigma`, `bb_pct_b_fast/slow`,
  `price_percentile_fast/slow`, and `dist_from_high/low_fast/slow` (all already live in
  `FEATURE_VECTOR_DOMAIN`) occupy the same conceptual neighborhood — "distance to a reference
  level" or "position within a band" — as the new features. `dist_from_high/low_fast/slow` in
  particular is functionally a simpler version of support/resistance (distance to rolling window
  extreme vs. this phase's multi-touch pivot clustering). Whatever IC evaluation this phase runs
  (or hands off to the next corpus/IC measurement step) MUST test **incremental contribution**
  over this existing near-neighbor family — the todo 037/038-style partial-IC methodology
  (measuring incremental IC after controlling for parent/sibling atomics), not just raw
  standalone IC significance. This phase's own scope is building + wiring the primitives
  correctly; running the full incremental-IC promotion test happens via the existing
  `ic_engine`/corpus pipeline once these features start producing real (non-constant) values —
  scope this phase's plan to stop at "correct, real, non-constant values are computed and
  persisted for both live and batch," not at "promoted to ensemble weights."

### Why build now, not defer (historical context, do not re-litigate)
- **D-08:** This exact feature set was already litigated once (2026-06-30): Phase A IC analysis
  flagged it "zero-IC" and deleted it from the schema (`a270fb09`), then reverted ~25 minutes
  later (`e9a635a7`, `2870403b`) on the explicit principle "never delete signal candidates...
  re-evaluate after Phase B corpus re-run on corrected ic_engine." That re-evaluation never
  happened, and the original "zero-IC" reading was itself almost certainly a constant-input
  artifact (same root cause as today), not a real measurement. Deleting again without ever
  measuring the real computation would repeat the same unforced error — this is the reasoning
  basis for building now rather than re-deferring under todo 153's option 2 (delete).

### Claude's Discretion
- Exact bucket count / price-bin sizing for the POC/VA histogram (data-driven per timeframe,
  reasonable default e.g. ~50-100 buckets spanning the session's high-low range).
- Exact `FeatureCache` internal state shape for the session-VP accumulator (a bucket dict, same
  general shape as the existing `_wk_tp_vol_sum`/`_wk_vol_sum` accumulators, generalized to N
  buckets).
- Whether support/resistance clustering reuses `_LOOKBACK_BY_TF`'s exact per-timeframe values
  from the archived plugin or re-derives its own (APR-backed either way).

### Scope widened same session: port ctx_VolumeProfile, not i3_structure/market_profile.py
- **D-13:** `src/intelligence/context/volume_profile.py` (`VolumeProfilePlugin`, `ctx_VolumeProfile`,
  I4 tier) is a strictly better port source than `i3_structure/market_profile.py`: self-contained
  (only needs OHLCV + ATR, no cross-plugin fusion), **non-incremental by design**
  (`compute_next` just calls `compute_full` again — sidesteps D-01's unbounded-accumulator bug
  entirely rather than needing a fix), uses real volume-weighted histograms (not TPO
  touch-count), and computes BOTH a session track (reset at 09:30 ET) and a rolling track
  in the same pass. **Correction (D-18, third Fable review):** the rolling track is documented as
  "480 bars" (`_ROLLING_WINDOW = 480`, line 30) but the plugin's own `InputSpec(lookback=390)`
  (line 70) caps `len(df)` at 390 in practice, so `roll_n = min(480, len(df))` (line 258) always
  resolves to ≤390 bars — the 480-bar window is currently unreachable; it's really a ≤390-bar
  window, the same size as the session cap. The underlying two-window mechanism (and the reason it
  was chosen as the port source) still holds; only the "480-bar" figure was inaccurate. Its 18 outputs (`poc_price`, `vah`, `val`, `poc_price_rolling`,
  `vah_rolling`, `val_rolling`, `nearest_hvn_above/below`, `nearest_lvn_above/below`,
  `price_in_value_area`, `va_width_atr`, `distance_to_vah_atr`, `distance_to_val_atr`,
  `nearest_hvn_level`, `nearest_hvn_dist_atr`, `nearest_lvn_level`, `in_lvn`) map cleanly onto
  this phase's `poc_dist_atr`/`va_position` fields (compute `poc_dist_atr = (close - poc_price) /
  atr`, `va_position = (close - val) / (vah - val)` clamped [0,1]) while adding the rest as new
  atomic `FeatureCache`/`FeatureVector` fields at the same porting cost — it's the same histogram
  computation, just reading more values off it. Confirmed no known bugs (unlike D-01's finding on
  the older plugin) and no cross-plugin dependency (unlike `ctx_SRConsensus`, see D-14).

### D-16 (correction, same session): raw price levels are NOT valid FeatureVector columns
  Verified directly in `context/volume_profile.py` (lines 152-166, 279-300): `ctx_VolumeProfile`'s
  `poc_price`/`vah`/`val`/`poc_price_rolling`/`vah_rolling`/`val_rolling`/`nearest_hvn_above`/
  `nearest_hvn_below`/`nearest_lvn_above`/`nearest_lvn_below`/`nearest_hvn_level`/
  `nearest_lvn_level` are ALL raw price levels (e.g. `nearest_hvn_above = float(hvn_above.min())`
  — an actual bucket price), not ATR-normalized distances. Raw price is not a valid ML/IC feature
  in v3: it's non-stationary across time and non-comparable across symbols (a $400 SPY POC and a
  $30 ETF POC are not the same scale), which breaks cross-sectional IC measurement. This was fine
  in v2.x because these fields fed I7 trading plugins that computed their own ATR-normalization
  at consumption time (e.g. `poc_rejection.py`'s `abs(close - poc_price) / atr_14`) — v3's
  `FeatureFactory` has no such consumer; it only feeds `ic_engine`/ensemble training directly.

  **Corrected field list — every new `FeatureCache`/`FeatureVector` column must be ATR-distance
  or a bounded flag/position, never a raw price:**
  - `nearest_hvn_above_dist_atr = (nearest_hvn_above - close) / atr` (compute internally from the
    raw value, only persist the distance) — same for `nearest_hvn_below_dist_atr`,
    `nearest_lvn_above_dist_atr`, `nearest_lvn_below_dist_atr`.
  - `price_in_value_area` (flag), `in_lvn` (flag), `va_width_atr`, `distance_to_vah_atr`,
    `distance_to_val_atr` — already correctly ATR-normalized/bounded in the source, keep as-is.
  - `poc_price`, `vah`, `val`, `poc_price_rolling`, `vah_rolling`, `val_rolling`,
    `nearest_hvn_level`, `nearest_lvn_level` — **do NOT add these as `FeatureVector` columns.**
    They are intermediate values only. `poc_dist_atr`/`va_position` already derive from the
    session-track POC/VAH/VAL; a rolling-vs-session divergence is available if wanted as
    `poc_rolling_vs_session_dist_atr = (poc_price_rolling - poc_price) / atr`, but do not persist
    the raw levels themselves. `nearest_hvn_level`/`nearest_lvn_level` are fully superseded by the
    ATR-distance directional fields above — the legacy `nearest_hvn_dist_atr` (already
    ATR-normalized in the source) is the one exception worth keeping as-is.

### D-17 (correction, same session, per Fable 5's independent review): field-list errors in D-16
  Fable's review of the corrected D-16 scope (dispatched to independently verify D-13 through
  D-16 before execution, since none of the post-original-dispatch work had a second opinion)
  found two real issues, verified directly against `context/volume_profile.py`:

  1. **`in_lvn` was silently dropped.** RESEARCH.md Section 2's own prose lists `in_lvn` (line
     235: `1.0 if s_vol_hist[cur_bucket] <= vol_threshold_low else 0.0`, a bounded flag, not a raw
     price) alongside the other correctly-normalized fields, but D-16's final column list omitted
     it with no stated reason — an accidental drop, not a deliberate exclusion. `in_lvn` measures
     something genuinely distinct from `price_in_value_area` (local current-bucket volume
     thinness / liquidity-void detection vs. value-area membership) — added back above.

  2. **`va_width_atr` is exact algebraic collinearity, not just conceptual overlap.** From
     `volume_profile.py:249-253`: `distance_to_vah_atr + distance_to_val_atr =
     ((vah-close)+(close-val))/atr = (vah-val)/atr = va_width_atr`, identically, for every row
     where all three are non-null (same guard conditions). This is perfect linear dependency
     within this phase's own proposed columns — stronger than the cross-family conceptual overlap
     D-07 already screens for. **Decision: keep `va_width_atr` as a persisted column anyway** — it
     has a legitimate standalone interpretation (day-type / balance-vs-trend indicator, a
     recognized market-profile concept in its own right, not merely a byproduct), and known linear
     dependencies are exactly what todo 038's collinearity diagnostic and the standard IC/ensemble
     pipeline are built to handle. The point of this correction is that the redundancy is now
     **documented, not silently present** — do not treat this as new information distinct from the
     other two distance fields when interpreting IC results across this trio.

  **Final, corrected new `FeatureCache`/`FeatureVector` fields beyond the original 4 (10 columns,
  not 9, not 14):** `nearest_hvn_above_dist_atr`, `nearest_hvn_below_dist_atr`,
  `nearest_lvn_above_dist_atr`, `nearest_lvn_below_dist_atr`, `price_in_value_area`, `in_lvn`,
  `va_width_atr`, `distance_to_vah_atr`, `distance_to_val_atr`, `nearest_hvn_dist_atr` — all new
  entries needed in `FEATURE_VECTOR_DOMAIN` (tag `"structural"`) and a migration for the new
  `feature_vectors` columns (unlike the original 4, which already existed).

  Fable's review also confirmed D-14 (S/R deferral) and D-15 (Phase 164 split) both hold as
  written, with one correction: the round-number candidate logic (`_round_candidates`) actually
  lives in `sr_consensus.py:78-90` itself, not in `zone_engine.py` — self-contained, but still not
  worth bolting onto Phase 163 now (a third "distance to level" concept adds to D-07's collinearity
  concern without resolving the actual blocking dependency chain). See Phase 164's ROADMAP.md entry
  for the SMC raw-price-trap warning this review also produced.

### D-18 (addition, same session, per a third Fable review): rolling-track POC primitives
  The project owner asked "didn't we have more than 10 atomic primitives for 163" — a real gap:
  D-13's rationale for choosing `ctx_VolumeProfile` explicitly cited its rolling-track
  computation as a strength, but the corrected 10-column list only derived features from the
  session track, leaving the rolling track's already-computed output (`poc_price_rolling`,
  `vah_rolling`, `val_rolling`) completely unused. A third independent Fable review assessed
  which rolling-track derivatives are legitimate additions vs. scope creep, verifying directly
  against `volume_profile.py` rather than trusting the task framing (and caught that the
  framing's claim "no rolling VA is computed" was itself wrong — `vah_rolling`/`val_rolling`
  already exist at zero extra computation cost, same call as `poc_price_rolling`).

  **Add exactly 2 new columns:**
  - `poc_rolling_dist_atr = (close - poc_price_rolling) / atr` — the rolling-track equivalent of
    `poc_dist_atr`. Not collinear with it in general: early in a session, `session_df` has few
    bars (since today's 09:30 open) while `roll_df` is a fixed trailing ≤390-bar slice dominated
    by prior-session bars — the two POCs only converge near session close. A structural,
    time-of-day-dependent reason to expect real divergence, not window-size noise.
  - `poc_session_rolling_divergence_atr = (poc_price - poc_price_rolling) / atr` — the most
    conceptually distinct candidate: session dislocation from the multi-day value anchor, an
    open-drive/trend-day vs. balance-day signal (first-order auction-market-theory concept, not
    just another "distance to X" restatement). **Exact algebraic identity, same treatment as
    `va_width_atr` (D-17):** `poc_session_rolling_divergence_atr = poc_rolling_dist_atr −
    poc_dist_atr`, identically, once both exist. Keep anyway — genuine standalone economic
    meaning, known linear dependency documented rather than silently present, let todo 038's
    collinearity diagnostic and D-07's incremental-IC bar do their job.

  **Explicitly rejected, not on cost grounds (both are cheap — `vah_rolling`/`val_rolling`
  already exist) but on scope/collinearity-family-size discipline:**
  - `va_position_rolling`, `distance_to_vah_rolling_atr`, `distance_to_val_rolling_atr`,
    `va_width_rolling_atr` — would parallel-duplicate the entire session-VA family without a
    distinct new hypothesis the way `poc_session_rolling_divergence_atr` has one. D-17's
    dispensation for keeping one collinear feature (`va_width_atr`) doesn't stretch to a whole
    second VA family speculatively. Revisit only if the two accepted fields show real incremental
    IC once measured.
  - Rolling-track directional HVN/LVN (`nearest_hvn_above_rolling_dist_atr`, etc.) — would need
    genuinely new code (a second `_compute_directional_nodes()` call), same rejection logic as
    above with a stronger cost argument on top.

  **Final new-column count for Phase 163: 12, not 10** (the 10 from D-16/D-17 plus these 2). This
  is the VP-family count only — see D-19 below for the S/R additions that bring the phase-wide
  total to 17 new columns / 21 structural fields.

### S/R stays narrow — ctx_SRConsensus explicitly deferred, not silently adopted
- **D-14:** `src/intelligence/context/sr_consensus.py` (`ctx_SRConsensus`, Phase 116) is a
  materially richer S/R implementation — it aggregates candidate levels from swing points, fib
  zones, session levels, SMC order blocks/FVGs (via `zone_engine.collect_sr_candidates`), plus
  round numbers, then scores cross-method agreement (`sr_support_confluence_score`). Better
  signal in principle (multiple independent methods agreeing = stronger evidence), but it
  requires either porting or reimplementing the whole candidate-source constellation first
  (swing detection, fib zones, session levels, and Phase 164's SMC order-block/FVG primitives).
  **Deliberately deferred, not built in this phase** — Phase 163 stays with the simple,
  self-contained rolling-window pivot-clustering approach (D-02/D-04). Revisit `ctx_SRConsensus`
  once Phase 164's SMC atomics exist, since it explicitly depends on some of them.

### Sibling phase filed for the wider "institutional accumulation/distribution" family
- **D-15:** The project owner asked whether v2.x's smart-money-concepts (SMC) plugins — order
  blocks, fair value gaps, liquidity sweeps/pools, supply/demand zones, AMD (accumulation-
  manipulation-distribution) cycle, breaker/mitigation blocks, BOS/CHoCH — could become v3 atomic
  primitives too. Confirmed: all ~10 plugins in `src/intelligence/archive/smc_context/` are
  self-contained on the same shared utilities this phase already uses (`find_peaks`/
  `find_troughs`, plus `clamp`/`linear_ramp`/`freshness_decay`), ~2,484 lines total, no
  cross-plugin dependency chain. **Filed as Phase 164 (SMC Institutional Footprint Primitives),
  not folded into this phase** — distinct enough in scope (8+ separate detection concepts) to
  warrant its own plan and promotion-bar discipline, sequenced after this phase for shared
  conventions (ATR-distance normalization, APR namespace pattern, incremental-IC methodology).
  Full detail in Phase 164's ROADMAP.md entry / CONTEXT.md once planned.

### D-19 (correction, later session, per Codex cross-AI review + direct source verification): S/R plan was discarding 5 free fields
  Codex's review (163-REVIEWS.md) flagged Plan 03's S/R port as underspecified relative to the
  archived source ("minimal cluster-to-mean-price is sufficient"). Verified directly against
  `src/intelligence/features/i3_structure/support_resistance.py`: the plugin's `_cluster_levels`/
  `_finalize_cluster` helpers — which Plan 03 already has to run to get `sr_support_dist`/
  `sr_resist_dist` — also produce `resistance_strength`/`support_strength` (volume-weighted
  cluster strength: sum of `min(2.0, member_volume/mean_volume)` per cluster member, capped per
  member but unbounded in aggregate across cluster size — a comparable, no-price-unit metric, not
  ATR-normalized because it isn't a distance), `resistance_age_bars`/`support_age_bars` (bars
  since the nearest cluster's most recent touch — a bar count, same category as the already-used
  `swing_high_age_bars`/`trend_duration_bars`/`macd_cross_bars_ago` precedent: comparable across
  symbols, not price-scale-dependent, no ATR conversion needed), and `sr_level_count` (total
  distinct resistance+support clusters found in the lookback window — a structural-complexity/
  consolidation-vs-trending indicator, also a plain count). None of these 5 are raw price levels
  (D-16's rule doesn't apply) — they were simply never asked for by Plan 03's narrower interface,
  not excluded for a stated reason. **Decision: add all 5 to this phase's scope** — they come at
  effectively zero extra computation cost (the clustering pass already runs), and per D-08's
  "never delete/skip signal candidates without measuring" reasoning, skipping them here would
  repeat the same unforced-omission pattern D-08 was written to avoid, just one plan later.

  **Migration 243 (Plan 01) grows from 12 to 17 new columns**: the same 12 VP columns (D-16/D-17/
  D-18) plus these 5 new S/R columns. **Total structural `FeatureVector` fields for Phase 163
  becomes 21** (4 original + 12 new VP + 5 new S/R), not 16. `feature_registry` rows: use
  `normalization='none'` for `resistance_strength`/`support_strength`/`sr_level_count` (no ATR
  distance, no [0,1] bound — plain comparable scalars) and `normalization='none'`,
  `is_bounded=false` for `resistance_age_bars`/`support_age_bars` (bar counts, same treatment as
  existing bar-count fields elsewhere in the codebase). Plan 03's Task 1 must call the fuller
  `_cluster_levels`/`_finalize_cluster` port (strength + latest-touch tracking), not the
  "minimal cluster-to-mean-price" shortcut its original action text described — the fuller
  version is barely more code since Plan 03 already needs cluster membership to find the nearest
  level on each side.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Primary port source (D-13/D-14 — use these, not the tier-I3 plugins below)
- `src/intelligence/context/volume_profile.py` (`VolumeProfilePlugin`, `ctx_VolumeProfile`, I4
  tier) — the actual POC/VA/HVN/LVN port source. Read in full before planning; `compute_full()`
  (lines 179-301) is the reference algorithm, `_compute_profile()`/`_compute_value_area()`/
  `_compute_directional_nodes()` are the reusable sub-steps.
- `src/intelligence/context/sr_consensus.py` (`ctx_SRConsensus`, Phase 116) — read for context on
  why it's deferred (D-14), NOT a port source for this phase. Depends on
  `src/intelligence/trading/zone_engine.py`'s `collect_sr_candidates`/`find_best_level`, which in
  turn pulls from swing/fib/session-level/SMC plugin outputs — the reason it's out of scope here.

### Superseded archived reference (read only for D-01's bug-avoidance rationale)
- `src/intelligence/features/i3_structure/market_profile.py` (`MarketProfilePlugin`,
  `_compute_full_core`, `_compute_next_core`) — POC/value-area/TPO logic; has the unbounded-
  accumulator bug (D-01), uses touch-count not real volume. Superseded by `ctx_VolumeProfile`
  (D-13) as the actual port source — kept here only so the bug this phase avoids is documented.
- `src/intelligence/features/i3_structure/support_resistance.py` — pivot clustering via
  `find_peaks`/`find_troughs`, `_LOOKBACK_BY_TF`, ATR-based cluster radius; reports percentage
  distance, needs ATR-unit conversion (D-02). This one IS still the S/R port source (D-14) —
  simpler and self-contained, unlike `ctx_SRConsensus`.

### Phase 164 cross-reference (sibling phase, D-15)
- `src/intelligence/archive/smc_context/` — order blocks, FVG, liquidity sweeps/pools,
  supply/demand zones, AMD cycle, breaker/mitigation blocks, BOS/CHoCH. Not this phase's scope;
  see Phase 164 in ROADMAP.md.

### v3 wiring templates (the pattern to follow)
- `src/intelligence/feature_cache.py` — `FeatureCache` dataclass; `update_wk_vwap()` (line ~142)
  is the direct template for D-03's new `update_session_vp()` mutator (session-boundary-reset
  accumulation pattern). The 4 target fields already exist here (lines 65-68) with stub defaults
  — no schema/dataclass migration needed, just populate them for real.
- `src/intelligence/feature_factory.py` — `FEATURE_VECTOR_DOMAIN` dict (lines 58-83, includes the
  4 target fields tagged `"structural"`); `compute()`/`compute_batch()` sections around lines
  3084-3087, 3238-3241, 3447-3455, 3542-3545, 3700-3841, 4108-4110 (current stub wiring to
  replace); CMF/CCI/`range_position` computation as the template for D-04's stateless windowed
  S/R computation.
- `src/intelligence/schemas.py` — `FeatureVector` dataclass, lines 1262-1266 (stale "requires I3
  intraday injection" comment to remove per D-05).
- `src/intelligence/utils.py` — `find_peaks`/`find_troughs` (live, directly reusable, D-04).

### Historical record (why this was reverted from deletion once already — D-08)
- Commit `a270fb09` — original "zero-IC" deletion (2026-06-30).
- Commits `2870403b`/`e9a635a7` — revert with the "never delete signal candidates" reasoning
  (2026-06-30, ~25 min later).
- Commit `ba96feb4` — later cleanup of a stale removal (superseded by the revert; historical
  interest only).

### Todo / roadmap cross-references
- `.planning/todos/pending/153-vp-sr-features-null-in-batch-corpus.md` — the todo this phase
  closes; full prior investigation trail.
- `.planning/todos/pending/037-interaction-primitives-pilot-ic-test.md` (completed/) and
  `.planning/todos/pending/038-cross-sectional-collinearity-diagnostic.md` — the incremental-IC
  methodology D-07's promotion bar reuses.
- `.planning/ROADMAP.md` "Phase 151: Feature Primitives Expansion" — sibling atomic-expansion
  phase (todo 066, todo 104); this phase is NOT folded into 151's interaction-layer waves.

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `find_peaks`/`find_troughs` (`src/intelligence/utils.py`) — live, already used elsewhere; S/R
  clustering reuses these directly rather than reimplementing pivot detection.
- `atr_val` — already computed in `compute()`/`compute_batch()` before the VP/SR block; both new
  features' ATR-normalization reuses this existing value, no new ATR computation needed.
- `market_data_ohlcv_tradeable` — the view (not raw `market_data_ohlcv`) both live and batch
  paths already use for OHLCV reads; VP/SR computation reads from the same source, no new data
  access pattern.

### Established Patterns
- Session-boundary-reset accumulation: `update_wk_vwap()` in `feature_cache.py`.
- Stateless windowed computation inline in `compute()`/`compute_batch()`: CMF, CCI,
  `range_position`.
- APR migrate-as-you-go: `_config_service` module-level pattern / `cfg.get_sync(key, fallback)`
  per CLAUDE.md.

### Integration Points
- `FeatureCache` dataclass fields (lines 65-68) — already declared, populate don't add.
- `FEATURE_VECTOR_DOMAIN` dict — already has all 4 fields tagged `"structural"`, no registry
  change needed.
- `compute()` (live) and `compute_batch()` (backfill) — both need the new computation wired in;
  currently both paths read/pass through stub defaults or `None`.

</code_context>

<specifics>
## Specific Ideas

Project owner's original framing: "these seem like they could be used and tell info about how
far from resistance and support a bar is and ATR [distance]" — confirmed as a plausible, testable
hypothesis grounded in established auction-market-theory (POC/value area) and technical-analysis
(support/resistance) constructs. The overlap check against existing near-neighbor features
(`vwap_dev_sigma`, `bb_pct_b`, `dist_from_high/low`) was the project owner's own follow-up
question and is now D-07's promotion-bar decision — the distinguishing value of this phase's
features is specifically (a) real volume-weighting (not OHLC extremes or VWAP's linear
weighting) and (b) multi-touch pivot significance (levels tested more than once), which is
exactly what needs measuring, not assuming.

</specifics>

<deferred>
## Deferred Ideas

- **Running the actual incremental-IC promotion test** (D-07) — this phase builds and wires the
  primitives so they produce real values; the IC measurement itself runs through the existing
  `ic_engine`/corpus pipeline on whatever cadence that next runs, not as a bespoke one-off script
  in this phase's scope.
- **Phase 151's Theory-Motivated Interaction Layer** — unaffected by this phase; these 4 features
  remain atomic primitives, not interaction terms.
- **`compute_frame_geometry()` becoming S/R-aware** (found 2026-07-21 fixing todo 162, filed as
  todo 163/deferred) — `services/alpha_frame_writer.py`'s frame stop/target geometry is
  currently ATR-only "because `sr_support_dist`/`sr_resist_dist` are 100% NULL across the
  corpus." Once this phase makes those columns real, there's a legitimate design question
  (should a stop ever sit tighter than real S/R structure?) worth its own scoping pass — not
  in this phase's scope, but don't let it get lost once these columns go live. See
  `.planning/todos/deferred/163-frame-geometry-sr-aware-stops-once-phase-163-lands.md`.

</deferred>

---

*Phase: 163-VP/SR Structural Primitives*
*Context gathered: 2026-07-20 via conversation discussion + Fable 5 dispatch*
