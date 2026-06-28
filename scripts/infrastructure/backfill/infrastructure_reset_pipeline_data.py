#!/usr/bin/env python3
"""
Full Data Reset — wipes all signal-derived tables and re-runs backfill + lifecycle replay.

Version: 2.0
Status: current
Last Updated: 2026-06-18

Run this whenever framing logic (stop/target geometry) or lifecycle logic changes
substantially enough that historical P&L is no longer trustworthy.

Safety controls:
  - Dry-run by default: prints row counts and what would be deleted, exits.
  - --confirm required to execute any destructive operation.
  - Advisory lock prevents concurrent resets.
  - Service quiescence check before touching data.

Usage:
    # Dry run — see what will be wiped:
    python scripts/infrastructure/backfill/infrastructure_reset_pipeline_data.py

    # Execute full reset:
    sudo systemctl stop indicagent-intelligence-pipeline
    python scripts/infrastructure/backfill/infrastructure_reset_pipeline_data.py --confirm

    # Skip the backfill + lifecycle replay (just wipe):
    python scripts/infrastructure/backfill/infrastructure_reset_pipeline_data.py --confirm --wipe-only

    # Wipe then replay with more workers:
    python scripts/infrastructure/backfill/infrastructure_reset_pipeline_data.py --confirm --workers 8
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

# Services that write signal-derived data — all must be stopped before wipe.
_LIFECYCLE_SERVICES = [
    "indicagent-intelligence-pipeline",
    "indicagent-signal-writer",
    "indicagent-signal-tracker-compute",
    "indicagent-lifecycle-writer",
    "indicagent-feature-writer",
    "indicagent-lineage-writer",
    "indicagent-llm-writer",
    "indicagent-swarm-ledger-writer",
    "indicagent-signal-metrics-compute",
    "indicagent-signal-metrics-writer",
    "indicagent-ctx-writer",
    "indicagent-graduation-compute",
    "indicagent-graduation-writer",
    "indicagent-alpha-swarm",
    "indicagent-narrative-compute",
]

# Tables cleared in dependency order.
# signal_ledger is a JOIN VIEW (signal_events + trade_frames + trade_executions);
# it is not truncated directly — clearing the base tables is sufficient.
_TRUNCATE_TABLES: list[tuple[str, str]] = [
    # --- signal enrichment / scoring (keyed by signal_id) ---
    ("alpha_multiplier_shadow", "AI multiplier predictions keyed by signal_id"),
    ("signal_ai_enrichment", "legacy AI enrichment keyed by signal_id"),
    ("intelligence_ai_enrichment", "narrative/AI enrichment on feature vectors"),
    # --- signal performance & quality stats ---
    ("signal_metrics", "per-setup rolling performance stats"),
    ("signal_metrics_ic", "information coefficient metrics"),
    ("signal_metrics_dq_failures", "signal metrics data-quality rejection log"),
    ("setup_performance", "per-setup rolling 30d stats; drives perf_multiplier"),
    ("pattern_reliability", "pattern win-rate / p-value derived from outcomes"),
    # --- signal auxiliary logs ---
    ("signal_transform_log", "per-signal multiplier transform audit trail"),
    ("signal_lineage", "signal lifecycle events keyed by signal_id"),
    # --- drift detection (trained on signal outcomes) ---
    ("drift_monitor", "KS / CUSUM drift checks derived from signal outcomes"),
    ("drift_state", "current per-symbol drift severity derived from signals"),
    # --- shadow / calibration (derived from signal outcomes) ---
    ("shadow_transition_log", "shadow promotion/demotion history"),
    ("calibration_curves", "confidence calibration curves"),
    ("confidence_calibration", "confidence calibration data"),
    # --- LLM audit (signal_id references orphaned after wipe) ---
    ("llm_model_scores", "per-model scoring derived from llm_calls + outcomes"),
    ("llm_calls", "LLM audit trail — signal_ids orphaned after wipe"),
    # --- ML artifacts (trained on stale signal data) ---
    ("ml_signal_training", "ML training rows derived from bad signal outcomes"),
    ("ml_models", "ML models trained on stale data"),
    ("ml_data_quality_runs", "ML data-quality run logs"),
    ("ml_discovery_runs", "ML feature discovery run logs"),
    # --- swarm / transform ---
    ("swarm_agent_weights", "swarm training weights (trained on bad data)"),
    ("tod_multipliers", "time-of-day multipliers learned from signal outcomes"),
    ("transform_graduation", "transform graduation verdicts derived from signals"),
    ("remediation_ledger", "APR auto-remediation ledger (stale after wipe)"),
    # --- AI memory (all derived from signal outcomes) ---
    ("memory_episodes_labeled", "labeled memory episodes with pnl_r"),
    ("memory_episodes_raw", "raw memory episodes keyed by signal_id"),
    ("memory_calibration_promoted", "promoted calibration records derived from outcomes"),
    ("memory_calibration_spc", "SPC control charts derived from signal outcomes"),
    ("memory_regime_transitions", "regime win-rate / pnl_r stats derived from signals"),
    ("memory_system_state", "current regime epoch counter"),
    # --- context snapshots (derived from bar + signal flow) ---
    ("ctx_events", "context events derived from market data and signals"),
    ("ctx_snapshots", "point-in-time context snapshots"),
    # --- intelligence pipeline validation ---
    ("intelligence_metrics", "correctness metrics for I1-I7 computed features"),
    # --- core SLA tables (order: executions before frames before events) ---
    ("trade_executions", "live execution outcomes — actual_pnl_r, exits"),
    ("trade_frames", "hypothesis layer — counterfactual_pnl_r, frame metadata"),
    ("signal_events", "signal detection layer — raw_confidence, factor_scores, status"),
    # --- features last: fastest to wipe in bulk vs per-symbol in backfill --clean ---
    ("intelligence_features", "computed I1-I7 feature vectors"),
]

# shadow_registry: keep enrollment rows; reset eval stats derived from bad outcomes.
_SHADOW_RESET_SQL = """
UPDATE shadow_registry
SET last_eval_n                = NULL,
    last_eval_ev_r             = NULL,
    last_eval_ci_lower         = NULL,
    last_eval_win_rate         = NULL,
    demotion_consecutive_count = 0
"""

# Tables preserved (raw data / config) — shown in dry-run for reference.
_PRESERVED_TABLES = [
    "market_data_ohlcv",
    "instruments",
    "contract_metadata",
    "cis_weights",
    "config_state",
    "roll_events",
    "macro_features",
    "market_data_gaps",
    "dlq_events",
    "service_health_events",
    "system_events",
    "instrument_annotations",
    "instrument_tags",
    "tag_vocabulary",
    "parity_certification_state",
]


def _db_conn(settings: Settings):
    return psycopg2.connect(settings.database_url)


def _acquire_lock(conn) -> bool:
    with conn.cursor() as cur:
        cur.execute("SELECT pg_try_advisory_lock(%s)", (_RESET_LOCK_ID,))
        return cur.fetchone()[0]


def _check_services() -> list[str]:
    active = []
    for svc in _LIFECYCLE_SERVICES:
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
    try:
        with conn.cursor() as cur:
            cur.execute(f"SELECT COUNT(*) FROM {table}")
            return cur.fetchone()[0]
    except Exception:
        return -1


def _shadow_eval_count(conn) -> int:
    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM shadow_registry WHERE last_eval_n IS NOT NULL")
        return cur.fetchone()[0]


def _print_plan(conn) -> None:
    print("\n=== DATA RESET PLAN ===\n")
    print(f"{'Table':<40} {'Rows':>10}  {'What'}")
    print("-" * 90)
    for table, description in _TRUNCATE_TABLES:
        n = _row_count(conn, table)
        marker = "  " if n >= 0 else "? "
        print(f"  {table:<38} {n:>10,}  {description}")

    n_shadow = _shadow_eval_count(conn)
    print(
        f"  {'shadow_registry (eval stats)':<38} {n_shadow:>10,}  eval stats reset; enrollment rows kept"
    )
    print()
    print("Tables preserved (raw data / config / infrastructure):")
    for t in _PRESERVED_TABLES:
        n = _row_count(conn, t)
        print(f"  {t:<40} {n:>10,}")
    print()


def _execute_wipe(conn) -> None:
    print(f"[{_ts()}] Wiping signal-derived tables...")
    table_list = ", ".join(t for t, _ in _TRUNCATE_TABLES)
    with conn.cursor() as cur:
        # Single statement so PostgreSQL resolves FK relationships between listed tables.
        cur.execute(f"TRUNCATE {table_list}")
        for table, _ in _TRUNCATE_TABLES:
            print(f"  TRUNCATED {table}")
        cur.execute(_SHADOW_RESET_SQL)
        print("  RESET shadow_registry eval stats")
    conn.commit()
    print(f"[{_ts()}] Wipe complete.\n")


def _run_backfill(workers: int) -> None:
    print(f"[{_ts()}] Starting backfill replay (workers={workers})...")
    print("  Re-emits all signals with current framing code.")
    print("  --clean deletes signals+features per-symbol before replay.\n")
    cmd = [
        sys.executable,
        "-u",
        str(project_root / "scripts/infrastructure/backfill/infrastructure_run_historical_pipeline.py"),
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
    print("  Computes counterfactual_pnl_r, exits, MAE/MFE for freshly emitted signals.\n")
    cmd = [
        sys.executable,
        "-u",
        str(project_root / "scripts/debug/replay/debug_lifecycle_replay.py"),
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
        cur.execute("SELECT COUNT(*) FROM signal_events")
        n_signals = cur.fetchone()[0]

        cur.execute("SELECT COUNT(*) FROM trade_frames")
        n_frames = cur.fetchone()[0]

        cur.execute("SELECT COUNT(*) FROM trade_frames WHERE counterfactual_pnl_r IS NOT NULL")
        n_with_pnl = cur.fetchone()[0]

        cur.execute("SELECT COUNT(*) FROM signal_events WHERE ctf_score > 0")
        n_ctf_nonzero = cur.fetchone()[0]

        cur.execute("SELECT COUNT(*) FROM intelligence_features")
        n_features = cur.fetchone()[0]

    pnl_pct = (n_with_pnl / n_frames * 100) if n_frames else 0
    ctf_pct = (n_ctf_nonzero / n_signals * 100) if n_signals else 0

    print(f"  signal_events rows:              {n_signals:>10,}")
    print(f"  trade_frames rows:               {n_frames:>10,}")
    print(f"  frames with counterfactual_pnl_r:{n_with_pnl:>10,}  ({pnl_pct:.1f}%)")
    print(f"  signals with ctf_score > 0:      {n_ctf_nonzero:>10,}  ({ctf_pct:.1f}%)")
    print(f"  intelligence_features rows:      {n_features:>10,}")

    if ctf_pct < 50:
        print("\n  WARNING: ctf_score non-zero rate is low (<50%). I6 CTF bug may have recurred.")
    if pnl_pct < 80 and n_frames > 100:
        print(
            "\n  WARNING: counterfactual_pnl_r fill rate is low (<80%). Lifecycle replay may be incomplete."
        )

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

    active = _check_services()
    if active:
        print("ERROR: lifecycle-writing services are still active:")
        for svc in active:
            print(f"  {svc}")
        print("\nStop them first, e.g.:")
        print("  sudo systemctl stop indicagent-intelligence-pipeline indicagent-signal-writer")
        sys.exit(1)

    print(f"[{_ts()}] Confirmed. Executing full data reset...\n")

    _execute_wipe(conn)

    if not args.wipe_only:
        _run_backfill(args.workers)
        _run_lifecycle_replay(args.workers)
        conn = _db_conn(settings)
        _post_verify(conn)

    print(f"[{_ts()}] Reset complete.")
    print()
    print("Next steps:")
    print("  sudo systemctl start indicagent-intelligence-pipeline")
    print("  setup_performance:      refills tonight at 11pm via ml-training")
    print("  swarm_agent_weights:    refills Monday via ml-orchestrator")
    print("  tod_multipliers:        refills via ml-training after signal volume accumulates")


if __name__ == "__main__":
    main()
