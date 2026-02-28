#!/usr/bin/env python3
"""
Historical Backfill Pipeline

Stage 1 (--fetch-only): Fetches multi-timeframe OHLCV bars from IBKR and stores
them in market_data_ohlcv. Short timeframes use named contracts; longer timeframes
use back-adjusted continuous contracts (ContFuture + ADJUSTED_LAST) to span rolls.

    Timeframe  History   Contract
    1m         35 days   Named (ESH6) — no rolls
    5m         1 year    Continuous adjusted — ~4 rolls
    15m        1 year    Continuous adjusted — ~4 rolls
    1h         2 years   Continuous adjusted — ~8 rolls
    1d         5 years   Continuous adjusted — ~20 rolls

Stage 2 (--replay-only): Reads each timeframe's native stored bars and replays
them through the full I1→I3→I4→I5→SMC→I6→I7 pipeline to populate
signal_ledger and intelligence_features.

Replaces: production/scripts/simple_seeder.py (retired)

Usage:
    python production/scripts/historical_backfill.py
    python production/scripts/historical_backfill.py --fetch-only
    python production/scripts/historical_backfill.py --replay-only
    python production/scripts/historical_backfill.py --symbols ESH6,NQH6
    python production/scripts/historical_backfill.py --days 60   # override 1m depth only
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from collections import defaultdict, deque
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

import psycopg2
import psycopg2.extras

project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

import pandas as pd

from src.config.settings import Settings
from src.intelligence.plugins import registry
from src.intelligence.register_plugins import register_all_plugins
from src.intelligence.trading.aggregator import AggregatedResult, aggregate
from src.intelligence.trading.signal_ledger import LedgerEntry
from src.providers import IBKRProvider

# ---------------------------------------------------------------------------
# Plugin lists — keep in sync with services
# ---------------------------------------------------------------------------
I1_PLUGINS = [
    "RSI", "MovingAverages", "MAComposite", "MACD", "ATR", "BollingerBands",
    "Stochastic", "CCI", "WilliamsR", "MFI", "OBV", "VWAP", "Supertrend",
    "ADX", "KeltnerChannels", "DonchianChannels", "ROC_PPO",
    "ind_CMF", "ind_Aroon", "ind_HistoricalVolatility",
    "ind_ChandelierExit", "ind_ParabolicSAR", "ind_StochRSI",
]
I3_PLUGINS = ["struct_SwingDetector", "struct_SupportResistance", "struct_TrendStructure"]
I4_PLUGINS = [
    "ctx_VolatilityRegime", "ctx_TrendRegime", "ctx_MomentumContext", "ctx_GARCHVolatility",
]
I5_PLUGINS = [
    "RSIDivergence", "BollingerSqueeze", "VolumeDivergence", "Confluence", "TrendConfluence",
]
SMC_PLUGINS = [
    "smc_BOSCHoCH", "smc_FairValueGap", "smc_OrderBlocks",
    "smc_LiquiditySweeps", "smc_BOCPDChangePoint",
]
I6_PLUGINS = ["i6_CrossTimeframeConfluence"]
I7_PLUGINS = [
    "trad_TrendFollowing", "trad_MeanReversion", "trad_LiquiditySweepReclaim",
    "trad_MTFAlignment", "trad_SqueezeExpansion", "trad_VWAPDeviation",
    "trad_MomentumBreakout",
]

MIN_BARS = 50
DEFAULT_TIMEFRAMES = ["1m", "5m", "15m", "1h", "1d"]

# Per-TF fetch config: (days_of_history, use_continuous_contract)
# Named contract for 1m (no rolls in 35 days); continuous back-adjusted for all others.
_TF_FETCH_CONFIG: dict[str, tuple[int, bool]] = {
    "1m":  (35,   False),  # named contract — no roll crossings
    "5m":  (365,  True),   # continuous adjusted — ~4 rolls
    "15m": (365,  True),   # continuous adjusted — ~4 rolls
    "1h":  (730,  True),   # continuous adjusted — ~8 rolls
    "1d":  (1825, True),   # continuous adjusted — ~20 rolls
}


def run_i1_plugins(
    bar_history: deque,
    symbol: str,
    timeframe: str,
) -> dict[str, Any]:
    """Run all I1 indicator plugins on the current bar history.

    Returns empty dict if fewer than MIN_BARS are available (indicators
    need warmup history to produce meaningful values).
    """
    if len(bar_history) < MIN_BARS:
        return {}

    df = pd.DataFrame(list(bar_history))
    frames: dict[str, Any] = {"main": df, "features": {}}
    features: dict[str, Any] = {}

    for name in I1_PLUGINS:
        try:
            plugin = registry.get_indicator(name)
            out = plugin.compute_full(frames)
            if out:
                features.update({k: v for k, v in out.items()
                                  if isinstance(v, (int, float, str, bool))})
                frames["features"] = features
        except Exception:
            pass  # individual plugin failure never kills the replay

    return features


def run_analysis_pipeline(
    frames: dict[str, Any],
    intelligence_cache: dict[str, dict[str, Any]],
    symbol: str,
    timeframe: str,
) -> dict[str, Any]:
    """Run I3 → I4 → I5 → SMC → I6 plugins in tier order.

    Mutates frames["features"] in-place (same as market_analysis_service).
    Caches result in intelligence_cache[symbol][timeframe] for I6 cross-TF plugin.

    Returns:
        Merged intelligence dict from all tiers.
    """
    features = dict(frames.get("features", {}))
    frames["features"] = features
    intelligence: dict[str, Any] = {}

    tier_sequence = [
        (I3_PLUGINS, "I3"),
        (I4_PLUGINS, "I4"),
        (I5_PLUGINS, "I5"),
        (SMC_PLUGINS, "SMC"),
        (I6_PLUGINS, "I6"),
    ]

    for plugin_names, _ in tier_sequence:
        for name in plugin_names:
            try:
                plugin = registry.get_pattern(name)
                out = plugin.compute_full(frames)
                if out:
                    intelligence.update(out)
                    features.update(out)
                    frames["features"] = features
            except Exception:
                pass

    intelligence_cache.setdefault(symbol, {})[timeframe] = intelligence
    return intelligence


# ---------------------------------------------------------------------------
# Intelligence features — sync DB insert (mirrors feature_writer_service with %s placeholders)
# ---------------------------------------------------------------------------

_INSERT_FEATURE_SYNC_SQL = """
INSERT INTO intelligence_features (
    ts, symbol, tf, platform, source, schema_version,
    bar, i1, i3, i4, i5, smc, i6
) VALUES (%s, %s, %s, %s, %s, %s,
    %s::jsonb, %s::jsonb, %s::jsonb, %s::jsonb, %s::jsonb, %s::jsonb, %s::jsonb)
ON CONFLICT (ts, symbol, tf) DO NOTHING
"""


def _build_intelligence_event(
    bar: dict,
    i1_features: dict,
    intelligence: dict,
    symbol: str,
    tf: str,
    ts: datetime,
) -> Any:
    """Build IntelligenceEvent from per-bar pipeline outputs.

    Returns None on any exception (never crashes the replay loop).
    source is always 'backfill'.

    Args:
        bar: dict with keys 'open', 'high', 'low', 'close', 'volume'
        i1_features: flat dict of I1 indicator outputs (extra='allow' model)
        intelligence: merged flat dict from run_analysis_pipeline (all tiers)
        symbol: contract symbol (e.g. 'ESH6')
        tf: timeframe string (e.g. '1m')
        ts: bar timestamp (timezone-aware datetime)
    """
    try:
        from src.intelligence.schemas import (
            I1Indicators,
            I3Structure,
            I4Context,
            I5Patterns,
            I6Confluence,
            IntelligenceEvent,
            OHLCVBar,
            SMCContext,
        )

        def _pick(model_cls: Any, src: dict) -> dict:
            """Filter src to only keys declared in model_cls.model_fields."""
            fields = model_cls.model_fields.keys()
            return {k: v for k, v in src.items() if k in fields}

        return IntelligenceEvent(
            ts=ts,
            symbol=symbol,
            tf=tf,
            source="backfill",
            bar=OHLCVBar(
                o=float(bar["open"]),
                h=float(bar["high"]),
                l=float(bar["low"]),
                c=float(bar["close"]),
                v=int(bar["volume"]),
            ),
            i1=I1Indicators(**_pick(I1Indicators, i1_features)),
            i3=I3Structure(**_pick(I3Structure, intelligence)),
            i4=I4Context(**_pick(I4Context, intelligence)),
            i5=I5Patterns(**_pick(I5Patterns, intelligence)),
            smc=SMCContext(**_pick(SMCContext, intelligence)),
            i6=I6Confluence(**_pick(I6Confluence, intelligence)),
        )
    except Exception:
        return None


def _event_to_sync_params(event: Any) -> tuple:
    """Serialize IntelligenceEvent to a 13-element tuple for psycopg2 batch insert.

    Column order matches _INSERT_FEATURE_SYNC_SQL:
      ts, symbol, tf, platform, source, schema_version,
      bar, i1, i3, i4, i5, smc, i6

    bar and i1 are serialized with model_dump() (include None values for completeness).
    i3, i4, i5, smc, i6 are serialized with model_dump(exclude_none=True) for compactness.
    """
    return (
        event.ts,                                                # datetime — psycopg2 native
        event.symbol,
        event.tf,
        event.platform,
        event.source,
        event.schema_version,
        json.dumps(event.bar.model_dump()),                      # bar: include all fields
        json.dumps(event.i1.model_dump()),                       # i1: include all fields
        json.dumps(event.i3.model_dump(exclude_none=True)),      # i3: sparse (extra='forbid')
        json.dumps(event.i4.model_dump(exclude_none=True)),      # i4: sparse
        json.dumps(event.i5.model_dump(exclude_none=True)),      # i5: sparse
        json.dumps(event.smc.model_dump(exclude_none=True)),     # smc: sparse
        json.dumps(event.i6.model_dump(exclude_none=True)),      # i6: sparse
    )


def _insert_features_sync(conn: Any, rows: list) -> None:
    """Synchronous psycopg2 batch insert into intelligence_features.

    Args:
        conn: psycopg2 connection
        rows: list of 13-element tuples from _event_to_sync_params()
    """
    if not rows:
        return
    with conn.cursor() as cur:
        psycopg2.extras.execute_batch(cur, _INSERT_FEATURE_SYNC_SQL, rows)
    conn.commit()


# ---------------------------------------------------------------------------
# Signal generation + sync DB insert
# ---------------------------------------------------------------------------

MARKET_CONTEXT_KEYS = (
    "trend_regime", "volatility_regime", "trend_confidence",
    "atr_14", "rsi_14", "ctf_score", "swing_pattern",
    "trend_strength", "volatility_percentile", "hmm_regime_state",
)

_INSERT_SYNC_SQL = """
INSERT INTO signal_ledger (
    signal_id, timestamp, symbol, timeframe, setup_plugin, signal_type,
    direction, entry_price, stop_loss, targets,
    confidence, confluence_score, regime_context, supporting_factors,
    was_selected, num_signals_bar, num_agreeing, num_conflicting,
    resolution_method, composite_rank, market_context, status,
    feature_ts, feature_tf,
    cis_score, bucket_scores, weights_version, signal_quality
) VALUES (
    %s::uuid, %s, %s, %s, %s, %s,
    %s, %s, %s, %s::jsonb,
    %s, %s, %s, %s::jsonb,
    %s, %s, %s, %s,
    %s, %s, %s::jsonb, %s,
    %s, %s,
    %s, %s::jsonb, %s, %s
) ON CONFLICT DO NOTHING
"""


def _build_ledger_entries(
    result: AggregatedResult,
    symbol: str,
    timeframe: str,
    timestamp: datetime,
    features: dict[str, Any],
    feature_ts: datetime | None = None,
    feature_tf: str | None = None,
) -> list[LedgerEntry]:
    """Convert an AggregatedResult into LedgerEntry objects for DB insertion.

    Args:
        result: aggregated I7 signals
        symbol: contract symbol
        timeframe: bar timeframe
        timestamp: bar timestamp
        features: merged feature dict for market_context extraction
        feature_ts: timestamp of the corresponding intelligence_features row (None if not written)
        feature_tf: timeframe of the corresponding intelligence_features row (None if not written)
    """
    if not result.all_ranked:
        return []

    market_ctx = {k: features[k] for k in MARKET_CONTEXT_KEYS if k in features}

    entries = []
    for sig in result.all_ranked:
        rank = sig.get("composite_rank", 99)
        was_selected = rank == 1 and result.selected_signal is not None
        entries.append(LedgerEntry(
            signal_id=str(uuid4()),
            timestamp=timestamp,
            symbol=symbol,
            timeframe=timeframe,
            setup_plugin=sig.get("setup_plugin", "unknown"),
            signal_type=sig.get("signal_type", "unknown"),
            direction=int(sig.get("direction", 0)),
            entry_price=float(sig.get("entry_price", 0.0)),
            stop_loss=float(sig.get("stop_loss", 0.0)),
            targets=[float(t) for t in sig.get("targets", [])],
            confidence=float(sig.get("confidence", 0.0)),
            confluence_score=float(sig.get("confluence_score", 0.0)),
            regime_context=str(sig.get("regime_context", "")),
            supporting_factors=list(sig.get("supporting_factors", [])),
            was_selected=was_selected,
            num_signals_bar=result.num_signals_fired,
            num_agreeing=result.num_agreeing,
            num_conflicting=result.num_conflicting,
            resolution_method=result.resolution_method,
            composite_rank=rank,
            market_context=market_ctx,
            status="pending",
            feature_ts=feature_ts,
            feature_tf=feature_tf,
        ))
    return entries


def _insert_signals_sync(conn: Any, entries: list[LedgerEntry]) -> None:
    """Synchronous psycopg2 batch insert into signal_ledger."""
    if not entries:
        return
    params = []
    for e in entries:
        params.append((
            e.signal_id, e.timestamp, e.symbol, e.timeframe,
            e.setup_plugin, e.signal_type, e.direction, e.entry_price, e.stop_loss,
            json.dumps(e.targets), e.confidence, e.confluence_score,
            e.regime_context, json.dumps(e.supporting_factors),
            e.was_selected, e.num_signals_bar, e.num_agreeing, e.num_conflicting,
            e.resolution_method, e.composite_rank, json.dumps(e.market_context),
            e.status,
            e.feature_ts,   # None for backfill
            e.feature_tf,   # None for backfill
            None,           # cis_score — NULL for backfill rows
            None,           # bucket_scores — NULL for backfill rows
            None,           # weights_version — NULL for backfill rows
            None,           # signal_quality — NULL for backfill rows
        ))
    with conn.cursor() as cur:
        psycopg2.extras.execute_batch(cur, _INSERT_SYNC_SQL, params)
    conn.commit()


def run_i7_and_persist(
    bar_history: deque,
    features: dict[str, Any],
    symbol: str,
    timeframe: str,
    timestamp: datetime,
    db_conn: Any,
    feature_ts: datetime | None = None,
    feature_tf: str | None = None,
) -> int:
    """Run I7 setup plugins on bar_history+features, aggregate, persist to signal_ledger.

    Args:
        bar_history: rolling window of bar dicts
        features: merged I1-I6 feature dict
        symbol: contract symbol
        timeframe: bar timeframe
        timestamp: bar timestamp
        db_conn: psycopg2 connection (None for dry-run)
        feature_ts: timestamp of the intelligence_features row for this bar (None if not written)
        feature_tf: timeframe of the intelligence_features row (None if not written)

    Returns:
        Number of ledger entries inserted (0 if no signals fired).
    """
    if len(bar_history) < MIN_BARS:
        return 0

    df = pd.DataFrame(list(bar_history))
    frames: dict[str, Any] = {"main": df, "features": features}

    raw_signals = []
    for name in I7_PLUGINS:
        try:
            plugin = registry.get_pattern(name)
            result = plugin.compute_full(frames)
            if result and result.get("direction", 0) != 0:
                result["setup_plugin"] = name
                raw_signals.append(result)
        except Exception:
            pass

    if not raw_signals:
        return 0

    trend_regime = float(features.get("trend_regime", 0.0))
    agg_result = aggregate(raw_signals, trend_regime=trend_regime)
    entries = _build_ledger_entries(
        agg_result, symbol, timeframe, timestamp, features,
        feature_ts=feature_ts, feature_tf=feature_tf,
    )

    if entries and db_conn is not None:
        _insert_signals_sync(db_conn, entries)

    return len(entries)


# ---------------------------------------------------------------------------
# DB fetch/store layer
# ---------------------------------------------------------------------------

_FETCH_BARS_SQL = """
SELECT timestamp, open, high, low, close, volume
FROM market_data_ohlcv
WHERE symbol = %s AND timeframe = %s
ORDER BY timestamp ASC
"""

_FETCH_BARS_SINCE_SQL = """
SELECT timestamp, open, high, low, close, volume
FROM market_data_ohlcv
WHERE symbol = %s AND timeframe = %s AND timestamp >= %s
ORDER BY timestamp ASC
"""

_STORE_SQL = """
INSERT INTO market_data_ohlcv
    (timestamp, symbol, timeframe, open, high, low, close, volume, source)
VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
ON CONFLICT (timestamp, symbol, timeframe) DO NOTHING
"""


def connect_db(settings: Settings) -> Any:
    """Create a synchronous psycopg2 connection from Settings."""
    # Parse DATABASE_URL: postgresql://user:pass@host:port/dbname
    url = settings.database_url
    # Simple parse — production URLs follow this pattern
    url = url.replace("postgresql://", "").replace("postgres://", "")
    userpass, rest = url.split("@", 1)
    user, password = userpass.split(":", 1)
    hostport_db = rest.split("/", 1)
    hostport = hostport_db[0]
    dbname = hostport_db[1] if len(hostport_db) > 1 else "indicagent"
    host, port = (hostport.split(":", 1) if ":" in hostport else (hostport, "5432"))

    return psycopg2.connect(
        host=host, port=int(port), database=dbname, user=user, password=password
    )


def fetch_bars(conn: Any, symbol: str, timeframe: str, since: datetime | None = None) -> list[dict]:
    """Fetch stored OHLCV bars for *symbol* + *timeframe*, ordered oldest-first.

    Args:
        since: If provided, only fetch bars on or after this timestamp.
    """
    with conn.cursor() as cur:
        if since is not None:
            cur.execute(_FETCH_BARS_SINCE_SQL, (symbol, timeframe, since))
        else:
            cur.execute(_FETCH_BARS_SQL, (symbol, timeframe))
        rows = cur.fetchall()
    return [
        {
            "timestamp": row[0] if row[0].tzinfo else row[0].replace(tzinfo=UTC),
            "symbol": symbol,
            "timeframe": timeframe,
            "open": float(row[1]),
            "high": float(row[2]),
            "low": float(row[3]),
            "close": float(row[4]),
            "volume": int(row[5]),
        }
        for row in rows
    ]


def store_bars(conn: Any, bars: list[dict], symbol: str, timeframe: str) -> int:
    """Upsert bars into market_data_ohlcv. Returns count inserted."""
    if not bars:
        return 0
    params = [
        (b["timestamp"], symbol, timeframe,
         b["open"], b["high"], b["low"], b["close"], b["volume"],
         b.get("source", "historical_backfill"))
        for b in bars
    ]
    with conn.cursor() as cur:
        psycopg2.extras.execute_batch(cur, _STORE_SQL, params)
    conn.commit()
    return len(params)


# ---------------------------------------------------------------------------
# Replay orchestrator
# ---------------------------------------------------------------------------

def replay_symbol(
    symbol: str,
    db_conn: Any,
    timeframes: list[str] | None = None,
    since: datetime | None = None,
) -> dict[str, int]:
    """Replay bars for *symbol* through the I1→I7 pipeline.

    Processes timeframes in order: 1m first, then 5m, 15m, 1h.
    Lower-TF bar history is available as cross-TF context when processing
    higher timeframes (same as live services).

    Args:
        since: If provided, only replay bars on or after this timestamp.

    Returns:
        dict mapping timeframe → number of ledger entries inserted.
    """
    if timeframes is None:
        timeframes = DEFAULT_TIMEFRAMES

    register_all_plugins()

    # Load native stored bars for each requested timeframe.
    # Each TF reads its own rows from market_data_ohlcv (1m = named contract,
    # 5m/1h/1d = back-adjusted continuous). Higher TFs have deeper history.
    bars_by_tf: dict[str, list[dict]] = {}
    for tf in timeframes:
        bars = fetch_bars(db_conn, symbol, tf, since=since)
        if bars:
            bars_by_tf[tf] = bars
            print(f"  {symbol}: {len(bars):,} {tf} bars loaded")
        else:
            print(f"  {symbol}: no {tf} bars in DB — skipping (run fetch stage first)")

    if not bars_by_tf:
        print(f"  {symbol}: no bars found in DB — run fetch stage first")
        return {}

    # Shared state across timeframes for cross-TF context
    bar_histories: dict[str, deque] = defaultdict(lambda: deque(maxlen=200))
    intelligence_cache: dict[str, dict] = {}

    signal_counts: dict[str, int] = {}

    for tf in timeframes:
        if tf not in bars_by_tf:
            continue

        bars = bars_by_tf[tf]
        total_signals = 0
        print(f"  {symbol}/{tf}: replaying {len(bars):,} bars...")

        for i, bar in enumerate(bars):
            ts = bar["timestamp"]
            history_key = f"{symbol}:{tf}"
            bar_histories[history_key].append(bar)
            history = bar_histories[history_key]

            # I1
            i1_features = run_i1_plugins(history, symbol, tf)
            if not i1_features:
                continue  # not enough bars yet

            # Build frames with cross-TF context (for I6 confluence)
            df = pd.DataFrame(list(history))
            frames: dict[str, Any] = {"main": df, "features": i1_features}

            tf_hierarchy = ["1m", "5m", "15m", "1h"]
            for other_tf in tf_hierarchy:
                if other_tf == tf:
                    continue
                other_key = f"{symbol}:{other_tf}"
                if other_key in bar_histories and len(bar_histories[other_key]) >= 50:
                    frames[f"tf_{other_tf}"] = pd.DataFrame(list(bar_histories[other_key]))
                cached = intelligence_cache.get(symbol, {}).get(other_tf)
                if cached:
                    frames[f"intel_{other_tf}"] = cached

            # I3 → I6
            intelligence = run_analysis_pipeline(frames, intelligence_cache, symbol, tf)

            # Merge all features for I7
            all_features = {**i1_features, **intelligence}

            # Build IntelligenceEvent and write to intelligence_features
            event = _build_intelligence_event(bar, i1_features, intelligence, symbol, tf, ts)
            written_feature_ts: datetime | None = None
            if event is not None:
                _insert_features_sync(db_conn, [_event_to_sync_params(event)])
                written_feature_ts = ts

            # I7 → signal_ledger (with feature_ts populated when features row was written)
            n = run_i7_and_persist(
                history, all_features, symbol, tf, ts, db_conn,
                feature_ts=written_feature_ts,
                feature_tf=(tf if written_feature_ts is not None else None),
            )
            total_signals += n

            if (i + 1) % 1000 == 0:
                print(f"    {symbol}/{tf}: {i+1:,}/{len(bars):,} bars, {total_signals} signals so far")

        signal_counts[tf] = total_signals
        print(f"  {symbol}/{tf}: done — {total_signals} signals inserted")

    return signal_counts




# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Historical Backfill — fetch IBKR bars + replay intelligence pipeline"
    )
    parser.add_argument("--days", type=int, default=35,
                        help="Days of 1m history to fetch (default: 35). Does not affect 5m/1h/1d depths.")
    parser.add_argument("--symbols", default=None,
                        help="Comma-separated symbols, e.g. ESH6,NQH6 (default: all active contracts)")
    parser.add_argument("--timeframes", default="1m,5m,15m,1h,1d",
                        help="Comma-separated timeframes for fetch+replay (default: 1m,5m,15m,1h,1d)")
    parser.add_argument("--client-id", type=int, default=56,
                        help="IBKR client ID (default: 56)")
    parser.add_argument("--fetch-only", action="store_true",
                        help="Only fetch from IBKR → DB, skip intelligence replay")
    parser.add_argument("--replay-only", action="store_true",
                        help="Only replay DB → signal_ledger, skip IBKR fetch")
    args = parser.parse_args()

    settings = Settings()
    timeframes = [t.strip() for t in args.timeframes.split(",") if t.strip()]

    # Filter contracts
    contracts = settings.contracts
    if args.symbols:
        wanted = {s.strip() for s in args.symbols.split(",") if s.strip()}
        contracts = [c for c in contracts if c.symbol in wanted]
        if not contracts:
            print(f"No matching contracts for: {args.symbols}")
            return

    print("Historical Backfill Pipeline")
    print(f"  Contracts : {[c.symbol for c in contracts]}")
    print(f"  Timeframes: {timeframes}")
    tf_depths = {tf: (args.days if tf == "1m" else _TF_FETCH_CONFIG[tf][0])
                 for tf in timeframes if tf in _TF_FETCH_CONFIG}
    print(f"  TF depths : {tf_depths}")
    print(f"  Stages    : {'fetch+replay' if not (args.fetch_only or args.replay_only) else 'fetch-only' if args.fetch_only else 'replay-only'}")
    print()

    db_conn = connect_db(settings)

    # --------------- Stage 1: IBKR Fetch ---------------
    if not args.replay_only:
        import asyncio
        print("=== Stage 1: IBKR Fetch ===")
        provider = IBKRProvider(
            host=settings.ib_host,
            port=settings.ib_port,
            client_id=args.client_id,
        )
        if not asyncio.run(provider.connect()):
            print("Cannot connect to TWS — aborting fetch stage")
            if args.fetch_only:
                db_conn.close()
                return
            print("Continuing with replay-only...")
        else:
            end_dt = datetime.now(tz=UTC)
            total_bars = 0
            # Fetch each requested TF using its configured depth and contract type.
            # 1m uses --days override; others use _TF_FETCH_CONFIG defaults.
            fetch_tfs = [tf for tf in timeframes if tf in _TF_FETCH_CONFIG]
            print(f"  Fetching TFs: {fetch_tfs}")
            print()
            for instrument in contracts:
                try:
                    qualified = asyncio.run(provider.qualify_instrument(instrument))
                    if not qualified:
                        print(f"  {instrument.symbol}: skipped (qualify failed)")
                        continue
                    for tf in fetch_tfs:
                        fetch_days, use_continuous = _TF_FETCH_CONFIG[tf]
                        if tf == "1m":
                            fetch_days = args.days  # --days overrides 1m depth
                        start_dt = (end_dt - timedelta(days=fetch_days)).replace(
                            hour=0, minute=0, second=0, microsecond=0
                        )
                        try:
                            ohlcv_bars = asyncio.run(provider.fetch_historical_bars(
                                symbol=instrument.symbol,
                                timeframe=tf,
                                start=start_dt,
                                end=end_dt,
                                continuous=use_continuous,
                            ))
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
                            n = store_bars(db_conn, bar_dicts, instrument.symbol, tf)
                            total_bars += n
                            label = "continuous-adj" if use_continuous else "named"
                            print(f"  {instrument.symbol}/{tf} ({label}, {fetch_days}d): {n} bars stored")
                        except Exception as e:
                            print(f"  {instrument.symbol}/{tf}: error — {e}")
                        time.sleep(2)  # IBKR pacing between TF requests
                except Exception as e:
                    print(f"  {instrument.symbol}: error — {e}")
                time.sleep(2)  # IBKR pacing between instruments
            asyncio.run(provider.disconnect())
            print(f"\nStage 1 complete: {total_bars:,} total bars stored\n")

    # --------------- Stage 2: Intelligence Replay ---------------
    if not args.fetch_only:
        print("=== Stage 2: Intelligence Replay ===")
        since_dt = (datetime.now(tz=UTC) - timedelta(days=args.days)).replace(
            hour=0, minute=0, second=0, microsecond=0
        ) if args.replay_only else None
        if since_dt:
            print(f"  Replaying bars since: {since_dt.date()} ({args.days}d)")
        grand_total = 0
        for contract in contracts:
            print(f"\n{contract.symbol}:")
            counts = replay_symbol(contract.symbol, db_conn, timeframes, since=since_dt)
            symbol_total = sum(counts.values())
            grand_total += symbol_total
            print(f"  {contract.symbol} total: {symbol_total} signals")

        print(f"\nStage 2 complete: {grand_total} total signals inserted into signal_ledger")

    db_conn.close()
    print("\nBackfill complete.")


if __name__ == "__main__":
    main()
