# Signal Replay Architecture — Renaissance Redesign Plan

**Created:** 2026-06-11
**Trigger:** Phase 121 orchestration taking hours; root cause analysis revealed three distinct architectural problems
**Goal:** Replay enters the DAG at the correct layer, signals have deterministic IDs, lifecycle evaluation is vectorized

---

## Pending: Full Signal Wipe (do after Phase 121 validates)

The 2.25M signals from non-Phase-121 setups were generated with pre-Phase-121 lifecycle logic — incomplete outcome columns, wrong evaluation. Mixing old and new signals in the training dataset is a hidden bias.

**Plan:** Once Phase 121 validates (current run completes and verify passes), run a full wipe:
1. `TRUNCATE signal_outcomes; TRUNCATE signal_ledger;` (tables will be decompressed — instant)
2. `run_historical_pipeline.py --replay-only --clean --setups ALL --workers 8`
3. `lifecycle_replay.py --workers 8` to populate outcomes for all regenerated signals

This is also the natural moment to deploy `feature_replay.py` (TASK-3) if it's ready — the full wipe is the first clean run where the new architecture can be used end-to-end.

---

## Problem Summary

The system has a deterministic DAG:
```
market_data_ohlcv → [I1→I6] → intelligence_features → [I7] → signal_ledger → [lifecycle] → signal_outcomes
```

Three compounding problems make replay slow and architecturally fragile:

1. **DAG violation** — `run_historical_pipeline.py --replay-only` enters at `market_data_ohlcv` even when `intelligence_features` is valid. Re-runs all I1→I6 compute (ON CONFLICT DO NOTHING discards the result), then runs I7. 100% wasted work. Hours instead of minutes.

2. **Random signal IDs** — Signal IDs are random UUIDs. Signals are deterministic outputs of `(ts, symbol, tf, setup_plugin, direction)`. Random IDs make ON CONFLICT DO UPDATE impossible, forcing DELETE + re-insert on every replay. Loses audit trail, breaks external references, defeats idempotency.

3. **Compression hostile to DML** — signal_ledger has 51 compressed chunks (2.1GB uncompressed). DELETE forces per-tuple decompression on write. market_data_ohlcv has 24 compressed chunks. Bar reads during lifecycle replay decompress on every fetch. Neither table is in the right state for bulk DML.

**Secondary:** Lifecycle replay inner loop is O(signals × bars) per (symbol, tf) pair. Top pairs have 29k pending signals. No vectorization.

---

## DB State (baseline 2026-06-11)

| Table | Rows | Compressed chunks | Uncompressed chunks | Compressed size | Uncompressed size |
|---|---|---|---|---|---|
| signal_ledger | 2,556,382 | 51 | 52 | 329 MB | 2.1 GB |
| signal_outcomes | ~2.5M | — | — | — | — |
| intelligence_features | 2,780,964 | 104 | 2 | 825 MB | 5.4 GB |
| market_data_ohlcv | — | 24 | 2 | 34 MB | 185 MB |

Pending lifecycle replay: 707,611 signals. Top pair: ESM6/1m = 29,652 pending.
Shadow signal rows (22 setups): 6,505. The delete itself is not the bottleneck.

---

## Work Items

### TASK-1: Decompress/recompress stages in phase_121_orchestrate.py
**Priority:** NOW — unblocks Phase 121
**Effort:** 1-2 hours
**File:** `production/scripts/phase_121_orchestrate.py`

Add two new stages wrapping the existing clean+replay sequence:

```
Stage 0: decompress   — decompress signal_ledger + market_data_ohlcv
Stage 1: snapshot
Stage 2: clean        (existing)
Stage 3: dry_run      (existing)
Stage 4: replay       (existing — bar reads now hit uncompressed chunks)
Stage 5: verify       (existing)
Stage 6: recompress   — recompress both tables
```

Implementation:

```python
STAGE_DECOMPRESS = "decompress"
STAGE_RECOMPRESS = "recompress"

async def _run_stage_decompress(state: dict) -> None:
    """Decompress signal_ledger + market_data_ohlcv before bulk DML."""
    if STAGE_DECOMPRESS in state["stages_complete"]:
        print(f"Stage {STAGE_DECOMPRESS}: already complete, skipping")
        return
    print(f"\n=== STAGE: {STAGE_DECOMPRESS} ===")
    settings = Settings()
    db = DatabaseManager(settings.database_url)
    await db.initialize()
    try:
        async with db.pool.acquire() as conn:
            for table in ("signal_ledger", "market_data_ohlcv"):
                result = await conn.fetch(
                    """SELECT decompress_chunk(format('%I.%I', chunk_schema, chunk_name)::regclass, true)
                       FROM timescaledb_information.chunks
                       WHERE hypertable_name = $1 AND is_compressed = true""",
                    table,
                )
                print(f"  {table}: decompressed {len(result)} chunks")
    finally:
        await db.close()
    _mark_complete(state, STAGE_DECOMPRESS)


async def _run_stage_recompress(state: dict) -> None:
    """Recompress signal_ledger + market_data_ohlcv after replay completes."""
    if STAGE_RECOMPRESS in state["stages_complete"]:
        print(f"Stage {STAGE_RECOMPRESS}: already complete, skipping")
        return
    print(f"\n=== STAGE: {STAGE_RECOMPRESS} ===")
    settings = Settings()
    db = DatabaseManager(settings.database_url)
    await db.initialize()
    try:
        async with db.pool.acquire() as conn:
            for table in ("signal_ledger", "market_data_ohlcv"):
                result = await conn.fetch(
                    """SELECT compress_chunk(format('%I.%I', chunk_schema, chunk_name)::regclass)
                       FROM timescaledb_information.chunks
                       WHERE hypertable_name = $1 AND is_compressed = false""",
                    table,
                )
                print(f"  {table}: compressed {len(result)} chunks")
    finally:
        await db.close()
    _mark_complete(state, STAGE_RECOMPRESS)
```

Update `_STAGE_ORDER` and `main_async()` to include the new stages.

**Acceptance criteria:**
- Phase 121 orchestrate completes end-to-end without hours-long stall
- Both tables recompressed after verify passes
- Decompress stage is idempotent (re-run safe)

---

### TASK-2: Audit and close uuid4() fallback gaps
**Priority:** Next sprint — small, low risk
**Effort:** 1-2 hours
**Status:** `make_signal_id()` already exists and is used in the two canonical signal-assignment paths:
- **Live pipeline:** `src/intelligence/pipeline/executor.py:906` — uses `make_signal_id()` correctly
- **Backfill:** `production/scripts/run_historical_pipeline.py:787` — uses `make_signal_id()` when `last_bar is not None`

**Remaining gaps (uuid4() fallbacks that break the determinism contract):**

| File | Line | Context |
|---|---|---|
| `run_historical_pipeline.py` | 800 | `else: sid = str(uuid4())` — when `last_bar is None` |
| `src/intelligence/schemas.py` | 925 | `signal_id=str(sig.get("signal_id") or uuid4())` — in `signal_dict_to_ranked()` |
| `services/signal_writer.py` | 209 | `signal_id=str(sig.get("signal_id") or uuid4())` — fallback on DB write |
| `services/alpha_swarm.py` | 491 | `signal_id = signal.signal_id or uuid4()` — AI swarm path |
| `services/narrative_swarm.py` | 117 | `signal_id = signal.signal_id or uuid4()` — narrative path |

The swarm/schema fallbacks are defensive (`or uuid4()`) — they only fire if the signal arrives without an ID, which should not happen if the executor correctly sets it upstream. But they are silent failure modes: a missing ID means the executor failed to set it, and the fallback hides that.

**Fix per site:**
- `run_historical_pipeline.py:800` — log warning + skip the signal if `last_bar is None`; a signal without bar data is malformed
- `schemas.py`, `signal_writer.py`, `alpha_swarm.py`, `narrative_swarm.py` — replace `or uuid4()` with `or _raise_missing_signal_id(sig)` (raises ValueError with signal context) to surface the upstream omission rather than silently masking it

**Acceptance criteria:**
- No silent `uuid4()` fallbacks remain in any signal-writing path
- Missing signal_id raises a loud error traceable to its origin, not a random ID

---

### TASK-3: feature_replay.py — I7-only replay from intelligence_features
**Priority:** Next sprint (after TASK-2)
**Effort:** 2-3 days
**File:** `production/scripts/feature_replay.py` (new)

**What it does:** Reads existing `intelligence_features` rows in time order, reconstructs IntelligenceEvent from stored JSONB, runs specified I7 plugins only, upserts signal_ledger via deterministic signal ID.

**Why:** Reduces shadow signal regeneration from hours (full I1→I7 re-run from bars) to minutes (I7-only pass over already-computed features).

**Interface:**
```
python production/scripts/feature_replay.py \
    --plugins trad_FVGFill,trad_POCRejection,...  \  # comma-separated or --shadow-setups flag
    --symbols ESM6,NQM6,...                          \  # default: all active contracts
    --since 2025-01-01                               \  # optional time window
    --workers 8
```

**Core loop:**
```python
async def _replay_plugin_for_pair(conn, symbol: str, tf: str, plugins: list[str]) -> int:
    """Stream intelligence_features for (symbol, tf), re-run I7 plugins, upsert signal_ledger."""
    rows = await conn.fetch(
        """SELECT ts, symbol, tf, bar, technical_indicators, pattern_detections,
                  regime_features, confluence_scores, smc, cross_timeframe_context
           FROM intelligence_features
           WHERE symbol = $1 AND tf = $2
           ORDER BY ts ASC""",
        symbol, tf,
    )
    upserted = 0
    for row in rows:
        event = _reconstruct_intelligence_event(row)  # unpack JSONB into IntelligenceEvent
        for plugin_name in plugins:
            plugin = _get_plugin(plugin_name)
            signals = plugin.evaluate(event)
            for sig in signals:
                sig.signal_id = make_signal_id(row["ts"], symbol, tf, plugin_name, sig.direction)
                await _upsert_signal(conn, sig)
                upserted += 1
    return upserted
```

**Key design constraints:**
- `_reconstruct_intelligence_event` must be the inverse of `_build_intelligence_event` in run_historical_pipeline.py — same JSONB schema, same field names
- Plugin instances must be initialized with the same state management as the live pipeline (GARCH/HMM/Kalman state must be seeded correctly before the replay loop)
- Upsert: `INSERT INTO signal_ledger ... ON CONFLICT (signal_id, timestamp) DO UPDATE SET ...` — requires TASK-2 (deterministic IDs) to be complete first

**Phase 121 clean stage after this ships:**
Replace `run_historical_pipeline.py --replay-only --clean --workers 8` with:
```
feature_replay.py --shadow-setups --workers 8
```

**Acceptance criteria:**
- Signal counts from feature_replay.py match within 1% of a full pipeline re-run for the same symbols/TFs
- Runtime under 10 minutes for full shadow set (22 plugins × all active symbols)
- Idempotent: running twice produces identical signal_ledger state
- No I1→I6 code paths invoked

---

### TASK-4: Vectorized lifecycle evaluation
**Priority:** Later (after TASK-2 + TASK-3)
**Effort:** 3-4 days
**File:** `production/scripts/lifecycle_replay.py`

**Problem:** Inner loop is `for bar in bars: for signal in active_signals: evaluate(signal, bar)`. For ES 1m with 29k signals × ~300k bars = ~8.7B scalar comparisons. Single-threaded Python, no vectorization.

**Fix:** Batch all active signals into numpy arrays, evaluate the full cohort against each bar in one vectorized operation:

```python
import numpy as np

# Build arrays once per (symbol, tf) pair
stop_prices  = np.array([s["stop_loss"] for s in active_signals])
target_prices = np.array([s["targets"][0] for s in active_signals])  # first target
entry_prices  = np.array([s["entry_price"] for s in active_signals])
signal_ids    = [s["signal_id"] for s in active_signals]

for bar in bars:
    low, high, close = bar["low"], bar["high"], bar["close"]

    stopped   = low  < stop_prices    # shape: (N,) bool
    targeted  = high > target_prices
    activated = (high >= entry_prices) | (low <= entry_prices)  # zone entry logic

    # Collect indices that changed state this bar
    newly_stopped  = np.where(stopped  & active_mask)[0]
    newly_targeted = np.where(targeted & active_mask)[0]
    # ... update active_mask, record exit_at, pnl_r, etc.
```

**Expected speedup:** 10-100x on the inner loop for dense signal cohorts.

**Acceptance criteria:**
- Lifecycle replay output (pnl_r, mae, mfe, exit_at, outcome) matches scalar loop within floating-point epsilon on a 10k-signal test case
- ES 1m (29k signals) processes in under 5 minutes
- All entry_type variants (at_close, at_pullback, at_limit, at_reclaim, zone_proximal) handled correctly in vectorized form

---

## Dependency Order

```
TASK-1 (decompress stages)   — independent, do now
TASK-2 (deterministic IDs)   — independent of TASK-1, do next sprint
TASK-3 (feature_replay.py)   — requires TASK-2 (upsert needs stable IDs)
TASK-4 (vectorized lifecycle) — independent of TASK-2/3, do after
```

---

## Files Touched

| Task | Files |
|---|---|
| TASK-1 | `production/scripts/phase_121_orchestrate.py` |
| TASK-2 | `src/intelligence/trading/signal_schema.py`, new migration script, `run_historical_pipeline.py`, signal fire path in intelligence_pipeline |
| TASK-3 | `production/scripts/feature_replay.py` (new), `production/scripts/phase_121_orchestrate.py` (update clean stage) |
| TASK-4 | `production/scripts/lifecycle_replay.py` |

---

## Notes

- TASK-1 is a tactical fix. TASK-2 + TASK-3 are the permanent architectural fix. Do not skip TASK-2 in favor of going straight to TASK-3 — without deterministic IDs, feature_replay.py still needs a delete step.
- intelligence_features does NOT need decompression for TASK-3 — sequential JSONB reads via ColumnarScan are fast for the analytics access pattern (full-table scan in time order).
- When TASK-3 ships, the `--replay-only` flag on run_historical_pipeline.py becomes correct again for its actual purpose: full pipeline re-run when I1→I6 is invalid.
- Consider adding a `validate_intelligence_features_complete(symbol, tf, since)` preflight check to feature_replay.py that aborts with a clear message if coverage gaps exist before starting the replay.
