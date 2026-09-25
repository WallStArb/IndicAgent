#!/usr/bin/env python3
"""
universe_expansion_onboard_gap_fill_etfs.py -- onboard EMLC and VIXY (Phase 174, Plan 10)

Small, re-runnable one-off that onboards exactly the two tickers Plan 07 selected to
close the corpus's two genuinely-empty exposure gaps: EM currency (EMLC) and equity-index
implied volatility (VIXY). All contract_details / instrument_metadata / tag values below
are taken verbatim from docs/research/phase174-etf-gap-fill-ticker-selection.md -- this
script does no re-research or re-decision, it only writes what Plan 07 already decided.

Both symbols are onboarded with compute_eligible=False, live_tradeable=False. Task 3 of
this plan promotes compute_eligible only after their backfill has actually landed (D-05/
D-06) -- this script provides no path to set either flag True.

Usage:
    .venv/bin/python scripts/infrastructure/universe_expansion_onboard_gap_fill_etfs.py
    .venv/bin/python scripts/infrastructure/universe_expansion_onboard_gap_fill_etfs.py --commit
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import date
from pathlib import Path

import structlog

# sys.path bootstrap: this file is scripts/infrastructure/<this file>.py -- 3 parents
# reach repo root (infrastructure/ -> scripts/ -> root), matching
# universe_expansion_stratified_sourcing.py's own header comment.
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from scripts.infrastructure._write_mode_args import add_write_mode_args  # noqa: E402
from src.config.classification_service import (  # noqa: E402
    SOURCE_REF_FUND_MANDATE,
    ClassificationAssignment,
)
from src.config.instrument_onboarding import (  # noqa: E402
    OnboardingRejected,
    OnboardResult,
    load_compute_timeframes,
    onboard_instrument,
)
from src.config.settings import Settings  # noqa: E402
from src.core.database_manager import DatabaseManager  # noqa: E402
from src.core.models import AssetClass, Instrument  # noqa: E402
from src.observability.metrics import JOB_COMPLETED_TOTAL, flush_and_shutdown_metrics  # noqa: E402
from src.providers.ibkr import IBKRProvider  # noqa: E402

_logger = structlog.get_logger(__name__)

# Dedicated client ID, distinct from other in-repo IBKR client IDs (35=provider, 40=default
# backfill, 44=chunk/rate-limit probe, 45=stratified-sourcing gateway probe, 48=personal_cost_
# hurdle) -- see src/providers/ibkr.py's _MAX_CLIENT_ID=50 ceiling.
_QUALIFIER_CLIENT_ID = 46

# Deterministic: the session_id most equity rows carry, ties broken by name. A bare
# LIMIT 1 with no ORDER BY returned whichever row the planner reached first, so a mixed
# session table could hand the ETFs a different calendar run to run (174 review IN-04).
_SESSION_ID_LOOKUP_SQL = """
SELECT contract_details->>'session_id' AS session_id FROM instruments
WHERE contract_details->>'asset_class' = 'equity' AND contract_details->>'session_id' IS NOT NULL
GROUP BY session_id
ORDER BY count(*) DESC, session_id
LIMIT 1
"""

# docs/research/phase174-etf-gap-fill-ticker-selection.md -- ten-key contract_details values
# (session_id is looked up live below, not hardcoded here, per the plan's instruction to read
# it from an existing equity ETF row rather than guessing).
_EMLC_CONTRACT = {
    "name": "VanEck J.P. Morgan EM Local Currency Bond ETF",
    "exchange": "SMART",
    "sector": "em_fx_bond",
    "tick_size": 0.01,
    "point_value": 1.0,
    "provider_meta": {},
}
_EMLC_METADATA = {
    "listing_date": date(2010, 7, 22),
    "underlying_index": "J.P. Morgan GBI-EM Global Core Index (GBIEMCOR)",
    "issuer": "VanEck",
    "description": (
        "Tracks the J.P. Morgan GBI-EM Global Core Index, providing exposure to "
        "local-currency-denominated emerging-market sovereign bonds. Primary use in this "
        "corpus is EM currency exposure; carries EM sovereign credit risk and "
        "interest-rate duration on top of that currency exposure -- see the EM-FX section "
        "of docs/research/phase174-etf-gap-fill-ticker-selection.md for the "
        "residualization note."
    ),
}
_EMLC_TAG_EVIDENCE = {
    "reason": (
        "Phase 174 D-06 EM-FX exposure gap fill; selected over CEW per "
        "docs/research/phase174-etf-gap-fill-ticker-selection.md -- EMLC trades roughly "
        "400-500x CEW's share volume on every window measured (20/65/50-day and "
        "same-session partial volume), live-verified 2026-09-15."
    ),
    "caveat": (
        "EMLC is not a currency-only instrument -- it holds EM sovereign local-currency "
        "bonds, so its return series carries EM sovereign credit risk and interest-rate "
        "duration on top of the currency exposure a purer instrument (CEW) would have "
        "offered. This contamination is real but removable: the corpus already carries "
        "duration exposure (TLT/IEF/SHY) and credit exposure elsewhere, so a "
        "common-factor control can residualize EMLC's credit/duration component out when "
        "a downstream consumer wants a clean currency read. Do not treat this tag as "
        "implying a clean, credit-free FX signal."
    ),
}

# Phase 182 (D-09, todo 384) -- indicagent_v1 codes pinned by Plan 03's reviewed seed
# (production/migrations/365_indicagent_v1_classification_seed.sql, shape-tested).
_EMLC_CLASSIFICATION = ClassificationAssignment("FI.EM", SOURCE_REF_FUND_MANDATE)
_VIXY_CLASSIFICATION = ClassificationAssignment("VOL.EQUITY", SOURCE_REF_FUND_MANDATE)

_VIXY_CONTRACT = {
    "name": "ProShares VIX Short-Term Futures ETF",
    "exchange": "SMART",
    "sector": "volatility_proxy",
    "tick_size": 0.01,
    "point_value": 1.0,
    "provider_meta": {},
}
_VIXY_METADATA = {
    "listing_date": date(2011, 1, 3),
    "underlying_index": "S&P 500 VIX Short-Term Futures Index",
    "issuer": "ProShares",
    "description": (
        "Holds a rolling position in near-term VIX futures, tracking the S&P 500 VIX "
        "Short-Term Futures Index. Primary use in this corpus is equity-index "
        "implied-volatility exposure. Selected over VXX (iPath Series B S&P 500 VIX "
        "Short-Term Futures ETN) because VXX is an ETN whose issuer halted new-share "
        "creation in March 2022, producing a persistent post-halt structural "
        "discontinuity in its price series -- see the vol-proxy section of "
        "docs/research/phase174-etf-gap-fill-ticker-selection.md."
    ),
}
_VIXY_TAG_EVIDENCE = {
    "reason": (
        "Phase 174 D-06 volatility-proxy exposure gap fill; selected over VXX per "
        "docs/research/phase174-etf-gap-fill-ticker-selection.md."
    ),
    "caveat": (
        "VXX (rejected) is an ETN -- an unsecured debt obligation of Barclays Bank plc, "
        "not a fund -- whose issuer halted new-share creation in March 2022 after the "
        "notes approached their SEC registration ceiling. With issuance closed, the "
        "mechanism that normally arbitrages an ETN back toward fair value is gone, "
        "producing a persistent post-halt structural discontinuity landing inside this "
        "corpus's measurement window. VIXY carries no equivalent risk: it is a real ETF "
        "(owns VIX futures directly) with normal creation/redemption throughout, despite "
        "VXX's measurably deeper volume (roughly 2-3x VIXY's on every window checked)."
    ),
}


async def _lookup_session_id(db: DatabaseManager) -> str:
    """Read session_id from an existing equity ETF row rather than guessing it."""
    async with db.pool.acquire() as conn:
        row = await conn.fetchrow(_SESSION_ID_LOOKUP_SQL)
    if row is None or not row[0]:
        raise RuntimeError(
            "universe_expansion_onboard_gap_fill_etfs: no existing equity instrument "
            "with a session_id found in instruments -- cannot derive session_id for "
            "EMLC/VIXY without guessing."
        )
    return row[0]


def _build_instrument(symbol: str, contract: dict, session_id: str) -> Instrument:
    return Instrument(
        symbol=symbol,
        base=symbol,
        name=contract["name"],
        asset_class=AssetClass.EQUITY,
        exchange=contract["exchange"],
        sector=contract["sector"],
        tick_size=contract["tick_size"],
        session_id=session_id,
        point_value=contract["point_value"],
        provider_meta=contract["provider_meta"],
    )


async def _run_commit(settings: Settings) -> list[OnboardResult]:
    db = DatabaseManager(settings.database_url)
    await db.initialize()

    provider = IBKRProvider(
        host=settings.ib_host, port=settings.ib_port, client_id=_QUALIFIER_CLIENT_ID
    )
    connected = await provider.connect()
    if not connected:
        await db.close()
        raise RuntimeError(
            "universe_expansion_onboard_gap_fill_etfs: could not connect to ib-gateway "
            "at 127.0.0.1:7497 -- Task 1 of this plan must prove the gateway serves "
            "data before this script runs in --commit mode."
        )

    results: list[OnboardResult] = []
    try:
        session_id = await _lookup_session_id(db)

        emlc = _build_instrument("EMLC", _EMLC_CONTRACT, session_id)
        vixy = _build_instrument("VIXY", _VIXY_CONTRACT, session_id)

        async with db.pool.acquire() as conn, conn.transaction():
            timeframes = await load_compute_timeframes(conn)  # once per run
            for instrument, tag_name, tag_evidence, metadata, classification in (
                (emlc, "fx_em", _EMLC_TAG_EVIDENCE, _EMLC_METADATA, _EMLC_CLASSIFICATION),
                (vixy, "vol_proxy", _VIXY_TAG_EVIDENCE, _VIXY_METADATA, _VIXY_CLASSIFICATION),
            ):
                try:
                    result = await onboard_instrument(
                        conn,
                        instrument,
                        qualifier=provider,
                        tags=((tag_name, 1.0, tag_evidence),),
                        timeframes=timeframes,
                        metadata=metadata,
                        classification=classification,
                        compute_eligible=False,
                        live_tradeable=False,
                    )
                    results.append(result)
                except OnboardingRejected as error:
                    _logger.error(
                        "universe_expansion_onboard_gap_fill_etfs.rejected",
                        symbol=instrument.symbol,
                        error=str(error),
                    )
                    raise
    finally:
        await provider.disconnect()
        await db.close()

    return results


async def _async_main(args: argparse.Namespace) -> int:
    settings = Settings()

    if not args.commit:
        print(
            "Dry run -- would onboard EMLC (fx_em) and VIXY (vol_proxy) via "
            "onboard_instrument(), compute_eligible=False, live_tradeable=False. "
            "No database writes, no IBKR connection made. Pass --commit to write."
        )
        return 0

    results = await _run_commit(settings)
    # Aggregate log line, never per-symbol (CLAUDE.md's no-per-row-logging rule).
    _logger.info(
        "universe_expansion_onboard_gap_fill_etfs.commit_complete",
        n_onboarded=len(results),
        symbols=[r.symbol for r in results],
        tags_inserted=sum(r.tags_inserted for r in results),
        backfill_rows_seeded=sum(r.backfill_rows_seeded for r in results),
    )
    print(
        "Commit run complete:",
        {
            "n_onboarded": len(results),
            "symbols": [r.symbol for r in results],
            "tags_inserted": sum(r.tags_inserted for r in results),
            "metadata_written": sum(1 for r in results if r.metadata_written),
            "backfill_rows_seeded": sum(r.backfill_rows_seeded for r in results),
        },
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Onboard EMLC (EM-FX) and VIXY (vol-proxy) -- Phase 174 Plan 10. "
            "Dry-run by default -- writing is opt-in via --commit."
        )
    )
    add_write_mode_args(
        parser,
        dry_run="Dry-run only (default): print what would be onboarded, make no writes.",
        commit=(
            "Actually write to instruments/instrument_tags/instrument_metadata/"
            "backfill_status via onboard_instrument(). Off by default -- writing is "
            "opt-in, not opt-out."
        ),
    )
    args = parser.parse_args(argv)

    status = "success"
    try:
        return_code = asyncio.run(_async_main(args))
    except Exception as error:
        status = "failure"
        _logger.error("universe_expansion_onboard_gap_fill_etfs.failed", error=str(error))
        print(f"FAILED: {error}", file=sys.stderr)
        return 1
    finally:
        JOB_COMPLETED_TOTAL.add(
            1, {"job": "universe-expansion-onboard-gap-fill-etfs", "status": status}
        )
        flush_and_shutdown_metrics()
    return return_code


if __name__ == "__main__":
    from src.observability.otel import OTelInitError, init_otel_providers

    try:
        init_otel_providers("universe-expansion-onboard-gap-fill-etfs")
    except OTelInitError as error:
        print(f"[warn] OTel init failed -- metrics disabled: {error}")
    sys.exit(main())
