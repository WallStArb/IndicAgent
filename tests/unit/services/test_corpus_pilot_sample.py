"""The 1d pilot sample rule (methodology-change ledger 2026-11-22d): the constants, the
sha256 ordering, the refusal below the minimum, the chunks the sample lives in and the
bars-to-stored-rows conversion the screen is given."""

from __future__ import annotations

import hashlib

import pytest

from services import corpus_pilot_sample as ps


def _bars(n_long: int, n_short: int = 0) -> dict[str, int]:
    return {f"L{i:03d}": ps.PILOT_MIN_BARS for i in range(n_long)} | {
        f"S{i:03d}": ps.PILOT_MIN_BARS - 1 for i in range(n_short)
    }


def test_the_constants_are_the_ledger_values():
    assert ps.PILOT_MIN_BARS == 1000
    assert ps.PILOT_MIN_JUDGED_NAMES == 65


def test_the_sample_is_the_first_n_names_meeting_the_bar_floor_in_sha256_order():
    bars = _bars(200, 50)
    sample = ps.pilot_sample(bars, "run-a")
    assert len(sample) == ps.PILOT_MIN_JUDGED_NAMES
    assert all(bars[s] >= ps.PILOT_MIN_BARS for s in sample)  # a 999-bar name never enters
    key = lambda s: hashlib.sha256(f"{s}run-a".encode()).hexdigest()  # noqa: E731
    qualifying = sorted((s for s in bars if bars[s] >= ps.PILOT_MIN_BARS), key=key)
    assert sample == qualifying[: ps.PILOT_MIN_JUDGED_NAMES]


def test_the_sample_is_deterministic_per_run_and_differs_between_runs():
    bars = _bars(300)
    assert ps.pilot_sample(bars, "run-a") == ps.pilot_sample(dict(reversed(bars.items())), "run-a")
    assert ps.pilot_sample(bars, "run-a") != ps.pilot_sample(bars, "run-b")


def test_the_sample_is_not_confined_to_the_start_of_the_alphabet():
    bars = {f"{chr(65 + i % 26)}{i:04d}": 2000 for i in range(2600)}
    first_letters = {s[0] for s in ps.pilot_sample(bars, "run-a")}
    assert len(first_letters) > 10


def test_fewer_qualifying_names_than_the_minimum_refuses_and_names_the_count():
    with pytest.raises(ps.PilotSampleShort, match=r"64 .*65"):
        ps.pilot_sample(_bars(64, 500), "run-a")


def test_the_sample_chunk_indices_are_the_sorted_chunks_holding_the_sample():
    chunks = [("A", "B"), ("C", "D"), ("E", "F")]
    assert ps.sample_chunk_indices(["F", "A", "E"], chunks) == [0, 2]


def test_a_sample_name_outside_every_chunk_is_an_error_not_a_skip():
    with pytest.raises(ValueError, match="ZZZ"):
        ps.sample_chunk_indices(["A", "ZZZ"], [("A", "B")])


def test_the_screen_floor_converts_bars_to_stored_rows_by_the_first_stored_row():
    assert ps.min_stored_rows(first_row=252) == 748
    with pytest.raises(ValueError):
        ps.min_stored_rows(first_row=ps.PILOT_MIN_BARS)  # no stored row could ever qualify
