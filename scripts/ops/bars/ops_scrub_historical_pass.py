#!/usr/bin/env python3
"""Historical D2a scrub pass (phase 185 plan 10; D-08, D-09, D-12).

Runs services/bar_scrub.py's scrub_symbols over the whole stored history of one
timeframe: every D2a rule at 1d, the D-14 ports at intraday (return_magnitude,
gap_before_next). Default is a DRY RUN -- compute and print per-rule counts and
the quarantine keys, write nothing. --apply opens one bar_derivation_batch
provenance row (stage 'scrub', the APR snapshot it ran under), replaces the
flags under the bar_derivation_writer role, emits one integrity fact per rule
count plus 'historical_pass_complete', and closes the batch completed/failed.

Safety: the pass only ever writes bar_quality_flag and bar_derivation_batch;
market_data_ohlcv rows are never modified or deleted (D-09), and every read
comes from market_data_ohlcv_scrub_input through the library.

Usage:
    .venv/bin/python scripts/ops/bars/ops_scrub_historical_pass.py --tf 1d
    .venv/bin/python scripts/ops/bars/ops_scrub_historical_pass.py --tf 1d --apply
    .venv/bin/python scripts/ops/bars/ops_scrub_historical_pass.py --tf 5m --apply
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

import asyncpg
import structlog

from services._batch_utils import load_apr_dict_async
from services.bar_derivation_batch import close_batch, open_batch
from services.bar_scrub import discover_scrub_symbols, scrub_symbols
from src.config.settings import Settings
from src.core.integrity_monitor import emit_integrity_fact_async
from src.core.service_utils import setup_service_logging
from src.intelligence.bars.scrub_rules import RULE_VERSION
from src.observability.metrics import JOB_COMPLETED_TOTAL, flush_and_shutdown_metrics
from src.observability.otel import OTelInitError, init_otel_providers

setup_service_logging("logs/scrub_historical_pass.log")
_logger = structlog.get_logger(__name__)

_JOB = "scrub-historical-pass"
_MONITOR_TYPE = "bar_scrub"
_TFS = ("1d", "5m", "15m", "1h")
_SNAPSHOT_PREFIXES = ("threshold.bar_scrub.", "alpha.quant.", "alpha.forward_returns.")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--tf",
        choices=_TFS,
        required=True,
        help="Timeframe to scrub (1d: every rule; intraday: D-14 ports).",
    )
    parser.add_argument(
        "--symbols", nargs="*", default=None, help="Restrict the pass to these symbols."
    )
    parser.add_argument(
        "--limit-symbols",
        type=int,
        default=None,
        help="Scrub only the first N symbols (after sorting); smoke runs.",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        default=False,
        help="Write flags, the provenance batch and integrity facts. DEFAULT IS DRY "
        "RUN (compute and print counts, zero DB writes).",
    )
    return parser.parse_args()


def _render_report(
    tf: str,
    counts: dict[str, int],
    quarantine_keys: list[tuple[str, str, object]],
    elapsed_s: float,
    apply: bool,
) -> str:
    lines = [
        f"# D2a historical scrub pass -- tf={tf} ({'APPLY' if apply else 'DRY RUN'})",
        "",
        f"symbols rule counts (flags {'written' if apply else 'computed'}):",
        "",
        "| rule | flags |",
        "|---|---|",
    ]
    lines.extend(f"| {rule} | {counts[rule]} |" for rule in sorted(counts))
    lines.append("")
    lines.append(f"total: {sum(counts.values())}   wall: {elapsed_s:.1f}s")
    lines.append("")
    lines.append(f"quarantine keys ({len(quarantine_keys)}):")
    lines.extend(f"  {rule} {symbol} {ts.isoformat()}" for rule, symbol, ts in quarantine_keys)
    if not apply:
        lines.append("")
        lines.append(
            "DRY-RUN MODE (default) -- zero DB writes made. Pass --apply after "
            "reviewing the counts and quarantine keys above."
        )
    return "\n".join(lines)


async def _run(args: argparse.Namespace) -> int:
    settings = Settings()
    dsn = settings.database_url.replace("postgresql+asyncpg://", "postgresql://")
    pool = await asyncpg.create_pool(dsn=dsn)
    try:
        async with pool.acquire() as conn:
            apr = await load_apr_dict_async(conn, ["threshold.bar_scrub.%"])
            snapshot = {
                key: value
                for key, value in sorted(apr.items())
                if key.startswith(_SNAPSHOT_PREFIXES)
            }
            symbols = (
                list(args.symbols) if args.symbols else await discover_scrub_symbols(conn, args.tf)
            )
        if args.limit_symbols is not None:
            symbols = symbols[: args.limit_symbols]
        _logger.info(
            "scrub_historical_pass.start",
            tf=args.tf,
            symbols=len(symbols),
            apply=args.apply,
        )

        batch_id = ""
        if args.apply:
            async with pool.acquire() as conn:
                batch_id = await open_batch(
                    conn,
                    stage="scrub",
                    rule_version=RULE_VERSION,
                    apr_snapshot=snapshot,
                    n_symbols=len(symbols),
                    detail={"tf": args.tf, "apply": True},
                )

        quarantine_keys: list[tuple[str, str, object]] = []
        t0 = time.monotonic()
        try:
            counts = await scrub_symbols(
                pool,
                tf=args.tf,
                symbols=symbols,
                rules=None,
                start=None,
                end=None,
                batch_id=batch_id,
                write=args.apply,
                prune_stale=args.apply,
                quarantine_key_sink=quarantine_keys,
            )
        except Exception as error:
            if args.apply:
                async with pool.acquire() as conn:
                    await close_batch(conn, batch_id, status="failed", detail={"error": str(error)})
            raise
        elapsed_s = time.monotonic() - t0

        if args.apply:
            async with pool.acquire() as conn:
                for rule in sorted(counts):
                    await emit_integrity_fact_async(
                        conn,
                        _MONITOR_TYPE,
                        f"tf={args.tf}",
                        rule,
                        float(counts[rule]),
                        None,
                        True,
                        None,
                    )
                await emit_integrity_fact_async(
                    conn,
                    _MONITOR_TYPE,
                    f"tf={args.tf}",
                    "historical_pass_complete",
                    1.0,
                    None,
                    True,
                    None,
                )
                await close_batch(
                    conn,
                    batch_id,
                    status="completed",
                    detail={
                        "tf": args.tf,
                        "counts": counts,
                        "symbols": len(symbols),
                        "elapsed_s": round(elapsed_s, 3),
                    },
                )

        print(_render_report(args.tf, counts, quarantine_keys, elapsed_s, args.apply))  # noqa: T201
        return 0
    finally:
        await pool.close()


def main() -> None:
    args = _parse_args()
    try:
        init_otel_providers(service_name=f"indicagent-{_JOB}")
    except OTelInitError as error:
        _logger.warning("scrub_historical_pass.otel_init_failed", error=str(error))

    status = "success"
    try:
        exit_code = asyncio.run(_run(args))
    except Exception as error:
        status = "failure"
        _logger.error("scrub_historical_pass.failed", tf=args.tf, error=str(error))
        exit_code = 1
    finally:
        JOB_COMPLETED_TOTAL.add(1, {"job": _JOB, "status": status})
        flush_and_shutdown_metrics()
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
