#!/usr/bin/env python3
"""phase_121_orchestrate — single idempotent entry point for the Phase 121 D-01 sequence.

Executes the complete delete+regenerate+replay pipeline for the 22 shadow setups
in strict stage order. Tracks completed stages in a JSON state file for
deterministic resume after any crash.

Stages (in order):
    1. snapshot  — capture before-snapshot before any deletes
    2. clean     — delete 22 shadow setups' old noise signals via historical_backfill.py --clean
    3. dry_run   — validate 14-column mapping with --workers 1 before full replay
    4. replay    — run lifecycle_replay.py across all pending signals
    5. verify    — hard-fail if stopped_at_entry or orphan_ledger_rows > 0

Usage:
    .venv/bin/python production/scripts/phase_121_orchestrate.py

    On crash: re-run the same command — resumes from the last completed stage.

RE-RUN SAFETY:
    - before-snapshot JSON is immutable after creation (abort guard in before_snapshot script)
    - lifecycle_replay.py is idempotent via ON CONFLICT DO NOTHING in _seed_orphan_outcomes
    - Re-running phase_121_orchestrate.py is always safe
"""

from __future__ import annotations

import asyncio
import json
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
STAGE_CLEAN = "clean"
STAGE_DRY_RUN = "dry_run"
STAGE_REPLAY = "replay"
STAGE_VERIFY = "verify"

_STAGE_ORDER = [STAGE_SNAPSHOT, STAGE_CLEAN, STAGE_DRY_RUN, STAGE_REPLAY, STAGE_VERIFY]

_STATE_PATH = _PROJECT_ROOT / "docs" / "plans" / "phase-121-orchestrate-state.json"
_SNAPSHOT_PATH = _PROJECT_ROOT / "docs" / "plans" / "phase-121-before-snapshot.json"

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
    result = _run_subprocess([sys.executable, "production/scripts/phase_121_before_snapshot.py"])
    if result.returncode != 0:
        raise RuntimeError(f"Stage '{STAGE_SNAPSHOT}' failed with exit code {result.returncode}")
    _mark_complete(state, STAGE_SNAPSHOT)


async def _run_stage_clean(state: dict) -> None:
    """STAGE_CLEAN: delete 22 shadow setups' old noise signals via historical_backfill --clean."""
    if STAGE_CLEAN in state["stages_complete"]:
        print(f"Stage {STAGE_CLEAN}: already complete, skipping")
        return

    print(f"\n=== STAGE: {STAGE_CLEAN} ===")
    log_path = _PROJECT_ROOT / "logs" / "phase_121_clean.log"
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
    """STAGE_DRY_RUN: validate 14-column mapping on a small batch before full replay."""
    if STAGE_DRY_RUN in state["stages_complete"]:
        print(f"Stage {STAGE_DRY_RUN}: already complete, skipping")
        return

    print(f"\n=== STAGE: {STAGE_DRY_RUN} ===")
    print("  Validating 14-column mapping with --workers 1 (fail-fast before bulk replay)...")
    result = _run_subprocess(
        [
            sys.executable,
            "production/scripts/lifecycle_replay.py",
            "--workers",
            "1",
            "--dry-run",
            "--force",
        ]
    )
    output = result.stdout or ""

    # Check for column-mapping errors in output
    found_errors = [p for p in _DRY_RUN_ERROR_PATTERNS if p in output]
    if found_errors or result.returncode != 0:
        error_detail = f"Column-mapping errors detected: {found_errors}" if found_errors else ""
        raise RuntimeError(
            f"Stage '{STAGE_DRY_RUN}' failed — "
            f"exit_code={result.returncode} {error_detail}. "
            "Fix the column mapping in lifecycle_replay.py Task 2 before re-running."
        )
    _mark_complete(state, STAGE_DRY_RUN)


async def _run_stage_replay(state: dict) -> None:
    """STAGE_REPLAY: run lifecycle_replay.py across all pending signals."""
    # REPLAY is always re-run (lifecycle_replay.py is idempotent via ON CONFLICT DO NOTHING)
    if STAGE_REPLAY in state["stages_complete"]:
        print(f"Stage {STAGE_REPLAY}: already complete, skipping")
        return

    print(f"\n=== STAGE: {STAGE_REPLAY} ===")
    log_path = _PROJECT_ROOT / "logs" / "phase_121_replay.log"
    result = _run_subprocess(
        [
            sys.executable,
            "production/scripts/lifecycle_replay.py",
            "--workers",
            "8",
            "--force",
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
        await _run_stage_clean(state)
        await _run_stage_dry_run(state)
        await _run_stage_replay(state)
        await _run_stage_verify(state)
    except Exception:
        raise

    print(
        f"\n=== Phase 121 D-01 sequence COMPLETE ==="
        f"\nCompleted stages: {state['stages_complete']}"
    )
    return 0


def main() -> None:
    try:
        init_otel_providers("phase-121-orchestrate")
    except OTelInitError as error:
        print(f"[warn] OTel init failed — metrics disabled: {error}")
    exit_code = 1
    try:
        exit_code = asyncio.run(main_async())
        JOB_COMPLETED_TOTAL.add(1, {"job": "phase-121-orchestrate", "status": "success"})
    except Exception as error:
        print(f"ERROR: {error}")
        JOB_COMPLETED_TOTAL.add(1, {"job": "phase-121-orchestrate", "status": "failure"})
    finally:
        flush_and_shutdown_metrics()
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
