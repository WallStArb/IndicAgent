#!/usr/bin/env python3
"""
Pipeline Reset

Clears and regenerates the canonical IndicAgent dataset from raw OHLCV bars.
Run whenever signals change, schema changes, or data integrity is in question.

Renaissance principle: Data quality over model complexity. No ML model or alpha
claim is valid until the training dataset is clean, gap-free, and correctly
timestamped.

Usage:
    # Full reset — re-fetch from IBKR + replay
    python production/scripts/pipeline_reset.py

    # Fast reset — keep OHLCV, just re-replay through updated signal logic
    python production/scripts/pipeline_reset.py --keep-ohlcv

    # Specific symbols only
    python production/scripts/pipeline_reset.py --keep-ohlcv --symbols ESH6,NQH6

    # See what would happen without touching anything
    python production/scripts/pipeline_reset.py --dry-run
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import asyncio

import redis
from aiokafka.admin import AIOKafkaAdminClient, NewTopic
from aiokafka.errors import UnknownTopicOrPartitionError

# Allow running from repo root
sys.path.insert(0, str(Path(__file__).parents[2]))

# Reuse connect_db and replay logic from historical_backfill
from production.scripts.historical_backfill import (  # noqa: E402
    connect_db,
    replay_symbol,
)
from src.config.settings import Settings

# Tables cleared on every reset (always)
_ALWAYS_CLEAR = [
    "signal_ledger",
    "intelligence_features",
    "technical_indicators",
    "setup_performance",  # no symbol column — always truncated in full
    "drift_state",
    "drift_monitor",
]

# Tables in _ALWAYS_CLEAR that have no symbol column (always TRUNCATE, never per-symbol DELETE)
_ALWAYS_TRUNCATE = {"setup_performance"}

# Cleared only without --keep-ohlcv
_OHLCV_TABLE = "market_data_ohlcv"

# Cleared only with --clear-llm
_LLM_TABLES = ["llm_calls", "llm_model_scores"]

# Redis key patterns to clear (will be prefixed with env_prefix)
_REDIS_PATTERNS = ["indicators", "intelligence", "signals", "narratives"]

DEFAULT_TIMEFRAMES = ["1m", "5m", "15m", "1h", "1d"]

_STOP_SERVICES = [
    "indicagent-signal-generator",
    "indicagent-signal-lifecycle",
    "indicagent-market-analysis",
    "indicagent-feature-writer",
    "indicagent-ai-narrative",
]

_START_SERVICES = [
    "indicagent-market-analysis",
    "indicagent-feature-writer",
    "indicagent-signal-generator",
    "indicagent-signal-lifecycle",
    "indicagent-ai-narrative",
]


def _row_count(conn: Any, table: str) -> int:
    """Return row count for *table*.

    Uses fast stats estimate for large hypertables (market_data_ohlcv has 10k+
    chunks; COUNT(*) locks every chunk and hits max_locks_per_transaction).
    Falls back to exact COUNT(*) for small tables.
    """
    _APPROX_TABLES = {"market_data_ohlcv"}
    if table in _APPROX_TABLES:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT reltuples::bigint FROM pg_class WHERE relname = %s",
                (table,),
            )
            row = cur.fetchone()
            return row[0] if row and row[0] > 0 else 0
    with conn.cursor() as cur:
        cur.execute(f"SELECT COUNT(*) FROM {table}")  # noqa: S608
        row = cur.fetchone()
        return row[0] if row else 0


def build_preflight_summary(
    conn: Any,
    keep_ohlcv: bool,
    clear_llm: bool,
) -> str:
    """Return a human-readable summary of what will be cleared."""
    lines = ["DB tables:"]
    tables = list(_ALWAYS_CLEAR)
    if not keep_ohlcv:
        tables.append(_OHLCV_TABLE)
    if clear_llm:
        tables.extend(_LLM_TABLES)
    for table in tables:
        count = _row_count(conn, table)
        lines.append(f"  {table:<35} {count:>10,} rows")
    return "\n".join(lines)


def clear_redis_streams(r: redis.Redis, env_prefix: str) -> int:
    """Delete all pipeline stream keys for *env_prefix*. Returns key count deleted."""
    deleted = 0
    for pattern_name in _REDIS_PATTERNS:
        pattern = f"{env_prefix}:{pattern_name}:*"
        keys = list(r.scan_iter(pattern))
        if keys:
            r.delete(*keys)
            deleted += len(keys)
    return deleted


async def clear_kafka_topics(bootstrap_servers: str, env_prefix: str) -> int:
    """Delete and recreate all pipeline Kafka topics to flush all stream data.

    Returns number of topics cleared.
    """
    from production.scripts.kafka_init_topics import _TOPIC_SPECS

    prefix = f"{env_prefix}." if env_prefix else ""
    new_topics = [
        NewTopic(
            name=f"{prefix}{suffix}",
            num_partitions=partitions,
            replication_factor=1,
            topic_configs={"retention.ms": retention_ms},
        )
        for suffix, partitions, retention_ms in _TOPIC_SPECS
    ]
    topic_names = [t.name for t in new_topics]

    client = AIOKafkaAdminClient(bootstrap_servers=bootstrap_servers, request_timeout_ms=30000)
    await asyncio.wait_for(client.start(), timeout=30.0)
    try:
        try:
            await client.delete_topics(topic_names)
            await asyncio.sleep(1.0)  # allow deletion to propagate before recreating
        except UnknownTopicOrPartitionError:
            pass  # topics may not exist on first run
        try:
            await client.create_topics(new_topics)
        except Exception as e:
            if type(e).__name__ != "TopicAlreadyExistsError" and "already exists" not in str(e).lower():
                raise
    finally:
        await client.close()

    return len(topic_names)


def publish_reset_sentinel(r: redis.Redis, env_prefix: str, symbols: list[str]) -> None:
    """Publish a pipeline_reset event to system:events so SSE clients auto-clear state."""
    from src.core.stream_keys import system_events as sk_system_events

    key = sk_system_events(env_prefix)
    r.xadd(
        key,
        {
            "event": "pipeline_reset",
            "ts": datetime.now(UTC).isoformat(),
            "symbols": json.dumps(symbols),
        },
        maxlen=50,
    )


def truncate_tables(
    conn: Any,
    keep_ohlcv: bool,
    clear_llm: bool,
    symbols: list[str] | None = None,
) -> list[str]:
    """TRUNCATE target tables (or DELETE by symbol when symbols is given)."""
    tables = list(_ALWAYS_CLEAR)
    if not keep_ohlcv:
        tables.append(_OHLCV_TABLE)
    if clear_llm:
        tables.extend(_LLM_TABLES)

    with conn.cursor() as cur:
        if symbols:
            # Targeted per-symbol DELETE to preserve other symbols' data.
            # Tables in _ALWAYS_TRUNCATE have no symbol column — always truncate in full.
            placeholders = ",".join(["%s"] * len(symbols))
            for table in tables:
                if table in _ALWAYS_TRUNCATE:
                    cur.execute(f"TRUNCATE {table} CASCADE")  # noqa: S608
                else:
                    cur.execute(
                        f"DELETE FROM {table} WHERE symbol = ANY(ARRAY[{placeholders}])", symbols
                    )  # noqa: S608
        else:
            for table in tables:
                cur.execute(f"TRUNCATE {table} CASCADE")  # noqa: S608
    conn.commit()
    return tables


def verify_dataset(conn: Any) -> tuple[bool, str]:
    """Check that the reset produced non-empty tables.

    Returns (ok, report_string).
    """
    lines = ["Verification:"]
    ok = True

    for table in ["signal_ledger", "intelligence_features", "market_data_ohlcv"]:
        count = _row_count(conn, table)
        status = "OK" if count > 0 else "EMPTY ⚠"
        if count == 0:
            ok = False
        lines.append(f"  {table:<35} {count:>10,} rows  [{status}]")

    # Per-symbol/TF signal breakdown
    with conn.cursor() as cur:
        cur.execute("""
            SELECT symbol, timeframe, count(*) as n,
                   min(timestamp)::date, max(timestamp)::date
            FROM signal_ledger
            GROUP BY symbol, timeframe
            ORDER BY symbol, timeframe
        """)
        rows = cur.fetchall()

    if rows:
        lines.append("\n  Signals per symbol/TF:")
        for sym, tf, n, min_dt, max_dt in rows:
            lines.append(f"    {sym:<8} {tf:<4}  {n:>6,} signals  ({min_dt} → {max_dt})")
    else:
        lines.append("\n  No signals — check replay completed successfully")
        ok = False

    return ok, "\n".join(lines)


def _pause_for_services(action: str, services: list[str]) -> None:
    """Print service commands and wait for user to press Enter."""
    verb = "stop" if action == "stop" else "start"
    print(f"\n{'='*50}")
    print(f"{action.upper()} pipeline services before continuing:")
    print()
    for svc in services:
        print(f"  sudo systemctl {verb} {svc}")
    print()
    input(f"Press Enter when services are {verb}ped...")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Pipeline Reset — clear and regenerate canonical IndicAgent dataset"
    )
    parser.add_argument(
        "--keep-ohlcv",
        action="store_true",
        help="Skip IBKR re-fetch; replay from existing market_data_ohlcv",
    )
    parser.add_argument(
        "--symbols", default=None, help="Comma-separated symbols (default: all active contracts)"
    )
    parser.add_argument(
        "--days",
        type=int,
        default=14,
        help="Days of 1m history to fetch (default: 14; other TFs use _TF_FETCH_CONFIG)",
    )
    parser.add_argument(
        "--clear-llm", action="store_true", help="Also truncate llm_calls and llm_model_scores"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be cleared; exit without touching anything",
    )
    parser.add_argument("--yes", action="store_true", help="Skip confirmation prompt")
    parser.add_argument("--client-id", type=int, default=56, help="IBKR client ID (default: 56)")
    args = parser.parse_args()

    settings = Settings()
    t_start = time.time()

    # --- Preflight ---
    db_conn = connect_db(settings)
    print("\nPipeline Reset")
    print("=" * 50)
    if args.dry_run:
        print("DRY RUN — nothing will be modified\n")
    print(build_preflight_summary(db_conn, args.keep_ohlcv, args.clear_llm))
    print()

    if args.dry_run:
        db_conn.close()
        return

    if not args.yes:
        answer = input("This cannot be undone. Type YES to continue: ")
        if answer.strip() != "YES":
            print("Aborted.")
            db_conn.close()
            return

    # Resolve target symbols early so they're available for sentinel and all stages
    target_symbols = (
        [s.strip() for s in args.symbols.split(",") if s.strip()] if args.symbols else None
    )

    # --- Stage 1: Stop services ---
    _pause_for_services("stop", _STOP_SERVICES)

    # --- Stage 2: Clear Kafka topics ---
    kafka_env_prefix = settings.env_name or ""
    print("\n[1/5] Clearing Kafka topics (delete + recreate)...")
    bootstrap = getattr(settings, "kafka_bootstrap_servers", None)
    if bootstrap is None:
        print("      WARNING: kafka_bootstrap_servers not configured, using localhost:19092")
        bootstrap = "localhost:19092"
    n_topics = asyncio.run(clear_kafka_topics(bootstrap, env_prefix=kafka_env_prefix))
    print(f"      Cleared {n_topics} Kafka topics")

    # --- Stage 3: Truncate DB ---
    print("\n[2/5] Truncating DB tables...")
    cleared = truncate_tables(db_conn, args.keep_ohlcv, args.clear_llm, symbols=target_symbols)
    verb = "DELETED rows for specified symbols in" if target_symbols else "TRUNCATED"
    for t in cleared:
        print(f"      {verb} {t}")

    # --- Stage 4: Fetch OHLCV ---
    contracts = settings.contracts
    if args.symbols:
        wanted = {s.strip() for s in args.symbols.split(",") if s.strip()}
        contracts = [c for c in contracts if c.symbol in wanted]
        if not contracts:
            print(f"No matching contracts for: {args.symbols}")
            db_conn.close()
            return

    if not args.keep_ohlcv:
        print("\n[3/5] Fetching OHLCV from IBKR...")
        from production.scripts.historical_backfill import (
            _TF_FETCH_CONFIG,
            store_bars,
        )
        from src.providers import IBKRProvider

        provider = IBKRProvider(
            host=settings.ib_host,
            port=settings.ib_port,
            client_id=args.client_id,
        )
        if not asyncio.run(provider.connect()):
            print("  Cannot connect to TWS — skipping fetch (will replay existing OHLCV)")
        else:
            end_dt = datetime.now(tz=UTC)
            fetch_tfs = list(_TF_FETCH_CONFIG.keys())
            for instrument in contracts:
                try:
                    qualified = asyncio.run(provider.qualify_instrument(instrument))
                    if not qualified:
                        print(f"  {instrument.symbol}: qualify failed — skipping")
                        continue
                    for tf in fetch_tfs:
                        fetch_days, use_continuous = _TF_FETCH_CONFIG[tf]
                        if tf == "1m":
                            fetch_days = args.days
                        if fetch_days <= 14:
                            use_continuous = False
                        start_dt = (end_dt - timedelta(days=fetch_days)).replace(
                            hour=0, minute=0, second=0, microsecond=0
                        )
                        try:
                            ohlcv_bars = asyncio.run(
                                provider.fetch_historical_bars(
                                    symbol=instrument.symbol,
                                    timeframe=tf,
                                    start=start_dt,
                                    end=end_dt,
                                    continuous=use_continuous,
                                )
                            )
                            bar_dicts = [
                                {
                                    "timestamp": b.timestamp,
                                    "open": b.open,
                                    "high": b.high,
                                    "low": b.low,
                                    "close": b.close,
                                    "volume": b.volume,
                                    "source": b.source,
                                }
                                for b in ohlcv_bars
                            ]
                            if bar_dicts:
                                n = store_bars(db_conn, bar_dicts, instrument.symbol, tf)
                                label = "continuous-adj" if use_continuous else "named"
                                sym = instrument.symbol
                                print(f"  {sym}/{tf} ({label}, {fetch_days}d): {n:,} bars")
                        except Exception as e:
                            print(f"  {instrument.symbol}/{tf}: error — {e}")
                        time.sleep(2)  # IBKR pacing between TF requests
                except Exception as e:
                    print(f"  {instrument.symbol}: fetch error — {e}")
            asyncio.run(provider.disconnect())
    else:
        print("\n[3/5] Skipping IBKR fetch (--keep-ohlcv)")

    # --- Stage 5: Replay pipeline ---
    print("\n[4/5] Replaying I1→I7 pipeline...")
    for contract in contracts:
        counts = replay_symbol(
            symbol=contract.symbol,
            db_conn=db_conn,
            timeframes=DEFAULT_TIMEFRAMES,
        )
        for tf, n in counts.items():
            print(f"  {contract.symbol}/{tf}: {n:,} signals")

    # --- Stage 6: Verify ---
    print("\n[5/5] Verifying dataset...")
    ok, report = verify_dataset(db_conn)
    print(report)
    if not ok:
        print("\n⚠  Verification failed — check above for empty tables")

    db_conn.close()

    # --- Restart services ---
    _pause_for_services("start", _START_SERVICES)

    # --- Summary ---
    elapsed = time.time() - t_start
    m, s = divmod(int(elapsed), 60)
    print(f"\n{'='*50}")
    print(f"Pipeline Reset {'Complete ✓' if ok else 'Complete with warnings ⚠'}")
    print(f"Elapsed: {m}m {s}s")
    print()


if __name__ == "__main__":
    main()
