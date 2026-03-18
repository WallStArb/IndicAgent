# Phase 34: I4 Infrastructure — Anchored VWAP + Volume Profile - Context

**Gathered:** 2026-03-17
**Status:** Ready for planning

<domain>
## Phase Boundary

Migrate and upgrade two existing computation plugins to I4/context/ (AnchoredVWAP from I3/structure, VolumeProfile from I5/patterns), extending each with richer fields that I7 setups require. Implement five I7 plugins consuming this new I4 infrastructure: trad_AnchoredVWAPReversion, trad_VWAPReclaim, trad_POCRejection, trad_HVNRejection, trad_LVNBreakout.

Design framing: Renaissance — one canonical computation per feature, instrument everything, let the training pipeline discover which signals have alpha.

</domain>

<decisions>
## Implementation Decisions

### Plugin Architecture — Upgrade + Migrate (no duplication)

- **Do NOT create new parallel plugins** — two overlapping plugins already exist; duplicate feature names (`session_vwap` vs `avwap_session`) would introduce multicollinearity that silently degrades the logistic regression in `weight_updater.py`
- **Migrate `structure/anchored_vwap.py` → `context/anchored_vwap.py`**: keep all existing output names (`session_vwap`, `swing_vwap`, `weekly_vwap`, `above_session_vwap`, `vwap_alignment_score`, etc.), add new I4 fields (bands, deviation sigma, velocity). Update TIER_I3 → TIER_I4. One canonical VWAP computation.
- **Migrate `patterns/volume_profile.py` → `context/volume_profile.py`**: keep existing output names (`nearest_hvn_level`, `nearest_hvn_dist_atr`, `nearest_lvn_level`, `in_lvn`), add new fields (poc, vah, val, session/rolling dual track, VA context). Update TIER_I5 → TIER_I4. One canonical volume profile computation.
- DAG ordering: both now in I4 — run after I3 (swings available for swing VWAP anchor) and before I7 (features available for setups). No ordering issue.

### AnchoredVWAP — New I4 Fields

- **`avwap_upper_band`, `avwap_lower_band`**: computed for session VWAP anchor — `session_vwap ± N × std(typical - session_vwap)` over session window. Both upper and lower bands logged.
- **`swing_vwap_upper_band`, `swing_vwap_lower_band`**: same std band calculation anchored to swing VWAP. Logged as training features — weight updater discovers whether swing VWAP extension has independent alpha beyond session VWAP extension.
- **`session_vwap_deviation_sigma`**: `(close - session_vwap) / std(typical - session_vwap)` — how many standard deviations price is from session VWAP. Continuous value logged every bar (not just on signal fire). Initial hypotheses like "1.5 std threshold" are starting points; training pipeline finds empirically optimal threshold.
- **`swing_vwap_deviation_sigma`**: same for swing VWAP anchor. Logged alongside for independent analysis.
- **`session_vwap_deviation_velocity`**: rate of change of `session_vwap_deviation_sigma` over last 3 bars — how fast price is moving away from VWAP. Fast extensions snap back harder than slow drifts. Logged as training feature every bar; weight updater discovers whether velocity predicts reversion outcome class.

### Volume Profile — Dual Track (session-reset + rolling)

- **Session-reset track** (primary): Volume profile resets at each session open (09:30 ET for equity/futures). POC/VAH/VAL accumulate from open to current bar. These are the institutionally watched levels for same-session reaction setups.
  - Outputs: `poc_price`, `vah`, `val` (70% value area — standard definition)
  - `nearest_hvn_above`, `nearest_hvn_below`: closest HVN above and below current price (directional, not just nearest)
  - `nearest_lvn_above`, `nearest_lvn_below`: closest LVN above and below current price (directional)
- **Rolling fixed-window track** (parallel): last 480 bars (~8h on 1m, ~40h on 5m). Stable levels mixing today's and prior session distribution.
  - Outputs: `poc_price_rolling`, `vah_rolling`, `val_rolling`
  - Training pipeline determines which track (session vs rolling) produces more reliable VOL-02 signals after N≥30
- **Both tracks logged every bar** — Renaissance: collect all signal candidates, let data answer the question
- Keep existing outputs (`nearest_hvn_level`, `nearest_hvn_dist_atr`, `nearest_lvn_level`, `in_lvn`) alongside new ones

### Value Area Context Fields (Market Profile 80% Rule)

- **`price_in_value_area`**: 1.0 when `val ≤ close ≤ vah`, 0.0 otherwise. Key institutional session bias signal — when price opens/enters the VA, it completes the VA ~80% of the time (Market Profile research)
- **`va_width_atr`**: `(vah - val) / atr_14` — normalized value area width. Wide VA = broad acceptance/distribution day; narrow VA = trending/directional day. Training feature for all VP-based setups.
- **`distance_to_vah_atr`**: `(vah - close) / atr_14` — normalized distance to value area high. Logged every bar. Negative when above VAH.
- **`distance_to_val_atr`**: `(close - val) / atr_14` — normalized distance to value area low. Negative when below VAL.
- All four logged every bar regardless of whether a VOL-02 signal fires — near-misses and misses are training data

### I7 VWAP Setups — Two Complementary Plugins (same I4 infrastructure)

**`trad_AnchoredVWAPReversion`** — fade extended price back toward session VWAP:
- Gate: `abs(session_vwap_deviation_sigma) > 1.5 AND hmm_regime == "ranging" (hmm_regime=0) AND hurst_exponent < 0.55`
- Direction: short when above upper band, long when below lower band
- Entry type: `at_limit` — pre-position at session VWAP band (T1 = session VWAP, T2 = opposite band)
- `session_vwap_deviation_sigma` and `session_vwap_deviation_velocity` logged per signal fire for training
- Stop: `trade_framer.py` — structural snap first (nearest HVN as invalidation), GARCH ATR fallback
- `regime_type = "mean_reversion"`

**`trad_VWAPReclaim`** — price breaks VWAP then reclaims it:
- Gate: prior bar closes below (long setup) or above (short setup) session VWAP; current bar closes back through VWAP AND `rel_volume > 1.2` (volume confirmation on reclaim bar)
- Direction: long on reclaim from below, short on reclaim from above
- Entry type: `at_pullback` — entry on close of reclaim bar
- Log `bars_below_vwap` (how long below before reclaim) and `vwap_reclaim_volume_ratio` as per-signal training features
- Regime: any (`regime_type = "any"`) — reclaims happen across regimes; training pipeline discovers per-regime alpha
- Stop: `trade_framer.py` — structural snap to session VWAP as invalidation level (price must hold VWAP), GARCH ATR fallback

### I7 Volume Profile Setups — Three Separate Plugins

**Three separate plugins for independent statistical tracking** — POC/HVN rejection is mean-reversion, LVN breakout is trend. One plugin can't carry a single `regime_type` for all three without defeating the regime gating. Each accumulates independent N for `validate_alpha.py` promotion.

**`trad_POCRejection`** — price tests POC, fails with momentum reversal:
- Gate: `abs(close - poc_price) / atr_14 < 0.3` (within 0.3×ATR of POC) AND momentum reversal (price stall + directional divergence on oscillator)
- Direction: short rejection at POC from above, long rejection at POC from below
- Log `poc_test_volume_ratio` (volume at POC test vs session average) — key training feature; institutional volume at POC is confirmatory
- `regime_type = "mean_reversion"`
- Stop: POC itself as the structural invalidation level via `trade_framer.py`

**`trad_HVNRejection`** — price stalls and reverses at high-volume node:
- Gate: price within 0.3×ATR of `nearest_hvn_above` (short) or `nearest_hvn_below` (long) AND momentum reversal confirmed
- Log `hvn_distance_entered_atr` (how deep into the HVN before rejection) and `hvn_volume_rank` (relative prominence of the HVN vs other nodes) as training features
- `regime_type = "mean_reversion"`
- Stop: `trade_framer.py` structural snap to HVN boundary

**`trad_LVNBreakout`** — fast price expansion through low-volume thin area:
- Gate: `in_lvn == 1.0` AND `rel_volume > 1.5` (expansion bar) AND close in direction of trend (HMM trending regime)
- Direction: long when expanding upward through LVN with trend, short when expanding downward
- Log `lvn_width_atr` (how thin the LVN is) — thinner LVNs should produce faster moves
- `regime_type = "trend"`
- T1 = `nearest_hvn_above` (long) / `nearest_hvn_below` (short) — expansion targets next HVN

### Cross-Plugin Architecture

- All 5 new I7 plugins call `trade_framer.py` — inherit GARCH-adaptive multipliers automatically
- All fire as production signals immediately (no shadow gate required for new setups — see Phase 31 decisions)
- `validate_alpha.py` promotion gate runs after N≥30 per plugin
- All log continuous values every bar for near-threshold events — score=0.9 near-misses are as valuable as fires

### Claude's Discretion

- Exact std band computation (rolling std window length within session — start of session vs trailing N bars)
- `poc_migration_rate` implementation (could be added — rate at which POC shifts intrabar)
- HVN `volume_rank` computation methodology
- Momentum reversal indicator used in POC/HVN rejection gate (RSI divergence vs oscillator cross vs candle pattern)
- Exact `bars_below_vwap` maximum cap for VWAPReclaim (prevent stale reclaims)

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Existing Plugin Files to Migrate

- `src/intelligence/structure/anchored_vwap.py` — existing AnchoredVWAP plugin; migrate to context/ and extend with new fields; do NOT create a new file alongside it
- `src/intelligence/patterns/volume_profile.py` — existing VolumeProfile plugin; migrate to context/ and extend; do NOT duplicate

### Plugin Protocol & Registration

- `src/intelligence/CLAUDE.md` — tier protocol, plugin interface, tier directory conventions; TIER_I4 plugin class structure
- `src/intelligence/register_plugins.py` — TIER_I3, TIER_I4, TIER_I5, TIER_I7 lists; remove from old tiers, add to TIER_I4; all 5 new I7 plugins added to TIER_I7

### Feature Schema

- `src/intelligence/schemas.py` — canonical IntelligenceEvent fields; verify `swing_high_idx`, `swing_low_idx`, `hurst_exponent`, `hmm_regime`, `rel_volume`, `atr_14`, `garch_vol_regime` exist before planning
- Existing VWAP fields in schema: `session_vwap`, `session_vwap_dist_pct`, `swing_vwap`, `weekly_vwap`, `above_session_vwap`, `above_swing_vwap`, `above_weekly_vwap`, `vwap_alignment_score`
- Existing VP fields in schema: `nearest_hvn_level`, `nearest_hvn_dist_atr`, `nearest_lvn_level`, `in_lvn`
- All new I4 output fields must be added to IntelligenceEvent schema before using them in I7 plugins

### Stop Architecture

- `src/intelligence/trading/trade_framer.py` — all 5 I7 plugins must call this; inherits GARCH-adaptive ATR scaling automatically

### Reference I7 Plugin Implementations

- `src/intelligence/trading/choch_reversal.py` — minimal I7 plugin pattern (gate → direction → framer → output)
- `src/intelligence/trading/mean_reversion.py` — GARCH/Kalman gated mean-reversion reference; pattern for VWAP Reversion
- `src/intelligence/context/session_context.py` — ET timezone and session reset logic; reference for session-open reset in VP

### Requirements

- `.planning/REQUIREMENTS.md` VWAP-01, VWAP-02, VOL-01, VOL-02 — original specs; Phase 34 context supersedes where it makes more specific decisions (3 plugins not 1 for VOL-02; VWAPReclaim added)

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets

- `src/intelligence/structure/anchored_vwap.py` `AnchoredVWAPPlugin`: fully functional session + swing + weekly VWAP — extend in place, don't rewrite. `swing_high_idx` / `swing_low_idx` from features already consumed.
- `src/intelligence/patterns/volume_profile.py` `VolumeProfilePlugin`: `_N_BUCKETS=50` histogram with HVN/LVN detection already working — extend to add POC, VAH, VAL, session-reset track, direction-aware HVN/LVN fields.
- `src/intelligence/context/session_context.py` `_ET_TZ` + `_in_window()`: ET timezone helpers for session-reset logic in volume profile.
- `src/intelligence/context/garch_volatility.py`: outputs `garch_sigma`, `garch_vol_regime` — GARCH-first pattern for all stop sizing.
- `src/intelligence/trading/mean_reversion.py`: GARCH/Hurst gated mean-reversion I7 plugin — closest reference pattern for VWAP Reversion.

### Established Patterns

- TIER migration: update TIER_I3/TIER_I5 to remove old names, update TIER_I4 to add new names. `registry.validate_tier()` hard-crashes on missing names — test locally before committing.
- Plugin `_state` keyed by `(symbol, timeframe)`: needed for VWAPReclaim (must track `bars_below_vwap` across ticks), VolumeProfile session-reset (must track session open bar index).
- Always-log pattern: all continuous feature fields computed and logged every bar — `session_vwap_deviation_sigma`, `session_vwap_deviation_velocity`, `va_width_atr`, etc. appear in `intelligence_features` on every bar regardless of whether a signal fires.
- `_no_signal()` on gate failure: all I7 plugins return `self._no_signal()` when conditions not met.

### Integration Points

- DB migration required: new schema columns for `session_vwap_deviation_sigma`, `avwap_upper_band`, `avwap_lower_band`, `poc_price`, `vah`, `val`, `price_in_value_area`, `va_width_atr`, and all other new fields. New migration `036_vwap_volume_profile_fields.sql` (or whatever next sequential number is).
- `src/intelligence/schemas.py` `IntelligenceEvent`: all new I4 output fields must be added here before I7 plugins can consume them.
- `src/intelligence/register_plugins.py`: remove `anchored_vwap_plugin` from TIER_I3, `volume_profile_plugin` from TIER_I5; add both to TIER_I4; add all 5 new I7 plugins to TIER_I7.

</code_context>

<specifics>
## Specific Ideas

- Renaissance framing throughout: all fixed thresholds (`1.5 std`, `0.3×ATR proximity`, `1.5× rel_volume`, `480-bar rolling`) are initial hypotheses, not permanent gates — log the continuous values so the training pipeline can find empirically correct thresholds
- The plugin migration decision (not duplication) is critical for ML data quality: `session_vwap` and a hypothetical `avwap_session` would be the same number under two feature names — multicollinearity that silently degrades logistic regression weight learning
- Three separate VOL-02 plugins (not one with variant field) is the right architecture because each has a different `regime_type` — LVN breakout is trend, POC/HVN rejection is mean-reversion. A single plugin carrying `regime_type = "any"` would defeat the regime gating for all three.
- Value Area 80% rule (Market Profile): when price is inside VAL-VAH, it tends to complete the value area. `price_in_value_area` is a binary session bias feature; log every bar so training pipeline can quantify this rule's accuracy per setup and regime.
- `session_vwap_deviation_velocity` is the Renaissance addition: not just "how far" but "how fast" price is moving from VWAP. Fast extensions with high velocity snap back harder. This is a quality gate on VWAP reversion strength that the training pipeline will discover empirically.
- VWAPReclaim adds the "return" hypothesis complementing the "extension" hypothesis of VWAPReversion — two statistically independent tests from the same I4 infrastructure, doubling the labeled training data collected per session.

</specifics>

<deferred>
## Deferred Ideas

- MTF volume profile convergence (1m/5m/15m POC agreement at same price) — cross-TF computation; belongs in Phase 36 (cross-asset/cross-TF service)
- VWAP anchor selection by highest-volume day (institutional anchor) — future enhancement to anchored_vwap.py
- `poc_migration_rate` field (intrabar POC drift) — Claude's discretion whether to add; not a gate on any I7 plugin

</deferred>

---

*Phase: 34-i4-infrastructure-anchored-vwap-volume-profile*
*Context gathered: 2026-03-17*
