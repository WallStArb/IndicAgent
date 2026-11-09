"""Data adjacency diff: what a source could serve versus what we store (todo 603, rung 0).

The register doc `docs/reference/data-adjacency-register.md` holds the same seed rows with the
availability-time, history-start, retrieval-cost and license columns; SERVED_FIELDS below is the
machine-readable half. The two must move together: tests/unit/test_ops_adjacency_diff.py
asserts every field here appears in a register table row, and every target (table, column) here
is either a real storage location or an empty tuple.

"Stored" means the field's data exists in some table we hold, from any vendor; which vendor's
copy is canonical is the register doc's business, not this diff's. Targets with an empty tuple
are fields no table carries today, which is the scouting list.

Read-only: the only statements are SELECTs against information_schema and one session-level
`SET default_transaction_read_only = on`. Nothing is written to the database or to disk; the
report goes to stdout.

Run: .venv/bin/python scripts/ops/ops_adjacency_diff.py
Exit 0 always: a diff is a report, not a gate.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

import psycopg

project_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(project_root))

from src.config.settings import get_settings  # noqa: E402


# (table, column) locations where a field would live. Empty tuple: captured nowhere.
# Field names match the register doc's field column (its distinctive lead wording).
@dataclass(frozen=True)
class ServedField:
    source: str
    field: str
    targets: tuple[tuple[str, str], ...]


SERVED_FIELDS: tuple[ServedField, ...] = (
    # Massive flat files (us_stocks_sip/minute_aggs_v1); admission pending todo 600.
    ServedField(
        "massive flat files",
        "open, high, low, close (per-minute)",
        (
            ("ohlcv_raw", "open"),
            ("ohlcv_raw", "high"),
            ("ohlcv_raw", "low"),
            ("ohlcv_raw", "close"),
        ),
    ),
    ServedField("massive flat files", "volume (per-minute)", (("ohlcv_raw", "volume"),)),
    ServedField("massive flat files", "transactions (trade count)", ()),
    ServedField(
        "massive flat files", "window_start (bar timestamp)", (("ohlcv_raw", "timestamp"),)
    ),
    ServedField("massive flat files", "extended-hours rows", ()),
    ServedField("massive flat files", "listing_end", (("listing_end", "last_session"),)),
    # Alpaca bars.
    ServedField(
        "alpaca",
        "open, high, low, close, volume (SIP 5m, 1d)",
        (("ohlcv_raw", "open"), ("ohlcv_raw", "volume")),
    ),
    ServedField("alpaca", "vwap", ()),
    ServedField("alpaca", "trade count", ()),
    ServedField("alpaca", "extended-hours bars", ()),
    # IBKR bars and contract data.
    ServedField(
        "ibkr",
        "open, high, low, close, volume (5m pre-2016, 1d)",
        (("ohlcv_raw", "open"),),
    ),
    ServedField(
        "ibkr",
        "borrow availability",
        (
            ("borrow_availability_snapshots", "shortable_shares"),
            ("borrow_availability_snapshots", "shortable"),
        ),
    ),
    # Massive REST.
    ServedField(
        "massive rest",
        "dividends",
        (("dividend_events", "ex_date"), ("dividend_events", "amount")),
    ),
    ServedField(
        "massive rest",
        "splits",
        (("corporate_action", "effective_date"), ("corporate_action", "factor")),
    ),
    ServedField("massive rest", "ticker events", ()),
    ServedField("massive rest", "market holidays", ()),
    ServedField("massive rest", "earnings", ()),
    ServedField("massive rest", "corporate events", ()),
    ServedField("massive rest", "income statements", ()),
    ServedField("massive rest", "EDGAR filing index", ()),
    # SEC EDGAR direct.
    ServedField("sec edgar", "8-K Item 2.02 acceptance timestamp", ()),
    # Yahoo dividends cross-check.
    ServedField(
        "yahoo",
        "dividend dates",
        (("dividend_events", "ex_date"), ("dividend_events", "amount")),
    ),
    # FRED and NY Fed macro layer.
    ServedField(
        "fred / ny fed",
        "economic series",
        (
            ("economic_series_observation", "value"),
            ("economic_series_observation", "available_at"),
        ),
    ),
    # Cboe and FRED volatility.
    ServedField("cboe / fred", "index and volatility series", ()),
    # Exchange calendars.
    ServedField("exchange calendars", "index rebalances", ()),
    # FINRA direct.
    ServedField("finra", "short volume", ()),
    ServedField("finra", "short interest", ()),
)

STORED, PARTIAL, NOT_STORED = "stored", "partial", "not stored"


def load_stored_columns(conn: psycopg.Connection) -> dict[str, set[str]]:
    rows = conn.execute(
        "select table_name, column_name from information_schema.columns"
        " where table_schema = 'public'"
    ).fetchall()
    stored: dict[str, set[str]] = {}
    for table_name, column_name in rows:
        stored.setdefault(table_name, set()).add(column_name)
    return stored


def field_verdict(field: ServedField, stored: dict[str, set[str]]) -> tuple[str, list[str]]:
    """Return (verdict, missing target strings). A field with no targets is never stored."""
    missing = [
        f"{table}.{column}"
        for table, column in field.targets
        if column not in stored.get(table, set())
    ]
    if not field.targets or len(missing) == len(field.targets):
        return NOT_STORED, missing
    if missing:
        return PARTIAL, missing
    return STORED, []


def diff(
    fields: tuple[ServedField, ...], stored: dict[str, set[str]]
) -> dict[str, dict[str, list[str]]]:
    """Group verdicts by source: {source: {verdict: [field names]}}."""
    by_source: dict[str, dict[str, list[str]]] = {}
    for field in fields:
        verdict, _missing = field_verdict(field, stored)
        by_source.setdefault(field.source, {}).setdefault(verdict, []).append(field.field)
    return by_source


def print_report(fields: tuple[ServedField, ...], stored: dict[str, set[str]]) -> None:
    by_source = diff(fields, stored)
    print("Data adjacency diff (stored = the field's data exists in some table, any vendor)")
    print()
    header = f"{'source':<18} {'servable':>8} {STORED:>8} {PARTIAL:>8} {NOT_STORED:>10}"
    print(header)
    print("-" * len(header))
    for source in dict.fromkeys(field.source for field in fields):
        verdicts = by_source.get(source, {})
        servable = sum(len(v) for v in verdicts.values())
        print(
            f"{source:<18} {servable:>8} {len(verdicts.get(STORED, [])):>8}"
            f" {len(verdicts.get(PARTIAL, [])):>8} {len(verdicts.get(NOT_STORED, [])):>10}"
        )
    total_servable = len(fields)
    total_stored = sum(len(v.get(STORED, [])) + len(v.get(PARTIAL, [])) for v in by_source.values())
    print("-" * len(header))
    print(f"{'total':<18} {total_servable:>8} {total_stored:>8}")
    print()
    print("Not stored (the scouting list):")
    for field in fields:
        verdict, missing = field_verdict(field, stored)
        if verdict == NOT_STORED:
            note = f" (missing: {', '.join(missing)})" if missing else ""
            print(f"  {field.source:<18} {field.field}{note}")
        elif verdict == PARTIAL:
            print(f"  {field.source:<18} {field.field} [partial] (missing: {', '.join(missing)})")
    stored_names = [field.field for field in fields if field_verdict(field, stored)[0] == STORED]
    print()
    print("Stored: " + (", ".join(stored_names) if stored_names else "(none)"))


def main() -> int:
    with psycopg.connect(get_settings().database_url) as conn:
        conn.execute("SET default_transaction_read_only = on")
        stored = load_stored_columns(conn)
    print_report(SERVED_FIELDS, stored)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
