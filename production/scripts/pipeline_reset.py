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

    # Seed reset — wipe everything, seed recent named-contract bars, replay
    # (real prices only; no back-adjustment artifacts; short warm-up window)
    python production/scripts/pipeline_reset.py --no-backfill

    # Specific symbols only
    python production/scripts/pipeline_reset.py --keep-ohlcv --symbols ESH6,NQH6

    # See what would happen without touching anything
    python production/scripts/pipeline_reset.py --dry-run
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from aiokafka.admin import AIOKafkaAdminClient, NewTopic
from aiokafka.errors import UnknownTopicOrPartitionError

# Allow running from repo root
sys.path.insert(0, str(Path(__file__).parents[2]))

# Reuse connect_db and replay logic from historical_backfill
from production.scripts.historical_backfill import (  # noqa: E402
    connect_db,
    replay_symbol,
    seed_roll_chain,
)
from src.intelligence.register_plugins import register_all_plugins
from src.config.settings import Settings
from src.core.database_manager import DatabaseManager

# Tables cleared on every reset (always)
_ALWAYS_CLEAR = [
    "signal_ledger",
    "intelligence_features",
    "setup_performance",      # no symbol column — always truncated in full
    "drift_state",
    "drift_monitor",
    "confidence_calibration", # isotonic regression curves — fit on signal outcomes
    "cis_weights",            # CIS aggregator weights — learned from signal outcomes
    "system_events",          # roll/pipeline event log — ephemeral operational data
    "instruments",            # Active traded instruments
    "contract_metadata",      # Contract-specific metadata
    "pattern_reliability",    # Historical pattern reliability
    "llm_calls",              # LLM call audit log
    "llm_model_scores",       # LLM performance scores
]

# Tables in _ALWAYS_CLEAR that have no symbol column (always TRUNCATE, never per-symbol DELETE)
_ALWAYS_TRUNCATE = {
    "setup_performance",
    "confidence_calibration",
    "cis_weights",
    "system_events",
    "instruments",
    "pattern_reliability",
    "contract_metadata",
    "llm_calls",
    "llm_model_scores",
}

# Cleared only without --keep-ohlcv
_OHLCV_TABLE = "market_data_ohlcv"

# Seed depths for --no-backfill mode: short, named-contract-only windows.
# All values are <= 90d so IBKR returns named front-month bars (no back-adjustment).
# Real prices only — no continuous-adjusted artifacts that distort signal fire prices and stops.
_TF_SEED_CONFIG: dict[str, int] = {
    "1m":  3,   # ~1,170 bars — warm up I1 indicators, intraday pattern coverage
    "5m":  7,   # ~546 bars  — one full week of session context
    "15m": 21,  # ~546 bars  — 3 weeks of pattern detection history
    "1h":  45,  # ~293 bars  — ~6 weeks of regime context
    "1d":  90,  # ~90 bars   — 3 months of macro structure
}

# Cleared only with --clear-llm
_LLM_TABLES = ["llm_calls", "llm_model_scores"]

DEFAULT_TIMEFRAMES = ["1m", "5m", "15m", "1h", "1d"]

_STOP_SERVICES = [
    "indicagent-signal-generator",
    "indicagent-signal-lifecycle",
    "indicagent-feature-pipeline",
    "indicagent-feature-writer",
    "indicagent-ai-narrative",
]

_START_SERVICES = [
    "indicagent-feature-pipeline",
    "indicagent-feature-writer",
    "indicagent-signal-generator",
    "indicagent-signal-lifecycle",
    "indicagent-ai-narrative",
]


def _row_count(conn: Any, table: str) -> int:
    """Return row count for *table*, or -1 if the table does not exist.

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
    try:
        with conn.cursor() as cur:
            cur.execute(f"SELECT COUNT(*) FROM {table}")  # noqa: S608
            row = cur.fetchone()
            return row[0] if row else 0
    except Exception:
        conn.rollback()
        return -1  # table does not exist


def build_preflight_summary(
    conn: Any,
    keep_ohlcv: bool,
    clear_llm: bool,
    no_backfill: bool = False,
) -> str:
    """Return a human-readable summary of what will be cleared."""
    lines = ["DB tables to clear:"]
    tables = list(_ALWAYS_CLEAR)
    if not keep_ohlcv and not no_backfill:
        tables.append(_OHLCV_TABLE)
    elif no_backfill:
        # --no-backfill wipes OHLCV too — no point keeping it if we won't replay
        tables.append(_OHLCV_TABLE)
    if clear_llm or no_backfill:
        tables.extend(_LLM_TABLES)
    for table in tables:
        count = _row_count(conn, table)
        if count == -1:
            lines.append(f"  {table:<35} (table not yet created — skip)")
        else:
            lines.append(f"  {table:<35} {count:>10,} rows")
    if no_backfill:
        lines.append("\nMode: seed — named-contract bars only, no back-adjustment")
        for tf, days in _TF_SEED_CONFIG.items():
            lines.append(f"  {tf}: {days}d")
    return "\n".join(lines)


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


def truncate_tables(
    conn: Any,
    keep_ohlcv: bool,
    clear_llm: bool,
    symbols: list[str] | None = None,
    no_backfill: bool = False,
) -> list[str]:
    """TRUNCATE target tables (or DELETE by symbol when symbols is given)."""
    tables = list(_ALWAYS_CLEAR)
    # --no-backfill wipes OHLCV — no replay means keeping it would leave stale prices
    if not keep_ohlcv or no_backfill:
        tables.append(_OHLCV_TABLE)
    # --no-backfill always clears LLM tables — narratives for non-existent signals are worthless
    if clear_llm or no_backfill:
        tables.extend(_LLM_TABLES)

    cleared = []
    with conn.cursor() as cur:
        if symbols:
            # Targeted per-symbol DELETE to preserve other symbols' data.
            # Tables in _ALWAYS_TRUNCATE have no symbol column — always truncate in full.
            placeholders = ",".join(["%s"] * len(symbols))
            for table in tables:
                if _row_count(conn, table) == -1:
                    continue  # table not yet created — skip silently
                if table in _ALWAYS_TRUNCATE:
                    cur.execute(f"TRUNCATE {table} CASCADE")  # noqa: S608
                else:
                    cur.execute(
                        f"DELETE FROM {table} WHERE symbol = ANY(ARRAY[{placeholders}])", symbols
                    )  # noqa: S608
                cleared.append(table)
        else:
            for table in tables:
                if _row_count(conn, table) == -1:
                    continue  # table not yet created — skip silently
                cur.execute(f"TRUNCATE {table} CASCADE")  # noqa: S608
                cleared.append(table)
    conn.commit()
    return cleared


def verify_dataset(conn: Any, seed_mode: bool = False) -> tuple[bool, str]:
    """Check that the reset produced the expected table state.

    seed_mode=True: signal_ledger must be empty (I7 was skipped); intelligence_features
    and market_data_ohlcv must be non-empty (warmup bars written).

    Returns (ok, report_string).
    """
    lines = ["Verification:"]
    ok = True

    for table in ["market_data_ohlcv", "intelligence_features"]:
        count = _row_count(conn, table)
        status = "OK" if count > 0 else "EMPTY ⚠"
        if count == 0:
            ok = False
        lines.append(f"  {table:<35} {count:>10,} rows  [{status}]")

    sl_count = _row_count(conn, "signal_ledger")
    if seed_mode:
        status = "CLEAN ✓" if sl_count == 0 else f"NOT EMPTY ⚠ ({sl_count:,} rows)"
        if sl_count > 0:
            ok = False
        lines.append(f"  {'signal_ledger':<35} {status}")
        lines.append("\n  Seed mode — signals will fire from live bars only")
    else:
        status = "OK" if sl_count > 0 else "EMPTY ⚠"
        if sl_count == 0:
            ok = False
        lines.append(f"  {'signal_ledger':<35} {sl_count:>10,} rows  [{status}]")

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


def _pause_for_services(action: str, services: list[str], auto_confirm: bool = False) -> None:
    """Print service commands and wait for user to press Enter, or auto-execute if auto_confirm=True."""
    verb = "stop" if action == "stop" else "start"
    print(f"\n{'='*50}")
    if auto_confirm:
        print(f"{action.upper()} pipeline services automatically (--yes flag):")
        import subprocess
        for svc in services:
            cmd = ["sudo", "systemctl", verb, svc]
            print(f"  {' '.join(cmd)}")
            try:
                result = subprocess.run(cmd, capture_output=True, text=True)
                if result.returncode != 0:
                    print(f"    Warning: {result.stderr.strip()}")
            except Exception as e:
                print(f"    Error: {e}")
    else:
        print(f"{action.UPPER()} pipeline services before continuing:")
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
        "--no-backfill",
        action="store_true",
        help=(
            "Wipe all derived data then seed short named-contract windows "
            f"({', '.join(f'{tf}={d}d' for tf, d in _TF_SEED_CONFIG.items())}) — "
            "real prices only, no back-adjustment"
        ),
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
    print(build_preflight_summary(db_conn, args.keep_ohlcv, args.clear_llm, args.no_backfill))
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
    _pause_for_services("stop", _STOP_SERVICES, auto_confirm=args.yes)

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
    cleared = truncate_tables(
        db_conn, args.keep_ohlcv, args.clear_llm,
        symbols=target_symbols, no_backfill=args.no_backfill,
    )
    verb = "DELETED rows for specified symbols in" if target_symbols else "TRUNCATED"
    for t in cleared:
        print(f"      {verb} {t}")

    # Re-seed contract_metadata — truncate_tables() wipes it, so tws_daemon would
    # pick up 0 futures from get_active_contracts() and never subscribe to them.
    print("      re-seeding contract_metadata (front-month roll chain)...")
    async def _seed_contract_metadata() -> None:
        _dm = DatabaseManager(settings.database_url)
        await _dm.initialize()
        await seed_roll_chain(settings, _dm)
        await _dm.close()
    asyncio.run(_seed_contract_metadata())

    # --- Stage 4: Fetch OHLCV ---
    contracts = settings.contracts
    if args.symbols:
        wanted = {s.strip() for s in args.symbols.split(",") if s.strip()}
        contracts = [c for c in contracts if c.symbol in wanted]
        if not contracts:
            print(f"No matching contracts for: {args.symbols}")
            db_conn.close()
            return

    from production.scripts.historical_backfill import store_bars
    from src.providers import IBKRProvider

    def _fetch_ohlcv(tf_config: dict[str, tuple[int, bool]]) -> None:
        """Fetch OHLCV bars for all contracts using the given per-TF config."""
        provider = IBKRProvider(
            host=settings.ib_host,
            port=settings.ib_port,
            client_id=args.client_id,
        )
        if not asyncio.run(provider.connect()):
            print("  Cannot connect to TWS — skipping fetch (will replay existing OHLCV)")
            return
        end_dt = datetime.now(tz=UTC)
        for instrument in contracts:
            try:
                qualified = asyncio.run(provider.qualify_instrument(instrument))
                if not qualified:
                    print(f"  {instrument.symbol}: qualify failed — skipping")
                    continue
                for tf, (fetch_days, use_continuous) in tf_config.items():
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

    if args.no_backfill:
        # Seed mode: wipe was already done above. Fetch a short window of named-contract
        # bars per TF (real prices, no back-adjustment), then replay through I1→I7.
        seed_config = {tf: (days, False) for tf, days in _TF_SEED_CONFIG.items()}
        print("\n[3/5] Seeding recent named-contract bars (no back-adjustment)...")
        for tf, days in _TF_SEED_CONFIG.items():
            print(f"  {tf}: {days}d")
        _fetch_ohlcv(seed_config)
    elif not args.keep_ohlcv:
        from production.scripts.historical_backfill import _TF_FETCH_CONFIG
        full_config = {
            tf: (
                args.days if tf == "1m" else fetch_days,
                False if (args.days if tf == "1m" else fetch_days) <= 14 else use_continuous,
            )
            for tf, (fetch_days, use_continuous) in _TF_FETCH_CONFIG.items()
        }
        print("\n[3/5] Fetching OHLCV from IBKR...")
        _fetch_ohlcv(full_config)
    else:
        print("\n[3/5] Skipping IBKR fetch (--keep-ohlcv)")

    # --- Stage 5: Replay pipeline ---
    register_all_plugins()
    if args.no_backfill:
        print("\n[4/5] Replaying I1→I6 (seed mode — intelligence_features only, no signals)...")
    else:
        print("\n[4/5] Replaying I1→I7 pipeline...")
    for contract in contracts:
        counts = replay_symbol(
            symbol=contract.symbol,
            db_conn=db_conn,
            timeframes=DEFAULT_TIMEFRAMES,
            skip_signals=args.no_backfill,
        )
        if args.no_backfill:
            for tf, n in counts.items():
                print(f"  {contract.symbol}/{tf}: {n:,} feature rows")
        else:
            for tf, n in counts.items():
                print(f"  {contract.symbol}/{tf}: {n:,} signals")

    # --- Stage 6: Verify ---
    print("\n[5/5] Verifying dataset...")
    ok, report = verify_dataset(db_conn, seed_mode=args.no_backfill)
    print(report)
    if not ok:
        print("\n⚠  Verification failed — check above for empty tables")

    db_conn.close()

    # --- Restart services ---
    _pause_for_services("start", _START_SERVICES, auto_confirm=args.yes)

    # --- Summary ---
    elapsed = time.time() - t_start
    m, s = divmod(int(elapsed), 60)
    print(f"\n{'='*50}")
    print(f"Pipeline Reset {'Complete ✓' if ok else 'Complete with warnings ⚠'}")
    print(f"Elapsed: {m}m {s}s")
    print()


if __name__ == "__main__":
    main()
