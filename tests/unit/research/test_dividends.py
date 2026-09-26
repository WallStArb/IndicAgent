"""Total-return prices for research panels (todo 428)."""

import dataclasses
from datetime import date

import numpy as np
import pandas as pd
import pytest

from src.intelligence.research import dividends, legs, snapshot
from src.intelligence.research import panel as panel_mod
from src.intelligence.research.dividends import DividendGrid
from src.intelligence.research.panel import Panel, daily_panel, forward_returns
from src.intelligence.research.spec import parse_spec_text
from tests.unit.research.test_spec import FAMILY, _hash

SUSPECT = 0.10


def _grid(symbols, n_sessions, yields=None, events=(), single=(), uncovered=()):
    """yields: a full [S, m] array, or events {(session, col): yield}; single: (session, col)
    events only one source reports; uncovered: (session, col) pairs outside coverage."""
    m = len(symbols)
    y = np.zeros((n_sessions, m)) if yields is None else yields
    s = np.zeros((n_sessions, m))
    c = np.ones((n_sessions, m), dtype=bool)
    for (k, j), v in dict(events).items():
        y[k, j] = v
    for k, j in single:
        s[k, j] = y[k, j]
    for k, j in uncovered:
        c[k, j] = False
    return DividendGrid(tuple(symbols), y, s, c)


def _hy_daily(n=1500, m=6, seed=0, annual_yield=0.08):
    """Zero-alpha total-return walks; the first half of the names pay a quarterly dividend, so
    their stored (price-only) series drift down by the yield. Returns (raw panel, grid, TR
    closes, TR opens)."""
    rng = np.random.default_rng(seed)
    tr = 100 * np.exp(np.cumsum(rng.normal(0, 0.012, (n, m)), axis=0))
    tr_open = tr * np.exp(rng.normal(0, 0.003, (n, m)))
    y = np.zeros((n, m))
    y[63::63, : m // 2] = annual_yield / 4
    factor = np.cumprod(1 - y, axis=0)  # the price-only series: TR x product of (1 - y)
    raw = daily_panel(tr * factor, opens=tr_open * factor)
    return raw, _grid(raw.symbols, n, yields=y), tr, tr_open


def test_grid_maps_ex_dates_to_sessions():
    sessions = np.array(["2024-01-02", "2024-01-03", "2024-01-05"], dtype="datetime64[D]")
    grid = dividends.dividend_grid(
        sessions,
        ("A", "B"),
        {"A": (date(2024, 1, 3), date(2024, 1, 5))},
        [
            ("A", date(2024, 1, 4), 0.01, False),  # a holiday: shows on the next session
            ("A", date(2024, 1, 5), 0.02, True),  # same session: compounds
            ("A", date(2023, 12, 29), 0.5, False),  # before the panel
            ("A", date(2024, 1, 8), 0.5, False),  # after it
            ("Z", date(2024, 1, 3), 0.5, False),  # not a panel symbol
        ],
    )
    assert grid.div_yield[:, 0] == pytest.approx([0, 0, 1.01 * 1.02 - 1])
    assert grid.div_unconfirmed_yield[:, 0].tolist() == [0, 0, 0.02]  # per event, not compound
    assert grid.div_covered[:, 0].tolist() == [False, True, True]
    assert not grid.div_covered[:, 1].any()  # B has no coverage row: unknown everywhere


def test_session_dates_are_exchange_local():
    ts = np.array(["2024-01-02T14:30", "2024-01-02T20:45", "2024-01-03T14:30", "2024-01-03T20:45"])
    p = dataclasses.replace(
        daily_panel(np.ones((4, 1))), timestamps=ts.astype("datetime64[m]"), bars_per_session=2
    )
    assert snapshot.session_dates(p).tolist() == [date(2024, 1, 2), date(2024, 1, 3)]


def test_daily_total_return_recovers_the_total_return_series_exactly():
    raw, grid, tr, tr_open = _hy_daily()
    out = dividends.total_return(raw, grid, SUSPECT)
    np.testing.assert_allclose(out.close, tr, rtol=1e-12)
    np.testing.assert_allclose(out.open, tr_open, rtol=1e-12)
    assert out.manifest["total_return"]["events_applied"] == int((grid.div_yield > 0).sum())
    # The raw daily open-to-open target carries every ex-date drop; the corrected one does not.
    raw_fwd, tr_fwd = forward_returns(raw.open), forward_returns(out.open)
    ex_rows = np.flatnonzero(grid.div_yield[:, 0] > 0) - 2  # entry t+1, exit t+2
    assert np.all(tr_fwd[ex_rows, 0] - raw_fwd[ex_rows, 0] == pytest.approx(-np.log1p(-0.02)))


def test_a_price_drop_of_exactly_the_dividend_is_a_zero_total_return():
    """Code review counterexample: 100 then 90 ex a $10 dividend (y = 0.10) must be flat."""
    raw = daily_panel(np.array([[100.0], [90.0]]), opens=np.array([[100.0], [90.0]]))
    out = dividends.total_return(raw, _grid(raw.symbols, 2, events={(1, 0): 0.10}), SUSPECT)
    assert np.log(out.close[1, 0] / out.close[0, 0]) == pytest.approx(0.0, abs=1e-15)


def test_family9_guard_a_high_yield_name_with_no_alpha_shows_no_price_level_signal():
    """done-when of todo 428: a price-level feature (distance from the trailing 252-session high)
    on the total-return panel is the feature of the zero-alpha total-return walk itself, so a
    high-yield name carries no dividend-made signal. On price-only data it does."""

    def dist_from_high(close):
        return np.log(close / pd.DataFrame(close).rolling(252).max().to_numpy())

    def payer_gap(close):
        d = dist_from_high(close)
        return np.nanmean(d[:, :3]) - np.nanmean(d[:, 3:])

    raw, grid, tr, _ = _hy_daily(n=2000)
    out = dividends.total_return(raw, grid, SUSPECT)
    np.testing.assert_allclose(dist_from_high(out.close), dist_from_high(tr), atol=1e-12)
    assert payer_gap(raw.close) < payer_gap(out.close) - 0.02  # price-only pushes payers down


def _intraday(n_sessions=4, bps=4, m=2, seed=1):
    rng = np.random.default_rng(seed)
    n = n_sessions * bps
    close = 50 * np.exp(np.cumsum(rng.normal(0, 0.004, (n, m)), axis=0))
    start = np.datetime64("2024-01-02T14:30", "m")
    day, bar = np.timedelta64(1, "D"), np.timedelta64(15, "m")
    ts = np.array([start + d * day + b * bar for d in range(n_sessions) for b in range(bps)])
    return Panel(
        tf="15m",
        symbols=tuple(f"s{j}" for j in range(m)),
        timestamps=ts,
        bars_per_session=bps,
        valid=np.ones(n, dtype=bool),
        open=close * np.exp(rng.normal(0, 0.001, (n, m))),
        close=close,
        volume=np.ones((n, m)),
    )


def test_intraday_returns_are_unchanged_and_the_overnight_leg_gains_the_dividend():
    raw = _intraday()
    out = dividends.total_return(raw, _grid(raw.symbols, 4, events={(2, 0): 0.03}), SUSPECT)
    np.testing.assert_allclose(  # targets never cross the gap: unchanged up to rounding
        forward_returns(out.open, 1, raw.session, closes=out.close),
        forward_returns(raw.open, 1, raw.session, closes=raw.close),
        rtol=0,
        atol=1e-14,
    )
    r_raw = panel_mod.bar_returns(legs.session_legs(raw))
    r_tr = panel_mod.bar_returns(legs.session_legs(out))
    overnight = 2 * legs.LEGS  # session 2's row 0: previous close to this open
    assert r_tr[overnight, 0] - r_raw[overnight, 0] == pytest.approx(-np.log1p(-0.03))
    others = np.ones(r_raw.shape, dtype=bool)
    others[overnight, 0] = False
    np.testing.assert_allclose(r_tr[others], r_raw[others], rtol=1e-12, equal_nan=True)


def test_prices_outside_coverage_are_nan_and_an_uncovered_symbol_is_dropped():
    n = 30
    raw = daily_panel(np.full((n, 3), 10.0), opens=np.full((n, 3), 10.0))
    uncovered = [(k, 0) for k in range(5)] + [(k, 2) for k in range(n)]
    out = dividends.total_return(raw, _grid(raw.symbols, n, uncovered=uncovered), SUSPECT)
    assert out.symbols == ("s0", "s1")
    assert np.isnan(out.close[:5, 0]).all() and np.isfinite(out.close[5:, 0]).all()
    assert out.manifest["total_return"]["symbols_without_coverage"] == ["s2"]


def test_a_large_single_source_yield_splits_the_symbol_instead_of_being_applied():
    n = 40
    raw = daily_panel(np.full((n, 2), 10.0), opens=np.full((n, 2), 10.0))
    grid = _grid(
        raw.symbols, n, events={(20, 0): 0.5, (20, 1): 0.5, (30, 0): 0.01}, single=[(20, 0)]
    )
    out = dividends.total_return(raw, grid, SUSPECT)
    assert out.symbols == ("s0", "s0~1", "s1")  # s1's 50% is confirmed by both: applied
    before, after = out.close[:, 0], out.close[:, 1]
    assert np.isfinite(before[:20]).all() and np.isnan(before[20:]).all()
    assert np.isnan(after[:20]).all() and np.isfinite(after[20:]).all()
    fwd = forward_returns(out.open)
    assert np.isnan(fwd[18, :2]).all()  # the one return spanning the suspect ex-date (19 -> 20)
    assert fwd[17, 0] == 0 and fwd[19, 1] == 0  # returns on either side are intact
    assert fwd[28, 1] == pytest.approx(-np.log1p(-0.01))  # later dividends still apply
    assert fwd[18, 2] == pytest.approx(-np.log1p(-0.5))
    assert out.manifest["total_return"]["splits"] == [["s0~1", str(raw.timestamps[20])]]


def test_suspect_is_judged_per_event_and_a_yield_of_one_always_splits():
    n = 10
    raw = daily_panel(np.full((n, 3), 10.0), opens=np.full((n, 3), 10.0))
    sessions = np.datetime64("2024-01-01") + np.arange(n)
    cover = {s: (date(2024, 1, 1), date(2024, 1, 10)) for s in raw.symbols}
    grid = dividends.dividend_grid(
        sessions,
        raw.symbols,
        cover,
        [
            ("s0", date(2024, 1, 5), 0.02, True),  # small, unconfirmed
            ("s0", date(2024, 1, 5), 0.30, False),  # large, confirmed, same session
            ("s1", date(2024, 1, 5), 1.0, False),  # confirmed but no finite factor
        ],
    )
    out = dividends.total_return(raw, grid, SUSPECT)
    assert out.symbols == ("s0", "s1", "s1~1", "s2")
    fwd = forward_returns(out.open)
    # s0's session (index 4) compounds both events and applies them: the small unconfirmed one
    # does not taint the confirmed special.
    assert fwd[2, 0] == pytest.approx(-np.log(1 - (1.02 * 1.30 - 1)), rel=1e-12)


def test_a_real_snapshot_in_synthetic_mode_is_refused_under_a_total_return_spec():
    import asyncio

    from src.intelligence.research import runner as runner_mod

    spec = parse_spec_text(
        FAMILY.replace(
            '  end_exclusive: "2025-12-24"\n',
            '  end_exclusive: "2025-12-24"\n  total_return: {suspect_yield: 0.1}\n',
        )
    )
    raw, _, _, _ = _hy_daily(n=50)
    real = dataclasses.replace(raw, manifest={"source": snapshot.PRICE_SOURCE})
    with pytest.raises(ValueError, match="real mode"):
        asyncio.run(runner_mod._analysis_panel(spec, None, real=False, panel=real))


def test_grid_aligns_by_name_and_a_missing_symbol_is_uncovered():
    raw, grid, _, _ = _hy_daily(n=50)
    narrowed = panel_mod.select_symbols(raw, ["s4", "s1"])
    out = dividends.total_return(narrowed, grid, SUSPECT)
    assert out.symbols == ("s1", "s4")
    aligned = grid.aligned(("s4", "zz"))
    np.testing.assert_array_equal(aligned.div_yield[:, 0], grid.div_yield[:, 4])
    assert not aligned.div_covered[:, 1].any()
    with pytest.raises(ValueError, match="sessions"):
        dividends.total_return(raw, _grid(raw.symbols, 49), SUSPECT)


def test_identity_grid_changes_nothing():
    raw, _, _, _ = _hy_daily(n=50)
    out = dividends.total_return(raw, dividends.no_dividends(raw), SUSPECT)
    np.testing.assert_array_equal(out.close, raw.close)
    assert out.symbols == raw.symbols


def test_snapshot_without_dividends_keeps_its_bytes_and_one_with_them_round_trips(tmp_path):
    raw, grid, _, _ = _hy_daily(n=50)
    plain = panel_mod.save(raw, tmp_path / "a")
    assert not list(plain.glob("div_*.npy")) and dividends.load_grid(plain) is None
    assert plain.name == panel_mod.save(raw, tmp_path / "c", None).name
    with_div = panel_mod.save(raw, tmp_path / "b", grid.arrays())
    loaded = dividends.load_grid(with_div)
    assert loaded.symbols == raw.symbols
    np.testing.assert_array_equal(loaded.div_yield, grid.div_yield)
    assert panel_mod.load(with_div).symbols == raw.symbols


@pytest.mark.parametrize("seed", range(5))
def test_future_dividend_facts_never_move_an_earlier_price(seed):
    """Causality of the transform itself (S3's probe perturbs prices, not the dividend grid)."""
    rng = np.random.default_rng(seed)
    raw, g, _, _ = _hy_daily(n=300, seed=seed)
    t = int(rng.integers(50, 250))
    late = np.arange(300)[:, None] > t
    future = DividendGrid(
        g.symbols,
        np.where(late, rng.uniform(0, 0.3, g.div_yield.shape), g.div_yield),
        np.where(late, rng.uniform(0, 0.3, g.div_yield.shape), g.div_unconfirmed_yield),
        np.where(late, rng.random(g.div_covered.shape) > 0.3, g.div_covered),
    )
    base = dividends.total_return(raw, g, SUSPECT)
    moved = dividends.total_return(raw, future, SUSPECT)
    for j, sym in enumerate(base.symbols):
        if sym in moved.symbols:
            k = moved.symbols.index(sym)
            np.testing.assert_array_equal(moved.close[: t + 1, k], base.close[: t + 1, j])
            np.testing.assert_array_equal(moved.open[: t + 1, k], base.open[: t + 1, j])


def test_total_return_is_hashed_only_when_set():
    """Specs written before todo 428 (family 1, book_v1) keep their recorded hashes."""
    with_tr = FAMILY.replace(
        '  end_exclusive: "2025-12-24"\n',
        '  end_exclusive: "2025-12-24"\n  total_return: {suspect_yield: 0.1}\n',
    )
    assert parse_spec_text(with_tr).panel.total_return.suspect_yield == 0.1
    assert _hash(with_tr) != _hash(FAMILY)
    assert parse_spec_text(FAMILY).panel.total_return is None
