"""align (184 B3a-c, design D4 and D7 guards 1 and 2): the only research node with two clocks."""

import numpy as np
import pytest

from src.intelligence.research.align import (
    align,
    align_causality_probe,
    align_index,
    check_alignment,
    gather,
)
from src.intelligence.research.clock import closes_at
from src.intelligence.research.guards import (
    GuardFailure,
    causality_probe_array,
    memory_check_array,
)
from tests.unit.research import mtf_fixtures as fx

NAT = np.datetime64("NaT", "ns")
ROWS = np.array([10, 40, 70, 95])


def _t(minutes):
    """Synthetic availability: minutes after a fixed UTC instant (NaT where None)."""
    base = np.datetime64("2024-01-02T15:00", "ns")
    return np.array(
        [NAT if m is None else base + np.timedelta64(m, "m") for m in minutes],
        dtype="datetime64[ns]",
    )


def _closes(panel):
    return closes_at(panel.timestamps, panel.valid, panel.tf, panel.bars_per_session)


def _x(seed=0, n=120, m=4):
    return np.random.default_rng(seed).normal(0, 0.01, (n, m))


def _shift_early(avail):
    """A planted leak: each source row declared available at the previous row's close."""
    out = np.empty_like(avail)
    out[1:] = avail[:-1]
    out[0] = avail[0] - np.timedelta64(1, "D")
    return out


# --- D4 semantics -----------------------------------------------------------------------------


def test_latest_finite_within_max_age_else_nan():
    src = np.array([[1.0, 10.0], [2.0, np.nan], [np.nan, np.nan], [np.nan, 40.0]])
    s_av = _t([0, 10, 20, 30])
    d_av = _t([30])
    # Symbol 0: latest candidate row 3 is NaN; row 1 is finite, two rows back.
    np.testing.assert_array_equal(align(src, s_av, d_av, 2), [[2.0, 40.0]])
    np.testing.assert_array_equal(align(src, s_av, d_av, 1), [[np.nan, 40.0]])


def test_weekend_does_not_age_a_daily_value():
    daily = fx.daily_grid([fx.BEFORE_DST_SPRING, fx.DST_SPRING])
    hourly = fx.intraday_grid("1h", [fx.DST_SPRING])
    out = align(daily.close, _closes(daily), _closes(hourly), 0)
    # Monday's rows before the close read Friday's value at age 0.
    np.testing.assert_array_equal(out[:-1], np.repeat(daily.close[:1], 6, axis=0))
    np.testing.assert_array_equal(out[-1], daily.close[1])


def test_equal_availability_is_causal():
    src = np.array([[1.0], [2.0]])
    np.testing.assert_array_equal(align(src, _t([0, 10]), _t([10, 9]), 0), [[2.0], [1.0]])


def test_nat_source_never_candidate_and_nat_destination_is_nan():
    src = np.array([[1.0, 5.0], [2.0, 6.0], [3.0, 7.0]])
    s_av = _t([0, None, 20])
    out = align(src, s_av, _t([15, None, 25]), 5)
    np.testing.assert_array_equal(out[0], [1.0, 5.0])  # row 1 (NaT) is skipped
    assert np.isnan(out[1]).all()
    np.testing.assert_array_equal(out[2], [3.0, 7.0])


def test_age_grid_rows_counts_a_missing_final_source_bar():
    panel = fx.intraday_grid("15m", [fx.BEFORE_DST_FALL, fx.DST_FALL])
    rows = fx.session_rows(panel, fx.BEFORE_DST_FALL)
    last = int(rows[-1])
    src_panel = fx.drop_rows(panel, [last])
    s_av = _closes(src_panel)
    assert np.isnat(s_av[last])
    src = src_panel.close.copy()
    src[last + 1, 0] = np.nan  # next session's first bar missing for symbol 0
    d_av = s_av[[last + 1]]
    # Symbol 0's latest finite value is row last-1: two grid rows back, one valid row between.
    assert np.isnan(align(src, s_av, d_av, 1)[0, 0])
    assert align(src, s_av, d_av, 2)[0, 0] == src[last - 1, 0]
    assert align(src, s_av, d_av, 1)[0, 1] == src[last + 1, 1]


def test_broadcast_series_to_n_symbols():
    src = np.array([[1.0], [2.0], [3.0]])
    out = align(src, _t([0, 10, 20]), _t([5, 25]), 1, n_symbols=3)
    assert out.shape == (2, 3)
    np.testing.assert_array_equal(out, [[1.0] * 3, [3.0] * 3])
    with pytest.raises(ValueError, match="cannot fill"):
        align(np.ones((3, 2)), _t([0, 10, 20]), _t([5]), 1, n_symbols=3)


def test_destination_before_first_source_is_nan():
    out = align(np.array([[1.0], [2.0]]), _t([10, 20]), _t([0, 9, 10]), 3)
    assert np.isnan(out[:2]).all() and out[2, 0] == 1.0


def test_source_unchanged_and_dtype_kept():
    src = _x().astype(np.float32)
    src[5, 1] = np.nan
    before = src.copy()
    av = _t(range(len(src)))
    out = align(src, av, av, 2)
    np.testing.assert_array_equal(src, before)
    assert out.dtype == np.float32
    assert not np.shares_memory(out, src)


def test_rejects_bad_inputs():
    src = np.ones((3, 1))
    with pytest.raises(ValueError, match="non-decreasing"):
        align(src, _t([0, 20, 10]), _t([30]), 1)
    with pytest.raises(ValueError, match="max_age_rows"):
        align(src, _t([0, 10, 20]), _t([30]), -1)
    with pytest.raises(ValueError, match="datetime64"):
        align(src, np.arange(3), _t([30]), 1)
    with pytest.raises(ValueError, match="shape"):
        align(src, _t([0, 10]), _t([30]), 1)


# --- one implementation: index, gather, check_alignment ----------------------------------------


def _index_case():
    src = _x(n=60, m=3)
    src[np.random.default_rng(3).random(src.shape) < 0.2] = np.nan
    s_av = _t(range(0, 600, 10))
    d_av = _t(range(5, 600, 7))
    return src, s_av, d_av


def test_index_is_int32_and_gather_equals_align_bit_for_bit():
    src, s_av, d_av = _index_case()
    idx = align_index(np.isfinite(src), s_av, d_av, 2)
    assert idx.dtype == np.int32 and idx.shape == (len(d_av), 3)
    out = align(src, s_av, d_av, 2)
    np.testing.assert_array_equal(idx == -1, np.isnan(out))
    assert gather(src, idx).tobytes() == out.tobytes()


def test_index_check_alignment_passes_true_and_rejects_future_and_stale():
    src, s_av, d_av = _index_case()
    idx = align_index(np.isfinite(src), s_av, d_av, 2)
    every = np.arange(len(d_av))
    check_alignment(idx, s_av, d_av, 2, every)

    # A cell reading the latest available row, pointed one row later: a future row.
    t, j = (int(v) for v in np.argwhere(idx[:-1] >= 0)[-1])
    cand = int(np.searchsorted(s_av, d_av[t], side="right") - 1)
    later = idx.copy()
    later[t, j] = cand + 1
    with pytest.raises(GuardFailure, match=f"lookahead: destination row {t}"):
        check_alignment(later, s_av, d_av, 2, every)

    stale = idx.copy()
    stale[t, j] = cand - 3
    with pytest.raises(GuardFailure, match=f"max age: destination row {t}"):
        check_alignment(stale, s_av, d_av, 2, every)
    # Rows outside the scored set are not checked.
    check_alignment(stale, s_av, d_av, 2, np.delete(every, t))


def test_index_check_alignment_on_daily_into_intraday():
    daily = fx.daily_grid()
    hourly = fx.intraday_grid("1h")
    s_av, d_av = _closes(daily), _closes(hourly)
    idx = align_index(np.isfinite(daily.close), s_av, d_av, 1)
    check_alignment(idx, s_av, d_av, 1, np.arange(len(d_av)))


# --- D7 guard 1: planted leak ------------------------------------------------------------------


def test_leak_same_clock_fails_causality_probe_array():
    x = _x()
    true = _t(range(0, 15 * len(x), 15))
    leaky = _shift_early(true)
    causality_probe_array(lambda a: align(a, true, true, 3), x, ROWS, seed=0)
    with pytest.raises(GuardFailure, match="lookahead"):
        causality_probe_array(lambda a: align(a, leaky, true, 3), x, ROWS, seed=0)


def test_leak_on_real_grid_fails_causality_probe_array():
    panel = fx.intraday_grid("15m")
    true = _closes(panel)
    x = np.log(panel.close)
    causality_probe_array(lambda a: align(a, true, true, 2), x, ROWS, seed=0)
    leaky = true.copy()
    known = np.flatnonzero(~np.isnat(true))
    leaky[known[1:]] = true[known[:-1]]
    with pytest.raises(GuardFailure, match="lookahead"):
        causality_probe_array(lambda a: align(a, leaky, true, 2), x, ROWS, seed=0)


def test_leak_cross_clock_align_causality_probe():
    daily = fx.daily_grid()
    hourly = fx.intraday_grid("1h")
    s_av, d_av = _closes(daily), _closes(hourly)
    rows = np.arange(0, len(d_av), 3)
    align_causality_probe(daily.close, s_av, d_av, 1, rows, seed=0)
    leaky = _shift_early(s_av)
    with pytest.raises(GuardFailure, match="lookahead"):
        align_causality_probe(
            daily.close,
            s_av,
            d_av,
            1,
            rows,
            seed=0,
            fn=lambda a: align(a, leaky, d_av, 1),
        )


# --- D7 guard 2: daily value on an intraday clock ----------------------------------------------


@pytest.mark.parametrize("tf", ["1h", "5m"])
@pytest.mark.parametrize("day", [fx.HALF_DAY, fx.DST_SPRING, fx.DST_FALL])
def test_daily_on_intraday_previous_session_until_the_last_slot(tf, day):
    daily = fx.daily_grid()
    intra = fx.intraday_grid(tf)
    out = align(daily.close, _closes(daily), _closes(intra), 0)
    k = list(fx.ALL_SESSIONS).index(day)
    rows = fx.session_rows(intra, day)
    traded = rows[intra.valid[rows]]
    assert len(traded) >= 4
    np.testing.assert_array_equal(
        out[traded[:-1]], np.repeat(daily.close[[k - 1]], len(traded) - 1, 0)
    )
    np.testing.assert_array_equal(out[traded[-1]], daily.close[k])
    # The last traded slot closes exactly at the daily close.
    assert _closes(intra)[traded[-1]] == _closes(daily)[k]
    # Half-day slots after the early close are untraded: NaN.
    assert np.isnan(out[rows[~intra.valid[rows]]]).all()


# --- memory ------------------------------------------------------------------------------------


def test_memory_reach_is_at_most_max_age_rows():
    x = _x(n=120, m=3)
    x[(np.arange(120) % 4 == 1) | (np.arange(120) % 4 == 2)] = np.nan
    av = _t(range(120))
    rows = np.array([8, 40, 72, 100])
    reach = memory_check_array(lambda a: align(a, av, av, 3), x, rows, declared=3)
    assert reach == 2
    reach = memory_check_array(lambda a: align(a, av, av, 1), x, rows, declared=1)
    assert reach == 1
