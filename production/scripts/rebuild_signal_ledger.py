#!/usr/bin/env python3
"""rebuild_signal_ledger — idempotent orchestrator for full signal ledger rebuild.

Executes the complete delete+regenerate+replay pipeline in strict stage order.
Tracks completed stages in a JSON state file for deterministic resume after
any crash or interruption.

Stages (in order):
    1. snapshot    — capture before-snapshot before any deletes
    2. decompress  — decompress signal_ledger + market_data_ohlcv before bulk DML
    3. clean       — delete old signals via historical_backfill.py --clean
    4. dry_run     — validate column mapping with --workers 1 before full replay
    5. replay      — run historical_backfill.py --replay-only across all symbols
    6. verify      — hard-fail if stopped_at_entry or orphan_ledger_rows > 0
    7. recompress  — recompress signal_ledger + market_data_ohlcv

Usage:
    .venv/bin/python production/scripts/rebuild_signal_ledger.py

    On crash: re-run the same command — resumes from the last completed stage.

RE-RUN SAFETY:
    - before-snapshot JSON is immutable after creation (abort guard on file existence)
    - historical_backfill.py is idempotent via ON CONFLICT DO NOTHING
    - Re-running rebuild_signal_ledger.py is always safe
"""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_PROJECT_ROOT))

from src.config.settings import Settings
from src.core.database_manager import DatabaseManager
from src.observability.metrics import JOB_COMPLETED_TOTAL, flush_and_shutdown_metrics
from src.observability.otel import OTelInitError, init_otel_providers

# Stage names — order is enforced by the stage execution sequence
STAGE_SNAPSHOT = "snapshot"
STAGE_DECOMPRESS = "decompress"
STAGE_DROP_INDEXES = "drop_indexes"
STAGE_CLEAN = "clean"
STAGE_DRY_RUN = "dry_run"
STAGE_REPLAY = "replay"
STAGE_VERIFY = "verify"
STAGE_REBUILD_INDEXES = "rebuild_indexes"
STAGE_RECOMPRESS = "recompress"

_STAGE_ORDER = [
    STAGE_SNAPSHOT,
    STAGE_DECOMPRESS,
    STAGE_DROP_INDEXES,
    STAGE_CLEAN,
    STAGE_DRY_RUN,
    STAGE_REPLAY,
    STAGE_VERIFY,
    STAGE_REBUILD_INDEXES,
    STAGE_RECOMPRESS,
]

# Tables that must be decompressed before bulk DML and recompressed after.
# signal_ledger: 51 compressed chunks — DELETE forces per-tuple decompression on write.
# market_data_ohlcv: 24 compressed chunks — bar reads during lifecycle replay decompress on fetch.
_BULK_DML_TABLES = ("signal_ledger", "market_data_ohlcv")

# Non-PK indexes to drop before bulk INSERT and rebuild after.
# Each inserted row updates every live index. Dropping them before the replay eliminates
# that write amplification. PKs are excluded — TimescaleDB requires them for chunk management.
# Rebuilt after verify passes; pipeline is stopped so CONCURRENTLY is not needed.
_DROP_INDEXES_SQL = [
    "DROP INDEX IF EXISTS idx_signal_ledger_expires_at",
    "DROP INDEX IF EXISTS idx_signal_ledger_setup_plugin",
    "DROP INDEX IF EXISTS idx_signal_ledger_shadow",
    "DROP INDEX IF EXISTS idx_signal_ledger_signal_id",
    "DROP INDEX IF EXISTS idx_signal_ledger_stop_basis",
    "DROP INDEX IF EXISTS idx_signal_ledger_symbol_tf",
    "DROP INDEX IF EXISTS signal_ledger_timestamp_idx",
    "DROP INDEX IF EXISTS idx_signal_outcomes_closed",
    "DROP INDEX IF EXISTS idx_signal_outcomes_live",
    "DROP INDEX IF EXISTS idx_signal_outcomes_pending_suppressed",
    "DROP INDEX IF EXISTS idx_signal_outcomes_pnl",
    "DROP INDEX IF EXISTS idx_signal_outcomes_status",
]

_REBUILD_INDEXES_SQL = [
    "CREATE INDEX IF NOT EXISTS idx_signal_ledger_expires_at ON signal_ledger (expires_at) WHERE expires_at IS NOT NULL",
    "CREATE INDEX IF NOT EXISTS idx_signal_ledger_setup_plugin ON signal_ledger (setup_plugin)",
    "CREATE INDEX IF NOT EXISTS idx_signal_ledger_shadow ON signal_ledger (is_shadow) WHERE is_shadow = true",
    "CREATE INDEX IF NOT EXISTS idx_signal_ledger_signal_id ON signal_ledger (signal_id)",
    "CREATE INDEX IF NOT EXISTS idx_signal_ledger_stop_basis ON signal_ledger (stop_basis) WHERE stop_basis IS NOT NULL",
    "CREATE INDEX IF NOT EXISTS idx_signal_ledger_symbol_tf ON signal_ledger (symbol, timeframe, timestamp DESC)",
    "CREATE INDEX IF NOT EXISTS signal_ledger_timestamp_idx ON signal_ledger (timestamp DESC)",
    "CREATE INDEX IF NOT EXISTS idx_signal_outcomes_closed ON signal_outcomes (outcome, activated_at DESC) WHERE outcome IS NOT NULL",
    "CREATE INDEX IF NOT EXISTS idx_signal_outcomes_live ON signal_outcomes (signal_id, status) WHERE status = ANY(ARRAY['pending', 'active'])",
    "CREATE INDEX IF NOT EXISTS idx_signal_outcomes_pending_suppressed ON signal_outcomes (status, signal_id) WHERE status = ANY(ARRAY['pending', 'regime_suppressed'])",
    "CREATE INDEX IF NOT EXISTS idx_signal_outcomes_pnl ON signal_outcomes (pnl_r, outcome) WHERE pnl_r IS NOT NULL",
    "CREATE INDEX IF NOT EXISTS idx_signal_outcomes_status ON signal_outcomes (status) WHERE exit_at IS NULL",
]

_STATE_PATH = _PROJECT_ROOT / "docs" / "plans" / "signal-ledger-rebuild-state.json"
_SNAPSHOT_PATH = _PROJECT_ROOT / "docs" / "plans" / "signal-ledger-snapshot.json"

# Column-mapping error indicators to detect in lifecycle_replay.py dry-run output
_DRY_RUN_ERROR_PATTERNS = [
    "AttributeError",
    "KeyError",
    "InterfaceError",
    "RuntimeError",
    "stop_basis",
    "trailing_stop_price",
    "shadow_tracking_start_ts",
    "effective_ts",
    "staleness_score",
    "shadow_mae",
    "shadow_mfe",
    "staleness_trigger_reason",
    "chandelier_vol_source",
    "shadow_outcome",
    "stop_type_col",
    "structural_stop_distance_atr",
    "adaptive_buffer_mult",
    "plugin_regime_type",
]


def _load_state() -> dict:
    """Load stage state from disk. Returns empty state if file does not exist."""
    if _STATE_PATH.exists():
        try:
            return json.loads(_STATE_PATH.read_text())
        except (json.JSONDecodeError, OSError):
            print(f"[warn] Could not read state file {_STATE_PATH} — starting fresh")
    return {"stages_complete": [], "started_at": None, "last_updated": None}


def _save_state(state: dict) -> None:
    """Persist stage state to disk."""
    state["last_updated"] = datetime.now(UTC).isoformat()
    _STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    _STATE_PATH.write_text(json.dumps(state, indent=2))


def _mark_complete(state: dict, stage: str) -> None:
    """Record a stage as complete and save."""
    if stage not in state["stages_complete"]:
        state["stages_complete"].append(stage)
    _save_state(state)
    print(f"  Stage {stage}: COMPLETE (recorded)")


_PIPELINE_UNIT = "indicagent-intelligence-pipeline"
_SIGNAL_WRITER_UNIT = "indicagent-signal-writer"


def _systemctl(action: str, unit: str) -> None:
    """Stop or start a systemd unit via sudo. Warns but does not raise on failure."""
    sudo_pass = os.environ.get("SUDO_PASS", "")
    result = subprocess.run(
        ["/usr/bin/sudo.ws", "-S", "systemctl", action, unit],
        input=sudo_pass + "\n",
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        print(
            f"  [warn] systemctl {action} {unit} exited {result.returncode}: {result.stderr.strip()}"
        )
    else:
        print(f"  systemctl {action} {unit}: OK")


def _run_subprocess(cmd: list[str], log_path: Path | None = None) -> subprocess.CompletedProcess:
    """Run a subprocess, streaming output to stdout and optionally to a log file."""
    print(f"  Running: {' '.join(cmd)}")
    if log_path:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with open(log_path, "w") as log_fh:
            result = subprocess.run(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
            )
            output = result.stdout or ""
            print(output, end="")
            log_fh.write(output)
    else:
        result = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        output = result.stdout or ""
        print(output, end="")
    return result


async def _decompress_tables(db: DatabaseManager) -> None:
    async with db.pool.acquire() as conn:
        for table in _BULK_DML_TABLES:
            chunks = await conn.fetch(
                """SELECT chunk_schema, chunk_name
                   FROM timescaledb_information.chunks
                   WHERE hypertable_name = $1 AND is_compressed = true""",
                table,
            )
            if not chunks:
                print(f"  {table}: no compressed chunks — skipping")
                continue
            for chunk in chunks:
                await conn.execute(
                    "SELECT decompress_chunk($1, true)",
                    f"{chunk['chunk_schema']}.{chunk['chunk_name']}",
                )
            print(f"  {table}: decompressed {len(chunks)} chunks")


async def _recompress_tables(db: DatabaseManager) -> None:
    async with db.pool.acquire() as conn:
        for table in _BULK_DML_TABLES:
            chunks = await conn.fetch(
                """SELECT chunk_schema, chunk_name
                   FROM timescaledb_information.chunks
                   WHERE hypertable_name = $1 AND is_compressed = false""",
                table,
            )
            if not chunks:
                print(f"  {table}: no uncompressed chunks — skipping")
                continue
            for chunk in chunks:
                await conn.execute(
                    "SELECT compress_chunk($1)",
                    f"{chunk['chunk_schema']}.{chunk['chunk_name']}",
                )
            print(f"  {table}: compressed {len(chunks)} chunks")


async def _run_stage_decompress(state: dict) -> None:
    """Decompress signal_ledger + market_data_ohlcv before bulk DML.

    TimescaleDB forces per-tuple decompression during DELETE on compressed chunks,
    turning a 6k-row delete into an hours-long operation. Explicit decompression
    upfront is a deliberate operational step: compress=cold storage, decompress before
    bulk replay. Recompressed in STAGE_RECOMPRESS after verify passes.
    """
    if STAGE_DECOMPRESS in state["stages_complete"]:
        print(f"Stage {STAGE_DECOMPRESS}: already complete, skipping")
        return

    print(f"\n=== STAGE: {STAGE_DECOMPRESS} ===")
    settings = Settings()
    db = DatabaseManager(settings.database_url)
    await db.initialize()
    try:
        await _decompress_tables(db)
    finally:
        await db.close()
    _mark_complete(state, STAGE_DECOMPRESS)


async def _run_stage_drop_indexes(state: dict) -> None:
    """Drop non-PK indexes on signal_ledger + signal_outcomes before bulk INSERT.

    Each row inserted during replay updates every live index. With 12 non-PK btree
    indexes across both tables, dropping them before the load and rebuilding after
    cuts per-row write work by ~12x on the index side.
    """
    if STAGE_DROP_INDEXES in state["stages_complete"]:
        print(f"Stage {STAGE_DROP_INDEXES}: already complete, skipping")
        return

    print(f"\n=== STAGE: {STAGE_DROP_INDEXES} ===")
    settings = Settings()
    db = DatabaseManager(settings.database_url)
    await db.initialize()
    try:
        async with db.pool.acquire() as conn:
            for sql in _DROP_INDEXES_SQL:
                await conn.execute(sql)
                print(f"  {sql}")
    finally:
        await db.close()
    _mark_complete(state, STAGE_DROP_INDEXES)


async def _run_stage_rebuild_indexes(state: dict) -> None:
    """Rebuild non-PK indexes on signal_ledger + signal_outcomes after verify passes."""
    if STAGE_REBUILD_INDEXES in state["stages_complete"]:
        print(f"Stage {STAGE_REBUILD_INDEXES}: already complete, skipping")
        return

    print(f"\n=== STAGE: {STAGE_REBUILD_INDEXES} ===")
    settings = Settings()
    db = DatabaseManager(settings.database_url)
    await db.initialize()
    try:
        async with db.pool.acquire() as conn:
            for sql in _REBUILD_INDEXES_SQL:
                await conn.execute(sql)
                print(f"  done: {sql[:60]}...")
    finally:
        await db.close()
    _mark_complete(state, STAGE_REBUILD_INDEXES)


async def _run_stage_recompress(state: dict) -> None:
    """Recompress signal_ledger + market_data_ohlcv after verify passes."""
    if STAGE_RECOMPRESS in state["stages_complete"]:
        print(f"Stage {STAGE_RECOMPRESS}: already complete, skipping")
        return

    print(f"\n=== STAGE: {STAGE_RECOMPRESS} ===")
    settings = Settings()
    db = DatabaseManager(settings.database_url)
    await db.initialize()
    try:
        await _recompress_tables(db)
    finally:
        await db.close()
    _mark_complete(state, STAGE_RECOMPRESS)


async def _run_stage_snapshot(state: dict) -> None:
    """STAGE_SNAPSHOT: capture before-snapshot (immutable baseline)."""
    if STAGE_SNAPSHOT in state["stages_complete"]:
        if _SNAPSHOT_PATH.exists():
            print(f"Stage {STAGE_SNAPSHOT}: already complete, skipping")
            return
        else:
            print(
                f"ABORT: stage '{STAGE_SNAPSHOT}' is in stages_complete but snapshot "
                f"file does not exist at {_SNAPSHOT_PATH}. Manual intervention required."
            )
            raise RuntimeError(
                f"Snapshot stage recorded as complete but file missing: {_SNAPSHOT_PATH}"
            )

    if _SNAPSHOT_PATH.exists():
        print(
            f"ABORT: snapshot file already exists at {_SNAPSHOT_PATH} "
            f"but stage not in stages_complete. Manual intervention required — "
            f"either delete the snapshot file or add '{STAGE_SNAPSHOT}' to stages_complete."
        )
        raise RuntimeError(
            "Snapshot file exists but stage not recorded — manual intervention required"
        )

    print(f"\n=== STAGE: {STAGE_SNAPSHOT} ===")
    result = _run_subprocess([sys.executable, "production/scripts/signal_ledger_snapshot.py"])
    if result.returncode != 0:
        raise RuntimeError(f"Stage '{STAGE_SNAPSHOT}' failed with exit code {result.returncode}")
    _mark_complete(state, STAGE_SNAPSHOT)


async def _run_stage_clean(state: dict) -> None:
    """STAGE_CLEAN: delete old signals via historical_backfill --clean."""
    if STAGE_CLEAN in state["stages_complete"]:
        print(f"Stage {STAGE_CLEAN}: already complete, skipping")
        return

    print(f"\n=== STAGE: {STAGE_CLEAN} ===")
    log_path = _PROJECT_ROOT / "logs" / "signal_ledger_clean.log"
    result = _run_subprocess(
        [
            sys.executable,
            "production/scripts/historical_backfill.py",
            "--replay-only",
            "--clean",
            "--workers",
            "8",
        ],
        log_path=log_path,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"Stage '{STAGE_CLEAN}' failed with exit code {result.returncode}. "
            f"See {log_path} for details."
        )
    _mark_complete(state, STAGE_CLEAN)


async def _run_stage_dry_run(state: dict) -> None:
    """STAGE_DRY_RUN: smoke-test 2 days of replay before committing to the full run."""
    if STAGE_DRY_RUN in state["stages_complete"]:
        print(f"Stage {STAGE_DRY_RUN}: already complete, skipping")
        return

    print(f"\n=== STAGE: {STAGE_DRY_RUN} ===")
    print("  Running 2-day smoke test with --workers 1 (fail-fast before bulk replay)...")
    result = _run_subprocess(
        [
            sys.executable,
            "production/scripts/historical_backfill.py",
            "--replay-only",
            "--workers",
            "1",
            "--days",
            "2",
            "--use-precomputed-features",
        ]
    )
    output = result.stdout or ""

    found_errors = [p for p in _DRY_RUN_ERROR_PATTERNS if p in output]
    if found_errors or result.returncode != 0:
        error_detail = f"errors detected: {found_errors}" if found_errors else ""
        raise RuntimeError(
            f"Stage '{STAGE_DRY_RUN}' failed — "
            f"exit_code={result.returncode} {error_detail}. "
            "Fix historical_backfill.py before re-running."
        )
    _mark_complete(state, STAGE_DRY_RUN)


async def _run_stage_replay(state: dict) -> None:
    """STAGE_REPLAY: run historical_backfill.py --replay-only across all symbols."""
    # REPLAY is always re-run (historical_backfill.py is idempotent via ON CONFLICT DO NOTHING)
    if STAGE_REPLAY in state["stages_complete"]:
        print(f"Stage {STAGE_REPLAY}: already complete, skipping")
        return

    print(f"\n=== STAGE: {STAGE_REPLAY} ===")
    log_path = _PROJECT_ROOT / "logs" / "signal_ledger_replay.log"
    result = _run_subprocess(
        [
            sys.executable,
            "production/scripts/historical_backfill.py",
            "--replay-only",
            "--workers",
            "8",
            "--use-precomputed-features",
        ],
        log_path=log_path,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"Stage '{STAGE_REPLAY}' failed with exit code {result.returncode}. "
            f"See {log_path} for details. Re-run to resume (idempotent)."
        )
    _mark_complete(state, STAGE_REPLAY)


async def _run_stage_verify(state: dict) -> None:
    """STAGE_VERIFY: hard-fail if stopped_at_entry or orphan_ledger_rows > 0."""
    if STAGE_VERIFY in state["stages_complete"]:
        print(f"Stage {STAGE_VERIFY}: already complete, skipping")
        return

    print(f"\n=== STAGE: {STAGE_VERIFY} ===")
    settings = Settings()
    db = DatabaseManager(settings.database_url)
    await db.initialize()
    try:
        async with db.pool.acquire() as conn:
            # (a) stopped_at_entry == 0 for shadow signals
            row_sae = await conn.fetchrow("""SELECT COUNT(*) AS count
                   FROM signal_ledger sl
                   JOIN signal_outcomes so ON sl.signal_id = so.signal_id
                   WHERE so.outcome = 'stopped_at_entry'
                     AND sl.is_shadow = true""")
            sae_count = row_sae["count"]

            # (b) orphan_ledger_rows == 0 (Phase 104 invariant)
            row_orphan = await conn.fetchrow("""SELECT COUNT(*) AS count
                   FROM signal_ledger sl
                   LEFT JOIN signal_outcomes so ON sl.signal_id = so.signal_id
                   WHERE so.signal_id IS NULL""")
            orphan_count = row_orphan["count"]

        failures = []
        if sae_count > 0:
            failures.append(
                f"stopped_at_entry={sae_count} for shadow signals "
                "(Phase 117 fix must eliminate all stopped_at_entry)"
            )
        if orphan_count > 0:
            failures.append(
                f"orphan_ledger_rows={orphan_count} "
                "(signal_ledger rows without signal_outcomes — Phase 104 invariant violated)"
            )

        if failures:
            for failure in failures:
                print(f"  VERIFY FAILED: {failure}")
            raise RuntimeError(f"STAGE_VERIFY failed: {'; '.join(failures)}")

        print(f"  stopped_at_entry (shadow): {sae_count}")
        print(f"  orphan_ledger_rows: {orphan_count}")
        print("  VERIFY PASSED")
    finally:
        await db.close()

    _mark_complete(state, STAGE_VERIFY)


async def main_async() -> int:
    """Run the full D-01 sequence with stage-based resume."""
    state = _load_state()

    if not state.get("started_at"):
        state["started_at"] = datetime.now(UTC).isoformat()
        _save_state(state)
        print(f"Phase 121 orchestration started at {state['started_at']}")
    else:
        completed = state.get("stages_complete", [])
        print(f"Resuming Phase 121 orchestration — " f"completed stages: {completed}")

    try:
        await _run_stage_snapshot(state)
        # Stop live pipeline and signal writer before clean/replay — prevents stale
        # Kafka-buffered signals from being written during the clean window, and avoids
        # contention on signal_ledger during the backfill INSERT. Both restarted in finally.
        _systemctl("stop", _PIPELINE_UNIT)
        _systemctl("stop", _SIGNAL_WRITER_UNIT)
        await _run_stage_decompress(state)
        await _run_stage_drop_indexes(state)
        await _run_stage_clean(state)
        await _run_stage_dry_run(state)
        await _run_stage_replay(state)
        await _run_stage_verify(state)
        await _run_stage_rebuild_indexes(state)
        await _run_stage_recompress(state)
    finally:
        _systemctl("start", _PIPELINE_UNIT)
        _systemctl("start", _SIGNAL_WRITER_UNIT)

    print(
        f"\n=== Phase 121 D-01 sequence COMPLETE ==="
        f"\nCompleted stages: {state['stages_complete']}"
    )
    return 0


def main() -> None:
    try:
        init_otel_providers("rebuild-signal-ledger")
    except OTelInitError as error:
        print(f"[warn] OTel init failed — metrics disabled: {error}")
    exit_code = 1
    try:
        exit_code = asyncio.run(main_async())
        JOB_COMPLETED_TOTAL.add(1, {"job": "rebuild-signal-ledger", "status": "success"})
    except Exception as error:
        print(f"ERROR: {error}")
        JOB_COMPLETED_TOTAL.add(1, {"job": "rebuild-signal-ledger", "status": "failure"})
    finally:
        flush_and_shutdown_metrics()
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
