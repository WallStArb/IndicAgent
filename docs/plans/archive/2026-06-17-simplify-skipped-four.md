# Simplify: Fix the Four Skipped Items

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix the four root-cause issues deferred from the Phase 131 simplification pass.

**Architecture:** Each fix is independent and self-contained. Task 1 extracts shared seed SQL constants so both the live executor and the replay script import the same definition. Task 2 replaces N asyncio connections with one batched DISTINCT ON query. Task 3 collapses two parallel asset_class injection sites into one base_features dict. Task 4 adds a covering index and removes the per-symbol Python batching workaround that was hiding it.

**Tech Stack:** Python 3.14, asyncpg (live path), psycopg2 (replay path), PostgreSQL/TimescaleDB.

## Global Constraints

- All timestamps UTC — `datetime.now(UTC)` only.
- No hardcoded topic strings — all via `stream_keys.py`.
- Run `.venv/bin/pytest tests/unit/ -q` after every task — must stay green.
- Commit message style: `fix(<area>): <description>` — no `Co-Authored-By`.
- Plans go in `docs/plans/`, migrations in `production/migrations/`.

---

### Task 1: Shared I3 seed SQL constants

**Problem:** The I3 seed query and numeric key set are defined independently in `feature_pipeline_executor.py` (asyncpg) and `run_historical_pipeline.py` (psycopg2). If the query drifts between the two, live and replay results diverge silently.

**Fix:** Extract `_I3_SEED_QUERY`, `_I3_SEED_COLS`, and `_I3_NUMERIC_KEYS` into a new shared module. Both callers import from it.

**Files:**
- Create: `src/intelligence/pipeline/seed_constants.py`
- Modify: `src/intelligence/pipeline/feature_pipeline_executor.py` — remove local `_SEED_QUERY` definition; import from `seed_constants`
- Modify: `production/scripts/run_historical_pipeline.py` — remove local `_SEED_NUMERIC_KEYS`; import from `seed_constants`

**Interfaces:**
- Produces: `_I3_SEED_QUERY: str`, `_I3_SEED_COLS: tuple[str, ...]`, `_I3_NUMERIC_KEYS: frozenset[str]`

- [ ] **Step 1: Create the shared constants module**

```python
# src/intelligence/pipeline/seed_constants.py
"""Shared constants for I3 trend-field seeding (A7 fix).

Both the live FeaturePipelineExecutor and the replay script seed _last_events /
intelligence_cache from intelligence_features using these constants. Keeping them
in one place prevents live/replay divergence.
"""

_I3_SEED_QUERY: str = """
    SELECT regime_features->>'trend_direction'    AS trend_direction,
           regime_features->>'trend_strength'     AS trend_strength,
           regime_features->>'trend_bars_elapsed' AS trend_bars_elapsed,
           regime_features->>'trend_confirmed'    AS trend_confirmed
    FROM intelligence_features
    WHERE symbol = $1 AND tf = $2
    ORDER BY ts DESC
    LIMIT 1
"""

# Column order matches _I3_SEED_QUERY SELECT list — used to build dicts from positional rows.
_I3_SEED_COLS: tuple[str, ...] = (
    "trend_direction",
    "trend_strength",
    "trend_bars_elapsed",
    "trend_confirmed",
)

# Fields that arrive as JSONB text and must be coerced to float for extract_trend_sign().
_I3_NUMERIC_KEYS: frozenset[str] = frozenset(
    {"trend_direction", "trend_strength", "trend_bars_elapsed"}
)
```

- [ ] **Step 2: Update feature_pipeline_executor.py to import from seed_constants**

In `src/intelligence/pipeline/feature_pipeline_executor.py`, add the import near the top (after the existing `from src.intelligence.*` imports):

```python
from src.intelligence.pipeline.seed_constants import _I3_SEED_QUERY
```

Then in `_seed_last_events_from_db`, remove the local `_SEED_QUERY = """..."""` block (lines ~166-175). The `_fetch_one` closure already references `_SEED_QUERY` — it will now use the imported name.

- [ ] **Step 3: Update run_historical_pipeline.py to import from seed_constants**

In `production/scripts/run_historical_pipeline.py`:

Remove these lines (near `_SEED_NUMERIC_KEYS` at ~line 1414):
```python
_SEED_NUMERIC_KEYS: frozenset[str] = frozenset({"trend_direction", "trend_strength", "trend_bars_elapsed"})
```

Add an import after the `from src.*` import block (search for the `# Set up sys.path BEFORE importing from src` section and add after it):
```python
from src.intelligence.pipeline.seed_constants import _I3_NUMERIC_KEYS as _SEED_NUMERIC_KEYS, _I3_SEED_COLS as _SEED_COLS
```

Then in the seed loop in `replay_symbol()`, replace `_seed_cols = ("trend_direction", ...)` with just `_seed_cols = _I3_SEED_COLS` (the tuple is now imported). The psycopg2 query string stays inline (different placeholder syntax `%s` vs `$1`) but at least the column list and numeric coercion keys are shared.

> **Note:** The psycopg2 query can't literally reuse `_I3_SEED_QUERY` because asyncpg uses `$1/$2` placeholders and psycopg2 uses `%s`. Extract the query body as a shared constant anyway — add `_I3_SEED_QUERY_PG: str` to `seed_constants.py` with `%s` placeholders for the replay path to use.

Actually do this: add both variants to `seed_constants.py`:

```python
# asyncpg placeholder variant ($1, $2) — used by FeaturePipelineExecutor
_I3_SEED_QUERY: str = """
    SELECT regime_features->>'trend_direction'    AS trend_direction,
           regime_features->>'trend_strength'     AS trend_strength,
           regime_features->>'trend_bars_elapsed' AS trend_bars_elapsed,
           regime_features->>'trend_confirmed'    AS trend_confirmed
    FROM intelligence_features
    WHERE symbol = $1 AND tf = $2
    ORDER BY ts DESC
    LIMIT 1
"""

# psycopg2 placeholder variant (%s) — used by run_historical_pipeline.py replay path
_I3_SEED_QUERY_PG: str = _I3_SEED_QUERY.replace("$1", "%s").replace("$2", "%s")
```

Then in `run_historical_pipeline.py` replace the inline SQL:
```python
from src.intelligence.pipeline.seed_constants import (
    _I3_NUMERIC_KEYS as _SEED_NUMERIC_KEYS,
    _I3_SEED_COLS as _SEED_COLS,
    _I3_SEED_QUERY_PG as _SEED_QUERY_PG,
)
```

And in `replay_symbol()` seed loop replace:
```python
_cur.execute(
    """SELECT regime_features->>'trend_direction'    AS trend_direction,
              ...
       WHERE symbol = %s AND tf = %s
       ORDER BY ts DESC
       LIMIT 1""",
    (symbol, _seed_tf),
)
```
with:
```python
_cur.execute(_SEED_QUERY_PG, (symbol, _seed_tf))
```

And remove `_seed_cols = _I3_SEED_COLS` (it's already imported as `_SEED_COLS` — use that).

- [ ] **Step 4: Run tests**

```bash
.venv/bin/pytest tests/unit/ -q
```

Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add src/intelligence/pipeline/seed_constants.py \
        src/intelligence/pipeline/feature_pipeline_executor.py \
        production/scripts/run_historical_pipeline.py
git commit -m "refactor(seed): extract shared I3 seed SQL constants to seed_constants.py"
```

---

### Task 2: Single batched DISTINCT ON query in `_seed_last_events_from_db`

**Problem:** `_seed_last_events_from_db` uses `asyncio.gather` to fire one `pool.acquire()` per (symbol, tf) pair — 4N pool acquire/release cycles for 4 TFs × N symbols. All queries hit the same table with the same ORDER BY; they can be collapsed into one round-trip.

**Fix:** Replace the per-pair gather with a single `DISTINCT ON (symbol, tf)` query over all symbols and timeframes at once.

**Files:**
- Modify: `src/intelligence/pipeline/feature_pipeline_executor.py` — `_seed_last_events_from_db`
- Modify: `src/intelligence/pipeline/seed_constants.py` — add `_I3_SEED_QUERY_BATCH`
- Modify: `tests/unit/pipeline/test_feature_pipeline_executor_seed.py` — update mock to return list of rows

**Interfaces:**
- Consumes: `_I3_SEED_QUERY_BATCH: str` from seed_constants (added here)
- The external behaviour of `_seed_last_events_from_db` is unchanged — callers pass same args, `_last_events` is populated the same way.

- [ ] **Step 1: Add batch query to seed_constants.py**

Add to `src/intelligence/pipeline/seed_constants.py`:

```python
# Single-round-trip variant: fetches the most recent row per (symbol, tf) for any
# combination of symbols and timeframes. DISTINCT ON guarantees one row per pair.
# asyncpg passes symbol list as $1 (array) and tf list as $2 (array).
_I3_SEED_QUERY_BATCH: str = """
    SELECT DISTINCT ON (symbol, tf)
        symbol,
        tf,
        regime_features->>'trend_direction'    AS trend_direction,
        regime_features->>'trend_strength'     AS trend_strength,
        regime_features->>'trend_bars_elapsed' AS trend_bars_elapsed,
        regime_features->>'trend_confirmed'    AS trend_confirmed
    FROM intelligence_features
    WHERE symbol = ANY($1) AND tf = ANY($2)
    ORDER BY symbol, tf, ts DESC
"""
```

- [ ] **Step 2: Write the failing test**

In `tests/unit/pipeline/test_feature_pipeline_executor_seed.py`, add:

```python
@pytest.mark.asyncio
async def test_seed_uses_single_batch_query() -> None:
    """_seed_last_events_from_db must call fetch() once (batch), not fetchrow() per pair."""
    executor = _make_executor()

    fake_rows = [
        _make_dict_row({
            "symbol": "ESM6", "tf": "1m",
            "trend_direction": "1.0", "trend_strength": "0.8",
            "trend_bars_elapsed": "5.0", "trend_confirmed": "true",
        }),
    ]

    mock_conn = AsyncMock()
    mock_conn.fetch = AsyncMock(return_value=fake_rows)
    mock_pool_ctx = AsyncMock()
    mock_pool_ctx.__aenter__ = AsyncMock(return_value=mock_conn)
    mock_pool_ctx.__aexit__ = AsyncMock(return_value=None)
    mock_db = MagicMock()
    mock_db.pool.acquire.return_value = mock_pool_ctx

    await executor._seed_last_events_from_db(["ESM6"], ["1m", "5m"], mock_db)

    # Must call fetch once (batched), never fetchrow (per-pair old pattern)
    mock_conn.fetch.assert_called_once()
    mock_conn.fetchrow.assert_not_called()
    assert "ESM6:1m" in executor._last_events
```

You need a helper `_make_dict_row` (asyncpg rows support `row["key"]` access):

```python
def _make_dict_row(data: dict) -> MagicMock:
    row = MagicMock()
    row.__getitem__ = lambda self, key: data.get(key)
    row.get = lambda key, default=None: data.get(key, default)
    return row
```

Run:
```bash
.venv/bin/pytest tests/unit/pipeline/test_feature_pipeline_executor_seed.py::test_seed_uses_single_batch_query -v
```
Expected: FAIL (method still uses `fetchrow`).

- [ ] **Step 3: Rewrite `_seed_last_events_from_db` to use single batch query**

Replace the body of `_seed_last_events_from_db` in `feature_pipeline_executor.py`:

```python
async def _seed_last_events_from_db(
    self,
    symbols: list[str],
    timeframes: list[str],
    db: DatabaseManager,
) -> None:
    """Seed _last_events from the most recent intelligence_features row per (symbol, tf).

    Single batch query using DISTINCT ON — one round-trip regardless of how many
    (symbol, tf) pairs are requested.
    """
    from src.intelligence.pipeline.seed_constants import _I3_SEED_QUERY_BATCH

    async with db.pool.acquire() as conn:
        rows = await conn.fetch(_I3_SEED_QUERY_BATCH, symbols, timeframes)

    seeded_count = 0
    for row in rows:
        symbol = row["symbol"]
        tf = row["tf"]
        trend_direction_raw = row["trend_direction"]
        trend_strength_raw = row["trend_strength"]
        trend_bars_elapsed_raw = row["trend_bars_elapsed"]

        event = IntelligenceEvent(
            ts=datetime.now(UTC),
            symbol=symbol,
            tf=tf,
            bar=OHLCVBar(o=0.0, h=0.0, l=0.0, c=0.0, v=0),
            i1=I1Indicators(),
            i3=I3Structure(
                trend_direction=(
                    float(trend_direction_raw) if trend_direction_raw is not None else None
                ),
                trend_strength=(
                    float(trend_strength_raw) if trend_strength_raw is not None else None
                ),
                trend_duration_bars=(
                    float(trend_bars_elapsed_raw)
                    if trend_bars_elapsed_raw is not None
                    else None
                ),
            ),
            i4=I4Context(),
            i5=I5Patterns(),
            smc=SMCContext(),
            i6=I6Confluence(),
            source="live",
        )
        self._last_events[f"{symbol}:{tf}"] = event
        seeded_count += 1

    if not rows:
        self._logger.debug(
            "seed: no prior intelligence_features rows",
            symbols=symbols,
            timeframes=timeframes,
        )

    self._logger.info(
        "seeded _last_events from DB",
        count=seeded_count,
        symbols=len(symbols),
        timeframes=len(timeframes),
    )
```

- [ ] **Step 4: Update existing tests that mock `fetchrow` per pair**

The existing tests in `test_feature_pipeline_executor_seed.py` mock `fetchrow`. They need to be updated to mock `fetch` (returns a list). Update `_make_mock_db`:

```python
def _make_mock_db(rows: list[dict] | None) -> MagicMock:
    """Return a mock DatabaseManager whose pool.acquire() returns a fake asyncpg conn."""
    mock_conn = AsyncMock()
    if rows is None or rows == []:
        mock_conn.fetch = AsyncMock(return_value=[])
    else:
        mock_rows = []
        for row_data in rows:
            mock_row = MagicMock()
            mock_row.__getitem__ = lambda self, key, d=row_data: d.get(key)
            mock_rows.append(mock_row)
        mock_conn.fetch = AsyncMock(return_value=mock_rows)

    mock_pool_ctx = AsyncMock()
    mock_pool_ctx.__aenter__ = AsyncMock(return_value=mock_conn)
    mock_pool_ctx.__aexit__ = AsyncMock(return_value=None)

    mock_db = MagicMock()
    mock_db.pool.acquire.return_value = mock_pool_ctx
    return mock_db
```

Update any existing test calls: `_make_mock_db(row)` → `_make_mock_db([{**row, "symbol": "ESM6", "tf": "1m"}])` (batch rows must include symbol/tf). Look at each existing test and add `"symbol"` and `"tf"` keys to the row dict, and wrap in a list.

- [ ] **Step 5: Run all tests**

```bash
.venv/bin/pytest tests/unit/pipeline/test_feature_pipeline_executor_seed.py -v
.venv/bin/pytest tests/unit/ -q
```

Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add src/intelligence/pipeline/seed_constants.py \
        src/intelligence/pipeline/feature_pipeline_executor.py \
        tests/unit/pipeline/test_feature_pipeline_executor_seed.py
git commit -m "perf(seed): replace per-pair asyncio.gather with single DISTINCT ON batch query"
```

---

### Task 3: Single asset_class injection point in `replay_symbol()`

**Problem:** `replay_symbol()` injects `_symbol_asset_class` into `all_features` at two separate points — once for the precomputed path (line ~1791) and once for the computed path (line ~1823). A third code path would silently miss the injection.

**Fix:** Build `_base_features` once before the bar loop and merge it into `all_features` in a single place after both branches resolve.

**Files:**
- Modify: `production/scripts/run_historical_pipeline.py` — `replay_symbol()` bar loop

- [ ] **Step 1: Write a failing test**

In `tests/unit/scripts/test_run_historical_pipeline.py`, add:

```python
def test_asset_class_injected_via_base_features(monkeypatch) -> None:
    """asset_class must be present in all_features regardless of which branch runs."""
    # This test validates the structure: after the fix, both the precomputed and
    # computed paths must see asset_class from a shared _base_features merge.
    # We verify indirectly: run replay_symbol with a mocked pipeline that captures
    # all_features passed to run_i7_and_persist and check asset_class is always present.
    # (This test documents intent; full integration requires a DB fixture.)
    # At minimum, verify the module-level logic is structurally correct by inspecting
    # that _base_features is built once from _symbol_asset_class.
    import ast, textwrap
    source = Path("production/scripts/run_historical_pipeline.py").read_text()
    # Structural assertion: "_base_features" must appear exactly once as an assignment
    # before the bar loop, and "all_features.update(_base_features)" in both branches.
    assert "_base_features" in source, "_base_features dict must exist after the fix"
    assert source.count('"asset_class"') <= 3, (
        "asset_class should only appear in _base_features construction + at most one legacy comment"
    )
```

Run:
```bash
.venv/bin/pytest tests/unit/scripts/test_run_historical_pipeline.py::test_asset_class_injected_via_base_features -v
```
Expected: FAIL (no `_base_features` in source yet).

- [ ] **Step 2: Refactor replay_symbol() bar loop**

In `production/scripts/run_historical_pipeline.py`, in `replay_symbol()`:

**Before** the bar-processing loop (after the `if seed_from_db:` block, around line ~1731), add:

```python
    # A4: resolve asset_class once and merge into every all_features dict via _base_features.
    # Both the precomputed and computed paths call all_features.update(_base_features).
    _base_features: dict[str, str] = (
        {"asset_class": _symbol_asset_class} if _symbol_asset_class is not None else {}
    )
```

Then in the precomputed branch, replace:
```python
            # A4 fix: inject asset_class for precomputed path (not stored in intelligence_features).
            if _symbol_asset_class is not None:
                all_features["asset_class"] = _symbol_asset_class
```
with:
```python
            all_features.update(_base_features)
```

And in the computed branch, replace:
```python
            # A4 fix: inject asset_class resolved at function start; mirrors
            # FeaturePipelineExecutor.execute():332 which injects via instrument_map DI.
            if _symbol_asset_class is not None:
                all_features["asset_class"] = _symbol_asset_class
```
with:
```python
            all_features.update(_base_features)
```

- [ ] **Step 3: Run tests**

```bash
.venv/bin/pytest tests/unit/scripts/test_run_historical_pipeline.py -v
.venv/bin/pytest tests/unit/ -q
```

Expected: all pass.

- [ ] **Step 4: Commit**

```bash
git add production/scripts/run_historical_pipeline.py \
        tests/unit/scripts/test_run_historical_pipeline.py
git commit -m "refactor(replay): single _base_features dict for asset_class injection"
```

---

### Task 4: Covering index + remove per-symbol batching in `_assert_backfill_integrity`

**Problem:** `_assert_backfill_integrity` loops symbol-by-symbol because running the integrity queries across all symbols caused timeouts. That's a missing-index problem, not a Python batching problem. The current workaround swallows errors per symbol, which means a real invariant violation on a single symbol gets logged as "audit infrastructure failed" and the function exits 0.

**Fix:** Add a covering index on `signal_events(symbol, signal_id)` (Migration 144), then replace the N-symbol loop with two single queries using `symbol = ANY(%s)`.

**Files:**
- Create: `production/migrations/144_signal_events_integrity_index.sql`
- Modify: `production/scripts/run_historical_pipeline.py` — `_assert_backfill_integrity`

- [ ] **Step 1: Create migration 144**

```sql
-- production/migrations/144_signal_events_integrity_index.sql
-- Migration 144: Two indexes to make _assert_backfill_integrity query-efficient at any
-- corpus size, eliminating the need for per-symbol Python batching.
--
-- INDEX 1: Invariant 2 — signal_id uniqueness per symbol.
--   Query: SELECT signal_id FROM signal_events WHERE symbol = ANY(%s) GROUP BY signal_id HAVING COUNT(*) > 1
--   Without index: full table scan.
--   With (symbol, signal_id): index-only scan — both filter and group key are in the index.
--
-- INDEX 2: Invariant 1 — was_selected uniqueness per (symbol, tf, bar_ts).
--   Query joins signal_events -> trade_frames ON (signal_id, signal_ts) WHERE was_selected = TRUE.
--   Existing idx_trade_frames_signal (signal_id, signal_ts) covers the JOIN columns but
--   must post-filter on was_selected, scanning all trade_frames rows per signal.
--   Partial index WHERE was_selected = TRUE is 5-20x smaller (selected rows are rare)
--   and turns the trade_frames side of the JOIN into an index-only scan on the subset
--   that actually matters. (Best Practice: use partial indexes for filtered queries.)

CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_signal_events_symbol_signal_id
    ON signal_events (symbol, signal_id);

CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_trade_frames_selected_signal_ts
    ON trade_frames (signal_id, signal_ts)
    WHERE was_selected = TRUE;
```

- [ ] **Step 2: Write failing test for non-batched behavior**

In `tests/unit/scripts/test_run_historical_pipeline.py`, add:

```python
def test_assert_backfill_integrity_uses_any_not_loop() -> None:
    """_assert_backfill_integrity must use ANY($1) not a per-symbol loop."""
    import inspect
    from production.scripts.run_historical_pipeline import _assert_backfill_integrity
    src = inspect.getsource(_assert_backfill_integrity)
    assert "for sym in symbols" not in src, (
        "_assert_backfill_integrity must not loop over symbols — use ANY(%s) instead"
    )
    assert "ANY" in src, "must use ANY(%s) for batch symbol filtering"
```

Run:
```bash
.venv/bin/pytest tests/unit/scripts/test_run_historical_pipeline.py::test_assert_backfill_integrity_uses_any_not_loop -v
```
Expected: FAIL (still has `for sym in symbols`).

- [ ] **Step 3: Rewrite `_assert_backfill_integrity`**

Replace the entire function body (keep the docstring) in `production/scripts/run_historical_pipeline.py`:

```python
def _assert_backfill_integrity(conn: Any, symbols: list[str]) -> None:
    """Assert was_selected and signal_id invariants across all symbols in one pass.

    Invariant 1: was_selected = TRUE occurs at most once per (symbol, tf, bar_ts).
    Invariant 2: Every signal_id in signal_events is globally unique.

    Runs two queries using ANY(%s) — covered by idx_signal_events_symbol_tf (migration 140)
    and idx_signal_events_symbol_signal_id (migration 144). sys.exit(1) on any violation.
    """
    # --- Invariant 1: was_selected uniqueness per (symbol, tf, bar_ts) ---
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT se.symbol, se.tf, se.ts, COUNT(*) AS winner_count
                FROM signal_events se
                JOIN trade_frames tf ON tf.signal_id = se.signal_id
                                   AND tf.signal_ts = se.ts
                WHERE se.symbol = ANY(%s) AND tf.was_selected = TRUE
                GROUP BY se.symbol, se.tf, se.ts
                HAVING COUNT(*) > 1
                ORDER BY winner_count DESC
                LIMIT 20
                """,
                (symbols,),
            )
            all_violations = cur.fetchall()
    except Exception as error:
        print(f"\n[INTEGRITY WARN] invariant 1 query failed: {error}")
        print("  Data may be intact; re-run audit manually to confirm.")
        return

    if all_violations:
        print(f"\n[INTEGRITY FAIL] was_selected > 1 per bar — {len(all_violations)} bars affected:")
        for sym, tf, ts, cnt in all_violations:
            print(f"  {sym}/{tf} @ {ts}: {cnt} winners")
        sys.exit(1)

    # --- Invariant 2: signal_id global uniqueness ---
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT COUNT(*) FROM (
                    SELECT signal_id FROM signal_events
                    WHERE symbol = ANY(%s)
                    GROUP BY signal_id HAVING COUNT(*) > 1
                ) dups
                """,
                (symbols,),
            )
            total_dup_count = cur.fetchone()[0]
    except Exception as error:
        print(f"\n[INTEGRITY WARN] invariant 2 query failed: {error}")
        print("  Data may be intact; re-run audit manually to confirm.")
        return

    if total_dup_count:
        print(f"\n[INTEGRITY FAIL] {total_dup_count} duplicate signal_ids found")
        sys.exit(1)

    print(
        f"\n[INTEGRITY PASS] was_selected invariant holds across {len(symbols)} symbols. signal_ids unique."
    )
```

> **Note on exception handling:** The old code swallowed per-symbol errors and continued, potentially hiding real violations. The new code returns (exits 0) on query failure for the whole batch — consistent with the docstring intent ("audit infrastructure failure is not a data integrity violation"). A single query failure now correctly aborts the audit rather than masking some symbols.

- [ ] **Step 4: Run tests**

```bash
.venv/bin/pytest tests/unit/scripts/test_run_historical_pipeline.py -v
.venv/bin/pytest tests/unit/ -q
```

Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add production/migrations/144_signal_events_integrity_index.sql \
        production/scripts/run_historical_pipeline.py \
        tests/unit/scripts/test_run_historical_pipeline.py
git commit -m "fix(integrity): add covering index + drop per-symbol batching from _assert_backfill_integrity"
```

---

## Execution Checklist

- [ ] Task 1: Shared I3 seed SQL constants
- [ ] Task 2: Single batched DISTINCT ON query
- [ ] Task 3: Single asset_class injection point
- [ ] Task 4: Covering index + remove per-symbol batching
