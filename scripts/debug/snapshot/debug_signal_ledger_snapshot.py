#!/usr/bin/env python3
"""
debug_signal_ledger_snapshot.py — per-setup signal metrics capture before rebuild

Writes docs/plans/signal-ledger-snapshot.json as the authoritative "before" baseline
for comparison after corpus rebuild; uses advisory lock for atomicity with delete operations.
Run ONCE before executing clean+replay; aborts if snapshot file already exists.
Requires TimescaleDB with signal_ledger view populated.
"""

from __future__ import annotations

import asyncio
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_PROJECT_ROOT))

from src.config.settings import Settings
from src.core.database_manager import DatabaseManager
from src.observability.metrics import JOB_COMPLETED_TOTAL, flush_and_shutdown_metrics
from src.observability.otel import OTelInitError, init_otel_providers

# Same advisory lock ID as lifecycle_replay.py — ensures atomicity with the later delete.
# Changing this would allow concurrent snapshot + delete operations.
_REPLAY_LOCK_ID = 20260602

_SNAPSHOT_PATH = _PROJECT_ROOT / "docs" / "plans" / "signal-ledger-snapshot.json"


async def _fetch_snapshot(conn) -> list:
    """Capture per-setup distribution-aware metrics before any deletes.

    Uses the expanded SQL from CONTEXT.md D-04 with full pnl_r distribution
    statistics (std, N, percentiles) enabling Welch's t-test in Wave 2.
    """
    return await conn.fetch("""SELECT
               sl.setup_plugin,
               sl.is_shadow,
               COUNT(*) AS total_signals,
               COUNT(*) FILTER (WHERE sl.was_selected = true) AS selected,
               AVG(CASE WHEN sl.was_selected = true THEN 1.0 ELSE 0.0 END) AS selection_rate,
               AVG(so.pnl_r) FILTER (WHERE so.pnl_r IS NOT NULL) AS avg_pnl_r,
               STDDEV(so.pnl_r) FILTER (WHERE so.pnl_r IS NOT NULL) AS pnl_r_std,
               COUNT(so.pnl_r) FILTER (WHERE so.pnl_r IS NOT NULL) AS pnl_r_n,
               PERCENTILE_CONT(0.05) WITHIN GROUP (ORDER BY so.pnl_r)
                   FILTER (WHERE so.pnl_r IS NOT NULL) AS pnl_r_p05,
               PERCENTILE_CONT(0.25) WITHIN GROUP (ORDER BY so.pnl_r)
                   FILTER (WHERE so.pnl_r IS NOT NULL) AS pnl_r_p25,
               PERCENTILE_CONT(0.50) WITHIN GROUP (ORDER BY so.pnl_r)
                   FILTER (WHERE so.pnl_r IS NOT NULL) AS pnl_r_p50,
               PERCENTILE_CONT(0.75) WITHIN GROUP (ORDER BY so.pnl_r)
                   FILTER (WHERE so.pnl_r IS NOT NULL) AS pnl_r_p75,
               PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY so.pnl_r)
                   FILTER (WHERE so.pnl_r IS NOT NULL) AS pnl_r_p95,
               COUNT(so.pnl_r) FILTER (WHERE so.pnl_r > 0) AS win_count,
               CORR(sl.cis_score, (so.pnl_r > 0)::int)
                   FILTER (WHERE so.pnl_r IS NOT NULL) AS calibration_corr,
               COUNT(*) FILTER (WHERE sl.counterfactual_pnl_r > 0) AS outcome_win,
               COUNT(*) FILTER (WHERE sl.counterfactual_pnl_r <= 0) AS outcome_loss,
               COUNT(*) FILTER (WHERE sl.counterfactual_pnl_r IS NULL) AS outcome_unresolved
           FROM signal_ledger sl
           GROUP BY sl.setup_plugin, sl.is_shadow
           ORDER BY total_signals DESC""")


def _write_snapshot(rows: list) -> None:
    """Write the before-snapshot JSON file.

    Guard: if the file already exists, aborts with SystemExit(1) — never
    overwrite an existing baseline.
    """
    if _SNAPSHOT_PATH.exists():
        print(
            f"ABORT: snapshot file already exists at {_SNAPSHOT_PATH}. "
            "Delete it first if you need to regenerate the baseline."
        )
        raise SystemExit(1)

    snapshot = {
        "captured_at": datetime.now(UTC).isoformat(),
        "setups": [
            {
                "setup_plugin": row["setup_plugin"],
                "is_shadow": row["is_shadow"],
                "total_signals": row["total_signals"],
                "selected": row["selected"],
                "selection_rate": row["selection_rate"],
                "avg_pnl_r": row["avg_pnl_r"],
                "pnl_r_std": row["pnl_r_std"],
                "pnl_r_n": row["pnl_r_n"],
                "pnl_r_p05": row["pnl_r_p05"],
                "pnl_r_p25": row["pnl_r_p25"],
                "pnl_r_p50": row["pnl_r_p50"],
                "pnl_r_p75": row["pnl_r_p75"],
                "pnl_r_p95": row["pnl_r_p95"],
                "win_count": row["win_count"],
                "calibration_corr": row["calibration_corr"],
                "outcome_expired": row["outcome_expired"],
                "outcome_stopped_at_entry": row["outcome_stopped_at_entry"],
                "outcome_filled": row["outcome_filled"],
            }
            for row in rows
        ],
    }
    _SNAPSHOT_PATH.parent.mkdir(parents=True, exist_ok=True)
    _SNAPSHOT_PATH.write_text(json.dumps(snapshot, indent=2, default=str))
    print(f"Snapshot written to {_SNAPSHOT_PATH} ({len(rows)} setups)")


async def _amain() -> int:
    """Main async entry point."""
    settings = Settings()
    db = DatabaseManager(settings.database_url)
    await db.initialize()
    try:
        async with db.pool.acquire() as conn:
            # Acquire advisory lock for atomicity with the later delete operation.
            row = await conn.fetchrow(
                "SELECT pg_try_advisory_lock($1) AS acquired", _REPLAY_LOCK_ID
            )
            if not row["acquired"]:
                print(
                    "ABORT: advisory lock already held (lifecycle_replay.py may be running). "
                    "Wait for it to complete and re-run."
                )
                return 1
            try:
                print("Advisory lock acquired — capturing before-snapshot...")
                rows = await _fetch_snapshot(conn)
                print(f"Snapshot query returned {len(rows)} setup rows")
            finally:
                await conn.execute("SELECT pg_advisory_unlock($1)", _REPLAY_LOCK_ID)

        _write_snapshot(rows)
        JOB_COMPLETED_TOTAL.add(1, {"job": "signal-ledger-snapshot", "status": "success"})
        return 0
    except SystemExit:
        JOB_COMPLETED_TOTAL.add(1, {"job": "signal-ledger-snapshot", "status": "failure"})
        raise
    except Exception as error:
        print(f"ERROR: {error}")
        JOB_COMPLETED_TOTAL.add(1, {"job": "signal-ledger-snapshot", "status": "failure"})
        return 1
    finally:
        await db.close()


def main() -> None:
    try:
        init_otel_providers("signal-ledger-snapshot")
    except OTelInitError as error:
        print(f"[warn] OTel init failed — metrics disabled: {error}")
    try:
        exit_code = asyncio.run(_amain())
    finally:
        flush_and_shutdown_metrics()
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
