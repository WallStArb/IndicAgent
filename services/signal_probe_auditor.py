"""SignalProbeAuditor — daily oneshot that simulates outcomes for unselected NEEDS_REFACTOR signals.

Timer-triggered: indicagent-signal-probe-auditor.timer (daily at 03:30).
One-shot: samples ~1% of unselected expired/suppressed signals from NEEDS_REFACTOR setups,
simulates activation from market_data_ohlcv forward bars, writes pnl_r/mae/mfe to
signal_probe_results, emits D-06 job_completed_total.

Phase 117.5 uses the accumulated signal_probe_results rows to derive empirical thresholds
for the 21 NEEDS_REFACTOR setups (requires MIN_SAMPLE_N=100 activations per setup).

Phase 130: stop_loss now sourced from trade_frames.stop_price via LEFT JOIN trade_frames.
signal_ledger references replaced with signal_events + trade_frames queries.
The dropped join on the now-absent outcomes table is not referenced here.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime
from typing import Any

import _path_bootstrap  # noqa: F401 — project root on sys.path
import asyncpg
import structlog

from src.config.settings import Settings
from src.core.database_manager import create_pool as create_db_pool
from src.observability.metrics import (
    JOB_COMPLETED_TOTAL,
    SIGNAL_PROBE_ACTIVATIONS_TOTAL,
    flush_and_shutdown_metrics,
)

logger = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SAMPLE_RATE: float = 0.01  # ~1% sample per setup per run
MIN_SAMPLE_N: int = 100  # Phase 117.5 gate: not enforced here, documented as target
MAX_BARS_FORWARD: int = 20  # bars to look forward for simulated activation

# D-06 contract: label MUST match the systemd unit suffix exactly (kebab-case).
_JOB_LABEL: str = "signal-probe-auditor"

# ---------------------------------------------------------------------------
# NEEDS_REFACTOR setups — from RCA Appendix A (2026-06-07)
# ---------------------------------------------------------------------------

NEEDS_REFACTOR_SETUPS: frozenset[str] = frozenset(
    {
        "trad_OFIContinuation",
        "trad_PatternCompletion",
        "trad_AnchoredVWAPReversion",
        "trad_GapAnalysisSetup",
        "trad_CVDDivergence",
        "trad_DivergenceStack",
        "trad_CandlestickPatternSetup",
        "trad_FailedBreakout",
        "trad_OFIDivergence",
        "trad_LiquidityHunt",
        "trad_CVDSpike",
        "trad_OFISpike",
        "trad_DualDivergence",
        "trad_VWAPReclaim",
        "trad_DeltaExhaustion",
        "trad_SessionExtremesSetup",
        "trad_LVNBreakout",
        "trad_ORB15",
        "trad_ORB30",
        "trad_SecondLegContinuation",
        "trad_VCP",
    }
)

# ---------------------------------------------------------------------------
# Pure simulation logic (tested directly without DB)
# ---------------------------------------------------------------------------


def simulate_outcome(
    sig: dict[str, Any],
    forward_bars: list[dict[str, Any]],
) -> dict[str, Any]:
    """Simulate activation and forward outcome from OHLCV bars.

    Args:
        sig: Signal row dict with keys: signal_id, direction, entry_zone_low,
             entry_zone_high, stop_loss (may be None).
        forward_bars: List of OHLCV bar dicts (timestamp, open, high, low, close)
                      ordered ascending by timestamp, up to MAX_BARS_FORWARD bars.

    Returns:
        Dict with simulation result fields for INSERT into signal_probe_results.
    """
    direction: int = sig["direction"]
    entry_zone_high: float | None = sig.get("entry_zone_high")
    entry_zone_low: float | None = sig.get("entry_zone_low")
    stop_loss: float | None = sig.get("stop_loss")

    result: dict[str, Any] = {
        "sim_activated": False,
        "sim_entry_price": None,
        "sim_exit_price": None,
        "sim_pnl_r": None,
        "sim_mae": None,
        "sim_mfe": None,
        "sim_bars_in_trade": None,
        "sim_outcome": "never_activated",
        "bars_forward": len(forward_bars),
    }

    if not forward_bars:
        return result

    # Determine entry price: long uses entry_zone_high, short uses entry_zone_low.
    if direction == 1:
        entry_trigger_price = entry_zone_high
    else:
        entry_trigger_price = entry_zone_low

    if entry_trigger_price is None:
        return result

    # Scan for activation.
    activated_bar_idx: int | None = None
    sim_entry_price: float | None = None

    for idx, bar in enumerate(forward_bars):
        bar_low = float(bar["low"])
        bar_high = float(bar["high"])

        if direction == 1 and bar_low <= entry_trigger_price:
            # Long activates when bar dips to or below entry_zone_high.
            activated_bar_idx = idx
            sim_entry_price = entry_trigger_price
            break
        elif direction == -1 and bar_high >= entry_trigger_price:
            # Short activates when bar rises to or above entry_zone_low.
            activated_bar_idx = idx
            sim_entry_price = entry_trigger_price
            break

    if activated_bar_idx is None or sim_entry_price is None:
        result["sim_outcome"] = "never_activated"
        return result

    # Activated — simulate forward from activation bar.
    result["sim_activated"] = True
    result["sim_entry_price"] = sim_entry_price

    post_activation_bars = forward_bars[activated_bar_idx + 1 :]
    running_mfe: float = 0.0  # maximum favorable excursion in price
    running_mae: float = 0.0  # maximum adverse excursion in price
    sim_exit_price: float = float(forward_bars[-1]["close"])  # default: last bar close
    bars_in_trade = len(post_activation_bars)

    for bar in post_activation_bars:
        bar_high = float(bar["high"])
        bar_low = float(bar["low"])

        if direction == 1:
            favorable_excursion = bar_high - sim_entry_price
            adverse_excursion = sim_entry_price - bar_low
        else:
            favorable_excursion = sim_entry_price - bar_low
            adverse_excursion = bar_high - sim_entry_price

        running_mfe = max(running_mfe, favorable_excursion)
        running_mae = max(running_mae, adverse_excursion)
        sim_exit_price = float(bar["close"])

    # Convert to R units using stop distance (if available).
    stop_distance: float | None = None
    if stop_loss is not None:
        stop_distance = abs(sim_entry_price - float(stop_loss))

    if stop_distance and stop_distance > 0:
        pnl_price = (sim_exit_price - sim_entry_price) * direction
        result["sim_pnl_r"] = pnl_price / stop_distance
        result["sim_mae"] = running_mae / stop_distance
        result["sim_mfe"] = running_mfe / stop_distance
    else:
        # No stop_loss — store raw price movement (not in R).
        result["sim_pnl_r"] = (sim_exit_price - sim_entry_price) * direction
        result["sim_mae"] = running_mae
        result["sim_mfe"] = running_mfe

    result["sim_exit_price"] = sim_exit_price
    result["sim_bars_in_trade"] = bars_in_trade
    result["sim_outcome"] = "window_end"

    return result


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------


async def _select_unselected_sample(
    conn: asyncpg.Connection,
) -> list[asyncpg.Record]:
    """Select ~1% sample of unselected NEEDS_REFACTOR signals not yet probed.

    Phase 130: stop_loss sourced from trade_frames.stop_price via LEFT JOIN trade_frames.
    entry_zone_low/entry_zone_high sourced from trade_frames.frame_details JSONB.
    signal_ledger replaced with signal_events + trade_frames.
    """
    setup_list = list(NEEDS_REFACTOR_SETUPS)
    rows = await conn.fetch(
        """
        SELECT
            se.signal_id,
            se.symbol,
            se.tf                                              AS timeframe,
            se.setup_plugin,
            CASE WHEN se.direction = 'long' THEN 1 ELSE -1 END AS direction,
            (tf.frame_details->>'entry_zone_low')::float8     AS entry_zone_low,
            (tf.frame_details->>'entry_zone_high')::float8    AS entry_zone_high,
            se.ts                                              AS signal_timestamp,
            tf.stop_price                                      AS stop_loss
        FROM signal_events se
        LEFT JOIN trade_frames tf
            ON tf.signal_id = se.signal_id AND tf.signal_ts = se.ts
        WHERE tf.was_selected = false
          AND se.is_shadow = false
          AND (tf.frame_details->>'activated_at') IS NULL
          AND se.status IN ('expired', 'regime_suppressed')
          AND se.setup_plugin = ANY($1)
          AND se.ts >= now() - interval '2 days'
          AND (tf.frame_details->>'entry_zone_low') IS NOT NULL
          AND (tf.frame_details->>'entry_zone_high') IS NOT NULL
          AND NOT EXISTS (
              SELECT 1 FROM signal_probe_results spr
              WHERE spr.signal_id = se.signal_id
          )
          AND random() < $2
        LIMIT 500
        """,
        setup_list,
        SAMPLE_RATE,
    )
    return list(rows)


async def _fetch_forward_bars(
    conn: asyncpg.Connection,
    symbol: str,
    timeframe: str,
    signal_timestamp: datetime,
) -> list[dict[str, Any]]:
    """Fetch up to MAX_BARS_FORWARD OHLCV bars after the signal timestamp."""
    rows = await conn.fetch(
        """
        SELECT timestamp, open, high, low, close
        FROM market_data_ohlcv
        WHERE symbol = $1
          AND timeframe = $2
          AND timestamp > $3
        ORDER BY timestamp ASC
        LIMIT $4
        """,
        symbol,
        timeframe,
        signal_timestamp,
        MAX_BARS_FORWARD,
    )
    return [dict(r) for r in rows]


async def _count_competing_signals(
    conn: asyncpg.Connection,
    signal_id: uuid.UUID,
    symbol: str,
    timeframe: str,
    signal_timestamp: datetime,
) -> int:
    """Count was_selected=true signals at the same bar, excluding this signal.

    Phase 130: was_selected lives in trade_frames; join signal_events + trade_frames.
    """
    row = await conn.fetchrow(
        """
        SELECT COUNT(*) AS cnt
        FROM signal_events se
        JOIN trade_frames tf ON tf.signal_id = se.signal_id AND tf.signal_ts = se.ts
        WHERE tf.was_selected = true
          AND se.symbol = $1
          AND se.tf = $2
          AND se.ts = $3
          AND se.signal_id != $4
        """,
        symbol,
        timeframe,
        signal_timestamp,
        signal_id,
    )
    return int(row["cnt"]) if row else 0


# ---------------------------------------------------------------------------
# Core probe logic
# ---------------------------------------------------------------------------


async def _run_probe(pool: asyncpg.Pool) -> None:
    """Acquire sample, simulate outcomes, batch-insert probe rows."""
    async with pool.acquire() as conn:
        sample_rows = await _select_unselected_sample(conn)

    if not sample_rows:
        logger.info("signal_probe.no_sample", count=0)
        return

    logger.info("signal_probe.sample_selected", count=len(sample_rows))

    probe_records: list[tuple[Any, ...]] = []
    counts_per_setup: dict[str, int] = {}

    for row in sample_rows:
        sig = dict(row)
        signal_id = sig["signal_id"]
        symbol = sig["symbol"]
        timeframe = sig["timeframe"]
        setup_plugin = sig["setup_plugin"]
        signal_timestamp = sig["signal_timestamp"]

        async with pool.acquire() as conn:
            forward_bars = await _fetch_forward_bars(conn, symbol, timeframe, signal_timestamp)
            competing = await _count_competing_signals(
                conn, signal_id, symbol, timeframe, signal_timestamp
            )
        sim = simulate_outcome(sig, forward_bars)

        now = datetime.now(UTC)
        probe_records.append(
            (
                signal_id,
                now,
                symbol,
                timeframe,
                setup_plugin,
                sig["direction"],
                sim["sim_activated"],
                sim["sim_entry_price"],
                sim["sim_exit_price"],
                sim["sim_pnl_r"],
                sim["sim_mae"],
                sim["sim_mfe"],
                sim["sim_bars_in_trade"],
                sim["sim_outcome"],
                sim["bars_forward"],
                competing,
            )
        )

        if sim["sim_activated"]:
            counts_per_setup[setup_plugin] = counts_per_setup.get(setup_plugin, 0) + 1

    # Batch insert — ON CONFLICT DO NOTHING for idempotency (unique index on signal_id).
    async with pool.acquire() as conn:
        await conn.executemany(
            """
            INSERT INTO signal_probe_results (
                signal_id, probed_at, symbol, timeframe, setup_plugin, direction,
                sim_activated, sim_entry_price, sim_exit_price, sim_pnl_r,
                sim_mae, sim_mfe, sim_bars_in_trade, sim_outcome,
                bars_forward, competing_signals_count
            ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15, $16)
            ON CONFLICT (signal_id) DO NOTHING
            """,
            probe_records,
        )

    # Emit activation counters.
    for setup_plugin, activation_count in counts_per_setup.items():
        SIGNAL_PROBE_ACTIVATIONS_TOTAL.add(activation_count, {"setup_plugin": setup_plugin})

    logger.info(
        "signal_probe.summary",
        total_sampled=len(sample_rows),
        total_inserted=len(probe_records),
        activations_by_setup=counts_per_setup,
    )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


async def _amain() -> None:
    settings = Settings()
    pool = await create_db_pool(settings.database_url, min_size=2, max_size=5)
    try:
        await _run_probe(pool)
    finally:
        await pool.close()


def main() -> None:
    """Run the signal probe auditor once and emit a completion counter before exit."""
    try:
        asyncio.run(_amain())
        JOB_COMPLETED_TOTAL.add(1, {"job": _JOB_LABEL, "status": "success"})
    except Exception as error:
        JOB_COMPLETED_TOTAL.add(1, {"job": _JOB_LABEL, "status": "failure"})
        raise error
    finally:
        flush_and_shutdown_metrics()


if __name__ == "__main__":
    main()
