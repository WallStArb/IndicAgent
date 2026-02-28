# Phase 3: Historical Data - Research

**Researched:** 2026-02-23
**Domain:** Historical backfill pipeline extension — intelligence_features write path
**Confidence:** HIGH

## Summary

Phase 3 has one technical task and one operational task. The technical task is extending `historical_backfill.py` Stage 2 to write to `intelligence_features` alongside `signal_ledger`, with `source='backfill'` set on every row. The operational task is running the extended backfill for 365 days and validating row counts and JOIN integrity.

The existing backfill already runs the full I1 through I7 pipeline and produces `features` and `intelligence` dicts per bar. What it does NOT do is assemble an `IntelligenceEvent` from those dicts and persist it. The extension must: build an `IntelligenceEvent` from the per-bar pipeline outputs, call `_event_to_insert_params()` (already written in `feature_writer_service.py`), and batch-insert directly into `intelligence_features` using psycopg2 (not asyncpg — the backfill is synchronous). This is additive — no existing code is broken.

The signal_ledger currently has 97,672 rows covering 2026-02-11 to 2026-02-23 (about 12 days). `intelligence_features` is empty. The 365-day target requires a Stage 1 fetch from IBKR TWS (host 10.0.0.33) to pull market data, then a Stage 2 replay to generate both `signal_ledger` and `intelligence_features` rows. Stage 1 is blocked by IBKR TWS availability; Stage 2 can be developed and unit-tested independently of IBKR.

**Primary recommendation:** Implement `_build_intelligence_event()` and `_insert_features_sync()` in `historical_backfill.py`, call them from `run_i7_and_persist()` after the pipeline run, then run `--days 365 --replay-only` to populate both tables. The `source='backfill'` field on `IntelligenceEvent` distinguishes backfill rows from live rows at query time.

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|-----------------|
| HST-01 | Historical backfill runs 365 days producing 2,700+ signals in `signal_ledger` | Existing Stage 1 (IBKR fetch) + Stage 2 (I1→I7 replay) already writes to `signal_ledger`; just needs `--days 365` run |
| HST-02 | `intelligence_features` populated with corresponding feature history for ML training | Requires new `_build_intelligence_event()` + `_insert_features_sync()` added to Stage 2 loop |
| HST-03 | Backfill writes both `signal_ledger` and `intelligence_features` in Stage 2 | Both writes must occur per bar within `run_i7_and_persist()` or equivalent; both use psycopg2 sync |
</phase_requirements>

## Standard Stack

### Core

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| psycopg2 | 2.9.x (already in .venv) | Sync DB writes for both `signal_ledger` and `intelligence_features` in Stage 2 | All existing backfill DB writes use psycopg2; asyncpg is only for live services |
| Pydantic v2 | 2.x (already in .venv) | `IntelligenceEvent` model construction and serialization | `IntelligenceEvent` is a Pydantic v2 model; `model_dump_json()` already used in feature_writer_service |
| psycopg2.extras.execute_batch | same | Batch INSERT for `intelligence_features` rows | Already used for `signal_ledger` inserts in `_insert_signals_sync()` |

### Supporting

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| json | stdlib | Serialize JSONB columns to strings for psycopg2 | psycopg2 does not auto-serialize dicts to JSONB; `json.dumps()` required for each JSONB column |
| pandas | 1.x/2.x (in .venv) | DataFrame construction for plugin compute | Already used in `run_i1_plugins()` and `run_i7_and_persist()` |

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| psycopg2 (sync) | asyncpg (async) | asyncpg is used by live services but the backfill is synchronous; mixing async into a sync script adds complexity with no benefit |
| Direct dict assembly | `IntelligenceEvent` Pydantic model | Could write raw dicts directly but using `IntelligenceEvent` enforces schema validation and reuses `_event_to_insert_params()` from `feature_writer_service.py` |

## Architecture Patterns

### Recommended Project Structure

The extension lives entirely in `production/scripts/historical_backfill.py`. No new files are needed.

```
production/scripts/historical_backfill.py
  + _build_intelligence_event(bar, i1_features, intelligence, symbol, tf, ts)
      → IntelligenceEvent | None
  + _insert_features_sync(conn, rows)          (batch psycopg2 insert)
  modified: run_i7_and_persist() — call both signal insert and features insert
```

The new SQL constant mirrors the asyncpg version in `feature_writer_service.py` but uses `%s` placeholders (psycopg2) instead of `$N`:

```python
_INSERT_FEATURE_SYNC_SQL = """
INSERT INTO intelligence_features (
    ts, symbol, tf, platform, source, schema_version,
    bar, i1, i3, i4, i5, smc, i6
) VALUES (%s, %s, %s, %s, %s, %s,
    %s::jsonb, %s::jsonb, %s::jsonb, %s::jsonb, %s::jsonb, %s::jsonb, %s::jsonb)
ON CONFLICT (ts, symbol, tf) DO NOTHING
"""
```

### Pattern 1: Build IntelligenceEvent from pipeline outputs

**What:** Construct an `IntelligenceEvent` from the flat `i1_features` and `intelligence` dicts that Stage 2 already produces per bar.

**When to use:** After the I1→I6 pipeline runs for each bar, before calling I7.

**Key insight:** The `intelligence` dict from `run_analysis_pipeline()` is a merged flat dict of all I3/I4/I5/SMC/I6 plugin outputs. Each sub-model (I3Structure, I4Context, etc.) uses `extra='forbid'` but all fields are `Optional` — so constructing each sub-model with only the keys it recognizes is safe; unknown keys from other tiers just won't match any declared field and will raise `ValidationError` if passed directly. The correct approach is to pass only the fields belonging to each sub-model.

**The mapping problem:** The flat `intelligence` dict contains keys from ALL tiers mixed together (e.g., both `trend_direction` from I3 and `smc_trend_direction` from SMC are in the same dict). Each Pydantic sub-model declares only its own fields. Construction must pass `**{k: v for k, v in intelligence.items() if k in SubModel.model_fields}` or use `model_validate(intelligence, strict=False)` with `extra='ignore'` — but the models use `extra='forbid'`. The safest pattern is to filter keys before passing.

**Recommended approach:**

```python
def _build_intelligence_event(
    bar: dict,
    i1_features: dict,
    intelligence: dict,
    symbol: str,
    tf: str,
    ts: datetime,
) -> IntelligenceEvent | None:
    """Build IntelligenceEvent from per-bar pipeline outputs.

    Returns None on any validation failure (bar is skipped — not crashed).
    """
    try:
        from src.intelligence.schemas import (
            IntelligenceEvent, OHLCVBar, I1Indicators,
            I3Structure, I4Context, I5Patterns, SMCContext, I6Confluence,
        )
        def _pick(model_cls, src):
            fields = model_cls.model_fields.keys()
            return {k: v for k, v in src.items() if k in fields}

        return IntelligenceEvent(
            ts=ts,
            symbol=symbol,
            tf=tf,
            source="backfill",
            bar=OHLCVBar(
                o=float(bar.get("open", 0)),
                h=float(bar.get("high", 0)),
                l=float(bar.get("low", 0)),
                c=float(bar.get("close", 0)),
                v=int(bar.get("volume", 0)),
            ),
            i1=I1Indicators(**_pick(I1Indicators, i1_features)),
            i3=I3Structure(**_pick(I3Structure, intelligence)),
            i4=I4Context(**_pick(I4Context, intelligence)),
            i5=I5Patterns(**_pick(I5Patterns, intelligence)),
            smc=SMCContext(**_pick(SMCContext, intelligence)),
            i6=I6Confluence(**_pick(I6Confluence, intelligence)),
        )
    except Exception:
        return None  # never crash the replay loop
```

**Note on I1Indicators `extra='allow'`:** I1Indicators uses `extra='allow'` so passing extra keys is fine. The `_pick` filter is still useful to avoid passing non-I1 keys (like I3/I4 outputs that might collide), but it is not strictly required for I1. For I3–I6 which use `extra='forbid'`, the key filter is mandatory.

### Pattern 2: Sync batch insert for intelligence_features

**What:** Same pattern as `_insert_signals_sync()` — collect rows into a list, call `psycopg2.extras.execute_batch()`, commit.

**Established in:** `_insert_signals_sync()` at line 224 of `historical_backfill.py`.

```python
def _insert_features_sync(conn, rows: list[tuple]) -> None:
    """Batch insert intelligence_features rows via psycopg2."""
    if not rows:
        return
    with conn.cursor() as cur:
        psycopg2.extras.execute_batch(cur, _INSERT_FEATURE_SYNC_SQL, rows)
    conn.commit()
```

**Row construction:** Use `_event_to_insert_params()` from `feature_writer_service.py` — BUT that function returns asyncpg-compatible parameters (datetime objects, string JSON). For psycopg2 the same approach works: datetime objects are handled natively by psycopg2, and `json.dumps()` strings with `::jsonb` cast in SQL work identically. The function can be copied or imported. Given the backfill is standalone, duplicating the tuple-building logic inline is cleaner than importing from a service module.

### Pattern 3: Integrate into the existing replay loop

**What:** Call `_build_intelligence_event()` + `_insert_features_sync()` inside `run_i7_and_persist()` (or at the call site in `replay_symbol()`).

**Recommended call site:** At the top of `run_i7_and_persist()`, after the `MIN_BARS` check but before I7 plugins run. This ensures every bar that produces I7 signals also has a corresponding intelligence_features row.

**Alternative:** Call separately after `run_analysis_pipeline()` in `replay_symbol()`. This would write features rows even for bars where no I7 signals fire — which is actually better for the ML model (more feature coverage). This is the preferred approach: write intelligence_features for every bar that passes the `MIN_BARS` gate, not just bars that produce signals.

**Consequence for JOIN integrity:** If features are written per bar (not per signal), then every signal row will have a corresponding features row. The JOIN from `signal_ledger.feature_ts` to `intelligence_features.ts` will work — but note that backfill signals currently write `feature_ts=NULL` (Phase 2 decision). Phase 3 must decide whether to:
- Keep `feature_ts=NULL` on backfill signals (current behavior, signals are not linked to features rows), OR
- Populate `feature_ts=ts` on backfill signals to enable the JOIN

**Recommendation:** Populate `feature_ts=ts` and `feature_tf=tf` on backfill signals when an intelligence_features row was successfully written for that bar. This enables the JOIN and satisfies HST-02's "corresponding feature rows" goal. This requires a small change to `_build_ledger_entries()` to accept the bar timestamp for feature linkage.

### Anti-Patterns to Avoid

- **Importing from services in the backfill script:** The backfill is a standalone script. Do not import `_event_to_insert_params` from `feature_writer_service` — duplicate the logic inline or extract to `src/`.
- **Using asyncpg `$N` placeholders with psycopg2:** psycopg2 uses `%s` placeholders; asyncpg uses `$1..$N`. The `_INSERT_FEATURE_SQL` in `feature_writer_service.py` uses `$N` and cannot be reused with psycopg2 directly.
- **Calling `run_analysis_pipeline()` twice:** The pipeline is already called in `replay_symbol()`. Do not re-run it in a separate features-writing function.
- **Constructing sub-models with unfiltered dicts:** Passing the full flat `intelligence` dict to `I3Structure(**intelligence)` will raise `ValidationError` because it contains keys from other tiers (I4, I5, SMC, I6). Always filter keys per sub-model.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| JSONB column serialization | Custom serializer | `json.dumps(model.model_dump())` | Already established pattern in `_event_to_insert_params()`; the `exclude_none=True` pattern for I3-I6 is also established |
| Batch INSERT | Row-by-row cursor.execute | `psycopg2.extras.execute_batch` | Already used in `_insert_signals_sync()`; handles parameterization safely |
| Schema validation | Manual field checking | `IntelligenceEvent` Pydantic model | Catches type errors at construction time; aligns with live service behavior |

**Key insight:** The intelligence_features INSERT SQL and serialization pattern are already proven in `feature_writer_service.py`. The only new work is: (1) building an `IntelligenceEvent` from the flat dicts the backfill already produces, and (2) writing the sync psycopg2 version of the insert.

## Common Pitfalls

### Pitfall 1: extra='forbid' on I3-I6 sub-models

**What goes wrong:** Constructing `I3Structure(**intelligence)` raises `ValidationError: Extra inputs are not permitted` because `intelligence` contains keys from all tiers merged together (e.g., `garch_sigma` from I4 will fail validation in I3Structure).

**Why it happens:** `run_analysis_pipeline()` merges all tier outputs into one flat dict. The Pydantic sub-models use `extra='forbid'` by design (schema drift protection).

**How to avoid:** Always use a key filter: `{k: v for k, v in intelligence.items() if k in ModelClass.model_fields}`.

**Warning signs:** `pydantic.ValidationError: Extra inputs are not permitted` in the backfill log.

### Pitfall 2: psycopg2 vs asyncpg placeholder syntax

**What goes wrong:** Copy-pasting `_INSERT_FEATURE_SQL` from `feature_writer_service.py` (which uses `$1, $2, ... $13`) into the backfill script causes `psycopg2.errors.SyntaxError` because psycopg2 expects `%s` placeholders.

**Why it happens:** asyncpg and psycopg2 use different placeholder conventions.

**How to avoid:** Write a new `_INSERT_FEATURE_SYNC_SQL` constant using `%s` placeholders. Use `psycopg2.extras.execute_batch()` not `await db_manager.execute_batch()`.

**Warning signs:** `psycopg2.errors.SyntaxError` or unexpected column binding errors.

### Pitfall 3: ON CONFLICT behavior at 1m resolution

**What goes wrong:** If Stage 2 is run twice (e.g., re-run after crash), rows that already exist in `intelligence_features` will be silently skipped due to `ON CONFLICT (ts, symbol, tf) DO NOTHING`.

**Why it happens:** The primary key is `(ts, symbol, tf)` — a re-run of the same bar will hit the conflict.

**How to avoid:** This is the desired behavior — idempotent writes. Just verify after a re-run that row counts match expectations (no silent data loss).

### Pitfall 4: Backfill run duration for 365 days

**What goes wrong:** 365 days * 22 symbols * ~390 1m bars/day trading session ≈ 3.1M bars. Each bar runs 57 plugins. The replay will take significant time — estimate 1-4 hours depending on hardware.

**Why it happens:** The pipeline is CPU-bound; each bar runs all I1-I6 plugins synchronously.

**How to avoid:** Use `--symbols ESH6,NQH6` to test a subset first. Run with `nohup` or `screen` to survive terminal disconnects. Monitor progress via the `{i+1} % 1000 == 0` print statements already in `replay_symbol()`.

**Warning signs:** Terminal disconnect killing the process mid-run.

### Pitfall 5: Missing contracts in 365-day historical data

**What goes wrong:** IBKR may not have full 365 days of 1m data for all 22 contracts (some contracts like ZCH6, ZSH6, ZWH6 only have data since 2026-02-12 currently). Fetching 365 days for contracts that recently rolled will return fewer bars.

**Why it happens:** Futures contracts roll; the front-month for H6 contracts only traded since ~March 2025. Some contracts like VXH6, SR1H6 may have limited history.

**How to avoid:** Run Stage 1 for all contracts and accept partial history. The 2,700+ signal count target should still be achievable with ESH6/NQH6 alone given their liquidity. Document actual row counts in the verification.

### Pitfall 6: signal_ledger already has 97,672 rows

**What goes wrong:** If `--replay-only --days 365` is run, it will re-process bars already covered (2026-02-11 to present), producing duplicate signal attempts. The `ON CONFLICT DO NOTHING` in `_INSERT_SYNC_SQL` will silently skip them (due to `signal_id` UUID), but the new code producing `intelligence_features` rows will also skip them via `ON CONFLICT (ts, symbol, tf) DO NOTHING`.

**Why it happens:** The signal_ledger uses UUID as primary key — no natural conflict key. The UUID is generated fresh on each replay so `ON CONFLICT DO NOTHING` on signal_ledger will NOT deduplicate — it uses `ON CONFLICT DO NOTHING` which means no conflict on UUID. Re-running Stage 2 will insert duplicate signals for dates already covered.

**How to avoid:** Check if signals already exist for the date range before replaying. Or truncate signal_ledger before the 365-day run if a clean baseline is desired. The cleanest approach: run Stage 1 first (fetch 365 days), then run Stage 2 once from scratch with a cleared signal_ledger, or filter bars to only process those not yet in the ledger.

**Warning signs:** `signal_ledger` count grows beyond expected 2,700+ to suspiciously round multiples.

**Correction:** Re-reading `_INSERT_SYNC_SQL`, it uses `ON CONFLICT DO NOTHING` without specifying a conflict target — this means it will use the table's primary key. The `signal_ledger` primary key appears to be `signal_id` (UUID), so duplicates won't be prevented. Verify this before running.

## Code Examples

### Build IntelligenceEvent from flat pipeline dicts

```python
# Source: pattern derived from feature_writer_service._event_to_insert_params()
# and historical_backfill.run_analysis_pipeline()

def _build_intelligence_event(
    bar: dict,
    i1_features: dict[str, Any],
    intelligence: dict[str, Any],
    symbol: str,
    tf: str,
    ts: datetime,
) -> "IntelligenceEvent | None":
    try:
        def _pick(model_cls, src):
            return {k: v for k, v in src.items() if k in model_cls.model_fields}
        return IntelligenceEvent(
            ts=ts, symbol=symbol, tf=tf, source="backfill",
            bar=OHLCVBar(o=bar["open"], h=bar["high"], l=bar["low"],
                         c=bar["close"], v=bar["volume"]),
            i1=I1Indicators(**i1_features),   # extra='allow', no filter needed
            i3=I3Structure(**_pick(I3Structure, intelligence)),
            i4=I4Context(**_pick(I4Context, intelligence)),
            i5=I5Patterns(**_pick(I5Patterns, intelligence)),
            smc=SMCContext(**_pick(SMCContext, intelligence)),
            i6=I6Confluence(**_pick(I6Confluence, intelligence)),
        )
    except Exception:
        return None
```

### psycopg2 batch insert for intelligence_features

```python
# Source: derived from _insert_signals_sync() in historical_backfill.py
# and _INSERT_FEATURE_SQL in feature_writer_service.py (adapted for %s)

_INSERT_FEATURE_SYNC_SQL = """
INSERT INTO intelligence_features (
    ts, symbol, tf, platform, source, schema_version,
    bar, i1, i3, i4, i5, smc, i6
) VALUES (%s, %s, %s, %s, %s, %s,
    %s::jsonb, %s::jsonb, %s::jsonb, %s::jsonb, %s::jsonb, %s::jsonb, %s::jsonb)
ON CONFLICT (ts, symbol, tf) DO NOTHING
"""

def _insert_features_sync(conn, rows: list[tuple]) -> None:
    if not rows:
        return
    with conn.cursor() as cur:
        psycopg2.extras.execute_batch(cur, _INSERT_FEATURE_SYNC_SQL, rows)
    conn.commit()

def _event_to_sync_params(event: IntelligenceEvent) -> tuple:
    return (
        event.ts, event.symbol, event.tf, event.platform,
        event.source, event.schema_version,
        json.dumps(event.bar.model_dump()),
        json.dumps(event.i1.model_dump()),
        json.dumps(event.i3.model_dump(exclude_none=True)),
        json.dumps(event.i4.model_dump(exclude_none=True)),
        json.dumps(event.i5.model_dump(exclude_none=True)),
        json.dumps(event.smc.model_dump(exclude_none=True)),
        json.dumps(event.i6.model_dump(exclude_none=True)),
    )
```

### Validation query: JOIN integrity check

```sql
-- Check: every signal with feature_ts set has a matching intelligence_features row
SELECT count(*) AS orphaned_signals
FROM signal_ledger sl
WHERE sl.feature_ts IS NOT NULL
  AND NOT EXISTS (
      SELECT 1 FROM intelligence_features inf
      WHERE inf.ts = sl.feature_ts
        AND inf.symbol = sl.symbol
        AND inf.tf = sl.feature_tf
  );
-- Expected: 0
```

```sql
-- Check: intelligence_features row counts by symbol and timeframe
SELECT symbol, tf, count(*) as feature_rows,
       min(ts) as from_ts, max(ts) as to_ts
FROM intelligence_features
WHERE source = 'backfill'
GROUP BY symbol, tf
ORDER BY symbol, tf;
```

### Run commands

```bash
# Stage 1: fetch 365 days from IBKR (requires TWS on 10.0.0.33)
source .venv/bin/activate
python production/scripts/historical_backfill.py --days 365 --fetch-only --client-id 56

# Stage 2: replay and populate signal_ledger + intelligence_features
python production/scripts/historical_backfill.py --replay-only \
    --timeframes 1m,5m,15m,1h

# Test with subset first
python production/scripts/historical_backfill.py --replay-only \
    --symbols ESH6,NQH6 --timeframes 1m

# Validation queries (after Stage 2)
psql postgresql://postgres:postgres@localhost:5432/indicagent \
    -c "SELECT count(*) FROM signal_ledger WHERE source IS NULL OR timestamp >= NOW() - INTERVAL '365 days';"
psql postgresql://postgres:postgres@localhost:5432/indicagent \
    -c "SELECT count(*) FROM intelligence_features WHERE source = 'backfill';"
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Backfill writes only `signal_ledger` | Backfill writes both `signal_ledger` and `intelligence_features` | Phase 3 (this phase) | ML model gets 365 days of feature history |
| `feature_ts=NULL` on all backfill signals | `feature_ts=ts` when features row was written | Phase 3 change | JOIN from signal to feature context becomes possible |
| `source='historical_backfill'` in market_data_ohlcv | `source='backfill'` in `IntelligenceEvent.source` | Phase 3 (new field use) | Distinguishes live vs backfill rows in intelligence_features queries |

## Open Questions

1. **Should signal_ledger be cleared before the 365-day run?**
   - What we know: It currently has 97,672 rows from 2026-02-11 to now. The `ON CONFLICT DO NOTHING` on signal_ledger uses UUID as conflict target — re-running will INSERT new UUIDs even for dates already covered, creating duplicates.
   - What's unclear: Whether the user wants to keep existing signal rows or start fresh.
   - Recommendation: The plan should include a decision step — document the choice and provide a truncation command if desired. For ML training, having two "runs" of signals for the same bars is confusing. Recommend: truncate and rerun cleanly.

2. **Which timeframes to replay?**
   - What we know: The CLI default is `1m,5m,15m,1h`. The continuous aggregates (migration 008) produce 5m/15m bars from 1m. Replaying 4 timeframes multiplies runtime by ~4x.
   - What's unclear: Whether the planner wants to replay all 4 timeframes or just 1m for the initial run.
   - Recommendation: Plan 03-01 should replay all 4 timeframes to maximize signal count and feature coverage. The 2,700+ signal target is achievable with 1m alone for 22 contracts, but multi-TF coverage is better for ML.

3. **Should `feature_ts` be populated on backfill signals?**
   - What we know: Phase 2 decision was `feature_ts=NULL` for backfill (no IntelligenceEvent at replay time). If Phase 3 writes IntelligenceEvents to intelligence_features per bar, then `feature_ts=ts` is available and correct.
   - What's unclear: Whether this contradicts the Phase 2 decision or extends it.
   - Recommendation: Phase 2 decision was correct at the time — there was no IntelligenceEvent during backfill. Phase 3 creates one, so populating `feature_ts=ts` is now valid and should be done to satisfy HST-02 (corresponding feature rows, joinable).

## Validation Architecture

### Test Framework

| Property | Value |
|----------|-------|
| Framework | pytest 7.x+ with asyncio-mode=auto |
| Config file | `pyproject.toml` `[tool:pytest]` section |
| Quick run command | `source .venv/bin/activate && python -m pytest tests/unit/test_historical_backfill.py -x -q` |
| Full suite command | `source .venv/bin/activate && python -m pytest tests/ -x -q` |
| Estimated runtime | ~5-10 seconds for unit tests |

### Phase Requirements to Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| HST-01 | Stage 2 still writes signal_ledger (regression) | unit | `pytest tests/unit/test_historical_backfill.py -x -q` | Yes |
| HST-02 | `_build_intelligence_event()` produces valid IntelligenceEvent from flat pipeline dicts | unit | `pytest tests/unit/test_historical_backfill.py::TestBuildIntelligenceEvent -x -q` | No — Wave 0 gap |
| HST-02 | `_insert_features_sync()` calls execute_batch with correct params | unit | `pytest tests/unit/test_historical_backfill.py::TestInsertFeaturesSync -x -q` | No — Wave 0 gap |
| HST-03 | `run_i7_and_persist()` calls both signal insert and features insert | unit | `pytest tests/unit/test_historical_backfill.py::TestRunI7BothWrites -x -q` | No — Wave 0 gap |
| HST-01/HST-02 | Row counts and JOIN integrity after 365-day run | manual/smoke | SQL queries after Stage 2 run | N/A |

### Nyquist Sampling Rate

- **Minimum sample interval:** After every committed task — run: `python -m pytest tests/unit/test_historical_backfill.py -x -q`
- **Full suite trigger:** Before merging final task of plan 03-01
- **Phase-complete gate:** Full suite green + manual SQL validation queries pass before marking Phase 3 done
- **Estimated feedback latency per task:** ~5 seconds

### Wave 0 Gaps (must be created before implementation)

- `tests/unit/test_historical_backfill.py` — covers new `_build_intelligence_event()` function (TestBuildIntelligenceEvent class), `_insert_features_sync()` (TestInsertFeaturesSync class), and `_event_to_sync_params()` tuple structure. The file exists but lacks these new test classes.

## Sources

### Primary (HIGH confidence)

- Codebase: `/home/bg/dev/indicagent/production/scripts/historical_backfill.py` — full 573-line implementation examined
- Codebase: `/home/bg/dev/indicagent/services/feature_writer_service.py` — `_event_to_insert_params()`, `_INSERT_FEATURE_SQL`, batch insert pattern
- Codebase: `/home/bg/dev/indicagent/src/intelligence/schemas.py` — IntelligenceEvent sub-model structure, `extra` config per tier
- Codebase: `/home/bg/dev/indicagent/production/migrations/009_intelligence_features.sql` — live table schema confirmed
- Codebase: `/home/bg/dev/indicagent/production/migrations/010_signal_ledger_feature_cols.sql` — feature_ts/feature_tf columns confirmed
- DB query: `intelligence_features` confirmed empty (0 rows), `signal_ledger` has 97,672 rows (2026-02-11 to 2026-02-23)
- DB query: `market_data_ohlcv` has 167,854 rows across 17 symbols (2026-02-11 to present, ~12 days)
- Codebase: `.planning/STATE.md` — Phase 2 decision: `feature_ts=NULL` for backfill (design decision to revisit in Phase 3)
- Codebase: `/home/bg/dev/indicagent/tests/unit/test_historical_backfill.py` — 11 existing tests confirmed passing

### Secondary (MEDIUM confidence)

- MEMORY.md context: IBKR TWS on 10.0.0.33 is a blocker for Stage 1; Stage 2 can be developed independently
- MEMORY.md context: 365-day backfill duration is unknown but expected to be significant (hours)

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — all libraries already in use in the codebase, no new dependencies needed
- Architecture: HIGH — the code to extend already exists; the pattern is established in feature_writer_service.py
- Pitfalls: HIGH — identified from direct code inspection (placeholder syntax, extra='forbid', signal deduplication)

**Research date:** 2026-02-23
**Valid until:** 2026-03-23 (stable domain — internal code, no external library changes expected)
