#!/usr/bin/env python3
"""One-off script to request a quote from IBKR for a given symbol (e.g. VXJ6)."""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.config.settings import get_settings
from src.providers.ibkr import IBKRProvider


async def main(symbol: str) -> None:
    settings = get_settings()
    # Use a distinct client ID so we don't conflict with TWS daemon (35) or others
    provider = IBKRProvider(
        host=settings.ib_host,
        port=settings.ib_port,
        client_id=settings.ib_client_id + 10,
    )
    if not await provider.connect():
        print("Failed to connect to IBKR")
        return
    try:
        instrument = await provider.resolve_instrument(symbol)
        if not instrument:
            print(f"Could not resolve symbol: {symbol}")
            return
        print(f"Resolved: {instrument.symbol} ({instrument.name})")
        if not await provider.qualify_instrument(instrument):
            print("Could not qualify contract")
            return
        quote = await provider.get_quote(instrument.symbol)
        if quote:
            print(f"Quote for {instrument.symbol}: {quote}")
        else:
            print("No quote data received (timeout or no market data)")
    finally:
        await provider.disconnect()


if __name__ == "__main__":
    sym = sys.argv[1] if len(sys.argv) > 1 else "VXJ6"
    asyncio.run(main(sym))
