# Zone Engine Plan — Cross-Review for Codex

**Version:** 1.0
**Status:** archived
**Last Updated:** 2026-05-05
## Context

This is a plan for a Python trading system (IndicAgent). The plan replaces primitive entry zone construction with a structural confluence engine and adds dual-tracking lifecycle (zone-gated vs. immediate entry).

A senior engineer review caught **3 blockers** and **8 warnings**. We need a second opinion on the design decisions and proposed fixes.

## The Plan (8 Tasks)

1. **zone_engine.py** — candidate collection + data structures (ZoneCandidate, ZoneResult)
2. **Clustering + resolve_structural_zone** — 3-tier fallback (confluence > single > ATR)
3. **Metrics** — 4 Prometheus metrics for zone engine
4. **Wire into trade_framer** — replace `_resolve_zone_bounds` with zone_engine
5. **Signal schema v2** — add `zone_source` field, bump version
6. **Dual tracking** — wire `evaluate_market_entry` in signal tracker
7. **Stop/target candidates** — add MA stops, Fib/VWAP/overnight/LVN targets
8. **Integration test + lint**

Full plan: `docs/plans/2026-05-04-structural-zone-engine-plan.md`
Design spec: `docs/plans/2026-05-04-structural-zone-engine-design.md`

## Key Files to Read

- `src/intelligence/trading/trade_framer.py` — current zone logic (lines 308-352: `_resolve_zone_bounds`)
- `src/intelligence/trading/lifecycle_tracker.py` — has `evaluate_market_entry` (line 527) and `MarketTransition` (line 515)
- `services/signal_tracker_compute_agent.py` — compute-only agent, no DB access
- `src/observability/metrics.py` — only `counter()` and `gauge()` helpers, no `histogram()`
- `src/intelligence/trading/signal_schema.py` — `make_signal_from_frame`

## Review Findings — Need Your Take

### BLOCKER 1: Task 4 — `_resolve_zone_bounds` replacement references nonexistent key

The plan's Step 1.2 proposes:
```python
result = resolve_structural_zone(features, direction, entry, features.get("stop_loss", 0.0), atr)
```
But `stop_loss` is not in the features dict — it's a local variable in `frame_trade()`. The plan then bypasses this function entirely in Step 1.3 by calling `resolve_structural_zone` directly. **Question:** Should we just delete `_resolve_zone_bounds` and inline the call, or keep a thin wrapper?

### BLOCKER 2: Task 6 — `self._ledger_repo` doesn't exist

`SignalTrackerComputeAgent` is DB-ignorant by design (architecture principle). The plan proposes:
```python
repo = self._ledger_repo
await repo.update_market_entry(...)
```
But `_ledger_repo` doesn't exist, and `update_market_entry` isn't a method on `SignalLedgerRepository` (closest is `record_market_resolution`). **Question:** Should market-entry outcomes be published as Kafka events (consistent with architecture), or should we add a DB dependency to this agent?

### BLOCKER 3: Task 6 — Wrong field name for market entry price

Plan uses `sig.get("market_price_at_signal")` and `sig.get("ask_at_signal")` — neither exists in the bootstrap query. The actual field from the bootstrap query is `market_entry_price`.

### WARNING (Design Decision): Task 4 — Losing setup_type-aware zone logic

The current `_resolve_zone_bounds` has specialized zone logic per setup type:
- `supply_demand_*` → demand/supply zone geometry
- `fvg*` → FVG gap bounds
- `choch*`/`ob*` → order block bounds
- `sweep*`/`liquidity_hunt*` → tight ±0.5 ATR
- Default → ±ATR band

The plan replaces ALL of this with generic structural confluence (S/R + MAs + VP levels). **Question:** Is this intentional? Should setup-specific zone logic be preserved as a pre-check before falling back to structural confluence?

### WARNING: Metrics helpers don't support what the plan needs

`counter()` helper has no label support — `ZONE_TIER_USED.labels(tier=...)` would crash.
No `histogram()` helper exists. Must use `Counter()` and `Histogram()` constructors directly.

### WARNING: Fibonacci retracement used as extension targets

Plan adds `fib_618` and `fib_786` as long targets (checking `fib_618 > entry`). But these are *retracement* levels — they're below entry for longs. This will be dead code.

## What We Need From You

1. **Architecture call on BLOCKER 2** — Kafka event vs. DB dependency for market-entry outcomes?
2. **Design call on the setup_type regression** — keep specialized zones, or go pure structural?
3. **Any issues we missed** — read the plan and source files, tell us what else looks wrong
4. **Suggested fix for each blocker** — concrete code or approach
