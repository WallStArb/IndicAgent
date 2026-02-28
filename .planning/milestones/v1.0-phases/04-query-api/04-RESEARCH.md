# Phase 4: Query API - Research

**Researched:** 2026-02-24
**Domain:** FastAPI route implementation — TimescaleDB queries, Parquet export, SSE payload upgrade
**Confidence:** HIGH

## Summary

Phase 4 adds three new capabilities to the existing FastAPI application: (1) a paginated query endpoint for `intelligence_features`, (2) an enhanced signal history endpoint with optional JOIN to feature context, and (3) a Parquet export endpoint. It also upgrades the existing SSE `intelligence_data` event to ensure the payload is well-formed for typed consumption. The foundation is solid — FastAPI 0.129.1, asyncpg 0.31.0, and pandas 3.0.1 are all in the `.venv`. pyarrow 23.0.1 must be added to `requirements.txt` (it is pip-installable and confirmed available in the pip index).

The good news on SSE: the dashboard `parseIntelligence()` in `use-market-stream.ts` already reads `payload.event` and parses the nested `IntelligenceEvent` JSON — the stream publisher already sets `{"event": "<IntelligenceEvent JSON>"}` on the Redis stream. The SSE route passes the raw `fields` dict through as `payload`. No change is needed to `sse.py` or the dashboard for typed IntelligenceEvent support — the upgrade is already done. The only SSE work is confirming this is correct and writing a test that verifies it.

The signal history route requires a new `src/api/routes/signals.py` file and a new `src/api/routes/features.py` file. Both follow the existing pattern: `APIRouter`, `Depends(get_db_manager)`, asyncpg `.fetch()` via `db_manager.fetch()`, structlog error logging, `HTTPException` on failure. The `intelligence_features` table has a composite primary key `(ts, symbol, tf)` and a btree index `(symbol, tf, ts DESC)` — date-range queries with pagination will use this index efficiently.

The Parquet export loads `intelligence_features` rows into a pandas DataFrame, expands JSONB tier columns (i1, i3, i4, i5, smc, i6) using `json.normalize` or manual column extraction, writes to a `BytesIO` buffer via `df.to_parquet(engine='pyarrow')`, and returns a `Response` with `media_type='application/octet-stream'`. This is an in-memory approach — acceptable for the expected data volumes (a year of data for a single symbol/timeframe is ~500k rows max, but realistically 1m bars for one symbol for 365 days is ~98,280 rows which is manageable in memory).

**Primary recommendation:** Two new route files (`features.py`, `signals.py`), pyarrow added to requirements.txt, both routers registered in `main.py`. SSE requires no code change — verify and test only.

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|-----------------|
| API-01 | `GET /api/features/{symbol}/{timeframe}` returns paginated `intelligence_features` with date range filter | New `features.py` route; asyncpg query on `intelligence_features` with `(symbol, tf, ts DESC)` index; cursor-based pagination via `before` timestamp param |
| API-02 | `GET /api/signals/{symbol}` returns signal history with optional JOIN to feature context | New `signals.py` route; `signal_ledger` LEFT JOIN `intelligence_features` ON `(symbol, feature_ts, feature_tf)` when `?include_features=true` |
| API-03 | SSE stream endpoint publishes typed IntelligenceEvent payloads — not flat string dicts | SSE already passes `{"event": "<IntelligenceEvent JSON>"}` through; dashboard `parseIntelligence()` already handles it; test coverage needed to lock behavior |
</phase_requirements>

## Standard Stack

### Core

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| FastAPI | 0.129.1 | Route handlers, request/response models, Depends injection | Already in codebase — all routes use this pattern |
| asyncpg | 0.31.0 | Async PostgreSQL queries via `db_manager.fetch()` | All existing DB routes use asyncpg via DatabaseManager |
| pyarrow | 23.0.1 | Parquet serialization backend for pandas `to_parquet()` | Only Parquet engine available; pandas 3.x requires pyarrow or fastparquet; pyarrow is the standard choice |
| pandas | 3.0.1 | DataFrame for JSONB column expansion + Parquet serialization | Already installed; used in indicators route |
| pydantic | v2 (in .venv) | Response model definition, IntelligenceEvent deserialization | All intelligence schemas are Pydantic v2 models |

### Supporting

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| structlog | (in .venv) | Structured error logging in route handlers | Every route handler uses this — follow existing pattern |
| fastapi.responses.Response | FastAPI built-in | Return raw bytes for Parquet export | Use instead of JSONResponse for binary content |
| io.BytesIO | stdlib | In-memory buffer for Parquet bytes | Avoids disk I/O for export endpoint |
| json | stdlib | Parse JSONB columns returned as strings by asyncpg | asyncpg returns JSONB columns as `str` — requires `json.loads()` before pandas |

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| pyarrow (Parquet engine) | fastparquet | fastparquet is not installed and is slower; pyarrow is the ecosystem standard |
| In-memory Parquet | Streaming Parquet via chunked generator | Streaming Parquet is complex to implement correctly; in-memory is fine for expected data volumes (<200k rows) |
| Cursor pagination (before=ts) | Offset pagination (page=N, per_page=N) | Cursor pagination is stable under concurrent writes to TimescaleDB; offset pagination drifts when new rows are inserted between pages |
| New route files | Adding to market_data.py | market_data.py already has 4 endpoints; separation keeps files focused and matches existing pattern (one domain per file) |

**Installation:**
```bash
# Add to requirements.txt then:
pip install pyarrow>=23.0.0
```

## Architecture Patterns

### Recommended Project Structure

```
src/api/routes/
├── health.py          # existing
├── indicators.py      # existing
├── instruments.py     # existing
├── market_data.py     # existing
├── sse.py             # existing — no change needed for API-03
├── features.py        # NEW — API-01: intelligence_features query + Parquet export
└── signals.py         # NEW — API-02: signal_ledger query with optional feature JOIN
```

Registration in `main.py`:
```python
from .routes import health, indicators, instruments, market_data, sse, features, signals

app.include_router(features.router, prefix="/api", tags=["features"])
app.include_router(signals.router, prefix="/api", tags=["signals"])
```

### Pattern 1: Paginated TimescaleDB query with cursor pagination

**What:** Query `intelligence_features` with date range and cursor-based pagination using the `(symbol, tf, ts DESC)` index.
**When to use:** API-01 — GET /api/features/{symbol}/{timeframe}

```python
# Source: codebase pattern from market_data.py + intelligence_features schema
@router.get("/features/{symbol}/{timeframe}")
async def get_features(
    symbol: str,
    timeframe: str,
    from_ts: datetime | None = Query(None, alias="from"),
    to_ts: datetime | None = Query(None, alias="to"),
    limit: int = Query(100, ge=1, le=1000),
    db_manager: DatabaseManager = Depends(get_db_manager),
) -> dict[str, Any]:
    query = """
        SELECT ts, symbol, tf, platform, source, schema_version,
               bar, i1, i3, i4, i5, smc, i6
        FROM intelligence_features
        WHERE symbol = $1 AND tf = $2
          AND ($3::timestamptz IS NULL OR ts >= $3)
          AND ($4::timestamptz IS NULL OR ts <= $4)
        ORDER BY ts DESC
        LIMIT $5
    """
    rows = await db_manager.fetch(query, symbol, timeframe, from_ts, to_ts, limit)
    # Each JSONB column is returned as str by asyncpg — parse with json.loads()
    return {"symbol": symbol, "timeframe": timeframe, "count": len(rows), "rows": [...]}
```

**Key detail:** asyncpg returns JSONB columns as Python `str`, not `dict`. Each of `bar`, `i1`, `i3`, `i4`, `i5`, `smc`, `i6` must be passed through `json.loads()` before returning as JSON.

### Pattern 2: Signal history with optional feature JOIN

**What:** Query `signal_ledger`, optionally LEFT JOIN to `intelligence_features` via `(symbol, feature_ts, feature_tf)`.
**When to use:** API-02 — GET /api/signals/{symbol}

```python
# Source: signal_ledger schema inspection
@router.get("/signals/{symbol}")
async def get_signals(
    symbol: str,
    include_features: bool = Query(False),
    limit: int = Query(100, ge=1, le=1000),
    db_manager: DatabaseManager = Depends(get_db_manager),
) -> dict[str, Any]:
    if include_features:
        query = """
            SELECT sl.signal_id, sl.timestamp, sl.symbol, sl.timeframe,
                   sl.setup_plugin, sl.signal_type, sl.direction,
                   sl.confidence, sl.status, sl.feature_ts, sl.feature_tf,
                   f.bar, f.i1, f.i3, f.i4, f.i5, f.smc, f.i6
            FROM signal_ledger sl
            LEFT JOIN intelligence_features f
              ON sl.symbol = f.symbol
             AND sl.feature_ts = f.ts
             AND sl.feature_tf = f.tf
            WHERE sl.symbol = $1
            ORDER BY sl.timestamp DESC
            LIMIT $2
        """
    else:
        query = """
            SELECT signal_id, timestamp, symbol, timeframe,
                   setup_plugin, signal_type, direction,
                   confidence, status, feature_ts, feature_tf
            FROM signal_ledger
            WHERE symbol = $1
            ORDER BY timestamp DESC
            LIMIT $2
        """
    rows = await db_manager.fetch(query, symbol, limit)
    ...
```

**Key detail:** `feature_ts` and `feature_tf` exist in `signal_ledger` but are NULL for pre-Phase 2 signals (existing data from before the backfill). The LEFT JOIN handles NULL gracefully.

### Pattern 3: Parquet export via in-memory BytesIO

**What:** Return `intelligence_features` rows as a Parquet file. Expand JSONB tier columns into flat columns for ML consumption.
**When to use:** API-01 extended — GET /api/features/export?format=parquet

```python
# Source: pandas 3.x + pyarrow docs
import io
import json
import pandas as pd
from fastapi import Response

@router.get("/features/export")
async def export_features(
    symbol: str = Query(...),
    timeframe: str = Query(...),
    format: str = Query("parquet"),
    db_manager: DatabaseManager = Depends(get_db_manager),
) -> Response:
    rows = await db_manager.fetch(query, symbol, timeframe)

    records = []
    for row in rows:
        record = {
            "ts": row["ts"], "symbol": row["symbol"], "tf": row["tf"],
            "source": row["source"],
        }
        # Expand each JSONB tier into flat columns with tier prefix
        for tier in ["bar", "i1", "i3", "i4", "i5", "smc", "i6"]:
            tier_data = json.loads(row[tier]) if isinstance(row[tier], str) else (row[tier] or {})
            for k, v in tier_data.items():
                record[f"{tier}_{k}"] = v
        records.append(record)

    df = pd.DataFrame(records)
    buf = io.BytesIO()
    df.to_parquet(buf, engine="pyarrow", index=False)
    buf.seek(0)

    return Response(
        content=buf.read(),
        media_type="application/octet-stream",
        headers={"Content-Disposition": f'attachment; filename="features_{symbol}_{timeframe}.parquet"'},
    )
```

### Pattern 4: SSE intelligence_data payload (already correct — verify only)

**What:** The SSE route passes raw Redis stream `fields` dict as `payload`. For the `intelligence:` stream, the field is `{"event": "<IntelligenceEvent JSON>"}`. The dashboard does `JSON.parse(payload.event)` to get the typed tiers.
**When to use:** API-03 — SSE verification

**Current flow (confirmed correct):**
1. `market_analysis_service.py` publishes: `redis.xadd(stream_key, {"event": event.model_dump_json()})`
2. `sse.py` XREADs and emits: `data: {"stream": "...", "id": "...", "payload": {"event": "<json>"}}`
3. Dashboard: `const { payload } = JSON.parse(evt.data); parseIntelligence(payload)` → `JSON.parse(payload.event)`

No code change needed. Test coverage is the only deliverable for API-03.

### Anti-Patterns to Avoid

- **Raw `fields` without json.loads() on JSONB:** asyncpg returns `Record` objects where JSONB columns are `str` (not `dict`). Returning them as-is produces double-encoded JSON in the response. Always `json.loads()` each JSONB column before building the response dict.
- **Offset pagination on TimescaleDB hypertables:** `OFFSET N` forces a sequential scan across N rows on each request. Use cursor pagination with `WHERE ts < $cursor_ts` instead.
- **Parquet with pandas without pyarrow installed:** `df.to_parquet()` requires either pyarrow or fastparquet. The endpoint will crash at runtime if pyarrow is not in requirements.txt. Add it explicitly.
- **Route ordering collision:** FastAPI matches routes in registration order. `/api/features/export` must be registered BEFORE `/api/features/{symbol}/{timeframe}` or FastAPI will try to match "export" as a `{symbol}` path parameter. Either register `export` first in the router or use a distinct path like `/api/features/export/parquet`.
- **Hardcoding symbol or contract code:** API callers may pass base symbols (ES) or contract codes (ESH6). Apply `_resolve_contract()` (or an equivalent lookup) when querying DB columns that store contract codes.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| JSONB column serialization | Custom JSONB parser | asyncpg + `json.loads()` | asyncpg handles PostgreSQL wire protocol; just call `json.loads()` on the string value |
| Parquet serialization | Custom binary writer | pandas `to_parquet(engine='pyarrow')` + `io.BytesIO` | pyarrow handles schema inference, compression, and nested type handling |
| Pagination cursor management | Custom token/offset scheme | `WHERE ts < $before_ts ORDER BY ts DESC LIMIT N` | Timestamp cursor is stable, index-friendly, and trivial to implement |
| Response content negotiation | Custom media type detection | FastAPI `Response(media_type=...)` | One line; FastAPI handles headers correctly |

**Key insight:** The complexity in this phase is entirely in the SQL and JSONB handling, not in FastAPI mechanics. The framework does its job cleanly — invest effort in correct query design and JSONB column expansion.

## Common Pitfalls

### Pitfall 1: asyncpg Record JSONB returned as str, not dict

**What goes wrong:** Developer writes `row["i4"]["garch_sigma"]` and gets `TypeError: string indices must be integers`.
**Why it happens:** asyncpg returns PostgreSQL JSONB columns as Python `str`, not `dict`. This is correct behavior — asyncpg avoids automatic deserialization cost.
**How to avoid:** For every JSONB column (`bar`, `i1`, `i3`, `i4`, `i5`, `smc`, `i6`): `tier_data = json.loads(row["i4"]) if row["i4"] else {}`.
**Warning signs:** `TypeError` on dict key access into a row field, or response JSON containing escaped strings within strings.

### Pitfall 2: Route ordering — /features/export matches before /{symbol}

**What goes wrong:** `GET /api/features/export?symbol=ES&timeframe=1m` triggers the `/{symbol}/{timeframe}` handler with `symbol="export"`, returning 404 or wrong data.
**Why it happens:** FastAPI matches path parameters greedily in registration order.
**How to avoid:** Register the `/features/export` route handler BEFORE `/{symbol}/{timeframe}` in the router, or use `/features/export/parquet` as the path to avoid the collision entirely.
**Warning signs:** Test that calls `/features/export` returns 422 (unexpected path param) instead of 200.

### Pitfall 3: pyarrow not in requirements.txt — crash at runtime

**What goes wrong:** The export endpoint works in dev (if pyarrow was installed manually) but crashes on a fresh deployment: `ImportError: Unable to find a usable engine`.
**Why it happens:** `pandas.to_parquet()` does not install its engine dependency; it just raises ImportError at call time.
**How to avoid:** Add `pyarrow>=23.0.0` to `requirements.txt` explicitly. Verify with `pip show pyarrow` after `pip install -r requirements.txt`.
**Warning signs:** The endpoint import succeeds but calling `df.to_parquet()` raises `ImportError`.

### Pitfall 4: NULL feature_ts in signal_ledger JOIN breaks include_features

**What goes wrong:** Signals generated before Phase 2 (or during the live pipeline before backfill) have `feature_ts = NULL` and `feature_tf = NULL`. The LEFT JOIN to `intelligence_features` returns NULL for all feature columns. If the response builder assumes non-null feature data, it will crash.
**Why it happens:** `feature_ts` was added in Phase 2 but only populated by the Phase 2+ signal generator and backfill. Historical signals (pre-Phase 2) have NULL.
**How to avoid:** Build the response dict with `if row["i4"] is not None else None` for all feature columns. The response should include `"features": null` when no matching row exists.
**Warning signs:** KeyError or AttributeError when processing signals from before 2026-02-23.

### Pitfall 5: Large Parquet export exhausts memory

**What goes wrong:** A request for all symbols across all timeframes for 365 days loads millions of rows into a single DataFrame and crashes the process.
**Why it happens:** In-memory approach has no size cap.
**How to avoid:** Require both `symbol` and `timeframe` as mandatory query params (not optional) for the export endpoint. Add a `LIMIT` of 100,000 rows or enforce a max date range (e.g., 90 days). Document this constraint in the endpoint description.
**Warning signs:** Process OOM or extremely slow response times for broad export requests.

## Code Examples

Verified patterns from codebase inspection:

### DB query pattern (from instruments.py)
```python
# Source: src/api/routes/instruments.py
rows = await db_manager.execute_query(
    "SELECT symbol, contract_details, is_active FROM instruments WHERE symbol = $1",
    symbol.upper(),
)
```

### DB fetch pattern (from market_data.py)
```python
# Source: src/api/routes/market_data.py
rows = await db_manager.fetch(query, symbol, timeframe, limit)
# rows is list of asyncpg.Record — access by column name: row["timestamp"]
```

### Correct JSONB handling
```python
# asyncpg returns JSONB as str — must parse
import json
tier_dict = json.loads(row["i4"]) if row["i4"] else {}
garch_sigma = tier_dict.get("garch_sigma")
```

### Parquet export (confirmed pattern — pyarrow 23.0.1)
```python
import io
import pandas as pd
buf = io.BytesIO()
df.to_parquet(buf, engine="pyarrow", index=False)
buf.seek(0)
return Response(
    content=buf.read(),
    media_type="application/octet-stream",
    headers={"Content-Disposition": 'attachment; filename="features.parquet"'},
)
```

### TestClient with dependency override (for unit tests)
```python
# Source: FastAPI docs pattern + project test pattern
from fastapi.testclient import TestClient
from unittest.mock import AsyncMock
from src.api.main import app
from src.api import dependencies

def make_client(mock_rows):
    mock_db = AsyncMock()
    mock_db.fetch = AsyncMock(return_value=mock_rows)
    mock_db.execute_query = AsyncMock(return_value=mock_rows)

    app.dependency_overrides[dependencies.get_db_manager] = lambda: mock_db
    client = TestClient(app)
    yield client
    app.dependency_overrides.clear()
```

### intelligence_features SQL — date-range query
```sql
-- Source: intelligence_features schema inspection
SELECT ts, symbol, tf, platform, source, schema_version,
       bar, i1, i3, i4, i5, smc, i6
FROM intelligence_features
WHERE symbol = $1 AND tf = $2
  AND ($3::timestamptz IS NULL OR ts >= $3)
  AND ($4::timestamptz IS NULL OR ts <= $4)
ORDER BY ts DESC
LIMIT $5
-- Uses index: idx_intel_features_sym_tf_ts (symbol, tf, ts DESC)
```

### signal_ledger + features JOIN SQL
```sql
-- Source: signal_ledger + intelligence_features schema inspection
SELECT sl.signal_id, sl.timestamp, sl.symbol, sl.timeframe,
       sl.setup_plugin, sl.signal_type, sl.direction, sl.entry_price,
       sl.stop_loss, sl.confidence, sl.status,
       sl.feature_ts, sl.feature_tf,
       f.bar, f.i1, f.i3, f.i4, f.i5, f.smc, f.i6
FROM signal_ledger sl
LEFT JOIN intelligence_features f
  ON sl.symbol = f.symbol
 AND sl.feature_ts = f.ts
 AND sl.feature_tf = f.tf
WHERE sl.symbol = $1
ORDER BY sl.timestamp DESC
LIMIT $2
-- NULL feature columns when feature_ts IS NULL (pre-Phase 2 signals)
```

## Database Schema Summary

### intelligence_features (confirmed via psql)
- **Primary key:** `(ts, symbol, tf)`
- **Key index:** `idx_intel_features_sym_tf_ts` btree `(symbol, tf, ts DESC)` — the one we use
- **JSONB columns:** `bar`, `i1`, `i3`, `i4`, `i5`, `smc`, `i6` — all NOT NULL, default `'{}'::jsonb`
- **Text columns:** `symbol`, `tf`, `platform` ('futures'), `source` ('live'/'backfill'), `schema_version` ('1.0')
- **Current data:** 25 rows in dev (ESH6, NQH6, RTYH6 — from Jan 2026 test run)

### signal_ledger (confirmed via psql)
- **Primary key:** `(signal_id, timestamp)`
- **Feature JOIN columns:** `feature_ts timestamptz`, `feature_tf text` — both nullable
- **Status values:** 'pending', 'active', 'exit'
- **Current data:** 97,672+ rows from 2026-02-11 onward; all have `feature_ts = NULL`

## SSE Status: Already Correct (API-03)

The SSE `intelligence_data` event already publishes typed IntelligenceEvent payloads:

1. Publisher (`market_analysis_service.py`): `redis.xadd(stream_key, {"event": event.model_dump_json()})`
2. SSE route (`sse.py`): XREADs fields dict, emits `payload: {"event": "<IntelligenceEvent JSON>"}`
3. Dashboard (`use-market-stream.ts`): `parseIntelligence(payload)` → `JSON.parse(payload.event)` → accesses `.i3`, `.i4`, `.i5`, `.smc`, `.i6`

**No code change required.** The task for API-03 is:
- Write unit/integration test confirming `intelligence_data` SSE event payload contains `payload.event` as valid IntelligenceEvent JSON
- Confirm `_event_name_for_stream()` maps `intelligence:*` to `"intelligence_data"` (verified in sse.py line 73)

## Open Questions

1. **Symbol resolution — base vs. contract code in API paths**
   - What we know: `intelligence_features.symbol` stores contract codes (`ESH6`), not base symbols (`ES`). The existing SSE route has `_resolve_contract()` that maps base → contract. The `market_data.py` endpoints accept contract codes directly.
   - What's unclear: Should the features/signals endpoints accept base symbols (`ES`) and resolve to contract, or require contract codes (`ESH6`) directly?
   - Recommendation: Accept both (same pattern as `_resolve_contract()` in sse.py) — check if the input has a digit; if not, resolve via `Settings().contracts`. Keeps API user-friendly.

2. **Export endpoint size limits**
   - What we know: After full 365-day backfill (Phase 3), a single symbol at 1m TF is ~98k rows. At 5 tiers × ~25 fields each ≈ 125 columns × 98k rows ≈ manageable in memory (~50MB DataFrame).
   - What's unclear: Maximum safe row count without OOM; whether to add explicit limit or rely on date range.
   - Recommendation: Enforce `LIMIT 100000` in the SQL and require `symbol` + `timeframe` as mandatory params. Document in endpoint description. Add a `max_rows` guard in the handler.

3. **Signals endpoint — which columns from signal_ledger to expose**
   - What we know: `signal_ledger` has 33 columns including exit/P&L data. Phase 6 (Auth) is not yet built — no auth protection exists.
   - What's unclear: Should P&L outcome data be included in Phase 4 (before auth)?
   - Recommendation: Include all columns in Phase 4 since auth is Phase 6. The endpoint is currently only accessible locally. Revisit when auth is added.

## Validation Architecture

`workflow.nyquist_validation` is not set to `true` in `.planning/config.json` — this section is omitted per instructions.

## Sources

### Primary (HIGH confidence)
- Codebase inspection: `src/api/routes/sse.py` — confirmed SSE payload format, stream routing
- Codebase inspection: `src/api/routes/market_data.py`, `instruments.py` — confirmed route patterns, asyncpg usage
- Codebase inspection: `src/intelligence/schemas.py` — confirmed IntelligenceEvent field structure
- Codebase inspection: `dashboard/src/hooks/use-market-stream.ts` — confirmed `parseIntelligence()` already handles typed IntelligenceEvent
- DB schema: `psql \d intelligence_features`, `\d signal_ledger` — confirmed columns, indexes, nullable constraints
- Installed package versions: `pandas==3.0.1`, `fastapi==0.129.1`, `asyncpg==0.31.0` (confirmed in .venv)
- pyarrow: confirmed installable (`pip show pyarrow` → 23.0.1); NOT yet in requirements.txt

### Secondary (MEDIUM confidence)
- asyncpg JSONB behavior (returns str): confirmed by attempting `json.loads()` pattern analysis against existing code and asyncpg documentation convention

### Tertiary (LOW confidence)
- None

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — all libraries confirmed in .venv, versions verified
- Architecture: HIGH — route patterns confirmed from existing codebase, DB schemas confirmed from psql
- SSE status: HIGH — source code and dashboard code both read and confirmed
- Pitfalls: HIGH — asyncpg JSONB behavior confirmed from code analysis; route ordering is FastAPI-documented behavior
- Parquet export: HIGH — pyarrow confirmed installable; pandas to_parquet confirmed requires it

**Research date:** 2026-02-24
**Valid until:** 2026-04-24 (stable libraries, no fast-moving dependencies in this phase)
