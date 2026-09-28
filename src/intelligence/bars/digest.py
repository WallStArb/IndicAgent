"""Bar content digest (D-07): content identity for a (symbol, tf, range) slice.

The digest is a sha256 over the canonical serialization of the slice's rows:
every OHLCV value and each row's quarantine rule set, rows sorted by timestamp
so the digest is stable under row order. It deliberately excludes the scrub
rule version: a rule change that moves no value triggers no downstream
recompute, while the rule version is recorded beside the digest in the
bar_content_digest table (plan 11), so a reader can still tell which rules
produced the hashed state.

Cross-phase interface (phase 186 D-23/D-24): this module is the one definition
of the bar content digest. The bar_content_digest table (plan 11) stores what
this function computes; 186's COPY primitive in services/_batch_utils.py reads
that table and must never recompute the digest differently.

Determinism: floats serialize through float.hex() (exact, platform-stable) and
volume NaN or None as the literal "null" (a NULL volume is a real data state:
recovered venue bars carry it), so no Python hash randomization, dict ordering
or float repr drift can move a digest between processes. Empty input hashes the
empty byte string: EMPTY_INPUT_DIGEST below is the documented constant.

Pure: arrays in, hex string out; no database, no config service, no I/O.
"""

from __future__ import annotations

import hashlib
import math
from collections.abc import Sequence
from datetime import UTC, datetime

import numpy as np

DIGEST_ALGORITHM: str = "sha256-bars-v1"

EMPTY_INPUT_DIGEST: str = hashlib.sha256(b"").hexdigest()


def _price_token(value: object) -> str:
    """Exact float serialization for an OHLC field."""
    return float(value).hex()


def _volume_token(value: object) -> str:
    """Volume serialization: NULL volume (NaN or None) is the literal 'null'."""
    if value is None:
        return "null"
    volume = float(value)
    if math.isnan(volume):
        return "null"
    return volume.hex()


def bar_content_digest(
    ts_seconds: np.ndarray,
    open_: np.ndarray,
    high: np.ndarray,
    low: np.ndarray,
    close: np.ndarray,
    volume: np.ndarray,
    quarantine_rules: Sequence[tuple[str, ...]],
) -> str:
    """Full 64-hex sha256 over the slice's rows sorted by timestamp.

    Rows serialize as ts|open|high|low|close|volume|rules with prices in
    float.hex form, volume per _volume_token, and each row's rule set sorted
    and comma-joined. Raises ValueError when quarantine_rules does not have one
    entry per row. Empty input returns EMPTY_INPUT_DIGEST.
    """
    ts_seconds = np.asarray(ts_seconds, dtype=np.int64)
    open_ = np.asarray(open_, dtype=np.float64)
    high = np.asarray(high, dtype=np.float64)
    low = np.asarray(low, dtype=np.float64)
    close = np.asarray(close, dtype=np.float64)
    n = ts_seconds.size
    if len(quarantine_rules) != n:
        raise ValueError(f"quarantine_rules has {len(quarantine_rules)} entries for {n} rows")

    digest = hashlib.sha256()
    order = np.argsort(ts_seconds, kind="stable")
    for i in order:
        rules = ",".join(sorted(quarantine_rules[int(i)]))
        line = (
            f"{int(ts_seconds[i])}"
            f"|{_price_token(open_[i])}"
            f"|{_price_token(high[i])}"
            f"|{_price_token(low[i])}"
            f"|{_price_token(close[i])}"
            f"|{_volume_token(volume[i])}"
            f"|{rules}\n"
        )
        digest.update(line.encode("utf-8"))
    return digest.hexdigest()


def month_ranges(ts_seconds: np.ndarray) -> list[tuple[datetime, datetime]]:
    """UTC calendar months covering the input, as [month start, next month start).

    One (symbol, tf, range) digest key per calendar month; empty input returns
    an empty list.
    """
    ts_seconds = np.asarray(ts_seconds, dtype=np.int64)
    if ts_seconds.size == 0:
        return []
    first = datetime.fromtimestamp(int(ts_seconds.min()), tz=UTC)
    last = datetime.fromtimestamp(int(ts_seconds.max()), tz=UTC)
    ranges: list[tuple[datetime, datetime]] = []
    year, month = first.year, first.month
    while (year, month) <= (last.year, last.month):
        start = datetime(year, month, 1, tzinfo=UTC)
        next_year, next_month = (year + 1, 1) if month == 12 else (year, month + 1)
        ranges.append((start, datetime(next_year, next_month, 1, tzinfo=UTC)))
        year, month = next_year, next_month
    return ranges
