<!-- generated-by: gsd-doc-writer -->
# Signal Lifecycle

**Version:** 2.8
**Status:** current
**Last Updated:** 2026-05-27

## Overview

A signal in IndicAgent is not a point-in-time event — it is a lifecycle. From the moment I7 fires a setup to the moment it expires or hits a target, the signal passes through a structured sequence of states tracked by the **SignalTrackerComputeAgent** (DB-ignorant compute) and persisted by the **LifecycleWriterAgent**.

The lifecycle captures:
- Whether the signal's entry zone was ever touched (activation)
- How far price moved in favor and against the trade (MAE/MFE)
- Which of 8 possible outcomes closed the trade
- Schema version for data quality gating (`signal_schema_version`)

This data becomes the **labeled training dataset** for the ML scoring model.

---

## Signal Origin: I7 Setup Detection

The I7 tier (36 setup plugins + CISScorer aggregator) fires signals when it detects high-confidence trading setups. The publisher (`intelligence_pipeline_agent.py`) normalizes every signal before emission:

- Injects `timestamp=bar_ts` (never empty)
- Sets `is_backfill` flag (for replay-generated signals)
- Sets `ttl_bars` (default: 10 — how many bars until expiry)
- Sets `signal_schema_version` (currently `'v1'`)
- Sets `expires_at` — TTL timestamp computed at insert time: `signal_ts + ttl_bars * tf_seconds`

Each signal is written to `signal_ledger` (TimescaleDB) with:

- `symbol`, `feature_ts`, `feature_tf` — join key back to `intelligence_features`
- `direction` — `1` (long) or `-1` (short)
- `entry_price` — resolved from zone geometry
- `entry_zone_low`, `entry_zone_high` — the entry zone bounds (NULL routes to DLQ)
- `stop_loss` — initial stop level
- `targets` — profit targets (JSONB list)
- `ttl_bars` — how many bars until the signal expires if never activated
- `expires_at` — absolute UTC timestamp at which the signal expires (bar-time wall-clock)
- `cis_score` — CISScorer output (0–1)
- `signal_schema_version` — `'v1'` (post-Phase-79 signals with proper zone geometry)

Signals start with `status = "pending"`.

---

## Signal States

```
pending           ──► active ──► expired
    └─────────────────────────────────► expired (ttl_expired, never_activated)
regime_suppressed ──► (virtual active) ──► expired (shadow, status never changes)
```

| State | Meaning |
|-------|---------|
| `"pending"` | Signal fired and regime-eligible; waiting for price to enter entry zone |
| `"active"` | Price entered the entry zone; trade is live |
| `"expired"` | Trade exited via stop, target, TTL expiry, chandelier stop, or condition expiry |
| `"regime_suppressed"` | Signal fired but failed the regime gate — not published to the stream. Tracked as a **shadow signal**: the lifecycle service virtually activates it from the signal bar close and records MAE/MFE/outcome without changing its status. This counterfactual data validates and tunes regime gate thresholds empirically. |

Signal status values are raw strings: `"pending"`, `"active"`, `"regime_suppressed"`, `"expired"`.

`regime_suppressed` signals accumulate as the primary feedback dataset for gate calibration.

---

## Activation: Zone Entry

The lifecycle pipeline is split into two services following the compute/writer DAG pattern:

- **`SignalTrackerComputeAgent`** (`services/signal_tracker_compute_agent.py`, systemd: `indicagent-signal-tracker-compute`) — DB-ignorant compute; reads 1m market bars and I7 signals, evaluates lifecycle transitions, publishes `LifecycleTransition` events to `intelligence.lifecycle` topic.
- **`LifecycleWriterAgent`** (`services/lifecycle_writer_agent.py`, systemd: `indicagent-lifecycle-writer`) — consumes `intelligence.lifecycle` topic and persists all transitions to `signal_ledger`.

For every pending signal, each new bar checks whether price entered the entry zone:

```python
# Zone-aware activation (from lifecycle_tracker.py)
bar_overlaps_zone = bar.low <= zone_high and bar.high >= zone_low

if bar_overlaps_zone:
    # D-01 temporal guard: never activate on a bar from before the signal fired
    if bar_time < signal_timestamp:
        return None
    # Activate
    activation_price = min(bar.high, zone_high)  # long
    # or: activation_price = max(bar.low, zone_low)  # short
```

On activation, `status` transitions to `"active"` and `activated_at` is recorded.

**NULL zone fields:** Signals with NULL `entry_zone_low` or `entry_zone_high` are routed to the DLQ by the signal writer — they never enter lifecycle tracking. This prevents silent fallback to `entry_price` (which produced incorrect results pre-Phase-107.5).

---

## TTL and expires_at (Phase 107.5)

**Prior to Phase 107.5**, TTL was evaluated by counting bars elapsed since signal fire using `(current_ts - signal_ts) / tf_seconds`. This required a LATERAL JOIN to `intelligence_features` during replay.

**After Phase 107.5**, TTL uses a pre-computed `expires_at` timestamp:

```python
expires_at = signal_ts + timedelta(seconds=ttl_bars * tf_seconds)
```

`expires_at` is written to `signal_ledger` at INSERT time (bar-time wall-clock, not server wall-clock). TTL evaluation in `evaluate_signal()`:

```python
# lifecycle_tracker.py — TTL check
expires_at = signal.get("expires_at")
if expires_at is None:
    # D-17: NULL expires_at is a data-integrity bug — increment counter, skip TTL
    _NULL_EXPIRES_AT_COUNTER.add(1, {"symbol": ..., "timeframe": ...})
elif bar_time is not None and bar_time >= expires_at:
    # TTL expired
    outcome = SignalOutcome.NEVER_ACTIVATED  # or TTL_EXPIRED_AHEAD/BEHIND
    return Transition(signal_id=sid, new_status=SignalStatus.EXPIRED, ...)
```

**Signal replay** (L9 `SignalReplayAuditorAgent`) uses `sl.expires_at < NOW()` directly — no LATERAL JOIN to `intelligence_features`:

```sql
SELECT ... FROM signal_ledger_full sl
WHERE sl.exit_at IS NULL
  AND sl.status IN ('pending', 'active')
  AND sl.expires_at IS NOT NULL
  AND sl.expires_at < NOW()
  AND sl.signal_schema_version = $1
ORDER BY sl.expires_at ASC
LIMIT $2
```

---

## MAE / MFE Tracking

Once active, the service tracks **Maximum Adverse Excursion** (MAE) and **Maximum Favorable Excursion** (MFE) in real time:

- **MAE** — worst drawdown against the trade in pnl_r units
- **MFE** — best peak in favor of the trade in pnl_r units

These are maintained as in-memory dicts keyed by `signal_id` and written to `signal_outcomes` when the trade closes.

---

## Exit Conditions (Priority Order)

`evaluate_signal()` checks exits in this order for active signals:

1. **Stop loss** — `bar.low <= stop_loss` (long) or `bar.high >= stop_loss` (short)
2. **Target hits** — checks highest target first; maps to outcome class
3. **Chandelier trailing stop** — ATR-based trailing stop (3× ATR multiple)
4. **Staleness condition expired** — 3 consecutive bars with composite staleness score > 0.5 (HMM regime flip + GARCH sigma ratio)
5. **TTL expiry** — `bar_time >= expires_at` (last check, only after all price-based checks)

---

## 8-Class Outcome Classification

Every closed signal receives one of 8 outcomes:

| Outcome | Trigger |
|---------|---------|
| `never_activated` | TTL expired, price never entered the entry zone |
| `stopped_at_entry` | Hit stop before leaving the entry zone (bar 0–2 in trade, or MFE <= 0.05) |
| `stopped_in_trade` | Hit stop after the trade was moving (bar 3+ in trade, MFE > threshold) |
| `target_1` | Price reached first target but not second |
| `target_1_2` | Price reached first and second target but not full |
| `target_full` | Price reached all targets |
| `ttl_expired_ahead` | TTL expired while trade was in positive territory (MFE > 0) |
| `ttl_expired_behind` | TTL expired while trade was in negative territory |

The stop outcomes (`stopped_at_entry` / `stopped_in_trade`) are resolved by `_classify_stop_outcome(mfe, bars_in_trade)` — the raw exit only knows a stop was hit, not which class.

---

## Outcome Propagation to LLM Audit

When a signal closes, the lifecycle service publishes the outcome to `llm.outcomes`:
- Signal ID, symbol, timeframe, outcome class, pnl_r, mae, mfe
- `indicagent-llm-writer` consumes this stream and back-fills the outcome onto any `llm_calls` records that generated this signal's narrative
- This closes the feedback loop: every LLM narrative call now knows whether the signal it described was profitable

---

## Database Schema

The `signal_ledger` table carries the fire-time record; `signal_outcomes` carries mutable lifecycle state (joined via `signal_ledger_full` view):

```sql
-- signal_ledger (fire-time, immutable)
signal_id           UUID
timestamp           TIMESTAMPTZ  -- signal fire time
symbol              TEXT
timeframe           TEXT
setup_plugin        TEXT
signal_type         TEXT
direction           INTEGER      -- 1=long, -1=short
entry_price         FLOAT
stop_loss           FLOAT
targets             JSONB        -- list of profit targets
entry_zone_low      FLOAT        -- NULL routes to DLQ at write time
entry_zone_high     FLOAT        -- NULL routes to DLQ at write time
ttl_bars            INTEGER NOT NULL DEFAULT 10
expires_at          TIMESTAMPTZ  -- computed at insert: signal_ts + ttl_bars * tf_seconds
cis_score           FLOAT
signal_schema_version TEXT        -- 'v1' for ML-quality signals

-- signal_outcomes (lifecycle state, mutable)
signal_id           UUID (FK)
status              TEXT DEFAULT 'pending'  -- pending|active|expired|regime_suppressed
activated_at        TIMESTAMPTZ
exit_at             TIMESTAMPTZ
bars_in_trade       INTEGER
mae                 FLOAT   -- maximum adverse excursion (pnl_r units)
mfe                 FLOAT   -- maximum favorable excursion (pnl_r units)
outcome             TEXT    -- one of 8 outcome classes
exit_price          FLOAT
exit_reason         TEXT    -- stop_loss|target_N|ttl_expired|chandelier_stop|condition_expired
swarm_multiplier    FLOAT
adjusted_confidence FLOAT
```

---

## Schema Versioning (Phase 79)

The `signal_schema_version` column distinguishes signal generations:

| Version | Meaning |
|---------|---------|
| `v0` | Pre-Phase-79 signals. Entry zones were zero-width or had incorrect entry_price for pullback/limit entry types. **ML training queries MUST exclude v0.** |
| `v1` | Post-fix signals with proper zone geometry, resolved entry_price, correct zone_low/zone_high bounds, and `expires_at` TTL column. |

The Phase 83 migration (`TRUNCATE TABLE signal_ledger`) removed all contaminated v0 data.

---

## Self-Healing: Bar Replay and Signal Replay

### BarReplayProviderAgent (L1)

A one-shot service that replays historical market data into the live pipeline:
- Reads `market_data_ohlcv` chronologically
- Publishes 1m bars to `market.bars` and HTF bars to `market.bars.htf`
- Checkpoint-based (resumes from last processed bar)
- Self-terminates when caught up to `NOW() - 5 minutes`

Use case: bootstrap a fresh pipeline, recover from extended downtime, or reprocess data after a signal schema upgrade.

### SignalReplayAuditorAgent (L9)

A periodic auditor (runs every 5 minutes) that resolves orphaned signal lifecycles:
- Queries `signal_ledger_full WHERE exit_at IS NULL AND expires_at IS NOT NULL AND expires_at < NOW() AND signal_schema_version = 'v1'`
- Replays each unresolved signal bar-by-bar against `market_data_ohlcv` using the same `evaluate_signal()` logic as the live tracker
- Publishes idempotent `LifecycleTransition` events (lifecycle writer deduplicates via `WHERE exit_at IS NULL`)
- Health invariant: `signal_replay_unresolved_gauge = 0`

**Two-path safety:** The live `SignalTrackerComputeAgent` handles real-time tracking. The replay auditor catches anything missed — service restarts, data gaps, delayed arrivals. Both use the same evaluation logic.

---

## Signal Generator Warmup

After a service restart, `IntelligencePipelineComputeAgent` needs ~50 live 1m bars (approximately 50 minutes) to warm up plugin state before setup plugins fire. The consumer group is NOT rewound on restart — it picks up from the current stream position. No signals will fire during warmup; this is expected and normal.

---

## Shadow Governance

All I7 plugins auto-enroll in the `shadow_registry` table at startup (idempotent via `ON CONFLICT DO NOTHING`).

- **Auto-enroll:** At startup, `enroll_all_plugins()` registers every TIER_I7 plugin
- **Promotion gate:** `n >= 100` resolved signals AND `bootstrap_ci_lower(pnl_r) > 0.0`
- **Demotion gate:** `EV[R] < -0.05` for 3 consecutive evaluation cycles

Shadow plugins fire and are tracked in `signal_ledger` with `is_shadow=True`. Their signals do not reach the stream-to-execution path until promoted.

---

## Training Data Use Case

The `signal_ledger` table with lifecycle outcomes is the primary labeled dataset for ML work:

```sql
SELECT
    f.*,                          -- 200+ feature columns from intelligence_features
    s.outcome,                    -- 8-class label
    s.mae, s.mfe,                 -- continuous targets
    s.bars_in_trade
FROM intelligence_features f
JOIN signal_ledger_full s
  ON f.symbol = s.symbol
 AND f.ts = s.feature_ts
 AND f.timeframe = s.feature_tf
WHERE s.outcome IS NOT NULL
  AND s.signal_schema_version = 'v1';  -- exclude contaminated v0 data
```

Every signal outcome tells you: given these market conditions at the time of entry, what happened?

---

## Related Documentation

- [Intelligence Tiers](intelligence-tiers.md) — I7 setup plugins and CISScorer
- [Regime Classification](regime-classification.md) — regime gates that filter I7 signals
- [Data Pipeline](../data/data-pipeline.md) — how signals flow from stream to TimescaleDB
- **Code:** `services/signal_tracker_compute_agent.py`, `services/lifecycle_writer_agent.py`, `services/signal_replay_auditor_agent.py`, `src/intelligence/trading/lifecycle_tracker.py`, `src/persistence/repository/signal_ledger_repository.py`
