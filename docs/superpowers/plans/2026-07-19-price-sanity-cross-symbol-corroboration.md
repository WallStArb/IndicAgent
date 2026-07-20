# Price-Sanity Cross-Symbol Corroboration (todos 152 + 151) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix todo 152 — the `return_{scale}_suspect` price-sanity guard (todo 148) currently
flags real, documented crisis events (May 6 2010 Flash Crash, Aug 24 2015 ETF flash crash, 2008
Lehman-aftermath `KRE` volatility) as corrupt because its magnitude-only ceiling can't
distinguish them from genuine bad prints (`UUP`/`XRT`/`VWO`). Add a cross-symbol corroboration
check: if `alpha.quant.cross_symbol_corroboration.min_symbols` (default 4, i.e. the subject
symbol + >=3 others) show a similarly extreme move at the identical `(tf, bar_ts)`, treat it as
a real market-wide event, not corruption. Apply the same signal to unblock todo 151's corrupt-
print cleanup tooling, whose CONFIRMED_CORRUPT bucket is contaminated with the same Flash Crash
rows (`CWB`/`RSP`/`VTV`/`VYM`) for the identical reason — its single-symbol neighbor-agreement
check can't tell a genuine V-shaped flash-crash recovery from an isolated bad print either.

**Architecture:** Both fixes reuse the same underlying signal (count of other symbols showing an
implausible move at the same timestamp) and the same APR threshold, but each implements its own
SQL against its own data model: 152 self-joins the already-computed `forward_returns` table (a
bulk corrective `UPDATE`, since forward_returns rows already exist and are idempotent-insert
under `ON CONFLICT DO NOTHING`); 151 queries `market_data_ohlcv_tradeable` directly for other
symbols' bars at the exact candidate timestamp and reuses the existing
`classify_candidate_bar()` function symmetrically (each neighbor symbol classified against its
own prev/next reference, exactly as the subject row was).

**Tech Stack:** Python 3.14, psycopg2 (forward_return_writer.py, sync), asyncpg
(ops_known_corrupt_print_cleanup.py, async), PostgreSQL/TimescaleDB, pytest.

## Global Constraints

- All timestamps UTC (`datetime.now(UTC)` only) — not touched by this plan (no new timestamp
  construction), but any test fixtures must use timezone-aware UTC datetimes.
- New tunable numeric values go through the Adaptive Parameter Registry — no hard-coded
  thresholds. `alpha.quant.cross_symbol_corroboration.min_symbols` is the one new parameter this
  plan introduces; both scripts read it via `cfg.get_sync()` / `cfg()`, never a module constant
  used directly in logic.
- Never log per-row inside a loop over the full corpus — corroboration results are logged once
  per run as an aggregate dict, not per (symbol, tf, bar_ts).
- Exception variable name is `error`, not `exc`.
- `ops_known_corrupt_print_cleanup.py --apply` mutates live production OHLCV data (volume=0
  correction) and is explicitly gated on human review per its own module docstring — this plan
  does NOT execute `--apply` as an automated step. Task 9 stops at the dry-run report.

---

## File Structure

- **Modify:** `services/forward_return_writer.py` — new `_build_corroboration_sql()`,
  `_apply_cross_symbol_corroboration()`, `--reclassify-suspect-only` CLI flag, wiring in `_run()`.
- **Modify:** `tests/unit/test_forward_return_writer.py` — SQL-shape + fake-conn tests for the
  above.
- **Create:** `production/migrations/240_cross_symbol_corroboration_apr_key.sql` — seeds
  `alpha.quant.cross_symbol_corroboration.min_symbols`.
- **Modify:** `scripts/ops/corpus/ops_known_corrupt_print_cleanup.py` — new `MARKET_EVENT`
  verdict, `count_corroborating_symbols()`, `apply_cross_symbol_downgrade()`, wiring in
  `_scan_and_classify()`, `render_dry_run_report()` MARKET_EVENT section.
- **Modify:** `tests/unit/test_known_corrupt_print_cleanup.py` — pure-logic tests for
  `apply_cross_symbol_downgrade()`.

---

### Task 1: APR migration for the cross-symbol corroboration threshold

**Files:**
- Create: `production/migrations/240_cross_symbol_corroboration_apr_key.sql`

**Interfaces:**
- Produces: APR key `alpha.quant.cross_symbol_corroboration.min_symbols` (int, default `4`),
  readable via `cfg.get_sync(...)` (sync) or `cfg(cfg_dict, ..., 4)` (async dict form) by both
  later tasks.

- [ ] **Step 1: Write the migration**

```sql
-- Migration 240: alpha.quant.cross_symbol_corroboration.min_symbols APR key (todo 152)
--
-- Todo 148's return_{scale}_suspect guard flags any return whose magnitude exceeds a
-- per-tf ceiling as suspect, excluding it from mean-based consumers. Investigating all
-- 76 currently-flagged rows against actual market history found two conflated
-- populations: genuine corrupt IBKR prints (UUP/XRT/VWO -- no economic basis) and real,
-- documented crisis events (the May 6 2010 Flash Crash across CWB/ITA/RSP/VTV/VUG/VYM,
-- the Aug 24 2015 ETF flash crash, 2008 Lehman-aftermath KRE volatility) that were
-- silently excluded from mean-based consumers -- a real defect per this project's
-- Renaissance data-retention principle ("never drop data that could contain signal"),
-- not a conservative default.
--
-- A magnitude-only ceiling structurally cannot make this distinction: a real Flash
-- Crash return and a fabricated $1000-print return can share the same magnitude. The
-- distinguishing signal is cross-symbol simultaneity -- corruption doesn't hit N
-- unrelated symbols at the identical historical minute; a market-wide liquidity vacuum
-- does. This key is the minimum distinct-symbol count (INCLUDING the subject symbol
-- itself) required at an identical (tf, bar_ts) to treat a flagged move as a
-- corroborated market event rather than a corrupt print.
--
-- Seed 4 is [initial_estimate]: the confirmed Flash Crash cluster hit 6 unrelated ETFs
-- simultaneously (well clear of this floor); the confirmed isolated corrupt prints
-- (UUP/XRT/VWO) each affected exactly 1 symbol. A floor of 4 (self + 3 others) sits
-- comfortably between those two populations with no known borderline case. Shared by
-- both todo 152 (services/forward_return_writer.py, corrective UPDATE on
-- forward_returns.return_{scale}_suspect) and todo 151
-- (scripts/ops/corpus/ops_known_corrupt_print_cleanup.py, CONFIRMED_CORRUPT ->
-- MARKET_EVENT downgrade) -- same underlying signal, two different data models. Not an
-- ML learning target.

BEGIN;

INSERT INTO config_schema (config_key, value_type, default_value, min_value, max_value, description)
VALUES
(
    'alpha.quant.cross_symbol_corroboration.min_symbols',
    'int',
    '4',
    2, 20,
    '[initial_estimate] Minimum distinct symbols (including the subject itself) showing '
    'an implausible move at the identical (tf, bar_ts) to treat a price-sanity-flagged '
    'return as a corroborated real market event (Flash Crash, ETF flash crash) rather '
    'than a corrupt print (todo 152). Used by services/forward_return_writer.py (clears '
    'return_{scale}_suspect) and scripts/ops/corpus/ops_known_corrupt_print_cleanup.py '
    '(downgrades CONFIRMED_CORRUPT to MARKET_EVENT). Not an ML learning target.'
)
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_state (config_key, config_value, version)
VALUES
    ('alpha.quant.cross_symbol_corroboration.min_symbols', '4', 1)
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_history (timestamp, config_key, version, config_value, changed_by, reason)
VALUES
    (NOW(), 'alpha.quant.cross_symbol_corroboration.min_symbols', 1, '4', 'migration_240',
     'Seed cross-symbol corroboration threshold, todo 152 [initial_estimate]')
ON CONFLICT DO NOTHING;

COMMIT;
```

- [ ] **Step 2: Apply the migration**

Run: `PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -f production/migrations/240_cross_symbol_corroboration_apr_key.sql`
Expected: `BEGIN` / two `INSERT 0 1` (or `INSERT 0 0` on rerun) / `COMMIT`, no errors.

- [ ] **Step 3: Verify the key is live**

Run: `PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -c "SELECT config_key, config_value FROM config_state WHERE config_key = 'alpha.quant.cross_symbol_corroboration.min_symbols';"`
Expected: one row, `config_value = 4`.

- [ ] **Step 4: Commit**

```bash
git add production/migrations/240_cross_symbol_corroboration_apr_key.sql
git commit -m "feat(todo-152): seed cross-symbol corroboration min_symbols APR key"
```

---

### Task 2: `forward_return_writer.py` — cross-symbol corroboration corrective pass

**Files:**
- Modify: `services/forward_return_writer.py`

**Interfaces:**
- Consumes: `_SCALES: tuple[str, ...]` (existing module constant), `observed_span` (existing
  import), `_logger` (existing module logger).
- Produces: `_build_corroboration_sql(scale: str) -> str`,
  `_apply_cross_symbol_corroboration(conn: Any, scales: tuple[str, ...], min_symbols: int, tracer: Any) -> dict[str, int]`
  (returns `{scale: n_rows_cleared}`) — both importable by tests and by task 3.

- [ ] **Step 1: Write the failing tests**

Add to `tests/unit/test_forward_return_writer.py` (append after the existing suspect-flag tests,
before the `_mock_conn_with_precheck_result` helper):

```python
def test_corroboration_sql_targets_correct_suspect_column():
    """Each scale's corroboration UPDATE must target its OWN return_{scale}_suspect
    column -- a corroboration event on return_fast must not accidentally clear
    return_slow_suspect for the same row (the two scales can have independent
    plausibility verdicts, same as todo 148's original per-scale design)."""
    for scale in ("fast", "mid", "slow", "extended"):
        sql = _build_corroboration_sql(scale)
        assert sql.count(f"return_{scale}_suspect") >= 3  # HAVING gate, SET, WHERE
        for other in ("fast", "mid", "slow", "extended"):
            if other != scale:
                assert f"return_{other}_suspect" not in sql


def test_corroboration_sql_groups_by_tf_and_bar_ts():
    """Corroboration is per (tf, bar_ts) -- a 5m bar and a 1h bar at an overlapping
    wall-clock instant must not cross-contaminate each other's symbol count."""
    sql = _build_corroboration_sql("fast")
    assert "GROUP BY tf, bar_ts" in sql
    assert "count(DISTINCT symbol)" in sql


def test_corroboration_sql_scoped_to_executable_return_type():
    sql = _build_corroboration_sql("fast")
    assert sql.count("executable_open_to_open") >= 2  # CTE filter + UPDATE filter


def _mock_conn_for_corroboration(rowcounts: dict[str, int]) -> MagicMock:
    """A conn whose cursor.rowcount cycles through rowcounts[scale] in call order."""
    cur = MagicMock()
    cur.__enter__.return_value = cur
    cur.__exit__.return_value = False
    rowcount_iter = iter(rowcounts.values())

    def _execute(*_args, **_kwargs):
        cur.rowcount = next(rowcount_iter)

    cur.execute.side_effect = _execute
    conn = MagicMock()
    conn.cursor.return_value = cur
    return conn


def test_apply_cross_symbol_corroboration_returns_cleared_counts_per_scale():
    conn = _mock_conn_for_corroboration({"fast": 0, "mid": 2, "slow": 4, "extended": 0})
    tracer = MagicMock()

    cleared = _apply_cross_symbol_corroboration(
        conn, _SCALES, min_symbols=4, tracer=tracer
    )

    assert cleared == {"fast": 0, "mid": 2, "slow": 4, "extended": 0}
    conn.commit.assert_called_once()


def test_apply_cross_symbol_corroboration_passes_min_symbols_param():
    conn = _mock_conn_for_corroboration({"fast": 0, "mid": 0, "slow": 0, "extended": 0})
    tracer = MagicMock()

    _apply_cross_symbol_corroboration(conn, _SCALES, min_symbols=7, tracer=tracer)

    for call in conn.cursor.return_value.execute.call_args_list:
        params = call.args[1]
        assert params["min_symbols"] == 7
```

Also update the existing import line near the top of the test file:

```python
from services.forward_return_writer import (
    _apply_cross_symbol_corroboration,
    _build_corroboration_sql,
    _build_forward_return_sql,
    _build_insert_sql,
    _emit_price_sanity_fact,
    _SCALES,
    forward_log_return,
)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/unit/test_forward_return_writer.py -v -k corroboration`
Expected: FAIL with `ImportError: cannot import name '_build_corroboration_sql'` (function does
not exist yet).

- [ ] **Step 3: Implement `_build_corroboration_sql` and `_apply_cross_symbol_corroboration`**

Insert into `services/forward_return_writer.py` immediately after `_build_insert_sql` (after the
line `ON CONFLICT (symbol, tf, bar_ts) DO NOTHING\n"""` block, before the
`# Symbol discovery` section comment at line ~342):

```python
# ---------------------------------------------------------------------------
# Cross-symbol corroboration (todo 152)
# ---------------------------------------------------------------------------


def _build_corroboration_sql(scale: str) -> str:
    """UPDATE clearing return_{scale}_suspect where >= min_symbols distinct symbols are
    ALSO flagged suspect at the identical (tf, bar_ts) -- corruption doesn't hit N
    unrelated symbols at the same historical minute; a real market-wide event (the May
    6 2010 Flash Crash hit 6 unrelated ETFs in the same 40-minute window) does.

    Bounded to already-suspect rows only (self-join CTE grouped by (tf, bar_ts), never
    a full-corpus scan) -- cheap enough to run unconditionally on every invocation,
    which is what re-flags rows written by PRIOR runs too (todo 152's sizing note: "a
    corrective UPDATE, not a new migration").
    """
    col = f"return_{scale}_suspect"
    return f"""
WITH corroborated_windows AS (
    SELECT tf, bar_ts
    FROM forward_returns
    WHERE return_type = 'executable_open_to_open'
      AND {col} = true
    GROUP BY tf, bar_ts
    HAVING count(DISTINCT symbol) >= %(min_symbols)s
)
UPDATE forward_returns fr
SET {col} = false
FROM corroborated_windows cw
WHERE fr.tf = cw.tf
  AND fr.bar_ts = cw.bar_ts
  AND fr.return_type = 'executable_open_to_open'
  AND fr.{col} = true
"""


def _apply_cross_symbol_corroboration(
    conn: Any, scales: tuple[str, ...], min_symbols: int, tracer: Any
) -> dict[str, int]:
    """Clear return_{scale}_suspect for rows corroborated by >= min_symbols distinct
    symbols at the identical (tf, bar_ts) -- todo 152. Runs once per invocation, after
    the full symbol/tf loop, over the WHOLE forward_returns table (not scoped to this
    run's --symbols) so historical suspect rows from prior runs get corrected too.

    Returns {scale: n_rows_cleared} -- logged once as an aggregate, never per-row
    (CLAUDE.md: never log per-row inside a corpus-scale loop).
    """
    with observed_span("forward_return_writer.cross_symbol_corroboration", tracer):
        cleared: dict[str, int] = {}
        for scale in scales:
            sql = _build_corroboration_sql(scale)
            with conn.cursor() as cur:
                cur.execute(sql, {"min_symbols": min_symbols})
                cleared[scale] = cur.rowcount
        conn.commit()
        _logger.info(
            "forward_return_writer.cross_symbol_corroboration_applied",
            min_symbols=min_symbols,
            cleared=cleared,
        )
        return cleared
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/unit/test_forward_return_writer.py -v -k corroboration`
Expected: 6 passed.

- [ ] **Step 5: Wire into `_run()` and add `--reclassify-suspect-only` CLI flag**

In `main()` (around line 548-558), change the `--training-window-end` argument's `required=True`
to `required=False` and add the new flag, then validate manually:

```python
    parser.add_argument("--symbols", nargs="*", default=None)
    parser.add_argument("--tf", nargs="*", choices=_DEFAULT_TFS, default=_DEFAULT_TFS)
    parser.add_argument(
        "--training-window-end",
        default=None,
        required=False,
        help="Explicit training window end (ISO 8601, timezone-aware/UTC) -- the OOS "
        "holdout clamp (LEAST(MAX(bar_ts), alpha.validation.oos_start)). No default: a "
        "bare MAX(bar_ts) fallback would silently consume the OOS holdout window "
        "(Phase 141.1 CR-01/IN-02). See docs/plans/OOS-EVAL-PROTOCOL.md. REQUIRED unless "
        "--reclassify-suspect-only is set.",
    )
    parser.add_argument(
        "--reclassify-suspect-only",
        action="store_true",
        default=False,
        help="Skip the full forward-return computation loop; only run the cross-symbol "
        "corroboration corrective pass (todo 152) against existing forward_returns "
        "rows. Does not require --training-window-end.",
    )
    args = parser.parse_args()
    if not args.reclassify_suspect_only and args.training_window_end is None:
        parser.error(
            "--training-window-end is required unless --reclassify-suspect-only is set."
        )
```

Then in `_run()`, immediately after `cfg = _load_config_service(conn)` (around line 579),
insert the early-exit branch:

```python
                cfg = _load_config_service(conn)

                min_corroborating_symbols = int(
                    cfg.get_sync("alpha.quant.cross_symbol_corroboration.min_symbols", 4)
                )

                if args.reclassify_suspect_only:
                    cleared = _apply_cross_symbol_corroboration(
                        conn, _SCALES, min_corroborating_symbols, tracer
                    )
                    _logger.info(
                        "forward_return_writer.reclassify_suspect_only_complete",
                        cleared=cleared,
                    )
                    return

                batch_size = int(
```

(The existing `batch_size = int(...)` line right after `cfg = _load_config_service(conn)`
becomes the line immediately following this insertion — the rest of the existing function body
is unchanged.)

Finally, call the corroboration pass at the end of the normal (non-reclassify-only) path too —
insert right after the existing `_emit_price_sanity_fact(conn, total_suspect, training_window_end)`
call (around line 693):

```python
                _emit_price_sanity_fact(conn, total_suspect, training_window_end)

                cleared = _apply_cross_symbol_corroboration(
                    conn, _SCALES, min_corroborating_symbols, tracer
                )
```

And add `cleared=cleared` to the existing `forward_return_writer.run_complete` log call's
keyword arguments (right after `failed_cells=failures,`).

- [ ] **Step 6: Run the full test file**

Run: `.venv/bin/pytest tests/unit/test_forward_return_writer.py -v`
Expected: all tests pass (existing + 6 new).

- [ ] **Step 7: Commit**

```bash
git add services/forward_return_writer.py tests/unit/test_forward_return_writer.py
git commit -m "feat(todo-152): cross-symbol corroboration for return_suspect false positives"
```

---

### Task 3: Run the corrective pass against the live database

**Files:** none (operational step — no code change)

- [ ] **Step 1: Dry check the current suspect count**

Run: `PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -c "SELECT tf, count(*) FROM forward_returns WHERE return_type='executable_open_to_open' AND (return_fast_suspect OR return_mid_suspect OR return_slow_suspect OR return_extended_suspect) GROUP BY tf;"`
Expected: nonzero counts, matching the ~76-row figure from todo 152's investigation (may drift
slightly with any backfill since 2026-07-19).

- [ ] **Step 2: Run the corrective pass**

Run: `python services/forward_return_writer.py --reclassify-suspect-only`
Expected: exit 0; log line `forward_return_writer.reclassify_suspect_only_complete` with
`cleared` counts per scale — nonzero for scales covering the Flash Crash / Aug 2015 / KRE
windows, zero is also possible if none of those specific rows carry that scale's suspect flag.

- [ ] **Step 3: Verify the known Flash Crash symbols are no longer suspect**

Run: `PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -c "SELECT symbol, tf, bar_ts, return_fast_suspect, return_mid_suspect, return_slow_suspect, return_extended_suspect FROM forward_returns WHERE symbol IN ('CWB','ITA','RSP','VTV','VUG','VYM') AND bar_ts BETWEEN '2010-05-06 17:00' AND '2010-05-06 19:00' AND (return_fast_suspect OR return_mid_suspect OR return_slow_suspect OR return_extended_suspect);"`
Expected: **zero rows** (all cleared by the corroboration pass).

- [ ] **Step 4: Verify the genuinely corrupt rows are UNCHANGED (still suspect)**

Run: `PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -c "SELECT symbol, tf, bar_ts, return_fast_suspect, return_mid_suspect, return_slow_suspect, return_extended_suspect FROM forward_returns WHERE symbol IN ('UUP','XRT','VWO') AND (return_fast_suspect OR return_mid_suspect OR return_slow_suspect OR return_extended_suspect);"`
Expected: rows still present (isolated corruption, no corroborating symbols — must remain
suspect).

---

### Task 4: `ops_known_corrupt_print_cleanup.py` — cross-symbol downgrade to `MARKET_EVENT`

**Files:**
- Modify: `scripts/ops/corpus/ops_known_corrupt_print_cleanup.py`

**Interfaces:**
- Consumes: `classify_candidate_bar()`, `CandidateVerdict` (existing, this file).
- Produces: `count_corroborating_symbols(pool, tf, subject_symbol, timestamp, magnitude_threshold, neighbor_agreement_threshold) -> int`
  (async), `apply_cross_symbol_downgrade(verdict: CandidateVerdict, n_corroborating_symbols: int, min_symbols: int) -> CandidateVerdict`
  (pure) — both used by `_scan_and_classify()`.

- [ ] **Step 1: Write the failing tests**

Add to `tests/unit/test_known_corrupt_print_cleanup.py` (append near the existing
`classify_candidate_bar` tests; check the file's existing import line first and add
`apply_cross_symbol_downgrade` to it):

```python
def test_apply_cross_symbol_downgrade_leaves_non_confirmed_verdicts_unchanged():
    ambiguous = CandidateVerdict(
        verdict="AMBIGUOUS",
        implausible_fields=("open",),
        max_ratio=15.0,
        neighbor_ratio=3.0,
        reason="implausible_but_neighbors_disagree",
    )
    result = apply_cross_symbol_downgrade(ambiguous, n_corroborating_symbols=10, min_symbols=4)
    assert result is ambiguous


def test_apply_cross_symbol_downgrade_below_threshold_stays_confirmed_corrupt():
    confirmed = CandidateVerdict(
        verdict="CONFIRMED_CORRUPT",
        implausible_fields=("open", "high"),
        max_ratio=40.0,
        neighbor_ratio=1.02,
        reason="isolated_spike_neighbors_agree",
    )
    # n_corroborating_symbols=2 other symbols + self = 3, min_symbols=4 -> not enough
    result = apply_cross_symbol_downgrade(confirmed, n_corroborating_symbols=2, min_symbols=4)
    assert result.verdict == "CONFIRMED_CORRUPT"
    assert result is confirmed


def test_apply_cross_symbol_downgrade_at_threshold_becomes_market_event():
    confirmed = CandidateVerdict(
        verdict="CONFIRMED_CORRUPT",
        implausible_fields=("open", "high", "low", "close"),
        max_ratio=142.0,
        neighbor_ratio=1.01,
        reason="isolated_spike_neighbors_agree",
    )
    # n_corroborating_symbols=3 other symbols + self = 4, min_symbols=4 -> corroborated
    result = apply_cross_symbol_downgrade(confirmed, n_corroborating_symbols=3, min_symbols=4)
    assert result.verdict == "MARKET_EVENT"
    assert result.implausible_fields == confirmed.implausible_fields
    assert result.max_ratio == confirmed.max_ratio
    assert "cross_symbol_corroborated_n=4" in result.reason
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/unit/test_known_corrupt_print_cleanup.py -v -k cross_symbol_downgrade`
Expected: FAIL with `ImportError: cannot import name 'apply_cross_symbol_downgrade'`.

- [ ] **Step 3: Implement `apply_cross_symbol_downgrade` and `count_corroborating_symbols`**

First, update the `CandidateVerdict` docstring-comment line (currently
`verdict: str  # "CONFIRMED_CORRUPT" | "AMBIGUOUS" | "PLAUSIBLE"`) to:

```python
    verdict: str  # "CONFIRMED_CORRUPT" | "AMBIGUOUS" | "PLAUSIBLE" | "MARKET_EVENT"
```

Insert the pure downgrade function immediately after `classify_candidate_bar` (after its closing
`)` and before `def build_subject_key`):

```python
def apply_cross_symbol_downgrade(
    verdict: CandidateVerdict, n_corroborating_symbols: int, min_symbols: int
) -> CandidateVerdict:
    """Downgrade CONFIRMED_CORRUPT -> MARKET_EVENT when the subject symbol plus
    n_corroborating_symbols OTHER symbols (total >= min_symbols) show a similarly
    implausible move at the identical (tf, timestamp) -- todo 152's cross-symbol
    corroboration signal applied to todo 151's classification. classify_candidate_bar's
    single-symbol neighbor-agreement check cannot distinguish a genuine V-shaped
    flash-crash recovery from an isolated bad print (both show "isolated spike,
    neighbors agree"); this is the missing signal. Only CONFIRMED_CORRUPT is checked --
    AMBIGUOUS/PLAUSIBLE never reach --apply regardless, so spending a corroboration
    query on them has no effect on the outcome.
    """
    if verdict.verdict != "CONFIRMED_CORRUPT":
        return verdict
    total_symbols = n_corroborating_symbols + 1
    if total_symbols < min_symbols:
        return verdict
    return CandidateVerdict(
        verdict="MARKET_EVENT",
        implausible_fields=verdict.implausible_fields,
        max_ratio=verdict.max_ratio,
        neighbor_ratio=verdict.neighbor_ratio,
        reason=f"cross_symbol_corroborated_n={total_symbols}",
    )
```

Add the async DB-touching corroboration query. Insert it in the "DB-touching steps" section,
immediately before `_scan_and_classify` (after the `_NEIGHBOR_SCAN_SQL` module constant and
`_LATEST_TRAINING_WINDOW_END_SQL`, before `def render_dry_run_report`... actually place it in
the DB-touching section since it's `async`, right before `async def _scan_and_classify`):

```python
_CROSS_SYMBOL_NEIGHBOR_SQL = """
    WITH neighbors AS (
        SELECT
            symbol, timestamp, open, high, low, close,
            LAG(close) OVER w AS prev_close,
            LEAD(open) OVER w AS next_open
        FROM market_data_ohlcv_tradeable
        WHERE timeframe = $1
          AND symbol != $2
          AND timestamp BETWEEN $3::timestamptz - INTERVAL '7 days'
                             AND $3::timestamptz + INTERVAL '7 days'
        WINDOW w AS (PARTITION BY symbol ORDER BY timestamp)
    )
    SELECT symbol, open, high, low, close, prev_close, next_open
    FROM neighbors
    WHERE timestamp = $3
"""


async def count_corroborating_symbols(
    pool: asyncpg.Pool,
    tf: str,
    subject_symbol: str,
    timestamp: Any,
    magnitude_threshold: float,
    neighbor_agreement_threshold: float,
) -> int:
    """Count OTHER symbols with an implausible bar (per classify_candidate_bar, same
    thresholds) at the exact same (tf, timestamp) as a CONFIRMED_CORRUPT candidate --
    todo 152's signal, reused here so a genuine market-wide event isn't misclassified.
    Each neighbor symbol is classified against ITS OWN prev/next reference, exactly as
    the subject row was -- symmetric reuse of classify_candidate_bar, no new
    classification logic. The +/-7 day window is generous slack for LAG/LEAD accuracy
    across weekends/holidays on 1d bars; cheap since this only runs per CONFIRMED_CORRUPT
    candidate (~27 total), not per-row over the corpus.
    """
    rows = await pool.fetch(_CROSS_SYMBOL_NEIGHBOR_SQL, tf, subject_symbol, timestamp)
    n_corroborating = 0
    for r in rows:
        neighbor_verdict = classify_candidate_bar(
            open_=float(r["open"]),
            high=float(r["high"]),
            low=float(r["low"]),
            close=float(r["close"]),
            prev_close=float(r["prev_close"]) if r["prev_close"] is not None else None,
            next_open=float(r["next_open"]) if r["next_open"] is not None else None,
            magnitude_threshold=magnitude_threshold,
            neighbor_agreement_threshold=neighbor_agreement_threshold,
        )
        if neighbor_verdict.verdict != "PLAUSIBLE":
            n_corroborating += 1
    return n_corroborating
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/unit/test_known_corrupt_print_cleanup.py -v -k cross_symbol_downgrade`
Expected: 3 passed.

- [ ] **Step 5: Wire into `_scan_and_classify` and load `min_symbols` in `_run`**

Modify `_scan_and_classify`'s signature and body (add `min_symbols` param, apply the downgrade
after computing `verdict`, before the `if verdict.verdict == "PLAUSIBLE": continue` check):

```python
async def _scan_and_classify(
    pool: asyncpg.Pool,
    symbol: str,
    tf: str,
    magnitude_threshold: float,
    neighbor_agreement_threshold: float,
    min_corroborating_symbols: int,
) -> list[CandidateRow]:
    rows = await pool.fetch(_NEIGHBOR_SCAN_SQL, symbol, tf)
    results: list[CandidateRow] = []
    for r in rows:
        verdict = classify_candidate_bar(
            open_=float(r["open"]),
            high=float(r["high"]),
            low=float(r["low"]),
            close=float(r["close"]),
            prev_close=float(r["prev_close"]) if r["prev_close"] is not None else None,
            next_open=float(r["next_open"]) if r["next_open"] is not None else None,
            magnitude_threshold=magnitude_threshold,
            neighbor_agreement_threshold=neighbor_agreement_threshold,
        )
        if verdict.verdict == "CONFIRMED_CORRUPT":
            n_corroborating = await count_corroborating_symbols(
                pool,
                tf,
                symbol,
                r["timestamp"],
                magnitude_threshold,
                neighbor_agreement_threshold,
            )
            verdict = apply_cross_symbol_downgrade(
                verdict, n_corroborating, min_corroborating_symbols
            )
        if verdict.verdict == "PLAUSIBLE":
            continue
        results.append(
            CandidateRow(
                symbol=symbol,
                tf=tf,
                timestamp=format_iso_ts(r["timestamp"]),
                open=float(r["open"]),
                high=float(r["high"]),
                low=float(r["low"]),
                close=float(r["close"]),
                volume=float(r["volume"]),
                prev_close=float(r["prev_close"]) if r["prev_close"] is not None else None,
                next_open=float(r["next_open"]) if r["next_open"] is not None else None,
                verdict=verdict,
            )
        )
    return results
```

Update the call site in `_run()` to load and pass `min_corroborating_symbols`. Add the import
(near the top, with the other `services._batch_utils` style imports — this file currently has
none, so add fresh):

```python
from services._batch_utils import load_apr_dict_async, cfg as _cfg
```

In `_run()`, after `pool = await asyncpg.create_pool(dsn=dsn)` and inside the `try:` block,
before the `pairs = await _fetch_candidate_tf_pairs(...)` line:

```python
        apr = await load_apr_dict_async(pool)
        min_corroborating_symbols = int(
            _cfg(apr, "alpha.quant.cross_symbol_corroboration.min_symbols", 4)
        )
```

And update the `_scan_and_classify` call site to pass it through:

```python
            rows = await _scan_and_classify(
                pool, symbol, tf, args.magnitude_threshold, args.neighbor_agreement_threshold,
                min_corroborating_symbols,
            )
```

- [ ] **Step 6: Update `render_dry_run_report` to add a MARKET_EVENT section**

In `render_dry_run_report`, add a `market_event` bucket alongside the existing three:

```python
def render_dry_run_report(rows: list[CandidateRow]) -> str:
    confirmed = [r for r in rows if r.verdict.verdict == "CONFIRMED_CORRUPT"]
    ambiguous = [r for r in rows if r.verdict.verdict == "AMBIGUOUS"]
    plausible = [r for r in rows if r.verdict.verdict == "PLAUSIBLE"]
    market_event = [r for r in rows if r.verdict.verdict == "MARKET_EVENT"]

    lines = [
        "# Known Corrupt OHLCV Print Cleanup -- Dry-Run Report (todo 151)",
        "",
        f"Candidates scanned: {len(rows)}",
        f"CONFIRMED_CORRUPT: {len(confirmed)}",
        f"AMBIGUOUS: {len(ambiguous)}",
        f"MARKET_EVENT (real crisis event, cross-symbol corroborated -- excluded from apply): {len(market_event)}",
        f"PLAUSIBLE (ruled out by neighbor cross-check): {len(plausible)}",
        "",
    ]

    header = (
        "| symbol | tf | timestamp | open | high | low | close | volume | "
        "prev_close | next_open | max_ratio | neighbor_ratio | implausible_fields | reason |"
    )
    divider = "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"

    for group_name, group in (
        ("CONFIRMED_CORRUPT", confirmed),
        ("AMBIGUOUS", ambiguous),
        ("MARKET_EVENT", market_event),
    ):
        lines.append(f"## {group_name} ({len(group)})")
        lines.append("")
        if group:
            lines.append(header)
            lines.append(divider)
            for r in group:
                neighbor_ratio_str = (
                    f"{r.verdict.neighbor_ratio:.3f}"
                    if r.verdict.neighbor_ratio is not None
                    else "n/a"
                )
                lines.append(
                    f"| {r.symbol} | {r.tf} | {r.timestamp} | {r.open} | {r.high} | {r.low} | "
                    f"{r.close} | {r.volume} | {r.prev_close} | {r.next_open} | "
                    f"{r.verdict.max_ratio:.2f} | {neighbor_ratio_str} | "
                    f"{','.join(r.verdict.implausible_fields)} | {r.verdict.reason} |"
                )
        lines.append("")

    return "\n".join(lines)
```

- [ ] **Step 7: Run the full test file**

Run: `.venv/bin/pytest tests/unit/test_known_corrupt_print_cleanup.py -v`
Expected: all tests pass (existing + 3 new).

- [ ] **Step 8: Commit**

```bash
git add scripts/ops/corpus/ops_known_corrupt_print_cleanup.py tests/unit/test_known_corrupt_print_cleanup.py
git commit -m "feat(todo-151): downgrade cross-symbol-corroborated CONFIRMED_CORRUPT to MARKET_EVENT"
```

---

### Task 5: Re-run the dry-run report against the live database and stop for review

**Files:** none (operational verification step)

- [ ] **Step 1: Run the dry-run**

Run: `python scripts/ops/corpus/ops_known_corrupt_print_cleanup.py`
Expected: exit 0. Report printed to stdout.

- [ ] **Step 2: Verify CWB/RSP/VTV/VYM's Flash Crash rows now classify as MARKET_EVENT**

In the printed report, check the `MARKET_EVENT` section contains the 2010-05-06 rows for
`CWB`, `RSP`, `VTV`, `VYM` (and check whether `ITA`/`VUG` appear too, per the original todo's
finding of 6 affected symbols).

- [ ] **Step 3: Verify the 23 previously-confirmed-safe rows are still CONFIRMED_CORRUPT**

In the `CONFIRMED_CORRUPT` section, confirm `UUP` (~11 rows), `VWO` (~4 rows), `XRT` (1 row),
and RSP's isolated 2007-08-01 row are still present and RSP's 2010-05-06 row is NOT among them
(it should now be in MARKET_EVENT instead).

- [ ] **Step 4: STOP — do not run `--apply`**

Per the script's own module docstring ("This script must never be invoked with --apply by an
unsupervised agent — a human reviews the CONFIRMED_CORRUPT table in the dry-run report first"),
present the dry-run report to the user and wait for explicit confirmation before running
`python scripts/ops/corpus/ops_known_corrupt_print_cleanup.py --apply`. This step is
intentionally not automated by this plan.

---

## Self-Review

**Spec coverage:**
- Todo 152's recommended fix (option 1, cross-symbol corroboration) — Task 2.
- Todo 152's sizing note ("re-flagging the existing 76 suspect rows via a corrective UPDATE") —
  Task 3.
- Todo 151's blocking note (152 must land before `--apply`, expects contaminated rows to
  reclassify) — Task 4 (code) + Task 5 (live verification).
- Todo 151's own safety gate (human review before `--apply`) — preserved, Task 5 Step 4.

**Placeholder scan:** none found — every step has literal code/commands/SQL.

**Type consistency:** `_apply_cross_symbol_corroboration` returns `dict[str, int]` keyed by
scale name, matching `_SCALES` tuple elements throughout. `apply_cross_symbol_downgrade` and
`count_corroborating_symbols` signatures match their call sites in `_scan_and_classify`.
