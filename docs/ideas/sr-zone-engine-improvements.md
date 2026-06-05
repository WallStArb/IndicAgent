# SR / Zone Engine Improvements

**Version:** 1.0
**Status:** ideas
**Priority:** medium
**Milestone:** post-Phase-116
**Last Updated:** 2026-06-05
**Tags:** sr, zone_engine, i3, i4, confluence, support, resistance

Ideas for improving SR quality and zone_engine source coverage beyond Phase 116. All ideas are
post-Phase-116 — the foundation (ATR clustering, TF lookback, `ctx_SRConsensus`, `collect_sr_candidates`)
must be live first. Track calibration work in `.planning/todos/pending/019-sr-strength-calibration.md`.

---

## 1. Calibration (Priority: HIGH — do first)

### 1.1 Regression-Fit default_strength Weights

The `default_strength` values added in Phase 116 (0.5–0.8) are v0 intuition placeholders.
Gate: n >= 500 signals with `sr_support_confluence_score > 0`. Fit ridge regression per source
family, per TF bucket. See todo `019-sr-strength-calibration.md`.

### 1.2 Per-TF Source Quality Priors

Before regression data accumulates, apply heuristic TF priors:
- 1m/5m: reduce session level weight (prior_session_low/high) by 0.8x — session levels matter
  less on micro-TF where intraday structure dominates
- 15m+: increase session level weight by 1.2x
- 1h+: HVN (nearest_hvn_below/above) weight increase — intraday HVN loses meaning on 1h

Implement as a `_tf_weight_multiplier(tf: str, source_family: str) -> float` applied in
`_resolve_strength` when the source family and TF are both known.

---

## 2. New Source Candidates for zone_engine

### 2.1 Multi-Session High/Low (Weekly / Monthly)

Current session sources: prior_session_high/low, asian_session_high/low.
Add: `weekly_high`, `weekly_low`, `monthly_high`, `monthly_low` as I3 plugin outputs.
These are macro SR anchors that dominate on 1h/4h/1d. Default strength: 0.85 (stronger than
daily session levels).

- Source plugin: new I3 plugin `struct_MacroLevels` or extend `struct_SessionLevels`
- When to trigger: 1h+ TFs only (gate in zone_engine specs via a `min_tf` field, or pre-filter
  in `collect_sr_candidates` via a `source_tf_gate` on each spec)

### 2.2 Touch/Test Memory (Level Strength by Confirmed Touches)

A level that has held under 3+ tests is empirically stronger than a fresh level. Requires
a running counter in I3 state or a persistence lookup.

- Option A: I3 plugin tracks `resistance_touch_count` (bars in the current lookback window where
  price approached the resistance cluster within 0.3 ATR and rejected). Emit as a feature field.
- Option B: `ctx_SRConsensus` queries `intelligence_features` to count historical approaches.
  Violates the DB-ignorant pipeline rule — not viable.
- Option A is correct. Add `resistance_touch_count`, `support_touch_count` to I3 SR plugin
  outputs. Use `touch_count / max(1, lookback_bars)` as a multiplier on default_strength in
  zone_engine.

### 2.3 Overnight Gap Fill Levels

When today's open gaps above/below yesterday's close, the gap fill target becomes an SR level.
- Feature: `gap_fill_target` = prior close when `open > prior_close + ATR * 0.5` (gap up) or
  `open < prior_close - ATR * 0.5` (gap down). None otherwise.
- Source plugin: extend `struct_SessionLevels` or add a thin I3 plugin.
- Default strength: 0.7 (gap fills are high-probability but time-decayed).

### 2.4 VPOC Migration (Volume Point of Control Drift)

The intraday VPOC migrates as volume accumulates. When today's VPOC moves away from
yesterday's VPOC, the prior day's VPOC becomes an SR reference.
- Feature: `prior_poc_price` (yesterday's daily VPOC from `poc_price` in `intelligence_features`).
  Requires a one-bar lookback query — needs to be emitted by VP plugin with a lag.
- Default strength: 0.75 — VPOC is a strong level when price revisits.

### 2.5 Cumulative Delta Inflection Levels (Orderflow — Deferred)

Requires orderflow integration (delta per bar from bid/ask volume). When CVD reverses
sharply at a price level, that level becomes a structural anchor.
- Blocked on orderflow provider (see IDEAS.md: Delta Divergence Setup).
- Default strength: 0.85 when available — CVD-confirmed levels are the strongest mechanical SR.

### 2.6 Options Gamma Levels (GEX Clusters)

For ES/NQ/RTY, SPX/NDX options gamma concentrations at key strikes create price magnets.
GEX (gamma exposure) flips from negative to positive gamma at the strike cluster.
- Source: requires a GEX data feed (CBOE, OptionsDX, or scraped from brokerage API).
- Not currently possible without an external provider. Track in DerivAgent ideas.
- Default strength when available: 0.9 (gamma walls are the strongest level type for index futures).

---

## 3. Clustering Improvements

### 3.1 Zone Width Output

The current SR plugin outputs a single `nearest_support` price point. In reality, a cluster
of 3 pivots within 0.5 ATR should be represented as a zone (center ± half-width).
- Add `support_zone_width_atr`, `resistance_zone_width_atr` to I3 SR plugin outputs.
- Use in zone_engine: candidates within a zone get a width-proportional strength boost —
  wider zones (more cluster members) represent more institutional memory.
- Downstream: I7 entry plugins use `sr_nearest_support - support_zone_width_atr * 0.5` as the
  true zone boundary for stop placement instead of the raw pivot level.

### 3.2 Adaptive Cluster Radius by Regime

Current: `cluster_radius = atr_14 * 0.5` (fixed multiplier).
The 0.5x multiplier is a v0 constant. In a trending regime, pivots are sparse and the relevant
cluster radius should be larger (fewer but stronger levels). In a ranging regime, pivots are
dense and a tighter radius preserves level granularity.

- Use `hmm_regime` from I6/SMC: regime 0 (range) → `cluster_atr_mult = 0.4`; regime 1 (trend)
  → `cluster_atr_mult = 0.65`.
- Add a `_REGIME_CLUSTER_MULT: dict[int, float] = {0: 0.4, 1: 0.65, 2: 0.5}` and read the
  `hmm_regime` from `frames.get("smc") or {}` in `compute_full`.

### 3.3 Cluster Density Score

A cluster of 5 pivots within 0.5 ATR is empirically stronger than a cluster of 2. Current
strength formula: `len(members) * mean_vol_ratio`. This scales with member count already, but
the scaling is linear.

Consider: `strength = (len(members) ** 1.2) * mean_vol_ratio` — a mild superlinear bonus for
density. Gate: verify empirically after n >= 200 signals before shipping.

---

## 4. collect_sr_candidates Improvements

### 4.1 Source Diversity Minimum for Consensus

Current `find_best_level`: prefer clusters with `_source_diversity >= 2`. If no multi-source
cluster exists, fall back to `_pick_single_best`. This means a round number alone can be the
output (intended, but should be distinguishable).

Add `sr_support_source_count: int` as a 7th output field from `ctx_SRConsensus`. Downstream
I7 plugins can gate on `sr_support_source_count >= 2` to require genuine multi-source confluence
rather than accepting a lone round number.

### 4.2 Proximity-Weighted Score

The current confluence score is `float(_source_diversity(best))` — a count of distinct source
families. This ignores how close each source is to the consensus price.

Better: score = `sum(candidate.strength * (1 - dist_from_cluster_center / max_dist) for c in cluster)`.
Closer candidates contribute more to the score. Cap at 1.0. This rewards tight clusters over
loose ones even if source count is the same.

### 4.3 Stale Level Decay

A level last tested 200 bars ago is less relevant than one tested 10 bars ago. Add a
`_age_decay(age_bars: float, tf: str) -> float` multiplier that reduces `default_strength` by
`max(0.3, 1.0 - age_bars / lookback_bars)`. Minimum 0.3 so very old levels still contribute
weakly to confluence.

---

## 5. Testing and Observability

### 5.1 SR Accuracy Metric

After Phase 116 ships, add a shadow evaluation comparing `sr_nearest_support` / `sr_nearest_resistance`
to actual signal stop-out and target levels:
- `sr_support_accuracy`: fraction of signals where `entry - stop >= sr_nearest_support - ATR * 0.5`
  (meaning the stop was correctly anchored to the computed support)
- `sr_resistance_accuracy`: fraction of signals where target <= `sr_nearest_resistance + ATR * 0.5`

Track via `shadow_registry` DB table, same governance as signal-level accuracy.

### 5.2 Source Contribution Breakdown (Observability)

Currently `sr_support_confluence_score` is an aggregate number. Add a JSON field
`sr_support_sources: list[str]` (e.g. `["hvn_below", "prior_sess_l", "round_1000"]`) to see
which sources contributed to the winning cluster in each bar. Useful for debugging and for
the calibration regression. Store in the `intelligence_features` JSONB tier column.

---

## Ordering Recommendation

1. **019-sr-strength-calibration** (todo, gated on n >= 500) — highest leverage once data accumulates
2. **Zone width output (3.1)** — immediate downstream value for stop placement, minimal implementation cost
3. **`sr_support_source_count` (4.1)** — cheap 7th field, immediately useful for I7 gating
4. **Per-TF source priors (1.2)** — cheap heuristic improvement, no data dependency
5. **Multi-session levels (2.1)** — new I3 plugin, medium effort, high value for 1h+
6. **Touch/test memory (2.2)** — requires I3 state tracking, medium effort
7. **Adaptive cluster radius (3.2)** — requires regime integration, medium effort, gated on regime quality
8. **Source contribution JSON (5.2)** — useful for debugging, low urgency
9. **Everything else** — deferred until calibration validates direction
