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
    return sorted(nyse_sessions(date(2010, 1, 1), date(2010, 12, 31)))[:n]


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
    outcome = _judge({"1d": result, "5m": None})
    assert (outcome.outcome, outcome.reason) == (nc.OUTCOME_NO_DETECTOR, "no_detector")


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


def _judge(
    results: dict, preclass: str = nc.ERA_NO_ACTION, listed: bool = True, unresolved: bool = False
) -> runner.NameJudgement:
    return runner.judge_name_era(results, preclass, listed, one_d_unresolved=unresolved)


def _outcome(judgement: runner.NameJudgement) -> tuple[str, str]:
    return judgement.outcome, judgement.reason


def test_judge_name_era_outcomes() -> None:
    good = _arm(250, 250, 0.0, 0.99)
    assert _outcome(_judge({"1d": good})) == (nc.OUTCOME_PASS, "")
    assert _outcome(_judge({"1d": good}, listed=False)) == (
        nc.OUTCOME_NOT_LISTED,
        "not_listed_in_era",
    )
    assert _outcome(_judge({"1d": good}, nc.ERA_NON_SPLIT)) == (
        nc.OUTCOME_NO_DETECTOR,
        "non_split_adjustment_convention",
    )
    unresolved = _arm(250, 250, 0.0, 0.5)
    assert _outcome(_judge({"1d": unresolved})) == (nc.OUTCOME_UNRESOLVED, "identity_unresolved")
    low = _arm(250, 250, 0.0, 0.99, ret=0.96)  # returns agree on 96 percent
    assert _outcome(_judge({"1d": low})) == (nc.OUTCOME_FLAGGED, "price_agreement_1d")


def test_name_era_below_the_minimum_pair_count_has_no_detector() -> None:
    few = _arm(nc.NAME_ERA_MIN_PAIRS, nc.NAME_ERA_MIN_PAIRS, 0.0, 0.99, ret=0.0)  # 99 pairs
    assert _outcome(_judge({"1d": few})) == (nc.OUTCOME_NO_DETECTOR, "no_detector")
    enough = _arm(nc.NAME_ERA_MIN_PAIRS + 1, 1, 0.0, 0.99, ret=0.5)  # 100 pairs, half wrong
    assert _outcome(_judge({"1d": enough}))[0] == nc.OUTCOME_FLAGGED


def test_an_unresolved_1d_era_judges_the_cell_on_5m_alone() -> None:
    bad_1d = _arm(250, 250, 0.0, 0.99, ret=0.9)
    good_5m = _arm(250, 250, 0.0, 0.99)
    assert _outcome(_judge({"1d": bad_1d, "5m": good_5m})) == (
        nc.OUTCOME_FLAGGED,
        "price_agreement_1d",
    )
    assert _outcome(_judge({"1d": bad_1d, "5m": good_5m}, unresolved=True)) == (
        nc.OUTCOME_PASS,
        "",
    )
    assert _outcome(_judge({"1d": bad_1d}, unresolved=True)) == (
        nc.OUTCOME_UNRESOLVED,
        "close_convention_1d",
    )


def test_judge_name_era_level_classes() -> None:
    # a constant level factor with agreeing returns passes, listed in the scale listing
    adj = _arm(250, 0, 0.25, 0.99, cls=nc.SCALE_ADJUSTMENT_LEVEL)
    assert _outcome(_judge({"1d": adj})) == (nc.OUTCOME_PASS, "adjustment_level_listed")
    drift = _arm(250, 100, 0.0, 0.99, cls=nc.SCALE_LEVEL_DRIFT)
    assert _outcome(_judge({"5m": drift}))[1] == "level_drift_listed"
    # a stable offset that reads as a split ratio is a candidate missing split: flagged
    split = _arm(250, 0, 0.6931, 0.99, cls=nc.SCALE_SPLIT_LIKE)
    assert _outcome(_judge({"1d": split})) == (
        nc.OUTCOME_FLAGGED,
        "scale_factor_split_like_1d",
    )


def test_a_null_incumbent_volume_is_unknown_not_zero() -> None:
    days = _days(10)
    close = np.linspace(20, 21, 10)
    inc = _daily(days, close)
    volume = inc.volume.copy()
    volume[3] = np.nan
    inc = runner.Bars(inc.t_ns, inc.key, inc.ohlc, volume, None, None)
    result = runner.compare_arm("1d", "ibkr", _daily(days, close), inc, [], {})
    assert result is not None and result.n_matched == 9
    assert result.n_incumbent_unknown_volume == 1 and result.n_incumbent_zero_volume == 0


def test_clean_vendor_passes_the_name_level_run_end_to_end() -> None:
    """Calibration: Massive equal to the incumbent on both arms is a pass with full agreement."""
    days = _days(150)
    rng = np.random.default_rng(5)
    close = 25 * np.exp(np.cumsum(rng.normal(0, 0.01, 150)))
    inc = _daily(days, close)
    massive = _daily(days, close)
    result = runner.compare_arm("1d", "ibkr", massive, inc, [], {})
    assert result is not None and result.n_matched == 150 and result.scale_class == ""
    assert result.n_ret_pairs == 149 and result.n_ret_agree == 149
    assert _outcome(_judge({"1d": result})) == (nc.OUTCOME_PASS, "")


def test_level_factor_incumbent_passes_on_returns_and_is_listed() -> None:
    """R3: an incumbent carrying a constant non-split factor agrees on returns, fails on level."""
    days = _days(150)
    rng = np.random.default_rng(6)
    close = 25 * np.exp(np.cumsum(rng.normal(0, 0.01, 150)))
    massive = _daily(days, close)
    inc = _daily(days, close / 1.28)
    result = runner.compare_arm("1d", "ibkr", massive, inc, [], {})
    assert result is not None
    assert result.n_agree == 0 and result.n_ret_agree == result.n_ret_pairs == 149
    assert result.scale_class == nc.SCALE_ADJUSTMENT_LEVEL
    assert _outcome(_judge({"1d": result}))[1] == "adjustment_level_listed"
