# Structural Zone Engine — Design Spec

**Version:** 1.0
**Last Updated:** 2026-05-04
**Date:** 2026-05-04
**Status:** Draft
**Scope:** Rewrite entry zone construction + wire dual-tracking lifecycle + audit stop/target hierarchy

## Problem

94% of signals expire `never_activated`. Root cause: `_resolve_zone_bounds` in `trade_framer.py` uses
only FVG gap boundaries (often far from current price) or an ATR fallback band. It ignores the 200+
structural data points already computed across I1/I3/I4/SMC tiers.

Meanwhile, stop and target placement already use structural levels (swing, S/R, supply/demand, POC,
VWAP, etc.) but miss MAs, Fibs, LVN/HVN, Donchian/Keltner, session VWAPs, and overnight levels.

## Architecture Decisions

### No new agents or services

The zone calculation is a **pure function** of the features dict — it belongs as a utility module,
not a new service. Two existing services already own the right responsibilities:

| Concern | Existing owner | Where zone logic plugs in |
|---|---|---|
| Zone construction | `intelligence_pipeline_agent` → I7 plugins → `frame_trade()` | Called at signal fire time |
| Zone-gated lifecycle | `signal_tracker_compute_agent` → `evaluate_signal()` | Already running |
| Immediate-entry lifecycle | `signal_tracker_compute_agent` → `evaluate_market_entry()` | Already exists, unwired |

### Separation of concerns: extract `zone_engine.py`

`trade_framer.py` is 37k lines. The zone engine should be a standalone module in
`src/intelligence/trading/zone_engine.py` — same pattern as `atr_utils.py`, `confidence_utils.py`,
`exhaustion_utils.py`. Benefits:
- Independently unit-testable (pure function: features in → zone bounds out)
- `trade_framer.py` calls `resolve_structural_zone()` instead of inline logic
- Other consumers (e.g., dashboard, replay scripts) can import it directly
- Keeps `trade_framer.py` focused on its job: orchestrating stop/target/zone into a TradeFrame

### Observability

Zone engine is a utility, not an agent — it doesn't inherit from BaseAgent. But Renaissance demands
every decision is measurable. Use existing `src/observability/metrics.py` factory pattern (same as
plugin metrics):

```python
# Metrics emitted per zone resolution:
ZONE_TIER_USED = counter("zone_tier_used", "Zone engine tier selected")  # labels: tier=(confluence|single|atr)
ZONE_CANDIDATE_COUNT = histogram("zone_candidate_count", "Structural candidates evaluated")
ZONE_CLUSTER_DENSITY = histogram("zone_cluster_density", "Cluster tightness (members / width_atr)")
ZONE_WIDTH_ATR = histogram("zone_width_atr", "Final zone width in ATR units")
```

These are Prometheus counters/histograms registered via the existing factory — no OTel or base agent
changes needed. The counter labels (`tier`, `setup_type`) let us segment by plugin later.

### Compute cost

Clustering runs per-signal (not per-bar). ~30 signals/bar × 55 symbols × 60 bars/min = ~99k
clustering ops/min. Each op: O(n log n) where n ≈ 15 candidates. Negligible — less than one
plugin compute() call.

## Design

### 1. Structural Zone Engine (`zone_engine.py` — new module)

Replace the 5-branch `_resolve_zone_bounds` with a 3-tier structural confluence engine.

**Candidate collection:**

Collect all structural levels in the pullback direction. For longs: levels below entry (support side).
For shorts: levels above entry (resistance side).

Support-side candidates (long pullback):

| Candidate | Source | Strength field |
|---|---|---|
| `nearest_support` | I3 | `support_strength` |
| `swing_low` | I3 | `swing_low_age_bars` (inverse) |
| `nearest_demand_high` | SMC | `demand_strength` |
| `ema_21` | I1 | fixed 0.7 (dynamic MA) |
| `sma_50` | I1 | fixed 0.6 (slower MA) |
| `ssl_level` | SMC | `ssl_significance` |
| `poc_price` / `poc_price_rolling` | I4 | fixed 0.8 (volume POC) |
| `val` / `val_rolling` | I4 | fixed 0.7 (value area) |
| `nearest_lvn_level` | I4 | fixed 0.5 (thin volume) |
| `nearest_hvn_below` | I4 | fixed 0.7 (thick volume) |
| `fib_618` | I3 | `fib_cluster_strength` |
| `fib_786` | I3 | `fib_cluster_strength` |
| `overnight_low` | I3 | fixed 0.6 (session structure) |

Resistance-side candidates (short pullback): mirror with `nearest_resistance`, `swing_high`,
`nearest_supply_low`, `bsl_level`, `vah`, `overnight_high`, etc.

VP field selection (same rule as existing `_select_vp` in trade_framer): session VP (`poc_price`,
`val`, `vah`) for 1m/5m; rolling VP (`poc_price_rolling`, `val_rolling`, `vah_rolling`) for 15m+.

Filter: only include candidates between entry and stop (longs: `stop < level < entry`;
shorts: `entry < level < stop`). Levels beyond the stop make no sense as entry zones.

**Tier 1 — Confluence Cluster (primary):**

1. Sort candidates by price
2. Group candidates within 0.5× ATR of each other
3. Score: `score = member_count * (1.0 / max(cluster_width_atr, 0.1))`
4. Pick highest-scoring cluster with 2+ members
5. Zone = `[cluster_min - 0.15×ATR, cluster_max + 0.15×ATR]`
6. Minimum width: 0.25× ATR (expand symmetrically if narrower)

**Tier 2 — Single Best Level (fallback):**

If no cluster has 2+ members, score each candidate:
```
score = proximity_score * 0.4 + strength_score * 0.3 + freshness_score * 0.3
```
- `proximity_score`: closer to entry = better (linear 0-1, 1.0 at 0.25×ATR, 0.0 at 2×ATR)
- `strength_score`: tier-specific field or fixed default (see table above)
- `freshness_score`: `1.0 / (1.0 + age_bars / 50.0)` — fresher levels score higher

Zone = `[level - 0.25×ATR, level + 0.25×ATR]`, clamped between entry and stop.

**Tier 3 — ATR Band (emergency):**

No usable structural level found. Current behavior unchanged: `entry - 1.0×ATR` to
`entry + 0.5×ATR`.

**Output:**

```python
@dataclass
class ZoneResult:
    zone_low: float
    zone_high: float
    tier: str              # "confluence" | "single" | "atr"
    source: str            # "confluence:swing_low+ema21+poc" | "single:hvn" | "atr_fallback"
    candidate_count: int   # how many structural levels were evaluated
    cluster_members: int   # how many in the winning cluster (0 if not confluence)
```

`trade_framer.py` calls `resolve_structural_zone()` and uses `ZoneResult.zone_low/zone_high`.
`ZoneResult.source` is stored in the signal dict as `zone_source` for ML attribution.

### 2. Dual Tracking Lifecycle

Wire `evaluate_market_entry()` into the signal tracker bar loop.

**What changes in `signal_tracker_compute_agent.py`:**

For each signal on each bar, run both evaluation paths in parallel:
```python
# Existing: zone-gated lifecycle
zone_transition = evaluate_signal(sig, ...)

# New: immediate-entry lifecycle (always active from bar 1)
market_transition = evaluate_market_entry(sig, market_entry_price=sig["market_price_at_signal"], ...)
```

- `market_entry_price` = `market_price_at_signal` (already stored in signal_ledger at fire time)
- Market entry track runs independently — separate MAE/MFE/PnR counters per signal in memory
- On signal exit (zone track resolves), also resolve the market entry track and persist both

**DB writes:** Use existing `update_market_entry()` in `signal_ledger_repository.py`. The 10
`market_entry_*` columns already exist. No migration.

**Memory overhead:** One extra `dict` per signal for market-entry state (mae, mfe, bars_elapsed).
With ~200 active signals, that's ~200 dicts — negligible.

### 3. Stop/Target Hierarchy Audit

Add missing structural candidates to stop and target placement in `trade_framer.py`:

**Stop candidates to add (inserted after swing, before S/R fallback):**
- `ema_21` / `sma_50`: dynamic MA support/resistance (ATR buffer like swing)
- `supertrend_value`: trend-following stop (if `supertrend_dir` confirms direction)
- `nearest_hvn_level`: volume-confirmed structural stop

**Target candidates to add:**
- `fib_618` / `fib_786`: Fibonacci extension targets
- `nearest_lvn_level`: price moves through LVNs — target near HVN
- `session_vwap` / `swing_vwap`: institutional reference price targets
- `overnight_high` / `overnight_low`: session structure targets

All use existing feature keys. No new computation.

## Signal Schema

Bump `signal_schema_version` to `"v2"`. Rationale: zone construction logic fundamentally changes
zone widths and activation behavior. ML training queries must filter `WHERE signal_schema_version >= 'v2'`
for clean zone-attributed data. v1 signals retain their existing zones for retrospective analysis.

New field: `zone_source` (string, nullable) — populated by zone engine, stored in signal_ledger.
`NULL` for v0/v1 signals (backward compatible).

## Files Changed

| File | Change |
|---|---|
| `src/intelligence/trading/zone_engine.py` | **NEW** — structural zone engine (candidate collection, clustering, scoring) |
| `src/intelligence/trading/trade_framer.py` | Replace `_resolve_zone_bounds` with call to `zone_engine.resolve_structural_zone()`. Add stop/target candidates. |
| `services/signal_tracker_compute_agent.py` | Wire `evaluate_market_entry` + market-entry state tracking into bar loop |
| `src/intelligence/trading/signal_schema.py` | Add `zone_source` field, bump schema version to v2 |
| `src/observability/metrics.py` | Add zone engine metrics (counter + 3 histograms) |
| `tests/unit/trading/test_zone_engine.py` | **NEW** — unit tests for clustering, scoring, edge cases |
| `tests/unit/trading/test_trade_framer.py` | Update existing tests for new zone integration |

## Success Metrics

- Zone activation rate > 15% (from current ~2% for non-GapAnalysis setups)
- Dual tracking populates `market_entry_pnl_r` for resolved signals
- After 30 days: measurable zone vs immediate entry comparison per setup type
- Prometheus dashboard: zone tier distribution, candidate counts, cluster density
- Zero new services, topics, or DB migrations
