> **HISTORICAL DOCUMENT** — `intelligence_processor_service.py` was deleted in Phase 1 (2026-02-23) as described in this document. The canonical service is now `market_analysis_service.py`.

# Design: Unified Intelligence Data Bus

**Session:** 2026-02-22
**Type:** Architecture design / brainstorm — reference document, not an implementation plan yet
**Status:** Draft — decisions TBD

---

## Background & Motivation

IndicAgent computes 50-60 intelligence features per bar per symbol per timeframe — I1 indicators, I4 context (GARCH, Kalman, regime), I5 patterns, SMC smart money, I6 confluence, and I7 signals. Right now:

- The **hot path** works: Redis Streams carry everything in real time
- The **cold path is incomplete**: most features are never persisted; only I7 signals reach the DB
- **Other consumers are blocked**: LLM agents, external apps, and replay scenarios have no clean access to the full feature set

The vision: a **unified intelligence data bus** where every feature computed by every plugin flows into a durable, queryable, shareable stream — accessible in real time *or* historically.

---

## Current State (Discovered 2026-02-22)

### What's working

| Layer | Output | Where |
|-------|--------|--------|
| Redis hot path | `intelligence:SYMBOL:TF` stream, 50-60 fields per bar, all tiers I3-I6 | Ephemeral, ~1000 message circular buffer |
| Signal ledger | Full I7 signal lifecycle (entry, stop, targets, PnL) | TimescaleDB `signal_ledger`, 365-day retention |
| OHLCV | Raw 1m bars | TimescaleDB `market_data_ohlcv`, 90-day retention |
| Technical indicators | I1 scalar outputs | TimescaleDB `technical_indicators`, 60-day retention |

### What's broken / missing

| Gap | Detail |
|-----|--------|
| **Features table never written** | `features` table exists in schema (migration 001) but zero INSERT calls anywhere in codebase — completely unused |
| **Intelligence table incomplete** | `intelligence` table IS written to (scalars only) but: no retention policy (unbounded growth risk), arrays and complex objects dropped at serialization, no structured schema |
| **I1 features ephemeral** | 23 indicator outputs (RSI, MACD, ATR, etc.) computed every bar but never persisted — only I7 signal snapshots capture a subset |
| **GARCH + Kalman orphaned in I7** | Both plugins run and publish to `intelligence:` stream — but zero I7 plugins consume their outputs. LLM agents will need them but no wiring exists yet |
| **No time-based Redis retention** | Streams are count-trimmed only (1000 msgs for intelligence); at 23 contracts × 4 timeframes that's ~12 bars of history per symbol/TF |
| **Replay loses state** | Stage 2 backfill recomputes I1-I7 from OHLCV, but Kalman/GARCH warm-up state is lost — first N bars of replay have degraded quality |
| **Scalar-only persistence** | `intelligence` table strips arrays; SMC zone geometry (FVG bounds, order block high/low), divergence arrays, target lists all lost |

### GARCH / Kalman — orphaned but valuable

These two compute on every bar and ARE published to `intelligence:` stream:
- **GARCH:** `garch_sigma`, `garch_vol_ratio`, `garch_vol_regime`, `garch_shock`
- **Kalman:** `kalman_trend`, `kalman_slope`, `kalman_price_position`, `kalman_uncertainty`, `kalman_upper`, `kalman_lower`, `kalman_gain`

No I7 plugin reads them. Use cases identified:
1. LLM agents — direct consumption for narrative context
2. ML scoring model (Phase 3) — rich features for signal quality prediction
3. VWAPDeviation / SqueezeExpansion — `garch_sigma` as dynamic vol gate
4. MeanReversion — `kalman_price_position` for entry quality filter

---

## The Vision: Unified Intelligence Data Bus

### Requirements (from session discussion)

1. **Real-time** — any consumer can tap the stream as bars arrive
2. **Historical** — query any symbol/timeframe/feature over any lookback period
3. **Shareable** — external apps and processes can subscribe or query
4. **Replayable** — replay historical feature data without re-running the pipeline
5. **LLM-ready** — structured enough for agent consumption (not flat string k/v)
6. **Professional/robust** — production grade, not duct tape

### Consumer types identified

| Consumer | Access pattern | Needs |
|----------|---------------|-------|
| Dashboard | Real-time SSE | Current bar, all fields |
| LLM narrative agent (I8) | Per-signal, current bar | GARCH, Kalman, regime context |
| ML scoring model (Phase 3) | Batch historical | All I1-I6 features, aligned timestamps |
| Signal lifecycle tracker | Per bar | I7 signals only (already working) |
| External apps / other processes | REST or stream subscription | Configurable field set |
| Historical analysis / backtesting | Query by time range | Full feature matrix |

---

## Architecture Options

### Option A — Extend current (Redis + TimescaleDB, minimal change)

**How:** Fix the `features` table to actually be populated. Add proper retention policy to `intelligence` table. Serialize full JSONB payloads (not scalar-only).

**Pros:** No new infrastructure. Already have Redis Streams + TimescaleDB. Fastest path.

**Cons:** Redis still ephemeral (count-based trim). No pub/sub fanout for external apps. JSONB queries at scale are slower than columnar. Schema is implicit (flat k/v dict).

**Verdict:** Good short-term fix. Not the end state.

---

### Option B — Redis Streams as the bus (lean on what we have)

**How:** Increase stream retention (time-based XADD or larger maxlen), expose streams directly to external consumers via Redis client. Add a TimescaleDB writer service that consumes the stream and persists.

**Pros:** Already publishing everything to `intelligence:` stream. Redis Streams have consumer groups — easy fanout. DragonflyDB supports same protocol.

**Cons:** Redis Streams are in-memory — data loss on restart. No native HTTP access for external non-Redis consumers. XADD with large maxlen = memory pressure. Schema is flat string k/v, not typed.

**Verdict:** Works well as hot bus. Needs persistence layer behind it.

---

### Option C — NATS JetStream

**How:** Replace or augment Redis Streams with NATS JetStream as the primary message bus. JetStream has built-in persistence (file-backed), replay, subject-based routing, push/pull consumers.

**Pros:** True durable message bus. File-backed (survives restart). Native replay. HTTP API available. Designed for microservices data sharing. Subjects map cleanly to `intelligence.SYMBOL.TF`.

**Cons:** New infrastructure dependency. Migration from Redis Streams is non-trivial. Adds operational complexity (NATS server + monitoring). Overkill if the app stays monolith-adjacent.

**Verdict:** Best architectural choice if external sharing / multi-process is a real requirement. More complex to set up.

---

### Option D — Kafka / Redpanda

**How:** Kafka as the canonical event log. All pipeline outputs written as typed events. Consumers can replay from any offset.

**Pros:** Industry standard for event streaming at scale. True append-only log (full replay). Schema registry for typed events. Ecosystem (Kafka Connect → TimescaleDB sink, etc.).

**Cons:** Heavy operational overhead. Overkill for current scale (23 contracts). Java ecosystem friction. Kafka Connect adds another service.

**Verdict:** Too heavy unless this becomes a multi-tenant or enterprise-scale platform.

---

### Option E — Hybrid: Redis hot + TimescaleDB feature store (RECOMMENDED)

**How:**
1. Redis Streams stays as the real-time hot bus (already working, keep it)
2. A **feature writer service** consumes `intelligence:` stream and writes to TimescaleDB `features` table with proper columnar schema (JSONB payload with indexed fields for common queries)
3. Add retention policies to all intelligence tables
4. Expose a **feature query API** (REST) for historical access
5. Structured **event schema** (replace flat string k/v with typed JSONB)
6. External apps access via: (a) Redis consumer group for real-time, or (b) REST API for historical

**Architecture:**
```
Pipeline ──→ intelligence: stream (Redis/Dragonfly) ──→ Dashboard (SSE, real-time)
                │                                    ──→ LLM agents (consumer group)
                │                                    ──→ External apps (consumer group)
                │
                ↓ (new: feature writer service)
          TimescaleDB features table
          (full JSONB payload, indexed, retention policy)
                │
                ↓ (new: query API)
          REST /api/features?symbol=ESH6&tf=5m&from=...&fields=garch_sigma,kalman_trend
          REST /api/intelligence?...  (historical analysis)
```

**Pros:**
- No new infrastructure (Redis + TimescaleDB already running)
- Hot path unchanged — no latency impact
- Cold path filled: features persisted for replay/ML training
- Clean separation of concerns
- REST API makes it accessible to any language/process
- Schema can evolve incrementally

**Cons:**
- Feature writer service adds a Redis consumer — need to ensure it keeps up
- JSONB queries need proper indexing for performance
- Schema design requires thought (flat JSONB? columnar? hybrid?)

---

## Schema Design Decisions

### Current `intelligence` stream format (problem)
```python
# Flat strings — loses types, arrays, nested objects
{"trend_regime": "0.72", "garch_sigma": "0.0043", "kalman_trend": "4521.5", ...}
```

### Proposed structured event schema
```json
{
  "ts": "2026-02-22T14:05:00Z",
  "symbol": "ESH6",
  "tf": "5m",
  "bar": {"o": 4521.0, "h": 4530.0, "l": 4515.0, "c": 4525.0, "v": 12400},
  "i1": {"rsi_14": 62.4, "macd_diff": 0.8, "atr_14": 8.2, "bb_width": 0.012, ...},
  "i4": {
    "trend_regime": 0.72, "trend_confidence": 0.85, "ma_alignment": 0.9,
    "vol_regime": 1.2, "vol_expansion": true,
    "momentum_bias": 0.6, "momentum_strength": 0.7,
    "garch_sigma": 0.0043, "garch_vol_regime": 1, "garch_shock": 0.8,
    "kalman_trend": 4521.5, "kalman_slope": 0.3, "kalman_price_position": 0.4
  },
  "i5": {"rsi_div": false, "bb_squeeze": true, "squeeze_duration": 8, ...},
  "smc": {"bos": true, "fvg_active": true, "fvg_high": 4528.0, "fvg_low": 4522.0, ...},
  "i6": {"ctf_score": 0.78, "ctf_aligned": true},
  "i7": {"setup": "trad_TrendFollowing", "direction": 1, "confidence": 0.82, "entry": 4525.0}
}
```

### TimescaleDB `features` table (proposed)
```sql
CREATE TABLE features (
  ts          TIMESTAMPTZ NOT NULL,
  symbol      TEXT NOT NULL,
  timeframe   TEXT NOT NULL,
  payload     JSONB NOT NULL,    -- full structured event above
  version     TEXT DEFAULT '1.0' -- schema version
);
SELECT create_hypertable('features', 'ts');
CREATE INDEX ON features (symbol, timeframe, ts DESC);
-- Retention: 90 days (match OHLCV)
SELECT add_retention_policy('features', INTERVAL '90 days');
```

---

## GARCH + Kalman Wiring (related, low-effort wins)

Even before the full data bus, these two plugins should be wired to existing I7 plugins:

| Plugin | Suggested addition | Rationale |
|--------|-------------------|-----------|
| `trad_MeanReversion` | Gate on `kalman_price_position` (must be > 1.0 std dev) | Higher quality entry filter |
| `trad_VWAPDeviation` | Use `garch_sigma` as dynamic spread threshold | Adapts to current vol regime |
| `trad_SqueezeExpansion` | Add `garch_vol_regime` check (must be non-extreme) | Avoid explosive vol breakouts |
| LLM narrative agent (I8) | Pass full I4 context block | Richer context for narratives |

---

## Open Questions — RESOLVED (2026-02-22)

1. **NATS vs Redis+TimescaleDB** → **Redis + TimescaleDB hybrid is the right call now.** Few internal consumers. Eventually a Vercel-hosted frontend will hit this server over HTTPS — that's REST, not Redis. No need for NATS overhead.

2. **Schema version** → **Formalize now.** `intelligence.v1` JSONB schema with versioning from day 1. Don't let the flat string k/v accumulate tech debt. Good engineering early matters.

3. **Feature writer service** → **Standalone microservice**, as long as it's decoupled from the hot path (async consumer). Microservices are fine when they don't add latency to time-sensitive processing. Feature writer is async — it can lag and catch up.

4. **Retention policy** → **Years, not 90 days.** Seasonal pattern analysis requires multi-year data. Need TimescaleDB compression to make this practical. Design for it from the start.

5. **Replay fidelity** → **Accept degraded quality for first ~50 bars.** Don't save warm-up state — the complexity isn't worth it. Document the warm-up requirement clearly.

6. **API access control** → **Design with auth from day 1.** JWT or API keys. Currently internal; eventual goal is an externally offered service. Right-sizing auth now avoids painful retrofitting.

7. **Wire GARCH/Kalman to I7** → **Yes, do it as a quick independent win.**

---

## Architectural Decisions (Finalized)

### 1. Service Consolidation — Deprecate `intelligence_processor_service.py`

**Decision:** `market_analysis_service.py` is the one canonical I3-I6 pipeline service.

**Rationale:** `intelligence_processor_service.py` is the older version — it reads raw `market:SYMBOL:TF` bars and recomputes I1 internally before running I3-I6. This violates separation of concerns: I1 is already computed by `indicator_service.py`. `market_analysis_service.py` correctly consumes the pre-computed `indicators:SYMBOL:TF` stream.

**Action:** Deprecate `intelligence_processor_service.py`. Audit any consumers that depend on it, migrate them to `market_analysis_service.py`.

---

### 2. Intelligence Event Schema — Versioned, Tiered JSONB

Replace the flat string k/v format with a proper Pydantic-validated, versioned schema. Tiers are separate sub-objects — not one giant flat dict.

```python
# src/intelligence/schemas.py (new canonical file)
class IntelligenceEvent(BaseModel):
    schema_version: Literal["1.0"] = "1.0"
    ts: datetime
    symbol: str
    tf: str
    bar: OHLCVBar                  # OHLCV that triggered this computation
    i1: dict[str, float]           # 23 I1 indicator outputs (echoed from indicators: stream)
    i3: dict[str, Any]             # structure: swing, support/resistance, trend
    i4: dict[str, float]           # context: regimes, GARCH (4), Kalman (7)
    i5: dict[str, Any]             # patterns: divergence flags, squeeze, confluence
    smc: dict[str, Any]            # smart money: BOS, FVG, order blocks, liquidity
    i6: dict[str, float]           # confluence: CTF scores
    source: Literal["live", "backfill"] = "live"
```

**Why tiered sub-dicts rather than all flat?**
- I7 (signals) is NOT in this event — that's the signal_generator_service's domain, downstream
- Tier separation makes queries surgical ("give me just i4 for GARCH analysis")
- Schema evolution per tier is cleaner — can add i4 fields without touching i3
- Compression in TimescaleDB is more efficient when similar data is co-located

The publisher (`market_analysis_service.py`) validates and serializes via Pydantic. SSE route and all consumers parse via the same model.

---

### 3. Plugin State Persistence — All Stateful Plugins

**Decision:** Every stateful plugin should persist and restore its state. No warm-up degradation.

Currently, only I1 indicators (via `IncrementalManager`) save state. I4 context plugins (GARCH, Kalman), I5 patterns (divergence lookback), and SMC (order blocks, FVGs persist until invalidated) all lose state on restart.

**Design — plugin state protocol:**
```python
# Add to PatternPlugin protocol (src/intelligence/plugins.py)
def get_state(self) -> dict:    # serialize internal state to JSON-safe dict
    ...
def restore_state(self, state: dict) -> None:   # restore from saved dict
    ...
```

**Storage:** Redis hash per plugin per symbol per timeframe:
```
plugin_state:{symbol}:{tf}:{plugin_name}  →  JSON blob
TTL: 7 days (survive weekends + brief outages)
```

**Lifecycle in `market_analysis_service.py`:**
- **On startup:** Load all plugin states from Redis before processing first bar
- **On SIGTERM:** Flush all plugin states to Redis before shutdown
- **Periodic checkpoint:** Every N bars (e.g., every 60 bars = 1 hour of 1m data), checkpoint state to Redis — protects against crash without graceful shutdown

This completely solves the warm-up problem and makes restarts transparent.

---

### 4. Feature Store — `intelligence_features` Hypertable

Replace the broken `features` + scalar-only `intelligence` tables with one well-designed hypertable:

```sql
CREATE TABLE intelligence_features (
    ts              TIMESTAMPTZ     NOT NULL,
    symbol          TEXT            NOT NULL,
    tf              TEXT            NOT NULL,
    schema_version  TEXT            NOT NULL DEFAULT '1.0',
    bar             JSONB,          -- OHLCV snapshot
    i1              JSONB,          -- indicator outputs
    i3              JSONB,          -- structure outputs
    i4              JSONB,          -- context outputs (GARCH, Kalman, regimes)
    i5              JSONB,          -- pattern outputs
    smc             JSONB,          -- smart money outputs
    i6              JSONB,          -- confluence outputs
    source          TEXT            DEFAULT 'live'
);

SELECT create_hypertable('intelligence_features', 'ts',
    chunk_time_interval => INTERVAL '1 week');

-- Indexes
CREATE UNIQUE INDEX ON intelligence_features (symbol, tf, ts DESC);
CREATE INDEX ON intelligence_features USING GIN (i4);   -- fast GARCH/Kalman queries
CREATE INDEX ON intelligence_features USING GIN (smc);  -- fast SMC queries

-- Compression (after 7 days — data is settled)
ALTER TABLE intelligence_features SET (
    timescaledb.compress,
    timescaledb.compress_segmentby = 'symbol, tf',
    timescaledb.compress_orderby = 'ts DESC'
);
SELECT add_compression_policy('intelligence_features', INTERVAL '7 days');

-- NO retention policy — data kept indefinitely for seasonal analysis
```

**Why tiered JSONB columns instead of one `payload JSONB`?**
- Query efficiency: `SELECT i4->>'garch_sigma' FROM intelligence_features` vs scanning one giant blob
- GIN indexes per tier are smaller and faster
- Compression by tier segments works better
- Easy to add future tiers (i8 narratives?) without schema migration

**Old tables:** `features` (unused) → drop. `intelligence` (scalar-only) → migrate content to `intelligence_features.i3`/`i4`/etc., then drop.

---

### 5. Signal Ledger Enhancement — Feature Reference

Drop the `regime_context TEXT` string. Add a typed reference to the feature row:

```sql
ALTER TABLE signal_ledger
    ADD COLUMN feature_ts TIMESTAMPTZ,
    ADD COLUMN feature_tf TEXT,
    DROP COLUMN regime_context;   -- was a stringified summary, now superseded

-- ML training query becomes trivial:
-- SELECT sl.*, f.i4, f.smc, f.i6
-- FROM signal_ledger sl
-- JOIN intelligence_features f
--   ON f.symbol = sl.symbol
--   AND f.ts = sl.feature_ts
--   AND f.tf = sl.feature_tf
-- WHERE sl.status = 'stopped_out' OR sl.status LIKE 'target_%'
```

This is the data model that makes ML training clean — every signal has the full feature context it was generated from, accessible via a join.

---

### 6. Consumer Group Naming Convention

Internal services:
```
{service_short_name}:{purpose}
```

| Consumer Group | Service | Stream consumed |
|----------------|---------|-----------------|
| `indicator_svc:compute` | indicator_service | `market:SYMBOL:TF` |
| `market_analysis:pipeline` | market_analysis_service | `indicators:SYMBOL:TF` |
| `feature_writer:persist` | feature_writer_service | `intelligence:SYMBOL:TF` |
| `signal_gen:i7` | signal_generator_service | `intelligence:SYMBOL:TF` |
| `narrative_agent:i8` | ai_narrative_service | `signals:SYMBOL:TF:aggregated` |
| `signal_tracker:lifecycle` | signal_tracker_service | `signals:SYMBOL:TF:aggregated` |

External consumers:
```
ext:{app_name}:{purpose}
```
e.g., `ext:vercel_dashboard:realtime`, `ext:ml_trainer:batch`

---

### 7. Feature Writer Service

Standalone service: `services/feature_writer_service.py`

**Role:** Async bridge from the hot path (Redis) to the cold path (TimescaleDB). Completely decoupled — can lag, batch writes, retry on DB failure, without touching the pipeline.

**Design:**
```
intelligence:SYMBOL:TF (Redis Stream)
    ↓ consumer group: feature_writer:persist
Feature Writer Service
    ↓ parse + validate IntelligenceEvent
    ↓ batch (100ms window or 50 events, whichever first)
    ↓ bulk INSERT via COPY or execute_batch
intelligence_features (TimescaleDB)
```

**Key behaviors:**
- Reads from ALL symbol/TF streams (wildcard consumer pattern)
- Batches writes to reduce DB round-trips (target: <100ms latency, not real-time)
- On startup, reads `XINFO GROUPS` to resume from last committed ID (no data loss)
- Metrics: `feature_writer_rows_written_total`, `feature_writer_lag_ms`, `feature_writer_errors_total`
- Systemd service: `indicagent-feature-writer`

---

### 8. Historical Backfill Expansion

Expand `historical_backfill.py` to:
1. Fetch 365 days of IBKR 1m data (increase `--days 365`, check IBKR limits per contract)
2. Stage 2 replay now writes to BOTH `signal_ledger` AND `intelligence_features`
3. Source field = `'backfill'` to distinguish from live data

**Note:** IBKR 1m historical data limit varies by contract type — equity futures typically allow 365 days. Verify per contract. The `IBKRFetcher` in `historical_backfill.py` handles the chunked fetch.

---

### 9. Auth Layer Design

FastAPI dependency injection — single `Depends(verify_auth)` that handles both:

```python
# src/api/auth.py
async def verify_auth(
    authorization: str | None = Header(None),
    x_api_key: str | None = Header(None),
) -> AuthContext:
    if x_api_key:
        return verify_api_key(x_api_key)    # machine consumers
    if authorization:
        return verify_jwt(authorization)     # human users (Vercel frontend)
    raise HTTPException(401)
```

Storage: `api_keys` table in PostgreSQL (hashed, with metadata: app_name, created_at, last_used, rate_limit_tier).

---

### 10. ML Export Pattern

No feature store (Feast/Hopsworks) needed at this scale. TimescaleDB + a Parquet export endpoint:

```
GET /api/features/export
    ?symbol=ESH6&tf=5m
    &from=2025-01-01&to=2026-01-01
    &tiers=i1,i4,smc          # optional: select tiers
    &format=parquet            # or csv
```

The endpoint queries `intelligence_features`, flattens JSONB with `jsonb_to_record`, returns Parquet via `pyarrow`. ML training code: `pd.read_parquet(url)`.

For multi-TF alignment, the API handles "latest bar at or before ts" via:
```sql
SELECT DISTINCT ON (symbol, tf)
    ts, symbol, tf, i4, smc
FROM intelligence_features
WHERE symbol = 'ESH6'
  AND ts <= $target_ts
ORDER BY symbol, tf, ts DESC
```

---

### 11. External Access — Cloudflare Tunnel

```bash
# Install cloudflared, configure once:
cloudflared tunnel create indicagent
cloudflared tunnel route dns indicagent api.yourdomain.com
cloudflared tunnel run indicagent
# Result: https://api.yourdomain.com → localhost:8000 (FastAPI)
# Vercel frontend calls https://api.yourdomain.com/api/...
```

Systemd service: `cloudflared.service` so it survives reboots.

---

## Engineering Advice & Architectural Notes

### On TimescaleDB for multi-year features — the math matters

At 23 contracts × 4 timeframes × ~390 1m bars/trading day × ~250 trading days/year:
- ~9,000 bars/day → ~2.25M bars/year
- At 60+ features per bar → ~135M feature-rows/year
- 3 years = ~400M rows — this is fine for TimescaleDB **with compression**

Key settings:
```sql
-- Compress by symbol/timeframe segment, order by time
ALTER TABLE features SET (
  timescaledb.compress,
  timescaledb.compress_segmentby = 'symbol, timeframe',
  timescaledb.compress_orderby = 'ts DESC'
);
SELECT add_compression_policy('features', INTERVAL '7 days');
-- Typical compression ratio for time-series: 10-20x
-- 400M rows uncompressed ~20-40GB → ~2-4GB compressed
```
**Do NOT add a retention policy to features** — let it grow for seasonal analysis.

---

### On the Vercel frontend — HTTPS is required

Vercel-hosted frontends will refuse to call HTTP endpoints. This means the local FastAPI server **must be accessible over HTTPS**. Options:

| Option | Complexity | Cost | Notes |
|--------|-----------|------|-------|
| **Cloudflare Tunnel** | Low | Free | Best choice — `cloudflared` daemon, no port forwarding, HTTPS automatic |
| ngrok | Low | Freemium | URL changes on restart unless paid |
| VPS reverse proxy | Medium | ~$5/mo | Nginx + Let's Encrypt on a VPS, proxy to home |
| Dynamic DNS + Let's Encrypt | Medium | Free | Requires open port, router config |

**Recommendation: Cloudflare Tunnel.** One daemon (`cloudflared`), permanent subdomain, HTTPS handled automatically, no ports exposed. Works perfectly for a home server serving a Vercel frontend.

---

### On microservices — the right boundary for this stack

Not everything should be a service. Here's the right split for this platform:

| Component | Should be separate service? | Reason |
|-----------|---------------------------|--------|
| **Feature Writer** | ✅ Yes | Async Redis consumer → DB writer; decoupled from hot path; can lag without impacting pipeline |
| **Historical query API** | ❌ No | Just add endpoints to existing FastAPI; same process, no network hop, simpler |
| **Auth middleware** | ❌ No | FastAPI middleware — not a service |
| **LLM agent (I8)** | Already separate (`ai_narrative_service.py`) | ✅ Correct |
| **Signal tracker** | Already separate | ✅ Correct |

The principle: separate service = justified when it has a **different scaling axis**, **different fault domain**, or **async decoupling** is valuable. Query API has none of these — it's just serving requests from the same DB.

---

### On schema design — Pydantic + JSONB is the right pattern

Define the event schema as a **Pydantic model** at publish time. This gives:
- Validation at the source (pipeline bugs caught early)
- Auto-generated JSON schema documentation
- Easy evolution (add fields, version the model)

```python
# src/intelligence/schemas.py (new file)
class IntelligenceEvent(BaseModel):
    schema_version: str = "1.0"
    ts: datetime
    symbol: str
    tf: str
    bar: OHLCVBar
    i1: dict[str, float]   # all 23 indicator outputs
    i4: I4Context          # typed sub-model
    i5: I5Patterns
    smc: SMCContext
    i6: I6Confluence
    i7: I7Signal | None
```

Store as JSONB in TimescaleDB — flexible for schema evolution, queryable with `->` operators, indexable with GIN.

---

### On auth — JWT with API key fallback

For a service you might offer externally, the right approach:
- **JWT** for human users (Vercel frontend login flow)
- **API keys** for machine consumers (other apps, scripts)
- FastAPI's `Depends()` makes this clean — one dependency injection handles both

Design the auth layer before you have external users, not after. FastAPI + python-jose + a simple `api_keys` table is ~100 lines.

---

### On event sourcing vs request/response — understand the tradeoff

What you're building is close to an **event-sourced** system:
- Every bar generates an event (the intelligence payload)
- Events are published to a stream (Redis)
- Consumers can replay from history (TimescaleDB)

This is a well-established pattern. The key principle: **the stream is the source of truth, the DB is a projection of the stream.** The feature writer service creates the DB projection. If the DB gets corrupted or schema changes, you replay the stream to rebuild it.

For now, the stream is ephemeral (Redis) and the DB is the durable source — that's fine because the pipeline can always re-derive features from OHLCV. But worth understanding the conceptual model.

---

## Recommended Build Sequence (when ready)

These are independent enough to be separate phases:

| Phase | What | Why first |
|-------|------|-----------|
| **0 (quick win)** | Wire GARCH/Kalman into I7 plugins | Small, independent, immediate value |
| **1** | Define `IntelligenceEvent` Pydantic schema + update publisher to emit structured JSONB | Foundation — everything downstream depends on the schema |
| **2** | Feature Writer Service — async Redis consumer → `features` hypertable with compression | Unlocks persistence; decoupled so low risk |
| **3** | Historical query API endpoints on existing FastAPI | Unlocks Vercel frontend + ML training data access |
| **4** | Auth layer (JWT + API keys) on FastAPI | Needed before any external exposure |
| **5** | Cloudflare Tunnel + Vercel frontend integration | External access |
| **6** | ML scoring model (Phase 3 on roadmap) | Now has feature data to train on |

---

## Reference: Key Files

| File | Role |
|------|------|
| `src/intelligence/context/garch_volatility.py` | GARCH plugin — outputs 4 fields |
| `src/intelligence/context/kalman_trend.py` | Kalman plugin — outputs 7 fields |
| `src/intelligence/register_plugins.py` | Plugin registration (all 53) |
| `services/market_analysis_service.py` | I3-I6 pipeline + intelligence stream publisher |
| `services/intelligence_processor_service.py` | Older pipeline (reads market: stream) |
| `src/core/redis_streams_manager.py` | Stream operations, maxlen config |
| `src/core/stream_keys.py` | Stream name constants |
| `src/api/routes/sse.py` | SSE endpoint — consumes intelligence: stream → dashboard |
| `production/schemas/create_schema.sql` | DB schema (features table defined but unused) |
| `production/migrations/` | All migrations including retention policies (007) |
| `production/scripts/historical_backfill.py` | Stage 2 replay (I1-I7 from OHLCV) |
| `docs/architecture/stream-schemas.md` | Stream schema docs (composite.v1 mentioned but not implemented) |
