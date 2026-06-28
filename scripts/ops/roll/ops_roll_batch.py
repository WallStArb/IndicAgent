#!/usr/bin/env python3
"""roll_batch — nightly calendar-driven futures roll promotion.

Version: 1.0
Status: current
Last Updated: 2026-06-06

Replaces RollComputeAgent (24/7 streaming) and ContractMetadataWriterAgent
(Kafka consumer) with a single oneshot script that:

1. Seeds missing contracts into contract_metadata
2. Detects rolls via calendar (get_roll_window + derive_roll_chain)
3. Promotes front-month atomically in contract_metadata
4. Broadcasts ContractUpdateEvent for downstream cache invalidation
5. Logs volume validation data for historical analysis

Runs via systemd timer at 23:00 UTC (6pm ET). Idempotent — safe to rerun.

Usage:
    python scripts/ops/roll/ops_roll_batch.py           # normal run
    python scripts/ops/roll/ops_roll_batch.py --dry-run  # log only, no writes
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

# Project root on sys.path — same pattern as roll_backtest.py
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import asyncpg
import structlog
from opentelemetry import metrics as _otel_metrics

from src.config.contracts import (
    FUTURES_ROLL_CYCLES,
    MONTH_CODE_TO_NUM,
    derive_roll_chain,
    get_expiry_date,
    get_roll_window,
)
from src.config.settings import Settings, get_active_contracts
from src.core.database_manager import create_pool as create_db_pool
from src.core.kafka_utils import KafkaProducerClient
from src.core.models import AssetClass
from src.core.schemas.market_events import ContractUpdateEvent
from src.core.stream_keys import topic_contract_updates
from src.observability.metrics import JOB_COMPLETED_TOTAL, flush_and_shutdown_metrics

_logger = structlog.get_logger("roll_batch")

# ---------------------------------------------------------------------------
# OTel metrics
# ---------------------------------------------------------------------------

_meter = _otel_metrics.get_meter("indicagent")
_RUNS = _meter.create_counter("roll_batch_runs_total", description="Nightly batch runs")
_PROMOTIONS = _meter.create_counter(
    "roll_batch_promotions_total", description="Contract promotions"
)
_SEEDS = _meter.create_counter("roll_batch_seeds_total", description="New contracts seeded")
_ERRORS = _meter.create_counter("roll_batch_errors_total", description="Processing errors")

_ATTRS = {"component": "roll_batch"}


# ---------------------------------------------------------------------------
# Pure detection
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RollDecision:
    base_symbol: str
    old_contract: str
    new_contract: str
    roll_end: date


def detect_rolls(today: date) -> list[RollDecision]:
    """Pure function: return roll promotions due for today.

    For each symbol in FUTURES_ROLL_CYCLES, check if today >= roll_end.
    If so, derive the chain and return the promotion decision.
    Returns empty list when no rolls are due.
    """
    decisions: list[RollDecision] = []

    for base_symbol in FUTURES_ROLL_CYCLES:
        try:
            roll_window = get_roll_window(base_symbol, today)
        except ValueError:
            continue

        if roll_window is None:
            continue

        _roll_start, roll_end = roll_window

        if today < roll_end:
            continue

        try:
            chain = derive_roll_chain(base_symbol)
        except (ValueError, IndexError):
            _logger.warning("roll_batch.chain_derivation_failed", base_symbol=base_symbol)
            continue

        if not chain or len(chain) < 2:
            continue

        decisions.append(
            RollDecision(
                base_symbol=base_symbol,
                old_contract=chain[0]["symbol"],
                new_contract=chain[1]["symbol"],
                roll_end=roll_end,
            )
        )

    return decisions


def _parse_contract_expiry(symbol: str, base_symbol: str) -> date | None:
    """Decode the expiry date embedded in a futures symbol like 'NGM6' or 'ESM26'.

    Returns None if the suffix can't be parsed.
    """
    suffix = symbol[len(base_symbol) :]  # e.g. "M6" or "M26"
    if len(suffix) < 2:
        return None
    month_code = suffix[0]
    year_str = suffix[1:]
    month = MONTH_CODE_TO_NUM.get(month_code)
    if month is None or not year_str.isdigit():
        return None
    year_num = int(year_str)
    # Single digit: interpret as current decade (e.g. "6" → 2026)
    year = 2020 + year_num if year_num < 100 else year_num
    try:
        return get_expiry_date(base_symbol, month, year)
    except Exception:
        return None


async def detect_expired_front_months(conn: asyncpg.Connection, today: date) -> list[RollDecision]:
    """Rescue: find front-month contracts that passed expiry and were missed by detect_rolls.

    This handles the case where the system was down during a roll window, or where
    get_roll_window returns None because we're already past roll_end. Queries the DB
    for is_front_month=true contracts, computes each contract's expiry date, and
    promotes the next contract whenever today > expiry_date.
    """
    rows = await conn.fetch("""SELECT symbol, base_symbol, roll_to
           FROM contract_metadata
           WHERE is_front_month = true AND asset_class = 'futures'""")

    decisions: list[RollDecision] = []
    for row in rows:
        symbol = row["symbol"]
        base_symbol = row["base_symbol"]

        expiry_date = _parse_contract_expiry(symbol, base_symbol)
        if expiry_date is None:
            continue

        if today <= expiry_date:
            continue  # Not yet expired; normal detect_rolls handles it

        # Guard: verify the contract is actually dead before promoting.
        # get_expiry_date uses different formulas for different futures families and
        # may be inaccurate for some (e.g. GC/SI/HG expire at end of delivery month,
        # not 3 days before the 25th of the prior month). A contract with bars in
        # the last 26 hours is still trading regardless of what the formula says.
        recent_bar = await conn.fetchval(
            """SELECT 1 FROM market_data_ohlcv
               WHERE symbol = $1 AND timestamp > NOW() - INTERVAL '28 hours' LIMIT 1""",
            symbol,
        )
        if recent_bar:
            continue

        # Expired — find the next contract via roll_to column or chain derivation
        next_contract: str | None = row["roll_to"] or None
        if not next_contract:
            try:
                chain = derive_roll_chain(base_symbol)
                symbols = [e["symbol"] for e in chain]
                if symbol in symbols:
                    idx = symbols.index(symbol)
                    next_contract = symbols[idx + 1] if idx + 1 < len(symbols) else None
                else:
                    next_contract = symbols[0] if symbols else None
            except Exception:
                pass

        if not next_contract:
            _logger.warning(
                "roll_batch.rescue_no_next_contract",
                base=base_symbol,
                expired=symbol,
                expiry_date=str(expiry_date),
            )
            continue

        _logger.warning(
            "roll_batch.rescue_expired_front_month",
            base=base_symbol,
            expired=symbol,
            expiry_date=str(expiry_date),
            next_contract=next_contract,
            days_overdue=(today - expiry_date).days,
        )
        decisions.append(
            RollDecision(
                base_symbol=base_symbol,
                old_contract=symbol,
                new_contract=next_contract,
                roll_end=expiry_date,
            )
        )

    return decisions


# ---------------------------------------------------------------------------
# DB operations
# ---------------------------------------------------------------------------


async def seed_missing_contracts(conn: asyncpg.Connection, settings: Settings) -> int:
    """INSERT contracts from get_active_contracts() with ON CONFLICT DO NOTHING."""
    instruments = get_active_contracts(settings)
    futures = [i for i in instruments if i.asset_class == AssetClass.FUTURES]
    if not futures:
        return 0

    params: list = []
    value_clauses: list[str] = []
    for idx, instrument in enumerate(futures):
        base_idx = idx * 4
        value_clauses.append(
            f"(${base_idx + 1}, ${base_idx + 2}, ${base_idx + 3}, ${base_idx + 4}, true)"
        )
        params.extend([instrument.symbol, instrument.base, AssetClass.FUTURES, instrument.exchange])

    result = await conn.fetch(
        f"""INSERT INTO contract_metadata
                (symbol, base_symbol, asset_class, exchange, is_front_month)
            VALUES {', '.join(value_clauses)}
            ON CONFLICT (symbol) DO NOTHING
            RETURNING symbol""",
        *params,
    )
    count = len(result)
    if count:
        _SEEDS.add(count, _ATTRS)
        _logger.info("roll_batch.seeded", count=count)
    return count


async def _volume_validation(
    conn: asyncpg.Connection, old_contract: str, new_contract: str
) -> tuple[float, float]:
    """Query last 3 days of volume for both contracts. Returns (old_vol, new_vol)."""
    since = datetime.now(UTC) - timedelta(days=3)
    rows = await conn.fetch(
        """SELECT symbol, SUM(volume)::float as total_vol
           FROM market_data_ohlcv
           WHERE symbol = ANY($1) AND timestamp >= $2
           GROUP BY symbol""",
        [old_contract, new_contract],
        since,
    )
    by_symbol = {r["symbol"]: r["total_vol"] or 0.0 for r in rows}
    return by_symbol.get(old_contract, 0.0), by_symbol.get(new_contract, 0.0)


async def execute_promotion(
    conn: asyncpg.Connection,
    decision: RollDecision,
    dry_run: bool = False,
) -> bool:
    """Atomic front-month promotion. Returns True if promoted (or would have been)."""
    # Check if already promoted
    current = await conn.fetchrow(
        "SELECT is_front_month FROM contract_metadata WHERE symbol = $1",
        decision.new_contract,
    )
    if current and current["is_front_month"]:
        _logger.debug(
            "roll_batch.already_promoted",
            base=decision.base_symbol,
            contract=decision.new_contract,
        )
        return False

    # Volume validation (informational only)
    try:
        old_vol, new_vol = await _volume_validation(
            conn, decision.old_contract, decision.new_contract
        )
        vol_ratio = new_vol / old_vol if old_vol > 0 else float("inf")
        _logger.info(
            "roll_batch.volume_validation",
            base=decision.base_symbol,
            old_contract=decision.old_contract,
            new_contract=decision.new_contract,
            old_vol=old_vol,
            new_vol=new_vol,
            ratio=round(vol_ratio, 2),
        )
    except Exception:
        _logger.debug("roll_batch.volume_validation_skipped", base=decision.base_symbol)

    if dry_run:
        _logger.info(
            "roll_batch.dry_run_promotion",
            base=decision.base_symbol,
            old=decision.old_contract,
            new=decision.new_contract,
        )
        return True

    async with conn.transaction():
        old_row = await conn.fetchrow(
            "SELECT base_symbol, exchange FROM contract_metadata WHERE symbol = $1 FOR UPDATE",
            decision.old_contract,
        )
        if old_row is None:
            _logger.warning(
                "roll_batch.old_contract_not_found",
                contract=decision.old_contract,
                base=decision.base_symbol,
            )
            return False

        exchange = old_row["exchange"]

        await conn.execute(
            """UPDATE contract_metadata
               SET is_front_month = false, updated_at = NOW()
               WHERE symbol = $1""",
            decision.old_contract,
        )
        await conn.execute(
            """INSERT INTO contract_metadata
                   (symbol, base_symbol, asset_class, exchange, is_front_month,
                    roll_from, roll_detected_at, updated_at)
               VALUES ($1, $2, $3, $4, true, $5, $6, NOW())
               ON CONFLICT (symbol) DO UPDATE SET
                   is_front_month = true,
                   roll_from = EXCLUDED.roll_from,
                   roll_detected_at = EXCLUDED.roll_detected_at,
                   updated_at = NOW()""",
            decision.new_contract,
            decision.base_symbol,
            AssetClass.FUTURES,
            exchange,
            decision.old_contract,
            datetime.now(UTC),
        )
        await conn.execute(
            """INSERT INTO roll_events
                   (detected_at, base_symbol, old_contract, new_contract,
                    detection_method, is_authoritative)
               VALUES ($1, $2, $3, $4, 'calendar', true)""",
            datetime.now(UTC),
            decision.base_symbol,
            decision.old_contract,
            decision.new_contract,
        )

    _PROMOTIONS.add(1, _ATTRS)
    _logger.info(
        "roll_batch.promoted",
        base=decision.base_symbol,
        old=decision.old_contract,
        new=decision.new_contract,
    )
    return True


# ---------------------------------------------------------------------------
# Kafka broadcast
# ---------------------------------------------------------------------------


async def broadcast_update(decision: RollDecision, settings: Settings) -> None:
    """Publish ContractUpdateEvent so bar_writer and bar_auditor invalidate caches."""
    producer = KafkaProducerClient(bootstrap_servers=settings.kafka_bootstrap_servers)
    try:
        await producer.start()
        event = ContractUpdateEvent(
            base_symbol=decision.base_symbol,
            old_contract=decision.old_contract,
            new_contract=decision.new_contract,
            promoted_at=datetime.now(UTC),
        )
        await producer.publish(
            topic_contract_updates(settings.env_name),
            event.model_dump(mode="json"),
            key=decision.base_symbol,
        )
        _logger.info(
            "roll_batch.broadcast_sent",
            base=decision.base_symbol,
            old=decision.old_contract,
            new=decision.new_contract,
        )
    finally:
        await producer.stop()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


async def run(dry_run: bool = False) -> None:
    settings = Settings()
    today = datetime.now(UTC).date()
    _RUNS.add(1, _ATTRS)
    _logger.info("roll_batch.run", today=str(today), dry_run=dry_run)

    pool = await create_db_pool(settings.database_url, min_size=1, max_size=2)

    try:
        async with pool.acquire() as conn:
            seeded = await seed_missing_contracts(conn, settings)

            calendar_decisions = detect_rolls(today)
            rescue_decisions = await detect_expired_front_months(conn, today)

            # Merge: rescue takes precedence, calendar fills in the rest.
            # Deduplicate by base_symbol so a symbol isn't promoted twice.
            seen: set[str] = set()
            decisions: list[RollDecision] = []
            for d in rescue_decisions + calendar_decisions:
                if d.base_symbol not in seen:
                    seen.add(d.base_symbol)
                    decisions.append(d)

            _logger.info(
                "roll_batch.decisions",
                count=len(decisions),
                rescue=len(rescue_decisions),
                calendar=len(calendar_decisions),
            )

            for decision in decisions:
                promoted = await execute_promotion(conn, decision, dry_run=dry_run)
                if promoted and not dry_run:
                    await broadcast_update(decision, settings)
        JOB_COMPLETED_TOTAL.add(1, {"job": "roll-batch", "status": "success"})
    except Exception as exc:
        _ERRORS.add(1, _ATTRS)
        _logger.error("roll_batch.error", error=str(exc))
        JOB_COMPLETED_TOTAL.add(1, {"job": "roll-batch", "status": "failure"})
        raise
    finally:
        await pool.close()

    _logger.info("roll_batch.complete", decisions=len(decisions), seeded=seeded)


def main() -> None:
    parser = argparse.ArgumentParser(description="Nightly futures roll promotion batch")
    parser.add_argument(
        "--dry-run", action="store_true", help="Log decisions, skip DB writes and Kafka"
    )
    args = parser.parse_args()
    try:
        asyncio.run(run(dry_run=args.dry_run))
    finally:
        flush_and_shutdown_metrics()


if __name__ == "__main__":
    main()
