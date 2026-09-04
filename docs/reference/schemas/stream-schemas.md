<!-- generated-by: gsd-doc-writer -->
# Intelligence Stream Schemas & Data Contracts

**Version:** 4.0
**Last Updated:** 2026-09-04
**Status:** current

This document defines IndicAgent's live Kafka/Redpanda data contracts, plus the archived v2.x schemas still present in code for historical traceability. Verified 2026-09-04 against `src/intelligence/schemas.py`, `src/core/stream_keys.py`, and the live TimescaleDB schema.

**v2.x/v3.0 split (read this before citing anything below as "live"):** Per root `CLAUDE.md`, the v2.x typed bus — `IntelligenceEvent` (tiered JSONB i1/i3/i4/i5/smc/i6), `SignalEvent`/I7 signals, and everything published to `intelligence.journal`/`intelligence.i7.signals` — is **archived, no live consumer as of 2026-07-02**. `intelligence-pipeline` and `feature-writer` services are `failed`/`inactive`; `intelligence_features` and `signal_events` are confirmed empty (0 rows, live-checked 2026-09-04). v3.0's live path is `FeatureVectorPipeline` (compute, in-process) → `FeatureVectorRecord` on `topic_feature_vectors` → `FeatureVectorWriter` → `feature_vectors` (106M+ rows) → `forward_return_writer`/`ic_engine`/`ensemble_trainer` → `AlphaPublisher` → `alpha.events` → `alpha_events` (70M+ rows, sole writer `AlphaPublisher`). If you are documenting or debugging something that touches Kafka today, it is almost certainly on the v3.0 path.

---

## Runtime stream names (code)

All topic names are built by `src/core/stream_keys.py` functions, never hardcoded — dot-separated, with an optional `INDICAGENT_ENV` prefix (`env_prefix(env_name)`, e.g. `dev.market.bars`). There are ~50 `topic_*` functions in that file; this doc covers the ones with active producers/consumers plus the archived ones referenced by name elsewhere in the codebase. Grep `src/core/stream_keys.py` directly for the full list, including DLQ topics (`topic_*_dlq`).

---

## Live v3.0 Schemas

### `FeatureVector` / `FeatureVectorRecord` — the ML training dataset

Defined in `src/intelligence/schemas.py`. `FeatureVector` is a **frozen dataclass** (not Pydantic — pure-function output, no I/O, immutable after construction; D-08), 298 orthogonal feature primitives computed per bar by `FeatureFactory`, grouped into: momentum (7), volume/flow (8), volatility (2), session-level (21), regime-level (10), oscillators (6), cross-asset (10), named interaction primitives (5), theory-motivated interactions (10), calendar (17), velocity primitives (4+6), recency/statistical atomics (11), cross-timeframe (3), statistical/liquidity (4), bar anatomy ratios (8), lagged return series (6), open/close split (4), temporal coordinates (10), volume structure (12), breakout distance (12), return distribution (7), plus additional groups — see the field-group docstring on `FeatureVector` in `schemas.py` for the maintained, binding field order (ends "Total: 298"). Most fields are non-optional `float`; the Phase 165 Swing/Fib/Trend/Session Structure block (41 fields) is `float | None` by design — `None` means "not measured," never a fake placeholder value (D-01).

`FeatureVectorRecord` is the Kafka wire envelope:
```python
class FeatureVectorRecord:
    symbol: str
    tf: str
    bar_ts: datetime          # UTC bar open timestamp
    pipeline_version: str     # e.g. "3.0.0"
    feature_factory_version: str
    regime: str | None        # HMM state label: "ranging" | "trending_up" | "trending_down"
    regime_label_source: str  # always "filtered" (D-07: forward Viterbi only, no lookahead)
    vector: FeatureVector
```

**Topic:** `topic_feature_vectors(env)` → `{env}.intelligence.feature_vectors`. **Published by** `IntelligencePipeline`/`FeatureVectorPipeline` after `FeatureFactory.compute()`. **Consumed by** `FeatureVectorWriter` (batch INSERT to `feature_vectors` hypertable; consumer group `feature_vector_writer_group`). **Status: Operational, live.**

### `alpha_events` — alpha emission events

No dedicated Pydantic/dataclass schema — the Kafka payload mirrors the `alpha_events` DB row exactly (`services/alpha_publisher.py`'s `_INSERT_SQL` columns, live-verified against `\d alpha_events`):

```python
{
    "event_id": str,
    "symbol": str,
    "tf": str,
    "bar_ts": str,                # ISO-8601 UTC
    "ensemble_version": str,
    "weight_version": str,
    "regime": str | None,
    "alpha_score": float,
    "alpha_ci_lower": float | None,
    "alpha_ci_upper": float | None,
    "effective_n": float | None,
    "n_features_active": int | None,
    "emission_threshold": float,
    "direction": str,             # "long" | "short" (DB CHECK constraint)
    "top_features": dict,         # JSONB — the only live JSONB payload field of note
    "emitted_at": str,            # ISO-8601 UTC, DB default now()
    "cost_hurdle": float,         # DB default 0.0
    "is_shadow": bool,            # DB default true
}
```

**Topic:** `topic_alpha_events(env)` → `{env}.alpha.events`. **Published by** `AlphaPublisher` (`services/alpha_publisher.py`) when the ensemble alpha score crosses the per-TF emission threshold (`alpha.quant.threshold.{tf}` APR key, e.g. 1.5/1.2/1.0/0.8 for 5m/15m/1h/1d) and the `effective_N` gate is met (`alpha.ensemble.effective_n_gate`). `AlphaPublisher` writes the DB row first (`INSERT ... ON CONFLICT (event_id, bar_ts) DO NOTHING`), then publishes the same shape to Kafka. **`alpha_publisher` is the sole writer of `alpha_events`** (DAG Invariant, root `CLAUDE.md`). **Status: Operational, live** (Kafka publish is best-effort alongside the authoritative DB write — the row lands in `alpha_events` regardless of whether the Kafka publish succeeds).

### `narrative.v1` — I8 AI signal narrative

```python
{
    "symbol": str,          # Trading symbol (e.g., "ESH6")
    "timeframe": str,       # Timeframe (5m, 15m)
    "timestamp": str,       # UTC ISO-8601 timestamp
    "narrative": str,       # 2-3 sentence human-readable trade narrative
    "action_bias": str,     # "bullish" | "bearish"
    "confidence": str,      # Signal confidence as string float (e.g., "0.74")
    "model": str,           # LLM model used
    "latency_ms": str,      # Ollama call latency as string int
}
```

**Topic:** `topic_narratives(env)` → `{env}.narratives`; group synthesis on `topic_narratives_group(env)` → `{env}.narratives.group`. **Published by** `AINarrativeService`/`NarrativeSynthesizer` only when `selected_signal is not None` and `direction != 0`. **Status: code is current, but the producer is dormant** — per root `CLAUDE.md`, `indicagent-narrative-compute` is `disabled`/`inactive` and `BaseAIWorker`/its swarm consumers have had zero commits since the v3.0 rebuild started 2026-06-20. This is I8's target-state schema, not confirmed-running — check `systemctl status indicagent-narrative-compute` before assuming it fires.

---

## Archived v2.x Schemas (no live consumer since 2026-07-02)

These remain defined in `src/intelligence/schemas.py` and are wired into `sse.py`'s topic list (see [SSE Protocol](../api/sse-protocol.md)), but their producing service (`indicagent-intelligence-pipeline`) is `failed` with an `ExecStart` pointing at a deleted file, and their target tables (`intelligence_features`, `signal_events`) are confirmed at 0 rows. Kept here for historical/debugging traceability only — do not build new work against them.

### `IntelligenceEvent`

```python
class IntelligenceEvent(BaseModel):
    ts: datetime
    symbol: str
    tf: str
    bar: OHLCVBar
    i1: dict[str, float]   # I1 Technical indicators (29 plugins)
    i3: dict[str, Any]     # I3 Market structure (9 plugins)
    i4: dict[str, float]   # I4 Context/regime (13 plugins)
    i5: dict[str, Any]     # I5 Patterns (16 plugins)
    smc: dict[str, Any]    # Smart Money Concepts (16 plugins)
    i6: dict[str, float]   # I6 Confluence scoring (7 plugins)
    bar_close_ts: datetime | None
    i1_computed_at: datetime | None
    computed_at: datetime
```
**Topic:** `topic_intelligence_journal(env)` → `{env}.intelligence.journal` (as `BarIntelligenceRecord`, the atomic wire form). **Target table:** `intelligence_features` — 0 rows.

### `SignalEvent` / `RankedSignal` (I7)

```python
class SignalEvent(BaseModel):
    ts: datetime
    symbol: str
    tf: str
    direction: str  # "long" | "short"
    entry_low: float
    entry_high: float
    stop_loss: float
    target_1: float
    target_2: float
    target_full: float
    ttl_bars: int
    confidence: float
    cis_score: float
    calibrated_confidence: float
    is_winner: bool
    source: str
```
**Topic:** `topic_intelligence_i7_signals(env)` → `{env}.intelligence.i7.signals`. **Consumed by** `SignalWriter` for `signal_ledger` persistence — but `signal_ledger` is a view over `signal_events`/`trade_frames`/`trade_executions`, all confirmed at 0 rows (see `docs/reference/db-maintenance.md`).

---

## Not Implemented (schema defined, never wired to a live stream)

The following `*.v1` schemas (`composite.v1`, `pattern.v1`, `regime.v1`, `insight.v1`, `features.v1`, `bar.v1`) described in earlier revisions of this document as `env:type:SYMBOL:TIMEFRAME`-style colon-delimited streams do not correspond to any function in the live `src/core/stream_keys.py` (which builds dot-separated names, per DAG Invariant 4) and have no producer or consumer in the current codebase. They described an intended-but-never-built intermediate stream layer from an earlier design iteration. Treat any doc or code comment citing a colon-delimited stream pattern (`prod:bar:ES:1m`, `env:composite:SYMBOL:TIMEFRAME`, etc.) as stale — the actual topic-naming convention, live since the v2.x rebuild, is dot-separated via `stream_keys.py` only.

---

## Related Documentation

- [SSE Protocol](../api/sse-protocol.md) — how these topics reach the dashboard over Server-Sent Events
- [DB Maintenance](../db-maintenance.md) — live row counts / archived-table status for the tables these topics feed
- Root `CLAUDE.md` — Architecture section, v2.x/v3.0 pipeline diagrams, DAG Invariants
