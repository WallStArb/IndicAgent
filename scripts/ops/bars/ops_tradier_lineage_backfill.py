#!/usr/bin/env python3
"""One-time 1d repair: Tradier lineage, current 1d digests and replaced legacy flags (plan 185-30).

The Tradier loader learned to write tradier-v1 lineage and 1d digests in plan 185-27; the bars it
stored before then carry no lineage (or a stale d2-v1 row from before the overwrite) and digests
computed over the IBKR values they replaced. This script repairs that corpus with the write
path's own statements, never copies of them:

- lineage (default mode): for every Tradier-owned name (TRADIER_OWNED_SQL, or --symbols) runs
  the loader's TRADIER_LINEAGE_UPSERT_SQL, which names the latest equal TRADIER observation of
  each stored tradier bar, then the loader's unmatched check. A stored bar with no equal
  observation gets no lineage; it is listed and the batch ends failed (exit 1).
- --digests: write_1d_digests (services/bar_derivation.py) over every symbol with canonical 1d
  bars, rule tradier-v1 for owned names and d2-v1 otherwise; only changed months are inserted.
- --retire-replaced-legacy-flags: deletes the 1d legacy_price_sanity_status flags (migration
  381) whose bar was replaced by a non-IBKR source, each judged on an IBKR value that
  ohlcv_revision still holds. Every retired flag and the replaced values are recorded in the
  batch detail and the names are re-digested. Intraday legacy flags are never touched.

Default is a dry run: lineage and retirement read only; the digest dry run calls the writer
inside a transaction it rolls back, so the stale-month count is the writer's own. --apply opens
one bar_derivation_batch (stage tradier, rule tradier-v1); each name is its own transaction on
one serial connection, writes under SET LOCAL ROLE bar_derivation_writer (D2's role and the
scrub's flag deleter).

Usage:
  python -m scripts.ops.bars.ops_tradier_lineage_backfill [--symbols A,B] [--apply]
  python -m scripts.ops.bars.ops_tradier_lineage_backfill --digests [--apply]
  python -m scripts.ops.bars.ops_tradier_lineage_backfill --retire-replaced-legacy-flags [--apply]
Exit codes: 0 clean; 1 unmatched bars or a per-name failure (other names still complete).
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import time
from pathlib import Path
from typing import Any

import asyncpg

project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))

from scripts.infrastructure.backfill.infrastructure_run_tradier_daily import (  # noqa: E402
    _TRADIER_LINEAGE_UNMATCHED_SQL,
    TRADIER_LINEAGE_UPSERT_SQL,
    TRADIER_OWNED_SQL,
)
from services.bar_derivation import write_1d_digests  # noqa: E402
from services.bar_derivation_batch import close_batch, open_batch  # noqa: E402
from src.config.settings import get_settings  # noqa: E402
from src.core.database_manager import _setup_codecs  # noqa: E402
from src.intelligence.bars.derivation import RULE_VERSION  # noqa: E402
from src.intelligence.bars.sources import (  # noqa: E402
    CANONICAL_1D_SOURCES,
    TRADIER_RULE_VERSION,
)
from src.providers.tradier import SOURCE as TRADIER_SOURCE  # noqa: E402

_WRITER_ROLE_SQL = "SET LOCAL ROLE bar_derivation_writer"
LEGACY_RULE = "legacy_price_sanity_status"
_IBKR_1D_SOURCES = [s for s in CANONICAL_1D_SOURCES if s != TRADIER_SOURCE]

OWNED_SYMBOLS_SQL = f"""
SELECT i.symbol FROM instruments i
WHERE {TRADIER_OWNED_SQL.format(col="i.symbol")}
ORDER BY i.symbol
"""

# Every symbol with a canonical 1d bar ($1 = CANONICAL_1D_SOURCES), with its ownership.
CANONICAL_1D_SYMBOLS_SQL = f"""
SELECT i.symbol, {TRADIER_OWNED_SQL.format(col="i.symbol")} AS owned
FROM instruments i
WHERE EXISTS (SELECT 1 FROM market_data_ohlcv m
              WHERE m.symbol = i.symbol AND m.timeframe = '1d' AND m.source = ANY($1::text[]))
ORDER BY i.symbol
"""

# One name's stored tradier bars, those whose lineage is missing or not tradier-v1, and those
# still carrying a d2-v1 row from before the Tradier overwrite.
LINEAGE_STATUS_SQL = f"""
SELECT count(*) AS n_stored,
       count(*) FILTER (WHERE l.rule_version IS DISTINCT FROM '{TRADIER_RULE_VERSION}') AS n_needs,
       count(*) FILTER (WHERE l.rule_version = '{RULE_VERSION}') AS n_stale_d2
FROM market_data_ohlcv m
LEFT JOIN canonical_bar_lineage l
  ON l.symbol = m.symbol AND l.timeframe = '1d' AND l."timestamp" = m."timestamp"
WHERE m.symbol = $1 AND m.timeframe = '1d' AND m.source = '{TRADIER_SOURCE}'
"""

# 1d legacy flags whose stored bar is no longer IBKR's ($1 = the IBKR 1d sources) and whose
# judged IBKR value ohlcv_revision holds. Read as the session user: bar_derivation_writer has no
# grant on ohlcv_revision.
REPLACED_LEGACY_FLAGS_SQL = f"""
SELECT f.symbol, f."timestamp", f.detail, m.source AS stored_source,
       {TRADIER_OWNED_SQL.format(col="f.symbol")} AS owned,
       jsonb_agg(jsonb_build_object(
           'load_id', r.load_id::text, 'old_open', r.old_open, 'old_high', r.old_high,
           'old_low', r.old_low, 'old_close', r.old_close, 'old_volume', r.old_volume,
           'old_source', r.old_source) ORDER BY r.load_id) AS replaced
FROM bar_quality_flag f
JOIN market_data_ohlcv m
  ON m.symbol = f.symbol AND m.timeframe = '1d' AND m."timestamp" = f."timestamp"
JOIN ohlcv_revision r
  ON r.symbol = f.symbol AND r.timeframe = '1d' AND r."timestamp" = f."timestamp"
 AND r.old_source = ANY($1::text[])
WHERE f.rule = '{LEGACY_RULE}' AND f.timeframe = '1d'
  AND m.source <> ALL($1::text[])
GROUP BY f.symbol, f."timestamp", f.detail, m.source
ORDER BY f.symbol, f."timestamp"
"""

RETIRE_LEGACY_FLAG_SQL = f"""
DELETE FROM bar_quality_flag
WHERE rule = '{LEGACY_RULE}' AND timeframe = '1d' AND symbol = $1 AND "timestamp" = $2
"""


def _rowcount(status: str) -> int:
    return int(status.rsplit(None, 1)[-1])


async def _lineage(
    conn: Any, names: list[str], *, apply: bool, batch_id: str | None, report: dict[str, Any]
) -> None:
    totals = {"n_symbols": len(names), "stored": 0, "needs_lineage": 0, "stale_d2": 0}
    unmatched: dict[str, list[str]] = {}
    lineage_rows = 0
    started = time.monotonic()
    for symbol in names:
        if not apply:
            row = await conn.fetchrow(LINEAGE_STATUS_SQL, symbol)
            gaps = [
                str(r["bar_date"]) for r in await conn.fetch(_TRADIER_LINEAGE_UNMATCHED_SQL, symbol)
            ]
            totals["stored"] += row["n_stored"]
            totals["needs_lineage"] += row["n_needs"]
            totals["stale_d2"] += row["n_stale_d2"]
            print(
                f"  {symbol}: stored {row['n_stored']} needs_lineage {row['n_needs']} "
                f"stale_d2 {row['n_stale_d2']} unmatched {len(gaps)}"
            )
        else:
            tx = conn.transaction()
            await tx.start()
            try:
                await conn.execute(_WRITER_ROLE_SQL)
                n = _rowcount(await conn.execute(TRADIER_LINEAGE_UPSERT_SQL, symbol, batch_id))
                gaps = [
                    str(r["bar_date"])
                    for r in await conn.fetch(_TRADIER_LINEAGE_UNMATCHED_SQL, symbol)
                ]
            except Exception as error:
                await tx.rollback()
                report["failures"].append(f"lineage {symbol}: {error}")
                continue
            # The matched bars' lineage commits; an unmatched bar has none and is reported.
            await tx.commit()
            lineage_rows += n
        if gaps:
            unmatched[symbol] = gaps
    totals["unmatched_bars"] = sum(len(v) for v in unmatched.values())
    if apply:
        totals["lineage_rows"] = lineage_rows
        totals["seconds"] = round(time.monotonic() - started, 1)
    totals["unmatched"] = unmatched
    report["lineage"] = totals
    print(
        f"lineage: symbols {totals['n_symbols']} stored {totals['stored']} "
        f"needs_lineage {totals['needs_lineage']} stale_d2 {totals['stale_d2']} "
        f"unmatched_bars {totals['unmatched_bars']}"
        + (f" lineage_rows {lineage_rows} seconds {totals['seconds']}" if apply else "")
    )
    for symbol, gaps in unmatched.items():
        print(f"  unmatched {symbol}: {len(gaps)} bar(s): {', '.join(gaps[:10])}")


async def _digest_one(conn: Any, symbol: str, rule_version: str, batch_id: str | None) -> int:
    if batch_id is not None:
        return await write_1d_digests(
            conn, symbol=symbol, batch_id=batch_id, rule_version=rule_version
        )
    # Dry run: the writer itself decides which months changed; its insert is rolled back.
    tx = conn.transaction()
    await tx.start()
    try:
        return await write_1d_digests(conn, symbol=symbol, batch_id=None, rule_version=rule_version)
    finally:
        await tx.rollback()


async def _digests(
    conn: Any,
    names: list[tuple[str, bool]],
    *,
    batch_id: str | None,
    report: dict[str, Any],
    key: str = "digests",
) -> None:
    owned_rows = owned_n = 0
    ibkr: dict[str, int] = {}
    for symbol, owned in names:
        rule_version = TRADIER_RULE_VERSION if owned else RULE_VERSION
        try:
            n = await _digest_one(conn, symbol, rule_version, batch_id)
        except Exception as error:
            report["failures"].append(f"digest {symbol}: {error}")
            continue
        if owned:
            owned_n += 1
            owned_rows += n
        else:
            ibkr[symbol] = n
    detail = {
        "tradier_owned": {
            "n_symbols": owned_n,
            "rows": owned_rows,
            "rule_version": TRADIER_RULE_VERSION,
        },
        "ibkr_owned": {
            "n_symbols": len(ibkr),
            "rows": sum(ibkr.values()),
            "rule_version": RULE_VERSION,
            "symbols": {s: n for s, n in ibkr.items() if n},
        },
    }
    report[key] = detail
    label = "stale_months" if batch_id is None else "rows_inserted"
    print(
        f"{key}: {len(names)} symbols, {label} {owned_rows + sum(ibkr.values())} "
        f"(tradier-owned {owned_rows} over {owned_n}, ibkr-owned {sum(ibkr.values())} over "
        f"{len(ibkr)}; ibkr names with changes {len(detail['ibkr_owned']['symbols'])})"
    )


async def _retire(
    conn: Any, *, apply: bool, batch_id: str | None, report: dict[str, Any]
) -> list[tuple[str, bool]]:
    """Retire the replaced 1d legacy flags; returns (symbol, owned) to re-digest."""
    tx = conn.transaction()
    await tx.start()
    retired: list[dict[str, Any]] = []
    try:
        rows = await conn.fetch(REPLACED_LEGACY_FLAGS_SQL, _IBKR_1D_SOURCES)
        for r in rows:
            retired.append(
                {
                    "symbol": r["symbol"],
                    "timestamp": r["timestamp"].isoformat(),
                    "detail": r["detail"],
                    "stored_source": r["stored_source"],
                    "replaced": r["replaced"],
                }
            )
            old = r["replaced"][0]
            print(
                f"  {r['symbol']} {r['timestamp'].date()}: stored {r['stored_source']}, "
                f"replaced {old['old_source']} close {old['old_close']}"
            )
        if apply:
            await conn.execute(_WRITER_ROLE_SQL)
            n_deleted = 0
            for r in rows:
                n_deleted += _rowcount(
                    await conn.execute(RETIRE_LEGACY_FLAG_SQL, r["symbol"], r["timestamp"])
                )
            if n_deleted != len(rows):
                raise RuntimeError(f"deleted {n_deleted} flags for {len(rows)} candidates")
            await tx.commit()
        else:
            await tx.rollback()
    except Exception as error:
        await tx.rollback()
        report["failures"].append(f"retire: {error}")
        return []
    report["retired_legacy_flags"] = retired
    print(f"legacy 1d flags {'retired' if apply else 'to retire'}: {len(retired)}")
    return sorted({(r["symbol"], bool(r["owned"])) for r in rows})


async def run(
    conn: Any,
    *,
    symbols: list[str] | None,
    lineage: bool,
    digests: bool,
    retire: bool,
    apply: bool,
) -> int:
    if not (lineage or digests or retire):
        lineage = True
    report: dict[str, Any] = {"plan": "185-30", "failures": []}
    batch_id: str | None = None
    status = "failed"
    try:
        lineage_names: list[str] = []
        digest_names: list[tuple[str, bool]] = []
        if lineage:
            lineage_names = symbols or [r["symbol"] for r in await conn.fetch(OWNED_SYMBOLS_SQL)]
        if digests:
            rows = await conn.fetch(CANONICAL_1D_SYMBOLS_SQL, list(CANONICAL_1D_SOURCES))
            digest_names = [(r["symbol"], bool(r["owned"])) for r in rows]
            if symbols:
                digest_names = [(s, o) for s, o in digest_names if s in set(symbols)]
        if apply:
            batch_id = await open_batch(
                conn,
                stage="tradier",
                rule_version=TRADIER_RULE_VERSION,
                apr_snapshot={},
                n_symbols=len(lineage_names) or len(digest_names) or None,
                detail={
                    "plan": "185-30",
                    "modes": [
                        m
                        for m, on in (
                            ("lineage", lineage),
                            ("digests", digests),
                            ("retire_replaced_legacy_flags", retire),
                        )
                        if on
                    ],
                },
            )
        if lineage:
            await _lineage(conn, lineage_names, apply=apply, batch_id=batch_id, report=report)
        if retire:
            redigest = await _retire(conn, apply=apply, batch_id=batch_id, report=report)
            if apply and redigest:
                await _digests(
                    conn, redigest, batch_id=batch_id, report=report, key="retire_redigest"
                )
        if digests:
            await _digests(conn, digest_names, batch_id=batch_id, report=report)
        unmatched = report.get("lineage", {}).get("unmatched_bars", 0)
        if report["failures"]:
            print(f"failures ({len(report['failures'])}): {report['failures'][:20]}")
        if not apply:
            print("dry run: nothing written (pass --apply)")
        failed = bool(report["failures"]) or unmatched > 0
        status = "failed" if failed else "completed"
        return 1 if failed else 0
    finally:
        if batch_id is not None:
            report["failures"] = report["failures"][:50]
            await close_batch(conn, batch_id, status=status, detail=report)


async def _main_async(args: argparse.Namespace) -> int:
    conn = await asyncpg.connect(get_settings().database_url)
    try:
        # A bare connection has no jsonb codec; the legacy read returns jsonb.
        await _setup_codecs(conn)
        symbols = (
            [s.strip() for s in args.symbols.split(",") if s.strip()] if args.symbols else None
        )
        return await run(
            conn,
            symbols=symbols,
            lineage=args.lineage,
            digests=args.digests,
            retire=args.retire_replaced_legacy_flags,
            apply=args.apply,
        )
    finally:
        await conn.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--symbols", help="comma-separated; default: every name the mode covers")
    parser.add_argument("--lineage", action="store_true", help="tradier-v1 lineage (the default)")
    parser.add_argument("--digests", action="store_true", help="1d digests, every canonical name")
    parser.add_argument(
        "--retire-replaced-legacy-flags",
        action="store_true",
        help="retire 1d legacy price-sanity flags on bars a non-IBKR source replaced",
    )
    parser.add_argument("--apply", action="store_true", help="write (default: dry run)")
    return asyncio.run(_main_async(parser.parse_args(argv)))


if __name__ == "__main__":
    sys.exit(main())
