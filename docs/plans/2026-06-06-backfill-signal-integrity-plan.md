# Backfill Signal Integrity Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `historical_backfill.py --replay-only --clean --workers 8` produce a provably clean signal_ledger where every signal_id is unique and `was_selected = TRUE` occurs at most once per (symbol, tf, bar_ts), with calibration and perf_weights threaded through the pipeline for structural parity with the live system.

**Architecture:** Eight surgical changes to `production/scripts/historical_backfill.py`: two new DB loaders, calibration kwargs threaded through three function signatures, calibration loaded in both worker paths, and a post-run integrity gate that hard-fails on invariant violations. No schema changes, no live pipeline changes.

**Tech Stack:** Python 3.11, psycopg2, `setup_performance_updater._compute_perf_multipliers` (reused from live pipeline), pytest with MagicMock for unit tests.

---

## File Map

- **Modify:** `production/scripts/historical_backfill.py` — all eight changes
- **Modify:** `tests/unit/scripts/test_historical_backfill.py` — new tests for loaders and integrity gate

---

### Task 1: Add `_load_calibration_curves` and `_load_perf_weights`

These two functions are the DB loading primitives. They are called once per worker after the connection opens. Both return empty dicts when their tables are empty — `aggregate()` handles `None` and `{}` identically.

**Files:**
- Modify: `tests/unit/scripts/test_historical_backfill.py`
- Modify: `production/scripts/historical_backfill.py`

- [ ] **Step 1: Write the failing tests**

Add to `tests/unit/scripts/test_historical_backfill.py`:

```python
from unittest.mock import MagicMock, call


def test_load_calibration_curves_empty_table():
    """Returns empty dict when calibration_curves table has no rows."""
    from production.scripts.historical_backfill import _load_calibration_curves

    conn = MagicMock()
    conn.cursor.return_value.__enter__.return_value.fetchall.return_value = []
    result = _load_calibration_curves(conn)
    assert result == {}


def test_load_calibration_curves_builds_two_tuple_key():
    """DB rows with 3-tuple (plugin, tf, symbol) become 2-tuple (plugin, tf) keys.
    
    Symbol-specific row beats global '*' row for the same (plugin, tf).
    """
    from production.scripts.historical_backfill import _load_calibration_curves

    conn = MagicMock()
    conn.cursor.return_value.__enter__.return_value.fetchall.return_value = [
        # Global sentinel row
        ("vwap_deviation", "1m", "*", {"breakpoints": [0.1, 0.5, 0.9], "values": [0.15, 0.5, 0.85]}),
        # Symbol-specific row — should win for same (plugin, tf)
        ("vwap_deviation", "1m", "ESM6", {"breakpoints": [0.2, 0.6, 0.9], "values": [0.25, 0.6, 0.88]}),
        # Different plugin
        ("momentum_burst", "5m", "*", {"breakpoints": [0.0, 1.0], "values": [0.0, 1.0]}),
    ]
    result = _load_calibration_curves(conn, symbol="ESM6")
    assert ("vwap_deviation", "1m") in result
    assert ("momentum_burst", "5m") in result
    # Symbol-specific wins over global
    bp, vals = result[("vwap_deviation", "1m")]
    assert bp == [0.2, 0.6, 0.9]


def test_load_calibration_curves_skips_rows_missing_data():
    """Rows with missing breakpoints or values are silently skipped."""
    from production.scripts.historical_backfill import _load_calibration_curves

    conn = MagicMock()
    conn.cursor.return_value.__enter__.return_value.fetchall.return_value = [
        ("vwap_deviation", "1m", "*", {"breakpoints": [], "values": []}),
        ("momentum_burst", "5m", "*", None),
    ]
    result = _load_calibration_curves(conn)
    assert result == {}


def test_load_perf_weights_empty_table():
    """Returns empty dict when setup_performance has no eligible rows."""
    from production.scripts.historical_backfill import _load_perf_weights

    conn = MagicMock()
    conn.cursor.return_value.__enter__.return_value.fetchall.return_value = []
    result = _load_perf_weights(conn)
    assert result == {}


def test_load_perf_weights_returns_multipliers():
    """Rows from setup_performance are converted to (perf_multiplier, sample_size) tuples.
    
    _compute_perf_multipliers sorts by sharpe_ratio ascending. Best Sharpe
    gets lowest multiplier (sorts first under ascending adjusted_rank).
    """
    from production.scripts.historical_backfill import _load_perf_weights

    conn = MagicMock()
    # Two plugins with sample_size >= 100
    conn.cursor.return_value.__enter__.return_value.fetchall.return_value = [
        ("vwap_deviation", 0.62, 0.25, 150, 1.5),   # plugin, win_rate, avg_pnl_r, sample_size, sharpe
        ("momentum_burst", 0.55, 0.15, 120, 0.8),
    ]
    result = _load_perf_weights(conn)
    assert "vwap_deviation" in result
    assert "momentum_burst" in result
    # Both are (multiplier, sample_size) tuples
    for plugin, val in result.items():
        mult, size = val
        assert 0.5 <= mult <= 1.5
        assert isinstance(size, int)
    # Best Sharpe (vwap_deviation at 1.5) gets lowest multiplier
    assert result["vwap_deviation"][0] < result["momentum_burst"][0]
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
.venv/bin/pytest tests/unit/scripts/test_historical_backfill.py -k "load_calibration or load_perf" -v 2>&1 | tail -20
```

Expected: `ImportError` or `AttributeError` — functions don't exist yet.

- [ ] **Step 3: Implement `_load_calibration_curves` and `_load_perf_weights`**

Find the line after `_insert_signals_sync` ends (around line 903) and add before `run_i7_and_persist`. Add the import at the top of the file near other src imports:

Add import near the top with other `src.intelligence` imports:
```python
from src.intelligence.setup_performance_updater import _compute_perf_multipliers
```

Add these two functions immediately before `run_i7_and_persist` (before line 906):

```python
def _load_calibration_curves(
    conn: Any, symbol: str = "*"
) -> dict[tuple[str, str], tuple[list, list]]:
    """Load calibration curves from DB as 2-tuple keyed dict for aggregate().

    The DB stores 3-tuple keys (plugin, tf, symbol). aggregate() uses 2-tuple
    (plugin, tf). This function resolves the symbol dimension: symbol-specific
    curves take precedence over the global '*' sentinel.

    Returns {} when the table is empty — aggregate() falls back to raw confidence.
    """
    with conn.cursor() as cur:
        cur.execute(
            "SELECT setup_plugin, timeframe, symbol, curve_data "
            "FROM calibration_curves "
            "WHERE symbol = %s OR symbol = '*'",
            (symbol,),
        )
        rows = cur.fetchall()

    result: dict[tuple[str, str], tuple[list, list]] = {}
    for plugin, tf, row_symbol, curve_data in rows:
        if not curve_data:
            continue
        bp = curve_data.get("breakpoints")
        vals = curve_data.get("values")
        if not bp or not vals:
            continue
        key = (plugin, tf)
        # Symbol-specific row overwrites global '*' sentinel for the same key.
        if key not in result or row_symbol != "*":
            result[key] = (bp, vals)
    return result


def _load_perf_weights(conn: Any) -> dict[str, tuple[float, int]]:
    """Load perf multipliers from setup_performance using the same Sharpe-rank
    formula as the live pipeline (_compute_perf_multipliers).

    Returns {} when no setups have sample_size >= MIN_SAMPLE_SIZE (100).
    """
    from src.intelligence.setup_performance_updater import MIN_SAMPLE_SIZE

    with conn.cursor() as cur:
        cur.execute(
            "SELECT setup_plugin, win_rate, avg_pnl_r, sample_size, sharpe_ratio "
            "FROM setup_performance WHERE sample_size >= %s",
            (MIN_SAMPLE_SIZE,),
        )
        rows = cur.fetchall()

    if not rows:
        return {}

    stats = {
        plugin: {
            "win_rate": win_rate,
            "avg_pnl_r": avg_pnl_r,
            "sample_size": sample_size,
            "sharpe_ratio": sharpe_ratio,
        }
        for plugin, win_rate, avg_pnl_r, sample_size, sharpe_ratio in rows
    }
    return _compute_perf_multipliers(stats)
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
.venv/bin/pytest tests/unit/scripts/test_historical_backfill.py -k "load_calibration or load_perf" -v 2>&1 | tail -20
```

Expected: all 5 tests `PASSED`.

- [ ] **Step 5: Run full unit suite to check for regressions**

```bash
.venv/bin/pytest tests/unit/ -q 2>&1 | tail -10
```

Expected: all green.

- [ ] **Step 6: Commit**

```bash
git add production/scripts/historical_backfill.py tests/unit/scripts/test_historical_backfill.py
git commit -m "feat(backfill): add calibration and perf_weights loaders"
```

---

### Task 2: Thread calibration through `run_i7_and_persist`

`run_i7_and_persist` is the innermost call site that talks to `aggregate()`. Add the two new kwargs here and pass them through.

**Files:**
- Modify: `tests/unit/scripts/test_historical_backfill.py`
- Modify: `production/scripts/historical_backfill.py:906-917` (function signature)
- Modify: `production/scripts/historical_backfill.py:974` (aggregate call)

- [ ] **Step 1: Write the failing test**

Add to `tests/unit/scripts/test_historical_backfill.py`:

```python
def test_run_i7_and_persist_passes_calibration_to_aggregate():
    """calibration_curves and perf_weights reach aggregate() when provided."""
    import sys
    from collections import deque
    from datetime import UTC, datetime
    from pathlib import Path
    from unittest.mock import MagicMock, patch

    sys.path.insert(0, str(Path(__file__).parents[3] / "production" / "scripts"))
    from production.scripts.historical_backfill import run_i7_and_persist
    from src.intelligence.register_plugins import register_all_plugins

    register_all_plugins()

    base = datetime(2026, 3, 7, 9, 30, 0, tzinfo=UTC)
    bars = [
        {
            "timestamp": base,
            "open": 5200.0,
            "high": 5205.0,
            "low": 5195.0,
            "close": 5202.0,
            "volume": 1000.0,
        }
        for _ in range(60)  # enough bars to pass warmup guard
    ]
    history = deque(bars, maxlen=200)
    features = {"trend_regime": 0.5}

    cal_curves = {("some_plugin", "1m"): ([0.0, 1.0], [0.0, 1.0])}
    perf_wts = {"some_plugin": (1.0, 100)}

    captured = {}

    def fake_aggregate(signals, *, trend_regime=0.0, features=None,
                       calibration_curves=None, perf_weights=None, **kwargs):
        captured["calibration_curves"] = calibration_curves
        captured["perf_weights"] = perf_weights
        from src.intelligence.trading.aggregator import AggregatedResult
        return AggregatedResult(selected=None, all_ranked=[], active=[])

    with patch("production.scripts.historical_backfill.aggregate", side_effect=fake_aggregate):
        run_i7_and_persist(
            history, features, "ESM6", "1m", base, db_conn=None,
            calibration_curves=cal_curves, perf_weights=perf_wts,
        )

    assert captured.get("calibration_curves") == cal_curves
    assert captured.get("perf_weights") == perf_wts
```

- [ ] **Step 2: Run test to verify it fails**

```bash
.venv/bin/pytest tests/unit/scripts/test_historical_backfill.py -k "test_run_i7_and_persist_passes_calibration" -v 2>&1 | tail -15
```

Expected: `TypeError` — unexpected keyword argument `calibration_curves`.

- [ ] **Step 3: Update `run_i7_and_persist` signature and aggregate call**

Replace the function signature at line 906:

```python
def run_i7_and_persist(
    bar_history: deque,
    features: dict[str, Any],
    symbol: str,
    timeframe: str,
    timestamp: datetime,
    db_conn: Any,
    feature_ts: datetime | None = None,
    feature_tf: str | None = None,
    df: pd.DataFrame | None = None,
    signal_buffer: list | None = None,
    calibration_curves: dict | None = None,
    perf_weights: dict | None = None,
) -> int:
```

Replace the `aggregate(...)` call at line 974:

```python
    agg_result = aggregate(
        raw_signals,
        trend_regime=trend_regime,
        features=features,
        calibration_curves=calibration_curves,
        perf_weights=perf_weights,
        timeframe=timeframe,
    )
```

- [ ] **Step 4: Run test to verify it passes**

```bash
.venv/bin/pytest tests/unit/scripts/test_historical_backfill.py -k "test_run_i7_and_persist_passes_calibration" -v 2>&1 | tail -10
```

Expected: `PASSED`.

- [ ] **Step 5: Run full unit suite**

```bash
.venv/bin/pytest tests/unit/ -q 2>&1 | tail -10
```

Expected: all green.

- [ ] **Step 6: Commit**

```bash
git add production/scripts/historical_backfill.py tests/unit/scripts/test_historical_backfill.py
git commit -m "feat(backfill): thread calibration_curves and perf_weights into run_i7_and_persist"
```

---

### Task 3: Thread calibration through `replay_symbol`

`replay_symbol` calls `run_i7_and_persist` in the event loop. Add the two kwargs and pass them through.

**Files:**
- Modify: `tests/unit/scripts/test_historical_backfill.py`
- Modify: `production/scripts/historical_backfill.py:1314-1320` (signature)
- Modify: `production/scripts/historical_backfill.py:1455-1466` (call site)

- [ ] **Step 1: Locate all `run_i7_and_persist` call sites inside `replay_symbol`**

```bash
grep -n "run_i7_and_persist" production/scripts/historical_backfill.py
```

There are two: one in the event loop (~line 1455) and one in the buffered flush path. Both must receive the kwargs.

- [ ] **Step 2: Write the failing test**

Add to `tests/unit/scripts/test_historical_backfill.py`:

```python
def test_replay_symbol_threads_calibration_to_run_i7():
    """calibration_curves and perf_weights are forwarded to run_i7_and_persist."""
    from unittest.mock import patch, MagicMock
    from production.scripts.historical_backfill import replay_symbol

    captured = {}

    def fake_run_i7(history, features, symbol, tf, ts, db_conn, **kwargs):
        captured["calibration_curves"] = kwargs.get("calibration_curves")
        captured["perf_weights"] = kwargs.get("perf_weights")
        return 0

    cal_curves = {("vwap_deviation", "1m"): ([0.0, 1.0], [0.0, 1.0])}
    perf_wts = {"vwap_deviation": (0.8, 120)}

    mock_conn = MagicMock()
    # Make fetch_bars return empty so replay_symbol exits early after the check
    with patch("production.scripts.historical_backfill.fetch_bars", return_value=[]):
        result = replay_symbol(
            "ESM6", mock_conn, ["1m"],
            calibration_curves=cal_curves,
            perf_weights=perf_wts,
        )

    # Empty bars → returns {} without calling run_i7, but signature must accept kwargs
    assert result == {}
```

- [ ] **Step 3: Run test to verify it fails**

```bash
.venv/bin/pytest tests/unit/scripts/test_historical_backfill.py -k "test_replay_symbol_threads_calibration" -v 2>&1 | tail -10
```

Expected: `TypeError` — unexpected keyword argument `calibration_curves`.

- [ ] **Step 4: Update `replay_symbol` signature**

Replace line 1314–1320:

```python
def replay_symbol(
    symbol: str,
    db_conn: Any,
    timeframes: list[str] | None = None,
    since: datetime | None = None,
    skip_signals: bool = False,
    calibration_curves: dict | None = None,
    perf_weights: dict | None = None,
) -> dict[str, int]:
```

- [ ] **Step 5: Update all `run_i7_and_persist` calls inside `replay_symbol`**

Find every `run_i7_and_persist(` call inside `replay_symbol` (grep showed ~line 1455). Add `calibration_curves=calibration_curves, perf_weights=perf_weights` to each call. The call looks like:

```python
            n = run_i7_and_persist(
                history,
                all_features,
                symbol,
                tf,
                ts,
                db_conn,
                feature_ts=written_feature_ts,
                feature_tf=(tf if written_feature_ts is not None else None),
                df=df,
                signal_buffer=signal_buffers[tf],
                calibration_curves=calibration_curves,
                perf_weights=perf_weights,
            )
```

- [ ] **Step 6: Run tests to verify they pass**

```bash
.venv/bin/pytest tests/unit/scripts/test_historical_backfill.py -k "calibration or perf_weights or load_calib or load_perf" -v 2>&1 | tail -15
```

Expected: all `PASSED`.

- [ ] **Step 7: Run full unit suite**

```bash
.venv/bin/pytest tests/unit/ -q 2>&1 | tail -10
```

Expected: all green.

- [ ] **Step 8: Commit**

```bash
git add production/scripts/historical_backfill.py tests/unit/scripts/test_historical_backfill.py
git commit -m "feat(backfill): thread calibration through replay_symbol"
```

---

### Task 4: Load calibration in `_replay_worker` and single-worker path

Both execution paths — the `ProcessPoolExecutor` multi-worker path and the `args.workers == 1` serial path — must load calibration before calling `replay_symbol`.

**Files:**
- Modify: `production/scripts/historical_backfill.py:1505-1526` (`_replay_worker`)
- Modify: `production/scripts/historical_backfill.py:1973-1979` (single-worker path in `main`)

No new tests needed: the loaders are already tested in Task 1, and `replay_symbol` threading is tested in Task 3. The wiring here is structural.

- [ ] **Step 1: Update `_replay_worker` to load and pass calibration**

Replace lines 1518–1524:

```python
    symbol, db_url, timeframes, since_dt, skip_signals = args
    register_all_plugins()
    conn = psycopg2.connect(dsn=db_url)
    conn.autocommit = True
    try:
        calibration_curves = _load_calibration_curves(conn, symbol=symbol)
        perf_weights = _load_perf_weights(conn)
        counts = replay_symbol(
            symbol, conn, timeframes, since=since_dt, skip_signals=skip_signals,
            calibration_curves=calibration_curves, perf_weights=perf_weights,
        )
        return symbol, sum(counts.values()), counts
    finally:
        conn.close()
```

- [ ] **Step 2: Update single-worker path in `main`**

Find the `args.workers == 1` branch (~line 1973). Replace the inner `replay_symbol` call:

```python
        if args.workers == 1:
            perf_weights = _load_perf_weights(db_conn)  # global — same for all symbols
            for contract in contracts:
                print(f"\n{contract.symbol}:")
                calibration_curves = _load_calibration_curves(db_conn, symbol=contract.symbol)
                counts = replay_symbol(
                    contract.symbol, db_conn, timeframes, since=since_dt,
                    calibration_curves=calibration_curves,
                    perf_weights=perf_weights,
                )
                symbol_total = sum(counts.values())
                grand_total += symbol_total
                print(f"  {contract.symbol} total: {symbol_total} signals")
```

`perf_weights` is global (same for all symbols) — load once before the loop. `calibration_curves` is symbol-specific — load per contract, matching the worker path's `_load_calibration_curves(conn, symbol=symbol)` call.

- [ ] **Step 3: Run full unit suite**

```bash
.venv/bin/pytest tests/unit/ -q 2>&1 | tail -10
```

Expected: all green.

- [ ] **Step 4: Commit**

```bash
git add production/scripts/historical_backfill.py
git commit -m "feat(backfill): load calibration in worker and single-worker paths"
```

---

### Task 5: Add `_assert_backfill_integrity` and wire into main

The integrity gate is the invariant enforcer. It runs automatically after every `--replay-only` run. If it passes, data is usable. If it fails, the run is invalid — fix and retry.

**Files:**
- Modify: `tests/unit/scripts/test_historical_backfill.py`
- Modify: `production/scripts/historical_backfill.py` (new function + call in main)

- [ ] **Step 1: Write the failing tests**

Add to `tests/unit/scripts/test_historical_backfill.py`:

```python
def test_assert_backfill_integrity_passes_clean_data():
    """No violations → prints PASS and returns normally."""
    from unittest.mock import MagicMock, call
    from production.scripts.historical_backfill import _assert_backfill_integrity

    conn = MagicMock()
    cur = conn.cursor.return_value.__enter__.return_value
    # First query (was_selected violations): no rows
    # Second query (duplicate signal_ids): count = 0
    cur.fetchall.return_value = []
    cur.fetchone.return_value = (0,)

    # Must not raise
    _assert_backfill_integrity(conn, ["ESM6"])


def test_assert_backfill_integrity_fails_on_multiple_winners(capsys):
    """was_selected > 1 per bar → sys.exit(1)."""
    import pytest
    from unittest.mock import MagicMock
    from production.scripts.historical_backfill import _assert_backfill_integrity
    from datetime import UTC, datetime

    conn = MagicMock()
    cur = conn.cursor.return_value.__enter__.return_value
    ts = datetime(2026, 3, 7, 9, 30, 0, tzinfo=UTC)
    # First query returns one violation row
    cur.fetchall.return_value = [("ESM6", "1m", ts, 2)]

    with pytest.raises(SystemExit) as exc_info:
        _assert_backfill_integrity(conn, ["ESM6"])

    assert exc_info.value.code == 1
    captured = capsys.readouterr()
    assert "INTEGRITY FAIL" in captured.out
    assert "ESM6/1m" in captured.out


def test_assert_backfill_integrity_fails_on_duplicate_signal_ids(capsys):
    """Duplicate signal_ids → sys.exit(1) even if was_selected is clean."""
    import pytest
    from unittest.mock import MagicMock
    from production.scripts.historical_backfill import _assert_backfill_integrity

    conn = MagicMock()
    cur = conn.cursor.return_value.__enter__.return_value
    # was_selected check: no violations
    cur.fetchall.return_value = []
    # signal_id uniqueness check: 3 duplicates
    cur.fetchone.return_value = (3,)

    with pytest.raises(SystemExit) as exc_info:
        _assert_backfill_integrity(conn, ["ESM6"])

    assert exc_info.value.code == 1
    captured = capsys.readouterr()
    assert "INTEGRITY FAIL" in captured.out
    assert "duplicate signal_ids" in captured.out
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
.venv/bin/pytest tests/unit/scripts/test_historical_backfill.py -k "assert_backfill_integrity" -v 2>&1 | tail -10
```

Expected: `ImportError` — `_assert_backfill_integrity` does not exist.

- [ ] **Step 3: Implement `_assert_backfill_integrity`**

Add this function immediately before the `run_normalize` function (~line 1534):

```python
def _assert_backfill_integrity(conn: Any, symbols: list[str]) -> None:
    """Assert was_selected and signal_id invariants. Hard-fails with sys.exit(1) on violation.

    Invariant 1: was_selected = TRUE occurs at most once per (symbol, tf, bar_ts).
    Invariant 2: Every signal_id in signal_ledger is globally unique.

    Called automatically after every --replay-only run. If this passes, the data
    is usable for training. If it fails, wipe with --clean and investigate.
    """
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT symbol, timeframe, timestamp, COUNT(*) AS winner_count
            FROM signal_ledger
            WHERE symbol = ANY(%s) AND was_selected = TRUE
            GROUP BY symbol, timeframe, timestamp
            HAVING COUNT(*) > 1
            ORDER BY winner_count DESC
            LIMIT 20
            """,
            (symbols,),
        )
        violations = cur.fetchall()

    if violations:
        print(f"\n[INTEGRITY FAIL] was_selected > 1 per bar — {len(violations)} bars affected:")
        for sym, tf, ts, cnt in violations:
            print(f"  {sym}/{tf} @ {ts}: {cnt} winners")
        sys.exit(1)

    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT COUNT(*) FROM (
                SELECT signal_id FROM signal_ledger
                WHERE symbol = ANY(%s)
                GROUP BY signal_id HAVING COUNT(*) > 1
            ) dups
            """,
            (symbols,),
        )
        dup_count = cur.fetchone()[0]

    if dup_count:
        print(f"\n[INTEGRITY FAIL] {dup_count} duplicate signal_ids found")
        sys.exit(1)

    print("\n[INTEGRITY PASS] was_selected invariant holds. signal_ids unique.")
```

- [ ] **Step 4: Wire integrity gate into `main` after stage 2**

Find the line `print(f"\nStage 2 complete: {grand_total} total signals inserted into signal_ledger")` (~line 2001). Add immediately after it:

```python
        print(f"\nStage 2 complete: {grand_total} total signals inserted into signal_ledger")
        _assert_backfill_integrity(db_conn, [c.symbol for c in contracts])
```

- [ ] **Step 5: Run tests to verify they pass**

```bash
.venv/bin/pytest tests/unit/scripts/test_historical_backfill.py -k "assert_backfill_integrity" -v 2>&1 | tail -15
```

Expected: all 3 tests `PASSED`.

- [ ] **Step 6: Run full unit suite**

```bash
.venv/bin/pytest tests/unit/ -q 2>&1 | tail -10
```

Expected: all green.

- [ ] **Step 7: Commit**

```bash
git add production/scripts/historical_backfill.py tests/unit/scripts/test_historical_backfill.py
git commit -m "feat(backfill): add integrity gate asserting was_selected and signal_id invariants"
```

---

### Task 6: Clean data and replay

With all code changes in place, wipe the dirty signal data and rebuild cleanly.

**Files:** None — operational step only.

- [ ] **Step 1: Verify current dirty state before wiping**

```bash
PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -c "
SELECT symbol, timeframe,
  COUNT(*) as total_signals,
  SUM(CASE WHEN was_selected THEN 1 ELSE 0 END) as selected_count,
  COUNT(DISTINCT timestamp) as distinct_bars
FROM signal_ledger
GROUP BY symbol, timeframe
ORDER BY symbol, timeframe;"
```

Record these numbers. After replay, `selected_count / distinct_bars` must be ≤ 1.0 for every row.

- [ ] **Step 2: Run clean replay**

```bash
python production/scripts/historical_backfill.py --replay-only --clean --workers 8
```

The script will:
1. Wipe `signal_outcomes` and `signal_ledger` rows for all active contracts
2. Wipe `intelligence_features` rows for all active contracts
3. Replay all bars through I1→I7, write features + signals
4. Load calibration + perf_weights at worker start (no-op today — both tables empty)
5. Use deterministic `make_signal_id()` for every signal
6. Flush buffered signals at end of each TF
7. Run `_assert_backfill_integrity` automatically

Expected last lines:
```
Stage 2 complete: XXXXX total signals inserted into signal_ledger

[INTEGRITY PASS] was_selected invariant holds. signal_ids unique.

Backfill complete.
```

- [ ] **Step 3: Verify post-replay state**

```bash
PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -c "
SELECT symbol, timeframe,
  COUNT(*) as total_signals,
  SUM(CASE WHEN was_selected THEN 1 ELSE 0 END) as selected_count,
  COUNT(DISTINCT timestamp) as distinct_bars,
  ROUND(SUM(CASE WHEN was_selected THEN 1 ELSE 0 END)::numeric /
        NULLIF(COUNT(DISTINCT timestamp), 0), 3) as winners_per_bar
FROM signal_ledger
GROUP BY symbol, timeframe
ORDER BY symbol, timeframe;"
```

Every `winners_per_bar` must be ≤ 1.000.

- [ ] **Step 4: Verify no duplicate signal_ids**

```bash
PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -c "
SELECT COUNT(*) as duplicate_signal_ids
FROM (
  SELECT signal_id FROM signal_ledger GROUP BY signal_id HAVING COUNT(*) > 1
) dups;"
```

Expected: `0`.

---

## Done-Coding SOP

After Task 6 completes:

```bash
# code-simplifier agent   # clean up changed code (invoke automatically)
# /review                 # peer review
.venv/bin/pytest tests/unit/ -q
git checkout main && git merge --ff-only <branch>
git branch -d <branch>
git worktree prune
git push origin main
```
