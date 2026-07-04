# Backfill Signal Integrity — Design

**Date:** 2026-06-06
**Status:** archived
**Type:** Design Specification
**Last Updated:** 2026-06-08
**Resolution:** Implemented — see commits around 2026-06-06

---

## Execution Summary (2026-06-08)

This design was implemented via commits:
- `1ef126b2` feat(backfill): add calibration and perf_weights loaders
- `cbd3b7fd` feat(backfill): thread calibration_curves and perf_weights into run_i7_and_persist
- `31f7d22e` feat(backfill): thread calibration through replay_symbol
- `518035d0` feat(backfill): load calibration in worker and single-worker paths
- `c6c000c6` feat(backfill): add integrity gate asserting was_selected and signal_id invariants

The backfill integrity fix is now production code. This document is preserved for historical reference.

---



## Problem

Multiple partial backfill runs using `uuid4()` signal IDs stacked duplicate rows in
`signal_ledger`. Because every run generated a fresh random ID, `ON CONFLICT DO NOTHING`
never fired. The result: ~280k signals across 6 symbols where ESM6/1m has 13,480 bars
with 2 winners and ESM6/15m has 1,315 bars with up to 3 winners. The `was_selected = TRUE`
invariant — at most one winner per (symbol, tf, bar_ts) — is broken.

Secondary issue: the backfill calls `aggregate()` without `calibration_curves` or
`perf_weights`. Both tables are empty today so this is a no-op, but it is a structural
divergence from the live pipeline that will produce miscalibrated signals once training data
exists.

`make_signal_id()` (deterministic SHA-256 hash of bar OHLCV + plugin + direction) was
already shipped in the prior session. The ID primitive is correct. The DB is dirty.

## Invariants

These must hold after every `--replay-only` run:

1. Every `signal_id` in `signal_ledger` is globally unique.
2. Every `(symbol, timeframe, timestamp)` tuple has at most one `was_selected = TRUE` row.

Violation of either invariant means the data is not usable for training or analysis.

## Design

**Scope:** `production/scripts/historical_backfill.py` only. No schema changes, no live
pipeline changes, no new services. Eight surgical changes.

### Change 1-2: Calibration loaders

Two new functions, called once per worker after the DB connection opens:

```python
def _load_calibration_curves(conn) -> dict[tuple[str, str], tuple[list, list]]:
    """Load isotonic calibration curves from DB. Returns {} when table is empty."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT setup_plugin, timeframe, curve_data FROM calibration_curves"
        )
        rows = cur.fetchall()
    return {
        (plugin, tf): (data["breakpoints"], data["values"])
        for plugin, tf, data in rows
    }

def _load_perf_weights(conn) -> dict[str, tuple[float, int]]:
    """Load performance multipliers for setups with sample_size >= 30."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT setup_plugin, perf_multiplier, sample_size "
            "FROM setup_performance WHERE sample_size >= 30"
        )
        rows = cur.fetchall()
    return {plugin: (mult, size) for plugin, mult, size in rows}
```

Both return empty dicts when their tables are empty — `aggregate()` handles `None` and `{}`
identically (falls back to raw confidence ranking).

### Change 3: `_replay_worker`

After `conn = psycopg2.connect(...)`, load calibration and perf, pass to `replay_symbol`:

```python
calibration_curves = _load_calibration_curves(conn)
perf_weights = _load_perf_weights(conn)
counts = replay_symbol(
    symbol, conn, timeframes, since=since_dt, skip_signals=skip_signals,
    calibration_curves=calibration_curves, perf_weights=perf_weights,
)
```

### Change 4: `replay_symbol`

Add two optional kwargs, thread them into `run_i7_and_persist`:

```python
def replay_symbol(
    symbol, db_conn, timeframes=None, since=None, skip_signals=False,
    calibration_curves=None, perf_weights=None,
) -> dict[str, int]:
```

Pass `calibration_curves=calibration_curves, perf_weights=perf_weights` into every
`run_i7_and_persist(...)` call.

### Change 5: `run_i7_and_persist`

Add two optional kwargs, pass to `aggregate()`:

```python
def run_i7_and_persist(
    ...,
    calibration_curves=None,
    perf_weights=None,
) -> int:
```

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

### Change 6: Single-worker path in `main`

Before calling `replay_symbol` in the `args.workers == 1` branch, load from `db_conn`:

```python
calibration_curves = _load_calibration_curves(db_conn)
perf_weights = _load_perf_weights(db_conn)
counts = replay_symbol(
    contract.symbol, db_conn, timeframes, since=since_dt,
    calibration_curves=calibration_curves, perf_weights=perf_weights,
)
```

### Change 7: `_assert_backfill_integrity`

New function. Hard-fails with `sys.exit(1)` on any violation:

```python
def _assert_backfill_integrity(conn, symbols: list[str]) -> None:
    """Assert was_selected and signal_id invariants. Exits non-zero on violation."""
    with conn.cursor() as cur:
        cur.execute("""
            SELECT symbol, timeframe, timestamp, COUNT(*) AS winner_count
            FROM signal_ledger
            WHERE symbol = ANY(%s) AND was_selected = TRUE
            GROUP BY symbol, timeframe, timestamp
            HAVING COUNT(*) > 1
            ORDER BY winner_count DESC LIMIT 20
        """, (symbols,))
        violations = cur.fetchall()

    if violations:
        print(f"\n[INTEGRITY FAIL] was_selected > 1 — {len(violations)} bars:")
        for sym, tf, ts, cnt in violations:
            print(f"  {sym}/{tf} @ {ts}: {cnt} winners")
        sys.exit(1)

    with conn.cursor() as cur:
        cur.execute("""
            SELECT COUNT(*) FROM (
                SELECT signal_id FROM signal_ledger WHERE symbol = ANY(%s)
                GROUP BY signal_id HAVING COUNT(*) > 1
            ) dups
        """, (symbols,))
        dup_count = cur.fetchone()[0]

    if dup_count:
        print(f"\n[INTEGRITY FAIL] {dup_count} duplicate signal_ids")
        sys.exit(1)

    print("\n[INTEGRITY PASS] was_selected invariant holds. signal_ids unique.")
```

### Change 8: Call integrity gate in `main`

After `print(f"\nStage 2 complete: {grand_total} total signals...")`:

```python
_assert_backfill_integrity(db_conn, [c.symbol for c in contracts])
```

## Operational Protocol

```bash
# Wipe dirty data and rebuild cleanly with deterministic signal IDs
python production/scripts/historical_backfill.py --replay-only --clean --workers 8

# Script must print before exit:
# [INTEGRITY PASS] was_selected invariant holds. signal_ids unique.
```

The integrity gate runs on every `--replay-only` invocation going forward — not just this
one. Silent corruption cannot accumulate again.

## Bootstrap Sequence (for reference)

For future sessions when calibration training is implemented:

```
1. Backfill OHLCV → market_data_ohlcv          (done)
2. Backfill features → intelligence_features    (done)
3. Backfill signals → signal_ledger             (this spec)
4. Train calibration → calibration_curves       (future)
5. Train perf weights → setup_performance       (future)
6. Optional: replay signals with calibration    (future, only if calibrated_confidence
                                                 matters for training label quality)
```

Steps 4-6 require step 3 to be verified clean first. The integrity gate is the gate between
step 3 and step 4.

## Out of Scope

- Kalman/GARCH cold-start bias in backfill (acknowledged known bias; separate problem)
- Calibration training (step 4 above)
- Any changes to the live intelligence pipeline
- New tables, daemons, or services
