"""The 1d pilot sample rule of the corpus rerun.

Pre-registered gate constants, declared in the methodology-change ledger entry 2026-11-22d and
changed only by a dated amendment there (APR-exempt: an operator-tunable sample floor invites
tuning after seeing results). The measurement behind them (G6 power 0.90 against a defect in 10
percent of names at the 5 percent null limit) is in that entry.

- A name qualifies for the sample with at least PILOT_MIN_BARS tradeable 1d bars before the pin
  date (`horizon`), stated in bars; the screen counts stored rows, `min_stored_rows` converts.
- The sample is the first PILOT_MIN_JUDGED_NAMES qualifying names ordered by
  sha256(symbol + run id): deterministic per run, not confined to one end of the alphabet.
- A pilot with fewer than PILOT_MIN_JUDGED_NAMES names cannot be sampled or judged and refuses.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Any

PILOT_MIN_BARS = 1_000
PILOT_MIN_JUDGED_NAMES = 65


class PilotSampleShort(RuntimeError):
    """Fewer qualifying names than the pilot needs to judge; the pilot refuses."""


def pilot_sample(bars_by_symbol: Mapping[str, int], run_id: str) -> list[str]:
    """The pilot's names: qualifying symbols in sha256(symbol + run_id) order, the first
    PILOT_MIN_JUDGED_NAMES of them. Raises PilotSampleShort when fewer qualify."""
    qualifying = [s for s, n in bars_by_symbol.items() if n >= PILOT_MIN_BARS]
    if len(qualifying) < PILOT_MIN_JUDGED_NAMES:
        raise PilotSampleShort(
            f"{len(qualifying)} members have at least {PILOT_MIN_BARS} tradeable 1d bars; the "
            f"pilot needs {PILOT_MIN_JUDGED_NAMES} (ledger 2026-11-22d)"
        )
    qualifying.sort(key=lambda s: hashlib.sha256(f"{s}{run_id}".encode()).hexdigest())
    return qualifying[:PILOT_MIN_JUDGED_NAMES]


def sample_chunk_indices(sample: Sequence[str], chunks: Sequence[Sequence[str]]) -> list[int]:
    """The sorted indices of the symbol chunks holding the sample (a stage executes whole
    chunks, so unit identities stay those of the full run). An unchunked name is an error."""
    chunk_of = {symbol: i for i, chunk in enumerate(chunks) for symbol in chunk}
    unchunked = sorted(set(sample) - chunk_of.keys())
    if unchunked:
        raise ValueError(f"sample names in no symbol chunk: {unchunked}")
    return sorted({chunk_of[s] for s in sample})


def min_stored_rows(first_row: int) -> int:
    """The screen's `--min-name-rows` for a name with PILOT_MIN_BARS bars: the rebuild stores
    rows from `first_row` (the momentum z-score window), so stored rows are bars minus it."""
    if first_row >= PILOT_MIN_BARS:
        raise ValueError(
            f"first stored row {first_row} leaves no row of a {PILOT_MIN_BARS}-bar name"
        )
    return PILOT_MIN_BARS - first_row


_HISTORY_BARS_SQL = """
SELECT symbol, count(*) FROM market_data_ohlcv_tradeable
WHERE timeframe = '1d' AND timestamp < %s GROUP BY symbol
"""


def fetch_history_bars(conn: Any, horizon: datetime) -> dict[str, int]:
    """Per symbol, its tradeable 1d bars before `horizon` (the pin date). Reads only."""
    with conn.cursor() as cur:
        cur.execute(_HISTORY_BARS_SQL, (horizon,))
        return {symbol: int(n) for symbol, n in cur.fetchall()}
