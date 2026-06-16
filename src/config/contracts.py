"""Futures roll chain derivation utility.

Provides:
- FUTURES_ROLL_CYCLES: per-symbol month code sequences
- MONTH_CODE_TO_NUM: CME month code to calendar month number
- derive_roll_chain(): derive 3-contract roll chain from a base symbol
- get_expiry_date(): approximate expiry date per contract family
- get_roll_window(): return active roll window (start, end) or None

Usage:
    from src.config.contracts import derive_roll_chain, get_expiry_date, get_roll_window
    chain = derive_roll_chain("ES")
    # [{"symbol": "ESM6", "base_symbol": "ES", "month_code": "M",
    #   "expiry_month": 6, "expiry_year": 2026, "roll_from": None, "roll_to": "ESU6",
    #   "expiry_date": date(2026, 6, 19)},
    #  ...]
"""

from __future__ import annotations

import calendar as cal_mod
from datetime import UTC, date, datetime, timedelta

# ---------------------------------------------------------------------------
# Month code mapping (CME standard)
# ---------------------------------------------------------------------------

MONTH_CODE_TO_NUM: dict[str, int] = {
    "F": 1,  # January
    "G": 2,  # February
    "H": 3,  # March
    "J": 4,  # April
    "K": 5,  # May
    "M": 6,  # June
    "N": 7,  # July
    "Q": 8,  # August
    "U": 9,  # September
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
    "ES": ["H", "M", "U", "Z"],  # E-mini S&P 500
    "NQ": ["H", "M", "U", "Z"],  # E-mini Nasdaq
    "RTY": ["H", "M", "U", "Z"],  # E-mini Russell 2000
    "YM": ["H", "M", "U", "Z"],  # E-mini Dow
    # ---- Interest Rates (CBOT quarterly) ----
    "ZN": ["H", "M", "U", "Z"],  # 10-Year T-Note
    "ZF": ["H", "M", "U", "Z"],  # 5-Year T-Note
    "ZB": ["H", "M", "U", "Z"],  # 30-Year T-Bond
    "ZT": ["H", "M", "U", "Z"],  # 2-Year T-Note
    # ---- Volatility (CFE quarterly) ----
    "VX": ["H", "M", "U", "Z"],  # CBOE VIX Futures (IBKR trading_class: VX)
    "VIX": [
        "F",
        "G",
        "H",
        "J",
        "K",
        "M",
        "N",
        "Q",
        "U",
        "V",
        "X",
        "Z",
    ],  # CBOE VIX Futures (IBKR base=VIX, contract prefix=VX, monthly)
    # ---- Energy (NYMEX monthly) ----
    "CL": ["F", "G", "H", "J", "K", "M", "N", "Q", "U", "V", "X", "Z"],  # Crude Oil WTI
    "NG": ["F", "G", "H", "J", "K", "M", "N", "Q", "U", "V", "X", "Z"],  # Natural Gas
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
# Contract family classification (for expiry date calculation)
# ---------------------------------------------------------------------------

#: Quarterly-expiry symbols: equity index, rates, VIX futures.
#: Expiry = third Friday of the expiry month.
# Some base symbols differ from their contract prefix (e.g. IBKR base "VIX" → contracts "VXJ6")
_CONTRACT_PREFIX_MAP: dict[str, str] = {
    "VIX": "VX",
}

_QUARTERLY_SYMBOLS: frozenset[str] = frozenset(
    {"ES", "NQ", "RTY", "YM", "ZN", "ZF", "ZB", "ZT", "VX"}
)

#: Monthly energy and metals futures.
#: Expiry = last business day of the month PRIOR to the expiry month.
_ENERGY_METALS_SYMBOLS: frozenset[str] = frozenset({"CL", "GC", "SI", "HG", "NG", "BZ", "PL", "PA"})

#: Grain futures (CBOT grain cycle).
#: Expiry = Friday closest to the 15th of the expiry month.
_GRAIN_SYMBOLS: frozenset[str] = frozenset({"ZC", "ZS", "ZW"})


def get_expiry_date(base_symbol: str, expiry_month: int, expiry_year: int) -> date:
    """Return approximate expiry date for a futures contract.

    Rules by contract family:
    - Quarterly (equity index, rates, VIX): third Friday of expiry month
    - Monthly energy/metals: last business day of month PRIOR to expiry month
    - Monthly grain: Friday closest to 15th of expiry month
    - Default (unknown): 25th of expiry month (conservative)

    Args:
        base_symbol: Futures base symbol, e.g. "ES", "CL", "ZC".
        expiry_month: Calendar expiry month (1-12).
        expiry_year: Full 4-digit expiry year.

    Returns:
        Approximate expiry date.
    """
    if base_symbol in _QUARTERLY_SYMBOLS:
        # Third Friday of expiry month
        first_day = date(expiry_year, expiry_month, 1)
        weekday_of_first = first_day.weekday()  # 0=Mon, 4=Fri
        days_to_first_friday = (4 - weekday_of_first) % 7
        first_friday = first_day + timedelta(days=days_to_first_friday)
        return first_friday + timedelta(weeks=2)

    if base_symbol in _ENERGY_METALS_SYMBOLS:
        # CME rule: 3 business days prior to the 25th calendar day of the month
        # preceding the delivery month. If the 25th is a weekend, count back from
        # the prior Friday (i.e. find the business day on or before the 25th, then
        # go back 3 more business days).
        prior_month = expiry_month - 1 if expiry_month > 1 else 12
        prior_year = expiry_year if expiry_month > 1 else expiry_year - 1
        anchor = date(prior_year, prior_month, 25)
        while anchor.weekday() >= 5:
            anchor -= timedelta(days=1)
        bdays = 0
        d = anchor
        while bdays < 3:
            d -= timedelta(days=1)
            if d.weekday() < 5:
                bdays += 1
        return d

    if base_symbol in _GRAIN_SYMBOLS:
        # Friday closest to 15th of expiry month
        mid = date(expiry_year, expiry_month, 15)
        days_to_friday = (4 - mid.weekday()) % 7
        if days_to_friday > 3:
            days_to_friday -= 7
        return mid + timedelta(days=days_to_friday)

    # Default: conservative 25th of expiry month (capped to last day of month)
    last_day_of_month = cal_mod.monthrange(expiry_year, expiry_month)[1]
    day = min(25, last_day_of_month)
    return date(expiry_year, expiry_month, day)


def get_roll_window(base_symbol: str, ref_date: date) -> tuple[date, date] | None:
    """Return the active roll window for a futures symbol, or None.

    Roll window: starts ~14 calendar days before expiry (≈10 trading days),
    ends ~3 calendar days before expiry (≈2 trading days).

    Also returns a window if the roll start is within 21 days in the future.

    Args:
        base_symbol: Futures base symbol, e.g. "ES".
        ref_date: Reference date to check against.

    Returns:
        (roll_start, roll_end) if inside or approaching a roll window, else None.

    Raises:
        ValueError: If base_symbol is not in FUTURES_ROLL_CYCLES.
    """
    chain = derive_roll_chain(base_symbol, ref_year=ref_date.year, ref_month=ref_date.month)
    if not chain:
        return None

    for entry in chain:
        expiry = get_expiry_date(base_symbol, entry["expiry_month"], entry["expiry_year"])
        roll_start = expiry - timedelta(days=14)
        # Friday of the week prior to expiry week (at least 7 days before expiry)
        _anchor = expiry - timedelta(days=7)
        roll_end = _anchor - timedelta(days=(_anchor.weekday() - 4) % 7)

        # Active: anywhere from roll_start up to (but not including) expiry
        if roll_start <= ref_date < expiry:
            return (roll_start, roll_end)

        # Also surface windows approaching within 21 days
        if roll_start > ref_date and (roll_start - ref_date).days <= 21:
            return (roll_start, roll_end)

    return None


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
    index = start_idx
    cur_year = scan_year
    while len(contracts_raw) < 3:
        contracts_raw.append((cur_year, cycle[index]))
        index += 1
        if index >= cycle_len:
            index = 0
            cur_year += 1

    # Build contract dicts
    result: list[dict] = []
    for _i, (exp_year, code) in enumerate(contracts_raw):
        exp_month = MONTH_CODE_TO_NUM[code]
        year_digit = str(exp_year)[-1]  # 1-digit year suffix (IBKR format)
        prefix = _CONTRACT_PREFIX_MAP.get(base_symbol, base_symbol)
        symbol = f"{prefix}{code}{year_digit}"
        result.append(
            {
                "symbol": symbol,
                "base_symbol": base_symbol,
                "month_code": code,
                "expiry_month": exp_month,
                "expiry_year": exp_year,
                "expiry_date": get_expiry_date(base_symbol, exp_month, exp_year),
                "roll_from": None,  # filled below
                "roll_to": None,  # filled below
            }
        )

    # Wire roll_from / roll_to linkage
    for i, contract in enumerate(result):
        if i > 0:
            contract["roll_from"] = result[i - 1]["symbol"]
        if i < len(result) - 1:
            contract["roll_to"] = result[i + 1]["symbol"]

    return result
