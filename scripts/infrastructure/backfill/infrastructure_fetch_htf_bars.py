#!/usr/bin/env python3
"""One-shot HTF bar backfill: replay 1m bars from market_data_ohlcv through
BarAccumulator and publish completed HTF bars to topic_market_bars_htf.

Version: 1.0
Status: current
Last Updated: 2026-06-12


Usage:
    .venv/bin/python scripts/infrastructure/backfill/infrastructure_fetch_htf_bars.py --hours 24
    .venv/bin/python scripts/infrastructure/backfill/infrastructure_fetch_htf_bars.py --since 2026-04-02 --until 2026-04-09

The intelligence pipeline must be running — it will consume and persist the replayed bars.
Run while the bar_aggregator service is stopped to avoid duplicate messages.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

import asyncpg

from src.config.settings import Settings, get_active_contracts
from src.core.bar_accumulator import BarAccumulator
from src.core.kafka_utils import KafkaProducerClient
from src.core.schemas.bar_message import BarMessage
from src.core.stream_keys import message_key, topic_market_bars_htf


def _row_to_bar_message(row: dict) -> BarMessage:
    """Convert a market_data_ohlcv row dict to a BarMessage."""
    ts = row.get("ts") or row.get("timestamp")
    if isinstance(ts, str):
        ts = datetime.fromisoformat(ts)
    if ts is not None and ts.tzinfo is None:
        ts = ts.replace(tzinfo=UTC)
    tf = row.get("tf") or row.get("timeframe", "1m")
    return BarMessage(
        symbol=row["symbol"],
        tf=tf,
        ts=ts,
        open=float(row["open"]),
        high=float(row["high"]),
        low=float(row["low"]),
        close=float(row["close"]),
        volume=float(row.get("volume", 0)),
        session_type=row.get("session_type", "rth"),
        source="ibkr_named",
    )


def _replay_bars(
    accumulator: BarAccumulator,
    rows: list[dict],
    tf_targets: tuple[str, ...] = ("5m", "15m", "1h", "4h", "1d"),
) -> list[BarMessage]:
    """Feed 1m bar rows through BarAccumulator; return completed HTF bars."""
    htf_bars: list[BarMessage] = []
    for row in rows:
        bar = _row_to_bar_message(row)
        completed = accumulator.update(bar)
        for c in completed:
            if c.tf in tf_targets:
                htf_bars.append(c)
    return htf_bars


async def _publish_htf_bars(
    producer: KafkaProducerClient,
    bars: list[BarMessage],
    topic: str,
) -> None:
    """Publish HTF bar messages to Kafka topic."""
    for bar in bars:
        key = message_key(bar.symbol, bar.tf)
        payload = bar.model_dump(mode="json")
        await producer.publish(topic, payload, key=key)


async def _fetch_1m_bars(
    conn: asyncpg.Connection,
    symbols: list[str],
    since: datetime,
    until: datetime,
) -> list[dict]:
    """Fetch 1m bars from market_data_ohlcv in time-ascending order."""
    rows = await conn.fetch(
        """
        SELECT symbol,
               timestamp AS ts,
               'rth'     AS session_type,
               open, high, low, close, volume
        FROM market_data_ohlcv
        WHERE symbol = ANY($1)
          AND timeframe = '1m'
          AND timestamp >= $2
          AND timestamp <  $3
        ORDER BY symbol, timestamp ASC
        """,
        symbols,
        since,
        until,
    )
    return [dict(r) for r in rows]


async def _amain(args: argparse.Namespace) -> None:
    settings = Settings()
    contracts = get_active_contracts(settings)
    symbols = [c.symbol for c in contracts]

    until = datetime.now(UTC)
    if args.hours:
        since = until - timedelta(hours=args.hours)
    else:
        since = datetime.fromisoformat(args.since).replace(tzinfo=UTC)
        until = datetime.fromisoformat(args.until).replace(tzinfo=UTC)

    print(f"Backfilling HTF bars for {symbols} from {since} to {until}")

    conn = await asyncpg.connect(settings.database_url)
    try:
        rows = await _fetch_1m_bars(conn, symbols, since, until)
    finally:
        await conn.close()
    print(f"  Fetched {len(rows)} 1m bars from market_data_ohlcv")

    # Group by symbol and replay each symbol independently
    by_symbol: dict[str, list[dict]] = {}
    for row in rows:
        by_symbol.setdefault(row["symbol"], []).append(row)

    htf_topic = topic_market_bars_htf(settings.env_name)
    producer = KafkaProducerClient(bootstrap_servers=settings.kafka_bootstrap_servers)
    await producer.start()
    try:
        total_published = 0
        for symbol, symbol_rows in by_symbol.items():
            acc = BarAccumulator()
            htf_bars = _replay_bars(acc, symbol_rows)
            await _publish_htf_bars(producer, htf_bars, topic=htf_topic)
            print(f"  {symbol}: {len(symbol_rows)} 1m bars -> {len(htf_bars)} HTF bars published")
            total_published += len(htf_bars)
    finally:
        await producer.stop()
    print(f"Done. Published {total_published} HTF bars to {htf_topic}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Backfill HTF bars from 1m OHLCV data")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--hours", type=int, help="Look back N hours from now")
    group.add_argument("--since", type=str, help="ISO date start (use with --until)")
    parser.add_argument("--until", type=str, default=None, help="ISO date end (default: now)")
    args = parser.parse_args()

    if args.hours and args.until:
        parser.error("--until cannot be used with --hours; use --since/--until instead")

    if args.since and not args.until:
        args.until = datetime.now(UTC).isoformat()

    asyncio.run(_amain(args))


if __name__ == "__main__":
    main()
