#!/usr/bin/env python3
"""
Full Data Reset — wipes all signal-derived tables and re-runs backfill + lifecycle replay.

Version: 1.1
Status: current
Last Updated: 2026-06-06

Run this whenever framing logic (stop/target geometry) or lifecycle logic changes
substantially enough that historical P&L is no longer trustworthy.

Safety controls:
  - Dry-run by default: prints row counts and what would be deleted, exits.
  - --confirm required to execute any destructive operation.
  - Advisory lock prevents concurrent resets.
  - Service quiescence check before touching data.

Usage:
    # Dry run — see what will be wiped:
    python production/scripts/reset_pipeline_data.py

    # Execute full reset:
    sudo systemctl stop indicagent-intelligence-pipeline
    python production/scripts/reset_pipeline_data.py --confirm

    # Skip the backfill + lifecycle replay (just wipe):
    python production/scripts/reset_pipeline_data.py --confirm --wipe-only

    # Wipe then replay with more workers:
    python production/scripts/reset_pipeline_data.py --confirm --workers 8
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

import psycopg2

project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from src.config.settings import Settings

# Advisory lock ID — prevents concurrent resets.
_RESET_LOCK_ID = 20260606

# Tables cleared in this order (no FK constraints exist, but outcomes before
# ledger and features last mirrors how the backfill --clean works).
_TRUNCATE_TABLES: list[tuple[str, str]] = [
    ("signal_metrics", "per-setup rolling performance stats"),
    ("signal_ai_enrichment", "AI enrichment records keyed by signal_id"),
    ("signal_metrics_ic", "information coefficient metrics"),
    ("shadow_transition_log", "shadow promotion/demotion history"),
    ("calibration_curves", "confidence calibration curves"),
    ("confidence_calibration", "confidence calibration data"),
    ("ml_signal_training", "ML training rows — pnl_r/win labels from bad outcomes"),
    ("signal_lineage", "signal lifecycle events keyed by signal_id — orphaned after wipe"),
    ("swarm_agent_weights", "swarm training weights (trained on bad data)"),
    ("llm_calls", "LLM audit trail (signal_ids will be orphaned after wipe)"),
    ("trade_executions", "live execution outcomes — actual_pnl_r, exits"),
    ("trade_frames", "hypothesis layer — counterfactual_pnl_r, frame metadata"),
    ("signal_events", "signal detection layer — raw_confidence, factor_scores, status"),
    (
        "signal_ledger",
        "signal fire-time records — stop/target geometry (view, dropped via cascade)",
    ),
    # intelligence_features last: backfill --clean also deletes these per-symbol,
    # but a full TRUNCATE here is faster than per-symbol deletes for a global reset.
    ("intelligence_features", "computed I1-I7 feature vectors"),
]

# shadow_registry: keep enrollment rows (component_name, component_type, enrolled_at);
# reset eval stats derived from bad signal outcomes.
_SHADOW_RESET_SQL = """
UPDATE shadow_registry
SET last_eval_n              = NULL,
    last_eval_ev_r           = NULL,
    last_eval_ci_lower       = NULL,
    last_eval_win_rate       = NULL,
    demotion_consecutive_count = 0
"""


def _db_conn(settings: Settings):
    return psycopg2.connect(settings.database_url)


def _acquire_lock(conn) -> bool:
    with conn.cursor() as cur:
        cur.execute("SELECT pg_try_advisory_lock(%s)", (_RESET_LOCK_ID,))
        return cur.fetchone()[0]


def _check_services() -> list[str]:
    """Return list of lifecycle-writing services that are still active."""
    services = [
        "indicagent-intelligence-pipeline",
        "indicagent-signal-tracker",
        "indicagent-feature-writer",
    ]
    active = []
    for svc in services:
        result = subprocess.run(
            ["systemctl", "is-active", svc],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.stdout.strip() == "active":
            active.append(svc)
    return active


def _row_count(conn, table: str) -> int:
    with conn.cursor() as cur:
        cur.execute(f"SELECT COUNT(*) FROM {table}")
        return cur.fetchone()[0]


def _shadow_eval_count(conn) -> int:
    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM shadow_registry WHERE last_eval_n IS NOT NULL")
        return cur.fetchone()[0]


def _print_plan(conn) -> None:
    print("\n=== DATA RESET PLAN ===\n")
    print(f"{'Table':<35} {'Rows':>10}  {'What'}")
    print("-" * 75)
    for table, description in _TRUNCATE_TABLES:
        try:
            n = _row_count(conn, table)
        except Exception:
            n = -1
        print(f"  {table:<33} {n:>10,}  {description}")

    n_shadow = _shadow_eval_count(conn)
    print(
        f"  {'shadow_registry (eval stats)':<33} {n_shadow:>10,}  eval stats reset; enrollment rows kept"
    )
    print()
    print("Tables preserved (raw data / config):")
    for t in (
        "market_data_ohlcv",
        "instruments",
        "contract_metadata",
        "cis_weights",
        "config_state",
        "roll_events",
    ):
        try:
            n = _row_count(conn, t)
        except Exception:
            n = -1
        print(f"  {t:<35} {n:>10,}")
    print()


def _execute_wipe(conn) -> None:
    print(f"[{_ts()}] Wiping signal-derived tables...")
    with conn.cursor() as cur:
        for table, _ in _TRUNCATE_TABLES:
            cur.execute(f"TRUNCATE {table}")
            print(f"  TRUNCATED {table}")
        cur.execute(_SHADOW_RESET_SQL)
        print("  RESET shadow_registry eval stats")
    conn.commit()
    print(f"[{_ts()}] Wipe complete.\n")


def _run_backfill(workers: int) -> None:
    print(f"[{_ts()}] Starting backfill replay (workers={workers})...")
    print("  This re-emits all signals with current framing code.")
    print("  --clean deletes signals+features per-symbol before replay.\n")
    cmd = [
        sys.executable,
        "-u",
        str(project_root / "production/scripts/run_historical_pipeline.py"),
        "--replay-only",
        "--clean",
        "--workers",
        str(workers),
    ]
    result = subprocess.run(cmd)
    if result.returncode != 0:
        print(f"\n[{_ts()}] ERROR: backfill exited with code {result.returncode}")
        sys.exit(result.returncode)
    print(f"[{_ts()}] Backfill replay complete.\n")


def _run_lifecycle_replay(workers: int) -> None:
    print(f"[{_ts()}] Starting lifecycle replay (workers={workers})...")
    print("  Computes pnl_r, exits, MAE/MFE for freshly emitted signals.\n")
    cmd = [
        sys.executable,
        "-u",
        str(project_root / "production/scripts/lifecycle_replay.py"),
        "--workers",
        str(workers),
    ]
    result = subprocess.run(cmd)
    if result.returncode != 0:
        print(f"\n[{_ts()}] ERROR: lifecycle_replay exited with code {result.returncode}")
        sys.exit(result.returncode)
    print(f"[{_ts()}] Lifecycle replay complete.\n")


def _post_verify(conn) -> None:
    print(f"[{_ts()}] Post-reset verification...")
    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM signal_ledger")
        n_signals = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM signal_ledger WHERE counterfactual_pnl_r IS NOT NULL")
        n_with_pnl = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM signal_ledger WHERE counterfactual_pnl_r = 0.0")
        n_zero = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM signal_ledger WHERE entry_zone_low IS NOT NULL")
        n_with_zones = cur.fetchone()[0]

    print(f"  signal_ledger rows:          {n_signals:>10,}")
    print(f"  frames with pnl_r:          {n_with_pnl:>10,}")
    print(f"  frames with zero pnl_r:      {n_zero:>10,}")
    print(f"  signals with entry zones:    {n_with_zones:>10,}")

    # Spot check zone bounds on a sample signal
    with conn.cursor() as cur:
        cur.execute("""SELECT sl.entry_zone_low, sl.entry_zone_high, sl.stop_loss,
                      sl.adaptive_buffer_mult, sl.stop_basis
               FROM signal_ledger sl
               WHERE sl.entry_zone_low IS NOT NULL
               LIMIT 1""")
        row = cur.fetchone()
    if row:
        print("\n  Sample signal zone/stop check:")
        print(f"    entry_zone_low={row[0]}, entry_zone_high={row[1]}")
        print(f"    stop_loss={row[2]}, adaptive_buffer_mult={row[3]}, stop_basis={row[4]}")
    else:
        print("\n  WARNING: No signals found with entry_zone_low populated.")

    print()


def _ts() -> str:
    return datetime.now(UTC).strftime("%H:%M:%S")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Full signal data reset — wipe + backfill + lifecycle replay."
    )
    parser.add_argument(
        "--confirm",
        action="store_true",
        help="Required to execute. Without this flag, prints dry-run plan and exits.",
    )
    parser.add_argument(
        "--wipe-only",
        action="store_true",
        help="Truncate tables but skip backfill and lifecycle replay.",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=4,
        help="Worker count for backfill and lifecycle replay (default: 4).",
    )
    args = parser.parse_args()

    settings = Settings()
    conn = _db_conn(settings)

    if not _acquire_lock(conn):
        print("ERROR: Another reset is already running (advisory lock held). Aborting.")
        sys.exit(1)

    _print_plan(conn)

    if not args.confirm:
        print("DRY RUN — no changes made.")
        print("Re-run with --confirm to execute.\n")
        return

    # Service quiescence check
    active = _check_services()
    if active:
        print("ERROR: lifecycle-writing services are still active:")
        for svc in active:
            print(f"  {svc}")
        print("\nStop them first:")
        print("  sudo systemctl stop indicagent-intelligence-pipeline")
        sys.exit(1)

    print(f"[{_ts()}] Confirmed. Executing full data reset...\n")

    _execute_wipe(conn)

    if not args.wipe_only:
        _run_backfill(args.workers)
        _run_lifecycle_replay(args.workers)
        conn = _db_conn(settings)  # reconnect after long-running subprocesses
        _post_verify(conn)

    print(f"[{_ts()}] Reset complete.")
    print()
    print("Next steps:")
    print("  sudo systemctl start indicagent-intelligence-pipeline")
    print("  setup_performance:    refills tonight at 11pm via ml-training")
    print("  swarm_agent_weights:  refills Monday via ml-orchestrator")


if __name__ == "__main__":
    main()
