# Renaissance Pipeline Refactor — Design Spec

**Date:** 2026-03-21
**Status:** Shipped (Phase 44)
**Supersedes:** `docs/superpowers/specs/2026-03-21-feature-pipeline-renaissance-design.md`
**Phases:** 44.1 (FeaturePipelineService), 44.2 (SignalGeneratorService consolidation), 44.3 (Atomic persistence + OHLCV)

> **Name drift note (2026-03-28):** Names used in this spec reflect Phase 44 conventions. Subsequent renames: `FeaturePipelineService` → `FeatureComputeAgent` (Phase 44→52); `SignalLifecycleService` → `SignalTrackerAgent` (Phase 52.4); `indicagent-feature-pipeline` → `indicagent-feature-compute`.

---

## Problem Statement

Five structural violations of Renaissance principles in the current intelligence pipeline:

1. **Bar history in three places** — `OrderedDict` in indicator_service, `deque(200)` in market_analysis_service, `deque(200)` in signal_generator_service. Divergence is guaranteed. Bugs fixed in one are not fixed in others.

2. **11 Kafka execution hops** — 3 hops for I1-I6 (bars → indicators → intelligence → feature_writer), 8 hops for the I7 pipeline (6 separate stage services chained via Kafka). Each hop adds latency and an ordering risk.

3. **Two-phase write corrupts ML training data** — `intelligence_features` rows are written incomplete: I1-I6 first, i7 UPSERT arrives separately. Every ML training row has a window of incompleteness. If the service restarts between phases, rows are permanently broken.

4. **OHLCV has two sources of truth** — historical bars in `market_data_ohlcv` (proper table), live bars buried in `intelligence_features.bar` (JSONB). The boundary between them shifts with every deployment.

5. **Pipeline stages are services wrapping pure functions** — `quality_gate`, `regime_gate`, `tod_adjuster`, `calibrator`, `ranker`, `winner_selector` are deterministic transforms on a signal dict. Making each a separate service adds 6 systemd units, 6 Kafka topics, 6 consumer groups, and 6× the latency for zero alpha benefit. Observability does not require network hops.

---

## Renaissance Principles Applied

- **Observation is not decision.** I1-I6 answers "what is the market doing?" I7 answers "what should the model do about it?" These are separate epistemic problems — separate services, typed contract between them.
- **Separate modules, not separate services.** The DAG is enforced by code structure and typed interfaces, not network topology. Services are for independent scaling, deployment, and failure domains. Pipeline stages have none of these properties.
- **Atomic training data.** The ML training dataset must have complete rows at insert time. No race conditions, no partial writes, no undefined behavior.
- **One source of truth.** One OHLCV table. One bar history implementation. One persistence path.
- **Instrument everything.** Every stage emits counts. Every failure is observable. Every dropped audit is counted, not silent.

---

## Architecture

### Service DAG

```
TWS Daemon
    │
    ▼  development.market.bars  (BarMessage — typed)
    │
FeaturePipelineService                          [NEW — Phase 44.1]
    Replaces: indicator_service
              market_analysis_service
              timeframes_builder_service
    ─ BarAccumulator (in-process HTF derivation)
    ─ BarHistory (shared module, src/core/)
    ─ I1 → I2 → I3 → I4 → I5 → I6
    ─ Writes live 1m bars to market_data_ohlcv (async batch)
    │
    ├──► development.market.bars.htf
    └──► development.intelligence        (IntelligenceEvent, i1–i6 complete)
    │
    ▼
SignalGeneratorService                          [REFACTORED — Phase 44.2]
    Absorbs: quality_gate, regime_gate, tod_adjuster,
             calibrator, ranker, winner_selector
    ─ BarHistory (same shared module, seeded from IntelligenceEvent.bar)
    ─ I7 plugin execution (36 plugins)
    ─ In-process pipeline stages (pure functions, src/intelligence/pipeline/):
        apply_quality_gate() → apply_regime_gate() → apply_tod_adjustment()
        → apply_calibration() → rank_signals() → select_winner()
    ─ Async observability publishes via bounded audit queue:
        pipeline.quality_gated, pipeline.regime_gated, pipeline.tod_adjusted,
        pipeline.calibrated, pipeline.ranked, pipeline.winner
    ─ Writes winner to signal_ledger (failure: log + metric, pipeline continues)
    ─ Publishes development.intelligence.i7 (intentional redundancy —
        dashboard backward compatibility; retire after Phase 44.x stable)
    │
    ├──► development.intelligence.record    (BarIntelligenceRecord — complete)
    └──► development.signals.aggregated     (winner for SignalLifecycleService)
    │
    ▼
FeatureWriterService                            [SIMPLIFIED — Phase 44.3]
    Consumes: development.intelligence.record ONLY
    Single atomic INSERT per bar — no UPSERTs, no partial rows
    │
    ▼  intelligence_features hypertable (complete rows, always)

─── Unchanged ────────────────────────────────────────────────────────
LLMWriterService     → consumes intelligence.i8
                     → writes llm_calls (primary)
                     → UPSERTs intelligence_features.i8 (moved from feature_writer)
SignalLifecycleService → market.bars.htf + signals.aggregated
AINarrativeService   → intelligence (unchanged)
CrossAssetService    → cross_asset (unchanged)
API / SSE            → all topics, read-only fan-out
```

### Services Retired (Phase 44.1)
`indicagent-indicator`, `indicagent-market-analysis`, `indicagent-timeframes`

### Services Retired (Phase 44.2)
`indicagent-quality-gate`, `indicagent-regime-gate`, `indicagent-tod-adjuster`,
`indicagent-calibrator`, `indicagent-ranker`, `indicagent-winner-selector`

**Net: 18 services → 9. 11 Kafka execution hops → 2.**

---

## Data Contracts

### `BarMessage` — `src/core/schemas/bar_message.py`

Replaces string dicts from TWS daemon. Eliminates every `float(bar["open"])` coercion.

```python
class SessionType(str, Enum):
    RTH = "rth"
    ETH = "eth"
    CRYPTO = "crypto"
    FX = "fx"
    CLOSED = "closed"

class BarMessage(BaseModel):
    schema_version: str = "1.0"
    ts: datetime            # UTC-aware, bar open time
    symbol: str
    tf: str
    open: float
    high: float
    low: float
    close: float
    volume: int
    source: Literal["ibkr_live", "ibkr_seed", "htf_derived"]
    session_type: SessionType
    gap_preceding: bool     # True if expected prior bar was missing
```

### `IntelligenceEvent` — extend in-place (`src/intelligence/schemas.py`)

Existing i1–i6 tier fields unchanged. Two fields added:

```python
schema_version: str = "1.0"
session_type: SessionType = SessionType.RTH
pipeline_latency_ms: float = 0.0
```

### `RankedSignal` — `src/intelligence/schemas.py`

```python
class RankedSignal(BaseModel):
    signal_id: str
    plugin: str
    direction: str
    raw_confidence: float
    calibrated_confidence: float
    regime_eligible: bool
    quality_score: float
    tod_multiplier: float
    adjusted_rank: float
    is_winner: bool         # True for exactly one signal per bar (or none)
```

### `BarIntelligenceRecord` — `src/intelligence/schemas.py`

The canonical labeled training sample for Phase 49 ML. Published to `development.intelligence.record`.

```python
class BarIntelligenceRecord(BaseModel):
    schema_version: str = "1.0"

    # Full observation (i1–i6)
    intelligence: IntelligenceEvent

    # Full decision layer — ALL candidates, ALL scores, winner flagged
    # Never drop signal candidates — each is a potential ML feature column
    ranked_signals: list[RankedSignal]

    # Denormalized winner — fast access without JSONB parsing
    winner_plugin: str | None = None
    winner_confidence: float | None = None
    winner_direction: str | None = None

    # Pipeline funnel audit — observable at every stage
    signals_evaluated: int          # raw I7 outputs before any gating
    signals_after_quality: int
    signals_after_regime: int
    signals_after_tod: int
    signals_after_calibration: int  # = len(ranked_signals)

    # Persistence audit
    ledger_written: bool            # False on signal_ledger write failure
                                    # Phase 49 filters WHERE ledger_written = TRUE

    # Denormalized from IntelligenceEvent — top-level for fast INSERT without JSONB parse
    session_type: SessionType       # mirrors intelligence.session_type
    days_to_expiry: int | None      # computed by FeaturePipelineService from expiry map (startup step 2)

    # Timing
    i7_computed_at: datetime
    pipeline_latency_ms: float      # bar_close_ts → record publish delta
```

### Stream Key Functions (`src/core/stream_keys.py`)

New addition — follows `topic_<thing>()` pattern:
```python
def topic_intelligence_record(env_name: str) -> str:
    """Complete BarIntelligenceRecord — single atomic persistence source."""
    return f"{env_prefix(env_name)}intelligence.record"
```

> **Note on existing pipeline topic functions:** `stream_keys.py` already defines `topic_quality_gated()`, `topic_regime_gated()`, `topic_tod_adjusted()`, `topic_calibrated()`, `topic_ranked()`, `topic_winner()` (no `pipeline_` infix). Phase 44.2 uses these existing names. The audit queue payloads in `_queue_stage_audits()` use these functions directly.

---

## Shared Modules

### `src/core/bar_history.py`

Single implementation replacing three diverging bar buffers. **No pandas dependency** — core modules have zero domain dependencies.

```python
class BarHistory:
    def __init__(self, maxlen: int = 200) -> None:
        self._data: dict[tuple[str,str], deque[BarMessage]] = defaultdict(
            lambda: deque(maxlen=maxlen)
        )
        # Opaque cache slot — service layer stores its own derived representation here
        # (e.g., DataFrame). Typed Any in core to avoid pandas import dependency.
        self._frame_cache: dict[tuple[str,str], Any] = {}
        # Note: pandas is banned from src/core/ — DataFrame construction happens at service layer

    def append(self, bar: BarMessage) -> None: ...
    def get(self, symbol: str, tf: str) -> deque[BarMessage]: ...

    def get_arrays(self, symbol: str, tf: str) -> dict[str, np.ndarray]:
        """Return OHLCV as numpy arrays. O(n) first call per bar, O(1) after.
        Pandas conversion happens at the service layer via _build_frames()."""
        ...

    def is_warm(self, symbol: str, tf: str, min_bars: int) -> bool: ...
    def seed(self, symbol: str, tf: str, bars: list[BarMessage]) -> None: ...
    def migrate_symbol(self, old: str, new: str) -> None: ...  # futures rolls
```

`is_warm()` is the single warmup gate. No plugin ever checks `len(history) > N` directly.

### `src/core/bar_accumulator.py`

Derives HTF bars from 1m stream in-process. Replaces `timeframes_builder_service`. Eliminates DB aggregate view queries for HTF context at I6.

```python
class BarAccumulator:
    def __init__(self, timeframes: list[str]) -> None: ...

    def update(self, bar_1m: BarMessage) -> list[BarMessage]:
        """Returns [] most bars, [BarMessage, ...] when HTF windows close.
        Window boundaries are time-based, not count-based.
        Does not synthesize bars for gaps — no data fabrication."""
        ...

    def current_partial(self, tf: str) -> BarMessage | None:
        """In-progress partial bar — used for startup state restore."""
        ...
```

Session-aware: partial bars at session boundaries are closed and emitted, not carried forward. `source="htf_derived"` on all output bars.

---

## FeaturePipelineService Internals

**File:** `services/feature_pipeline_service.py`
**Systemd:** `indicagent-feature-pipeline`
**Metrics port:** `:9109`

### Startup Sequence (strict order — no live bars processed with cold history)

```
1. Connect DB + Kafka
2. Build expiry map (once, cached for service lifetime)
3. Seed BarHistory:
   — single ROW_NUMBER() window query on intelligence_features
     (last 200 rows per symbol+tf, all in one query — not 61×5 queries)
   — fallback: market_data_ohlcv for any (symbol,tf) below min_bars_for_tf()
4. Restore BarAccumulator partial state:
   — seek development.market.bars to last 5m window boundary (~5 min replay)
   — deterministic: same replay = same partial accumulator state
5. Re-publish last known IntelligenceEvent per (symbol,tf) → development.intelligence
6. Subscribe to development.system.events (futures roll events)
7. Begin consuming development.market.bars
```

### Per-Bar Execution

```python
_CONCURRENCY_LIMIT: int = min(32, (os.cpu_count() or 4) * 2)
# Semaphore created in run() — not module-level (unsafe before event loop)

async def _process_symbol(self, bar: BarMessage) -> None:
    bar = self._detect_gap(bar)             # sets gap_preceding flag
    self.bar_history.append(bar)
    self._queue_ohlcv_write(bar)            # async batch → market_data_ohlcv

    htf_bars = self.bar_accumulator.update(bar)
    for htf_bar in htf_bars:
        self.bar_history.append(htf_bar)
        await self._publish_htf(htf_bar)    # → development.market.bars.htf

    if not self.bar_history.is_warm(bar.symbol, bar.tf, min_bars_for_tf(bar.tf)):
        return

    frames = self._build_frames(bar)        # DataFrame conversion here, not in core
    event = self._run_tiers(bar, frames)
    await self._publish_intelligence(event) # → development.intelligence
```

### OHLCV Ground Truth — Unified

FeaturePipelineService is the only live writer to `market_data_ohlcv`. Same batch pattern as FeatureWriterService (buffer 50 / flush every 5s). `ON CONFLICT DO NOTHING`.

**Only 1m bars written.** Existing TimescaleDB continuous aggregate views (`ohlcv_15m`, `ohlcv_1h`, `ohlcv_4h`, `ohlcv_1d`) derive HTF data automatically. Writing pre-aggregated HTF bars would interfere with the views.

Result: `market_data_ohlcv` is the single queryable OHLCV ground truth for both historical backfill and live data. No schema changes required.

### Correctness Invariants (must not be lost from market_analysis_service)

**1. `_prev_i1_features` for I2 crossover detection:**
```python
frames["prev_features"] = self._prev_i1_features.get(f"{bar.symbol}:{bar.tf}", {})
# run I1
self._prev_i1_features[f"{bar.symbol}:{bar.tf}"] = i1_result
```

**2. `smc_trend_direction` rename before frame merge:**
```python
smc_result["smc_trend_direction"] = smc_result.pop("trend_direction", None)
```
Without this, SMC overwrites I3Structure's `trend_direction` and corrupts I4–I6.

**3. CPU-bound plugins via `asyncio.to_thread` with per-(plugin, symbol, tf) locks.**

### Key Metrics
```
feature_pipeline_bars_processed_total{symbol, tf}
feature_pipeline_latency_ms             # bar_close_ts → intelligence publish
feature_pipeline_warmup_skips_total
feature_pipeline_ohlcv_writes_total
feature_pipeline_htf_bars_total{tf}
```
Target: **pipeline_latency_ms < 50ms p99**

### Futures Roll Handling
1. `bar_history.migrate_symbol(old, new)`
2. Adjust price-sensitive I1 plugin state by `roll_gap` (Bollinger, Keltner, Donchian)
3. Structured log: old symbol, new symbol, roll gap, plugin count adjusted

---

## SignalGeneratorService — Decision Layer

**File:** `services/signal_generator_service.py` (refactored in place)
**Systemd:** `indicagent-signal-generator`
**Metrics port:** `:9112`

### Pipeline Stage Modules (`src/intelligence/pipeline/`)

Each module is a pure function: typed inputs → typed outputs. No Kafka, no DB, no service awareness. State is passed as arguments, not closed over.

> **Migration note:** These modules currently exist as service classes at `src/intelligence/stages/` (e.g., `QualityGateService` with Kafka consumer/producer wiring). Phase 44.2 renames the directory to `src/intelligence/pipeline/` and refactors each service class into a pure function. The old service files at `src/intelligence/stages/` are deleted once the pure-function equivalents are verified.

```
src/intelligence/pipeline/
    __init__.py
    quality_gate.py       apply_quality_gate(signals, thresholds) → list[Signal]
    regime_gate.py        apply_regime_gate(signals, regime_ctx)  → list[Signal]
    tod_adjuster.py       apply_tod_adjustment(signals, tod_table, hour_et) → list[Signal]
    calibrator.py         apply_calibration(signals, cal_model)   → list[Signal]
    ranker.py             rank_signals(signals, perf_weights)     → list[RankedSignal]
    winner_selector.py    select_winner(ranked)                   → RankedSignal | None
```

Function naming rationale: `apply_*` for transforms (consistent with `apply_exhaustion_boost`/`apply_exhaustion_guard`), `rank_signals`/`select_winner` for operations that compute a result.

### State Owned by Service

```python
self.bar_history = BarHistory(maxlen=200)    # seeded from IntelligenceEvent.bar
self._regime_cache: dict                     # keyed by (symbol, tf) — unchanged
self._cross_asset_cache: dict                # keyed by tf — unchanged
self._htf_intel_cache: dict                  # keyed by tf — unchanged

# Pipeline stage state — loaded at startup, refreshed by background tasks
self._calibration_model: dict    # refreshed every 15 min
self._tod_table: dict            # refreshed daily
self._perf_weights: dict         # refreshed every 15 min from setup_performance
```

State refresh is a background `asyncio` task. Hot path never queries DB.

### Audit Queue — Reliable Observability Without Blocking Hot Path

```python
# Bounded queue — hot path never blocks on Kafka publish
self._audit_queue: asyncio.Queue = asyncio.Queue(maxsize=1000)

async def _queue_stage_audits(self, payloads: list[dict]) -> None:
    for p in payloads:
        try:
            self._audit_queue.put_nowait(p)
        except asyncio.QueueFull:
            self._audit_drops_total.inc()    # observable, never silent

# Background drain task — publishes to pipeline.* topics
async def _drain_audit_queue(self) -> None:
    while not self.shutdown_requested:
        payload = await self._audit_queue.get()
        await self._producer.publish(payload["topic"], payload["data"])
```

### Per-Bar Execution

```python
async def _process_event(self, event: IntelligenceEvent) -> None:
    self.bar_history.append(event.bar)
    frames = self._build_frames(event)

    # I7 plugins
    raw_signals = self._run_i7_plugins(frames, event)

    # In-process pipeline — pure function calls
    quality_gated  = apply_quality_gate(raw_signals, self._thresholds)
    regime_gated   = apply_regime_gate(quality_gated, event.i3)
    tod_adjusted   = apply_tod_adjustment(regime_gated, self._tod_table, hour_et)
    calibrated     = apply_calibration(tod_adjusted, self._calibration_model)
    ranked         = rank_signals(calibrated, self._perf_weights)
    winner         = select_winner(ranked)

    # Observability — async, bounded queue, never blocks hot path
    # topic_quality_gated() / topic_regime_gated() etc. are existing stream_keys.py functions
    await self._queue_stage_audits([
        {"topic": topic_quality_gated(...),  "data": quality_gated},
        {"topic": topic_regime_gated(...),   "data": regime_gated},
        {"topic": topic_tod_adjusted(...),   "data": tod_adjusted},
        {"topic": topic_calibrated(...),     "data": calibrated},
        {"topic": topic_ranked(...),         "data": ranked},
        {"topic": topic_winner(...),         "data": winner},
    ])

    # Write winner to signal_ledger — defined failure mode
    ledger_written = False
    if winner and self._cooldown_clear(event.symbol, event.tf):
        try:
            await self._write_signal_ledger(event, winner)
            ledger_written = True
            self._update_cooldown(event.symbol, event.tf)
        except Exception as e:
            self.logger.error("signal_ledger_write_failed", error=str(e))
            self._ledger_write_failures_total.inc()
            # Pipeline continues — record still published
            # Phase 49 ML queries filter WHERE ledger_written = TRUE

    # Publish complete record — always, regardless of ledger outcome
    record = self._build_record(event, ranked, winner, ledger_written)
    await self._publish_record(record)           # → development.intelligence.record

    # Backward compat — ranked signals array for dashboard SSE
    # Intentional redundancy. Retire after dashboard rewired to intelligence.record.
    await self._publish_i7_scorecard(event, ranked)  # → development.intelligence.i7

    if winner:
        await self._publish_aggregated(event, winner)  # → development.signals.aggregated
```

### Key Metrics
```
signal_generator_events_processed_total{symbol, tf}
signal_generator_signals_fired_total{symbol, tf, plugin}
signal_generator_pipeline_stage_input_total{stage}
signal_generator_pipeline_stage_output_total{stage}
signal_generator_audit_queue_drops_total
signal_generator_ledger_write_failures_total
signal_generator_cooldown_suppressed_total
signal_generator_latency_ms
```

---

## FeatureWriterService — Simplified

**File:** `services/feature_writer_service.py` (simplified in place)
**Phase:** 44.3

**Before:** 3 topics, two-phase write, UPSERTs, partial rows, race conditions, ~180 lines of i7/i8 split logic.

**After:** 1 topic, single atomic INSERT, complete rows, always.

**DB migration required (Phase 44.3 scope):** New columns must be added to `intelligence_features` before the new INSERT runs:
```sql
ALTER TABLE intelligence_features
    ADD COLUMN IF NOT EXISTS winner_plugin text,
    ADD COLUMN IF NOT EXISTS winner_confidence double precision,
    ADD COLUMN IF NOT EXISTS winner_direction text,
    ADD COLUMN IF NOT EXISTS signals_evaluated integer,
    ADD COLUMN IF NOT EXISTS signals_after_quality integer,
    ADD COLUMN IF NOT EXISTS signals_after_regime integer,
    ADD COLUMN IF NOT EXISTS signals_after_tod integer,
    ADD COLUMN IF NOT EXISTS signals_after_calibration integer,
    ADD COLUMN IF NOT EXISTS ledger_written boolean,
    ADD COLUMN IF NOT EXISTS i7_computed_at timestamptz;
-- session_type and days_to_expiry already exist in intelligence_features schema
```
Migration file: `production/migrations/NNN_intelligence_features_record_columns.sql` (NNN = next sequence number).

```sql
INSERT INTO intelligence_features (
    ts, symbol, tf,
    bar, i1, i2, i3, i4, i5, smc, i6, i7,
    winner_plugin, winner_confidence, winner_direction,
    signals_evaluated, signals_after_quality, signals_after_regime,
    signals_after_tod, signals_after_calibration,
    ledger_written, pipeline_latency_ms,
    i7_computed_at, computed_at, session_type, days_to_expiry
)
VALUES (...)
ON CONFLICT (ts, symbol, tf) DO NOTHING
```

**Removed:** `_process_i7_message()`, `_process_i8_message()`, `_flush_i7_i8()`, `_UPSERT_I7_SQL`, `_UPSERT_I8_SQL`, `_i7_buffer`, `_i8_buffer`.

**i8 persistence moved to LLMWriterService.** LLMWriterService owns all LLM data and already writes `llm_calls`. Phase 44.3 adds: new `development.intelligence.i8` topic subscription, new consumer group, buffer, and `UPDATE intelligence_features SET i8 = $1 WHERE ts = $2 AND symbol = $3 AND tf = $4` UPSERT — everything LLM in one service. This is new work in LLMWriterService, not a minor wiring step.

---

## Migration Plan (Clean Cutover — Markets Down Window)

No parallel running. Stop old, start new, validate.

### Phase 44.1 — FeaturePipelineService
```bash
sudo systemctl stop indicagent-indicator indicagent-market-analysis indicagent-timeframes
sudo systemctl start indicagent-feature-pipeline
# Validate: development.intelligence flowing, pipeline_latency_ms metric visible,
#           development.market.bars.htf flowing
```

### Phase 44.2 — SignalGeneratorService Consolidation
```bash
sudo systemctl stop indicagent-quality-gate indicagent-regime-gate \
  indicagent-tod-adjuster indicagent-calibrator indicagent-ranker \
  indicagent-winner-selector
sudo systemctl restart indicagent-signal-generator
# Validate: development.intelligence.record flowing, pipeline.* topics populated,
#           signal_ledger receiving winners, ledger_write_failures_total = 0
```

### Phase 44.3 — Atomic Persistence + OHLCV Unification
```bash
sudo systemctl restart indicagent-feature-writer indicagent-llm-writer
# Validate: intelligence_features rows complete (i7 not null on arrival),
#           ledger_written=TRUE on winner rows,
#           market_data_ohlcv receiving live 1m bars
```

---

## Naming Conventions

All names verified against CLAUDE.md standards:

| Element | Name | Standard |
|---------|------|----------|
| Service files | `feature_pipeline_service.py`, `signal_generator_service.py`, `feature_writer_service.py` | `snake_case_service.py` ✓ |
| Systemd units | `indicagent-feature-pipeline`, `indicagent-signal-generator`, `indicagent-feature-writer` | `indicagent-<name>` ✓ |
| Core classes | `BarHistory`, `BarAccumulator`, `BarMessage`, `SessionType` | `PascalCase` ✓ |
| Schema classes | `IntelligenceEvent`, `BarIntelligenceRecord`, `RankedSignal` | `PascalCase` ✓ |
| Pipeline modules | `quality_gate.py`, `regime_gate.py`, `tod_adjuster.py`, `calibrator.py`, `ranker.py`, `winner_selector.py` | `snake_case.py` ✓ |
| Pipeline functions | `apply_quality_gate()`, `apply_regime_gate()`, `apply_tod_adjustment()`, `apply_calibration()`, `rank_signals()`, `select_winner()` | `verb_noun()`, consistent with `apply_exhaustion_*` ✓ |
| Stream key fn | `topic_intelligence_record()` | `topic_<thing>()` ✓ |
| Topic | `development.intelligence.record` | dots, mirrors `.i7`/`.i8` ✓ |
| Constants | `_CONCURRENCY_LIMIT: int` | `UPPER_SNAKE_CASE` ✓ |
| Metrics | `feature_pipeline_*`, `signal_generator_*` | `<service>_<metric>_<suffix>` ✓ |

---

## Testing Strategy

### Unit Tests
- `tests/unit/core/test_bar_history.py` — append, maxlen, `get_arrays()`, `is_warm()`, seed, `migrate_symbol()`
- `tests/unit/core/test_bar_accumulator.py` — 5m/15m/1h boundaries, session break close, gap handling, `current_partial()`
- `tests/unit/intelligence/pipeline/test_quality_gate.py` — each stage module independently
- (same pattern for all 6 stage modules)
- `tests/unit/test_feature_pipeline_service.py`
- `tests/unit/test_feature_writer_service.py` — simplified single-buffer logic

### Integration Tests
- 200 BarMessages → assert `BarIntelligenceRecord` has all tiers populated, `pipeline_latency_ms > 0`
- Startup seed: load BarHistory from DB fixtures → first bar → I6 has HTF context
- Gap detection: feed bars with gap → `gap_preceding=True` on subsequent bar
- Roll event: inject roll → `migrate_symbol()` called, I1 state adjusted
- `ledger_written=False` path: mock DB failure → record still published, metric incremented
- Audit queue full: overflow 1000 events → `audit_drops_total` incremented, hot path not blocked

### Regression
- Run old pipeline and FeaturePipelineService against identical 200-bar fixture
- Assert I1 indicator values numerically identical
- Assert I6 CTF scores within tolerance (HTF from in-process vs DB views may differ at window edges — document delta, accept)

---

## Success Criteria

- `development.intelligence` published for all active symbols on every bar
- `development.intelligence.record` published with complete rows (i7 not null, ledger_written flag set)
- `intelligence_features` rows always complete at insert time — no rows with i7=null from timing
- `pipeline_latency_ms < 50ms` at p99
- `market_data_ohlcv` receiving live 1m bars — single OHLCV ground truth
- `BarHistory` module has one implementation used by both FeaturePipelineService and SignalGeneratorService
- All retired systemd units absent from `systemctl list-units`
- All existing I1–I7 plugin unit tests pass unchanged
- `signal_generator_ledger_write_failures_total = 0` under normal operation
- `signal_generator_audit_queue_drops_total = 0` under normal load
- No `float(bar["open"])` string coercions in the codebase

---

## What Does Not Change

- TWS daemon bar polling logic
- Plugin system: TIER_I1…TIER_I7, plugin protocol, `registry.validate_tier()`
- All I1–I7 plugin implementations
- SignalLifecycleService, AINarrativeService, LLMWriterService (except i8 UPSERT addition), CrossAssetService, API
- `development.market.bars` topic name and Kafka key convention
- `development.intelligence` topic name (schema extended, not renamed)
- TimescaleDB schema — `intelligence_features`, `signal_ledger` unchanged (new columns added, no drops)
- Dashboard and SSE layer (development.intelligence.i7 still published for backward compat)

---

## Intentional Redundancy Note

`development.intelligence.i7` is published by SignalGeneratorService alongside `development.intelligence.record`. This is deliberate — dashboard SSE currently subscribes to `intelligence.i7` for the signal scorecard. The same data exists in `BarIntelligenceRecord.ranked_signals`.

**Todo:** Rewire dashboard SSE to consume `intelligence.record`, then retire `intelligence.i7` topic. Low priority — captured in `.planning/todos/pending/`. UX is not the product; the data is.

---

*Spec approved: 2026-03-21*
*Supersedes: 2026-03-21-feature-pipeline-renaissance-design.md*
