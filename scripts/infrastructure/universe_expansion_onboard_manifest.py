#!/usr/bin/env python3
"""
universe_expansion_onboard_manifest.py -- onboard a reviewed manifest of equity instruments

Reads a manifest CSV (columns symbol, name, code, source_ref, tags, cohort, issuer,
underlying_index, description, ibkr_symbol; tags ';'-separated; ibkr_symbol set only for a
share class IBKR spells with a space, e.g. BRK.B -> "BRK B") and onboards every row through
onboard_instrument(), the single sanctioned write path.

Two phases, so no database transaction is open while IBKR is being called (todo 431):

1. Qualify. Every symbol is qualified against IBKR outside any transaction. A known-good
   probe symbol is qualified before and after the loop; if either probe fails the gateway
   dropped (the weekly 2FA logout, todo 395) and the run aborts before writing anything,
   instead of recording every remaining symbol as a rejection.
2. Write. One short transaction onboards the qualified set, all or nothing: any rejection
   (an existing symbol, an unknown classification code or tag) rolls back the whole batch.
   The qualifier handed to onboard_instrument answers from phase 1's results and makes no
   network call. The dry run stops after phase 1, so it does not exercise those checks.

Symbols IBKR does not resolve (delisted or taken private since the holdings snapshot) are
listed in the summary and not written. Every row is onboarded with compute_eligible and
compute_eligible_1d false; universe_expansion_promote_compute_eligible.py promotes them after
their backfill lands.

Usage:
    .venv/bin/python scripts/infrastructure/universe_expansion_onboard_manifest.py \\
        --manifest config/universe/expansion_2026_09_26.csv --timeframes 1d [--commit]
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import structlog

project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from scripts.infrastructure._write_mode_args import add_write_mode_args  # noqa: E402
from src.config.classification_service import ClassificationAssignment  # noqa: E402
from src.config.instrument_onboarding import (  # noqa: E402
    OnboardingRejected,
    onboard_instrument,
)
from src.config.settings import Settings  # noqa: E402
from src.core.database_manager import DatabaseManager  # noqa: E402
from src.core.models import AssetClass, Instrument  # noqa: E402
from src.observability.metrics import JOB_COMPLETED_TOTAL, flush_and_shutdown_metrics  # noqa: E402
from src.providers.ibkr import IBKRProvider  # noqa: E402

_logger = structlog.get_logger(__name__)

# Shares 46 with universe_expansion_onboard_gap_fill_etfs.py: both are operator-run one-offs
# that qualify contracts, never run concurrently (src/providers/ibkr.py _MAX_CLIENT_ID=50).
_QUALIFIER_CLIENT_ID = 46

# A long-listed equity ETF that must always qualify; its failure means the gateway, not the
# manifest, is at fault.
_PROBE_SYMBOL = "SPY"

_MANIFEST_COLUMNS = (
    "symbol",
    "name",
    "code",
    "source_ref",
    "tags",
    "cohort",
    "issuer",
    "underlying_index",
    "description",
    "ibkr_symbol",
)


@dataclass(frozen=True)
class ManifestRow:
    symbol: str
    name: str
    classification: ClassificationAssignment
    tags: tuple[str, ...]
    cohort: str
    metadata: dict[str, Any] | None
    ibkr_symbol: str = ""


def load_manifest(path: Path) -> list[ManifestRow]:
    """Parse and validate the manifest. Raises ValueError on a missing column, a duplicate
    symbol, an empty tag list or a bad source_ref, before any IBKR or database call."""
    with path.open(newline="") as fh:
        reader = csv.DictReader(fh)
        missing = set(_MANIFEST_COLUMNS) - set(reader.fieldnames or ())
        if missing:
            raise ValueError(f"{path}: missing manifest columns {sorted(missing)}")
        rows: list[ManifestRow] = []
        seen: set[str] = set()
        for raw in reader:
            symbol = raw["symbol"].strip()
            if not symbol or symbol in seen:
                raise ValueError(f"{path}: empty or duplicate symbol {symbol!r}")
            seen.add(symbol)
            tags = tuple(t.strip() for t in raw["tags"].split(";") if t.strip())
            if not tags:
                raise ValueError(f"{path}: {symbol} has no tags")
            has_fund_metadata = bool(raw["issuer"].strip())
            rows.append(
                ManifestRow(
                    symbol=symbol,
                    name=raw["name"].strip(),
                    classification=ClassificationAssignment(
                        code=raw["code"].strip(), source_ref=raw["source_ref"].strip()
                    ),
                    tags=tags,
                    cohort=raw["cohort"].strip(),
                    metadata=(
                        {
                            "listing_date": None,
                            "underlying_index": raw["underlying_index"].strip() or None,
                            "issuer": raw["issuer"].strip(),
                            "description": raw["description"].strip() or None,
                        }
                        if has_fund_metadata
                        else None
                    ),
                    ibkr_symbol=raw["ibkr_symbol"].strip(),
                )
            )
    return rows


def build_instrument(row: ManifestRow) -> Instrument:
    return Instrument(
        symbol=row.symbol,
        base=row.symbol,
        name=row.name,
        asset_class=AssetClass.EQUITY,
        exchange="SMART",
        sector="",
        tick_size=0.01,
        session_id="nyse",
        point_value=1.0,
        provider_meta={"ibkr": {"symbol": row.ibkr_symbol}} if row.ibkr_symbol else {},
    )


class _PreQualified:
    """InstrumentQualifier that answers from phase 1's results, so the write transaction
    never waits on IBKR."""

    def __init__(self, qualified: set[str]) -> None:
        self._qualified = qualified

    async def qualify_instrument(self, instrument: Any, **_kwargs: Any) -> bool:
        return instrument.symbol in self._qualified


async def qualify_all(qualifier: Any, rows: list[ManifestRow]) -> tuple[set[str], list[str]]:
    """Phase 1: qualify every row, bracketed by probe checks. Returns (qualified, rejected).
    Raises RuntimeError if either probe fails, since then a rejection says nothing about the
    symbol."""
    probe = Instrument(
        symbol=_PROBE_SYMBOL,
        base=_PROBE_SYMBOL,
        asset_class=AssetClass.EQUITY,
        exchange="SMART",
        session_id="nyse",
    )
    if not await qualifier.qualify_instrument(probe):
        raise RuntimeError(f"gateway probe {_PROBE_SYMBOL} failed before qualification")
    qualified: set[str] = set()
    rejected: list[str] = []
    for row in rows:
        if await qualifier.qualify_instrument(build_instrument(row)):
            qualified.add(row.symbol)
        else:
            rejected.append(row.symbol)
    if not await qualifier.qualify_instrument(probe):
        raise RuntimeError(
            f"gateway probe {_PROBE_SYMBOL} failed after qualification; rejections "
            f"({len(rejected)}) are untrustworthy, nothing written"
        )
    return qualified, rejected


async def write_all(
    conn: Any, rows: list[ManifestRow], qualified: set[str], timeframes: tuple[str, ...]
) -> list[str]:
    """Phase 2: onboard every qualified row inside one transaction. Returns onboarded symbols.
    Any failure, including OnboardingRejected, rolls back the whole batch."""
    qualifier = _PreQualified(qualified)
    onboarded: list[str] = []
    async with conn.transaction():
        for row in rows:
            if row.symbol not in qualified:
                continue
            await onboard_instrument(
                conn,
                build_instrument(row),
                qualifier=qualifier,
                tags=[
                    (tag, 1.0, {"reason": f"universe expansion 2026-09-26, {row.cohort}"})
                    for tag in row.tags
                ],
                timeframes=timeframes,
                metadata=row.metadata,
                metadata_skip_reason=(
                    "" if row.metadata else "single-name equity: no issuer/index metadata applies"
                ),
                classification=row.classification,
            )
            onboarded.append(row.symbol)
    return onboarded


async def _async_main(args: argparse.Namespace) -> int:
    rows = load_manifest(args.manifest)
    timeframes = tuple(tf.strip() for tf in args.timeframes.split(",") if tf.strip())
    if not timeframes or len(set(timeframes)) != len(timeframes):
        # A duplicate makes the promotion predicate's count(*) = cardinality(...) unsatisfiable.
        raise ValueError(f"--timeframes must be non-empty with no repeats, got {args.timeframes!r}")
    settings = Settings()

    provider = IBKRProvider(
        host=settings.ib_host, port=settings.ib_port, client_id=_QUALIFIER_CLIENT_ID
    )
    if not await provider.connect():
        raise RuntimeError("could not connect to ib-gateway")
    try:
        qualified, rejected = await qualify_all(provider, rows)
    finally:
        await provider.disconnect()

    print(f"qualified {len(qualified)}/{len(rows)}; rejected: {rejected or 'none'}")
    if not args.commit:
        print("dry run: no database writes")
        return 0

    db = DatabaseManager(settings.database_url)
    await db.initialize()
    try:
        async with db.pool.acquire() as conn:
            onboarded = await write_all(conn, rows, qualified, timeframes)
    finally:
        await db.close()
    _logger.info(
        "universe_expansion_onboard_manifest.complete",
        manifest=str(args.manifest),
        n_rows=len(rows),
        n_onboarded=len(onboarded),
        rejected=rejected,
        timeframes=list(timeframes),
    )
    print(f"onboarded {len(onboarded)}; rejected {len(rejected)}: {rejected or 'none'}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Onboard a reviewed instrument manifest.")
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument(
        "--timeframes",
        required=True,
        help="Comma-separated timeframes seeded into backfill_status (e.g. 1d).",
    )
    add_write_mode_args(
        parser,
        dry_run="Dry run (default): qualify every symbol, write nothing.",
        commit="Qualify, then onboard the qualified set in one transaction.",
    )
    args = parser.parse_args(argv)

    status = "success"
    try:
        return asyncio.run(_async_main(args))
    except OnboardingRejected as error:
        status = "failure"
        print(f"FAILED (batch rolled back): {error}", file=sys.stderr)
        return 1
    except Exception as error:
        status = "failure"
        _logger.error("universe_expansion_onboard_manifest.failed", error=str(error))
        print(f"FAILED: {error}", file=sys.stderr)
        return 1
    finally:
        JOB_COMPLETED_TOTAL.add(1, {"job": "universe-expansion-onboard-manifest", "status": status})
        flush_and_shutdown_metrics()


if __name__ == "__main__":
    from src.observability.otel import OTelInitError, init_otel_providers

    try:
        init_otel_providers("universe-expansion-onboard-manifest")
    except OTelInitError as error:
        print(f"[warn] OTel init failed -- metrics disabled: {error}")
    sys.exit(main())
