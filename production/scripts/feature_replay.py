"""I7-only replay from intelligence_features.

Reads stored JSONB tier columns, reconstructs IntelligenceEvent, runs specified I7 plugins,
inserts into signal_events + trade_frames (3-table schema). Bypasses all I1-I6 compute.
Depends on migration 125 column names (i1/i2/i3/i4/i5/smc/cross_timeframe_context) and
plan 06 deterministic IDs.

Phase 130: migrated write path to signal_events + trade_frames (3-table schema).
G0 grouping: one signal_events row + one trade_frames row (at_close) per signal.
Direction converted from int (1/-1) to text ('long'/'short').
frame_id = uuid5(NAMESPACE_DNS, f"{signal_id}:at_close") — deterministic across re-runs.

Usage examples:

    # Replay all I7 plugins for ESM6 since 2026-06-01
    python production/scripts/feature_replay.py --symbols ESM6 --since 2026-06-01

    # Dry-run: reconstruct + evaluate but do not write to signal_events
    python production/scripts/feature_replay.py --dry-run --symbols ESM6 --since 2026-06-10 --workers 1

    # Replay only shadow validation setups (fast path for Phase 121 re-runs)
    python production/scripts/feature_replay.py --shadow-setups --symbols ESM6 --since 2026-06-01 --workers 4

    # Replay specific plugins
    python production/scripts/feature_replay.py --plugins trad_OFIContinuation,trad_DivergenceStack

Idempotency: ON CONFLICT (signal_id, ts) DO NOTHING on signal_events; ON CONFLICT (frame_id) DO NOTHING
on trade_frames. Running twice produces identical signal_ids and frame_ids (deterministic).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import asyncpg
import structlog

# Set up sys.path BEFORE importing from src
_project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(_project_root))

from src.config.settings import Settings, get_active_contracts
from src.core.database_manager import create_pool
from src.core.service_utils import TF_SECONDS, parse_iso_ts, setup_service_logging
from src.intelligence.pipeline.signal_processor import annotate_signal_with_context
from src.intelligence.plugins import registry
from src.intelligence.plugins.mixins import incremental_compute
from src.intelligence.register_plugins import TIER_I7, register_all_plugins
from src.intelligence.schemas import (
    FEATURE_SCHEMA_VERSION,
    I1Indicators,
    I2Events,
    I3Structure,
    I4Context,
    I5Patterns,
    I6Confluence,
    IntelligenceEvent,
    OHLCVBar,
    SMCContext,
)
from src.intelligence.trading.aggregator import aggregate
from src.intelligence.trading.signal_schema import SIGNAL_SCHEMA_VERSION, make_signal_id
from src.persistence.repository.signal_events_repository import LedgerEntry, SignalStatus

logger = structlog.get_logger(__name__)

# uuid5 namespace for deterministic frame_id — matches run_historical_pipeline.py
_FRAME_ID_NS = uuid.NAMESPACE_DNS


def _make_frame_id(signal_id: str, entry_type: str = "at_close") -> str:
    """Deterministic frame_id — same signal_id + entry_type always produces same UUID."""
    return str(uuid.uuid5(_FRAME_ID_NS, f"{signal_id}:{entry_type}"))


def _direction_text(direction_int: int) -> str:
    """Convert direction integer (1/-1) to text ('long'/'short') for signal_events."""
    return "long" if direction_int == 1 else "short"


# ---------------------------------------------------------------------------
# SQL constants
# ---------------------------------------------------------------------------

_SELECT_FEATURES_SQL = """
SELECT ts, symbol, tf, bar, technical_indicators, composite_events, regime_features,
       confluence_scores, pattern_detections, smc, cross_timeframe_context, market_context
FROM intelligence_features
WHERE symbol = $1 AND tf = $2
  AND ($3::timestamptz IS NULL OR ts >= $3)
ORDER BY ts ASC
"""

# G0 grouping: one signal_events row + one trade_frames row (at_close) per signal.
# ON CONFLICT DO NOTHING — idempotent across re-runs via deterministic signal_id and frame_id.
_INSERT_SIGNAL_EVENTS_SQL = """
INSERT INTO signal_events (
    signal_id, ts, symbol, tf, setup_plugin, direction,
    raw_confidence, calibrated_confidence, cis_score, weights_version,
    factor_scores, context_features,
    ctf_score, ctf_confirmed, zone_friction_score,
    hmm_regime_at_fire, plugin_regime_type, garch_sigma_at_fire,
    is_shadow, is_backfill, status, signal_schema_version,
    ttl_bars, expires_at, signal_computed_at, feature_ts
) VALUES (
    $1::uuid, $2, $3, $4, $5, $6,
    $7, $8, $9, $10,
    $11::jsonb, $12::jsonb,
    $13, $14, $15,
    $16, $17, $18,
    $19, $20, $21, $22,
    $23, $24, $25, $26
)
ON CONFLICT (signal_id, ts) DO NOTHING
"""

_INSERT_TRADE_FRAMES_SQL = """
INSERT INTO trade_frames (
    frame_id, signal_id, signal_ts, entry_type, direction,
    entry_price, stop_price, target_price, r_multiple,
    ttl_bars, expires_at, counterfactual_pnl_r, was_selected, frame_details
) VALUES (
    $1::uuid, $2::uuid, $3, $4, $5,
    $6, $7, $8, $9,
    $10, $11, NULL, $12, $13::jsonb
)
ON CONFLICT (frame_id) DO NOTHING
"""


# ---------------------------------------------------------------------------
# Event reconstruction
# ---------------------------------------------------------------------------


def _reconstruct_intelligence_event(row: asyncpg.Record) -> IntelligenceEvent | None:
    """Reconstruct an IntelligenceEvent from an intelligence_features row.

    JSONB columns are already dicts when fetched via asyncpg (no json.loads needed).
    Returns None on any ValidationError or Exception — logs warning and skips row.
    """
    try:
        bar_data = row["bar"] or {}
        return IntelligenceEvent(
            ts=row["ts"],
            symbol=row["symbol"],
            tf=row["tf"],
            source="backfill",
            bar=OHLCVBar(
                o=float(bar_data.get("o", 0.0)),
                h=float(bar_data.get("h", 0.0)),
                l=float(bar_data.get("l", 0.0)),
                c=float(bar_data.get("c", 0.0)),
                v=int(bar_data.get("v", 0)),
            ),
            i1=I1Indicators(**(row["technical_indicators"] or {})),
            i2=I2Events(**(row["composite_events"] or {})),
            i3=I3Structure(**(row["regime_features"] or {})),
            i4=I4Context(**(row["confluence_scores"] or {})),
            i5=I5Patterns(**(row["pattern_detections"] or {})),
            smc=SMCContext(**(row["smc"] or {})),
            i6=I6Confluence(**(row["cross_timeframe_context"] or {})),
        )
    except Exception as error:
        logger.warning(
            "feature_replay: failed to reconstruct IntelligenceEvent",
            symbol=row["symbol"] if row else "unknown",
            tf=row["tf"] if row else "unknown",
            ts=str(row["ts"]) if row else "unknown",
            error=str(error),
        )
        return None


# ---------------------------------------------------------------------------
# Per (symbol, tf) replay loop
# ---------------------------------------------------------------------------


async def _replay_symbol_tf(
    pool: asyncpg.Pool,
    symbol: str,
    tf: str,
    since: datetime | None,
    plugins: list[str],
    dry_run: bool,
) -> int:
    """Fetch intelligence_features rows, run I7 plugins, insert signal_events + trade_frames.

    Returns count of signals inserted (or that would be inserted in dry-run mode).

    bar_history deque not provided — plugins requiring multi-bar state (e.g. HMM)
    will use empty state; re-run in full pipeline mode for state-dependent plugins.
    """
    async with pool.acquire() as conn:
        rows = await conn.fetch(_SELECT_FEATURES_SQL, symbol, tf, since)

    if not rows:
        logger.debug("feature_replay: no rows found", symbol=symbol, tf=tf, since=str(since))
        return 0

    tf_secs = TF_SECONDS.get(tf, 60)
    signal_count = 0
    # Per-plugin state dict for this (symbol, tf) — accumulates across bars
    # so onset guards and consecutive-state counters carry forward correctly.
    plugin_states: dict[str, dict] = {name: {} for name in plugins}
    # Resolve plugin instances once — plugins list is fixed for the whole (symbol, tf) run.
    resolved_plugins = {name: registry.get_pattern(name) for name in plugins}

    for row in rows:
        event = _reconstruct_intelligence_event(row)
        if event is None:
            continue

        bar_data = row["bar"] or {}
        i1_data = row["technical_indicators"] or {}
        i2_data = row["composite_events"] or {}
        i3_data = row["regime_features"] or {}
        i4_data = row["confluence_scores"] or {}
        i5_data = row["pattern_detections"] or {}
        smc_data = row["smc"] or {}
        ctf_data = row["cross_timeframe_context"] or {}
        mkt_data = row["market_context"] or {}

        # Build merged flat features dict (all tier dicts merged so each plugin finds
        # its fields regardless of which tier key it reads from).
        flat_features: dict[str, Any] = {}
        for tier in (i1_data, i2_data, i3_data, i4_data, i5_data, smc_data, ctf_data, mkt_data):
            if tier:
                flat_features.update(tier)

        # frames dict structure mirrors the pattern in run_historical_pipeline.py:
        # each tier key holds the full merged dict so plugins find features via any key.
        frames: dict[str, Any] = {
            "features": flat_features,
            "symbol": symbol,
            "tf": tf,
            "__timeframe__": tf,
            "timeframe": tf,
            "i1": flat_features,
            "i2": flat_features,
            "i3": flat_features,
            "i4": flat_features,
            "i5": flat_features,
            "smc": flat_features,
            "i6": flat_features,
        }

        raw_signals: list[dict] = []
        for name in plugins:
            try:
                plugin = resolved_plugins[name]
                result, plugin_states[name] = incremental_compute(
                    plugin, frames, plugin_states[name]
                )
                if result is not None:
                    if result.get("direction", 0) != 0:
                        result["setup_plugin"] = name
                        raw_signals.append(result)
            except Exception as error:
                logger.warning(
                    "feature_replay: plugin error",
                    plugin=name,
                    symbol=symbol,
                    tf=tf,
                    error=str(error),
                )

        if not raw_signals:
            continue

        for sig in raw_signals:
            annotate_signal_with_context(sig, flat_features)

        trend_regime = float(flat_features.get("trend_regime", 0.0))
        agg_result = aggregate(
            raw_signals,
            trend_regime=trend_regime,
            features=flat_features,
            calibration_curves=None,
            perf_weights=None,
        )

        if not agg_result.all_ranked:
            continue

        ts = row["ts"]
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=UTC)

        garch_sigma = flat_features.get("garch_sigma")
        hmm_regime = flat_features.get("hmm_regime")

        bar_o = float(bar_data.get("o", 0.0))
        bar_h = float(bar_data.get("h", 0.0))
        bar_l = float(bar_data.get("l", 0.0))
        bar_c = float(bar_data.get("c", 0.0))
        bar_v = float(bar_data.get("v", 0))
        ts_ns = int(ts.timestamp() * 1e9)
        signal_computed_at = datetime.now(UTC)

        entries: list[LedgerEntry] = []
        for sig in agg_result.all_ranked:
            rank = sig.get("composite_rank", 99)
            was_selected = rank == 1 and agg_result.selected_signal is not None
            setup_plugin = sig.get("setup_plugin", "unknown")
            direction = int(sig.get("direction", 0))

            sid = make_signal_id(
                symbol=symbol,
                feature_ts_ns=ts_ns,
                feature_tf=tf,
                open_=bar_o,
                high=bar_h,
                low=bar_l,
                close=bar_c,
                volume=bar_v,
                setup_plugin=setup_plugin,
                direction=direction,
            )

            ttl = sig.get("ttl_bars")
            expires_at = None
            if ttl is not None:
                try:
                    expires_at = ts + timedelta(seconds=int(ttl) * tf_secs)
                except (OverflowError, TypeError, ValueError):
                    expires_at = None

            entries.append(
                LedgerEntry(
                    signal_id=sid,
                    timestamp=ts,
                    symbol=symbol,
                    timeframe=tf,
                    setup_plugin=setup_plugin,
                    signal_type=sig.get("signal_type", "unknown"),
                    direction=direction,
                    was_selected=was_selected,
                    is_shadow=bool(sig.get("is_shadow", False)),
                    is_backfill=True,
                    signal_computed_at=signal_computed_at,
                    feature_ts=ts,
                    feature_tf=tf,
                    hmm_regime_at_fire=(
                        sig.get("hmm_regime_at_fire")
                        if "hmm_regime_at_fire" in sig
                        else (int(hmm_regime) if hmm_regime is not None else None)
                    ),
                    garch_sigma_at_fire=garch_sigma,
                    ttl_bars=ttl,
                    entry_price=float(sig.get("entry_price", 0.0)),
                    stop_loss=float(sig.get("stop_loss", 0.0)),
                    targets=[float(t) for t in sig.get("targets", [])],
                    entry_zone_low=sig.get("zone_low"),
                    entry_zone_high=sig.get("zone_high"),
                    market_entry_price=bar_c or None,
                    cis_score=(
                        sig.get("filtered_cis_score")
                        if sig.get("filtered_cis_score") is not None
                        else agg_result.cis_score
                    ),
                    bucket_scores=agg_result.bucket_scores,
                    weights_version=agg_result.weights_version,
                    expires_at=expires_at,
                    feature_schema_version=FEATURE_SCHEMA_VERSION,
                    stop_basis=sig.get("stop_basis"),
                    stop_type_col=sig.get("stop_type"),
                    structural_stop_distance_atr=sig.get("structural_stop_distance_atr"),
                    adaptive_buffer_mult=sig.get("adaptive_buffer_mult"),
                    plugin_regime_type=sig.get("plugin_regime_type"),
                    stop_structure_age_bars=sig.get("stop_structure_age_bars"),
                    raw_confidence=sig.get("pre_quality_confidence") or sig.get("confidence"),
                    calibrated_confidence=sig.get("calibrated_confidence"),
                    context_features=sig.get("context_features"),
                    ctf_score=sig.get("ctf_score"),
                    ctf_confirmed=sig.get("ctf_confirmed"),
                    zone_friction_score=sig.get("zone_friction_score"),
                    status=SignalStatus.PENDING,
                )
            )

        if not entries:
            continue

        signal_count += len(entries)

        if not dry_run:
            async with pool.acquire() as conn:
                async with conn.transaction():
                    for e in entries:
                        sid = str(e.signal_id)
                        direction = _direction_text(
                            int(e.direction) if isinstance(e.direction, (int, float)) else 1
                        )
                        raw_confidence = e.raw_confidence if e.raw_confidence is not None else 0.0

                        # Build frame_details JSONB: stop architecture + zone fields
                        frame_details: dict = {}
                        if e.stop_basis is not None:
                            frame_details["stop_basis"] = e.stop_basis
                        if e.stop_type_col is not None:
                            frame_details["stop_type_col"] = e.stop_type_col
                        if e.structural_stop_distance_atr is not None:
                            frame_details["structural_stop_distance_atr"] = float(
                                e.structural_stop_distance_atr
                            )
                        if e.adaptive_buffer_mult is not None:
                            frame_details["adaptive_buffer_mult"] = float(e.adaptive_buffer_mult)
                        if e.stop_structure_age_bars is not None:
                            frame_details["stop_structure_age_bars"] = e.stop_structure_age_bars
                        if e.entry_zone_low is not None:
                            frame_details["entry_zone_low"] = float(e.entry_zone_low)
                        if e.entry_zone_high is not None:
                            frame_details["entry_zone_high"] = float(e.entry_zone_high)
                        if e.market_entry_price is not None:
                            frame_details["market_entry_price"] = float(e.market_entry_price)

                        # Extract first target for trade_frames.target_price
                        targets = e.targets or []
                        target_price = float(targets[0]) if targets else None
                        stop_price = float(e.stop_loss) if e.stop_loss is not None else None
                        entry_price = float(e.entry_price) if e.entry_price is not None else None
                        r_multiple = None
                        if (
                            target_price is not None
                            and entry_price is not None
                            and stop_price is not None
                        ):
                            denom = entry_price - stop_price
                            if denom != 0:
                                r_multiple = (target_price - entry_price) / denom

                        frame_id = _make_frame_id(sid, "at_close")

                        await conn.execute(
                            _INSERT_SIGNAL_EVENTS_SQL,
                            sid,  # signal_id
                            e.timestamp,  # ts
                            e.symbol,  # symbol
                            e.timeframe,  # tf
                            e.setup_plugin,  # setup_plugin
                            direction,  # direction (text)
                            raw_confidence,  # raw_confidence (NOT NULL)
                            e.calibrated_confidence,  # calibrated_confidence
                            e.cis_score,  # cis_score
                            e.weights_version,  # weights_version
                            None,  # factor_scores (plugin-local, not in replay path)
                            e.context_features,  # context_features (asyncpg dict -> jsonb)
                            e.ctf_score,  # ctf_score
                            e.ctf_confirmed,  # ctf_confirmed
                            e.zone_friction_score,  # zone_friction_score
                            e.hmm_regime_at_fire,  # hmm_regime_at_fire
                            e.plugin_regime_type,  # plugin_regime_type
                            e.garch_sigma_at_fire,  # garch_sigma_at_fire
                            e.is_shadow,  # is_shadow
                            True,  # is_backfill
                            "pending",  # status
                            SIGNAL_SCHEMA_VERSION,  # signal_schema_version (int)
                            e.ttl_bars,  # ttl_bars
                            e.expires_at,  # expires_at
                            e.signal_computed_at,  # signal_computed_at
                            e.feature_ts,  # feature_ts
                        )
                        await conn.execute(
                            _INSERT_TRADE_FRAMES_SQL,
                            frame_id,  # frame_id
                            sid,  # signal_id
                            e.timestamp,  # signal_ts (FK anchor)
                            "at_close",  # entry_type
                            direction,  # direction (text)
                            entry_price,  # entry_price
                            stop_price,  # stop_price (was stop_loss)
                            target_price,  # target_price (first target)
                            r_multiple,  # r_multiple
                            e.ttl_bars,  # ttl_bars
                            e.expires_at,  # expires_at
                            # counterfactual_pnl_r = NULL (CounterfactualTracker v2.11)
                            e.was_selected,  # was_selected
                            json.dumps(frame_details) if frame_details else None,  # frame_details
                        )

    return signal_count


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


async def main() -> None:
    parser = argparse.ArgumentParser(
        description="I7-only replay from intelligence_features — bypasses I1-I6 compute."
    )
    parser.add_argument(
        "--plugins",
        default=None,
        help="Comma-separated plugin names. Default: all I7 plugins (TIER_I7).",
    )
    parser.add_argument(
        "--symbols",
        default=None,
        help="Comma-separated symbols (e.g. ESM6,NQM6). Default: all active contracts.",
    )
    parser.add_argument(
        "--since",
        default=None,
        help="ISO date string (e.g. 2026-01-01). Replay rows with ts >= since.",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=4,
        help="Number of concurrent (symbol, tf) tasks. Default: 4.",
    )
    parser.add_argument(
        "--shadow-setups",
        action="store_true",
        help=(
            "Use _SHADOW_VALIDATION_SETUPS from shadow_validator.py as the plugin set "
            "(overrides --plugins)."
        ),
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Reconstruct and run plugins but do not write to signal_events.",
    )
    args = parser.parse_args()

    setup_service_logging("logs/feature_replay.log")

    settings = Settings()
    register_all_plugins()

    # Resolve plugins
    if args.shadow_setups:
        # Add services/ to sys.path so shadow_validator import works
        _services_dir = str(_project_root / "services")
        if _services_dir not in sys.path:
            sys.path.insert(0, _services_dir)
        from shadow_validator import _SHADOW_VALIDATION_SETUPS

        plugins = list(_SHADOW_VALIDATION_SETUPS)
        logger.info(
            "feature_replay: shadow-setups mode",
            plugin_count=len(plugins),
            plugins=sorted(plugins),
        )
        print(
            f"[feature_replay] shadow-setups mode: {len(plugins)} plugins from _SHADOW_VALIDATION_SETUPS"
        )
    elif args.plugins:
        plugins = [p.strip() for p in args.plugins.split(",") if p.strip()]
    else:
        plugins = list(TIER_I7)

    logger.info("feature_replay: resolved plugins", count=len(plugins))

    # Resolve symbols
    if args.symbols:
        symbols = [s.strip() for s in args.symbols.split(",") if s.strip()]
    else:
        contracts = get_active_contracts(settings)
        symbols = [c.symbol for c in contracts]

    since = parse_iso_ts(args.since)

    # Default timeframes (mirrors run_historical_pipeline DEFAULT_TIMEFRAMES)
    timeframes = ["1m", "5m", "15m", "1h", "4h", "1d"]

    print(
        f"[feature_replay] symbols={symbols} plugins={len(plugins)} "
        f"timeframes={timeframes} since={args.since} dry_run={args.dry_run} workers={args.workers}"
    )

    pool = await create_pool(
        settings.database_url,
        min_size=2,
        max_size=max(4, args.workers + 2),
    )

    t_start = time.monotonic()

    # Build (symbol, tf) task pairs and run concurrently with semaphore gate
    semaphore = asyncio.Semaphore(args.workers)
    symbol_counts: dict[str, int] = {}
    total_signals = 0

    async def _bounded_replay(sym: str, tf: str) -> tuple[str, str, int]:
        async with semaphore:
            count = await _replay_symbol_tf(pool, sym, tf, since, plugins, args.dry_run)
            return sym, tf, count

    tasks = [_bounded_replay(sym, tf) for sym in symbols for tf in timeframes]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    for result in results:
        if isinstance(result, Exception):
            logger.warning("feature_replay: task failed", error=str(result))
            continue
        sym, tf, count = result
        symbol_counts[sym] = symbol_counts.get(sym, 0) + count
        total_signals += count

    await pool.close()

    elapsed = time.monotonic() - t_start

    # Summary
    print(f"\n[feature_replay] Complete in {elapsed:.1f}s")
    print(f"  Total signals {'(dry-run) ' if args.dry_run else ''}inserted: {total_signals}")
    for sym, count in sorted(symbol_counts.items()):
        print(f"  {sym}: {count} signals")

    logger.info(
        "feature_replay: complete",
        total_signals=total_signals,
        elapsed_s=round(elapsed, 2),
        dry_run=args.dry_run,
        symbol_counts=symbol_counts,
    )


if __name__ == "__main__":
    asyncio.run(main())
