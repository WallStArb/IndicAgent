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
    write_all,
)

_REPO = Path(__file__).resolve().parents[2]


def _write(path: Path, rows: list[dict]) -> Path:
    fields = list(_MANIFEST_COLUMNS) + [
        key for row in rows for key in row if key not in _MANIFEST_COLUMNS
    ]
    with path.open("w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({col: row.get(col, "") for col in fields})
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


# --- the spread_leg_pair column (todo 444) --------------------------------------------------


def test_pair_column_parses_with_the_tag(tmp_path: Path) -> None:
    rows = load_manifest(
        _write(
            tmp_path / "m.csv",
            [
                _row("AAA", tags="spread_leg", spread_leg_pair="BBB"),
                _row("BBB", tags="spread_leg", spread_leg_pair="AAA"),
            ],
        )
    )
    assert rows[0].spread_leg_pair == "BBB"
    assert rows[1].spread_leg_pair == "AAA"


def test_tag_without_pair_raises(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="without a spread_leg_pair"):
        load_manifest(_write(tmp_path / "m.csv", [_row("AAA", tags="spread_leg")]))


def test_pair_without_tag_raises(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="without carrying the spread_leg tag"):
        load_manifest(_write(tmp_path / "m.csv", [_row("AAA", spread_leg_pair="BBB"), _row("BBB")]))


def test_in_manifest_pair_must_name_itself_back(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="does not carry the spread_leg tag naming this row"):
        load_manifest(
            _write(
                tmp_path / "m.csv",
                [
                    _row("AAA", tags="spread_leg", spread_leg_pair="BBB"),
                    _row("BBB", tags="spread_leg"),
                ],
            )
        )


class _FakeConn:
    """write_all's connection: records the reciprocal-tag statements, answers the partner
    probe from `held`."""

    def __init__(self, held: str | None = None) -> None:
        self.held = held
        self.executed: list[tuple] = []

    class _Txn:
        async def __aenter__(self):
            return None

        async def __aexit__(self, *exc):
            return False

    def transaction(self):
        return self._Txn()

    async def fetchval(self, sql, *args):
        return self.held

    async def execute(self, sql, *args):
        self.executed.append((sql, args))


async def _write_rows(monkeypatch, conn, rows):
    monkeypatch.setattr(
        "scripts.infrastructure.universe_expansion_onboard_manifest.onboard_instrument",
        _noop_onboard,
    )
    return await write_all(conn, rows, qualified={row.symbol for row in rows})


async def _noop_onboard(conn, instrument, **kwargs):
    return None


async def test_write_all_pairs_off_manifest_partner_and_names_it_back(monkeypatch, tmp_path):
    # AAA is on the manifest; its partner BBB already trades and is not onboarded here, so
    # write_all writes BBB's reciprocal tag in the same transaction.
    rows = load_manifest(
        _write(tmp_path / "m.csv", [_row("AAA", tags="spread_leg", spread_leg_pair="BBB")])
    )
    conn = _FakeConn(held=None)
    onboarded = await _write_rows(monkeypatch, conn, rows)
    assert onboarded == ["AAA"]
    ((sql, args),) = conn.executed
    assert args[0] == "BBB"
    assert "'spread_leg'" in sql
    import json as _json

    evidence = _json.loads(args[1])
    assert evidence["pair"] == "AAA"


async def test_write_all_skips_a_partner_that_already_names_back(monkeypatch, tmp_path):
    rows = load_manifest(
        _write(tmp_path / "m.csv", [_row("AAA", tags="spread_leg", spread_leg_pair="BBB")])
    )
    conn = _FakeConn(held="AAA")
    await _write_rows(monkeypatch, conn, rows)
    assert conn.executed == []


async def test_write_all_raises_on_a_conflicting_partner_pair(monkeypatch, tmp_path):
    rows = load_manifest(
        _write(tmp_path / "m.csv", [_row("AAA", tags="spread_leg", spread_leg_pair="BBB")])
    )
    conn = _FakeConn(held="CCC")
    with pytest.raises(ValueError, match="names 'CCC'"):
        await _write_rows(monkeypatch, conn, rows)


async def test_write_all_carries_the_pair_in_the_row_evidence(monkeypatch, tmp_path):
    # An in-manifest pair's evidence blob names the partner through onboard_instrument's tags.
    seen: dict[str, tuple] = {}

    async def _capture(conn, instrument, *, tags=None, **kwargs):
        seen[instrument.symbol] = tags[0]

    monkeypatch.setattr(
        "scripts.infrastructure.universe_expansion_onboard_manifest.onboard_instrument", _capture
    )
    rows = load_manifest(
        _write(
            tmp_path / "m.csv",
            [
                _row("AAA", tags="spread_leg", spread_leg_pair="BBB"),
                _row("BBB", tags="spread_leg", spread_leg_pair="AAA"),
            ],
        )
    )
    await write_all(_FakeConn(), rows, qualified={"AAA", "BBB"})
    assert seen["AAA"][2]["pair"] == "BBB"
    assert seen["BBB"][2]["pair"] == "AAA"
