# `market_data_ohlcv` Tradeable-Bars Boundary Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the confirmed data-integrity bug where `cross_sectional_regime_model.py` and
`counterfactual_tracker.py` read `market_data_ohlcv` with zero filtering of placeholder bars
(82% intraday contamination), by introducing a single `market_data_ohlcv_tradeable` view and a
CI-enforced guard that stops the same gap from recurring at a future call site.

**Architecture:** One Postgres view (`WHERE volume > 0`) as the single filtering boundary; the
two live, zero-filtered call sites switch their `FROM` clause to the view; a pytest-based
allow-list test greps the tree for any raw `market_data_ohlcv` reference and fails CI if a new
one appears outside the checked-in allow-list.

**Tech Stack:** PostgreSQL/TimescaleDB (migration SQL), Python (psycopg2 in `counterfactual_tracker.py`,
psycopg2 in `cross_sectional_regime_model.py`), pytest (`tests/unit/`, `tests/integration/`).

## Global Constraints

- All timestamps UTC (`datetime.now(UTC)` only) — not touched by this plan, but any new code must
  comply.
- Exception variable name is `error`, not `exc` — not applicable here (no new exception handling
  added).
- `tests/unit/` must be CI-clean (no DB, no network) — the allow-list test and the two
  source-inspection tests in Tasks 2/3 must not require a live DB connection.
- DB-touching tests belong in `tests/integration/`, which rebuilds `indicagent_test` from a
  pinned baseline (`tests/integration/conftest.py`, cutoff migration 234) and auto-replays any
  migration numbered above the cutoff — migration 236 (Task 1) will be picked up automatically,
  no conftest changes needed.
- Never log per-row inside a loop over the full corpus — not applicable here (no new loops added).
- Design reference: `docs/plans/2026-07-16-market-data-ohlcv-active-bars-boundary-design.md` —
  read it for full rationale; this plan implements its Decisions 1-3 exactly, don't re-derive them.

---

### Task 1: Migration 236 — create `market_data_ohlcv_tradeable` view

**Files:**
- Create: `production/migrations/236_market_data_ohlcv_tradeable_view.sql`
- Test: `tests/integration/test_market_data_ohlcv_tradeable_view.py`

**Interfaces:**
- Produces: a Postgres view `market_data_ohlcv_tradeable` with identical columns to
  `market_data_ohlcv` (`timestamp, symbol, timeframe, open, high, low, close, volume, source,
  base`), filtered to `volume > 0`. Tasks 2 and 3 select from this view by name.

- [ ] **Step 1: Write the migration file**

```sql
-- Migration 236: market_data_ohlcv_tradeable view (todo 035)
--
-- market_data_ohlcv is a continuous calendar grid: bar_normalizer.py inserts flat-OHLC,
-- zero-volume placeholder rows (source='synthetic_fill') to fill weekend/holiday/gap slots,
-- and IBKR itself separately returns flat-OHLC, zero-volume carry-forward bars
-- (source='ibkr_named') when no trade occurs in a window -- empirically confirmed
-- (2026-07-16) that 99.998% of "real" ibkr_named/volume=0 rows are perfectly flat OHLC,
-- informationally identical to synthetic_fill. volume > 0 excludes both classes with a
-- single NOT NULL integer comparison -- no source-column dependency, no NULL handling
-- needed. See docs/plans/2026-07-16-market-data-ohlcv-active-bars-boundary-design.md for
-- the full audit and the predicate-choice rationale (Decision 1).
--
-- This is a plain (non-materialized) view: Postgres inlines it into the query plan, so
-- callers get identical chunk-exclusion and index usage to an inline WHERE volume > 0 --
-- verified via EXPLAIN (COSTS OFF) against live SPY 5m data before this migration was
-- written: same compressed-chunk index scan, same vectorized columnar filter, in both
-- forms.
--
-- Named _tradeable, not _active: 'active' is already a loaded lifecycle-status term in
-- this codebase (feature_registry/concept_registry/trade_frames: candidate -> active ->
-- shadow_only/expired -> deprecated). 'tradeable' is unused elsewhere and is the term
-- todo 035 itself already used.

BEGIN;

CREATE VIEW market_data_ohlcv_tradeable AS
SELECT *
FROM market_data_ohlcv
WHERE volume > 0;

COMMIT;
```

- [ ] **Step 2: Apply the migration to the dev database**

Run: `PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -f production/migrations/236_market_data_ohlcv_tradeable_view.sql`
Expected: `BEGIN` / `CREATE VIEW` / `COMMIT` — no errors. (Safe to run against the live dev DB
while the 143.1-07 corpus rebuild is in progress: `CREATE VIEW` takes no lock on
`market_data_ohlcv` beyond a brief `ACCESS SHARE`, and does not touch the currently-running
`ic_engine` process or its connections.)

- [ ] **Step 3: Write the failing integration test**

```python
"""Integration test: market_data_ohlcv_tradeable view filters volume=0 bars correctly.

Requires a live DB (indicagent_test) -- belongs in tests/integration/, not tests/unit/.
"""

from __future__ import annotations

import asyncpg
import pytest

_TEST_DB_URL = "postgresql://postgres:postgres@localhost:5432/indicagent_test"


@pytest.mark.asyncio
async def test_view_excludes_zero_volume_bars_and_includes_real_bars():
    conn = await asyncpg.connect(_TEST_DB_URL)
    try:
        await conn.execute(
            """
            INSERT INTO market_data_ohlcv
                (timestamp, symbol, timeframe, open, high, low, close, volume, source)
            VALUES
                ('2024-01-02 09:30:00+00', 'ZZTEST', '5m', 100.0, 100.5, 99.5, 100.2, 500, 'ibkr_named'),
                ('2024-01-02 09:35:00+00', 'ZZTEST', '5m', 100.2, 100.2, 100.2, 100.2, 0, 'synthetic_fill'),
                ('2024-01-02 09:40:00+00', 'ZZTEST', '5m', 100.2, 100.2, 100.2, 100.2, 0, 'ibkr_named')
            """
        )
        rows = await conn.fetch(
            "SELECT timestamp, volume FROM market_data_ohlcv_tradeable "
            "WHERE symbol = 'ZZTEST' ORDER BY timestamp"
        )
        assert len(rows) == 1
        assert rows[0]["volume"] == 500
    finally:
        await conn.execute("DELETE FROM market_data_ohlcv WHERE symbol = 'ZZTEST'")
        await conn.close()
```

- [ ] **Step 4: Run test to verify it fails before the migration is known-applied**

Run: `.venv/bin/pytest tests/integration/test_market_data_ohlcv_tradeable_view.py -v`
Expected: the `migrated_test_database` session fixture (`tests/integration/conftest.py`) rebuilds
`indicagent_test` and auto-replays migration 236 (it globs everything numbered above the 234
baseline cutoff) — so this test should actually PASS on first run once Step 1's file exists,
proving the fixture picked up the new migration correctly. If it instead fails with
`relation "market_data_ohlcv_tradeable" does not exist`, the migration file wasn't saved before
running the test — re-check Step 1.

- [ ] **Step 5: Confirm test passes**

Run: `.venv/bin/pytest tests/integration/test_market_data_ohlcv_tradeable_view.py -v`
Expected: `1 passed`

- [ ] **Step 6: Commit**

```bash
git add production/migrations/236_market_data_ohlcv_tradeable_view.sql tests/integration/test_market_data_ohlcv_tradeable_view.py
git commit -m "feat(db): add market_data_ohlcv_tradeable view (migration 236)"
```

---

### Task 2: Fix `cross_sectional_regime_model.py`'s zero-filter bar fetch

**Files:**
- Modify: `services/cross_sectional_regime_model.py:272-277` (`_fetch_group_bars`'s `sql` string)
- Test: `tests/unit/test_cross_sectional_regime_model.py`

**Interfaces:**
- Consumes: `market_data_ohlcv_tradeable` view from Task 1.
- No signature change to `_fetch_group_bars(dsn: str, tf: str, symbols: list[str]) -> dict[str, pd.DataFrame]`.

- [ ] **Step 1: Write the failing unit test**

Add to `tests/unit/test_cross_sectional_regime_model.py` (append a new test class; file already
imports `sys`, `Path`, and inserts project root onto `sys.path` at the top, matching this test's
needs):

```python
class TestFetchGroupBarsQueriesTradeableView:
    """_fetch_group_bars must read from market_data_ohlcv_tradeable, not the raw table
    (todo 035 / 2026-07-16 audit: the raw table is ~82% synthetic-fill/flat-carry-forward
    placeholder rows at intraday timeframes, contaminating every downstream regime label)."""

    def test_sql_references_tradeable_view_not_raw_table(self):
        import inspect

        import services.cross_sectional_regime_model as module

        source = inspect.getsource(module._fetch_group_bars)
        assert "market_data_ohlcv_tradeable" in source
        assert "FROM market_data_ohlcv\n" not in source
        assert "FROM market_data_ohlcv " not in source
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/unit/test_cross_sectional_regime_model.py::TestFetchGroupBarsQueriesTradeableView -v`
Expected: FAIL — `assert "market_data_ohlcv_tradeable" in source` fails, current source says
`FROM market_data_ohlcv`.

- [ ] **Step 3: Fix the query**

In `services/cross_sectional_regime_model.py`, change:

```python
    sql = """
        SELECT symbol, timestamp, close
        FROM market_data_ohlcv
        WHERE symbol = ANY(%s) AND timeframe = %s
        ORDER BY symbol, timestamp ASC
    """
```

to:

```python
    sql = """
        SELECT symbol, timestamp, close
        FROM market_data_ohlcv_tradeable
        WHERE symbol = ANY(%s) AND timeframe = %s
        ORDER BY symbol, timestamp ASC
    """
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/unit/test_cross_sectional_regime_model.py -v`
Expected: all tests in the file `PASSED`, including the new
`TestFetchGroupBarsQueriesTradeableView` class.

- [ ] **Step 5: Commit**

```bash
git add services/cross_sectional_regime_model.py tests/unit/test_cross_sectional_regime_model.py
git commit -m "fix(regime): cross_sectional_regime_model reads market_data_ohlcv_tradeable"
```

---

### Task 3: Fix `counterfactual_tracker.py`'s two zero-filter bar fetches

**Files:**
- Modify: `services/counterfactual_tracker.py:262-268` (`_ATR_SEED_SQL`),
  `services/counterfactual_tracker.py:275-280` (`_BAR_SCAN_SQL`)
- Test: `tests/unit/test_counterfactual_tracker.py`

**Interfaces:**
- Consumes: `market_data_ohlcv_tradeable` view from Task 1.
- No signature change to either SQL constant's call sites (`cur.execute(_ATR_SEED_SQL, ...)` at
  line 389, `cur.execute(_BAR_SCAN_SQL, ...)` at line 408).

- [ ] **Step 1: Write the failing unit test**

Add to `tests/unit/test_counterfactual_tracker.py` (file already imports `inspect` at the top —
same pattern as the existing `test_worker_source_uses_named_cursor_not_plain_cursor` test in
this file):

```python
def test_atr_seed_and_bar_scan_sql_query_tradeable_view_not_raw_table():
    """_ATR_SEED_SQL / _BAR_SCAN_SQL must read market_data_ohlcv_tradeable, not the raw
    table (todo 035 / 2026-07-16 audit: a synthetic-fill or IBKR flat-carry-forward bar
    here means zero true range and a fabricated flat price feeding stop/target exit
    logic in determine_exit)."""
    import services.counterfactual_tracker as module

    assert "market_data_ohlcv_tradeable" in module._ATR_SEED_SQL
    assert "market_data_ohlcv_tradeable" in module._BAR_SCAN_SQL
    assert "FROM market_data_ohlcv\n" not in module._ATR_SEED_SQL
    assert "FROM market_data_ohlcv\n" not in module._BAR_SCAN_SQL
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/unit/test_counterfactual_tracker.py::test_atr_seed_and_bar_scan_sql_query_tradeable_view_not_raw_table -v`
Expected: FAIL — both assertions on `"market_data_ohlcv_tradeable" in ...` fail.

- [ ] **Step 3: Fix both queries**

In `services/counterfactual_tracker.py`, change:

```python
_ATR_SEED_SQL = """
    SELECT open, high, low, close
    FROM market_data_ohlcv
    WHERE symbol = %s AND timeframe = %s AND timestamp <= %s
    ORDER BY timestamp DESC
    LIMIT %s
"""
```

to:

```python
_ATR_SEED_SQL = """
    SELECT open, high, low, close
    FROM market_data_ohlcv_tradeable
    WHERE symbol = %s AND timeframe = %s AND timestamp <= %s
    ORDER BY timestamp DESC
    LIMIT %s
"""
```

and change:

```python
_BAR_SCAN_SQL = """
    SELECT timestamp, open, high, low, close
    FROM market_data_ohlcv
    WHERE symbol = %s AND timeframe = %s AND timestamp > %s
    ORDER BY timestamp ASC
"""
```

to:

```python
_BAR_SCAN_SQL = """
    SELECT timestamp, open, high, low, close
    FROM market_data_ohlcv_tradeable
    WHERE symbol = %s AND timeframe = %s AND timestamp > %s
    ORDER BY timestamp ASC
"""
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/unit/test_counterfactual_tracker.py -v`
Expected: all tests in the file `PASSED`.

- [ ] **Step 5: Commit**

```bash
git add services/counterfactual_tracker.py tests/unit/test_counterfactual_tracker.py
git commit -m "fix(counterfactual): ATR seed and bar-path scan read market_data_ohlcv_tradeable"
```

---

### Task 4: CI-enforced allow-list — stop the next call site from reintroducing the gap

**Files:**
- Create: `tests/unit/test_market_data_ohlcv_boundary.py`

**Interfaces:**
- No production code interface — this is a static-analysis test with no runtime dependency on
  Tasks 1-3 beyond their file edits already having landed (the allow-list below assumes Tasks 2
  and 3 are already applied — the fixed files no longer match the raw-table pattern).

- [ ] **Step 1: Write the test (this IS the deliverable — there's no "make it fail first"**
  **step here since it's a repo-content assertion, not a behavior to implement; write it,**
  **run it, and it should pass immediately if Tasks 1-3 already landed)**

```python
"""CI guard: no new raw `market_data_ohlcv` reads outside this checked-in allow-list.

market_data_ohlcv is a continuous calendar grid containing synthetic-fill and IBKR
flat-carry-forward placeholder bars (see docs/plans/2026-07-16-market-data-ohlcv-active-
bars-boundary-design.md). Three separate files independently reintroduced this exact gap
over three weeks before this guard existed. A new file reading the raw table now fails CI
immediately unless this allow-list is also edited -- which forces a "why does this need
raw access" justification into the diff itself, at review time, rather than relying on
someone remembering to add `market_data_ohlcv_tradeable` to a FROM clause.

CI-clean: no DB, no network -- pure filesystem grep.
"""

from __future__ import annotations

import re
from pathlib import Path

_REPO_ROOT = Path(__file__).parent.parent.parent
_RAW_TABLE_PATTERN = re.compile(r"FROM\s+market_data_ohlcv\b(?!_tradeable)")
_SEARCH_DIRS = ("services", "src", "scripts")

# (file, reason) -- every raw `market_data_ohlcv` reference in the tree must appear here.
# Adding a new call site requires adding a row here with a real reason, not just silencing
# the test.
_ALLOW_LIST: dict[str, str] = {
    "services/signal_replay_auditor.py": (
        "Dead v2.x Signal Ledger Architecture code (signal_ledger) -- CLAUDE.md documents "
        "this tier as archived, no live consumer since 2026-07-02. Verified 2026-07-16: no "
        "running systemd unit, signal_events/trade_frames have zero rows. Not fixed -- "
        "v2.x's fate is todo 056's separate open question, not this guard's call."
    ),
    "services/signal_probe_auditor.py": (
        "Dead v2.x Signal Ledger Architecture code (signal_events/trade_frames) -- same "
        "verification as signal_replay_auditor.py above."
    ),
    "services/equity_regime_model.py": (
        "Dead code -- Phase 144 rollback path only (services/cross_sectional_regime_model.py "
        "is the live replacement), not currently invoked by the corpus pipeline."
    ),
    "services/backfill_feature_factory.py": (
        "Already correctly filters with `volume > 0` (confirmed correct via empirical audit "
        "2026-07-16, not migrated to the view yet -- Tier-2 follow-up, todo 123's sibling "
        "audit list)."
    ),
    "services/regime_writer.py": (
        "Already correctly filters with `volume > 0` -- same Tier-2 follow-up as above."
    ),
    "services/forward_return_writer.py": (
        "Already correctly filters with `volume > 0` -- same Tier-2 follow-up as above."
    ),
    "services/bar_replay_provider.py": (
        "Not yet classified -- Tier-2 audit follow-up (see design doc's 'not yet classified' "
        "list, 2026-07-16)."
    ),
    "scripts/ops/roll/ops_roll_batch.py": (
        "Not yet classified -- Tier-2 audit follow-up."
    ),
    "scripts/infrastructure/backfill/infrastructure_fetch_htf_bars.py": (
        "Not yet classified -- Tier-2 audit follow-up."
    ),
    "src/providers/base_provider_agent.py": (
        "Not yet classified -- likely wants the full calendar grid intentionally (backfill "
        "completeness count against the calendar target), but not verified. Tier-2 follow-up."
    ),
    "src/intelligence/services/bar_history_seeder.py": (
        "Not yet classified -- Tier-2 audit follow-up."
    ),
    "scripts/ops/pipeline/ops_pipeline_status.py": (
        "Monitoring wants the full grid -- gaps are the signal here, not noise. Correctly "
        "left alone (design doc's 'correctly left alone' list)."
    ),
    "scripts/infrastructure/backfill/infrastructure_context_features_writer.py": (
        "Not yet classified -- Tier-2 audit follow-up."
    ),
    "scripts/infrastructure/backfill/infrastructure_run_historical_pipeline.py": (
        "Backfill bookkeeping (min/max timestamp checks) against the full calendar grid -- "
        "plausibly intentional, not verified. Tier-2 audit follow-up."
    ),
    "scripts/debug/analysis/debug_bic_k_selection.py": (
        "Debug tooling -- Tier-2 audit follow-up."
    ),
    "scripts/debug/replay/debug_lifecycle_replay.py": (
        "Debug tooling -- Tier-2 audit follow-up."
    ),
    "scripts/analysis/crowding_proxy_regression.py": (
        "Standing diagnostic script, not a live gate -- Tier-2 audit follow-up."
    ),
    "src/persistence/repository/feature_snapshot_repository.py": (
        "Not yet classified -- Tier-2 audit follow-up."
    ),
    "src/api/routes/market_data.py": (
        "Raw display/API surface, not a measurement input -- correctly left alone (design "
        "doc's 'correctly left alone' list)."
    ),
}


def _find_raw_table_references() -> dict[str, int]:
    """Returns {relative_path: match_count} for every .py file under _SEARCH_DIRS that
    references the raw market_data_ohlcv table (not the _tradeable view)."""
    hits: dict[str, int] = {}
    for search_dir in _SEARCH_DIRS:
        for path in (_REPO_ROOT / search_dir).rglob("*.py"):
            text = path.read_text(encoding="utf-8", errors="ignore")
            count = len(_RAW_TABLE_PATTERN.findall(text))
            if count:
                hits[str(path.relative_to(_REPO_ROOT))] = count
    return hits


def test_every_raw_market_data_ohlcv_reference_is_on_the_allow_list():
    hits = _find_raw_table_references()
    unexpected = set(hits) - set(_ALLOW_LIST)
    assert not unexpected, (
        f"New raw `market_data_ohlcv` read(s) found, not on the allow-list: {unexpected}. "
        "If this is a genuine new call site, either point it at "
        "`market_data_ohlcv_tradeable` (preferred, if it needs tradeable bars only) or add "
        "it to _ALLOW_LIST in this file with a one-line reason (if it genuinely needs the "
        "full calendar grid)."
    )


def test_allow_list_has_no_stale_entries():
    hits = _find_raw_table_references()
    stale = set(_ALLOW_LIST) - set(hits)
    assert not stale, (
        f"Allow-list entries that no longer match any raw `market_data_ohlcv` reference: "
        f"{stale}. Either the file was fixed (remove its entry here) or moved/renamed "
        "(update the path)."
    )
```

- [ ] **Step 2: Run the test**

Run: `.venv/bin/pytest tests/unit/test_market_data_ohlcv_boundary.py -v`
Expected: `2 passed`. If `test_every_raw_market_data_ohlcv_reference_is_on_the_allow_list`
fails listing `services/cross_sectional_regime_model.py` or `services/counterfactual_tracker.py`,
Tasks 2/3 weren't actually applied yet — go back and confirm those commits landed first.

- [ ] **Step 3: Commit**

```bash
git add tests/unit/test_market_data_ohlcv_boundary.py
git commit -m "test: CI guard against new unfiltered market_data_ohlcv reads"
```

---

### Task 5: Documentation — CLAUDE.md gotcha line and methodology-change-ledger entry

**Files:**
- Modify: `CLAUDE.md` (Core Runtime Files section, near the existing
  `Instrument asset class filter` bullet)
- Modify: `docs/plans/methodology-change-ledger.md` (append new entry)

**Interfaces:** None — documentation only.

- [ ] **Step 1: Add the CLAUDE.md gotcha line**

In `CLAUDE.md`, in the `## Core Runtime Files` section, immediately after the existing line:

```
- **Instrument asset class filter:** `instruments.contract_details->>'asset_class'` — values: `'equity'` (ETFs), `'futures'`, `'fx'`. No top-level column. Use `is_active = true AND contract_details->>'asset_class' = 'equity'` to target ETFs only.
```

insert:

```
- **`market_data_ohlcv` reads for compute/measurement:** use `market_data_ohlcv_tradeable` (a view, `WHERE volume > 0`), not the raw table — `market_data_ohlcv` is a continuous calendar grid containing synthetic-fill and IBKR flat-carry-forward placeholder bars (~82% of intraday rows). Raw-table access outside this needs a `tests/unit/test_market_data_ohlcv_boundary.py` allow-list entry with a reason; CI fails otherwise.
```

- [ ] **Step 2: Append the methodology-change-ledger entry**

At the end of `docs/plans/methodology-change-ledger.md`, append:

```markdown

## 2026-07-16 — `market_data_ohlcv` tradeable-bars filtering added to three zero-filter regime/counterfactual/OOS-eval reads

**What result was observed before the change?** `services/cross_sectional_regime_model.py`
(the live Phase 144 cross-sectional regime writer, feeding `market_regimes`, which `ic_engine`
stratifies IC on), `services/counterfactual_tracker.py` (feeding `alpha_frames`'
true-range/MFE/MAE/exit-determination, Phase 142B), and `scripts/ops/corpus/ops_oos_holdout_eval.py`
(a live diagnostic reading `m.open` for OOS feature-IC scoring, found via a CI-guard regex
widening mid-implementation — its JOIN-based read was invisible to the guard's first draft,
which only matched `FROM`) all read `market_data_ohlcv` with zero filtering of placeholder bars.
~82% of intraday / ~32% of daily rows in the live corpus are `volume=0` (synthetic-fill or IBKR
flat-carry-forward). Every regime label, every counterfactual PnL/MFE/MAE, and every OOS
feature-IC score computed by these three files, for the entire corpus history to date, was
computed over this contaminated input.

**What changed?** All three files now read from a new `market_data_ohlcv_tradeable` view
(`WHERE volume > 0`, migration 236) instead of the raw table. No other files' filtering changed
— `regime_writer.py`/`forward_return_writer.py`/`backfill_feature_factory.py` already used
`volume > 0` inline and were confirmed correct by the same audit (see
`docs/plans/2026-07-16-market-data-ohlcv-active-bars-boundary-design.md`), not touched.
`services/bar_auditor.py` and `scripts/debug/analysis/debug_batch_agent_memory.py` also read the
raw table via JOIN, found by the same regex-widening pass, but are correctly left unfiltered
(gap-detection auditor that needs the full calendar grid; dead v2.x code respectively) — allow-listed,
not changed.

**What would the change have looked like if decided *before* seeing any data (pre-registered
justification), and honestly, was it?** This is a straightforward bug fix (missing filter, not
a re-derived threshold or a re-fit gate) — the pre-registered justification is simply "readers
must not see calendar-filler bars," a data-quality invariant this project already committed to
elsewhere (`regime_writer.py`, `forward_return_writer.py`) before this fix existed. It was not
decided in response to observing any specific IC/regime result; it was found by an unrelated
scoping pass (todo 035) and confirmed via direct inspection of the two files' SQL, not by
noticing an anomalous downstream number. Honestly pre-registered in that sense, though the
underlying gap had existed, undetected, since each file's creation.

**Consumer note:** the in-flight 143.1-07 corpus rebuild already executed
`cross_sectional_regime_model.py` for its current cycle before this fix landed — its regime
labels are pre-fix. This fix applies cleanly starting with the next corpus rebuild; no
retroactive correction of the in-flight run's regime labels was attempted or is possible without
re-running that step. `ops_oos_holdout_eval.py` is a manually-invoked diagnostic (not part of the
automated corpus pipeline), so any future run of it will use the corrected view immediately.
```

- [ ] **Step 3: Commit**

```bash
git add CLAUDE.md docs/plans/methodology-change-ledger.md
git commit -m "docs: record market_data_ohlcv_tradeable fix in methodology-change-ledger, add CLAUDE.md gotcha"
```

---

### Task 6: Todo hygiene — close 035, file the Tier-2 follow-up, update PRIORITIES.md

**Files:**
- Modify: `.planning/todos/pending/035-market-ohlcv-active-bars-view.md` → move to
  `.planning/todos/completed/035-market-ohlcv-active-bars-view.md`
- Create: `.planning/todos/pending/124-market-ohlcv-tradeable-view-tier2-audit.md`
- Modify: `.planning/todos/PRIORITIES.md`

**Interfaces:** None — planning-doc hygiene only.

- [ ] **Step 1: Move todo 035 to completed, with a resolution note**

Read `.planning/todos/pending/035-market-ohlcv-active-bars-view.md` first (for its exact current
frontmatter), then move it with `git mv .planning/todos/pending/035-market-ohlcv-active-bars-view.md
.planning/todos/completed/035-market-ohlcv-active-bars-view.md`, update its frontmatter
`status: pending` → `status: completed` and add a `closed: 2026-07-16` field, and append:

```markdown

## Resolution (2026-07-16)

Closed via `docs/plans/2026-07-16-market-data-ohlcv-active-bars-boundary-design.md` +
`docs/plans/2026-07-16-market-data-ohlcv-tradeable-boundary-plan.md`. Built the single-boundary
view this todo asked for (`market_data_ohlcv_tradeable`, migration 236), fixed the 3 live
call sites that had zero filtering (`cross_sectional_regime_model.py`, `counterfactual_tracker.py`
— a bigger, previously-undiscovered instance of this exact gap, found while scoping this todo —
plus `ops_oos_holdout_eval.py`, found mid-implementation when the CI guard's regex was widened
to also catch `JOIN`, not just `FROM`), and added a CI-enforced allow-list test
(`tests/unit/test_market_data_ohlcv_boundary.py`) so a future call site can't silently
reintroduce it. `bar_auditor.py` and `debug_batch_agent_memory.py` were also found by the same
regex-widening and correctly allow-listed (legitimate full-grid gap auditor; dead v2.x code).
The 3 files already using `volume > 0` correctly, plus 10 not-yet-classified files, are follow-up
todo 124 — not fixed here.
```

- [ ] **Step 2: File the Tier-2 follow-up todo**

```markdown
---
status: pending
priority: P3
filed: 2026-07-16
source: split from todo 035's full-tree audit (docs/plans/2026-07-16-market-data-ohlcv-active-bars-boundary-design.md)
---

# 124 — `market_data_ohlcv_tradeable` view: Tier-2 file audit

## Problem

Todo 035 closed by fixing the 2 live call sites with zero placeholder-bar filtering
(`cross_sectional_regime_model.py`, `counterfactual_tracker.py`) and building
`market_data_ohlcv_tradeable` as the single boundary. 13 more files reference the raw table and
were deliberately not touched in that pass (see the design doc's "not yet classified" and
"already correctly filtered" lists) — each needs a genuine per-file judgment call on whether it
should migrate to the view, and 3 of them (`regime_writer.py`, `forward_return_writer.py`,
`backfill_feature_factory.py`) are already filtering correctly with an inline `volume > 0` and
would only gain a style/DRY benefit, not a correctness fix, from switching.

## Not yet done

For each of the 13 files listed in `tests/unit/test_market_data_ohlcv_boundary.py`'s
`_ALLOW_LIST` with a "Tier-2" or "not yet classified" reason: read the call site, determine
whether it needs tradeable-only bars or genuinely wants the full calendar grid (e.g. backfill
completeness checks may intentionally count against the full grid), migrate to
`market_data_ohlcv_tradeable` where appropriate, and remove its entry from the allow-list.

## References

- `docs/plans/2026-07-16-market-data-ohlcv-active-bars-boundary-design.md` — full audit,
  per-file classification as of 2026-07-16
- `tests/unit/test_market_data_ohlcv_boundary.py` — the allow-list to shrink as files are
  reviewed
- `.planning/todos/completed/035-market-ohlcv-active-bars-view.md` — closed todo this splits from
```

Save as `.planning/todos/pending/124-market-ohlcv-tradeable-view-tier2-audit.md`.

- [ ] **Step 3: Update PRIORITIES.md**

In `.planning/todos/PRIORITIES.md`'s P3 table, replace the existing `035` row:

```
| [035](pending/035-market-ohlcv-active-bars-view.md) | `market_data_ohlcv` active-bars filter belongs at one boundary, not 4 call sites |
```

with:

```
| [124](pending/124-market-ohlcv-tradeable-view-tier2-audit.md) | Tier-2 follow-up: 13 remaining `market_data_ohlcv` call sites to classify/migrate to `market_data_ohlcv_tradeable`, split from closed todo 035 |
```

and add a line to the "Closed 2026-07-16" note (already present from the earlier 059/060/104
cleanup this session) noting 035's closure too:

```
**Closed 2026-07-16:** 059 (AegisAgent/TradeAgent reuse review), 060 (Cluster 2 legacy intel docs
review — also resolved catalog.md's process-conflict flag; one gap spun out as todo 123 above),
104 (quarterly-seasonality/OPEX Fable review, already closed 2026-07-13 as part of the Calendar
Primitives doc — this table just hadn't been updated to reflect it), 035 (market_data_ohlcv
active-bars view — built as market_data_ohlcv_tradeable, migration 236; Tier-2 remainder split
to todo 124).
```

- [ ] **Step 4: Commit**

```bash
git add .planning/todos/completed/035-market-ohlcv-active-bars-view.md .planning/todos/pending/124-market-ohlcv-tradeable-view-tier2-audit.md .planning/todos/PRIORITIES.md
git commit -m "docs(todos): close 035, split Tier-2 remainder into todo 124"
```

---

### Task 7: Full-suite verification, `/simplify`, `/review`

**Files:** None new — this is the Done-Coding SOP's mandatory closing gate (CLAUDE.md).

- [ ] **Step 1: Run `/simplify` on the changed code**

Invoke the `/simplify` skill over the diff from Tasks 1-4 (migration SQL, the two service-file
query changes, the two new test files).

- [ ] **Step 2: Run `/review` for a peer code review pass**

Invoke the `/code-review` skill over the same diff.

- [ ] **Step 3: Run the full unit suite**

Run: `.venv/bin/pytest tests/unit/ -q`
Expected: all tests pass, no new failures introduced (the pre-existing unrelated
`test_no_smooth_or_backward_in_factory` failure, if still present, is not this plan's concern).

- [ ] **Step 4: Run the integration suite**

Run: `.venv/bin/pytest tests/integration/ -q`
Expected: all tests pass, including the new `test_market_data_ohlcv_tradeable_view.py`.

- [ ] **Step 5: Merge to main per CLAUDE.md's Done-Coding SOP**

```bash
git checkout main
git merge --ff-only <feature-branch>
git branch -d <feature-branch>
git worktree prune
```

(Do not push to `origin/main` without separate confirmation — pushing is a shared-state action
outside this plan's scope.)
