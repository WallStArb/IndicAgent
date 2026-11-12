"""ops_massive_load_checks stage C: name-level comparison on synthetic bars (no database)."""

from __future__ import annotations

from datetime import date

import numpy as np

from scripts.ops.bars import ops_massive_load_checks as runner
from src.intelligence.bars import massive_name_checks as nc
from src.intelligence.bars.sessions import nyse_sessions
from src.intelligence.bars.split_rescale import SplitFactor

NS = 1_000_000_000


def _daily(days: list[date], close: np.ndarray) -> runner.Bars:
    keys = np.array(days, dtype="datetime64[D]")
    ohlc = (close * 0.99, close * 1.01, close * 0.98, close.copy())
    return runner.Bars(
        keys.astype("datetime64[ns]").astype("int64"),
        keys,
        ohlc,
        np.full(len(days), 1e6),
        None,
        None,
    )


def _days(n: int) -> list[date]:
    return sorted(nyse_sessions(date(2010, 3, 1), date(2010, 6, 30)))[:n]


def test_rth_mask_cuts_outside_session() -> None:
    sessions = nyse_sessions(date(2010, 3, 1), date(2010, 3, 5))
    open_ns = int(sessions[date(2010, 3, 1)][0].timestamp()) * NS
    stamps = np.array(
        [open_ns - 300 * NS, open_ns, open_ns + 300 * NS * 77, open_ns + 300 * NS * 78]
    )
    assert runner.rth_mask(stamps, sessions).tolist() == [False, True, True, False]


def test_compare_arm_applies_the_frozen_split_and_counts_matches() -> None:
    days = _days(40)
    incumbent_close = np.linspace(20, 30, 40)
    inc = _daily(days, incumbent_close)
    massive = _daily(days, incumbent_close * 2.0)  # unadjusted: a 2:1 split after the window
    split = [SplitFactor(date(2010, 12, 31), 2.0)]
    ok = runner.compare_arm("1d", "ibkr", massive, inc, split, {})
    assert ok is not None and ok.n_matched == 40 and ok.n_agree == 40
    assert abs(ok.median_log_ratio) < 1e-12
    # without the recorded split the same data is a scale disagreement, never silently refitted
    wrong = runner.compare_arm("1d", "ibkr", massive, inc, [], {})
    assert wrong is not None and wrong.n_agree == 0 and wrong.classes == {"scale": 40}


def test_compare_arm_counts_unmatched_and_zero_volume_incumbent_bars() -> None:
    days = _days(10)
    close = np.linspace(20, 21, 10)
    inc = _daily(days, close)
    inc_volume = inc.volume.copy()
    inc_volume[2] = 0.0  # a zero-volume incumbent bar: counted, never assumed no-trade
    inc = runner.Bars(inc.t_ns, inc.key, inc.ohlc, inc_volume, None, None)
    massive = _daily(days[:8], close[:8])  # Massive lacks the last two sessions
    result = runner.compare_arm("1d", "ibkr", massive, inc, [], {})
    assert result is not None
    assert result.n_matched == 7  # 8 massive sessions minus the zero-volume one
    assert result.n_incumbent_zero_volume == 1
    assert result.n_incumbent_traded_missing == 2 and len(result.missing_listed) == 2


def test_compare_arm_with_no_overlap_reports_zero_not_a_pass() -> None:
    days = _days(10)
    close = np.linspace(20, 21, 10)
    result = runner.compare_arm(
        "1d", "ibkr", _daily(days[:5], close[:5]), _daily(days[5:], close[5:]), [], {}
    )
    assert result is not None and result.n_matched == 0
    outcome = runner.judge_name_era({"1d": result, "5m": None}, nc.ERA_NO_ACTION, True)
    assert outcome == (nc.OUTCOME_GAP, "no_incumbent_overlap")


def _arm(
    matched: int, agree: int, median: float, corr: float, *, ret: float = 1.0, cls: str = ""
) -> runner.ArmResult:
    pairs = matched - 1
    return runner.ArmResult(
        matched,
        agree,
        agree,
        {},
        median,
        corr,
        0,
        0,
        [],
        pairs,
        int(pairs * ret),
        matched,
        matched,
        0.0,
        cls,
    )


def test_judge_name_era_outcomes() -> None:
    good = _arm(250, 250, 0.0, 0.99)
    assert runner.judge_name_era({"1d": good}, nc.ERA_NO_ACTION, True) == (nc.OUTCOME_PASS, "")
    assert runner.judge_name_era({"1d": good}, nc.ERA_NO_ACTION, False)[1] == "not_listed_in_era"
    assert runner.judge_name_era({"1d": good}, nc.ERA_NON_SPLIT, True)[1] == (
        "non_split_adjustment_convention"
    )
    unresolved = _arm(250, 250, 0.0, 0.5)
    assert runner.judge_name_era({"1d": unresolved}, nc.ERA_NO_ACTION, True)[1] == (
        "identity_unresolved"
    )
    low = _arm(250, 250, 0.0, 0.99, ret=0.96)  # returns agree on 96 percent
    assert runner.judge_name_era({"1d": low}, nc.ERA_NO_ACTION, True)[1] == "price_agreement_1d"


def test_judge_name_era_level_classes() -> None:
    # a constant level factor with agreeing returns passes, listed in the scale listing
    adj = _arm(250, 0, 0.25, 0.99, cls=nc.SCALE_ADJUSTMENT_LEVEL)
    assert runner.judge_name_era({"1d": adj}, nc.ERA_NO_ACTION, True) == (
        nc.OUTCOME_PASS,
        "adjustment_level_listed",
    )
    drift = _arm(250, 100, 0.0, 0.99, cls=nc.SCALE_LEVEL_DRIFT)
    assert runner.judge_name_era({"5m": drift}, nc.ERA_NO_ACTION, True)[1] == "level_drift_listed"
    # a stable offset that reads as a split ratio is a candidate missing split: gap list
    split = _arm(250, 0, 0.6931, 0.99, cls=nc.SCALE_SPLIT_LIKE)
    assert runner.judge_name_era({"1d": split}, nc.ERA_NO_ACTION, True) == (
        nc.OUTCOME_GAP,
        "scale_factor_split_like_1d",
    )


def test_rth_1d_is_built_from_the_regular_session_5m_bars() -> None:
    days = _days(2)
    keys = np.repeat(np.array(days, dtype="datetime64[D]"), 3)
    t = np.arange(6, dtype=np.int64)
    o = np.array([10.0, 11, 12, 20, 21, 22])
    bars = runner.Bars(t, keys, (o, o + 1, o - 1, o + 0.5), np.ones(6), None, None)
    built = runner.rth_1d_from_5m(bars)
    assert len(built.t_ns) == 2 and built.ohlc[0].tolist() == [10.0, 20.0]
    assert built.ohlc[1].tolist() == [13.0, 23.0] and built.ohlc[3].tolist() == [12.5, 22.5]
    assert built.volume.tolist() == [3.0, 3.0]


def test_clean_vendor_passes_the_name_level_run_end_to_end() -> None:
    """Calibration: Massive equal to the incumbent on both arms is a pass with full agreement."""
    days = _days(60)
    rng = np.random.default_rng(5)
    close = 25 * np.exp(np.cumsum(rng.normal(0, 0.01, 60)))
    inc = _daily(days, close)
    massive = _daily(days, close)
    result = runner.compare_arm("1d", "ibkr", massive, inc, [], {})
    assert result is not None and result.n_matched == 60 and result.scale_class == ""
    assert result.n_ret_pairs == 59 and result.n_ret_agree == 59
    assert runner.judge_name_era({"1d": result}, nc.ERA_NO_ACTION, True) == (nc.OUTCOME_PASS, "")


def test_level_factor_incumbent_passes_on_returns_and_is_listed() -> None:
    """R3: an incumbent carrying a constant non-split factor agrees on returns, fails on level."""
    days = _days(80)
    rng = np.random.default_rng(6)
    close = 25 * np.exp(np.cumsum(rng.normal(0, 0.01, 80)))
    massive = _daily(days, close)
    inc = _daily(days, close / 1.28)
    result = runner.compare_arm("1d", "ibkr", massive, inc, [], {})
    assert result is not None
    assert result.n_agree == 0 and result.n_ret_agree == result.n_ret_pairs == 79
    assert result.scale_class == nc.SCALE_ADJUSTMENT_LEVEL
    assert runner.judge_name_era({"1d": result}, nc.ERA_NO_ACTION, True)[1] == (
        "adjustment_level_listed"
    )
