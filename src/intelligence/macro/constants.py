"""Macro factor instrument constants.

Defines cross-asset instrument groups for macro factor computation.
Each factor degrades gracefully when instruments are absent.
"""

from __future__ import annotations

# Rate futures for yield curve slope (Plan 64-03A)
MACRO_RATE_FUTURES = frozenset({
    "ZT",  # 2-Year US Treasury Note futures
    "ZN",  # 10-Year US Treasury Note futures
    "ZB",  # 30-Year US Treasury Bond futures
    "ZF",  # 5-Year US Treasury Note futures
})

# FX pairs for USD strength (Plan 64-03C — deferred)
MACRO_FX_PAIRS = frozenset({
    "EURUSD",  # Euro/US Dollar
    "GBPUSD",  # British Pound/US Dollar
    "USDJPY",  # US Dollar/Japanese Yen
    "USDCHF",  # US Dollar/Swiss Franc
})

# Flight-to-quality instruments (Plan 64-03B)
MACRO_FLIGHT_TO_QUALITY = frozenset({
    "TLT",  # iShares 20+ Year Treasury Bond ETF
    "SPY",  # SPDR S&P 500 ETF Trust
    "VX",   # CBOE Volatility Index futures
})

# Yield curve anchor pair — short end (ZT) + long end (ZB) used for slope computation
MACRO_YC_ANCHOR_PAIR = frozenset({"ZT", "ZB"})

# FTQ instruments actually consumed by compute_flight_to_quality (SPY + TLT only — VX unused)
MACRO_FTQ_INSTRUMENTS = frozenset({"TLT", "SPY"})

# All macro instruments consumed by this service (excludes FX — deferred to Plan 64-03C)
MACRO_ACTIVE_SYMBOLS = MACRO_RATE_FUTURES | MACRO_FTQ_INSTRUMENTS

# All macro instruments (union of all factors)
MACRO_ALL_SYMBOLS = MACRO_RATE_FUTURES | MACRO_FX_PAIRS | MACRO_FLIGHT_TO_QUALITY
