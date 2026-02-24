# Architecture Reference — IndicAgent Unified Intelligence Bus

> Source of truth for architectural decisions. The *why* behind the build sequence.
> Full design doc: `docs/plans/2026-02-22-unified-intelligence-data-bus-design.md`

---

## Core Architecture

```
IBKR TWS → Redis Streams (hot path) → Dashboard (SSE, real-time)
                │                    → LLM agents (consumer group)
                │                    → Signal generator (consumer group)
                │
                ↓ feature_writer_service (async, decoupled)
          TimescaleDB intelligence_features hypertable
                │
                ↓ REST API (/api/features, /api/signals)
          Vercel frontend (via Cloudflare Tunnel → HTTPS)
```

**Stack choice rationale:** Redis + TimescaleDB was chosen over NATS/Kafka — no new infrastructure, hot path unchanged, external consumers use REST not Redis. Right-sized for current scale (23 contracts × 4 TFs).

---

## Key Architectural Decisions

### 1. Single canonical pipeline service
`market_analysis_service.py` only. `intelligence_processor_service.py` was deleted (Phase 1).

**Why:** The old service re-computed I1 internally — violating separation of concerns since `indicator_service.py` already owns I1. Canonical service consumes pre-computed `indicators:SYMBOL:TF` stream.

### 2. IntelligenceEvent — versioned, tiered JSONB schema
```python
class IntelligenceEvent(BaseModel):
    schema_version: Literal["1.0"] = "1.0"
    ts: datetime; symbol: str; tf: str
    bar: OHLCVBar
    i1: dict[str, float]   # 23 indicator outputs
    i3: dict[str, Any]     # structure: swing, S/R, trend
    i4: dict[str, float]   # context: regimes, GARCH (4 fields), Kalman (7 fields)
    i5: dict[str, Any]     # patterns: divergence, squeeze, confluence
    smc: dict[str, Any]    # smart money: BOS, FVG, order blocks, liquidity
    i6: dict[str, float]   # confluence: CTF scores
    source: Literal["live", "backfill"] = "live"
```

**Why tiered sub-dicts vs flat:** Surgical queries (`SELECT i4->>'garch_sigma'`), smaller GIN indexes per tier, cleaner schema evolution per tier, better TimescaleDB compression.

**Why i7 is NOT in this event:** Signal generation is downstream (signal_generator_service), separate domain.

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

### 6. Plugin state persistence protocol
Every stateful plugin implements `get_state() / restore_state()`. State stored in Redis hash:
```
plugin_state:{symbol}:{tf}:{plugin_name}  →  JSON blob  (TTL: 7 days)
```
Checkpointed every 60 bars. Loaded on startup, flushed on SIGTERM. Eliminates warm-up degradation on restart.

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

### 8. Auth — JWT + API key, single Depends
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

### 9. External access — Cloudflare Tunnel
Vercel requires HTTPS. Cloudflare Tunnel = free, no ports exposed, permanent subdomain, zero config.
```bash
cloudflared tunnel create indicagent
cloudflared tunnel route dns indicagent api.yourdomain.com
# systemd service: cloudflared.service
```

### 10. ML export — TimescaleDB + Parquet endpoint (no Feast/Hopsworks)
```
GET /api/features/export?symbol=ESH6&tf=5m&from=...&tiers=i1,i4,smc&format=parquet
```
Queries `intelligence_features`, flattens JSONB with `jsonb_to_record`, returns Parquet via pyarrow. `pd.read_parquet(url)` for ML training. Right-sized for current scale.

### 11. GARCH + Kalman — wired to I7, valuable for ML
Both compute on every bar, output to `intelligence:` stream. Use cases:
- **trad_MeanReversion**: gate on `kalman_price_position` (> 1.0 std dev)
- **trad_VWAPDeviation**: `garch_sigma` as dynamic spread threshold
- **trad_SqueezeExpansion**: `garch_vol_regime` check (avoid explosive vol)
- **LLM narrative agent**: full I4 context block

### 12. Historical backfill — replay fidelity tradeoff
Stage 2 replay writes `source='backfill'`. First ~50 bars have degraded quality (Kalman/GARCH warm-up). Accepted — complexity of saving warm-up state not worth it. Document the warm-up requirement clearly.

---

## Stream Keys (canonical)
```
{env}:ticks:{symbol}:live          # raw IBKR ticks
{env}:market:{symbol}:{tf}         # OHLCV bars
{env}:indicators:{symbol}:{tf}     # I1 outputs
{env}:intelligence:{symbol}:{tf}   # I3-I6 IntelligenceEvent
{env}:signals:{symbol}:{tf}:aggregated  # I7 signals
{env}:insight:{symbol}:{tf}        # I8 narratives (future)
```

---

## Key Files
| File | Role |
|------|------|
| `src/intelligence/schemas.py` | IntelligenceEvent Pydantic model (canonical) |
| `services/market_analysis_service.py` | I3-I6 pipeline + publisher |
| `services/feature_writer_service.py` | Redis → intelligence_features writer |
| `services/signal_generator_service.py` | I7 signals → signal_ledger |
| `src/core/stream_keys.py` | Stream name constants (always use helpers) |
| `src/api/routes/sse.py` | SSE endpoint → dashboard |
| `production/scripts/historical_backfill.py` | 365-day IBKR fetch + I1-I7 replay |
| `production/migrations/` | All DB migrations |
