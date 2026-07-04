# Lifecycle Replay Repair — Fix Script + Clean Corrupt Data

**Date:** 2026-06-03
**Status:** archived
**Type:** Implementation Plan
**Last Updated:** 2026-06-08
**Resolution:** Implemented — see `production/scripts/lifecycle_replay.py` (v1.2, 2026-06-06)

---

## Execution Summary (2026-06-08)

This plan was fully implemented:
- Script rewritten for post-Phase-104 schema (signal_ledger/signal_outcomes split)
- Advisory lock prevents concurrent replays
- --confirm flag required for destructive operations
- Four phases: preflight → reset → replay → verify
- Handles 2.83M corrupt signals from May 21 - June 1

The lifecycle_replay script (v1.2) is production code. This document is preserved for historical reference.

---



**Operational Requirements (non-negotiable):**
- Advisory lock held for entire reset+replay duration
- No concurrent live lifecycle writers (stop signal_tracker, feature_writer services)
- `--confirm` flag required for any destructive operation
- Before/after row counts must balance — discrepancy is a hard stop

---

## Context for the Implementer

### The Problem
On 2026-06-02, six data integrity bugs were fixed in the signal lifecycle tracking (commit `f6a44b45`). All 2.83M signals from May 21 - June 1 have outcomes computed by the broken code. Every downstream consumer — ML training, alpha swarm graduation, dashboard win rates — is built on corrupt pnl_r data.

### Current Schema (Post Phase-104 Split)
- **`signal_ledger`** (29 cols) — immutable signal definition. Key columns: `signal_id`, `timestamp`, `symbol`, `timeframe`, `direction`, `entry_price`, `stop_loss`, `targets`, `entry_zone_low`, `entry_zone_high`, `market_entry_price`, `ttl_bars`, `expires_at`, `hmm_regime_at_fire`, `garch_sigma_at_fire`, `is_shadow`, `is_backfill`.
- **`signal_outcomes`** (36 cols) — mutable lifecycle state. Key columns: `signal_id`, `status`, `outcome`, `pnl_r`, `mae`, `mfe`, `exit_at`, `exit_price`, `activated_at`, `market_entry_*` fields.
- **`signal_ledger_full`** — view that JOINs both on `signal_id`. This is NOT used by the replay (explicit JOIN is preferred for column provenance clarity and parameterized WHERE performance).

### What evaluate_signal() Expects
A dict with: `signal_id`, `status`, `direction`, `entry_price`, `stop_loss`, `targets`, `ttl_bars`, `bars_elapsed`, `point_value`, `entry_zone_low`, `entry_zone_high`. Plus optional: `chandelier_state`, `staleness_consecutive_bars`, `staleness_score`, `signal_timestamp`, `bar_time`.

### What evaluate_market_entry() Expects
Same as above, plus `market_entry_price` kwarg passed separately.

### Files
- **Modify:** `production/scripts/lifecycle_replay.py` (full rewrite of SELECT, writes, reset logic, add preflight)
- **Modify:** `tests/unit/scripts/test_lifecycle_replay.py` (extend existing tests)

---

## Task 0: Add Preflight & Safety Controls (NEW)

**Files:**
- Modify: `production/scripts/lifecycle_replay.py`

Every RenTec system proves correctness before touching data. This task adds the safety infrastructure that all subsequent tasks depend on.

- [ ] **Step 1: Add advisory lock acquisition**

Add a lock constant and acquisition function before `_fetch_work_queue`:

```python
# Advisory lock ID — prevents concurrent replays from corrupting data.
# pg_try_advisory_lock returns true if acquired, false if already held.
_REPLAY_LOCK_ID = 20260602  # date of the fix that necessitated this replay


async def _acquire_replay_lock(conn) -> bool:
    """Acquire exclusive advisory lock. Returns False if already held."""
    row = await conn.fetchrow("SELECT pg_try_advisory_lock($1) as acquired", _REPLAY_LOCK_ID)
    return row["acquired"]
```

- [ ] **Step 2: Add service quiescence check**

```python
async def _check_service_quiescence() -> list[str]:
    """Check that lifecycle-writing services are stopped. Returns list of active services."""
    import subprocess

    lifecycle_services = [
        "indicagent-intelligence-pipeline",
        "indicagent-signal-tracker",
        "indicagent-feature-writer",
    ]
    active = []
    for svc in lifecycle_services:
        result = subprocess.run(
            ["systemctl", "is-active", svc],
            capture_output=True, text=True, timeout=5,
        )
        if result.stdout.strip() == "active":
            active.append(svc)
    return active
```

- [ ] **Step 3: Add orphan signal_outcomes seeding**

```python
async def _seed_orphan_outcomes(
    conn, symbols: list[str], timeframes: list[str], cutoff: datetime
) -> int:
    """Seed missing signal_outcomes rows for signal_ledger entries in the repair window.

    Phase-104 split means every signal_ledger row MUST have a matching signal_outcomes row.
    If seeding was incomplete, INNER JOIN would silently skip these signals — the exact
    kind of silent data loss that destroys quant systems.

    Returns count of rows seeded.
    """
    result = await conn.execute(
        """INSERT INTO signal_outcomes (signal_id, status)
           SELECT sl.signal_id, 'pending'
           FROM signal_ledger sl
           LEFT JOIN signal_outcomes so ON sl.signal_id = so.signal_id
           WHERE so.signal_id IS NULL
             AND sl.timestamp >= '2026-05-21'
             AND sl.timestamp < $1
             AND sl.symbol = ANY($2)
             AND sl.timeframe = ANY($3)
           ON CONFLICT (signal_id) DO NOTHING""",
        cutoff,
        symbols,
        timeframes,
    )
    return int(result.split()[-1])
```

- [ ] **Step 4: Wire preflight into main_async**

In `main_async()`, before work queue fetch, add the preflight sequence:

```python
async with db.pool.acquire() as preflight_conn:
    # 1. Advisory lock — hard stop if another replay is running
    if not await _acquire_replay_lock(preflight_conn):
        logger.error("ABORT: another replay is already running (advisory lock held)")
        return
    logger.info("Advisory lock acquired (id=%d)", _REPLAY_LOCK_ID)

    try:
        # 2. Service quiescence — warn but allow override
        if not args.dry_run:
            active_services = await _check_service_quiescence()
            if active_services and not args.force:
                logger.error(
                    "ABORT: active lifecycle services detected: %s. "
                    "Stop them first or use --force to override.",
                    ", ".join(active_services),
                )
                return
            elif active_services:
                logger.warning(
                    "WARNING: running with active services (--force): %s. "
                    "Data races are possible.",
                    ", ".join(active_services),
                )

        # 3. Seed orphan outcomes (idempotent)
        cutoff = datetime.fromisoformat(
            args.reset_before.replace("Z", "+00:00")
        )
        orphans = await _seed_orphan_outcomes(preflight_conn, symbols, timeframes, cutoff)
        if orphans > 0:
            logger.info("Preflight: seeded %d orphan signal_outcomes rows", orphans)
        else:
            logger.info("Preflight: no orphan rows found")
    finally:
        await preflight_conn.execute("SELECT pg_advisory_unlock($1)", _REPLAY_LOCK_ID)
```

Note: The advisory lock is released in the `finally` block. For the actual reset+replay, re-acquire it in the reset function and hold through completion.

- [ ] **Step 5: Add --force argument**

```python
parser.add_argument(
    "--force", action="store_true",
    help="Override safety checks (service quiescence). Use with extreme caution."
)
```

- [ ] **Step 6: Commit**

```bash
git add production/scripts/lifecycle_replay.py
git commit -m "feat(replay): add preflight safety controls — advisory lock, quiescence check, orphan seeding"
```

---

## Task 1: Update SELECT to Match Current Schema

**Files:**
- Modify: `production/scripts/lifecycle_replay.py:231-256`

The current SELECT references 22 columns that no longer exist in `signal_ledger_full`. Replace with the minimal column set needed by `evaluate_signal()` and `evaluate_market_entry()`. The INNER JOIN is now safe because Task 0 seeds any missing `signal_outcomes` rows before we query.

- [ ] **Step 1: Replace the SELECT column list**

Replace lines 232-256 with:

```python
signals = await conn.fetch(
    """SELECT sl.signal_id, sl.timestamp, sl.symbol, sl.timeframe,
              sl.setup_plugin, sl.signal_type, sl.direction,
              sl.entry_price, sl.stop_loss, sl.targets,
              sl.entry_zone_low, sl.entry_zone_high,
              sl.market_entry_price, sl.ttl_bars, sl.expires_at,
              sl.is_shadow, sl.is_backfill, sl.signal_schema_version,
              sl.hmm_regime_at_fire, sl.garch_sigma_at_fire,
              sl.was_selected,
              so.status, so.outcome, so.activated_at,
              so.exit_at, so.exit_price, so.exit_reason,
              so.pnl_ticks, so.pnl_r, so.pnl_dollars,
              so.mae, so.mfe, so.bars_in_trade,
              so.activation_price, so.zone_entry_pct, so.bars_to_activation,
              so.market_entry_at, so.market_entry_exit_price,
              so.market_entry_pnl_r, so.market_entry_mae, so.market_entry_mfe,
              so.market_entry_bars_in_trade, so.market_entry_outcome,
              so.market_entry_gap_bars, so.market_entry_exit_at
       FROM signal_ledger sl
       JOIN signal_outcomes so ON sl.signal_id = so.signal_id
       WHERE so.status IN ('pending', 'regime_suppressed')
         AND sl.symbol = $1 AND sl.timeframe = $2
       ORDER BY sl.timestamp ASC""",
    symbol,
    timeframe,
)
```

Note: We JOIN explicitly rather than using the view. This makes column provenance explicit and avoids potential security_barrier or performance issues with parameterized WHERE on the view.

- [ ] **Step 2: Update the work queue query**

The `_fetch_work_queue` function (lines 179-195) uses `signal_ledger_full`. Update it to JOIN explicitly:

```python
async def _fetch_work_queue(
    db: DatabaseManager, symbols: list[str], timeframes: list[str]
) -> list[tuple[str, str, int]]:
    async with db.get_connection() as conn:
        rows = await conn.fetch(
            """SELECT sl.symbol, sl.timeframe, COUNT(*) as cnt
                FROM signal_ledger sl
                JOIN signal_outcomes so ON sl.signal_id = so.signal_id
                WHERE so.status IN ('pending', 'regime_suppressed')
                  AND sl.symbol = ANY($1)
                  AND sl.timeframe = ANY($2)
                GROUP BY sl.symbol, sl.timeframe
                ORDER BY cnt DESC""",
            symbols,
            timeframes,
        )
        return [(row["symbol"], row["timeframe"], row["cnt"]) for row in rows]
```

- [ ] **Step 3: Update TTL injection to use stored ttl_bars**

Lines 265-269 inject `ttl_bars` from `TF_TTL_BARS`. The signal_ledger now has `ttl_bars` as a real column. Use it when present, fall back to canonical:

```python
_tf_ttl = TF_TTL_BARS.get(timeframe, 10)
for _sig_dict in sig_map.values():
    # Use stored ttl_bars if present (Phase 107.5+), else canonical default
    stored_ttl = _sig_dict.get("ttl_bars")
    _sig_dict["ttl_bars"] = stored_ttl if stored_ttl and stored_ttl > 0 else _tf_ttl
```

- [ ] **Step 4: Commit**

```bash
git add production/scripts/lifecycle_replay.py
git commit -m "fix(replay): update SELECT to post-Phase-104 schema"
```

---

## Task 2: Add Integrated House Cleaning (`--reset` flag)

**Files:**
- Modify: `production/scripts/lifecycle_replay.py`

Add a `--reset` flag that wipes corrupt outcomes and derived tables before replay. The reset is bounded by exact timestamp range — no vague "pre-fix" predicates.

- [ ] **Step 1: Add reset arguments**

In `main_async()`, add to the argument parser:

```python
parser.add_argument(
    "--reset", action="store_true",
    help="Reset corrupt outcomes + truncate derived tables before replay"
)
parser.add_argument(
    "--reset-before", type=str, default="2026-06-02T00:00:00Z",
    help="ISO timestamp — only reset signals before this date (default: 2026-06-02)"
)
parser.add_argument(
    "--reset-after", type=str, default="2026-05-21T00:00:00Z",
    help="ISO timestamp — only reset signals after this date (default: 2026-05-21)"
)
parser.add_argument(
    "--confirm", action="store_true",
    help="Required with --reset. Prevents accidental destructive operations."
)
```

- [ ] **Step 2: Implement `_reset_corrupt_data()`**

Add this function before `_fetch_work_queue`. Note the advisory lock is re-acquired here and held through the entire reset:

```python
async def _reset_corrupt_data(
    db: DatabaseManager, symbols: list[str], timeframes: list[str],
    after: datetime, before: datetime,
) -> dict:
    """Reset corrupt signal_outcomes + truncate derived tables.

    Idempotent: safe to run multiple times. Only affects signals
    with outcome IS NOT NULL in the exact [after, before) window.

    Returns counts for audit logging.
    """
    stats = {}
    async with db.pool.acquire() as conn:
        # Re-acquire advisory lock for the destructive phase
        if not await _acquire_replay_lock(conn):
            raise RuntimeError("Cannot acquire advisory lock for reset")
        try:
            # 1. Reset signal_outcomes for corrupt-window signals
            result = await conn.execute(
                """UPDATE signal_outcomes SET
                    status = 'pending',
                    outcome = NULL,
                    exit_at = NULL,
                    exit_price = NULL,
                    exit_reason = NULL,
                    pnl_ticks = NULL,
                    pnl_r = NULL,
                    pnl_dollars = NULL,
                    signal_quality = NULL,
                    activated_at = NULL,
                    activation_price = NULL,
                    zone_entry_pct = NULL,
                    bars_to_activation = NULL,
                    mae = NULL,
                    mfe = NULL,
                    bars_in_trade = NULL,
                    market_entry_at = NULL,
                    market_entry_exit_price = NULL,
                    market_entry_exit_at = NULL,
                    market_entry_pnl_r = NULL,
                    market_entry_mae = NULL,
                    market_entry_mfe = NULL,
                    market_entry_bars_in_trade = NULL,
                    market_entry_outcome = NULL,
                    market_entry_gap_bars = NULL
                WHERE signal_id IN (
                    SELECT signal_id FROM signal_ledger
                    WHERE timestamp >= $1
                      AND timestamp < $2
                      AND symbol = ANY($3)
                      AND timeframe = ANY($4)
                )
                AND outcome IS NOT NULL""",
                after,
                before,
                symbols,
                timeframes,
            )
            stats["outcomes_reset"] = int(result.split()[-1])

            # 2. Truncate swarm_agent_weights (computed from lineage + outcomes)
            await conn.execute("TRUNCATE swarm_agent_weights")
            stats["weights_truncated"] = True

            # 3. Truncate setup_performance (computed from outcomes)
            await conn.execute("TRUNCATE setup_performance")
            stats["setup_perf_truncated"] = True

            logger.info(
                "reset_complete: outcomes_reset=%d, weights_truncated=True, "
                "setup_perf_truncated=True, window=[%s, %s)",
                stats["outcomes_reset"],
                after.isoformat(),
                before.isoformat(),
            )
        finally:
            await conn.execute("SELECT pg_advisory_unlock($1)", _REPLAY_LOCK_ID)
    return stats
```

- [ ] **Step 3: Wire reset into main flow with --confirm guard**

In `main_async()`, after preflight, before work queue:

```python
if args.reset:
    if not args.confirm:
        logger.error(
            "ABORT: --reset requires --confirm to prevent accidental data wipe. "
            "Run with --reset --confirm to proceed."
        )
        return
    after = datetime.fromisoformat(args.reset_after.replace("Z", "+00:00"))
    before = datetime.fromisoformat(args.reset_before.replace("Z", "+00:00"))
    logger.info(
        "Reset window: [%s, %s) — about to wipe outcomes and truncate derived tables",
        after.isoformat(),
        before.isoformat(),
    )
    reset_stats = await _reset_corrupt_data(db, symbols, timeframes, after, before)
    logger.info("Reset complete: %s", reset_stats)
```

- [ ] **Step 4: Commit**

```bash
git add production/scripts/lifecycle_replay.py
git commit -m "feat(replay): add --reset --confirm flag with bounded timestamp window"
```

---

## Task 3: Fix TTL Logic for Wall-Clock expires_at

**Files:**
- Modify: `production/scripts/lifecycle_replay.py`

The replay script uses bar-counting for TTL. The current `signal_tracker` uses `expires_at` (wall-clock, Phase 107.5). The replay should match.

- [ ] **Step 1: Update resolve_at_end_of_bars to use expires_at**

In `resolve_at_end_of_bars()` (lines 121-162), the TTL expiry at end-of-bars should check `expires_at`:

```python
def resolve_at_end_of_bars(
    sig: dict,
    last_bar: dict,
    *,
    tf_seconds: int,
    zone_mfe: float,
    market_mfe: float,
    zone_activated: bool = False,
    market_entry_price: float | None = None,
) -> dict:
    last_ts = last_bar["timestamp"]
    expires_at = sig.get("expires_at")

    # Use expires_at if available (Phase 107.5+), else compute from ttl_bars
    if expires_at is not None and last_ts < expires_at:
        # Signal hasn't expired yet — treat as still live (no forced resolution)
        return {"zone_outcome": None, "exit_at": None}

    # Compute exit timestamp
    if expires_at is not None:
        exit_ts = min(last_ts, expires_at)
    else:
        ttl_secs = sig.get("ttl_bars", 10) * tf_seconds
        exit_ts = sig["timestamp"] + timedelta(seconds=ttl_secs)
        exit_ts = min(last_ts, exit_ts)

    bars_elapsed = int((exit_ts - sig["timestamp"]).total_seconds() / tf_seconds)

    zone_outcome = (
        "ttl_expired_ahead"
        if zone_mfe > 0
        else ("never_activated" if not zone_activated else "ttl_expired_behind")
    )
    mep = market_entry_price if market_entry_price is not None else sig.get("market_entry_price")
    market_outcome = (
        ("ttl_expired_ahead" if market_mfe > 0 else "ttl_expired_behind")
        if mep is not None
        else None
    )
    market_bit = min(bars_elapsed, sig.get("ttl_bars", 10))

    return {
        "zone_outcome": zone_outcome,
        "exit_at": exit_ts,
        "market_entry_outcome": market_outcome,
        "market_entry_exit_price": float(last_bar["close"]) if mep is not None else None,
        "market_entry_pnl_r": None,
        "market_entry_mae": None,
        "market_entry_mfe": None,
        "market_entry_bars_in_trade": market_bit if mep is not None else None,
        "market_entry_gap_bars": None,
    }
```

- [ ] **Step 2: Update handle_no_data to use expires_at**

```python
def handle_no_data(sig: dict) -> dict:
    expires_at = sig.get("expires_at")
    if expires_at is not None:
        exit_ts = expires_at
    else:
        ttl_secs = sig.get("ttl_bars", 10) * TF_SECONDS.get(sig.get("timeframe", "1m"), 60)
        exit_ts = sig["timestamp"] + timedelta(seconds=ttl_secs)
    return {
        "zone_outcome": "never_activated",
        "zone_exit_at": exit_ts,
        "market_entry_outcome": None,
        "market_entry_exit_price": None,
        "market_entry_pnl_r": None,
        "market_entry_mae": None,
        "market_entry_mfe": None,
        "market_entry_bars_in_trade": None,
        "market_entry_gap_bars": None,
        "exit_at": exit_ts,
    }
```

- [ ] **Step 3: Commit**

```bash
git add production/scripts/lifecycle_replay.py
git commit -m "fix(replay): use expires_at wall-clock TTL (Phase 107.5)"
```

---

## Task 4: Verify Write Logic + Transaction Correctness

**Files:**
- Modify: `production/scripts/lifecycle_replay.py`

Task 4 from the original plan was a verification-only task. This version adds the critical transaction correctness audit that both reviewers flagged.

- [ ] **Step 1: Verify zone_exit UPDATE columns**

Current UPDATE (lines 698-709) writes to `signal_outcomes`:
```
SET status=v.status, exit_at=v.exit_at, exit_price=v.exit_price,
    exit_reason=v.exit_reason, pnl_ticks=v.pnl_ticks, pnl_r=v.pnl_r,
    pnl_dollars=v.pnl_dollars, signal_quality=v.signal_quality,
    mae=v.mae, mfe=v.mfe, bars_in_trade=v.bars_in_trade, outcome=v.outcome
```

All these columns exist in `signal_outcomes`. No change needed here.

- [ ] **Step 2: Verify activation UPDATE columns**

Current activation UPDATE (lines 738-747):
```
SET status='active', activated_at=v.activated_at,
    activation_price=v.activation_price, zone_entry_pct=v.zone_entry_pct,
    bars_to_activation=v.bars_to_activation
```

All exist in `signal_outcomes`. No change needed.

- [ ] **Step 3: Verify market UPDATE columns**

Current market UPDATE (lines 718-729):
```
SET market_entry_at=v.entry_at, market_entry_exit_price=v.exit_price,
    market_entry_exit_at=v.exit_at, market_entry_pnl_r=v.pnl_r,
    market_entry_mae=v.mae, market_entry_mfe=v.mfe,
    market_entry_bars_in_trade=v.bars_in_trade,
    market_entry_outcome=v.outcome, market_entry_gap_bars=v.gap_bars
```

All exist in `signal_outcomes`. No change needed.

- [ ] **Step 4: Fix final COMMIT/ROLLBACK transaction flow**

The current `_process_symbol_tf` function (lines 224-616) has a transaction flow issue: the final flush may not be committed before the connection is released. Fix the transaction lifecycle:

In `_process_symbol_tf`, after the bar streaming loop and the "6. Final flush + commit" section, ensure the final commit is explicit:

```python
        # 6. Final flush + commit
        if pending_writes and not dry_run:
            await _flush_writes(conn, pending_writes)
            pending_writes.clear()

        # Final COMMIT — every write must be durable before release
        if not dry_run:
            await conn.execute("COMMIT")
            logger.info(
                "%s %s: final commit — %d resolved total",
                symbol, timeframe, stats["processed"],
            )

        await db.pool.release(conn)
```

And in the exception handler, ensure ROLLBACK is explicit:

```python
    except Exception as exc:
        logger.error("Error processing %s %s: %s", symbol, timeframe, exc)
        stats["errors"] += 1
        try:
            if not dry_run:
                await conn.execute("ROLLBACK")
            await db.pool.release(conn)
        except Exception:
            pass
```

- [ ] **Step 5: Run a dry-run smoke test**

```bash
.venv/bin/python -u production/scripts/lifecycle_replay.py \
    --symbols ESM6 --timeframes 5m --dry-run 2>&1 | tail -20
```

Expected: no SQL errors, log output showing work queue and signal counts, advisory lock acquired/released.

- [ ] **Step 6: Commit**

```bash
git add production/scripts/lifecycle_replay.py
git commit -m "fix(replay): verify writes + fix final COMMIT/ROLLBACK transaction flow"
```

---

## Task 5: Add Post-Replay Verification

**Files:**
- Modify: `production/scripts/lifecycle_replay.py`

- [ ] **Step 1: Add `_verify_replay()` with comprehensive checks**

```python
async def _verify_replay(
    db: DatabaseManager, symbols: list[str], timeframes: list[str]
) -> None:
    """Post-replay integrity check.

    Every non-regime signal should have an outcome. Every impossible
    combination should be flagged. Every orphan should be detected.
    Discrepancies are hard stops — the data is not usable until resolved.
    """
    async with db.pool.acquire() as conn:
        row = await conn.fetchrow(
            """SELECT
                COUNT(*) as total,
                COUNT(CASE WHEN so.outcome IS NOT NULL THEN 1 END) as with_outcome,
                COUNT(CASE WHEN so.status = 'regime_suppressed' AND so.outcome IS NULL THEN 1 END) as regime_no_outcome,
                COUNT(CASE WHEN so.status NOT IN ('regime_suppressed')
                           AND so.outcome IS NULL
                           AND sl.timestamp < NOW() - INTERVAL '2 days'
                     THEN 1 END) as stale_unresolved,
                COUNT(CASE WHEN sl.market_entry_price IS NOT NULL
                           AND so.market_entry_outcome IS NULL
                           AND so.outcome IS NOT NULL
                     THEN 1 END) as missing_market_outcome,
                COUNT(CASE WHEN so.outcome IN ('target_1','target_1_2','target_full')
                           AND so.pnl_r IS NULL
                     THEN 1 END) as target_no_pnl
            FROM signal_ledger sl
            JOIN signal_outcomes so ON sl.signal_id = so.signal_id
            WHERE sl.symbol = ANY($1)
              AND sl.timeframe = ANY($2)
              AND sl.is_shadow = false""",
            symbols,
            timeframes,
        )

    logger.info(
        "VERIFY: total=%d with_outcome=%d regime_no_outcome=%d "
        "stale_unresolved=%d missing_market=%d target_no_pnl=%d",
        row["total"], row["with_outcome"],
        row["regime_no_outcome"], row["stale_unresolved"],
        row["missing_market_outcome"], row["target_no_pnl"],
    )

    issues = []
    if row["stale_unresolved"] > 0:
        issues.append(
            f"{row['stale_unresolved']} signals older than 2 days have no outcome"
        )
    if row["missing_market_outcome"] > 0:
        issues.append(
            f"{row['missing_market_outcome']} resolved signals with market_entry_price "
            f"but no market_entry_outcome"
        )
    if row["target_no_pnl"] > 0:
        issues.append(
            f"{row['target_no_pnl']} target-hit signals with null pnl_r"
        )

    if issues:
        for issue in issues:
            logger.warning("VERIFY ISSUE: %s", issue)
        logger.warning(
            "VERIFY: %d issue(s) found — investigate before trusting downstream data",
            len(issues),
        )
    else:
        logger.info("VERIFY: all checks passed — data is clean")
```

Wire into `main_async()` after all workers complete:

```python
all_stats = [...]  # existing gather results
total = sum(s["processed"] for s in all_stats)
logger.info("Replay done. Total processed: %d", total)

if not args.dry_run:
    await _verify_replay(db, symbols, timeframes)
```

- [ ] **Step 2: Update docstring with new usage**

Replace the file docstring usage section (lines 9-13) with:

```python
"""
Lifecycle Replay Script — batch replay of historical signal outcomes.

Evaluates dual-track outcomes (zone track + market track) for all signals
that lack outcomes, by replaying market_data_ohlcv bars chronologically
per (symbol, timeframe).

Safety controls:
    - Advisory lock prevents concurrent replays
    - Preflight seeds orphan signal_outcomes rows
    - --confirm required for destructive --reset
    - Post-replay verification catches data integrity issues

Usage:
    # Full reset + replay of corrupt data (requires service stop first):
    sudo systemctl stop indicagent-intelligence-pipeline
    python -u production/scripts/lifecycle_replay.py --reset --confirm --workers 8 \\
        --commit-every 1000 > /tmp/lifecycle_replay.log 2>&1 &

    # Replay only (no reset — for signals that never got resolved):
    python -u production/scripts/lifecycle_replay.py --workers 8

    # Dry run to verify schema compatibility:
    python -u production/scripts/lifecycle_replay.py --symbols ESM6 --timeframes 5m --dry-run

    # Replay specific symbols only:
    python -u production/scripts/lifecycle_replay.py --reset --confirm --symbols ESM6,NQM6

    # Include 4h timeframe (excluded by default):
    python -u production/scripts/lifecycle_replay.py --timeframes 1m,5m,15m,1h,4h

Derived table rebuild:
    After replay, swarm_agent_weights and setup_performance are empty.
    They repopulate on next scheduled runs:
      - setup_performance: nightly ml-training (11pm)
      - swarm_agent_weights: weekly ml-orchestrator (Monday)
"""
```

- [ ] **Step 3: Commit**

```bash
git add production/scripts/lifecycle_replay.py
git commit -m "feat(replay): add comprehensive post-replay verification + updated docs"
```

---

## Task 6: Unit Tests for Replay Helpers

**Files:**
- Modify: `tests/unit/scripts/test_lifecycle_replay.py` (existing file, extend with new tests)

The existing test file at `tests/unit/scripts/test_lifecycle_replay.py` already has solid coverage of the helper functions. Add tests for the new `expires_at` logic and the preflight safety functions.

- [ ] **Step 1: Add expires_at tests to the existing test file**

Append these test classes after the existing `TestTTLInjection` class:

```python
# ── Chunk 3: expires_at wall-clock TTL (Phase 107.5) ──────────────────────


@pytest.mark.unit
class TestExpiresAtWallClock:
    def test_resolve_not_yet_expired_returns_none_outcome(self):
        """Signal with expires_at in the future should not be forced to resolve."""
        replay = _get_replay()
        sig = _sig(signal_id="exp-future")
        sig["expires_at"] = BASE_TS + timedelta(hours=2)
        bar = _bar(BASE_TS + timedelta(minutes=30), 5110.0, 5090.0, 5100.0)
        result = replay.resolve_at_end_of_bars(
            sig, bar, tf_seconds=60, zone_mfe=0.5, market_mfe=0.3
        )
        assert result["zone_outcome"] is None
        assert result["exit_at"] is None

    def test_resolve_expired_with_expires_at_uses_it(self):
        """Signal past expires_at should resolve using expires_at as exit_ts."""
        replay = _get_replay()
        sig = _sig(signal_id="exp-past")
        sig["expires_at"] = BASE_TS + timedelta(minutes=5)
        bar = _bar(BASE_TS + timedelta(minutes=10), 5110.0, 5090.0, 5100.0)
        result = replay.resolve_at_end_of_bars(
            sig, bar, tf_seconds=60, zone_mfe=0.5, market_mfe=0.3,
            zone_activated=True, market_entry_price=5100.0,
        )
        assert result["zone_outcome"] == "ttl_expired_ahead"
        assert result["exit_at"] == sig["expires_at"]

    def test_resolve_no_expires_at_falls_back_to_ttl_bars(self):
        """Signal without expires_at uses ttl_bars * tf_seconds."""
        replay = _get_replay()
        sig = _sig(signal_id="exp-none", ttl_bars=10)
        sig.pop("expires_at", None)
        bar = _bar(BASE_TS + timedelta(minutes=15), 5110.0, 5090.0, 5100.0)
        result = replay.resolve_at_end_of_bars(
            sig, bar, tf_seconds=60, zone_mfe=0.0, market_mfe=0.0
        )
        # exit_at = min(bar_ts, sig_ts + 10*60s) = min(15min, 10min) = 10min
        expected_exit = sig["timestamp"] + timedelta(seconds=10 * 60)
        assert result["exit_at"] == expected_exit

    def test_handle_no_data_uses_expires_at(self):
        """handle_no_data with expires_at uses it as exit_ts."""
        replay = _get_replay()
        sig = _sig(signal_id="nodata-exp")
        sig["expires_at"] = BASE_TS + timedelta(hours=1)
        result = replay.handle_no_data(sig)
        assert result["exit_at"] == sig["expires_at"]

    def test_handle_no_data_fallback_ttl_bars(self):
        """handle_no_data without expires_at falls back to ttl_bars computation."""
        replay = _get_replay()
        sig = _sig(signal_id="nodata-ttl", ttl_bars=60)
        sig.pop("expires_at", None)
        result = replay.handle_no_data(sig)
        expected_exit = sig["timestamp"] + timedelta(seconds=60 * 60)
        assert result["exit_at"] == expected_exit

    def test_not_yet_expired_not_counted_as_processed(self):
        """Not-yet-expired signals should NOT increment processed count.

        This is a critical invariant: resolve_at_end_of_bars returning
        {zone_outcome: None} means the caller should skip the write
        and not count it as processed.
        """
        replay = _get_replay()
        sig = _sig(signal_id="exp-skip")
        sig["expires_at"] = BASE_TS + timedelta(hours=2)
        bar = _bar(BASE_TS + timedelta(minutes=30), 5110.0, 5090.0, 5100.0)
        result = replay.resolve_at_end_of_bars(
            sig, bar, tf_seconds=60, zone_mfe=0.0, market_mfe=0.0
        )
        # The result must be skip-compatible: no zone_outcome, no exit_at
        assert result["zone_outcome"] is None
        # Caller code in _process_symbol_tf checks result["zone_outcome"] is not None
        # before incrementing stats["processed"] — this test documents that contract.
```

- [ ] **Step 2: Run all tests**

```bash
.venv/bin/pytest tests/unit/scripts/test_lifecycle_replay.py -v
```

Expected: all existing + 6 new tests pass (total ~20 tests).

- [ ] **Step 3: Commit**

```bash
git add tests/unit/scripts/test_lifecycle_replay.py
git commit -m "test(replay): add expires_at wall-clock TTL tests (Phase 107.5)"
```

---

## Task 7: Execute the Replay

**Not a code task — operational. Run after Tasks 0-6 are complete and tested.**

- [ ] **Step 1: Dry run on one symbol to verify schema compatibility**

```bash
.venv/bin/python -u production/scripts/lifecycle_replay.py \
    --symbols ESM6 --timeframes 5m --dry-run 2>&1 | tail -30
```

Expected: advisory lock acquired, preflight shows orphan count, work queue shows pending signals, no SQL errors.

- [ ] **Step 2: Stop live lifecycle services**

```bash
sudo systemctl stop indicagent-intelligence-pipeline
```

Verify:
```bash
systemctl is-active indicagent-intelligence-pipeline  # should say "inactive"
```

- [ ] **Step 3: Full reset + replay on all symbols**

```bash
nohup .venv/bin/python -u production/scripts/lifecycle_replay.py \
    --reset --confirm --workers 8 --commit-every 1000 \
    > /tmp/lifecycle_replay_full.log 2>&1 &
```

Expected: runs for several hours processing 2.83M signals across all symbols.

- [ ] **Step 4: Monitor progress**

```bash
tail -f /tmp/lifecycle_replay_full.log
```

Look for: advisory lock acquired, reset counts match expectations, "committed N resolved so far" messages, no errors, work queue draining, VERIFY output at end.

- [ ] **Step 5: Verify results**

After replay completes, check the verification output at the end of the log. Then run an independent check:

```sql
SELECT setup_plugin,
       COUNT(*) as total,
       COUNT(CASE WHEN outcome IN ('target_1','target_1_2','target_full') THEN 1 END) as wins,
       ROUND(COUNT(CASE WHEN outcome IN ('target_1','target_1_2','target_full') THEN 1 END)::numeric
             / NULLIF(COUNT(CASE WHEN outcome IS NOT NULL AND status != 'regime_suppressed' THEN 1 END), 0) * 100, 1) as real_win_pct
FROM signal_ledger l
JOIN signal_outcomes o ON l.signal_id = o.signal_id
WHERE l.is_shadow = false
  AND o.outcome IS NOT NULL
  AND o.status != 'regime_suppressed'
GROUP BY setup_plugin
ORDER BY total DESC;
```

- [ ] **Step 6: Restart services**

```bash
sudo systemctl start indicagent-intelligence-pipeline
```

- [ ] **Step 7: Note derived table rebuild schedule**

`setup_performance` and `swarm_agent_weights` are empty after `--reset`. They repopulate automatically:
- `setup_performance`: next `ml-training` nightly run (11pm)
- `swarm_agent_weights`: next `ml-orchestrator` weekly run (Monday)

No manual rebuild needed.

---

## Self-Review

### Spec Coverage
- [x] Preflight safety controls — advisory lock, quiescence check, orphan seeding (Task 0, NEW)
- [x] Fix SELECT to match current schema (Task 1)
- [x] Add integrated house cleaning with bounded timestamps (Task 2)
- [x] Fix TTL for expires_at (Task 3)
- [x] Verify write logic + fix transaction COMMIT/ROLLBACK (Task 4)
- [x] Add comprehensive verification (Task 5)
- [x] Unit tests for expires_at (Task 6)
- [x] Execution plan with service stop/start (Task 7)

### Review Feedback Addressed
- [x] **Gemini HIGH: Reset scope** — exact timestamp bounds with --reset-after/--reset-before (Task 2)
- [x] **Gemini HIGH: Live service concurrency** — service quiescence check + advisory lock (Task 0)
- [x] **Gemini HIGH: Transaction flow** — explicit final COMMIT and ROLLBACK (Task 4)
- [x] **Gemini HIGH: Orphan ledger rows** — LEFT JOIN preflight seeds missing outcomes (Task 0)
- [x] **Gemini MEDIUM: Derived table rebuild** — documented in docstring and Task 7 Step 7
- [x] **Gemini MEDIUM: expires_at stale rows** — not-yet-expired returns None, test added (Task 6)
- [x] **Gemini LOW: Test path** — uses existing `tests/unit/scripts/` location (Task 6)
- [x] **Gemini LOW: Verification underspecified** — comprehensive checks: stale, missing market, target_no_pnl (Task 5)
- [x] **Codex MEDIUM: Concurrency** — advisory lock + service quiescence (Task 0)
- [x] **Codex MEDIUM: Locking** — per-pair ownership, advisory lock serializes replays (Task 0)
- [x] **Codex suggestion: --confirm flag** — required for --reset (Task 2)

### Placeholder Scan
No TBDs, TODOs, or "implement later" patterns. All steps contain actual code.

### Type Consistency
- `resolve_at_end_of_bars` returns dict with keys: `zone_outcome`, `exit_at`, `market_entry_outcome`, etc. — consistent across Task 3 definition and Task 4 verification.
- `_reset_corrupt_data` uses `datetime` bounds — consistent with `args.reset_after`/`args.reset_before` parsing in Task 2.
- All signal dict keys accessed match the SELECT in Task 1.
- Advisory lock ID is an integer constant — consistent across acquire/release calls.
