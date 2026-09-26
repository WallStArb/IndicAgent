"""Unit tests for universe_expansion_onboard_manifest.py and universe_expansion_holdings_draw.py."""

from __future__ import annotations

import csv
from pathlib import Path

import pytest

from scripts.infrastructure.universe_expansion_onboard_manifest import (
    _MANIFEST_COLUMNS,
    _PreQualified,
    build_instrument,
    load_manifest,
    qualify_all,
)

_REPO = Path(__file__).resolve().parents[2]


def _write(path: Path, rows: list[dict]) -> Path:
    with path.open("w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=_MANIFEST_COLUMNS)
        writer.writeheader()
        for row in rows:
            writer.writerow({col: row.get(col, "") for col in _MANIFEST_COLUMNS})
    return path


def _row(symbol: str, **overrides: str) -> dict:
    base = {
        "symbol": symbol,
        "name": f"{symbol} Inc",
        "code": "EQ.FIN.BANKS.BANKS",
        "source_ref": "ibkr_contract_details+review",
        "tags": "single_name_equity;eq_small_cap",
        "cohort": "test",
    }
    return base | overrides


def test_load_manifest_parses_tags_and_metadata(tmp_path: Path) -> None:
    rows = load_manifest(
        _write(
            tmp_path / "m.csv",
            [
                _row("AAA"),
                _row(
                    "EEE",
                    code="EQ.IT",
                    source_ref="fund_mandate",
                    tags="eq_sector",
                    issuer="Invesco",
                    underlying_index="Idx",
                ),
            ],
        )
    )
    assert rows[0].tags == ("single_name_equity", "eq_small_cap")
    assert rows[0].metadata is None
    assert rows[1].metadata == {
        "listing_date": None,
        "underlying_index": "Idx",
        "issuer": "Invesco",
        "description": None,
    }


@pytest.mark.parametrize(
    "rows",
    [
        [_row("AAA"), _row("AAA")],
        [_row("AAA", tags="")],
        [_row("AAA", source_ref="guess")],
    ],
    ids=["duplicate", "no-tags", "bad-source-ref"],
)
def test_load_manifest_rejects_bad_rows(tmp_path: Path, rows: list[dict]) -> None:
    with pytest.raises(ValueError):
        load_manifest(_write(tmp_path / "m.csv", rows))


def test_ibkr_symbol_reaches_provider_meta(tmp_path: Path) -> None:
    rows = load_manifest(
        _write(tmp_path / "m.csv", [_row("BRK.B", ibkr_symbol="BRK B"), _row("AAA")])
    )
    assert build_instrument(rows[0]).provider_meta == {"ibkr": {"symbol": "BRK B"}}
    assert build_instrument(rows[1]).provider_meta == {}


def test_committed_manifest_loads() -> None:
    rows = load_manifest(_REPO / "config/universe/expansion_2026_09_26.csv")
    assert len({r.symbol for r in rows}) == len(rows)
    assert all(
        r.classification.source_ref == "ibkr_contract_details+review"
        for r in rows
        if "single_name_equity" in r.tags
    )


class _FakeQualifier:
    def __init__(self, good: set[str], probe_results: list[bool]) -> None:
        self.good = good
        self.probe_results = probe_results

    async def qualify_instrument(self, instrument, **_kwargs) -> bool:
        if instrument.symbol == "SPY":
            return self.probe_results.pop(0)
        return instrument.symbol in self.good


async def test_qualify_all_splits_qualified_and_rejected(tmp_path: Path) -> None:
    rows = load_manifest(_write(tmp_path / "m.csv", [_row("AAA"), _row("BBB")]))
    qualified, rejected = await qualify_all(_FakeQualifier({"AAA"}, [True, True]), rows)
    assert qualified == {"AAA"}
    assert rejected == ["BBB"]


@pytest.mark.parametrize("probes", [[False], [True, False]], ids=["before", "after"])
async def test_qualify_all_aborts_when_gateway_probe_fails(
    tmp_path: Path, probes: list[bool]
) -> None:
    rows = load_manifest(_write(tmp_path / "m.csv", [_row("AAA")]))
    with pytest.raises(RuntimeError, match="gateway probe"):
        await qualify_all(_FakeQualifier({"AAA"}, probes), rows)


async def test_prequalified_answers_without_network(tmp_path: Path) -> None:
    rows = load_manifest(_write(tmp_path / "m.csv", [_row("AAA"), _row("BBB")]))
    qualifier = _PreQualified({"AAA"})
    assert await qualifier.qualify_instrument(build_instrument(rows[0])) is True
    assert await qualifier.qualify_instrument(build_instrument(rows[1])) is False
