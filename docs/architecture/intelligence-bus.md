# Architecture Reference — IndicAgent Unified Intelligence Bus

Last Updated: 2026-03-11

> Source of truth for architectural decisions. The *why* behind the build sequence.
> Full design doc: `docs/plans/2026-02-22-unified-intelligence-data-bus-design.md`

Status: I1-I8 complete — 98 plugins + 2 aggregation components, 1754 passing tests

---

## Core Architecture

```
IBKR TWS → Redpanda (hot path) → Dashboard (SSE, real-time)
                │              → LLM agents (consumer group)
                │              → Signal generator (consumer group)
                │
                ↓ feature_writer_service (async, decoupled)
          TimescaleDB intelligence_features hypertable
                │
                ↓ REST API (/api/features, /api/signals)
          Next.js dashboard (via localhost SSE + REST)
```

**Stack choice rationale:** Redpanda (Kafka-compatible) + TimescaleDB — Kafka-native streaming with consumer groups, hot path unchanged, external consumers use REST not Redpanda directly. Right-sized for current scale (60 active instruments × 5 TFs).

---

## Key Architectural Decisions

### 1. Single canonical pipeline service
`market_analysis_service.py` only. `intelligence_processor_service.py` was deleted (Phase 1). The `bar_aggregator_service` was also removed — timeframe aggregation is now embedded in the DataProviderAgent.

**Why:** The old service re-computed I1 internally — violating separation of concerns since `indicator_service.py` already owns I1. Canonical service consumes pre-computed `indicators:SYMBOL:TF` stream.

### 2. IntelligenceEvent — versioned, tiered JSONB schema
```python
class IntelligenceEvent(BaseModel):
    schema_version: Literal["1.0"] = "1.0"
    ts: datetime; symbol: str; tf: str
    bar: OHLCVBar
    i1: dict[str, float]   # indicator outputs (25 I1 raw + 11 I2 composite plugins)
    i3: dict[str, Any]     # structure: swing, S/R, trend
    i4: dict[str, float]   # context: regimes, GARCH (4 fields), Kalman (7 fields)
    i5: dict[str, Any]     # patterns: divergence, squeeze, confluence
    smc: dict[str, Any]    # smart money: BOS, FVG, order blocks, liquidity
    i6: dict[str, float]   # confluence: CTF scores
    source: Literal["live", "backfill"] = "live"
```

**Why tiered sub-dicts vs flat:** Surgical queries (`SELECT i4->>'garch_sigma'`), smaller GIN indexes per tier, cleaner schema evolution per tier, better TimescaleDB compression.

**Why i7 is NOT in this event:** Signal generation is downstream (signal_generator_service), separate domain. I8 narratives are in a separate `narratives:SYMBOL:TF` stream.

### 3. intelligence_features hypertable — no retention policy
```sql
-- Tiered JSONB columns: bar, i1, i3, i4, i5, smc, i6
-- Compression after 7 days (10-20x ratio; ~40GB → ~2-4GB for 3yr)
-- NO retention policy — seasonal analysis requires multi-year data
-- GIN indexes on i4 (GARCH/Kalman) and smc (smart money)
```

**Why no retention:** 400M rows/3yr is fine with compression. Seasonal patterns require years of history.

### 4. feature_writer_service — standalone async service
`services/feature_writer_service.py` — consumer group `feature_writer:persist`

**Why separate service:** Async decoupling — can lag, batch writes, retry on DB failure without touching the hot path latency. 100ms batch window or 50 events.

**Why NOT separate:** Query API (just add endpoints to FastAPI — same process, no network hop), auth middleware (FastAPI Depends), signal tracker (already separate — correct).

### 5. signal_ledger enhancement — feature reference columns
```sql
-- Added: feature_ts TIMESTAMPTZ, feature_tf TEXT
-- Dropped: regime_context TEXT (was stringified summary, now superseded)
-- ML training JOIN:
SELECT sl.*, f.i4, f.smc, f.i6
FROM signal_ledger sl
JOIN intelligence_features f ON f.symbol = sl.symbol
  AND f.ts = sl.feature_ts AND f.tf = sl.feature_tf
```

### 6. Plugin state — in-memory per-service
Stateful plugins are managed via in-memory dicts in each service (not Redis-backed):
- `_plugin_cache` — plugin singletons built at service init, reused per bar
- `_plugin_states` — `dict[tuple[str,str,str], dict]` keyed by `(plugin_name, symbol, timeframe)`; state is swapped onto `p._state` before `compute_full()` and written back after
- `_plugin_call_counts` — Prometheus metrics sampling (every PLUGIN_METRICS_SAMPLE_RATE=10 calls)

The `PluginStateManager` (Redis-backed) in `src/core/plugin_state_manager.py` exists but is not used in the hot path. Plugin state resets on service restart (warm-up period of ~50 1m bars for I1 incremental state).

### 7. Consumer group naming convention
```
{service_short_name}:{purpose}          # internal
ext:{app_name}:{purpose}               # external

feature_writer:persist    → feature_writer_service
signal_gen:i7             → signal_generator_service
narrative_agent:i8        → ai_narrative_service
ext:vercel_dashboard:realtime
ext:ml_trainer:batch
```

### 8. Auth — JWT + API key, single Depends (designed, not yet implemented)
```python
async def verify_auth(
    authorization: str | None = Header(None),
    x_api_key: str | None = Header(None),
) -> AuthContext:
    if x_api_key: return verify_api_key(x_api_key)    # machine consumers
    if authorization: return verify_jwt(authorization) # human users
    raise HTTPException(401)
```
Storage: `api_keys` table in PostgreSQL (hashed, with metadata).

### 9. ML export — TimescaleDB + Parquet endpoint (designed, not yet built)
```
GET /api/features/export?symbol=ESH6&tf=5m&from=...&tiers=i1,i4,smc&format=parquet
```
Queries `intelligence_features`, flattens JSONB with `jsonb_to_record`, returns Parquet via pyarrow. `pd.read_parquet(url)` for ML training. Right-sized for current scale.

### 10. GARCH + Kalman — wired to I7, valuable for ML
Both compute on every bar, output to `intelligence:` stream. Use cases:
- **trad_MeanReversion**: gate on `kalman_price_position` (> 1.0 std dev)
- **trad_VWAPDeviation**: `garch_sigma` as dynamic spread threshold
- **trad_SqueezeExpansion**: `garch_vol_regime` check (avoid explosive vol)
- **LLM narrative agent**: full I4 context block — Ollama (qwen3.5:9b per-signal, phi4-mini:3.8b group synthesis) — local Docker, no external API dependency

### 11. Historical backfill — replay fidelity tradeoff
Stage 2 replay writes `source='backfill'`. First ~50 bars have degraded quality (Kalman/GARCH warm-up). Accepted — complexity of saving warm-up state not worth it. Document the warm-up requirement clearly.

### 12. LLM audit trail — llm_calls hypertable + llm_writer_service

Every LLM call from `ai_narrative_service` is published to `llm_calls:stream` (maxlen=500) with full request/response context. `llm_writer_service` consumes this stream and writes to the `llm_calls` hypertable (keep forever — each call is a labeled training sample once outcome is known).

Signal lifecycle exits are published to `llm_outcomes:stream` (maxlen=200) by `signal_tracker_agent`. `llm_writer_service` back-fills realized outcome (pnl_r, mae, mfe) onto historical `llm_calls` records.

`llm_model_scores` table tracks per-model performance (win_rate, avg_pnl_r, p-value), refreshed every 15 minutes. This drives model selection for future calls.

**Why:** Renaissance principle — every LLM call is a labeled training sample. Once gone, the outcome cannot be recovered. Keep everything.

### 13. Signal lifecycle — zone-aware, 8-class outcome

`signal_tracker_agent` replaced `signal_tracker_service`. Key differences:
- Zone bounds: `zone_low/zone_high` from TradeFrame — price must enter the zone to activate
- MAE/MFE: tracked in-memory per signal_id (`_mae`, `_mfe` dicts); written to `signal_ledger` on exit
- `_activated_at` dict tracks activation time for `bars_in_trade` computation
- 8-class outcome: `never_activated`, `stopped_at_entry`, `stopped_in_trade`, `target_1`, `target_1_2`, `target_full`, `ttl_expired_ahead`, `ttl_expired_behind`

**Why:** A 3-state model (pending→active→exit) loses signal quality information. 8 classes enable regime-conditional performance analysis and ML feature engineering.

---

## Stream Keys (canonical)
```
{env}:ticks:{symbol}:live          # raw IBKR ticks
{env}:market:{symbol}:{tf}         # OHLCV bars
{env}:indicators:{symbol}:{tf}     # I1 outputs
{env}:intelligence:{symbol}:{tf}   # I3-I6 IntelligenceEvent
{env}:signals:{symbol}:{tf}:aggregated  # I7 signals
{env}:narratives:{symbol}:{tf}     # I8 AI narratives
{env}:llm_calls:stream             # LLM call audit log (maxlen=500)
{env}:llm_outcomes:stream          # Signal lifecycle exits (maxlen=200)
```

---

## Key Files
| File | Role |
|------|------|
| `src/intelligence/schemas.py` | IntelligenceEvent Pydantic model (canonical) |
| `services/market_analysis_service.py` | I3-I6 pipeline + publisher |
| `services/feature_writer_service.py` | intelligence:SYMBOL:TF → intelligence_features (async persistence) |
| `services/signal_generator_service.py` | I7 signals → signal_ledger |
| `services/signal_tracker_agent.py` | Zone-aware signal lifecycle (replaces signal_tracker_service) |
| `services/llm_writer_service.py` | LLM audit log → llm_calls hypertable + model scoring |
| `src/core/stream_keys.py` | Stream name constants (always use helpers) |
| `src/api/routes/sse.py` | SSE endpoint → dashboard |
| `production/scripts/historical_backfill.py` | 365-day IBKR fetch + I1-I7 replay |
| `production/migrations/` | All DB migrations |
