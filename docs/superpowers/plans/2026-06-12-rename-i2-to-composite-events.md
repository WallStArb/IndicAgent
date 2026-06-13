# Rename i2 DB Column to composite_events Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rename the `intelligence_features.i2` DB column to `composite_events` to match the functional naming convention used by all other tier columns, fixing an inconsistency left by Phase 122.

**Architecture:** The `i2` Pydantic field name and in-memory frames key `"i2"` are unchanged everywhere — only the DB column name and the SQL strings that reference it change. The seeder files (bar_history_seeder, warmup_provider) also have pre-existing wrong tier→column mappings that get fixed here. Migration 127 renames the column; all SQL then references `composite_events`.

**Tech Stack:** PostgreSQL/TimescaleDB migration, asyncpg, psycopg2 (run_historical_pipeline uses psycopg2 for batch inserts).

---

## Scope Boundary

**Changes:** DB column name in SQL strings + the three seeder files that incorrectly map Python tier keys to DB column names.

**No changes:** `frames.get("i2")` in any plugin, `event.i2` Pydantic attribute, `I2Events` class name, `Tier.I2` enum, test frames dicts (`"i2": {}`), or in-memory tiered dict keys. These are Python-layer tier identifiers, not DB column names.

---

## Files Modified

| File | What changes |
|------|-------------|
| `production/migrations/127_rename_i2_to_composite_events.sql` | **NEW** — DDL rename |
| `services/feature_writer.py` | SQL INSERT column list: `i2` → `composite_events` |
| `production/scripts/feature_replay.py` | SQL SELECT + `row["i2"]` → `row["composite_events"]` |
| `production/scripts/run_historical_pipeline.py` | SQL INSERT/SELECT + row variable name |
| `production/scripts/validate_alpha.py` | `"I2": "i2"` → `"I2": "composite_events"` |
| `src/persistence/repository/feature_snapshot_repository.py` | Add `composite_events` to SELECT; fix docstring |
| `src/persistence/logic/warmup_provider.py` | Fix all `_tier()` calls to use actual DB column names |
| `src/intelligence/services/bar_history_seeder.py` | Add `composite_events` to SELECT; fix scrambled tier→column mapping |
| `tests/unit/scripts/test_feature_replay.py` | Update SQL column assertion |
| `tests/unit/persistence/test_warmup_provider.py` | Fix `_make_feature_row` to use functional column names |
| `docs/intelligence/intelligence-foundation.md` | Add tier→DB column mapping table |

---

## Task 1: DB Migration

**Files:**
- Create: `production/migrations/127_rename_i2_to_composite_events.sql`

- [ ] **Step 1: Write the migration**

```sql
-- Migration 127: Rename i2 JSONB column to composite_events.
-- i2 was added in migration 124 using the tier-code name.
-- Migration 126 reverted i1/i3/i4/i5 to functional names but missed i2.
-- composite_events matches the I2 tier description: crossovers, threshold
-- crossings, and extremes from composite indicator plugins.
ALTER TABLE intelligence_features RENAME COLUMN i2 TO composite_events;
```

- [ ] **Step 2: Run the migration**

```bash
PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -f production/migrations/127_rename_i2_to_composite_events.sql
```

Expected output: `ALTER TABLE`

- [ ] **Step 3: Verify the rename**

```bash
PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -c "\d intelligence_features" | grep -E "composite_events|i2\b"
```

Expected: `composite_events | jsonb ...` and NO line containing just `i2 |`.

- [ ] **Step 4: Commit the migration**

```bash
git add production/migrations/127_rename_i2_to_composite_events.sql
git commit -m "feat(db): rename intelligence_features.i2 to composite_events (migration 127)"
```

---

## Task 2: feature_writer.py

**Files:**
- Modify: `services/feature_writer.py:67`

- [ ] **Step 1: Update SQL column name**

In `services/feature_writer.py`, change line 67:

```python
# BEFORE
    confluence_scores, smc, cross_timeframe_context, i2, trading_signals,

# AFTER
    confluence_scores, smc, cross_timeframe_context, composite_events, trading_signals,
```

The parameter position (`$15`) is unchanged — only the column name changes.

- [ ] **Step 2: Run tests**

```bash
.venv/bin/pytest tests/unit/services/test_feature_writer.py -q
```

Expected: all pass (tests mock the DB so column names don't affect them directly — but any SQL string assertions will catch the change).

- [ ] **Step 3: Commit**

```bash
git add services/feature_writer.py
git commit -m "fix(feature_writer): rename i2 → composite_events DB column reference"
```

---

## Task 3: feature_replay.py

**Files:**
- Modify: `production/scripts/feature_replay.py`

Three locations: the SQL constant, the row access for I2Events construction, and the local variable for building the flat_features dict.

- [ ] **Step 1: Update the SELECT SQL constant (line ~72)**

```python
# BEFORE
SELECT ts, symbol, tf, bar, technical_indicators, i2, regime_features, confluence_scores, pattern_detections, smc, cross_timeframe_context, market_context

# AFTER
SELECT ts, symbol, tf, bar, technical_indicators, composite_events, regime_features, confluence_scores, pattern_detections, smc, cross_timeframe_context, market_context
```

- [ ] **Step 2: Update the row access for I2Events (line ~157)**

```python
# BEFORE
            i2=I2Events(**(row["i2"] or {})),

# AFTER
            i2=I2Events(**(row["composite_events"] or {})),
```

- [ ] **Step 3: Update the i2_data local variable (line ~212)**

```python
# BEFORE
        i2_data = row["i2"] or {}

# AFTER
        i2_data = row["composite_events"] or {}
```

- [ ] **Step 4: Run tests**

```bash
.venv/bin/pytest tests/unit/scripts/test_feature_replay.py -q
```

Expected: FAIL on `test_functional_column_names_in_select` (asserts `"i2"` in SQL, now needs `"composite_events"`). Fix in Task 7.

- [ ] **Step 5: Commit**

```bash
git add production/scripts/feature_replay.py
git commit -m "fix(feature_replay): rename i2 → composite_events DB column reference"
```

---

## Task 4: run_historical_pipeline.py

**Files:**
- Modify: `production/scripts/run_historical_pipeline.py`

Four locations: two SQL strings, a comment, and a row variable.

- [ ] **Step 1: Update _INSERT_FEATURE_SYNC_SQL (line ~569)**

```python
# BEFORE
    confluence_scores, smc, cross_timeframe_context, i2

# AFTER
    confluence_scores, smc, cross_timeframe_context, composite_events
```

- [ ] **Step 2: Update _event_to_sync_params docstring (line ~646)**

```python
# BEFORE
      confluence_scores, smc, cross_timeframe_context, i2

# AFTER
      confluence_scores, smc, cross_timeframe_context, composite_events
```

- [ ] **Step 3: Update _load_precomputed_features SQL (line ~1007)**

```python
# BEFORE
            " i2, market_context"

# AFTER
            " composite_events, market_context"
```

- [ ] **Step 4: Update the row variable name and comment (line ~1016)**

```python
# BEFORE
    for ts, tf, i1_data, i5_data, i3_data, i4_data, smc_col, ctf, i2_col, mkt_col in rows:
        merged: dict = {}
        for tier in (i1_data, i5_data, i3_data, i4_data, smc_col, ctf, i2_col, mkt_col):

# AFTER
    for ts, tf, i1_data, i5_data, i3_data, i4_data, smc_col, ctf, ce_col, mkt_col in rows:
        merged: dict = {}
        for tier in (i1_data, i5_data, i3_data, i4_data, smc_col, ctf, ce_col, mkt_col):
```

- [ ] **Step 5: Update the comment at line ~999**

```python
# BEFORE
    All eight JSONB tier columns (including i2 and market_context) are merged

# AFTER
    All eight JSONB tier columns (including composite_events and market_context) are merged
```

- [ ] **Step 6: Run tests**

```bash
.venv/bin/pytest tests/unit/scripts/test_run_historical_pipeline.py -q
```

Expected: tests that check `"i2" in tiered` still pass (those test the in-memory tiered dict key, which is still `"i2"`). Any SQL string assertions should pass.

- [ ] **Step 7: Commit**

```bash
git add production/scripts/run_historical_pipeline.py
git commit -m "fix(historical_pipeline): rename i2 → composite_events DB column reference"
```

---

## Task 5: validate_alpha.py

**Files:**
- Modify: `production/scripts/validate_alpha.py:98`

- [ ] **Step 1: Update the tier→column mapping**

```python
# BEFORE
        "I2": "i2",

# AFTER
        "I2": "composite_events",
```

- [ ] **Step 2: Run tests**

```bash
.venv/bin/pytest tests/unit/scripts/test_validate_alpha.py -q 2>/dev/null || echo "no test file"
```

- [ ] **Step 3: Commit**

```bash
git add production/scripts/validate_alpha.py
git commit -m "fix(validate_alpha): update I2 tier→column mapping to composite_events"
```

---

## Task 6: Persistence layer — feature_snapshot_repository.py and warmup_provider.py

**Files:**
- Modify: `src/persistence/repository/feature_snapshot_repository.py`
- Modify: `src/persistence/logic/warmup_provider.py`

**Context:** `feature_snapshot_repository.py` did not SELECT `i2` at all, so `warmup_provider._tier("i2")` was silently failing (KeyError swallowed by outer try-except). Additionally, warmup_provider used tier-code keys (`"i1"`, `"i3"`, `"i4"`, `"i5"`, `"i6"`) for all `_tier()` calls, but the SELECT returns functional column names. All I1/I3/I4/I5/I6 tiers were silently initializing as empty dicts during warmup.

- [ ] **Step 1: Add composite_events to feature_snapshot_repository SELECT**

In `src/persistence/repository/feature_snapshot_repository.py`, update the SQL query and docstring:

```python
    async def get_recent_features(
        self,
        symbol: str,
        tf: str,
        limit: int,
        lookback_secs: int,
    ) -> list[dict[str, Any]]:
        """Return recent rows from intelligence_features, newest first.

        Each row has keys: ts, bar, technical_indicators, composite_events,
        market_context, pattern_detections, regime_features, confluence_scores,
        smc, cross_timeframe_context, bar_close_ts, i1_computed_at, computed_at.
        Returns [] on query failure.
        """
        try:
            return await self._db.execute_query(
                """
                SELECT ts, bar, technical_indicators, composite_events, market_context,
                       pattern_detections, regime_features, confluence_scores, smc,
                       cross_timeframe_context, bar_close_ts, i1_computed_at, computed_at
                FROM intelligence_features
                WHERE symbol = $1 AND tf = $2
                  AND ts > NOW() - ($3 * INTERVAL '1 second')
                ORDER BY ts DESC
                LIMIT $4
                """,
                symbol,
                tf,
                lookback_secs,
                limit,
            )
```

- [ ] **Step 2: Fix all _tier() calls in warmup_provider.py**

In `src/persistence/logic/warmup_provider.py`, update the tier construction block (lines ~174-180):

```python
# BEFORE
                        i1=I1Indicators(**_tier("i1")),
                        i2=I2Events(**_tier("i2")),
                        i3=I3Structure(**_tier("i3")),
                        i4=I4Context(**_tier("i4")),
                        i5=I5Patterns(**_tier("i5")),
                        smc=SMCContext(**_tier("smc")),
                        i6=I6Confluence(**_tier("i6")),

# AFTER
                        i1=I1Indicators(**_tier("technical_indicators")),
                        i2=I2Events(**_tier("composite_events")),
                        i3=I3Structure(**_tier("regime_features")),
                        i4=I4Context(**_tier("confluence_scores")),
                        i5=I5Patterns(**_tier("pattern_detections")),
                        smc=SMCContext(**_tier("smc")),
                        i6=I6Confluence(**_tier("cross_timeframe_context")),
```

- [ ] **Step 3: Run tests**

```bash
.venv/bin/pytest tests/unit/persistence/ -q
```

Expected: FAIL on `test_warmup_provider.py` tests that use `_make_feature_row` (which has `"i2": {}` as a key — needs updating). Fix in Task 7.

- [ ] **Step 4: Commit**

```bash
git add src/persistence/repository/feature_snapshot_repository.py src/persistence/logic/warmup_provider.py
git commit -m "fix(warmup): use functional column names in feature_snapshot_repository and warmup_provider tier mapping"
```

---

## Task 6b: bar_history_seeder.py

**Files:**
- Modify: `src/intelligence/services/bar_history_seeder.py`

**Context:** The seeder SELECT excludes `composite_events` (was `i2`). It uses `market_context` for I2 and has i3/i4/i5 column mappings swapped relative to their actual DB columns. All three tier models (I3Structure, I4Context, I5Patterns) were being fed data from the wrong columns.

- [ ] **Step 1: Add composite_events to SELECT and fix tier→column mapping**

In `src/intelligence/services/bar_history_seeder.py`, update the SQL query (line ~124) and the tier construction block (lines ~197-203):

```python
# SQL — add composite_events
                    rows = await db.execute_query(
                        f"""
                        SELECT ts, bar, technical_indicators, composite_events, market_context,
                               pattern_detections, regime_features, confluence_scores, smc,
                               cross_timeframe_context, bar_close_ts, i1_computed_at, computed_at
                        FROM intelligence_features
                        WHERE symbol = $1 AND tf = $2
                          AND ts > NOW() - INTERVAL '{lookback_secs} seconds'
                        ORDER BY ts DESC
                        LIMIT {min_bars}
                        """,
                        symbol,
                        tf,
                    )
```

```python
# Tier construction — fix all column names
                        i1=I1Indicators(**_tier("technical_indicators")),
                        i2=I2Events(**_tier("composite_events")),
                        i3=I3Structure(**_tier("regime_features")),
                        i4=I4Context(**_tier("confluence_scores")),
                        i5=I5Patterns(**_tier("pattern_detections")),
                        smc=SMCContext(**_tier("smc")),
                        i6=I6Confluence(**_tier("cross_timeframe_context")),
```

- [ ] **Step 2: Run tests**

```bash
.venv/bin/pytest tests/unit/intelligence/test_bar_history_seeder.py -q 2>/dev/null || echo "no test file"
.venv/bin/pytest tests/unit/ -k "seeder" -q
```

- [ ] **Step 3: Commit**

```bash
git add src/intelligence/services/bar_history_seeder.py
git commit -m "fix(bar_history_seeder): add composite_events to SELECT and fix scrambled tier→column mapping"
```

---

## Task 7: Update tests

**Files:**
- Modify: `tests/unit/scripts/test_feature_replay.py`
- Modify: `tests/unit/persistence/test_warmup_provider.py`

- [ ] **Step 1: Fix test_feature_replay.py SQL column assertion**

In `tests/unit/scripts/test_feature_replay.py`, update `test_functional_column_names_in_select`:

```python
def test_functional_column_names_in_select() -> None:
    """SELECT query must use functional column names (migrations 126+127)."""
    src = _SRC
    required_columns = (
        "technical_indicators",
        "regime_features",
        "confluence_scores",
        "pattern_detections",
        "composite_events",
        "smc",
        "cross_timeframe_context",
    )
    for col in required_columns:
        assert col in src, f"Expected column '{col}' in _SELECT_FEATURES_SQL"
```

Also update `test_tier_code_db_columns_not_in_select` — remove the `i2` exclusion since `i2` is now fully renamed:

```python
def test_tier_code_db_columns_not_in_select() -> None:
    """Tier-code DB column names must not appear as DB column refs (migrations 126+127)."""
    src = _SRC
    for tier_col in ("i1", "i3", "i4", "i5", "i2"):
        assert (
            f'row["{tier_col}"]' not in src
        ), f'Tier-code column ref row["{tier_col}"] found — use functional name'
```

- [ ] **Step 2: Fix test_warmup_provider.py `_make_feature_row`**

In `tests/unit/persistence/test_warmup_provider.py`, update `_make_feature_row` to use functional column names matching what `feature_snapshot_repository.get_recent_features` returns:

```python
def _make_feature_row(symbol: str = "ES", tf: str = "1m") -> dict:
    ts = datetime(2026, 3, 26, 10, 0, tzinfo=UTC)
    return {
        "ts": ts,
        "bar": {"o": 5100.0, "h": 5110.0, "l": 5095.0, "c": 5105.0, "v": 1000},
        "technical_indicators": {},
        "composite_events": {},
        "regime_features": {},
        "confluence_scores": {},
        "pattern_detections": {},
        "smc": {},
        "cross_timeframe_context": {},
        "market_context": {},
        "bar_close_ts": ts,
        "i1_computed_at": ts,
        "computed_at": ts,
    }
```

- [ ] **Step 3: Run all tests**

```bash
.venv/bin/pytest tests/unit/ -q
```

Expected: all previously passing tests still pass; the tests updated in this task now pass.

- [ ] **Step 4: Commit**

```bash
git add tests/unit/scripts/test_feature_replay.py tests/unit/persistence/test_warmup_provider.py
git commit -m "test: update feature_replay and warmup_provider tests for composite_events rename"
```

---

## Task 8: Update docs

**Files:**
- Modify: `docs/intelligence/intelligence-foundation.md`

- [ ] **Step 1: Add tier→DB column mapping table**

Find the `### Hypertables (TimescaleDB)` section in `docs/intelligence/intelligence-foundation.md` (around line 248). After the `intelligence_features` bullet, add:

```markdown
  **Tier→DB column mapping** (Python tier key → `intelligence_features` JSONB column):

  | Python tier key | DB column | Pydantic model |
  |----------------|-----------|----------------|
  | `i1` | `technical_indicators` | `I1Indicators` |
  | `i2` | `composite_events` | `I2Events` |
  | `i3` | `regime_features` | `I3Structure` |
  | `i4` | `confluence_scores` | `I4Context` |
  | `i5` | `pattern_detections` | `I5Patterns` |
  | `smc` | `smc` | `SMCContext` |
  | `i6` | `cross_timeframe_context` | `I6Confluence` |
```

- [ ] **Step 2: Commit**

```bash
git add docs/intelligence/intelligence-foundation.md
git commit -m "docs(intelligence): add tier→DB column mapping table; document composite_events rename"
```

---

## Task 9: Final verification

- [ ] **Step 1: Full test suite**

```bash
.venv/bin/pytest tests/unit/ -q
```

Expected: same pass count as before this plan started (42 pre-existing failures, no new failures).

- [ ] **Step 2: Grep for any remaining i2 DB column refs**

```bash
grep -rn 'row\["i2"\]\|row\.get.*"i2"\| i2,\|,i2\b\|"i2"\s*FROM\|"i2"\s*INTO\|INTO.*"i2"\|_tier("i2")' \
  services/ production/scripts/ src/persistence/ src/intelligence/services/ \
  --include="*.py"
```

Expected: zero matches.

- [ ] **Step 3: Verify DB column exists**

```bash
PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent \
  -c "SELECT composite_events FROM intelligence_features LIMIT 1"
```

Expected: returns a row (or empty result set) — no `column does not exist` error.

- [ ] **Step 4: Merge and push**

```bash
git checkout main && git merge --ff-only <branch>
git branch -d <branch>
git worktree prune
git push origin main
```
