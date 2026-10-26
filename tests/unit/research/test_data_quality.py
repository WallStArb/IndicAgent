"""S0 data-quality pinning and the D0 labels from a pinned snapshot (todo 501, D-04, D-07)."""

import json
from datetime import UTC, date, datetime

import numpy as np
import pytest

from src.intelligence.bars.label_inputs import LabelInputs
from src.intelligence.bars.labels import build_labels
from src.intelligence.research import data_quality
from src.intelligence.research.panel import Panel

T0 = datetime(2024, 1, 1, tzinfo=UTC)
T1 = datetime(2024, 2, 1, tzinfo=UTC)


def _inputs(**kw):
    base = dict(
        moved_symbols=frozenset({"B"}),
        move_dates={"B": date(2020, 1, 2)},
        quarantine_keys=frozenset({("A", 1704326400)}),
        exchange_of={},
        d2_rule_version="d2-v3",
        dividend_coverage={"A": (date(2000, 1, 1), date(2024, 1, 3))},
        policy_as_of=T0,
        verdict_as_of=None,
    )
    return LabelInputs(**{**base, **kw})


def _manifest(**kw):
    return data_quality.snapshot_manifest(
        _inputs(**kw),
        symbols=["B", "A"],
        tf="1d",
        digest_rows=[("A", T1, "d2"), ("A", T0, "d1"), ("B", T0, "d3")],
        verdict_rows=[("A|1d", "session_coverage", True), ("A|1d", "digest_fresh", False)],
    )


def test_manifest_pins_every_key_json_clean():
    m = _manifest()
    assert m["symbols"] == ["A", "B"]
    assert m["d2_rule_version"] == "d2-v3"
    assert m["policy_as_of"] == T0.isoformat() and m["verdict_as_of"] is None
    assert m["bar_integrity"] == {"A|1d": {"digest_fresh": False, "session_coverage": True}}
    assert set(m["bar_content_digests"]["1d"]) == {"A", "B"}
    assert m["bar_content_digests"]["1d"]["A"]["n_ranges"] == 2
    assert m["data_quality_inputs"] == {
        "moved_symbols": ["B"],
        "quarantine_keys": [["A", 1704326400]],
        "dividend_coverage": {"A": ["2000-01-01", "2024-01-03"]},
    }
    assert json.loads(json.dumps(m)) == m


def test_rule_version_none_is_recorded_as_none():
    assert _manifest(d2_rule_version=None)["d2_rule_version"] is None


def test_symbol_digest_ignores_row_order_and_tracks_content():
    rows = [("A", T0, "d1"), ("A", T1, "d2")]
    same = data_quality.symbol_digests(rows[::-1])
    assert data_quality.symbol_digests(rows) == same
    assert data_quality.symbol_digests([("A", T0, "d1"), ("A", T1, "dX")]) != same
    assert data_quality.symbol_digests([]) == {}


def _panel(manifest):
    ts = np.array(["2024-01-02", "2024-01-03", "2024-01-04"], dtype="datetime64[D]")
    close = np.array([[1.0, 2.0], [1.0, np.nan], [1.0, 2.0]])
    return Panel(
        tf="1d",
        symbols=("A", "B"),
        timestamps=ts,
        bars_per_session=1,
        valid=np.ones(3, dtype=bool),
        open=close,
        close=close,
        volume=close,
        manifest=manifest,
    )


def test_labels_from_pinned_inputs():
    block = data_quality.panel_labels(_panel(_manifest()), total_return=True)
    # 5 cells: A on 3 sessions, B on 2. B moved; A 2024-01-03 quarantined; A covered to 01-03.
    assert block == {
        "d2_rule_version": "d2-v3",
        "venue_truncation_share": 0.4,
        "dividends": {"total_return": True, "uncovered_share": 0.6},
        "scrub_flag_share": 0.2,
    }


def test_snapshot_without_pinned_inputs_has_no_labels():
    assert data_quality.panel_labels(_panel({"start": "2024-01-01"}), total_return=False) is None


def test_vectorized_labels_match_build_labels():
    rng = np.random.default_rng(7)
    days = np.datetime64("2024-01-02") + np.arange(40)
    symbols = tuple(f"S{i}" for i in range(6))
    close = np.where(rng.random((40, 6)) < 0.2, np.nan, 1.0)
    seconds = days.astype("datetime64[s]").astype(np.int64)
    quarantine = [[f"S{rng.integers(6)}", int(seconds[rng.integers(40)])] for _ in range(15)]
    coverage = {"S0": ["2024-01-10", "2024-01-30"], "S3": ["2023-01-01", "2030-01-01"]}
    manifest = {
        "d2_rule_version": "d2-v3",
        "data_quality_inputs": {
            "moved_symbols": ["S1", "S4", "ZZZ"],
            "quarantine_keys": quarantine,
            "dividend_coverage": coverage,
        },
    }
    panel = Panel(
        tf="1d",
        symbols=symbols,
        timestamps=days,
        bars_per_session=1,
        valid=np.ones(40, dtype=bool),
        open=close,
        close=close,
        volume=close,
        manifest=manifest,
    )
    rows, cols = np.nonzero(np.isfinite(close))
    cell_symbols = np.asarray(symbols, dtype=object)[cols]
    keys = np.empty(len(rows), dtype=object)
    keys[:] = list(zip(cell_symbols.tolist(), seconds[rows].tolist()))
    covered = np.array(
        [
            s in coverage and np.datetime64(coverage[s][0]) <= d <= np.datetime64(coverage[s][1])
            for s, d in zip(cell_symbols, days[rows])
        ]
    )
    expected = build_labels(
        d2_rule_version="d2-v3",
        cell_symbols=cell_symbols,
        moved_symbols=frozenset({"S1", "S4", "ZZZ"}),
        total_return=True,
        div_covered=covered,
        cell_keys=keys,
        flagged_keys=frozenset((s, t) for s, t in quarantine),
    ).to_manifest()
    got = data_quality.panel_labels(panel, total_return=True)
    assert got["dividends"] == pytest.approx(expected.pop("dividends"))
    got.pop("dividends")
    assert got == pytest.approx(expected)
    assert 0 < got["scrub_flag_share"] and 0 < got["venue_truncation_share"]
