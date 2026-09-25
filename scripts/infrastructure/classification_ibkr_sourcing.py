#!/usr/bin/env python3
"""
classification_ibkr_sourcing.py -- IBKR classification candidate sourcing (Phase 182, D-06)

Fetches IBKR ContractDetails.industry/.category/.subcategory/.longName for every
instrument currently tagged `single_name_equity`, via
IBKRProvider.fetch_contract_classification() (src/providers/ibkr.py, the sole
ib_async file -- Ring rule). Writes a candidate CSV for human review.

This script is read-only against the database (it only queries instrument_tags to
build the symbol list) and never writes a classification decision -- it produces
review input for Plan 03's indicagent_v1 node mapping. Safe to rerun: exits non-zero
and writes no file on a DB/gateway failure (RESEARCH.md Pitfall 4 -- no stale reuse,
every successful run's rows carry this run's own fetched_at).
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

import psycopg
import structlog

# sys.path bootstrap: this file is scripts/infrastructure/<this file>.py -- 3 parents
# reach repo root (infrastructure/ -> scripts/ -> root), matching the sibling
# universe_expansion_stratified_sourcing.py convention.
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from src.config.settings import Settings  # noqa: E402
from src.core.service_utils import format_iso_ts  # noqa: E402
from src.observability.metrics import JOB_COMPLETED_TOTAL, flush_and_shutdown_metrics  # noqa: E402
from src.providers.ibkr import IBKRProvider  # noqa: E402

_logger = structlog.get_logger(__name__)

_DEFAULT_OUT = "config/classification/ibkr_classification_candidates.csv"
# Client ID 47: free at plan time (35=provider, 40/45=backfill, 44/46/48/50 claimed
# by other scripts, see src/providers/ibkr.py's _MAX_CLIENT_ID=50 ceiling).
_DEFAULT_CLIENT_ID = 47

_CSV_COLUMNS = [
    "symbol",
    "industry",
    "category",
    "subcategory",
    "long_name",
    "status",
    "detail",
    "fetched_at",
]


def _fetch_single_name_equity_symbols(settings: Settings) -> list[str]:
    """Every symbol currently tagged single_name_equity, ordered by symbol.

    Active or not -- includes the 40 unlabeled 1d-pilot names (RESEARCH.md
    Pitfall 4). Raises RuntimeError (exit 3 at the call site) if the query
    returns zero rows -- an empty result means the instrument_tags table is
    unreachable or the tag itself has drifted, not that there are genuinely
    no single names.
    """
    dsn = settings.database_url.replace("postgresql+asyncpg://", "postgresql://")
    with psycopg.connect(dsn) as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT DISTINCT symbol FROM instrument_tags "
            "WHERE tag = 'single_name_equity' ORDER BY symbol"
        )
        rows = cur.fetchall()
    return [row[0] for row in rows]


async def _source_candidates(
    symbols: list[str], settings: Settings, client_id: int
) -> tuple[list[dict], dict[str, int]]:
    """Fetch classification candidates for every symbol, sequentially.

    Never aborts the loop on a single symbol's failure -- every failure mode
    (no details, ambiguous listing, timeout, other error) is recorded as a row
    status instead. Counts are accumulated and logged once at the end (no
    per-row logging, CLAUDE.md).
    """
    provider = IBKRProvider(host=settings.ib_host, port=settings.ib_port, client_id=client_id)
    connected = await provider.connect()
    if not connected:
        raise ConnectionError(
            "classification_ibkr_sourcing: ib-gateway connection failed "
            f"(127.0.0.1:{settings.ib_port}, client_id={client_id}). Check the "
            "gateway container is up and logged in: `docker ps --filter "
            "name=ib-gateway`. The weekly 2FA logout (todo 395) is the most common "
            "cause. This script writes no file when the gateway is unreachable -- "
            "safe to rerun once the gateway is back: `.venv/bin/python "
            "scripts/infrastructure/classification_ibkr_sourcing.py`."
        )

    rows: list[dict] = []
    try:
        for symbol in symbols:
            fetched_at = format_iso_ts(datetime.now(UTC))
            try:
                result = await provider.fetch_contract_classification(symbol)
            except TimeoutError as error:
                rows.append(_row(symbol, "timeout", fetched_at, detail=str(error)))
                continue
            except ValueError as error:
                rows.append(_row(symbol, "ambiguous", fetched_at, detail=str(error)))
                continue
            except Exception as error:  # noqa: BLE001 -- recorded per-symbol, loop continues
                rows.append(_row(symbol, "error", fetched_at, detail=str(error)))
                continue
            if result is None:
                rows.append(_row(symbol, "no_details", fetched_at))
                continue
            rows.append(
                # "ok" needs both fields the review maps from; a half-empty triple is not ready.
                _row(
                    symbol,
                    "ok" if result.industry and result.category else "empty",
                    fetched_at,
                    result=result,
                )
            )
    finally:
        await provider.disconnect()

    counts = dict.fromkeys(_STATUSES, 0)
    for row in rows:
        counts[row["status"]] += 1
    return rows, counts


_STATUSES = ("ok", "empty", "no_details", "ambiguous", "timeout", "error")


def _row(symbol: str, status: str, fetched_at: str, *, detail: str = "", result=None) -> dict:
    """One candidates-CSV row; the IBKR fields are empty unless a result was fetched."""
    return {
        "symbol": symbol,
        "industry": result.industry if result else "",
        "category": result.category if result else "",
        "subcategory": result.subcategory if result else "",
        "long_name": result.long_name if result else "",
        "status": status,
        "detail": detail,
        "fetched_at": fetched_at,
    }


def _write_csv_atomic(out_path: Path, rows: list[dict]) -> None:
    """Write rows to a temp file in the same directory, then os.replace -- a crash
    mid-write never leaves a partial candidates file on disk."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = out_path.with_suffix(out_path.suffix + ".tmp")
    with tmp_path.open("w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=_CSV_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)
    os.replace(tmp_path, out_path)


async def _async_main(args: argparse.Namespace) -> int:
    settings = Settings()

    symbols = _fetch_single_name_equity_symbols(settings)
    if not symbols:
        print(
            "FAILED: classification_ibkr_sourcing: 0 rows for "
            "tag='single_name_equity' in instrument_tags -- DB unreachable or the "
            "tag has drifted. No file written.",
            file=sys.stderr,
        )
        return 3

    try:
        rows, counts = await _source_candidates(symbols, settings, args.client_id)
    except ConnectionError as error:
        print(f"FAILED: {error}", file=sys.stderr)
        return 4

    non_ok = [row["symbol"] for row in rows if row["status"] != "ok"]
    out_path = Path(args.out)
    if non_ok and out_path.exists():
        # A gateway logout mid-run turns most rows into errors; never replace a complete
        # candidates file with that. The partial result goes beside it for inspection.
        out_path = out_path.with_suffix(".partial" + out_path.suffix)
        print(
            f"WARNING: {len(non_ok)} non-ok rows; {args.out} left unchanged, this run written "
            f"to {out_path}.",
            file=sys.stderr,
        )
    _write_csv_atomic(out_path, rows)
    _logger.info(
        "classification_ibkr_sourcing.complete",
        total=len(rows),
        ok=counts["ok"],
        empty=counts["empty"],
        no_details=counts["no_details"],
        ambiguous=counts["ambiguous"],
        timeout=counts["timeout"],
        error=counts["error"],
        out=str(out_path),
    )
    if non_ok:
        print(
            f"WARNING: {len(non_ok)}/{len(rows)} symbols non-ok: {', '.join(non_ok)}",
            file=sys.stderr,
        )
        return 2
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Source fresh IBKR industry/category/subcategory/longName candidates "
            "for every single_name_equity-tagged instrument (Phase 182, D-06)."
        )
    )
    parser.add_argument(
        "--out",
        default=_DEFAULT_OUT,
        help=f"Output CSV path (default: {_DEFAULT_OUT}).",
    )
    parser.add_argument(
        "--client-id",
        type=int,
        default=_DEFAULT_CLIENT_ID,
        help=f"IBKR client ID (default: {_DEFAULT_CLIENT_ID}).",
    )
    args = parser.parse_args(argv)

    status = "success"
    return_code = 1
    try:
        return_code = asyncio.run(_async_main(args))
        if return_code != 0:
            status = "failure"
    except Exception as error:
        status = "failure"
        _logger.error("classification_ibkr_sourcing.failed", error=str(error))
        print(f"FAILED: {error}", file=sys.stderr)
        return_code = 1
    finally:
        JOB_COMPLETED_TOTAL.add(1, {"job": "classification-ibkr-sourcing", "status": status})
        flush_and_shutdown_metrics()
    return return_code


if __name__ == "__main__":
    from src.observability.otel import OTelInitError, init_otel_providers

    try:
        init_otel_providers("classification-ibkr-sourcing")
    except OTelInitError as error:
        print(f"[warn] OTel init failed -- metrics disabled: {error}")
    sys.exit(main())
