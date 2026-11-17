"""The pit-anchor modes of the ticker-entity map writer (todo 609): pure tests.

The planner is covered in tests/unit/bars/test_ticker_entity_map_pit.py; the DB-bound
--pit-anchor and --pit-install runs are rehearsed against the live tables.
"""

from __future__ import annotations

import hashlib
import json
from datetime import date
from pathlib import Path

import pytest

from services.ticker_entity_map_writer import (
    MAP_FILES,
    PIT_KIND,
    HistoryRow,
    InstallRefused,
    OldSpan,
    check_pinned_map,
    manifest_sha256,
    pit_by_year,
    pit_stage2_rows,
    plan_rollback,
    read_map_dir,
    render_pit_map,
    retire_install_identifiers,
    write_map_files,
)
from src.intelligence.bars import ticker_entity_map_pit as pit

D = date.fromisoformat
GAP = b"symbol,scope,reason,valid_from,valid_to,detail\r\n"
CIK_A, CIK_B = "0000000001", "0000000002"
CF1 = "BBG000C2V3D6"
M = [date(2003, 9, 30), date(2003, 10, 31), date(2003, 11, 28)]
OLD = [
    OldSpan("LIVE", "LIVE", D("2003-09-10"), date.max, CF1.replace("C2V3D6", "B9XB24"), "raw", "{}")
]


def rec(ticker, cik=None, cf=None, typ=None):
    return pit.PitRecord(ticker, cik, cf, None, typ, f"{ticker} INC", "XNYS", None, f"raw-{ticker}")


def plan():
    snaps = [
        pit.PitSnapshot(
            M[0],
            (rec("AAA", CIK_A, typ="CS"), rec("BBB", cf=CF1, typ="ETF"), rec("NOK", typ="CS")),
            (),
        ),
        pit.PitSnapshot(M[1], (rec("AAA", CIK_A, typ="CS"), rec("BBB", cf=CF1, typ="ETF")), ()),
        pit.PitSnapshot(M[2], (), ()),
    ]
    return pit.plan_pit_map(snaps, pit.LiveState(frozenset({"LIVE"}), {}, ()))


INPUTS = {"pinned_map": "20261115_x", "rule": pit.PIT_RULE_ID}


def test_the_rendered_map_has_the_five_files_and_the_name_carries_the_pinned_gap_list_digest():
    name, files = render_pit_map(OLD, plan(), INPUTS, GAP, "20261116")
    assert set(files) == set(MAP_FILES)
    assert name == f"20261116_{hashlib.sha256(GAP).hexdigest()[:12]}"
    assert files["gap_list.csv"] == GAP


def test_the_spans_are_the_pinned_spans_kept_plus_the_pit_spans_and_nothing_is_removed():
    _, files = render_pit_map(OLD, plan(), INPUTS, GAP, "20261116")
    rows = files["spans.csv"].decode().splitlines()[1:]
    assert len(rows) == 1 + 2
    assert sum(",kept," in r for r in rows) == 1 and sum(",pit," in r for r in rows) == 2
    doc = json.loads(files["map_diff.json"])
    assert doc["kind"] == PIT_KIND and doc["diff"]["span_rows_removed"] == 0
    assert doc["diff"]["span_rows_added"] == 2 and doc["diff"]["old_spans"] == 1
    assert doc["diff"]["new_securities_by_key_kind"] == {"cik_ticker": 1, "composite_figi": 1}
    assert doc["pinned_spans_sha256"] == hashlib.sha256(files["pinned_spans.csv"]).hexdigest()


def test_a_cik_keyed_span_carries_no_composite_figi_and_a_figi_keyed_one_carries_it():
    _, files = render_pit_map(OLD, plan(), INPUTS, GAP, "20261116")
    by_symbol = {line.split(",")[0]: line for line in files["spans.csv"].decode().splitlines()[1:]}
    assert f",{CF1}," in by_symbol["BBB"] and ",pit,," in by_symbol["AAA"]


def test_the_render_is_deterministic_and_a_written_map_reads_back(tmp_path: Path):
    a = render_pit_map(OLD, plan(), INPUTS, GAP, "20261116")
    b = render_pit_map(OLD, plan(), INPUTS, GAP, "20261116")
    assert a == b
    name, files = a
    write_map_files(tmp_path / name, files)
    back = read_map_dir(tmp_path / name)
    assert back.manifest_sha256 == manifest_sha256(files) and back.diff["kind"] == PIT_KIND


def test_the_by_year_report_counts_placed_unplaced_and_ambiguous_without_reading_a_bar():
    (row,) = pit_by_year(plan())
    assert row["year"] == 2003 and row["placed"] == 4 and row["unplaced_no_key"] == 1
    assert row["unplaced_figi_collision"] == 0 and row["ambiguous_cik_ticker"] == 0


def test_the_stage2_rows_carry_the_key_the_dates_and_the_types():
    rows = {r.symbol: r for r in pit_stage2_rows(plan())}
    assert rows["BBB"].key_kind == pit.COMPOSITE_FIGI and rows["BBB"].types == ("ETF",)
    assert rows["AAA"].first == "2003-09-10" and rows["AAA"].last == "2003-11-28"
    assert rows["AAA"].rule == pit.PIT_RULE_ID


def _history(kind=PIT_KIND):
    lineage = {"install_id": "i1", "map_digest": "d", "map_dir": "20261116_d",
               "pre_install_sha256": "pre", "rows_retired": 0, "rows_inserted": 2,
               "kind": kind}  # fmt: skip
    return [
        HistoryRow(f"new{i}", "sid", f"S{i}", f"T{i}", D("2003-09-10"), None, "raw",
                   {"map_install": {**lineage, "origin": "pit"}}, None)
        for i in range(2)
    ]  # fmt: skip


def test_a_pit_rollback_retires_the_spans_restores_nothing_and_names_the_symbols_to_retire():
    p = plan_rollback("i1", _history())
    assert p.retire_ids == ("new0", "new1") and p.restore == ()
    assert p.new_symbols == ("S0", "S1")


def test_a_documentary_rollback_names_no_identifiers_to_retire():
    assert plan_rollback("i1", _history(kind="documentary")).new_symbols == ()


def test_a_pit_rollback_refuses_once_a_span_is_retired_by_something_else():
    rows = _history()
    rows[0] = HistoryRow(*[*list(rows[0].__dict__.values())[:-1], "ticker_map_rollback x"])
    with pytest.raises(InstallRefused, match="only 1 of the 2"):
        plan_rollback("i1", rows)


def test_a_pinned_map_directory_must_carry_the_digest_of_its_gap_list():
    digest = hashlib.sha256(GAP).hexdigest()[:12]
    check_pinned_map(f"20261115_{digest}", GAP, digest)
    with pytest.raises(ValueError, match="digest"):
        check_pinned_map("20261115_000000000000", GAP, digest)


class _IdentifierConn:
    def __init__(self, retired, foreign):
        self._retired, self._foreign = retired, foreign

    async def fetch(self, sql, *args):
        return [{"security_identifier_id": i} for i in self._retired]

    async def fetchval(self, sql, *args):
        return self._foreign


@pytest.mark.asyncio
async def test_the_rollback_retires_only_identifiers_whose_spans_all_came_from_the_install():
    assert (
        await retire_install_identifiers(_IdentifierConn(["a", "b"], 0), ["S0"], ["n0"], "r") == 2
    )


@pytest.mark.asyncio
async def test_the_rollback_refuses_an_identifier_a_span_outside_the_install_still_uses():
    with pytest.raises(InstallRefused, match="outside the install"):
        await retire_install_identifiers(_IdentifierConn(["a"], 1), ["S0"], ["n0"], "r")
