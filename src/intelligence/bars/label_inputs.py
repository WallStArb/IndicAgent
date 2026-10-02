"""D0 label-input reads for a research attempt (D-07).

One read-only asyncpg loader that assembles everything plan 08's labels need
for a set of symbols and a span: the names whose history starts at a venue
move and their move dates (``ohlcv_venue_head``), the quarantined bar keys
(``bar_quality_flag``, D-09), the listing-exchange mix (latest
``ohlcv_request.primary_exchange`` per name), the current D2 rule version
(latest completed ``bar_derivation_batch`` stage ``daily``; ``None`` until the
first daily derivation run, reported rather than guessed) and the dividend
coverage windows (``dividend_event_coverage``, Yahoo rows).

Boundary: this module reads, it never computes; the pure label math stays in
``labels.py`` and the research layer stays untouched (the helper lives one
ring out on purpose). Every symbol list is bound as an array parameter, never
inlined into SQL (T-185-16-03).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

from src.core.database_manager import _setup_codecs

_MOVED_SQL = """
SELECT symbol, MIN(smart_head_date) AS smart_head
FROM ohlcv_venue_head
WHERE pre_move AND symbol = ANY($1)
GROUP BY symbol
ORDER BY symbol
"""

_QUARANTINE_SQL = """
SELECT symbol, EXTRACT(EPOCH FROM "timestamp")::bigint AS ts_seconds
FROM bar_quality_flag
WHERE quarantine
  AND timeframe = $1
  AND "timestamp" >= $2
  AND "timestamp" < $3
  AND symbol = ANY($4)
"""

_EXCHANGE_SQL = """
SELECT symbol, primary_exchange
FROM (
    SELECT symbol, primary_exchange,
           ROW_NUMBER() OVER (PARTITION BY symbol ORDER BY requested_at DESC) AS rn
    FROM ohlcv_request
    WHERE symbol = ANY($1) AND primary_exchange IS NOT NULL
) ranked
WHERE rn = 1
"""

_D2_RULE_SQL = """
SELECT rule_version
FROM bar_derivation_batch
WHERE stage = 'daily' AND status = 'completed'
ORDER BY finished_at DESC NULLS LAST, started_at DESC
LIMIT 1
"""

_DIVIDEND_COVERAGE_SQL = """
SELECT symbol, covered_from, covered_to
FROM dividend_event_coverage
WHERE source = 'yahoo' AND symbol = ANY($1)
"""


@dataclass(frozen=True)
class LabelInputs:
    """Every D0 label input for one attempt's symbols and span (D-07).

    ``quarantine_keys`` holds ``(symbol, ts_seconds)`` pairs so ``labels.
    scrub_flag_share`` can match them against its cell keys. ``exchange_of``
    maps every name with a stored request to its latest primary exchange;
    ``dividend_coverage`` maps to ``(covered_from, covered_to)``.
    """

    moved_symbols: frozenset[str]
    move_dates: dict[str, date]
    quarantine_keys: frozenset[tuple[str, int]]
    exchange_of: dict[str, str]
    d2_rule_version: str | None
    dividend_coverage: dict[str, tuple[date, date]]


async def load_label_inputs(
    conn: Any,
    *,
    symbols: Sequence[str],
    tf: str,
    start: datetime,
    end: datetime,
) -> LabelInputs:
    """Load every label input for ``symbols`` over ``[start, end)`` at ``tf``.

    ``conn`` may be a bare ``asyncpg.connect()`` or a pooled connection: the
    jsonb codecs are (re)registered first so any future detail column decodes
    to a dict on both (a pooled registration is replaced in place, not
    duplicated).
    """
    await _setup_codecs(conn)
    symbol_array = list(symbols)

    moved_rows = await conn.fetch(_MOVED_SQL, symbol_array)
    move_dates = {row[0]: row[1] for row in moved_rows}

    quarantine_rows = await conn.fetch(_QUARANTINE_SQL, tf, start, end, symbol_array)
    quarantine_keys = frozenset((row[0], int(row[1])) for row in quarantine_rows)

    exchange_rows = await conn.fetch(_EXCHANGE_SQL, symbol_array)
    exchange_of = {row[0]: row[1] for row in exchange_rows}

    d2_rows = await conn.fetch(_D2_RULE_SQL)
    d2_rule_version = d2_rows[0][0] if d2_rows else None

    dividend_rows = await conn.fetch(_DIVIDEND_COVERAGE_SQL, symbol_array)
    dividend_coverage = {row[0]: (row[1], row[2]) for row in dividend_rows}

    return LabelInputs(
        moved_symbols=frozenset(move_dates),
        move_dates=move_dates,
        quarantine_keys=quarantine_keys,
        exchange_of=exchange_of,
        d2_rule_version=d2_rule_version,
        dividend_coverage=dividend_coverage,
    )
