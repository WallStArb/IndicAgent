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


def test_vendor_wide_threshold_and_other_investigation() -> None:
    ok = nc.AgreementCounts(10_000, 9_960, 9_990, {"rounding": 40})
    wide = nc.vendor_wide([ok, ok])
    assert wide.verdict == "ok" and not wide.investigate
    bad = nc.AgreementCounts(10_000, 9_900, 9_950, {"other": 100})
    out = nc.vendor_wide([bad])
    assert out.verdict == "stop" and out.investigate  # 99 percent < 99.5; other 1 percent > 0.5


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
    stopped = nc.close_partition(cells, out, stop_eras=[2011])
    assert isinstance(stopped, nc.Partition) and stopped.counts["stop"] == 1
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
