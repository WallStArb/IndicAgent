"""Massive load checks, name-level half: pure math on synthetic fixtures (design 8a, stage C)."""

from __future__ import annotations

import math
from datetime import date, timedelta

import numpy as np
import pytest

from src.intelligence.bars import massive_name_checks as nc
from src.intelligence.bars.massive_load_checks import VacuousCheckError


def _ohlc(close: np.ndarray) -> nc.Ohlc:
    return (close * 0.99, close * 1.01, close * 0.98, close.copy())


def test_agree_mask_half_increment_plus_one_bp() -> None:
    inc = np.array([10.00, 10.00, 10.00, 10.00])
    massive = np.array([10.005, 10.0051, 10.0105, 20.0])  # 0.5 cent + 1 bp of 10 = 0.006
    scale = np.array([1.0, 1.0, 1.0, 2.0])
    got = nc.agree_mask(massive, scale, inc, 0.01)
    assert got.tolist() == [True, True, False, True]


def test_agree_mask_uses_the_given_factor_not_a_fitted_one() -> None:
    # a 2:1 split recorded: massive 20 / factor 2 agrees with incumbent 10; with factor 1 it does not
    assert nc.agree_mask(np.array([20.0]), np.array([2.0]), np.array([10.0]), 0.01).all()
    assert not nc.agree_mask(np.array([20.0]), np.array([1.0]), np.array([10.0]), 0.01).any()


def test_price_agreement_counts_and_classes() -> None:
    n = 200
    close = np.linspace(20, 30, n)
    inc = _ohlc(close)
    massive = list(_ohlc(close))
    # 4 bars off by a few cents: rounding; 2 bars with only the close wrong: last_print
    for i in range(4):
        massive[3][i] = close[i] + 0.012
        massive[0][i] = massive[0][i] + 0.012
        massive[1][i] = massive[1][i] + 0.012
        massive[2][i] = massive[2][i] + 0.012
    for i in range(4, 6):
        massive[3][i] = close[i] + 0.5
    counts = nc.price_agreement(tuple(massive), np.ones(n), inc, 0.01)
    assert counts.n_matched == n and counts.n_agree == n - 6
    assert counts.n_class == {"rounding": 4, "last_print": 2}
    assert not nc.name_era_agreement_ok(counts)  # 194/200 = 97 percent


def test_price_agreement_time_shift_class() -> None:
    n = 50
    close = np.cumsum(np.ones(n)) + 20
    massive = _ohlc(close)
    prev = _ohlc(np.roll(close, 1))
    inc = tuple(a.copy() for a in massive)
    for k in range(4):
        inc[k][10] = prev[k][10]  # the incumbent's bar 10 is Massive's previous bar
    counts = nc.price_agreement(massive, np.ones(n), inc, 0.01, massive_prev_raw=prev)
    assert counts.n_agree == n - 1 and counts.n_class == {"time_shift": 1}


def test_price_agreement_scale_class() -> None:
    n = 100
    close = np.full(n, 40.0)
    inc = _ohlc(close)
    massive = _ohlc(close * 1.05)  # a name whose whole year sits 5 percent off
    counts = nc.price_agreement(massive, np.ones(n), inc, 0.01)
    assert counts.n_agree == 0 and counts.n_class == {"scale": n}


def test_vacuous_inputs_raise() -> None:
    empty = np.empty(0)
    with pytest.raises(VacuousCheckError):
        nc.price_agreement((empty,) * 4, empty, (empty,) * 4, 0.01)
    with pytest.raises(VacuousCheckError):
        nc.name_era_agreement_ok(nc.AgreementCounts(0, 0, 0))
    with pytest.raises(VacuousCheckError):
        nc.vendor_wide([])
    with pytest.raises(VacuousCheckError):
        nc.scale_check(empty, empty, empty)


def _counts(n: int, ret_agree_share: float, level_share: float, cls=None) -> nc.AgreementCounts:
    pairs = n - 1
    return nc.AgreementCounts(
        n,
        int(n * level_share),
        int(n * level_share),
        cls or {},
        pairs,
        int(pairs * ret_agree_share),
        n,
        n,
    )


def test_vendor_wide_stops_only_on_return_residual() -> None:
    clean = _counts(10_000, 0.9999, 0.999)
    out = nc.vendor_wide([clean], [clean])
    assert out.verdict == "ok" and not out.investigate
    # level agreement low but returns agree: ok, investigate printed with the class mix
    level_low = _counts(10_000, 0.9999, 0.95, {"last_print": 400, "other": 100})
    out = nc.vendor_wide([level_low], [level_low])
    assert (
        out.verdict == "ok"
        and out.investigate
        and out.class_mix == {"last_print": 400, "other": 100}
    )
    bad = _counts(10_000, 0.99, 0.99)
    assert nc.vendor_wide([bad], [bad]).verdict == "stop"  # residual 1 percent > 0.5
    with pytest.raises(VacuousCheckError):
        nc.vendor_wide([])
    with pytest.raises(VacuousCheckError):
        nc.vendor_wide([nc.AgreementCounts(5, 5, 5)])  # matched bars but no consecutive pair


def test_return_agreement_is_invariant_to_a_constant_level_factor() -> None:
    rng = np.random.default_rng(1)
    n = 300
    close = 40 * np.exp(np.cumsum(rng.normal(0, 0.003, n)))
    inc = _ohlc(close)
    pos = np.arange(n)
    for factor in (1.0, 1.28, 0.93):  # an incumbent dividend or spin-off adjustment
        massive = tuple(a * factor for a in _ohlc(close))
        pairs, ok, bars, bar_ok = nc.return_agreement(massive, inc, pos, pos, 0.01)
        assert (pairs, ok, bars, bar_ok) == (n - 1, n - 1, n, n)
        level = nc.price_agreement(
            massive, np.ones(n), inc, 0.01, massive_pos=pos, incumbent_pos=pos
        )
        assert level.ret_share == 1.0
        if factor != 1.0:
            assert level.share == 0.0  # the level comparison fails by construction


def test_return_agreement_detects_a_real_return_difference_and_skips_gaps() -> None:
    n = 50
    close = np.linspace(20, 25, n)
    inc = _ohlc(close)
    bad = _ohlc(close)
    bad[3][20] = close[20] * 1.01
    pos = np.arange(n)
    pairs, ok, _, _ = nc.return_agreement(bad, inc, pos, pos, 0.01)
    assert pairs == n - 1 and ok == n - 1 - 2  # the pairs into and out of bar 20
    # a bar missing from the incumbent breaks adjacency: that pair is not counted
    inc_pos = pos.copy()
    inc_pos[10:] += 1
    pairs, _, _, _ = nc.return_agreement(inc, inc, pos, inc_pos, 0.01)
    assert pairs == n - 2


def test_aggregate_bars_to_sessions() -> None:
    t = np.arange(6, dtype=np.int64)
    key = np.array([1, 1, 1, 2, 2, 2])
    o = np.array([10.0, 11, 12, 20, 21, 22])
    h = o + 1
    low = o - 1
    c = o + 0.5
    k, (so, sh, sl, sc), sv, st = nc.aggregate_bars_to_sessions(t, key, (o, h, low, c), np.ones(6))
    assert k.tolist() == [1, 2] and so.tolist() == [10, 20] and sh.tolist() == [13, 23]
    assert sl.tolist() == [9, 19] and sc.tolist() == [12.5, 22.5] and sv.tolist() == [3, 3]
    assert st.tolist() == [0, 3]
    empty = nc.aggregate_bars_to_sessions(t[:0], key[:0], (o[:0],) * 4, o[:0])
    assert len(empty[0]) == 0


def test_scale_class() -> None:
    assert nc.scale_class(0.0002, 0.001, 1.0, 1.0) == ""
    assert nc.scale_class(0.25, 0.002, 0.0, 1.0) == "adjustment_level"  # 1.28x, not a split ratio
    assert nc.scale_class(math.log(2.0), 0.002, 0.0, 1.0) == "split_like_level"
    assert nc.scale_class(-math.log(2.0), 0.002, 0.0, 1.0) == "split_like_level"
    # drifting offset with agreeing returns
    assert nc.scale_class(0.0, 0.02, 0.5, 0.999) == "level_drift"
    # level and returns both disagree: no class, a real disagreement
    assert nc.scale_class(0.0, 0.02, 0.5, 0.5) == ""
    assert nc.split_like_ratio(1.28) is None and nc.split_like_ratio(1.0) is None


def test_ledger_witnesses_from_frozen_data_only() -> None:
    w = nc.frozen_split_witness(2.0, [("2010-05-04", 2.0)])
    assert w is not None and w.kind == "filing_dated_corporate_action" and w.supports == "massive"
    assert nc.frozen_split_witness(0.5, [("2010-05-04", 2.0)]) is not None  # the inverse
    assert nc.frozen_split_witness(1.28, [("2010-05-04", 2.0)]) is None
    assert nc.frozen_split_witness(2.0, []) is None
    assert nc.massive_tape_witness(100.0, 50.0, 2.0, "2010-05-04") is not None
    assert nc.massive_tape_witness(100.0, 99.0, 2.0, "2010-05-04") is None
    assert nc.massive_tape_witness(0.0, 50.0, 2.0, "2010-05-04") is None


def test_clean_vendor_passes_every_name_level_check() -> None:
    """Calibration: Massive equal to the incumbent passes agreement, scale, identity and closure."""
    rng = np.random.default_rng(2)
    n = 400
    close = 30 * np.exp(np.cumsum(rng.normal(0, 0.004, n)))
    inc = _ohlc(close)
    massive = _ohlc(close)
    pos = np.arange(n)
    counts = nc.price_agreement(massive, np.ones(n), inc, 0.01, massive_pos=pos, incumbent_pos=pos)
    assert counts.share == 1.0 and counts.ret_share == 1.0 and counts.intra_share == 1.0
    assert nc.name_era_agreement_ok(counts)
    median = nc.scale_check(massive[3], np.ones(n), inc[3])
    assert nc.scale_ok(median)
    assert (
        nc.scale_class(median, nc.level_dispersion(massive[3], np.ones(n), inc[3]), 1.0, 1.0) == ""
    )
    assert nc.identity_resolved(nc.identity_correlation(massive[3], inc[3]))
    assert nc.vendor_wide([counts], [counts]).verdict == "ok"
    part = nc.close_partition([("A", 2010)], {("A", 2010): ("pass", "")}, stop_eras={})
    assert isinstance(part, nc.Partition) and part.counts == {"pass": 1, "gap_list": 0, "stop": 0}


def test_scale_check_uses_given_factor() -> None:
    close = np.array([50.0, 51.0, 52.0])
    assert nc.scale_ok(nc.scale_check(close * 4, np.full(3, 4.0), close))
    drifted = nc.scale_check(close * 1.002, np.ones(3), close)
    assert not nc.scale_ok(drifted)
    assert nc.scale_ok(nc.scale_check(close * 1.0009, np.ones(3), close))


def test_identity_correlation() -> None:
    rng = np.random.default_rng(3)
    a = 20 * np.exp(np.cumsum(rng.normal(0, 0.01, 60)))
    b = 40 * np.exp(np.cumsum(rng.normal(0, 0.01, 60)))
    assert nc.identity_resolved(nc.identity_correlation(a, a * 1.0003))
    assert not nc.identity_resolved(nc.identity_correlation(a, b))  # two different securities
    assert math.isnan(nc.identity_correlation(a[:2], a[:2]))
    assert not nc.identity_resolved(math.nan)


def test_preclassification_and_alpaca_epoch_seam() -> None:
    assert nc.preclassify_name_era(0, False) == "no_action"
    assert nc.preclassify_name_era(2, False) == "splits_only"
    assert nc.preclassify_name_era(2, True) == "non_split_adjustment"
    split = date(2020, 8, 28)
    assert nc.alpaca_epoch_seam_possible(date(2020, 6, 1), date(2020, 12, 1), [split])
    assert not nc.alpaca_epoch_seam_possible(date(2020, 9, 1), date(2020, 12, 1), [split])
    assert not nc.alpaca_epoch_seam_possible(None, None, [split])


def test_partition_closes_and_sums() -> None:
    cells = [("A", 2010), ("B", 2010), ("A", 2011)]
    out = {c: ("pass", "") for c in cells}
    out[("B", 2010)] = ("gap_list", "price_agreement")
    part = nc.close_partition(cells, out)
    assert isinstance(part, nc.Partition)
    assert part.counts == {"pass": 2, "gap_list": 1, "stop": 0} and part.n_mapped_cells == 3
    stopped = nc.close_partition(cells, out, stop_eras={2011: "return_residual"})
    assert isinstance(stopped, nc.Partition) and stopped.counts["stop"] == 1
    assert stopped.cells[("A", 2011)] == ("stop", "systemic_stop:return_residual")
    out[("B", 2010)] = ("gap_list", "not_listed_in_era")
    exempt = nc.close_partition(cells, out, stop_eras={2010: "volume_step"})
    assert isinstance(exempt, nc.Partition)
    assert exempt.cells[("B", 2010)] == ("gap_list", "not_listed_in_era")  # loads nothing
    assert exempt.cells[("A", 2010)][0] == "stop"
    assert sum(stopped.counts.values()) == stopped.n_mapped_cells


def test_partial_run_never_emits_a_table() -> None:
    cells = [("A", 2010), ("B", 2010)]
    result = nc.close_partition(cells, {("A", 2010): ("pass", "")})
    assert isinstance(result, nc.PartialRun)
    assert result.n_expected == 2 and result.n_judged == 1 and result.missing == (("B", 2010),)


def test_partition_rejects_bad_outcome_and_unexpected_cell() -> None:
    with pytest.raises(ValueError):
        nc.close_partition([("A", 2010)], {("A", 2010): ("maybe", "")})
    with pytest.raises(ValueError):
        nc.close_partition([("A", 2010)], {("A", 2010): ("pass", ""), ("Z", 2010): ("pass", "")})
    with pytest.raises(VacuousCheckError):
        nc.close_partition([], {})


def test_ledger_precedence_and_third_witness() -> None:
    w = nc.Witness
    row = nc.ledger_verdict(
        "OKE",
        "2005",
        "ibkr scale",
        [
            w("massive_continuity", "massive", "m"),
            w("filing_dated_corporate_action", "incumbent", "f"),
        ],
        nc.DISPUTE_MASSIVE_VS_IBKR,
        "s1",
    )
    assert row.decided_by == "filing_dated_corporate_action" and row.verdict == "massive_defect"
    only_alpaca = nc.ledger_verdict(
        "X", "2020", "d", [w("alpaca_2016_plus", "massive", "a")], nc.DISPUTE_MASSIVE_VS_IBKR, "s1"
    )
    assert only_alpaca.verdict == "unresolved" and only_alpaca.decided_by == "none"
    internal = nc.ledger_verdict(
        "Y",
        "2005",
        "d",
        [w("ibkr_1d_official_close", "massive", "i")],
        nc.DISPUTE_MASSIVE_INTERNAL,
        "s1",
    )
    assert internal.verdict == "unresolved"  # circular inside a Massive-internal check
    vs_ibkr = nc.ledger_verdict(
        "Y",
        "2005",
        "d",
        [w("ibkr_1d_official_close", "massive", "i")],
        nc.DISPUTE_MASSIVE_VS_IBKR,
        "s1",
    )
    assert vs_ibkr.verdict == "incumbent_defect"
    split = nc.ledger_verdict(
        "Z",
        "2005",
        "d",
        [
            w("exchange_official_close", "massive", "e"),
            w("exchange_official_close", "incumbent", "e2"),
        ],
        nc.DISPUTE_MASSIVE_VS_IBKR,
        "s1",
    )
    assert split.verdict == "unresolved"


def test_dispute_window() -> None:
    sessions = [date(2020, 1, 1) + timedelta(days=i) for i in range(60)]
    win = nc.dispute_window_sessions(sessions, date(2020, 1, 31))
    assert len(win) == 21 and date(2020, 1, 31) in win
    assert nc.dispute_window_sessions(sessions, date(2021, 1, 1)) == []
    edge = nc.dispute_window_sessions(sessions, date(2020, 1, 3))
    assert edge[0] == sessions[0]
