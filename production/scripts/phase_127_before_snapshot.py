#!/usr/bin/env python3
"""
Pre-replay baseline capture for Phase 127 clean replay.

Targets 3-table schema (signal_events/trade_frames/trade_executions).
Captures the "before" anchor for the validation report's signal volume delta.

This baseline MUST be regenerated on the 3-table schema — the old
phase-121-before-snapshot.json is incompatible (it referenced
signal_ledger + signal_outcomes, both dropped in Phase 130).

Usage:
    python production/scripts/phase_127_before_snapshot.py
"""

from __future__ import annotations

import asyncio
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[2]))

from src.config.settings import Settings
from src.core.database_manager import DatabaseManager
from src.core.service_utils import format_iso_ts
from src.observability.metrics import JOB_COMPLETED_TOTAL, flush_and_shutdown_metrics
from src.observability.otel import OTelInitError, init_otel_providers


async def _capture_baseline(conn) -> dict:
    """
    Capture pre-replay baseline on 3-table schema.

    Returns a JSON-serializable dict with:
    - Total row counts (signal_events, trade_frames, trade_executions)
    - Cold-start metrics (cold_start_count, non_cold_start_total, coverage_pct)
    - Per-setup breakdown (signal counts, selection rates, cold-start, stopped_at_entry)

    All queries target 3-table schema ONLY. Do NOT reference:
    - signal_outcomes (dropped)
    - signal_ledger_full (renamed to signal_ledger)
    - signal_type, feature_tf, bucket_scores, staleness_score (dropped columns)
    """

    # Totals
    total_signal_events = await conn.fetchval("SELECT COUNT(*) FROM signal_events")
    total_trade_frames = await conn.fetchval("SELECT COUNT(*) FROM trade_frames")
    total_trade_executions = await conn.fetchval("SELECT COUNT(*) FROM trade_executions")

    # Cold-start metrics
    # Cold-start = context_features IS NULL or '{}'::jsonb
    cold_start_count = await conn.fetchval(
        """
        SELECT COUNT(*)
        FROM signal_events
        WHERE context_features IS NULL OR context_features = '{}'::jsonb
        """
    )
    non_cold_start_total = total_signal_events - cold_start_count

    # Coverage on non-cold-start subset
    if non_cold_start_total > 0:
        non_cold_start_with_features = await conn.fetchval(
            """
            SELECT COUNT(*)
            FROM signal_events
            WHERE context_features IS NOT NULL AND context_features != '{}'::jsonb
            """
        )
        coverage_pct = 100.0 * non_cold_start_with_features / non_cold_start_total
    else:
        coverage_pct = 0.0

    # Per-setup breakdown
    setup_rows = await conn.fetch(
        """
        SELECT
            se.setup_plugin,
            se.is_shadow,
            COUNT(*) AS total_signals,
            COUNT(*) FILTER (WHERE tf.was_selected) AS selected,
            COUNT(*) FILTER (
                WHERE se.context_features IS NULL OR se.context_features = '{}'::jsonb
            ) AS cold_start_count,
            COUNT(*) FILTER (WHERE te.exit_reason = 'stopped_at_entry') AS stopped_at_entry_count
        FROM signal_events se
        LEFT JOIN trade_frames tf ON tf.signal_id = se.signal_id
        LEFT JOIN trade_executions te ON te.frame_id = tf.frame_id
        GROUP BY se.setup_plugin, se.is_shadow
        ORDER BY se.setup_plugin, se.is_shadow
        """
    )

    setups = []
    for row in setup_rows:
        total_signals = row["total_signals"]
        selected = row["selected"] or 0  # Handle NULL from LEFT JOIN
        selection_rate_pct = 100.0 * selected / total_signals if total_signals > 0 else 0.0

        # Coverage on non-cold-start subset for this setup
        setup_cold_start = row["cold_start_count"]
        setup_non_cold = total_signals - setup_cold_start

        if setup_non_cold > 0:
            # Need to re-query with context_features filter for this specific setup
            setup_with_features = await conn.fetchval(
                """
                SELECT COUNT(*)
                FROM signal_events
                WHERE setup_plugin = $1
                    AND is_shadow = $2
                    AND context_features IS NOT NULL
                    AND context_features != '{}'::jsonb
                """,
                row["setup_plugin"],
                row["is_shadow"],
            )
            setup_coverage_pct = 100.0 * setup_with_features / setup_non_cold
        else:
            setup_coverage_pct = 0.0

        setups.append(
            {
                "setup_plugin": row["setup_plugin"],
                "is_shadow": row["is_shadow"],
                "total_signals": total_signals,
                "selected": selected,
                "selection_rate_pct": round(selection_rate_pct, 2),
                "context_features_coverage_pct": round(setup_coverage_pct, 2),
                "cold_start_count": setup_cold_start,
                "stopped_at_entry_count": row["stopped_at_entry_count"] or 0,
            }
        )

    return {
        "captured_at": format_iso_ts(datetime.now(UTC)),
        "schema": "3-table (signal_events/trade_frames/trade_executions)",
        "totals": {
            "signal_events": total_signal_events,
            "trade_frames": total_trade_frames,
            "trade_executions": total_trade_executions,
        },
        "cold_start": {
            "cold_start_count": cold_start_count,
            "non_cold_start_total": non_cold_start_total,
            "context_features_coverage_pct": round(coverage_pct, 2),
        },
        "setups": setups,
    }


async def main():
    settings = Settings()
    db = DatabaseManager(settings.database_url)
    await db.initialize()

    try:
        async with db.pool.acquire() as conn:
            print("Capturing pre-replay baseline on 3-table schema...")
            baseline = await _capture_baseline(conn)

            # Write JSON
            output_path = Path("docs/plans/phase-127-before-snapshot.json")
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(json.dumps(baseline, indent=2, default=str))

            print(f"\nBaseline captured: {output_path}")
            print(f"  signal_events: {baseline['totals']['signal_events']:,}")
            print(f"  trade_frames: {baseline['totals']['trade_frames']:,}")
            print(f"  trade_executions: {baseline['totals']['trade_executions']:,}")
            print(f"  cold_start_count: {baseline['cold_start']['cold_start_count']:,}")
            print(f"  coverage (non-cold-start): {baseline['cold_start']['context_features_coverage_pct']:.2f}%")
            print(f"  setups: {len(baseline['setups'])}")

            JOB_COMPLETED_TOTAL.add(1, {"job": "phase-127-before-snapshot", "status": "success"})

    except Exception as error:
        print(f"ERROR: {error}", file=sys.stderr)
        JOB_COMPLETED_TOTAL.add(1, {"job": "phase-127-before-snapshot", "status": "failure"})
        raise
    finally:
        await db.close()
        flush_and_shutdown_metrics()


if __name__ == "__main__":
    try:
        init_otel_providers("phase-127-before-snapshot")
    except OTelInitError as error:
        print(f"[warn] OTel init failed — metrics disabled: {error}")

    asyncio.run(main())
