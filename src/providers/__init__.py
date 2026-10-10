"""
IndicAgent data providers.

Usage:
    from src.providers import IBKRProvider
    from src.providers.base import DataProvider, DataProviderAdapter, Tick, OHLCVBar
"""

from src.providers.base import (
    DataProvider,
    DataProviderAdapter,
    FetchBudget,
    HistoryPage,
    HistoryProvider,
    HistoryRequest,
    NoDataVerdict,
    OHLCVBar,
    Tick,
)
from src.providers.ibkr import IBKRProvider

__all__ = [
    "DataProvider",
    "DataProviderAdapter",
    "FetchBudget",
    "HistoryPage",
    "HistoryProvider",
    "HistoryRequest",
    "IBKRProvider",
    "NoDataVerdict",
    "OHLCVBar",
    "Tick",
    "history_leaf",
]


def history_leaf(name: str, settings=None, **kwargs) -> HistoryProvider:
    """The vendor-name seam for batch history (phase 190): callers dispatch through
    this factory and the HistoryProvider protocol, never a concrete leaf (the same
    fence the boundary test enforces on imports). A new vendor is one leaf module
    plus one entry here."""
    if name == "ibkr":
        return IBKRProvider(settings=settings, **kwargs)
    if name == "alpaca":
        from src.providers.alpaca import AlpacaProvider

        return AlpacaProvider(settings=settings, **kwargs)
    raise ValueError(f"no history leaf for vendor {name!r}; known: ibkr, alpaca")
