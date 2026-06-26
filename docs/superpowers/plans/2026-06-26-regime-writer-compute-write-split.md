# regime_writer Compute/Write Split Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Eliminate the concurrent-write deadlock in `regime_writer` by separating HMM compute (parallel) from DB writes (serial in main process).

**Architecture:** Workers currently open their own DB connections and do concurrent `execute_batch` UPDATEs to `feature_vectors`, causing index-page deadlocks. After this change, workers are pure compute: they return `update_rows` to the main process, which writes all results serially through a single connection. CPU parallelism is preserved; write contention is eliminated by construction.

**Tech Stack:** Python 3.14, psycopg2, hmmlearn, ProcessPoolExecutor, pytest

## Global Constraints

- All DB writes go through a single connection in the main process — never from worker subprocesses
- Worker functions must not import or call OTel instrumentation (use `_NoopTracer`)
- `_compute_symbol_tf` must remain pure compute: reads OHLCV, runs HMM, returns rows — no side effects
- Exception variable name is `error` (not `exc`) per CLAUDE.md
- `structlog` event kwarg collision rule: never pass `event=` kwarg
- All existing tests in `tests/unit/services/test_regime_writer.py` must remain green

---

### Task 1: Split `_label_symbol_tf` into compute + write

**Files:**
- Modify: `services/regime_writer.py` (lines 279–498 — the `_label_symbol_tf` function and `_run_symbol_worker`)
- Test: `tests/unit/services/test_regime_writer.py`

**Interfaces:**
- Produces: `_compute_symbol_tf(conn, symbol, tf, n_components, vol_window, n_iter, hmm_random_state, momentum_window, vol_of_vol_window) -> tuple[list[tuple], bool] | None`
  - Returns `(update_rows, converged)` on success, `None` if no data or insufficient obs
  - Each row in `update_rows` is a 10-tuple: `(regime, p_up, p_ranging, p_down, prob_val, entropy_val, duration, symbol, tf, ts)`
- Produces: `_write_regime_results(conn, symbol, tf, update_rows, converged, tracer) -> int`
  - Executes the batch UPDATE, runs the count verification query, logs, emits OTel span + metrics
  - Returns `n_updated`

- [ ] **Step 1: Write failing tests for `_compute_symbol_tf`**

Add to `tests/unit/services/test_regime_writer.py`:

```python
from unittest.mock import MagicMock, call
from services.regime_writer import _compute_symbol_tf


def _make_mock_conn(closes, volumes, timestamps):
    """Build a psycopg2 connection mock that returns synthetic OHLCV rows."""
    rows = list(zip(timestamps, closes, volumes))
    # cursor used as context manager for named server-side cursor
    cursor_mock = MagicMock()
    cursor_mock.__enter__ = lambda s: s
    cursor_mock.__exit__ = MagicMock(return_value=False)
    # fetchmany returns all rows on first call, then [] to signal EOF
    cursor_mock.fetchmany.side_effect = [rows, []]
    conn_mock = MagicMock()
    conn_mock.cursor.return_value = cursor_mock
    return conn_mock


def test_compute_symbol_tf_returns_tuple_structure():
    """_compute_symbol_tf must return (update_rows, converged) with correct row shape."""
    n = 500
    closes = _make_ranging_closes(n)
    volumes = _make_volumes(n)
    timestamps = _make_timestamps(n)
    conn = _make_mock_conn(closes, volumes, timestamps)

    result = _compute_symbol_tf(
        conn=conn,
        symbol="SPY",
        tf="1d",
        n_components=3,
        vol_window=20,
        n_iter=50,
        hmm_random_state=42,
        momentum_window=20,
        vol_of_vol_window=20,
    )

    assert result is not None
    update_rows, converged = result
    assert isinstance(update_rows, list)
    assert len(update_rows) > 0
    # Each tuple: (regime, p_up, p_ranging, p_down, prob_val, entropy_val, duration, symbol, tf, ts)
    assert len(update_rows[0]) == 10
    assert isinstance(converged, bool)


def test_compute_symbol_tf_regime_values():
    """All regime labels in update_rows must be canonical strings."""
    n = 500
    closes = _make_ranging_closes(n)
    volumes = _make_volumes(n)
    timestamps = _make_timestamps(n)
    conn = _make_mock_conn(closes, volumes, timestamps)

    result = _compute_symbol_tf(
        conn=conn, symbol="TLT", tf="1d",
        n_components=3, vol_window=20, n_iter=50,
        hmm_random_state=42, momentum_window=20, vol_of_vol_window=20,
    )

    assert result is not None
    update_rows, _ = result
    valid_labels = {"trending_up", "trending_down", "ranging"}
    for row in update_rows:
        assert row[0] in valid_labels, f"Invalid regime label: {row[0]}"


def test_compute_symbol_tf_probabilities_sum_to_one():
    """p_up + p_ranging + p_down must sum to ~1.0 for each row."""
    n = 500
    closes = _make_ranging_closes(n)
    volumes = _make_volumes(n)
    timestamps = _make_timestamps(n)
    conn = _make_mock_conn(closes, volumes, timestamps)

    result = _compute_symbol_tf(
        conn=conn, symbol="GLD", tf="1d",
        n_components=3, vol_window=20, n_iter=50,
        hmm_random_state=42, momentum_window=20, vol_of_vol_window=20,
    )

    assert result is not None
    update_rows, _ = result
    for row in update_rows:
        _regime, p_up, p_ranging, p_down, prob_val, entropy_val, duration, sym, tf, ts = row
        total = p_up + p_ranging + p_down
        assert abs(total - 1.0) < 1e-6, f"Probabilities sum to {total}, expected ~1.0"


def test_compute_symbol_tf_returns_none_on_insufficient_data():
    """Returns None when fewer obs than n_components * _MIN_OBS_FACTOR."""
    n = 10
    closes = [100.0] * n
    volumes = [1e6] * n
    timestamps = _make_timestamps(n)
    conn = _make_mock_conn(closes, volumes, timestamps)

    result = _compute_symbol_tf(
        conn=conn, symbol="SPY", tf="1d",
        n_components=3, vol_window=20, n_iter=50,
        hmm_random_state=42, momentum_window=20, vol_of_vol_window=20,
    )

    assert result is None


def test_compute_symbol_tf_no_db_write():
    """Worker must not call conn.execute or conn.executemany for writes."""
    n = 500
    closes = _make_ranging_closes(n)
    volumes = _make_volumes(n)
    timestamps = _make_timestamps(n)
    conn = _make_mock_conn(closes, volumes, timestamps)

    _compute_symbol_tf(
        conn=conn, symbol="SPY", tf="1d",
        n_components=3, vol_window=20, n_iter=50,
        hmm_random_state=42, momentum_window=20, vol_of_vol_window=20,
    )

    # The cursor mock is only called for the SELECT (fetchmany) — never for UPDATE
    cursor = conn.cursor.return_value
    for c in cursor.execute.call_args_list:
        sql = c[0][0].upper() if c[0] else ""
        assert "UPDATE" not in sql, f"Worker issued an UPDATE: {sql}"
```

- [ ] **Step 2: Run tests to verify they fail (imports don't exist yet)**

```bash
.venv/bin/pytest tests/unit/services/test_regime_writer.py -k "compute_symbol_tf" -v 2>&1 | tail -20
```

Expected: `ImportError: cannot import name '_compute_symbol_tf'`

- [ ] **Step 3: Rename `_label_symbol_tf` → `_compute_symbol_tf` and strip the DB write block**

In `services/regime_writer.py`:

Replace the entire `_label_symbol_tf` function (lines 279–498) with two functions:

```python
def _compute_symbol_tf(
    conn: Any,
    symbol: str,
    tf: str,
    n_components: int,
    vol_window: int,
    n_iter: int,
    hmm_random_state: int,
    momentum_window: int,
    vol_of_vol_window: int,
) -> tuple[list[tuple], bool] | None:
    """Fit HMM for one (symbol, tf) cell. Returns (update_rows, converged) or None.

    Pure compute — no DB writes. Each tuple in update_rows matches the UPDATE SQL
    parameter order: (regime, p_up, p_ranging, p_down, prob_val, entropy_val,
    duration, symbol, tf, ts).
    """
    timestamps = []
    closes = []
    volumes = []
    conn.commit()
    with conn.cursor("ohlcv_stream") as cur:
        cur.execute(
            "SELECT timestamp, close, volume "
            "FROM market_data_ohlcv "
            "WHERE symbol = %s AND timeframe = %s "
            "ORDER BY timestamp ASC",
            (symbol, tf),
        )
        while True:
            batch = cur.fetchmany(10000)
            if not batch:
                break
            for r in batch:
                timestamps.append(r[0])
                closes.append(float(r[1]))
                volumes.append(float(r[2]))

    if not timestamps:
        _logger.warning("regime_writer.no_ohlcv", symbol=symbol, tf=tf)
        return None

    obs_matrix, valid_ts = _build_obs_matrix(
        timestamps, closes, volumes,
        vol_window=vol_window,
        momentum_window=momentum_window,
        vol_of_vol_window=vol_of_vol_window,
    )

    min_rows = n_components * _MIN_OBS_FACTOR
    if len(valid_ts) < min_rows:
        _logger.warning(
            "regime_writer.insufficient_obs",
            symbol=symbol,
            tf=tf,
            n_obs=len(valid_ts),
            min_required=min_rows,
        )
        return None

    scaler = StandardScaler()
    obs_matrix = scaler.fit_transform(obs_matrix)

    model = GaussianHMM(
        n_components=n_components,
        covariance_type="diag",
        n_iter=n_iter,
        random_state=hmm_random_state,
    )
    model.fit(obs_matrix)

    d = model.means_.shape[1]
    covars_diag = model.covars_[:, np.arange(d), np.arange(d)]
    raw_states, alpha_history = _causal_decode(
        obs_matrix,
        model.means_,
        covars_diag,
        model.transmat_,
        n_components,
    )

    label_map = _build_label_map(model.means_)
    up_state = next(k for k, v in label_map.items() if v == _LABEL_TRENDING_UP)
    down_state = next(k for k, v in label_map.items() if v == _LABEL_TRENDING_DOWN)
    rang_state = next(k for k, v in label_map.items() if v == _LABEL_RANGING)

    update_rows: list[tuple] = []
    prev_state: int | None = None
    duration = 0
    for i, (ts, state_idx) in enumerate(zip(valid_ts, raw_states)):
        state_idx = int(state_idx)
        if state_idx == prev_state:
            duration += 1
        else:
            duration = 1
            prev_state = state_idx
        alpha = alpha_history[i]
        p_up = float(alpha[up_state])
        p_ranging = float(alpha[rang_state])
        p_down = float(alpha[down_state])
        prob_val = float(np.max(alpha))
        entropy_val = float(-np.sum(alpha * np.log(np.maximum(alpha, 1e-300))))
        update_rows.append((
            label_map[state_idx],
            p_up,
            p_ranging,
            p_down,
            prob_val,
            entropy_val,
            float(duration),
            symbol,
            tf,
            ts,
        ))

    return update_rows, model.monitor_.converged


def _write_regime_results(
    conn: Any,
    symbol: str,
    tf: str,
    update_rows: list[tuple],
    converged: bool,
    tracer: Any,
) -> int:
    """Write HMM regime labels for one (symbol, tf) cell to feature_vectors.

    Runs in the main process — single serial write connection, no concurrency.
    Returns n_updated.
    """
    update_sql = (
        "UPDATE feature_vectors "
        "SET regime                = %s, "
        "    hmm_prob_trending_up  = %s, "
        "    hmm_prob_ranging      = %s, "
        "    hmm_prob_trending_down = %s, "
        "    hmm_regime_prob       = %s, "
        "    hmm_entropy           = %s, "
        "    hmm_duration          = %s "
        "WHERE symbol = %s AND tf = %s AND bar_ts = %s"
    )
    with tracer.start_as_current_span(
        "regime_writer.write_symbol_tf",
        attributes={"symbol": symbol, "tf": tf},
    ) as span:
        try:
            with conn.cursor() as cur:
                psycopg2.extras.execute_batch(
                    cur,
                    update_sql,
                    update_rows,
                    page_size=_UPDATE_BATCH_SIZE,
                )
            conn.commit()
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT "
                    "  count(*) FILTER (WHERE regime IS NOT NULL), "
                    "  count(*) FILTER (WHERE regime IS NULL) "
                    "FROM feature_vectors WHERE symbol = %s AND tf = %s",
                    (symbol, tf),
                )
                n_updated, remaining = cur.fetchone()
                n_updated = int(n_updated)
                remaining = int(remaining)

            REGIME_WRITER_NULL_REGIME_REMAINING.set(remaining, {"symbol": symbol, "tf": tf})
            span.set_attribute("n_updated", n_updated)
            span.set_attribute("null_remaining", remaining)
            _logger.info(
                "regime_writer.symbol_tf_done",
                symbol=symbol,
                tf=tf,
                n_updated=n_updated,
                null_remaining=remaining,
                converged=converged,
            )
            return n_updated

        except Exception as error:
            from opentelemetry.trace import StatusCode

            span.set_status(StatusCode.ERROR, str(error))
            span.record_exception(error)
            raise
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
.venv/bin/pytest tests/unit/services/test_regime_writer.py -k "compute_symbol_tf" -v 2>&1 | tail -20
```

Expected: all 5 new tests PASS.

- [ ] **Step 5: Update `_run_symbol_worker` to call `_compute_symbol_tf` and return rows**

Replace the entire `_run_symbol_worker` function body. Workers no longer need write access or reconnect logic for write failures. The connection is read-only (OHLCV SELECT only).

```python
def _run_symbol_worker(args: tuple) -> dict:
    """Worker function for ProcessPoolExecutor — runs in subprocess.

    Opens its own psycopg2 connection for OHLCV reads only. Runs HMM compute
    and returns update_rows to the main process; never writes to the DB.

    Args:
        args: (symbol, tfs, dsn, n_components, vol_window, momentum_window,
               vol_of_vol_window, n_iter, hmm_random_state)

    Returns:
        dict with keys:
          symbol: str
          results: list of {tf, update_rows, converged} or {tf, error}
          error: str | None  (set if connection itself failed)
    """
    (
        symbol,
        tfs,
        dsn,
        n_components,
        vol_window,
        momentum_window,
        vol_of_vol_window,
        n_iter,
        hmm_random_state,
    ) = args

    setup_service_logging("logs/regime_writer.log")
    worker_log = structlog.get_logger(__name__)

    conn = None
    results = []
    error_msg = None

    try:
        conn = psycopg2.connect(dsn, options="-c idle_in_transaction_session_timeout=0")

        for tf in tfs:
            try:
                result = _compute_symbol_tf(
                    conn=conn,
                    symbol=symbol,
                    tf=tf,
                    n_components=n_components,
                    vol_window=vol_window,
                    momentum_window=momentum_window,
                    vol_of_vol_window=vol_of_vol_window,
                    n_iter=n_iter,
                    hmm_random_state=hmm_random_state,
                )
                if result is None:
                    results.append({"tf": tf, "update_rows": None, "converged": False})
                else:
                    update_rows, converged = result
                    results.append({"tf": tf, "update_rows": update_rows, "converged": converged})
            except Exception as error:
                worker_log.error(
                    "regime_writer.worker_cell_failed",
                    symbol=symbol,
                    tf=tf,
                    error=str(error),
                )
                results.append({"tf": tf, "update_rows": None, "error": str(error)})
                try:
                    conn.rollback()
                except Exception:
                    pass

    except Exception as error:
        error_msg = str(error)
        worker_log.error("regime_writer.worker_failed", symbol=symbol, error=error_msg)
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass

    return {"symbol": symbol, "results": results, "error": error_msg}
```

- [ ] **Step 6: Update `main()` to open a single write connection and call `_write_regime_results`**

Replace the `worker_args` + pool section in `main()`:

```python
            worker_args = [
                (
                    symbol,
                    tfs,
                    dsn,
                    n_components,
                    vol_window,
                    momentum_window,
                    vol_of_vol_window,
                    n_iter,
                    hmm_random_state,
                )
                for symbol in symbols
            ]

            total_updated = 0
            failures: list[str] = []

            write_conn = psycopg2.connect(
                dsn,
                options="-c idle_in_transaction_session_timeout=0",
            )
            try:
                with ProcessPoolExecutor(max_workers=n_workers) as pool:
                    for result in pool.map(_run_symbol_worker, worker_args, chunksize=1):
                        symbol = result["symbol"]
                        if result["error"]:
                            failures.append(symbol)
                            _logger.error(
                                "regime_writer.symbol_failed",
                                symbol=symbol,
                                error=result["error"],
                            )
                        for cell in result["results"]:
                            tf = cell["tf"]
                            if "error" in cell:
                                failures.append(f"{symbol}/{tf}")
                                continue
                            if cell["update_rows"] is None:
                                continue
                            try:
                                n = _write_regime_results(
                                    conn=write_conn,
                                    symbol=symbol,
                                    tf=tf,
                                    update_rows=cell["update_rows"],
                                    converged=cell.get("converged", False),
                                    tracer=tracer,
                                )
                                total_updated += n
                                REGIME_WRITER_ROWS_UPDATED_TOTAL.add(n, {"symbol": symbol, "tf": tf})
                            except Exception as error:
                                _logger.error(
                                    "regime_writer.write_failed",
                                    symbol=symbol,
                                    tf=tf,
                                    error=str(error),
                                )
                                failures.append(f"{symbol}/{tf}")
                                try:
                                    write_conn.rollback()
                                except Exception:
                                    pass
            finally:
                write_conn.close()
```

- [ ] **Step 7: Run the full test suite**

```bash
.venv/bin/pytest tests/unit/services/test_regime_writer.py -v 2>&1 | tail -30
```

Expected: all tests PASS (no regressions).

- [ ] **Step 8: Lint and format**

```bash
.venv/bin/ruff check services/regime_writer.py --fix && .venv/bin/black services/regime_writer.py
```

Expected: no errors.

- [ ] **Step 9: Commit**

```bash
git add services/regime_writer.py tests/unit/services/test_regime_writer.py
git commit -m "fix(regime_writer): separate compute from write to eliminate concurrent-update deadlock

Workers previously did concurrent execute_batch UPDATEs to feature_vectors,
causing index-page deadlock cascades on the TimescaleDB hypertable (12 workers
all blocking each other for 4+ hours on the June 26 corpus run).

_label_symbol_tf split into _compute_symbol_tf (pure HMM compute, runs in
worker subprocesses) and _write_regime_results (serial DB write, runs in main
process). Workers return update_rows; main holds a single write connection and
serializes all writes. CPU parallelism preserved; write contention eliminated."
```
