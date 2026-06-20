#!/usr/bin/env python3
"""
Pipeline Progress Monitor — backfill, signal events, and signal lifecycle status.

Version: 1.0
Status: current
Last Updated: 2026-06-19

Queries market_data_ohlcv, intelligence_features, signal_events, trade_frames,
and trade_executions to show current corpus build progress. Run during or after
a corpus rebuild to monitor row counts and ingestion rates.

Usage:
    python production/scripts/pipeline_status.py
"""

import asyncio
import sys
from datetime import UTC, datetime

import asyncpg

DB_DSN = "postgresql://postgres:postgres@localhost/indicagent"

RATE_WINDOW_MINUTES = 5


async def _fetch(conn: asyncpg.Connection, method: str, sql: str):
    try:
        return await getattr(conn, method)(sql)
    except Exception as error:
        return error


async def fetch_all(conn: asyncpg.Connection) -> dict:
    now = datetime.now(UTC)
    return {
        "bars_summary": await _fetch(
            conn,
            "fetchrow",
            "SELECT COUNT(*) AS total, MAX(timestamp) AS last_ts FROM market_data_ohlcv",
        ),
        "bars_by_timeframe": await _fetch(
            conn,
            "fetch",
            "SELECT timeframe, COUNT(*) AS cnt FROM market_data_ohlcv GROUP BY timeframe ORDER BY timeframe",
        ),
        "features_summary": await _fetch(
            conn,
            "fetchrow",
            "SELECT COUNT(*) AS total, MAX(ts) AS last_ts FROM intelligence_features",
        ),
        "features_by_timeframe": await _fetch(
            conn,
            "fetch",
            "SELECT tf, COUNT(*) AS cnt FROM intelligence_features GROUP BY tf ORDER BY tf",
        ),
        "features_rate": await _fetch(
            conn,
            "fetchrow",
            f"SELECT COUNT(*) AS recent FROM intelligence_features WHERE computed_at > NOW() - INTERVAL '{RATE_WINDOW_MINUTES} minutes'",
        ),
        "signals_summary": await _fetch(
            conn, "fetchrow", "SELECT COUNT(*) AS total, MAX(ts) AS last_ts FROM signal_events"
        ),
        "signals_by_status": await _fetch(
            conn,
            "fetch",
            "SELECT status::text, COUNT(*) AS cnt FROM signal_events GROUP BY status ORDER BY cnt DESC",
        ),
        "signals_by_timeframe": await _fetch(
            conn, "fetch", "SELECT tf, COUNT(*) AS cnt FROM signal_events GROUP BY tf ORDER BY tf"
        ),
        "signals_top_plugins": await _fetch(
            conn,
            "fetch",
            "SELECT setup_plugin, COUNT(*) AS cnt FROM signal_events GROUP BY setup_plugin ORDER BY cnt DESC LIMIT 8",
        ),
        "signals_backfill": await _fetch(
            conn, "fetchrow", "SELECT COUNT(*) AS cnt FROM signal_events WHERE is_backfill = true"
        ),
        "signals_shadow_governance": await _fetch(
            conn, "fetchrow", "SELECT COUNT(*) AS cnt FROM signal_events WHERE is_shadow = true"
        ),
        "hypothesis_layer_summary": await _fetch(
            conn,
            "fetchrow",
            "SELECT COUNT(*) AS total, MAX(signal_ts) AS last_ts FROM trade_frames",
        ),
        "execution_layer_summary": await _fetch(
            conn, "fetchrow", "SELECT COUNT(*) AS total FROM trade_executions"
        ),
        "shadow_governance_evaluated": await _fetch(
            conn,
            "fetchrow",
            "SELECT COUNT(*) AS with_evaluations, SUM(last_eval_n) AS total_evaluations FROM shadow_registry WHERE last_eval_n IS NOT NULL AND last_eval_n > 0",
        ),
        "shadow_governance_total": await _fetch(
            conn, "fetchrow", "SELECT COUNT(*) AS total FROM shadow_registry"
        ),
        "fetched_at": now,
    }


def safe_get(row, key):
    if row is None or isinstance(row, Exception):
        return None
    return row[key]


def format_number(value) -> str:
    if value is None:
        return "—"
    return f"{int(value):,}"


def format_timestamp(ts) -> str:
    if ts is None:
        return "—"
    return ts.strftime("%Y-%m-%d %H:%M UTC")


def print_section(title: str) -> None:
    print(f"\n{'─' * 55}")
    print(f"  {title}")
    print(f"{'─' * 55}")


def render(snapshot: dict, prev: dict | None = None, interval: int | None = None) -> None:
    print(f"\n{'=' * 55}")
    print(f"  Pipeline Status  —  {snapshot['fetched_at'].strftime('%Y-%m-%d %H:%M:%S UTC')}")
    print(f"{'=' * 55}")

    # --- Market data ---
    print_section("MARKET DATA  (market_data_ohlcv)")
    print(f"  Total bars : {format_number(safe_get(snapshot['bars_summary'], 'total'))}")
    print(f"  Last ts    : {format_timestamp(safe_get(snapshot['bars_summary'], 'last_ts'))}")
    if isinstance(snapshot["bars_by_timeframe"], list):
        bars_by_timeframe = {row["timeframe"]: row["cnt"] for row in snapshot["bars_by_timeframe"]}
        for timeframe in ("1m", "5m", "15m", "1h", "4h", "1d"):
            print(f"    {timeframe:<4}  {format_number(bars_by_timeframe.get(timeframe))}")
    else:
        bars_by_timeframe = {}

    # --- Intelligence features ---
    print_section("INTELLIGENCE FEATURES  (intelligence_features)")
    feature_total = safe_get(snapshot["features_summary"], "total") or 0
    prev_feature_total = safe_get(prev["features_summary"], "total") if prev else None
    delta_str = ""
    if prev_feature_total is not None and interval:
        delta = feature_total - prev_feature_total
        per_minute = delta / (interval / 60)
        delta_str = f"  (+{delta:,} @ {per_minute:,.0f}/min)"
    recent_features = safe_get(snapshot.get("features_rate"), "recent")
    rate_str = ""
    if recent_features is not None:
        per_minute = recent_features / RATE_WINDOW_MINUTES
        rate_str = f"  ({per_minute:,.0f}/min)"
    print(f"  Total      : {format_number(feature_total)}{delta_str}{rate_str}")
    print(f"  Last ts    : {format_timestamp(safe_get(snapshot['features_summary'], 'last_ts'))}")
    if isinstance(snapshot["features_by_timeframe"], list):
        features_by_timeframe = {row["tf"]: row["cnt"] for row in snapshot["features_by_timeframe"]}
        for timeframe in ("1m", "5m", "15m", "1h", "4h", "1d"):
            feature_count = features_by_timeframe.get(timeframe) or 0
            bar_count = bars_by_timeframe.get(timeframe) or 0
            coverage = f"  {feature_count / bar_count * 100:.1f}%" if bar_count else ""
            print(f"    {timeframe:<4}  {format_number(feature_count)}{coverage}")

    # --- Signal events (detection layer) ---
    print_section("SIGNAL EVENTS  (detection layer)")
    print(f"  Total            : {format_number(safe_get(snapshot['signals_summary'], 'total'))}")
    print(
        f"  Last ts          : {format_timestamp(safe_get(snapshot['signals_summary'], 'last_ts'))}"
    )
    print(f"  Backfill         : {format_number(safe_get(snapshot['signals_backfill'], 'cnt'))}")
    print(
        f"  Shadow governance: {format_number(safe_get(snapshot['signals_shadow_governance'], 'cnt'))}"
    )

    if isinstance(snapshot["signals_by_status"], list):
        print("  By status:")
        for row in snapshot["signals_by_status"]:
            print(f"    {row['status']:<22}  {format_number(row['cnt'])}")

    if isinstance(snapshot["signals_by_timeframe"], list):
        print("  By timeframe:")
        signals_by_timeframe = {row["tf"]: row["cnt"] for row in snapshot["signals_by_timeframe"]}
        for timeframe in ("1m", "5m", "15m", "1h", "4h", "1d"):
            count = signals_by_timeframe.get(timeframe)
            if count:
                print(f"    {timeframe:<4}  {format_number(count)}")

    if isinstance(snapshot["signals_top_plugins"], list) and snapshot["signals_top_plugins"]:
        print("  Top plugins:")
        for row in snapshot["signals_top_plugins"]:
            print(f"    {row['setup_plugin']:<35}  {format_number(row['cnt'])}")

    # --- Signal lifecycle: hypothesis + execution layers (SLA) ---
    print_section("SIGNAL LIFECYCLE  (hypothesis + execution layers)")
    print(
        f"  Hypothesis layer (trade_frames)     : {format_number(safe_get(snapshot['hypothesis_layer_summary'], 'total'))}"
    )
    last_hypothesis_ts = safe_get(snapshot["hypothesis_layer_summary"], "last_ts")
    if last_hypothesis_ts:
        print(f"  Last hypothesis ts                  : {format_timestamp(last_hypothesis_ts)}")
    print(
        f"  Execution layer (trade_executions)  : {format_number(safe_get(snapshot['execution_layer_summary'], 'total'))}"
    )

    # --- Shadow governance ---
    print_section("SHADOW GOVERNANCE  (shadow_registry)")
    print(
        f"  Registered plugins     : {format_number(safe_get(snapshot['shadow_governance_total'], 'total'))}"
    )
    print(
        f"  Plugins with evaluations: {format_number(safe_get(snapshot['shadow_governance_evaluated'], 'with_evaluations'))}"
    )
    print(
        f"  Total evaluation count : {format_number(safe_get(snapshot['shadow_governance_evaluated'], 'total_evaluations'))}"
    )

    print(f"\n{'=' * 55}\n")


async def main() -> None:
    watch = "--watch" in sys.argv or "-w" in sys.argv
    interval = 30
    for arg in sys.argv[1:]:
        if arg.lstrip("-").isdigit():
            interval = int(arg.lstrip("-"))

    conn = await asyncpg.connect(DB_DSN)
    prev = None
    try:
        while True:
            snapshot = await fetch_all(conn)
            if watch:
                print("\033[2J\033[H", end="")  # clear screen
            render(snapshot, prev=prev, interval=interval if prev else None)
            prev = snapshot
            if not watch:
                break
            await asyncio.sleep(interval)
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
