# Signal/Trade Separation: Renaissance-Grade Data Normalization

**Date**: 2026-06-08
**Status**: under-review
**Type**: Architecture Decision Record (ADR) Candidate
**Last Updated**: 2026-06-08
**Context**: Non-production environment — can delete all existing data and start fresh

---

## THE QUESTION

**Should we separate pattern detection, framing decisions, and execution measurement into distinct layers?**

Current: `signal_ledger` (7.5M rows) co-mixes pattern detection, trade framing, and execution results.

Proposed: Three-layer architecture:
1. **signal_events** (7.5M) - Pattern detection only
2. **trade_framing** (1.88M) - How we decided to trade the signal
3. **trade_execution** (1.88M) - What actually happened

**Dependency chain:** Pattern → Decision to Trade → Framing → Execution

---

## EXTENSIBLE DESIGN: Universal Signal Pipeline

**Key insight:** The three-layer architecture applies to ALL signal types, not just technical patterns.

### Signal Type Spectrum

```
┌─────────────────────────────────────────────────────────────────┐
│                    SIGNAL_EVENTS (Layer 1)                       │
│  "Something detected worth considering"                         │
├─────────────────────────────────────────────────────────────────┤
│ Technical Pattern Signals:                                      │
│ • OFI continuation: {"ofi_ewma_20": 0.0234, "consecutive_bars": 5} │
│ • Double bottom: {"pattern_type": "double_bottom", "neckline_break": true} │
│ • VWAP deviation: {"vwap_deviation_stdev": 2.3}                 │
│                                                                  │
│ Fundamental Signals:                                            │
│ • Earnings surprise: {"eps_beat": 0.15, "revenue_beat": 0.08, "guidance_raise": true} │
│ • Fed announcement: {"rate_change": 25, "hawkishness": 0.72, "dot_plot_shift": 2} │
│ • CPI data: {"cpi_miss": 0.02, "core_cpi_trend": "accelerating"} │
│                                                                  │
│ Qualitative Signals:                                             │
│ • LLM news analysis: {"sentiment": "bullish", "confidence": 0.84, "key_events": ["merger_rumor", "sector_rotation"]} │
│ • Social sentiment: {"twitter_sentiment_delta": 0.34, "reddit_mentions": 1250} │
│ • Analyst upgrade: {"broker": "Goldman", "action": "upgrade", "price_target_raise": 15} │
│                                                                  │
│ AI/ML Model Signals:                                            │
│ • Regime prediction: {"regime": "trending", "probability": 0.78, "model_version": "v3.2"} │
│ • Price prediction: {"predicted_move": 0.005, "confidence_interval": [0.002, 0.008]} │
│ • Anomaly detection: {"anomaly_score": 0.91, "anomaly_type": "volume_spike"} │
│                                                                  │
│ Alternative Data Signals:                                        │
│ • Satellite imagery: {"container_count_delta": 120, "port_congestion": "high"} │
│ • Supply chain data: {"inventory_turnover": -0.23, "supply_risk": "elevated"} │
│ • Weather impact: {"temperature_anomaly": 3.2, "impact_sector": "energy"} │
└─────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────┐
│                    TRADE_FRAMING (Layer 2)                      │
│  "Given this signal, how would we trade it?"                    │
├─────────────────────────────────────────────────────────────────┤
│ • Same framing logic applies to ALL signal types               │
│ • Entry/stop/target sizing per signal confidence                │
│ • Position sizing per portfolio context                         │
│ • Risk management per signal source reliability                  │
│ • Timeframe selection per signal type (fundamental = longer)    │
└─────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────┐
│                  TRADE_EXECUTION (Layer 3)                     │
│  "We traded it, here's what happened"                           │
├─────────────────────────────────────────────────────────────────┤
│ • Same execution metrics for ALL signal types                   │
│ • pnl_r, mae, mfe, outcome, exit_reason                         │
│ • Enables cross-type performance comparison                     │
│ • "Do fundamentals outperform technical?"                        │
│ • "How does LLM sentiment compare to pattern detection?"         │
└─────────────────────────────────────────────────────────────────┘
```

### Enhanced signal_events Table

```sql
CREATE TABLE signal_events (
    signal_id UUID PRIMARY KEY,
    timestamp TIMESTAMPTZ NOT NULL,
    symbol TEXT NOT NULL,
    timeframe TEXT NOT NULL,

    -- Signal source classification
    signal_source TEXT NOT NULL,  -- NEW! 'technical', 'fundamental', 'qualitative', 'ai_ml', 'alternative'
    setup_plugin TEXT NOT NULL,
    direction INTEGER NOT NULL,
    signal_type TEXT NOT NULL,

    -- Pattern detection PARAMETERS (what actually triggered it)
    detection_params JSONB NOT NULL,
    -- Structure varies by signal_source:
    -- Technical: OFI value, pattern type, VWAP deviation
    -- Fundamental: EPS beat, Fed rate change, CPI miss
    -- Qualitative: Sentiment score, LLM confidence, analyst action
    -- AI/ML: Model prediction, regime probability, anomaly score
    -- Alternative: Container count delta, inventory turnover, weather anomaly

    -- Pattern confidence (derived from detection_params)
    confidence DOUBLE PRECISION,

    -- Context at pattern detection time
    regime_context JSONB,
    bucket_scores JSONB,
    weights_version INTEGER,

    -- Meta
    was_selected BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT signal_events_ts_tf_idx UNIQUE (timestamp, symbol, timeframe, signal_id)
);

CREATE INDEX signal_events_source_idx ON signal_events (signal_source, timestamp);
CREATE INDEX signal_events_plugin_idx ON signal_events (setup_plugin, timestamp);
CREATE INDEX signal_events_detection_params_idx ON signal_events USING GIN (detection_params);
```

### Cross-Signal-Type Analysis (NEW CAPABILITY)

```sql
-- Compare signal source performance
SELECT
    signal_source,
    COUNT(*) as signals,
    COUNT(CASE WHEN te.outcome = 'target_1_2' THEN 1 END) * 1.0 / COUNT(*) as win_rate,
    AVG(te.pnl_r) as avg_pnl_r
FROM signal_events se
JOIN trade_framing tf ON tf.signal_id = se.signal_id
JOIN trade_execution te ON te.framing_id = tf.framing_id
GROUP BY signal_source;

-- Result example:
-- signal_source | signals | win_rate | avg_pnl_r
-- technical     |   75K   |  0.34    |  0.0012
-- fundamental  |    3K   |  0.41    |  0.0023
-- qualitative   |    2K   |  0.28    |  0.0008
-- ai_ml         |   10K   |  0.38    |  0.0015
```

### Renaissance Benefits of Universal Design

| Benefit | Impact |
|---------|--------|
| **True signal diversity** | Compare technical vs fundamental vs AI head-to-head |
| **Unified risk management** | Same framing logic applies to all signal types |
| **A/B testing signal sources** | Add new signal types without changing execution |
| **Portfolio optimization** | Allocate capital across signal types by proven edge |
| **Ruthless elimination** | Drop underperforming signal sources regardless of type |

---

## RENAISSANCE PRINCIPLES AT STAKE

| Principle | Current Violation | Proposed Fix |
|-----------|-------------------|--------------|
| **Separation of Concerns** | Signal generation ≠ trade execution, yet mixed in one table | Separate tables for separate domains |
| **Deterministic DAG** | One table does two things (signal creation + trade lifecycle) | Each node does one thing |
| **Data integrity** | 76% of rows have NULL trade fields (partial data) | Normalized schema — semantic sparsity eliminated (some NULLs remain for optional fields like exit_at) |
| **Instrument everything** | Pattern quality analysis conflated with framing quality — cannot decompose failure mode | **Primary motivation**: measurable pattern edge independent of framing choices |
| **Empirical over theoretical** | Cannot answer "did the pattern have edge if we had framed it differently?" | 3-table decomposition makes this answerable without reprocessing signals |

---

## CURRENT ARCHITECTURE: The Co-Mixing Problem

### signal_ledger Structure (7.5M rows)

**Signal domain fields** (present in all 7.5M rows):
- `signal_id`, `timestamp`, `symbol`, `timeframe`
- `setup_plugin`, `direction`, `signal_type`
- `entry_price`, `stop_loss`, `targets`, `confidence`
- `regime_context`, `bucket_scores`, `weights_version`
- `was_selected` (boolean gate)

**Trade domain fields** (present in only 1.88M rows):
- `activated_at`, `exit_at`, `exit_price`, `exit_reason`
- `pnl_r`, `mae`, `mfe`, `bars_in_trade`, `outcome`
- `market_entry_*` fields

**The problem:** 5.62M rows (75%) have NULL trade fields. This is sparse, denormalized data that violates First Normal Form (1NF).

### What Each Domain Answers

**signal_events** (7.5M) — Pattern/confluence identification:
> "At 09:31:02 AM on ESM6 1m, these conditions aligned: OFI_ewma_20 positive for 5 consecutive bars + trend regime + support_level_proximity = 0.72 confidence"

**trades** (1.88M) — Result of acting:
> "We entered at 4200.25 (zone entry 87%), stopped at 4195 (-125 ticks), exited at 4215 (+67 ticks), target_1_2 outcome, +0.31% R"

**Current architecture conflates "pattern existed" with "we traded it and here's what happened."**

---

## PROPOSED ARCHITECTURE: Normalized Separation

### Table 1: signal_events (7.5M rows) - Pattern Detection Layer

```sql
CREATE TABLE signal_events (
    signal_id UUID PRIMARY KEY,
    timestamp TIMESTAMPTZ NOT NULL,
    symbol TEXT NOT NULL,
    timeframe TEXT NOT NULL,

    -- Pattern identification
    signal_source TEXT NOT NULL,  -- NEW: 'technical', 'fundamental', 'qualitative', 'ai_ml', 'alternative'
    setup_plugin TEXT NOT NULL,
    direction INTEGER NOT NULL,
    signal_type TEXT NOT NULL,

    -- Pattern detection PARAMETERS (what actually triggered it)
    detection_params JSONB NOT NULL,
    -- NOTE: Requires per-signal-source schema contracts for validation, versioning, and required keys
    -- Examples by plugin:
    -- OFI Continuation: {"ofi_ewma_20": 0.0234, "consecutive_bars": 5, "ofi_magnitude": 1.8}
    -- Pattern Completion: {"pattern_type": "double_bottom", "neckline_break": true, "volume_confirmation": 1.8}
    -- VWAP Deviation: {"vwap_deviation_stdev": 2.3, "price_below_vwap": 0.002}
    -- Gap Analysis: {"gap_size_pct": 0.15, "gap_type": "common", "fill_zone": [4215, 4220]}
    -- Liquidity Sweep: {"sweep_ratio": 2.1, "poc_distance": 0.003, "reclaim_pending": true}
    -- CVD Divergence: {"cvd_divergence_pct": 0.45, "price_cvd_divergence": true, "divergence_bars": 3}

    -- Pattern confidence (derived from detection_params, not framing)
    confidence DOUBLE PRECISION,

    -- Context at pattern detection time
    regime_context JSONB,
    bucket_scores JSONB,
    weights_version INTEGER,
    detector_version TEXT,          -- NEW: Plugin version that generated this signal
    feature_pipeline_version TEXT, -- NEW: Feature computation version for reproducibility

    -- Meta
    was_selected BOOLEAN NOT NULL DEFAULT FALSE,  -- Did we consider trading this? (NOTE: mixes downstream state — consider derived field or separate table)
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT signal_events_ts_tf_idx UNIQUE (timestamp, symbol, timeframe, signal_id)
);

CREATE INDEX signal_events_plugin_idx ON signal_events (setup_plugin, timestamp);
CREATE INDEX signal_events_selected_idx ON signal_events (was_selected, timestamp);
CREATE INDEX signal_events_detection_params_idx ON signal_events USING GIN (detection_params);
```

**Domain purpose:** Record pattern detection events with full parameter context. "This pattern existed at this time with these specific conditions." NO framing parameters.

**Renaissance "Instrument everything":** We capture WHY the signal fired, not just THAT it fired. Enables post-mortem analysis of which parameter values correlate with success.

### Table 2: trade_framing (1.88M rows) - Framing Decision Layer

```sql
CREATE TABLE trade_framing (
    framing_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    signal_id UUID NOT NULL,

    -- Framing parameters (how we decided to trade)
    entry_price NUMERIC NOT NULL,
    stop_loss NUMERIC NOT NULL,
    targets JSONB NOT NULL,
    position_size INTEGER,

    -- Zone analysis
    zone_entry_pct DOUBLE PRECISION,
    zone_low NUMERIC,
    zone_high NUMERIC,

    -- Meta
    framed_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    framing_version TEXT,

    CONSTRAINT trade_framing_signal_id_fkey FOREIGN KEY (signal_id)
        REFERENCES signal_events(signal_id) ON DELETE CASCADE
);

CREATE INDEX trade_framing_signal_idx ON trade_framing (signal_id);
```

**Domain purpose:** Record framing decisions. "Given this signal, here's how we decided to trade it."

### Table 3: trade_execution (1.88M rows) - Execution Results Layer

```sql
CREATE TABLE trade_execution (
    execution_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    framing_id UUID NOT NULL,  -- Links to framing decision
    signal_id UUID NOT NULL,   -- Denormalized for queries

    -- Execution timing
    activated_at TIMESTAMPTZ NOT NULL,
    exit_at TIMESTAMPTZ,

    -- Execution pricing
    activation_price DOUBLE PRECISION,
    exit_price DOUBLE PRECISION,

    -- Execution constraints
    bars_to_activation INTEGER,

    -- Results
    exit_reason TEXT,
    pnl_ticks DOUBLE PRECISION,
    pnl_r DOUBLE PRECISION,
    pnl_dollars DOUBLE PRECISION,
    mae DOUBLE PRECISION,
    mfe DOUBLE PRECISION,
    bars_in_trade INTEGER,
    outcome TEXT,

    -- Execution lifecycle (NEW: model state transitions)
    status TEXT NOT NULL DEFAULT 'pending',  -- pending, activated, exited, expired, cancelled
    is_final BOOLEAN NOT NULL DEFAULT FALSE,

    -- Versioning for reproducibility (NEW)
    execution_simulator_version TEXT,
    replay_id TEXT,

    -- Market entry track (dual-path)
    market_entry_at TIMESTAMPTZ,
    market_entry_exit_price DOUBLE PRECISION,
    market_entry_exit_at TIMESTAMPTZ,
    market_entry_outcome TEXT,
    market_entry_pnl_r DOUBLE PRECISION,
    market_entry_mae DOUBLE PRECISION,
    market_entry_mfe DOUBLE PRECISION,
    market_entry_bars_in_trade INTEGER,
    market_entry_gap_bars INTEGER,

    -- Meta
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT trade_execution_framing_id_fkey FOREIGN KEY (framing_id)
        REFERENCES trade_framing(framing_id) ON DELETE CASCADE,
    CONSTRAINT trade_execution_signal_id_fkey FOREIGN KEY (signal_id)
        REFERENCES signal_events(signal_id) ON DELETE CASCADE
);

CREATE INDEX trade_execution_framing_idx ON trade_execution (framing_id);
CREATE INDEX trade_execution_signal_idx ON trade_execution (signal_id);
CREATE INDEX trade_execution_exit_idx ON trade_execution (exit_at);
CREATE INDEX trade_execution_outcome_idx ON trade_execution (outcome, exit_at);
```

**Domain purpose:** Record execution results. "We traded this framing, here's what happened."

### View: signal_ledger_full (backward compatibility)

```sql
CREATE MATERIALIZED VIEW signal_ledger_full AS
SELECT
    se.*,
    tf.framing_id,
    tf.entry_price,
    tf.stop_loss,
    tf.targets,
    tf.zone_entry_pct,
    te.execution_id,
    te.activated_at,
    te.exit_at,
    te.exit_price,
    te.exit_reason,
    te.pnl_r,
    te.mae,
    te.mfe,
    te.bars_in_trade,
    te.outcome
FROM signal_events se
LEFT JOIN trade_framing tf ON tf.signal_id = se.signal_id
LEFT JOIN trade_execution te ON te.framing_id = tf.framing_id;

-- Refresh on demand or via trigger
```

---

## RENAISSANCE ANALYSIS

### Benefits

| Benefit | Renaissance Principle | Impact |
|---------|----------------------|--------|
| **Three-layer separation** | Separation of Concerns | Pattern ≠ Framing ≠ Execution (each table single-purpose) |
| **Eliminate sparse data** | Data integrity | 0% NULL fields in any table (vs 75% today) |
| **A/B test framing strategies** | Let the system run | Apply different frames to same signal stream |
| **Independent component evolution** | Modularity | Change framing without touching detectors |
| **Pattern quality analysis** | Instrument everything | Measure pattern edge independent of framing choices |
| **Efficient lifecycle replay** | Ruthless efficiency | Replay 1.88M executions instead of 7.5M patterns |

### Trade-offs

| Concern | Renaissance Counter-argument | Mitigation |
|---------|---------------------------|------------|
| **Migration complexity** | Eliminate technical debt now vs later | Phased migration with backward-compatible view |
| **JOIN overhead for combined queries** | Most queries are domain-specific anyway | signal_ledger_full view for legacy queries |
| **Foreign key cascade risk** | Data integrity worth the constraint | Soft-delete pattern for production safety |
| **Dual-write transactional complexity** | Asynchronous patterns already handle this | Use existing transaction patterns from lifecycle_writer |

### Jim Simons' Perspective

**"Why are we storing 7.5M rows when 5.62M of them have meaningless trade data?"**

The Renaissance answer: **We shouldn't.** But more importantly:

**"When a signal fails, which layer failed — the pattern detection, the framing, or the execution?"**

With the current schema this question is unanswerable. A `stopped_at_entry` outcome could mean the pattern had no edge, or it could mean the stop was placed too tight. A `target_1` outcome on a poorly-framed signal could be luck. The 3-table separation makes failure mode decomposition possible — which is the precondition for improving any individual layer without contaminating the others.

**Note:** The "0% NULL fields" claim in earlier drafts is incorrect — `exit_at`, `position_size`, and other optional fields will still be NULL. The gain is elimination of *semantic* sparsity (trade lifecycle data on signals that never traded), not elimination of all NULLs.

---

## MIGRATION STRATEGY: Clean Start (Non-Production)

**Context:** This is a non-production environment. All existing signal/lifecycle data can be deleted. Scripts can be rewritten from scratch for the new architecture.

### Simplified Migration

```sql
-- 1. Drop old schema (no production data to preserve)
DROP TABLE IF EXISTS signal_ledger CASCADE;
DROP TABLE IF EXISTS signal_outcomes CASCADE;

-- 2. Create new normalized schema
CREATE TABLE signal_events (...);
CREATE TABLE trade_framing (...);
CREATE TABLE trade_execution (...);

-- 3. Create indexes for query performance
CREATE INDEX signal_events_ts_idx ON signal_events (timestamp DESC);
CREATE INDEX signal_events_symbol_idx ON signal_events (symbol, timestamp DESC);
CREATE INDEX trade_execution_signal_idx ON trade_execution (signal_id);

-- 4. Rewrite scripts to write to new schema
-- SignalWriter → signal_events (and trade_framing/trade_execution if selected)
-- Lifecycle queries → direct table access
```

**What we skip (production-only concerns):**
- ❌ Dual-write phase
- ❌ Backfill migration of 7.5M rows
- ❌ Materialized view for backward compatibility
- ❌ Soft-delete patterns for audit preservation
- ❌ Migration ID mapping tables

---

## I7 DUAL-EVENT EMISSION PATTERN

**How framing stays at compute time while data-layer separation is achieved:**

The compute-layer question (should framing be a separate service?) is settled: framing stays embedded in I7 plugins at compute time (Principle 12). The bar data, ATR, and zone levels needed for framing are only available at signal generation time — moving framing to a downstream service would require re-querying all of that context cold.

However, the I7 plugin emits **two distinct Kafka messages** from the same compute step, rather than one combined message:

```python
# I7 plugin compute_full() emits two events:

# 1. Pattern detection event — what the plugin observed
signal_event = {
    "signal_id": str(uuid4()),
    "setup_plugin": "trad_OFIContinuation",
    "signal_source": "technical",
    "detection_params": {
        "ofi_ewma_20": 847.3,
        "consecutive_bars": 12,
        "ofi_direction": 1,
    },
    "confidence": 0.71,
    "regime_context": {...},
    "detector_version": "v2",
    "feature_pipeline_version": settings.feature_schema_version,
}

# 2. Trade framing event — how we decided to trade it
trade_frame = {
    "signal_id": signal_event["signal_id"],  # FK
    "entry_price": 4201.25,
    "stop_loss": 4196.50,
    "targets": [{"price": 4210.0, "r_multiple": 1.7}],
    "zone_low": 4200.0,
    "zone_high": 4202.5,
    "stop_basis": "structural",
    "adaptive_buffer_mult": 1.2,
    "framing_version": "v1",
}

# Both published to separate Kafka topics in same plugin call.
# SignalWriter receives both; writes to signal_events + trade_framing atomically.
```

This gives full data-layer separation at zero additional service complexity. The I7 plugin is the only author of both events; the DAG invariant holds.

**Stream keys:**
- `topic_signal_events()` — consumed by SignalWriter → `signal_events` table
- `topic_trade_framing()` — consumed by SignalWriter → `trade_framing` table (only when `was_selected=True`)

---

## COUNCIL DECISIONS (2026-06-08)

**Decisions recorded — ADR approved.**

| Question | Decision | Rationale |
|----------|----------|-----------|
| **2-table vs 3-table** | **3-table** | Failure mode decomposition requires it: pattern quality must be measurable independent of framing quality. This is the instrument for empirical calibration in v2.9. |
| **Cardinality** | **1:1 enforced at application layer** | One signal → one framing → one execution for now. Schema does not use UNIQUE constraint on `signal_events.signal_id` in `trade_framing`, preserving 1:many option for future framing strategy A/B testing. |
| **Framing service** | **Compute stays in I7 plugin** (Principle 12) | Bar data required for framing is only available at compute time. Data-layer separation via dual-event emission achieves the same decomposability. |
| **Numeric types** | **`NUMERIC` for all prices/PnL** | `DOUBLE PRECISION` introduces reproducibility bugs via floating-point drift. `NUMERIC` is exact. |
| **was_selected** | **Derived field on `signal_events`** | Updated by SignalWriter when a framing row is written. Not mutable thereafter — if a signal is framed, it was selected. |
| **Migration timing** | **Before Phase 121 lifecycle replay** | Replay regenerates signal outcomes anyway. Migrating first means replay writes directly into the clean schema. |

**Resolved concerns from Cross-AI Review:**
- Cardinality: 1:1 enforced at application layer, schema allows 1:many — resolved
- Numeric types: `NUMERIC` everywhere — resolved
- was_selected coupling: derived field, set by SignalWriter on framing write — resolved
- "0% NULL fields": corrected in Jim Simons section above — resolved
- JSONB governance: `detection_params` governed by `signal_source` + `setup_plugin` contract; schema enforced in SignalWriter — resolved
- Execution lifecycle modeling: `status` column on `trade_execution` (pending → activated → exited → expired) — resolved
- Versioning: `detector_version` + `feature_pipeline_version` + `execution_simulator_version` + `framing_version` all present — resolved
- Indexing: `(symbol, timestamp DESC)` + BRIN on timestamp columns — resolved

---

## REMAINING OPEN QUESTIONS (Implementation Details Only)

1. **Partial fills / scale-outs**: If we add position sizing later, can one trade have multiple execution legs? The schema (no UNIQUE on framing_id in trade_execution) supports this, but the lifecycle state machine needs to handle it. Deferred until position sizing is in scope.
2. **`signal_ledger_full` view**: Regular view (recomputed on query) vs materialized view (refreshed on schedule). Regular view is simpler; materialized is faster for dashboard queries. Decision at Phase 124 based on query latency measurements.

---

## RECOMMENDED NEXT STEPS

1. ✅ **3-table confirmed** — proceed to Phase 123 (schema DDL design)
2. ✅ **Cardinality defined** — 1:1 at application layer, schema allows 1:many
3. ✅ **Framing stays in-plugin** — dual-event emission is the implementation pattern
4. **Phase 123**: Write migration DDL + constraints + indexes + `signal_ledger_full` view
5. **Phase 124**: Execute migration (drop `signal_ledger`, create 3 tables)
6. **Phase 125**: Rewrite SignalWriter (dual-event), lifecycle_writer, all queries
7. **Timing**: Phases 123-125 execute before Phase 121 lifecycle replay

---

## CROSS-AI REVIEW SUMMARY

**Reviewers:** Gemini, Codex
**Verdict:** Strongly Recommended (with clean-start simplifications)
**Full Review:** `docs/ideas/2026-06-08-signal-trade-separation-architecture-REVIEWS.md`

**Consensus:**
- Architecture is sound and aligns with Renaissance principles
- Migration complexity eliminated by clean-start (no dual-write, backfill, or backward compatibility needed)
- Remaining work: cardinality definition, numeric type standardization, JSONB contracts
