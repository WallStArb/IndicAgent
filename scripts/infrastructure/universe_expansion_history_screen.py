#!/usr/bin/env python3
"""
universe_expansion_history_screen.py -- screen drawn symbols for IBKR tradability and history

For each symbol in one or more draw CSVs, checks (1) that IBKR qualifies it and (2) that IBKR
returns at least one daily bar in the two weeks before --history-before. A name failing
either check is printed as FAIL and left out of the onboarding manifest.

Why a bar probe instead of IBKR's head timestamp: get_head_timestamp() is a one-sided floor
that often fails ("Query failed" for 112 of 273 active equities, 2026-09-24) and can predate
the first real daily bar by decades (ODFL). A bar in the window is direct evidence.

fetch_historical_bars() returns [] both for "no data" and for a request that exhausted its
retries (pacing, timeout, a dropped gateway). So after every empty probe the same window is
fetched for a control symbol that always has bars: if the control is also empty the verdict
is INCONCLUSIVE, never FAIL, and the name must be screened again. The 2026-09-26 run predates
this control and recorded 14 retry-exhausted probes as FAIL (config/universe/README.md).

The screen is a data-quality filter (a name listed after the cutoff adds little to a panel
scored from 2010), chosen before any return is looked at. It does tilt the draw toward
long-lived firms, on top of the current-membership survivorship bias (todo 376).

Settings reads the .env beside its own source tree, so a worktree run needs that .env
(a symlink to the main checkout's is enough):
    .venv/bin/python scripts/infrastructure/universe_expansion_history_screen.py \\
        --draw config/universe/r2k_draw_2026_09_26.csv --history-before 2016-09-26
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pandas as pd

project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from src.config.settings import Settings  # noqa: E402
from src.core.models import AssetClass, Instrument  # noqa: E402
from src.providers.ibkr import IBKRProvider  # noqa: E402

# Same operator-run qualification client as universe_expansion_onboard_manifest.py; the two
# never run at once. --client-id lets a second screen process share the list.
_DEFAULT_CLIENT_ID = 46

# Probe window before the cutoff: two calendar weeks always spans several sessions.
_PROBE_WINDOW = timedelta(days=14)

# Long-listed ETF with daily bars in any window since 1993; an empty fetch for it means the
# request failed, not that the window has no data.
_CONTROL_SYMBOL = "SPY"


async def screen(
    symbols: list[str], history_before: datetime, client_id: int = _DEFAULT_CLIENT_ID
) -> dict[str, str]:
    """Return {symbol: reason} for every symbol that fails; passing and inconclusive symbols
    are omitted. Each verdict is printed as it lands, so a long run's progress survives an
    interruption."""
    settings = Settings()
    provider = IBKRProvider(host=settings.ib_host, port=settings.ib_port, client_id=client_id)
    if not await provider.connect():
        raise RuntimeError("could not connect to ib-gateway")
    failures: dict[str, str] = {}
    start = history_before - _PROBE_WINDOW
    try:
        control = Instrument(
            symbol=_CONTROL_SYMBOL,
            base=_CONTROL_SYMBOL,
            asset_class=AssetClass.EQUITY,
            exchange="SMART",
            session_id="nyse",
        )
        if not await provider.qualify_instrument(control):
            raise RuntimeError(f"control symbol {_CONTROL_SYMBOL} failed to qualify")
        for symbol in symbols:
            instrument = Instrument(
                symbol=symbol,
                base=symbol,
                asset_class=AssetClass.EQUITY,
                exchange="SMART",
                session_id="nyse",
            )
            verdict = "PASS"
            if not await provider.qualify_instrument(instrument):
                failures[symbol] = "not qualified"
                verdict = "FAIL"
            elif not await provider.fetch_historical_bars(symbol, "1d", start, history_before):
                if await provider.fetch_historical_bars(
                    _CONTROL_SYMBOL, "1d", start, history_before
                ):
                    failures[symbol] = f"no daily bar before {history_before.date()}"
                    verdict = "FAIL"
                else:
                    verdict = "INCONCLUSIVE"
            print(f"{verdict} {symbol}", flush=True)
    finally:
        await provider.disconnect()
    return failures


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Screen drawn symbols for history.")
    parser.add_argument("--draw", type=Path, action="append", required=True)
    parser.add_argument("--history-before", required=True, help="YYYY-MM-DD cutoff.")
    parser.add_argument("--client-id", type=int, default=_DEFAULT_CLIENT_ID)
    parser.add_argument(
        "--only", default="", help="Comma-separated subset to screen (e.g. new replacements)."
    )
    args = parser.parse_args(argv)
    cutoff = datetime.strptime(args.history_before, "%Y-%m-%d").replace(tzinfo=UTC)
    symbols = [s for path in args.draw for s in pd.read_csv(path)["symbol"]]
    if args.only:
        wanted = {s.strip() for s in args.only.split(",")}
        symbols = [s for s in symbols if s in wanted]
    failures = asyncio.run(screen(list(dict.fromkeys(symbols)), cutoff, args.client_id))
    print(f"screened {len(symbols)}, failed {len(failures)}")
    print("failed=" + ",".join(failures))
    return 0


if __name__ == "__main__":
    sys.exit(main())
