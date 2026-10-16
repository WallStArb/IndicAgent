"""Unit tests for the vendor/kind swap script's --swap gates (phase 191 plan 14).

The fresh-prove requirement (todo 535 item 43, L4): --swap must refuse unless a clean --prove
completed after the last --build and both tables' per-timeframe row counts still match the prove
record. A count-equality resume could skip a same-count wrong-values window, so the swap may not
rely on a prove run by hand before it; the state record and this decision function are the code
that enforces it. prove_blockers is pure: these tests pin every refusal without a database.
"""

from __future__ import annotations

from scripts.ops.bars.ops_canonical_vendor_kind_swap import prove_blockers

_COUNTS = {"1d": 10, "5m": 20}


def _state(
    prove_result: str = "proven equal and gate-clean",
    prove_at: str = "2026-10-16T05:00:00+00:00",
    build_at: str | None = "2026-10-16T03:00:00+00:00",
    rows_original: int = 30,
    rows_v2: int = 30,
    by_timeframe_original: dict[str, int] | None = None,
    by_timeframe_v2: dict[str, int] | None = None,
) -> dict:
    state: dict = {}
    if build_at is not None:
        state["build"] = {"completed_at": build_at, "result": "copied"}
    state["prove"] = {
        "completed_at": prove_at,
        "result": prove_result,
        "rows_original": rows_original,
        "rows_v2": rows_v2,
        "by_timeframe_original": (
            dict(_COUNTS) if by_timeframe_original is None else by_timeframe_original
        ),
        "by_timeframe_v2": dict(_COUNTS) if by_timeframe_v2 is None else by_timeframe_v2,
    }
    return state


def test_clean_record_passes() -> None:
    assert prove_blockers(_state(), _COUNTS, _COUNTS) == []


def test_missing_prove_record_blocks() -> None:
    blockers = prove_blockers({}, _COUNTS, _COUNTS)
    assert blockers and "no --prove record" in blockers[0]


def test_unclean_prove_result_blocks() -> None:
    blockers = prove_blockers(
        _state(prove_result="digests equal, selection gate not clean"), _COUNTS, _COUNTS
    )
    assert blockers and "selection gate not clean" in blockers[0]


def test_prove_predating_the_last_build_blocks() -> None:
    blockers = prove_blockers(_state(build_at="2026-10-16T06:00:00+00:00"), _COUNTS, _COUNTS)
    assert blockers and "before the last build" in blockers[0]


def test_rows_moved_since_the_prove_blocks() -> None:
    blockers = prove_blockers(_state(), _COUNTS, {"1d": 10, "5m": 21})
    assert blockers and "moved since the prove" in " ".join(blockers)


def test_per_timeframe_drift_blocks_even_at_equal_totals() -> None:
    drifted = {"1d": 15, "5m": 15}
    blockers = prove_blockers(_state(), _COUNTS, drifted)
    assert blockers and "moved since the prove" in " ".join(blockers)


def test_unparseable_prove_timestamp_blocks() -> None:
    blockers = prove_blockers(_state(prove_at="not a timestamp"), _COUNTS, _COUNTS)
    assert blockers and "completed_at" in " ".join(blockers)
