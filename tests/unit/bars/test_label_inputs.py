"""Unit tests for the D0 label-input read helper (plan 185-16, D-07).

The helper is a read-only asyncpg loader: one parameterized query per label
input, rows mapped into LabelInputs. A fake connection records every fetch so
the tests pin the SQL shape (ANY($1) array parameters, never inlined symbol
lists) and the row mapping without a database.
"""

from __future__ import annotations

import inspect
from datetime import UTC, date, datetime

from src.intelligence.bars.label_inputs import LabelInputs, load_label_inputs


class FakeConn:
    """Records (sql, args) per fetch and returns queued row lists in order."""

    def __init__(self, results: list[list[tuple]]) -> None:
        self._results = list(results)
        self.calls: list[tuple[str, tuple]] = []
        self.codec_calls: list[str] = []

    async def set_type_codec(self, name: str, **kwargs) -> None:
        self.codec_calls.append(name)

    async def fetch(self, sql: str, *args) -> list[tuple]:
        self.calls.append((sql, args))
        return self._results.pop(0)


async def _run(results: list[list[tuple]]) -> tuple[LabelInputs, FakeConn]:
    conn = FakeConn(results)
    inputs = await load_label_inputs(
        conn,
        symbols=["AMD", "PEP", "SPY"],
        tf="1d",
        start=datetime(2006, 1, 1, tzinfo=UTC),
        end=datetime(2007, 1, 1, tzinfo=UTC),
    )
    return inputs, conn


async def test_load_label_inputs_maps_rows_and_uses_array_parameters() -> None:
    inputs, conn = await _run(
        [
            [("AMD", date(2015, 10, 1)), ("PEP", date(2017, 1, 1))],  # moved
            [("AMD", 1234567890), ("SPY", 987654321)],  # quarantine keys
            [("AMD", "ISLAND"), ("SPY", "ARCA")],  # exchange of
            [("grid-v3",)],  # d2 rule version
            [("AMD", date(2007, 1, 1), date(2026, 9, 30))],  # dividend coverage
        ]
    )

    assert inputs.moved_symbols == frozenset({"AMD", "PEP"})
    assert inputs.move_dates == {"AMD": date(2015, 10, 1), "PEP": date(2017, 1, 1)}
    assert inputs.quarantine_keys == frozenset({("AMD", 1234567890), ("SPY", 987654321)})
    assert inputs.exchange_of == {"AMD": "ISLAND", "SPY": "ARCA"}
    assert inputs.d2_rule_version == "grid-v3"
    assert inputs.dividend_coverage == {"AMD": (date(2007, 1, 1), date(2026, 9, 30))}

    # Five queries, every symbol list bound as an array parameter.
    assert len(conn.calls) == 5
    by_marker = {
        marker: (sql, args)
        for sql, args in conn.calls
        for marker in (
            "ohlcv_venue_head",
            "bar_quality_flag",
            "ohlcv_request",
            "bar_derivation_batch",
            "dividend_event_coverage",
        )
        if marker in sql
    }
    assert set(by_marker) == {
        "ohlcv_venue_head",
        "bar_quality_flag",
        "ohlcv_request",
        "bar_derivation_batch",
        "dividend_event_coverage",
    }
    for marker in (
        "ohlcv_venue_head",
        "bar_quality_flag",
        "ohlcv_request",
        "dividend_event_coverage",
    ):
        sql, args = by_marker[marker]
        assert "ANY($1)" in sql or "ANY($4)" in sql, f"{marker} must bind symbols as an array"
        assert "AMD" in args[0] or "AMD" in args[-1], f"{marker} must receive the symbol list"

    sql, args = by_marker["bar_quality_flag"]
    assert "quarantine" in sql
    assert args[0] == "1d"
    assert args[1] == datetime(2006, 1, 1, tzinfo=UTC)
    assert args[2] == datetime(2007, 1, 1, tzinfo=UTC)
    assert "AMD" in args[3]

    # The daily rule version reads the latest completed daily batch only.
    sql, _ = by_marker["bar_derivation_batch"]
    assert "stage = 'daily'" in sql
    assert "status = 'completed'" in sql

    # Bare connections get the jsonb codecs registered (contract).
    assert conn.codec_calls == ["jsonb", "json"]


async def test_d2_rule_version_is_none_before_the_first_daily_batch() -> None:
    inputs, _ = await _run(
        [
            [],  # moved
            [],  # quarantine
            [],  # exchange
            [],  # no completed daily batch: None, never a guess
            [],  # dividends
        ]
    )
    assert inputs.d2_rule_version is None
    assert inputs.moved_symbols == frozenset()
    assert inputs.quarantine_keys == frozenset()
    assert inputs.exchange_of == {}
    assert inputs.dividend_coverage == {}


def test_module_has_no_research_imports() -> None:
    """D-07 boundary: the read helper never reaches into the research layer."""
    from src.intelligence.bars import label_inputs

    assert "src.intelligence.research" not in inspect.getsource(label_inputs)
