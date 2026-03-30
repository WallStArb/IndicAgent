# Phase 50: Roll Monitor Graduation - Context

**Gathered:** 2026-03-30
**Updated:** 2026-03-30 (changed from removal to build-out)
**Status:** Ready for planning

## Phase Boundary

Build out the futures roll detection feature end-to-end. RollComputeAgent exists but is disabled; `roll_premium_pct` column exists but is never populated. Goal: enable the feature with working roll premium computation, D-21 validation, and downstream integration.

**Decision change:** Originally scoped for removal, user decided to build out properly.

---

## Implementation Decisions

### D-01: Build market_data_5m Foundation

Create `market_data_5m` view aggregating 1m bars into 5-minute buckets. Required for D-21 validation (cleaner volume signal) and enables HTF analysis.

**Actions:**
- Create materialized view: `SELECT timestamp_bin, symbol, OHLCV FROM market_data_ohlcv GROUP BY 5-min buckets`
- Run one-time backfill from existing 1m data
- Wire BarAggregatorComputeAgent 5m output to persistence

**Rationale:** Renaissance principle — "Never drop data that could contain signal." 5m compression reduces storage while preserving structure.

### D-02: Implement Roll Premium Computation

RollComputeAgent detects rolls but doesn't compute price gap. Need to derive front/back contract prices at detection time.

**Actions:**
- Extend RollComputeAgent to query active contracts and get bid/ask prices for front + back
- Populate `roll_gap_price` and `roll_gap_pct` in RollEvent
- FeatureWriterAgent consumes RollEvent and populates `roll_premium_pct` in intelligence_features

**Rationale:** Roll premium signal = (back - front) / front. This spread predicts returns during roll windows.

### D-03: Enable RollComputeAgent and Validate

**Actions:**
- Run D-21 validation against `market_data_5m` (gate: >=90% detection, <10% FP)
- If validation passes: enable `indicagent-roll-compute.service`
- If validation fails: tune algorithm or add more data

**Rationale:** Shadow mode until proven accurate. "Earn the right through proof."

### D-04: Wire Downstream Consumers

**Actions:**
- Identify which I7 plugins benefit from roll context (mean-reversion setups during roll windows)
- Add `roll_premium_pct` to trade_framer context
- I7 plugins can adjust confidence when roll premium is extreme (>2% contango = bearish signal)

**Rationale:** Roll spread contains information — market pays for carry cost during contango.

### D-05: Phase Split Structure

Phase 50 split into subphases:

| Subphase | Focus | Estimated Plans |
|----------|-------|-----------------|
| 50.1 | Create market_data_5m view + backfill | 2 plans |
| 50.2 | Implement roll premium computation | 2-3 plans |
| 50.3 | D-21 validation + enable service | 2 plans |
| 50.4 | Wire downstream consumers | 1-2 plans |

### Claude's Discretion

- **5m view type:** Materialized view with REFRESH CONCURRENTLY vs continuous aggregation via trigger — decide during planning
- **Price source for roll gap:** IBKR real-time quotes vs last bar close — decide based on data availability
- **Validation failure path:** If D-21 fails <90% detection, either tune z-score threshold or gather more data before retrying

---

## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Roll Detection
- `services/roll_compute_agent.py` — RollComputeAgent implementation (volume z-score algorithm)
- `production/scripts/validate_roll_detection.py` — D-21 validation script
- `src/config/contracts.py` — `get_roll_window()`, `derive_roll_chain()`, `FUTURES_ROLL_CYCLES`
- `src/core/schemas/market_events.py` — `RollEvent` schema

### Data Pipeline
- `src/core/bar_accumulator.py` — BarAccumulator (HTF aggregation logic)
- `services/bar_aggregator_compute_agent.py` — Publishes 5m bars to `market.bars.htf`
- `services/feature_writer_agent.py` — Writes to `intelligence_features` (needs roll_premium_pct wiring)

### Database
- `production/migrations/049_roll_premium_pct.sql` — Column definition (already applied)
- `.planning/ROADMAP.md` — Phase 50 context, depends-on relationships

### Architecture
- `CLAUDE.md` — DAG architecture, shadow mode pattern, graduation criteria
- `src/core/stream_keys.py` — `topic_roll_events()` stream key

---

## Existing Code Insights

### Reusable Assets

- **BarAccumulator** (`src/core/bar_accumulator.py`): Already aggregates 1m → 5m/15m/1h. Logic can be reused for 5m view creation.
- **RollMonitor** (in `roll_compute_agent.py`): Calendar + volume z-score algorithm already implemented. Just needs enablement.
- **Shadow stats monitoring** (`src/intelligence/weight_updater.py`): Infrastructure for tracking shadow performance exists.

### Established Patterns

- **Graduation pattern:** Phase 47 graduated CROSS_ASSET (flag removed, unconditional active). RollComputeAgent follows same pattern.
- **Materialized view refresh:** PostgreSQL `REFRESH CONCURRENTLY` allows queries while rebuilding.
- **Agent systemd units:** After=network-online.target, Wants=ibkr-provider, Restart=always pattern.

### Integration Points

- **BarAggregatorComputeAgent** → writes 5m bars to DB (may need new writer or existing)
- **RollComputeAgent** → publishes RollEvent to `topic_roll_events` → FeatureWriterAgent consumes
- **FeatureWriterAgent** → writes `roll_premium_pct` to `intelligence_features`
- **I7 plugins** → read `roll_premium_pct` from features dict (currently always None, will be populated)

---

## Specific Ideas

**Roll premium as signal:** When roll_premium_pct > 2% (extreme contango), market is paying premium for front month. This often precedes mean reversion. I7 mean-reversion plugins can boost confidence when roll premium is high.

**Volume z-score threshold:** Currently -2.0. If D-21 shows high FP rate, may need to adjust. Algorithm is sound (calendar gate + volume confirmation), threshold is the tunable.

**5m as foundation:** Once 5m data exists, it unblocks multiple features — not just roll detection. HTF analysis, cleaner signals, faster queries.

---

## Deferred Ideas

None — discussion stayed within phase scope.

---

*Phase: 50-roll-monitor-graduation*
*Context gathered: 2026-03-30 (build-out approach)*
