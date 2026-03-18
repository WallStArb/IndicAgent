"""Futures roll chain derivation utility.

Provides:
- FUTURES_ROLL_CYCLES: per-symbol month code sequences
- MONTH_CODE_TO_NUM: CME month code to calendar month number
- derive_roll_chain(): derive 3-contract roll chain from a base symbol

Usage:
    from src.config.contracts import derive_roll_chain
    chain = derive_roll_chain("ES")
    # [{"symbol": "ESM6", "base_symbol": "ES", "month_code": "M",
    #   "expiry_month": 6, "expiry_year": 2026, "roll_from": None, "roll_to": "ESU6"},
    #  ...]
"""

from __future__ import annotations

from datetime import UTC, datetime

# ---------------------------------------------------------------------------
# Month code mapping (CME standard)
# ---------------------------------------------------------------------------

MONTH_CODE_TO_NUM: dict[str, int] = {
    "F": 1,   # January
    "G": 2,   # February
    "H": 3,   # March
    "J": 4,   # April
    "K": 5,   # May
    "M": 6,   # June
    "N": 7,   # July
    "Q": 8,   # August
    "U": 9,   # September
    "V": 10,  # October
    "X": 11,  # November
    "Z": 12,  # December
}

# Reverse: calendar month number → month code
_NUM_TO_MONTH_CODE: dict[int, str] = {v: k for k, v in MONTH_CODE_TO_NUM.items()}

# ---------------------------------------------------------------------------
# Roll cycles per base symbol
# ---------------------------------------------------------------------------

#: Map from base symbol to ordered list of CME month codes in roll cycle.
#: Quarterly (H/M/U/Z): equity index, interest rate, volatility
#: Monthly (all 12): energy, metals
#: Grain cycle (H/K/N/U/Z): agricultural grains
FUTURES_ROLL_CYCLES: dict[str, list[str]] = {
    # ---- Equity Index (CME quarterly) ----
    "ES": ["H", "M", "U", "Z"],   # E-mini S&P 500
    "NQ": ["H", "M", "U", "Z"],   # E-mini Nasdaq
    "RTY": ["H", "M", "U", "Z"],  # E-mini Russell 2000
    "YM": ["H", "M", "U", "Z"],   # E-mini Dow
    # ---- Interest Rates (CBOT quarterly) ----
    "ZN": ["H", "M", "U", "Z"],   # 10-Year T-Note
    "ZF": ["H", "M", "U", "Z"],   # 5-Year T-Note
    "ZB": ["H", "M", "U", "Z"],   # 30-Year T-Bond
    "ZT": ["H", "M", "U", "Z"],   # 2-Year T-Note
    # ---- Volatility (CFE quarterly) ----
    "VIX": ["H", "M", "U", "Z"],  # CBOE VIX Futures
    # ---- Energy (NYMEX monthly) ----
    "CL": ["F", "G", "H", "J", "K", "M", "N", "Q", "U", "V", "X", "Z"],  # Crude Oil WTI
    # ---- Precious & Industrial Metals (COMEX monthly) ----
    "GC": ["F", "G", "H", "J", "K", "M", "N", "Q", "U", "V", "X", "Z"],  # Gold
    "SI": ["F", "G", "H", "J", "K", "M", "N", "Q", "U", "V", "X", "Z"],  # Silver
    "HG": ["F", "G", "H", "J", "K", "M", "N", "Q", "U", "V", "X", "Z"],  # Copper
    # ---- Agriculture / Grains (CBOT grain cycle H/K/N/U/Z) ----
    "ZC": ["H", "K", "N", "U", "Z"],  # Corn
    "ZS": ["H", "K", "N", "U", "Z"],  # Soybeans
    "ZW": ["H", "K", "N", "U", "Z"],  # Wheat
}


# ---------------------------------------------------------------------------
# Roll chain derivation
# ---------------------------------------------------------------------------


def derive_roll_chain(
    base_symbol: str,
    ref_year: int | None = None,
    ref_month: int | None = None,
) -> list[dict]:
    """Derive the 3-contract roll chain for a futures base symbol.

    Returns a list of 3 contract dicts sorted chronologically, starting from
    the contract whose expiry month is >= (ref_year, ref_month). If no contract
    in the current year matches, rolls into the next calendar year.

    Each dict contains:
        symbol (str): Full IBKR-format symbol, e.g. "ESM6"
        base_symbol (str): Base symbol, e.g. "ES"
        month_code (str): CME month code, e.g. "M"
        expiry_month (int): Calendar month 1–12
        expiry_year (int): Full 4-digit year, e.g. 2026
        roll_from (str | None): Previous symbol in chain (None for first)
        roll_to (str | None): Next symbol in chain (None for last)

    Args:
        base_symbol: Futures base symbol (e.g. "ES", "CL", "ZC").
        ref_year: Reference year for chain start (default: current UTC year).
        ref_month: Reference month 1–12 for chain start (default: current UTC month).

    Raises:
        ValueError: If base_symbol is not in FUTURES_ROLL_CYCLES.
    """
    if base_symbol not in FUTURES_ROLL_CYCLES:
        raise ValueError(
            f"Unknown futures base symbol {base_symbol!r}. "
            f"Known symbols: {sorted(FUTURES_ROLL_CYCLES)}"
        )

    now_utc = datetime.now(tz=UTC)
    year = ref_year if ref_year is not None else now_utc.year
    month = ref_month if ref_month is not None else now_utc.month

    cycle = FUTURES_ROLL_CYCLES[base_symbol]

    # Build an infinite stream of (year, month_code) pairs from the cycle,
    # starting at the first code whose month >= ref_month in ref_year.
    # We walk forward through the cycle across years until we collect 3 contracts.
    contracts_raw: list[tuple[int, str]] = []  # (expiry_year, month_code)

    # Start from the first cycle code >= ref_month in the ref_year, then wrap years
    cycle_len = len(cycle)
    scan_year = year
    # Find the first index in cycle where month >= ref_month
    start_idx: int | None = None
    for i, code in enumerate(cycle):
        if MONTH_CODE_TO_NUM[code] >= month:
            start_idx = i
            break

    if start_idx is None:
        # All cycle months < ref_month in current year — roll into next year
        scan_year = year + 1
        start_idx = 0

    # Collect 3 consecutive contracts
    idx = start_idx
    cur_year = scan_year
    while len(contracts_raw) < 3:
        contracts_raw.append((cur_year, cycle[idx]))
        idx += 1
        if idx >= cycle_len:
            idx = 0
            cur_year += 1

    # Build contract dicts
    result: list[dict] = []
    for _i, (exp_year, code) in enumerate(contracts_raw):
        exp_month = MONTH_CODE_TO_NUM[code]
        year_digit = str(exp_year)[-1]  # 1-digit year suffix (IBKR format)
        symbol = f"{base_symbol}{code}{year_digit}"
        result.append(
            {
                "symbol": symbol,
                "base_symbol": base_symbol,
                "month_code": code,
                "expiry_month": exp_month,
                "expiry_year": exp_year,
                "roll_from": None,  # filled below
                "roll_to": None,    # filled below
            }
        )

    # Wire roll_from / roll_to linkage
    for i, contract in enumerate(result):
        if i > 0:
            contract["roll_from"] = result[i - 1]["symbol"]
        if i < len(result) - 1:
            contract["roll_to"] = result[i + 1]["symbol"]

    return result
