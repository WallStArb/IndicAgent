"""D0 data-quality label arithmetic tests (D-04).

The labels an attempt carries: venue truncation share, dividend label and
scrub-flag share. Pure synthetic panels pin each behavior and the manifest
round-trip the S0 manifest and S6 evidence consume unchanged.
"""

from __future__ import annotations

import json

import numpy as np
import pytest

from src.intelligence.bars.labels import (
    DataQualityLabels,
    DividendLabel,
    build_labels,
    dividend_label,
    scrub_flag_share,
    venue_truncation_share,
)


def _panel_symbols(n_symbols: int = 10, n_sessions: int = 100) -> np.ndarray:
    """Flattened (name, session) cell symbols: each symbol in n_sessions cells."""
    return np.repeat(np.array([f"S{i:02d}" for i in range(n_symbols)], dtype="<U8"), n_sessions)


def _cell_keys(n: int = 1000) -> np.ndarray:
    """Structured (symbol, ts_seconds) keys, n cells over 10 symbols."""
    return np.array(
        [(f"S{i % 10:02d}", 1_700_000_000 + i) for i in range(n)],
        dtype=[("symbol", "U8"), ("ts", "i8")],
    )


def test_venue_truncation_share_two_moved_of_ten_symbols():
    symbols = _panel_symbols()
    assert symbols.size == 1000
    moved = frozenset({"S03", "S07"})
    assert venue_truncation_share(symbols, moved) == pytest.approx(0.2)


def test_venue_truncation_share_no_moved_symbols_is_zero():
    assert venue_truncation_share(_panel_symbols(), frozenset()) == pytest.approx(0.0)


def test_dividend_label_uncovered_share_150_of_1000():
    covered = np.ones(1000, dtype=bool)
    covered[:150] = False
    label = dividend_label(True, covered)
    assert isinstance(label, DividendLabel)
    assert label.total_return is True
    assert label.uncovered_share == pytest.approx(0.15)


def test_dividend_label_rejects_non_boolean_coverage():
    with pytest.raises(TypeError):
        dividend_label(False, np.zeros(10))


def test_scrub_flag_share_counts_only_keys_present_in_cells():
    cells = _cell_keys()
    flagged = frozenset(
        {(str(cells["symbol"][i]), int(cells["ts"][i])) for i in range(7)}
        | {("GHOST", 9_999)}  # a flagged bar outside the attempt's cells
    )
    assert scrub_flag_share(cells, flagged) == pytest.approx(0.007)


def test_scrub_flag_share_accepts_object_tuples():
    cells = np.empty(4, dtype=object)
    cells[:] = [("A", 1), ("A", 2), ("B", 1), ("B", 2)]
    assert scrub_flag_share(cells, frozenset({("B", 2)})) == pytest.approx(0.25)


def test_scrub_flag_share_rejects_2d_keys():
    cells = np.array([[("A", 1)], [("A", 2)]], dtype=object)
    with pytest.raises(ValueError):
        scrub_flag_share(cells, frozenset({("A", 1)}))


def test_build_labels_and_manifest_round_trip_through_json():
    covered = np.ones(1000, dtype=bool)
    covered[:150] = False
    cells = _cell_keys()
    flagged = frozenset({(str(cells["symbol"][i]), int(cells["ts"][i])) for i in range(7)})
    labels = build_labels(
        d2_rule_version="d2-2026-10-01.abc1234",
        cell_symbols=_panel_symbols(),
        moved_symbols=frozenset({"S03", "S07"}),
        total_return=True,
        div_covered=covered,
        cell_keys=cells,
        flagged_keys=flagged,
    )
    assert isinstance(labels, DataQualityLabels)
    assert labels.d2_rule_version == "d2-2026-10-01.abc1234"

    manifest = labels.to_manifest()
    assert set(manifest) == {
        "d2_rule_version",
        "venue_truncation_share",
        "dividends",
        "scrub_flag_share",
    }
    assert manifest["venue_truncation_share"] == pytest.approx(0.2)
    assert manifest["dividends"] == {
        "total_return": True,
        "uncovered_share": pytest.approx(0.15),
    }
    assert manifest["scrub_flag_share"] == pytest.approx(0.007)

    round_tripped = json.loads(json.dumps(manifest))
    assert round_tripped == manifest
