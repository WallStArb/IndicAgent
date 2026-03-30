# Phase 50: Roll Monitor Graduation - Context

**Gathered:** 2026-03-30
**Updated:** 2026-03-30 (build-out approach, full Renaissance DAG)
**Status:** Ready for planning

## Phase Boundary

Build out the futures roll detection feature end-to-end following Renaissance DAG principles. RollComputeAgent exists (DB-ignorant, publishes to `topic_roll_events`) but needs: D-21 validation, roll premium computation, service enablement, and downstream consumers.

**Renaissance principles:**
- **DAG:** RollComputeAgent → Kafka → FeatureWriterAgent → DB
- **Modularity:** Each agent has one job
- **Reuse:** 5m data exists, algorithm exists
- **Proof before production:** D-21 validation first
- **Earn the right through proof:** Shadow mode until validated

---

## Implementation Decisions

### D-01: Create market_data_5m View

5m data already exists in `market_data_ohlcv` (87K rows with `timeframe='5m'`). Create a view for D-21 validation.

**Actions:**
- Create `market_data_5m` view: `SELECT * FROM market_data_ohlcv WHERE timeframe = '5m'`
- Simple, no backfill needed
- Unblocks D-21 validation

### D-02: Implement Roll Premium Computation

RollComputeAgent detects rolls but doesn't compute price gap. Need front/back contract prices at detection time.

**Actions:**
- Extend RollComputeAgent to query active contracts (from `get_active_contracts()`)
- Get bid/ask prices for front + back contracts
- Compute `roll_gap_pct = (back_price - front_price) / front_price`
- Populate in RollEvent

### D-03: Run D-21 Validation

**Actions:**
- Run `validate_roll_detection.py` against `market_data_5m`
- Gate: >=90% detection rate, <10% false positive rate
- If passes: enable RollComputeAgent
- If fails: tune algorithm or gather more data

### D-04: Wire FeatureWriterAgent Consumer

**Actions:**
- FeatureWriterAgent subscribes to `topic_roll_events`
- On RollEvent, UPDATE `intelligence_features SET roll_premium_pct = ...`
- Only bars during roll windows get populated (others stay NULL)

### D-05: Downstream Consumers (Future)

I7 mean-reversion plugins can use `roll_premium_pct` to adjust confidence:
- High roll premium (>2% contango) → boost mean-reversion signals
- Low premium (backwardation) → different regime

**Defer to Phase 51+** — first get roll detection working.

### D-06: DAG Architecture (Renaissance)

**RollComputeAgent (DB-ignorant):**
- Consumes: `market.bars` (1m bars)
- Computes: Roll detection + roll premium
- Publishes: `RollEvent` to `topic_roll_events`
- NO DB writes

**FeatureWriterAgent (persistence):**
- Consumes: `topic_roll_events`
- Writes: `roll_premium_pct` to `intelligence_features`
- Reuses existing agent pattern

### D-07: Service Enablement

**Actions:**
- Run D-21 validation first
- If passes: `sudo systemctl enable indicagent-roll-compute.service`
- If fails: fix algorithm, revalidate

---

## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Roll Detection
- `services/roll_compute_agent.py` — RollComputeAgent (RollMonitor class, BaseAgent lifecycle)
- `production/scripts/validate_roll_detection.py` — D-21 validation script
- `src/config/contracts.py` — `get_roll_window()`, `derive_roll_chain()`, `FUTURES_ROLL_CYCLES`
- `src/core/schemas/market_events.py` — `RollEvent` schema (roll_gap_price, roll_gap_pct, detection_ts)

### Data Pipeline
- `services/bar_aggregator_compute_agent.py` — Publishes 5m bars to `market.bars.htf`
- `services/bar_writer_agent.py` — Writes to `market_data_ohlcv` (5m already there)
- `src/core/bar_accumulator.py` — BarAccumulator (HTF aggregation logic)

### Persistence
- `services/feature_writer_agent.py` — Needs to consume `topic_roll_events`
- `production/migrations/049_roll_premium_pct.sql` — Column definition (already applied)

### Architecture
- `CLAUDE.md` — DAG architecture, BaseAgent lifecycle, Golden Signals
- `src/core/stream_keys.py` — `topic_roll_events()`
- `src/core/agent/base.py` — BaseAgent class (RollComputeAgent inherits)

---

## Existing Code Insights

### Reusable Assets

- **RollMonitor** (in `roll_compute_agent.py`): Calendar + volume z-score algorithm. Implemented and tested.
- **BaseAgent** (`src/core/agent/base.py`): Lifecycle, metrics, Kafka wiring all exist.
- **FeatureWriterAgent**: Already consumes multiple topics, can add `topic_roll_events`.

### Established Patterns

- **Agent systemd units:** After=network-online.target, Wants=ibkr-provider, Restart=always
- **Kafka topics:** `topic_roll_events()` pattern already defined
- **Migration pattern:** `ALTER TABLE ... ADD COLUMN` already done in 049

### Integration Points

- **RollComputeAgent** → `topic_roll_events` → **FeatureWriterAgent** → `intelligence_features.roll_premium_pct`
- **I7 plugins** → read `features['roll_premium_pct']` → adjust confidence (future work)

---

## Specific Ideas

**Roll premium as signal:** When futures are in contango (front < back), market pays premium for front month. Extreme premium (>2%) often precedes mean reversion. This is NOT captured by OFI/CVD — it's contract structure information.

**D-21 validation is gate:** Don't enable service until algorithm proves accurate. "Earn the right through proof."

**5m view is trivial:** Just `CREATE VIEW market_data_5m AS SELECT * FROM market_data_ohlcv WHERE timeframe = '5m'`. No backfill needed.

---

## Deferred Ideas

- **I7 plugin integration:** Downstream consumers of roll_premium_pct deferred to Phase 51+
- **Roll premium as feature multiplier:** Aggregator weight adjustment based on roll premium (future)

---

*Phase: 50-roll-monitor-graduation*
*Context gathered: 2026-03-30*
*Approach: Full Renaissance DAG build-out*
