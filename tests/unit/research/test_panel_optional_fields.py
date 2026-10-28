"""Optional S0 fields: high, low and point-in-time sector (plan 187-15 Task 2)."""

import datetime
import json
from pathlib import Path

import numpy as np
import pytest

from src.intelligence.research import panel as panel_mod
from src.intelligence.research import store
from src.intelligence.research.snapshot import build_grid, sector_grid, session_dates
from src.intelligence.research.spec import load_spec_from_file
from tests.unit.research.test_spec import FAMILY

FAMILY1_SNAPSHOT = Path("/home/bg/dev/indicagent/logs/research/snapshots/panel_81fa9178ca4ad603")


def _bars(with_range=False):
    days = np.array(["2024-01-02", "2024-01-03", "2024-01-04"], dtype="datetime64[D]")
    ts = (days + np.timedelta64(21, "h")).astype("datetime64[ns]")
    o, c, v = np.array([10.0, 11, 12]), np.array([10.5, 11.5, 12.5]), np.array([100.0, 200, 300])
    a = (ts, o, c, v) + ((c + 1, o - 1) if with_range else ())
    b = (ts[1:], o[1:] * 2, c[1:] * 2, v[1:]) + (
        (c[1:] * 2 + 1, o[1:] * 2 - 1) if with_range else ()
    )
    return {"AAA": a, "BBB": b}


def test_a_panel_without_fields_writes_the_same_bytes(tmp_path):
    plain = build_grid(_bars(), "1d")
    assert plain.high is None and plain.low is None and plain.sector_pit is None
    path = panel_mod.save(plain, tmp_path)
    assert sorted(p.stem for p in path.glob("*.npy")) == [
        "close",
        "open",
        "timestamps",
        "valid",
        "volume",
    ]
    assert "sector_codes" not in store.read_meta(path)["manifest"]


@pytest.mark.skipif(not FAMILY1_SNAPSHOT.exists(), reason="family 1 snapshot not on this host")
def test_the_family1_snapshot_still_verifies_and_loads():
    assert store.verify(FAMILY1_SNAPSHOT).startswith("81fa9178ca4ad603")
    loaded = panel_mod.load(FAMILY1_SNAPSHOT)
    assert loaded.high is None and loaded.sector_pit is None


def test_high_and_low_align_with_open_and_close(tmp_path):
    grid = build_grid(_bars(with_range=True), "1d", ("high", "low"))
    np.testing.assert_array_equal(grid.high[:, 0], grid.close[:, 0] + 1)
    np.testing.assert_array_equal(grid.low[:, 1], [np.nan, 21.0, 23.0])
    loaded = panel_mod.load(panel_mod.save(grid, tmp_path))
    np.testing.assert_array_equal(loaded.high, grid.high)
    np.testing.assert_array_equal(loaded.low, grid.low)
    picked = panel_mod.select_symbols(loaded, ["BBB"])
    np.testing.assert_array_equal(picked.high[:, 0], grid.high[:, 1])
    with pytest.raises(ValueError, match="bar arrays"):
        build_grid(_bars(), "1d", ("high", "low"))  # the tuples lack the requested arrays


SESSIONS = np.array(["2024-01-02", "2024-01-03", "2024-01-04", "2024-01-05"], dtype="datetime64[D]")
D = datetime.date


def test_a_reclassification_mid_panel_switches_on_its_date():
    rows = [
        ("AAA", "S10", "Tech", D(2023, 1, 1), D(2024, 1, 4)),
        ("AAA", "S20", "Health", D(2024, 1, 4), None),
        ("BBB", "S20", "Health", D(2020, 1, 1), None),
    ]
    traded = np.ones((4, 2), bool)
    traded[0, 1] = False
    codes, table = sector_grid(SESSIONS, ("AAA", "BBB"), traded, rows)
    assert table == [["S10", "Tech"], ["S20", "Health"]]
    np.testing.assert_array_equal(codes[:, 0], [0, 0, 1, 1])
    np.testing.assert_array_equal(codes[:, 1], [-1, 1, 1, 1])  # untraded session: -1


def test_a_traded_session_without_a_classification_refuses():
    rows = [("AAA", "S10", "Tech", D(2024, 1, 3), None)]  # starts after the first session
    with pytest.raises(ValueError, match="AAA on 2024-01-02"):
        sector_grid(SESSIONS, ("AAA",), np.ones((4, 1), bool), rows)
    # Not traded before the assignment: nothing is assumed, nothing refuses.
    traded = np.array([[False], [True], [True], [True]])
    codes, _ = sector_grid(SESSIONS, ("AAA",), traded, rows)
    np.testing.assert_array_equal(codes[:, 0], [-1, 0, 0, 0])


def test_sector_pit_round_trips_with_its_code_table(tmp_path):
    grid = build_grid(_bars(), "1d")
    codes, table = sector_grid(
        session_dates(grid),
        grid.symbols,
        np.isfinite(grid.close),
        [("AAA", "S10", "Tech", D(2020, 1, 1), None), ("BBB", "S10", "Tech", D(2020, 1, 1), None)],
    )
    manifest = {**grid.manifest, "sector_codes": table}
    with_sectors = panel_mod.Panel(**{**grid.__dict__, "manifest": manifest, "sector_pit": codes})
    loaded = panel_mod.load(panel_mod.save(with_sectors, tmp_path))
    np.testing.assert_array_equal(loaded.sector_pit, codes)
    assert loaded.manifest["sector_codes"] == [["S10", "Tech"]]
    with pytest.raises(ValueError, match="sector_codes"):
        panel_mod.Panel(**{**grid.__dict__, "sector_pit": codes})


def _family(tmp_path, fields_line):
    text = FAMILY.replace("  bars_per_session: 26", "  bars_per_session: 26\n" + fields_line)
    path = tmp_path / "fam.yaml"
    path.write_text(text)
    return load_spec_from_file(path, root=tmp_path)


def test_spec_fields_are_optional_and_validated(tmp_path):
    plain = load_spec_from_file(_write(tmp_path, FAMILY), root=tmp_path)
    assert "fields" not in json.loads(plain.canonical)["panel"]
    withf = _family(tmp_path, "  fields: [high, low, sector_pit]")
    assert withf.model.panel.fields == ["high", "low", "sector_pit"]
    assert withf.spec_hash != plain.spec_hash
    for bad in ("  fields: []", "  fields: [high, high]", "  fields: [vwap]"):
        with pytest.raises(ValueError):
            _family(tmp_path, bad)


def _write(tmp_path, text):
    path = tmp_path / "plain.yaml"
    path.write_text(text)
    return path


def test_fields_have_one_canonical_order(tmp_path):
    a = _family(tmp_path, "  fields: [low, high]")
    b = _family(tmp_path, "  fields: [high, low]")
    assert a.model.panel.fields == ["high", "low"] and a.spec_hash == b.spec_hash


def test_the_runner_sub_panel_carries_every_optional_array():
    from src.intelligence.research.runner import _sub_panel

    grid = build_grid(_bars(with_range=True), "1d", ("high", "low"))
    codes, table = sector_grid(
        session_dates(grid),
        grid.symbols,
        np.isfinite(grid.close),
        [("AAA", "S10", "Tech", D(2020, 1, 1), None), ("BBB", "S10", "Tech", D(2020, 1, 1), None)],
    )
    full = panel_mod.Panel(
        **{
            **grid.__dict__,
            "manifest": {**grid.manifest, "sector_codes": table},
            "sector_pit": codes,
        }
    )
    sub = _sub_panel(full, 2)
    np.testing.assert_array_equal(sub.high, full.high[:2])
    np.testing.assert_array_equal(sub.sector_pit, full.sector_pit[:2])


def test_total_return_scales_high_and_low_like_open_and_close():
    from src.intelligence.research import dividends

    grid = build_grid(_bars(with_range=True), "1d", ("high", "low"))
    n_s, m = grid.n_sessions, len(grid.symbols)
    shape = (grid.n_sessions, len(grid.symbols))
    paid = np.zeros(shape)
    paid[1] = 0.02  # a 2% dividend on the second session for both names
    div = dividends.DividendGrid(grid.symbols, paid, np.zeros(shape), np.ones(shape, dtype=bool))
    out = dividends.total_return(grid, div, suspect_yield=0.5)
    ratio = out.close / grid.close
    for name in ("open", "high", "low"):
        np.testing.assert_allclose(getattr(out, name) / getattr(grid, name), ratio)


def test_a_transform_refuses_high_and_low(tmp_path):
    text = FAMILY.replace(
        "  bars_per_session: 26",
        "  bars_per_session: 26\n  transform: session_legs\n  fields: [high]",
    )
    path = tmp_path / "legs.yaml"
    path.write_text(text)
    with pytest.raises(ValueError, match="does not carry high or low"):
        load_spec_from_file(path, root=tmp_path)
