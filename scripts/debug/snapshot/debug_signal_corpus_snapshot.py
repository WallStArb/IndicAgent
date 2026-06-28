#!/usr/bin/env python3
"""
Signal Corpus Snapshot — before/after comparison for corpus rebuilds.

Version: 1.0
Status: current
Last Updated: 2026-06-17

Queries signal_events, trade_frames, and trade_executions and writes a
JSON summary with row counts, cold-start metrics, and per-setup breakdown.
Use before and after a corpus rebuild to verify acceptance gates.

Usage:
    python scripts/debug/snapshot/debug_signal_corpus_snapshot.py [--output PATH]

    --output  Path for the JSON snapshot (default: docs/plans/signal-corpus-snapshot.json)
"""

from __future__ import annotations

import argparse
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

JOB_NAME = "signal-corpus-snapshot"


async def _capture(conn) -> dict:
    total_signal_events = await conn.fetchval("SELECT COUNT(*) FROM signal_events")
    total_trade_frames = await conn.fetchval("SELECT COUNT(*) FROM trade_frames")
    total_trade_executions = await conn.fetchval("SELECT COUNT(*) FROM trade_executions")

    cold_start_count = await conn.fetchval("""
        SELECT COUNT(*)
        FROM signal_events
        WHERE context_features IS NULL OR context_features = '{}'::jsonb
        """)
    non_cold_start_total = total_signal_events - cold_start_count

    if non_cold_start_total > 0:
        non_cold_start_with_features = await conn.fetchval("""
            SELECT COUNT(*)
            FROM signal_events
            WHERE context_features IS NOT NULL AND context_features != '{}'::jsonb
            """)
        coverage_pct = 100.0 * non_cold_start_with_features / non_cold_start_total
    else:
        coverage_pct = 0.0

    setup_rows = await conn.fetch("""
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
        """)

    setups = []
    for row in setup_rows:
        total_signals = row["total_signals"]
        selected = row["selected"] or 0
        selection_rate_pct = 100.0 * selected / total_signals if total_signals > 0 else 0.0

        setup_cold_start = row["cold_start_count"]
        setup_non_cold = total_signals - setup_cold_start

        if setup_non_cold > 0:
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


async def main(output_path: Path) -> None:
    settings = Settings()
    db = DatabaseManager(settings.database_url)
    await db.initialize()

    try:
        async with db.pool.acquire() as conn:
            print("Capturing signal corpus snapshot...")
            snapshot = await _capture(conn)

            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(json.dumps(snapshot, indent=2, default=str))

            print(f"\nSnapshot written: {output_path}")
            print(f"  signal_events:    {snapshot['totals']['signal_events']:,}")
            print(f"  trade_frames:     {snapshot['totals']['trade_frames']:,}")
            print(f"  trade_executions: {snapshot['totals']['trade_executions']:,}")
            print(f"  cold_start_count: {snapshot['cold_start']['cold_start_count']:,}")
            print(
                f"  coverage (non-cold-start): {snapshot['cold_start']['context_features_coverage_pct']:.2f}%"
            )
            print(f"  setups: {len(snapshot['setups'])}")

            JOB_COMPLETED_TOTAL.add(1, {"job": JOB_NAME, "status": "success"})

    except Exception as error:
        print(f"ERROR: {error}", file=sys.stderr)
        JOB_COMPLETED_TOTAL.add(1, {"job": JOB_NAME, "status": "failure"})
        raise
    finally:
        await db.close()
        flush_and_shutdown_metrics()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Capture signal corpus snapshot")
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("docs/plans/signal-corpus-snapshot.json"),
        help="Output path for the JSON snapshot",
    )
    args = parser.parse_args()

    try:
        init_otel_providers(JOB_NAME)
    except OTelInitError as error:
        print(f"[warn] OTel init failed — metrics disabled: {error}")

    asyncio.run(main(args.output))
