# Pipeline Reset Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build `production/scripts/pipeline_reset.py` — a permanent, reusable script that clears and regenerates the canonical IndicAgent dataset (signal_ledger, intelligence_features, Redis streams) from raw OHLCV bars.

**Architecture:** Single script that imports replay/fetch functions from `historical_backfill.py`, adds Redis + DB clear logic, preflight/verify steps, and manual service pause prompts. No new services or modules — one well-documented script.

**Tech Stack:** Python 3.11+, psycopg2, redis-py, argparse. Reuses `historical_backfill.py` functions directly.

---

## Task 1: Script skeleton, flags, preflight display

**Files:**
- Create: `production/scripts/pipeline_reset.py`
- Test: `tests/unit/scripts/test_pipeline_reset.py`

**Step 1: Create test file**

```python
# tests/unit/scripts/test_pipeline_reset.py
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parents[3]))

import pytest
from unittest.mock import MagicMock, patch


def test_preflight_shows_row_counts():
    """Preflight prints table name and row count for each target table."""
    from production.scripts.pipeline_reset import build_preflight_summary

    conn = MagicMock()
    conn.cursor.return_value.__enter__ = lambda s: s
    conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
    conn.cursor.return_value.fetchone.return_value = (42,)

    summary = build_preflight_summary(conn, keep_ohlcv=False, clear_llm=False)

    assert "signal_ledger" in summary
    assert "intelligence_features" in summary
    assert "market_data_ohlcv" in summary
    assert "42" in summary


def test_preflight_omits_ohlcv_when_keep_ohlcv():
    """With --keep-ohlcv, market_data_ohlcv should not appear in summary."""
    from production.scripts.pipeline_reset import build_preflight_summary

    conn = MagicMock()
    conn.cursor.return_value.__enter__ = lambda s: s
    conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
    conn.cursor.return_value.fetchone.return_value = (0,)

    summary = build_preflight_summary(conn, keep_ohlcv=True, clear_llm=False)

    assert "market_data_ohlcv" not in summary


def test_preflight_includes_llm_when_flag_set():
    """With --clear-llm, llm_calls should appear in summary."""
    from production.scripts.pipeline_reset import build_preflight_summary

    conn = MagicMock()
    conn.cursor.return_value.__enter__ = lambda s: s
    conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
    conn.cursor.return_value.fetchone.return_value = (7,)

    summary = build_preflight_summary(conn, keep_ohlcv=False, clear_llm=True)

    assert "llm_calls" in summary
```

**Step 2: Run test to verify it fails**

```bash
.venv/bin/pytest tests/unit/scripts/test_pipeline_reset.py -v
```
Expected: ImportError or AttributeError — module doesn't exist yet.

**Step 3: Create the script skeleton**

```python
#!/usr/bin/env python3
"""
Pipeline Reset

Clears and regenerates the canonical IndicAgent dataset from raw OHLCV bars.
Run whenever signals change, schema changes, or data integrity is in question.

Renaissance principle: Data quality over model complexity. No ML model or alpha
claim is valid until the training dataset is clean, gap-free, and correctly
timestamped.

Usage:
    # Full reset — re-fetch from IBKR + replay
    python production/scripts/pipeline_reset.py

    # Fast reset — keep OHLCV, just re-replay through updated signal logic
    python production/scripts/pipeline_reset.py --keep-ohlcv

    # Specific symbols only
    python production/scripts/pipeline_reset.py --keep-ohlcv --symbols ESH6,NQH6

    # See what would happen without touching anything
    python production/scripts/pipeline_reset.py --dry-run
"""
from __future__ import annotations

import argparse
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import psycopg2
import psycopg2.extras
import redis

# Allow running from repo root
sys.path.insert(0, str(Path(__file__).parents[2]))

from src.config.settings import Settings

# Reuse connect_db and replay logic from historical_backfill
from production.scripts.historical_backfill import (  # noqa: E402
    connect_db,
    replay_symbol,
)

# Tables cleared on every reset (always)
_ALWAYS_CLEAR = [
    "signal_ledger",
    "intelligence_features",
    "technical_indicators",
]

# Cleared only without --keep-ohlcv
_OHLCV_TABLE = "market_data_ohlcv"

# Cleared only with --clear-llm
_LLM_TABLES = ["llm_calls", "llm_model_scores"]

# Redis key patterns to clear (will be prefixed with env_prefix)
_REDIS_PATTERNS = ["indicators", "intelligence", "signals", "narratives"]

DEFAULT_TIMEFRAMES = ["1m", "5m", "15m", "1h"]


def _row_count(conn: Any, table: str) -> int:
    """Return current row count for *table*."""
    with conn.cursor() as cur:
        cur.execute(f"SELECT COUNT(*) FROM {table}")  # noqa: S608
        row = cur.fetchone()
        return row[0] if row else 0


def build_preflight_summary(
    conn: Any,
    keep_ohlcv: bool,
    clear_llm: bool,
) -> str:
    """Return a human-readable summary of what will be cleared."""
    lines = ["DB tables:"]
    tables = list(_ALWAYS_CLEAR)
    if not keep_ohlcv:
        tables.append(_OHLCV_TABLE)
    if clear_llm:
        tables.extend(_LLM_TABLES)
    for table in tables:
        count = _row_count(conn, table)
        lines.append(f"  {table:<35} {count:>10,} rows")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Pipeline Reset — clear and regenerate canonical IndicAgent dataset"
    )
    parser.add_argument("--keep-ohlcv", action="store_true",
                        help="Skip IBKR re-fetch; replay from existing market_data_ohlcv")
    parser.add_argument("--symbols", default=None,
                        help="Comma-separated symbols (default: all active contracts)")
    parser.add_argument("--days", type=int, default=35,
                        help="Days of 1m history to fetch (default: 35)")
    parser.add_argument("--clear-llm", action="store_true",
                        help="Also truncate llm_calls and llm_model_scores")
    parser.add_argument("--dry-run", action="store_true",
                        help="Show what would be cleared; exit without touching anything")
    parser.add_argument("--yes", action="store_true",
                        help="Skip confirmation prompt")
    parser.add_argument("--client-id", type=int, default=56,
                        help="IBKR client ID (default: 56)")
    args = parser.parse_args()

    settings = Settings()
    db_conn = connect_db(settings)

    # --- Preflight ---
    print("\nPipeline Reset")
    print("=" * 50)
    if args.dry_run:
        print("DRY RUN — nothing will be modified\n")
    print(build_preflight_summary(db_conn, args.keep_ohlcv, args.clear_llm))
    print()

    if args.dry_run:
        db_conn.close()
        return

    if not args.yes:
        answer = input("This cannot be undone. Type YES to continue: ")
        if answer.strip() != "YES":
            print("Aborted.")
            db_conn.close()
            return

    db_conn.close()
    print("\nReady. Complete remaining steps below.")


if __name__ == "__main__":
    main()
```

**Step 4: Run tests**

```bash
.venv/bin/pytest tests/unit/scripts/test_pipeline_reset.py -v
```
Expected: All 3 tests PASS.

**Step 5: Commit**

```bash
git add production/scripts/pipeline_reset.py tests/unit/scripts/test_pipeline_reset.py
git commit -m "feat(reset): skeleton with preflight summary and dry-run"
```

---

## Task 2: Redis stream clearing

**Files:**
- Modify: `production/scripts/pipeline_reset.py`
- Test: `tests/unit/scripts/test_pipeline_reset.py`

**Step 1: Add failing tests**

```python
def test_clear_redis_streams_deletes_matching_keys():
    """clear_redis_streams deletes all keys matching the pipeline patterns."""
    from production.scripts.pipeline_reset import clear_redis_streams

    r = MagicMock()
    r.scan_iter.side_effect = [
        [b"development:indicators:ESH6:1m"],
        [b"development:intelligence:ESH6:1m"],
        [b"development:signals:ESH6:1m:aggregated"],
        [b"development:narratives:ESH6:1m"],
    ]
    r.delete = MagicMock()

    count = clear_redis_streams(r, env_prefix="development")

    assert r.delete.call_count == 4
    assert count == 4


def test_clear_redis_streams_returns_zero_when_no_keys():
    """Returns 0 when no matching keys exist."""
    from production.scripts.pipeline_reset import clear_redis_streams

    r = MagicMock()
    r.scan_iter.return_value = []

    count = clear_redis_streams(r, env_prefix="development")
    assert count == 0
```

**Step 2: Run tests — expect failure**

```bash
.venv/bin/pytest tests/unit/scripts/test_pipeline_reset.py::test_clear_redis_streams_deletes_matching_keys -v
```

**Step 3: Implement `clear_redis_streams`**

Add after `build_preflight_summary` in `pipeline_reset.py`:

```python
def clear_redis_streams(r: redis.Redis, env_prefix: str) -> int:
    """Delete all pipeline stream keys for *env_prefix*. Returns key count deleted."""
    deleted = 0
    for pattern_name in _REDIS_PATTERNS:
        pattern = f"{env_prefix}:{pattern_name}:*"
        keys = list(r.scan_iter(pattern))
        if keys:
            r.delete(*keys)
            deleted += len(keys)
    return deleted
```

Also add to `main()` after the confirmation prompt (placeholder for now — full wiring in Task 5):

```python
    # Will be wired in Task 5
    # r = redis.Redis.from_url(settings.redis_url)
    # n = clear_redis_streams(r, settings.env_prefix)
    # print(f"  Cleared {n} Redis stream keys")
```

**Step 4: Run all tests**

```bash
.venv/bin/pytest tests/unit/scripts/test_pipeline_reset.py -v
```
Expected: All 5 tests PASS.

**Step 5: Commit**

```bash
git add production/scripts/pipeline_reset.py tests/unit/scripts/test_pipeline_reset.py
git commit -m "feat(reset): Redis stream clearing"
```

---

## Task 3: DB table truncation

**Files:**
- Modify: `production/scripts/pipeline_reset.py`
- Test: `tests/unit/scripts/test_pipeline_reset.py`

**Step 1: Add failing tests**

```python
def test_truncate_tables_always_clears_core_tables():
    """truncate_tables always clears signal_ledger, intelligence_features, technical_indicators."""
    from production.scripts.pipeline_reset import truncate_tables

    conn = MagicMock()
    cur = MagicMock()
    conn.cursor.return_value.__enter__ = lambda s: cur
    conn.cursor.return_value.__exit__ = MagicMock(return_value=False)

    truncate_tables(conn, keep_ohlcv=True, clear_llm=False)

    executed = [call.args[0] for call in cur.execute.call_args_list]
    assert any("signal_ledger" in sql for sql in executed)
    assert any("intelligence_features" in sql for sql in executed)
    assert any("technical_indicators" in sql for sql in executed)
    assert not any("market_data_ohlcv" in sql for sql in executed)


def test_truncate_tables_includes_ohlcv_when_not_keep():
    """truncate_tables includes market_data_ohlcv when keep_ohlcv=False."""
    from production.scripts.pipeline_reset import truncate_tables

    conn = MagicMock()
    cur = MagicMock()
    conn.cursor.return_value.__enter__ = lambda s: cur
    conn.cursor.return_value.__exit__ = MagicMock(return_value=False)

    truncate_tables(conn, keep_ohlcv=False, clear_llm=False)

    executed = [call.args[0] for call in cur.execute.call_args_list]
    assert any("market_data_ohlcv" in sql for sql in executed)


def test_truncate_tables_includes_llm_when_flag_set():
    """truncate_tables includes llm_calls when clear_llm=True."""
    from production.scripts.pipeline_reset import truncate_tables

    conn = MagicMock()
    cur = MagicMock()
    conn.cursor.return_value.__enter__ = lambda s: cur
    conn.cursor.return_value.__exit__ = MagicMock(return_value=False)

    truncate_tables(conn, keep_ohlcv=True, clear_llm=True)

    executed = [call.args[0] for call in cur.execute.call_args_list]
    assert any("llm_calls" in sql for sql in executed)
```

**Step 2: Run tests — expect failure**

```bash
.venv/bin/pytest tests/unit/scripts/test_pipeline_reset.py -k "truncate" -v
```

**Step 3: Implement `truncate_tables`**

```python
def truncate_tables(conn: Any, keep_ohlcv: bool, clear_llm: bool) -> list[str]:
    """TRUNCATE target tables. Returns list of tables cleared."""
    tables = list(_ALWAYS_CLEAR)
    if not keep_ohlcv:
        tables.append(_OHLCV_TABLE)
    if clear_llm:
        tables.extend(_LLM_TABLES)

    with conn.cursor() as cur:
        for table in tables:
            cur.execute(f"TRUNCATE {table} CASCADE")  # noqa: S608
    conn.commit()
    return tables
```

**Step 4: Run all tests**

```bash
.venv/bin/pytest tests/unit/scripts/test_pipeline_reset.py -v
```
Expected: All 8 tests PASS.

**Step 5: Commit**

```bash
git add production/scripts/pipeline_reset.py tests/unit/scripts/test_pipeline_reset.py
git commit -m "feat(reset): DB table truncation"
```

---

## Task 4: Verification step

**Files:**
- Modify: `production/scripts/pipeline_reset.py`
- Test: `tests/unit/scripts/test_pipeline_reset.py`

**Step 1: Add failing tests**

```python
def test_verify_dataset_passes_when_rows_exist():
    """verify_dataset returns True when all tables have rows."""
    from production.scripts.pipeline_reset import verify_dataset

    conn = MagicMock()
    conn.cursor.return_value.__enter__ = lambda s: s
    conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
    # Returns different counts per call: signal_ledger=1000, intelligence_features=5000
    conn.cursor.return_value.fetchone.side_effect = [(1000,), (5000,), (10,)]
    conn.cursor.return_value.fetchall.return_value = [
        ("ESH6", "1m", 500, "2026-03-01", "2026-03-06"),
    ]

    ok, report = verify_dataset(conn)

    assert ok is True
    assert "ESH6" in report


def test_verify_dataset_fails_when_signal_ledger_empty():
    """verify_dataset returns False when signal_ledger has 0 rows."""
    from production.scripts.pipeline_reset import verify_dataset

    conn = MagicMock()
    conn.cursor.return_value.__enter__ = lambda s: s
    conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
    conn.cursor.return_value.fetchone.side_effect = [(0,), (0,), (0,)]
    conn.cursor.return_value.fetchall.return_value = []

    ok, report = verify_dataset(conn)

    assert ok is False
    assert "EMPTY" in report or "0" in report
```

**Step 2: Run tests — expect failure**

```bash
.venv/bin/pytest tests/unit/scripts/test_pipeline_reset.py -k "verify" -v
```

**Step 3: Implement `verify_dataset`**

```python
def verify_dataset(conn: Any) -> tuple[bool, str]:
    """Check that the reset produced non-empty tables.

    Returns (ok, report_string).
    """
    lines = ["Verification:"]
    ok = True

    for table in ["signal_ledger", "intelligence_features", "market_data_ohlcv"]:
        count = _row_count(conn, table)
        status = "OK" if count > 0 else "EMPTY ⚠"
        if count == 0:
            ok = False
        lines.append(f"  {table:<35} {count:>10,} rows  [{status}]")

    # Per-symbol/TF signal breakdown
    with conn.cursor() as cur:
        cur.execute("""
            SELECT symbol, timeframe, count(*) as n,
                   min(timestamp)::date, max(timestamp)::date
            FROM signal_ledger
            GROUP BY symbol, timeframe
            ORDER BY symbol, timeframe
        """)
        rows = cur.fetchall()

    if rows:
        lines.append("\n  Signals per symbol/TF:")
        for sym, tf, n, min_dt, max_dt in rows:
            lines.append(f"    {sym:<8} {tf:<4}  {n:>6,} signals  ({min_dt} → {max_dt})")
    else:
        lines.append("\n  No signals — check replay completed successfully")
        ok = False

    return ok, "\n".join(lines)
```

**Step 4: Run all tests**

```bash
.venv/bin/pytest tests/unit/scripts/test_pipeline_reset.py -v
```
Expected: All 10 tests PASS.

**Step 5: Commit**

```bash
git add production/scripts/pipeline_reset.py tests/unit/scripts/test_pipeline_reset.py
git commit -m "feat(reset): verification step with per-symbol signal breakdown"
```

---

## Task 5: Full orchestration

**Files:**
- Modify: `production/scripts/pipeline_reset.py`

Wire all stages into `main()`. No new tests — covered by manual run.

**Step 1: Replace `main()` with full orchestration**

Replace the existing `main()` with:

```python
_STOP_SERVICES = [
    "indicagent-signal-generator",
    "indicagent-signal-lifecycle",
    "indicagent-market-analysis",
    "indicagent-feature-writer",
    "indicagent-ai-narrative",
]

_START_SERVICES = [
    "indicagent-market-analysis",
    "indicagent-feature-writer",
    "indicagent-signal-generator",
    "indicagent-signal-lifecycle",
    "indicagent-ai-narrative",
]


def _pause_for_services(action: str, services: list[str]) -> None:
    """Print service commands and wait for user to press Enter."""
    verb = "stop" if action == "stop" else "start"
    print(f"\n{'='*50}")
    print(f"{action.upper()} pipeline services before continuing:")
    print()
    for svc in services:
        print(f"  sudo systemctl {verb} {svc}")
    print()
    input(f"Press Enter when services are {verb}ped...")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Pipeline Reset — clear and regenerate canonical IndicAgent dataset"
    )
    parser.add_argument("--keep-ohlcv", action="store_true",
                        help="Skip IBKR re-fetch; replay from existing market_data_ohlcv")
    parser.add_argument("--symbols", default=None,
                        help="Comma-separated symbols (default: all active contracts)")
    parser.add_argument("--days", type=int, default=35,
                        help="Days of 1m history to fetch (default: 35)")
    parser.add_argument("--clear-llm", action="store_true",
                        help="Also truncate llm_calls and llm_model_scores")
    parser.add_argument("--dry-run", action="store_true",
                        help="Show what would be cleared; exit without touching anything")
    parser.add_argument("--yes", action="store_true",
                        help="Skip confirmation prompt")
    parser.add_argument("--client-id", type=int, default=56,
                        help="IBKR client ID (default: 56)")
    args = parser.parse_args()

    settings = Settings()
    t_start = time.time()

    # --- Preflight ---
    db_conn = connect_db(settings)
    print("\nPipeline Reset")
    print("=" * 50)
    if args.dry_run:
        print("DRY RUN — nothing will be modified\n")
    print(build_preflight_summary(db_conn, args.keep_ohlcv, args.clear_llm))
    print()

    if args.dry_run:
        db_conn.close()
        return

    if not args.yes:
        answer = input("This cannot be undone. Type YES to continue: ")
        if answer.strip() != "YES":
            print("Aborted.")
            db_conn.close()
            return

    # --- Stage 1: Stop services ---
    _pause_for_services("stop", _STOP_SERVICES)

    # --- Stage 2: Clear Redis ---
    print("\n[1/5] Clearing Redis streams...")
    r = redis.Redis.from_url(settings.redis_url)
    n_keys = clear_redis_streams(r, settings.env_prefix)
    print(f"      Deleted {n_keys} stream keys")

    # --- Stage 3: Truncate DB ---
    print("\n[2/5] Truncating DB tables...")
    cleared = truncate_tables(db_conn, args.keep_ohlcv, args.clear_llm)
    for t in cleared:
        print(f"      TRUNCATED {t}")

    # --- Stage 4: Fetch OHLCV ---
    contracts = settings.contracts
    if args.symbols:
        wanted = {s.strip() for s in args.symbols.split(",") if s.strip()}
        contracts = [c for c in contracts if c.symbol in wanted]
        if not contracts:
            print(f"No matching contracts for: {args.symbols}")
            db_conn.close()
            return

    if not args.keep_ohlcv:
        print("\n[3/5] Fetching OHLCV from IBKR...")
        import asyncio
        from production.scripts.historical_backfill import (
            _TF_FETCH_CONFIG,
            store_bars,
        )
        from src.providers import IBKRProvider
        provider = IBKRProvider(
            host=settings.ib_host,
            port=settings.ib_port,
            client_id=args.client_id,
        )
        if not asyncio.run(provider.connect()):
            print("  Cannot connect to TWS — skipping fetch (will replay existing OHLCV)")
        else:
            end_dt = datetime.now(tz=UTC)
            fetch_tfs = list(_TF_FETCH_CONFIG.keys())
            for instrument in contracts:
                try:
                    qualified = asyncio.run(provider.qualify_instrument(instrument))
                    if not qualified:
                        print(f"  {instrument.symbol}: qualify failed — skipping")
                        continue
                    for tf in fetch_tfs:
                        fetch_days, use_continuous = _TF_FETCH_CONFIG[tf]
                        if tf == "1m":
                            fetch_days = args.days
                        bars = asyncio.run(provider.fetch_historical_bars(
                            instrument=qualified,
                            end_dt=end_dt,
                            duration_days=fetch_days,
                            bar_size=tf,
                            use_continuous=use_continuous,
                        ))
                        if bars:
                            n = store_bars(db_conn, bars, instrument.symbol, tf)
                            print(f"  {instrument.symbol}/{tf}: stored {n:,} bars")
                except Exception as e:
                    print(f"  {instrument.symbol}: fetch error — {e}")
            asyncio.run(provider.disconnect())
    else:
        print("\n[3/5] Skipping IBKR fetch (--keep-ohlcv)")

    # --- Stage 5: Replay pipeline ---
    print("\n[4/5] Replaying I1→I7 pipeline...")
    for contract in contracts:
        counts = replay_symbol(
            symbol=contract.symbol,
            db_conn=db_conn,
            timeframes=DEFAULT_TIMEFRAMES,
        )
        for tf, n in counts.items():
            print(f"  {contract.symbol}/{tf}: {n:,} signals")

    # --- Stage 6: Verify ---
    print("\n[5/5] Verifying dataset...")
    ok, report = verify_dataset(db_conn)
    print(report)
    if not ok:
        print("\n⚠  Verification failed — check above for empty tables")

    db_conn.close()

    # --- Restart services ---
    _pause_for_services("start", _START_SERVICES)

    # --- Summary ---
    elapsed = time.time() - t_start
    m, s = divmod(int(elapsed), 60)
    print(f"\n{'='*50}")
    print(f"Pipeline Reset {'Complete ✓' if ok else 'Complete with warnings ⚠'}")
    print(f"Elapsed: {m}m {s}s")
    print()
```

**Step 2: Run lint**

```bash
.venv/bin/ruff check production/scripts/pipeline_reset.py --fix
```
Expected: 0 errors.

**Step 3: Smoke test dry-run**

```bash
.venv/bin/python production/scripts/pipeline_reset.py --dry-run
```
Expected: Prints preflight summary with current row counts, exits without prompting.

**Step 4: Run full test suite**

```bash
.venv/bin/pytest tests/unit/scripts/test_pipeline_reset.py -v
```
Expected: All 10 tests PASS.

**Step 5: Commit**

```bash
git add production/scripts/pipeline_reset.py
git commit -m "feat(reset): full orchestration — service pauses, Redis clear, truncate, replay, verify"
```

---

## Task 6: Lint, final test run, and update docs

**Files:**
- Modify: `docs/cheatsheet.md`

**Step 1: Ruff full project**

```bash
.venv/bin/ruff check . --fix
```
Expected: 0 errors.

**Step 2: Full test suite**

```bash
.venv/bin/pytest tests/unit/ -v --tb=short 2>&1 | tail -20
```
Expected: All existing tests PASS + 10 new tests PASS.

**Step 3: Add to cheatsheet**

In `docs/cheatsheet.md`, find the "Core Commands" or "Scripts" section and add:

```markdown
**Pipeline Reset:**
`.venv/bin/python production/scripts/pipeline_reset.py --dry-run`  — preview
`.venv/bin/python production/scripts/pipeline_reset.py --keep-ohlcv`  — fast reset (replay only)
`.venv/bin/python production/scripts/pipeline_reset.py`  — full reset (re-fetch + replay)
```

**Step 4: Commit**

```bash
git add docs/cheatsheet.md
git commit -m "docs: add pipeline_reset to cheatsheet"
```
