"""ops_massive_load_checks stage C: name-level comparison on synthetic bars (no database)."""

from __future__ import annotations

import json
from datetime import date

import numpy as np
import pytest

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
    assert _outcome(_judge({"1d": unresolved})) == (nc.OUTCOME_UNRESOLVED, "identity_decorrelated")
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


# ---- round 5 review fixes ---------------------------------------------------------------------
def test_the_gap_list_is_built_from_every_named_defect_not_the_capped_listing() -> None:
    n = runner.DEFECT_LIST_CAP + 100
    tickers = np.array([f"T{i}" for i in range(n)])
    raw = runner.RawFile(
        tickers,
        np.arange(n),
        np.arange(n, dtype=np.int64),
        np.full(n, 10.0),
        np.full(n, 9.0),  # high under open: every row defective
        np.full(n, 8.0),
        np.full(n, 10.0),
        np.full(n, 1.0),
    )
    scan = runner.sanity_of(raw)
    log = runner.DefectLog()
    log.add(date(2010, 3, 1), raw, scan, 0, 0, "day")
    assert len(log.gap) == n and log.n_named == n  # every bar keyed and counted
    assert len(log.named) == runner.DEFECT_LIST_CAP  # only the first rows kept as dicts


def test_the_calendar_audit_rescales_the_ibkr_1d_series_before_the_comparison() -> None:
    """Rule 7: the audit names IBKR's smart_trades unadjusted over a 2:1 split; Massive (divided by
    the market split) agrees with the incumbent only once the incumbent is rescaled too."""
    days = _days(150)
    rng = np.random.default_rng(8)
    adjusted = 25 * np.exp(np.cumsum(rng.normal(0, 0.01, 150)))
    effective = days[74]  # the last session on the old scale
    split = [SplitFactor(effective, 2.0)]
    raw_massive = _daily(days, adjusted * np.where(np.array(days) <= effective, 2.0, 1.0))
    unadjusted_ibkr = _daily(days, adjusted * np.where(np.array(days) <= effective, 2.0, 1.0))
    before = runner.compare_arm("1d", "ibkr", raw_massive, unadjusted_ibkr, split, {})
    assert before is not None and before.n_ret_agree < before.n_ret_pairs  # IBKR's recorded defect
    fixed = runner.rescaled_bars(
        unadjusted_ibkr, runner.lc.split_scale_for_days(unadjusted_ibkr.key, split)
    )
    after = runner.compare_arm("1d", "ibkr", raw_massive, fixed, split, {})
    assert after is not None and after.n_agree == 150 and after.n_ret_agree == after.n_ret_pairs


def test_frozen_loads_the_calendar_audit_rescales_and_the_spans(tmp_path) -> None:
    import json
    from pathlib import Path

    cfg = runner.Config(Path(tmp_path), Path(tmp_path), 1, 6, (2010,), False, 0.0)
    frozen = Path(tmp_path) / "frozen"
    frozen.mkdir()
    (frozen / "frozen.json").write_text(
        json.dumps(
            {
                "freeze_version": runner.FREEZE_VERSION,
                "sha256": {},
                "horizon": "2026-11-12T12:00:00+00:00",
            }
        )
    )
    header = "symbol,effective_date,factor,recorded_at,inferred_by,rows_file,market_fact,unadjusted_routes\n"
    (frozen / "corporate_actions.csv").write_text(
        header
        + "EAT,2001-01-16,1.5,2026-10-01T00:00:00+00:00,calendar_audit,False,True,ibkr/smart_trades\n"
        + "PATK,2012-05-01,0.4,2026-10-01T00:00:00+00:00,calendar_audit,True,False,ibkr/smart_trades\n"
        + "AAPL,2014-06-06,7.0,2026-10-01T00:00:00+00:00,massive_reference,False,True,\n"
    )
    (frozen / "ticker_spans.csv").write_text(
        "symbol,ticker,valid_from,valid_to\nEAT,EAT,2003-09-10,\nOLD,OLD,2003-09-10,2010-01-01\n"
    )
    out = runner.load_frozen(cfg)
    assert [(s.effective_date.year, s.factor) for s in out.ibkr_rescales["PATK"]] == [(2012, 0.4)]
    assert "AAPL" not in out.ibkr_rescales  # a massive_reference split names no incumbent route
    assert [s.factor for s in out.splits["AAPL"]] == [7.0] and out.splits["PATK"] == []
    assert out.span_listed("EAT", 2020) and out.span_listed("OLD", 2009)
    assert not out.span_listed("OLD", 2010) and not out.span_listed("ZZZ", 2010)


def test_a_massive_hole_is_flagged_never_not_listed_and_never_stop_exempt() -> None:
    outcome = runner.judged_timeframes({}, nc.ERA_NO_ACTION, True, massive_hole=True)
    assert tuple(outcome) == (nc.OUTCOME_FLAGGED, "massive_hole", (), ())
    assert nc.OUTCOME_FLAGGED not in nc.STOP_EXEMPT_OUTCOMES


def test_identity_ignores_split_sized_returns_and_falls_back_to_the_5m_returns() -> None:
    rng = np.random.default_rng(3)
    close = 25 * np.exp(np.cumsum(rng.normal(0, 0.01, 150)))
    inc = close.copy()
    massive = close.copy()
    massive[75:] *= 2.0  # a split missing from the frozen table: one |ln 2| return on one arm
    assert nc.identity_resolved(nc.identity_correlation(massive, inc))
    assert np.isnan(nc.identity_correlation(close[:15], close[:15]))  # under 20 returns
    # thin daily identity, good 5m identity: judged on the 5m returns
    thin_1d = _arm(30, 30, 0.0, float("nan"))
    good_5m = _arm(250, 250, 0.0, 0.99)
    assert runner.judged_timeframes({"1d": thin_1d, "5m": good_5m}, nc.ERA_NO_ACTION, True)[0] == ""
    both_thin = _arm(30, 30, 0.0, float("nan"))
    assert runner.judged_timeframes({"1d": thin_1d, "5m": both_thin}, nc.ERA_NO_ACTION, True)[
        :2
    ] == (
        nc.OUTCOME_UNRESOLVED,
        "identity_thin",
    )


def test_daily_session_dates_use_the_one_definition() -> None:
    from datetime import UTC, datetime

    class Cursor:
        def __init__(self, stamp: datetime) -> None:
            self.stamp = stamp

        def __enter__(self) -> Cursor:
            return self

        def __exit__(self, *exc: object) -> None:
            return None

        def execute(self, sql: str, params: object = None) -> None:
            return None

        def stream(self, sql: str, params: object = None, size: int = 1):
            return iter(self.fetchall())

        def fetchall(self) -> list[tuple]:
            return [("A", self.stamp, 1.0, 1.0, 1.0, 1.0, 5, None)]

    class Conn:
        def __init__(self, stamp: datetime) -> None:
            self.stamp = stamp

        def cursor(self) -> Cursor:
            return Cursor(self.stamp)

    start, end = datetime(2010, 1, 1, tzinfo=UTC), datetime(2011, 1, 1, tzinfo=UTC)
    ibkr = runner.fetch_bars(
        Conn(datetime(2010, 3, 1, tzinfo=UTC)), "1d", "ibkr", ["A"], start, end
    )
    assert str(ibkr["A"].key[0]) == "2010-03-01"  # 00:00 UTC stamp: the UTC date
    stamp = datetime(2010, 3, 1, 5, tzinfo=UTC)  # midnight New York
    massive = runner.fetch_bars(Conn(stamp), "1d", "massive", ["A"], start, end)
    assert str(massive["A"].key[0]) == "2010-03-01"


def test_the_raw_fingerprint_is_scoped_per_series_and_moves_on_a_restatement() -> None:
    fp = {"massive|sip_flat|1d": "10|2026-01-01|0", "ibkr|named|5m": "99|x|0"}
    assert runner.scoped_fingerprint(fp, [("massive", "sip_flat", "1d")]) == {
        "massive|sip_flat|1d": "10|2026-01-01|0"
    }
    restated = {"massive|sip_flat|1d": "10|2026-02-01|3", "ibkr|named|5m": "99|x|0"}
    assert runner.scoped_fingerprint(
        restated, runner.VOLUME_SERIES[1:]
    ) != runner.scoped_fingerprint(
        fp, runner.VOLUME_SERIES[1:]
    )  # same row count, different served stamp and revision count


def test_the_live_fingerprint_and_exchange_map_are_deterministic(
    sql_probe_url: str | None,
) -> None:
    import pytest

    try:
        conn = runner.connect_read_only(sql_probe_url)
    except Exception as error:
        pytest.skip(f"database unavailable: {error}")
    with conn:
        first = runner.raw_fingerprints(conn, [2010, 2011], runner.STAGE_C_SERIES)
        assert first == runner.raw_fingerprints(conn, [2010, 2011], runner.STAGE_C_SERIES)
        assert set(first) == {2010, 2011}
        try:
            with conn.cursor() as cur:
                cur.execute(runner._EXCHANGE_SQL)
                rows = cur.fetchall()
        except Exception as error:  # the test database carries no reference_raw
            pytest.skip(f"reference_raw unavailable: {error}")
        assert len(rows) == len({s for s, _ in rows})  # one capture per ticker


def test_identity_is_judged_per_timeframe_and_counts_only_with_a_detector() -> None:
    bad_1d = _arm(250, 250, 0.0, 0.5)  # decorrelated daily pair with a detector
    good_5m = _arm(250, 250, 0.0, 0.99)
    gate = runner.judged_timeframes({"1d": bad_1d, "5m": good_5m}, nc.ERA_NO_ACTION, True)
    assert gate.outcome == "" and gate.usable == ("5m",) and gate.decorrelated == ("1d",)
    # decorrelated but under the pair minimum: no detector speaks, so not identity_decorrelated
    few_bad = _arm(30, 30, 0.0, 0.5)
    gate = runner.judged_timeframes({"1d": few_bad}, nc.ERA_NO_ACTION, True)
    assert gate.reason == "no_detector" and gate.decorrelated == ()


def test_the_ibkr_volume_rescale_is_the_factor_stage_c_divides_prices_by() -> None:
    from src.intelligence.bars.split_rescale import SplitFactor

    frozen = runner.Frozen({}, {"A": [SplitFactor(date(2010, 3, 5), 2.0)]}, {})
    days = np.array(["2010-03-04", "2010-03-05", "2010-03-08"], dtype="datetime64[D]")
    assert frozen.ibkr_scale("A", days).tolist() == [2.0, 2.0, 1.0]
    assert frozen.ibkr_scale("B", days).tolist() == [1.0, 1.0, 1.0]


@pytest.fixture(autouse=True)
def _outside_the_nightly_window(monkeypatch: pytest.MonkeyPatch) -> None:
    """A test run inside a nightly timer window must not sleep through it."""
    monkeypatch.setattr(runner, "in_nightly_window", lambda now: False)


def test_every_heavy_read_waits_out_the_nightly_window(monkeypatch: pytest.MonkeyPatch) -> None:
    from datetime import UTC, datetime

    waits: list[str] = []
    monkeypatch.setattr(runner, "wait_out_nightly_window", lambda: waits.append("w"))

    class Cursor:
        def __enter__(self) -> Cursor:
            return self

        def __exit__(self, *exc: object) -> None:
            return None

        def execute(self, sql: str, params: object = None) -> None:
            return None

        def stream(self, sql: str, params: object = None, size: int = 1):
            return iter(self.fetchall())

        def fetchall(self) -> list[tuple]:
            return []

    class Conn:
        def cursor(self) -> Cursor:
            return Cursor()

    start, end = datetime(2010, 1, 1, tzinfo=UTC), datetime(2011, 1, 1, tzinfo=UTC)
    runner.fetch_bars(Conn(), "1d", "ibkr", ["A"], start, end)  # type: ignore[arg-type]
    runner.fetch_split_tapes(Conn(), [("A", date(2010, 3, 1))])  # type: ignore[arg-type]
    runner.load_exchange_map(Conn())  # type: ignore[arg-type]
    runner.raw_fingerprints(Conn(), [2010, 2011], runner.VOLUME_SERIES)  # type: ignore[arg-type]
    assert len(waits) == 1 + 1 + 1 + 3  # one per read; the fingerprints wait before each era


def test_a_thin_era_is_not_the_close_convention() -> None:
    thin = nc.EraVerdict("1d", nc.ERA_UNRESOLVED, ("thin_era",), 5, 0, 0, 0, 0, 0, (), None, {}, {})  # type: ignore[arg-type]
    convention = nc.EraVerdict(
        "1d", nc.ERA_UNRESOLVED, ("close_convention",), 50, 0, 0, 0, 0, 0, (), None, {}, {}  # type: ignore[arg-type]
    )
    assert not runner._close_convention_unresolved(thin)
    assert runner._close_convention_unresolved(convention)


def test_split_tapes_have_their_own_parts_keyed_by_their_years(tmp_path) -> None:
    from datetime import UTC, datetime
    from pathlib import Path

    from src.intelligence.bars.split_rescale import SplitFactor

    tape_rows = [
        ("A", date(2020, 8, 28), datetime(2020, 8, 28, 4, tzinfo=UTC), 500.0),
        ("A", date(2020, 8, 28), datetime(2020, 8, 31, 4, tzinfo=UTC), 129.0),
    ]
    fetches: list[str] = []
    state = {"count": 5}

    class Cursor:
        def __enter__(self) -> Cursor:
            return self

        def __exit__(self, *exc: object) -> None:
            self.sql = ""

        def execute(self, sql: str, params: object = None) -> None:
            self.sql = sql

        def fetchall(self) -> list[tuple]:
            if "ohlcv_revision" in self.sql:
                return []
            if "unnest" in self.sql:
                fetches.append("tapes")
                return tape_rows
            return [("massive", "sip_flat", "1d", state["count"], None)]

    class Conn:
        def cursor(self) -> Cursor:
            return Cursor()

    cfg = runner.Config(Path(tmp_path), Path(tmp_path), 1, 6, (2010,), False, 0.0)
    (Path(tmp_path) / "frozen").mkdir()
    (Path(tmp_path) / "frozen" / "frozen.json").write_text(
        json.dumps(
            {
                "freeze_version": runner.FREEZE_VERSION,
                "sha256": {},
                "horizon": "2026-11-12T00:00:00+00:00",
            }
        )
    )
    frozen = runner.Frozen({"A": [SplitFactor(date(2020, 8, 28), 4.0)]}, {}, {})
    fps = {2010: {"massive|sip_flat|1d": "1|x|0"}}
    first = runner.run_split_tapes(cfg, Conn(), frozen, ["A"], fps)  # type: ignore[arg-type]
    assert first == {"A": {"2020-08-28": [500.0, 129.0]}} and fetches == ["tapes"]
    runner.run_split_tapes(cfg, Conn(), frozen, ["A"], fps)  # type: ignore[arg-type]
    assert fetches == ["tapes"]  # the part is current: nothing is fetched again
    state["count"] = 6  # the 2020 series was reloaded: only this tape part is invalidated
    runner.run_split_tapes(cfg, Conn(), frozen, ["A"], fps)  # type: ignore[arg-type]
    assert fetches == ["tapes", "tapes"]
    assert runner.tape_window_years(date(2020, 1, 5)) == (2019, 2020)
    key = runner.stage_c_keys([2010], {"seed": 1}, fps)[2010]
    assert "tape_fingerprints" not in key  # a name part does not key on tapes


def test_alpaca_may_witness_a_hole_but_ibkr_comes_first() -> None:
    traded = runner.Bars(
        np.array([1], dtype=np.int64),
        np.array(["2010-03-01"], dtype="datetime64[D]"),
        (np.ones(1),) * 4,
        np.array([5.0]),
        None,
        None,
    )
    assert runner.trade_witness({("1d", "ibkr"): {"A": traded}}, "A") == "ibkr"
    assert runner.trade_witness({("1d", "alpaca"): {"A": traded}}, "A") == "alpaca"
    assert runner.trade_witness({("1d", "alpaca"): {"B": traded}}, "A") == ""


def test_the_dispute_window_is_the_session_calendar_centred_on_the_date() -> None:
    window = runner.dispute_window(date(2010, 3, 16))
    assert len(window) == 21 and window[10] == date(2010, 3, 16)
    assert window == sorted(window) and all(d.weekday() < 5 for d in window)
    saturday = runner.dispute_window(date(2010, 3, 20))  # not a session: the next one centres
    assert saturday[10] == date(2010, 3, 22)


def test_a_reuse_check_reads_the_sidecar_not_the_part(tmp_path) -> None:
    from pathlib import Path

    cfg = runner.Config(Path(tmp_path), Path(tmp_path), 1, 6, (2010,), False, 0.0)
    key = {"seed": 1, "tape_fingerprints": {"2020": {"a": "1"}}}
    runner.write_part(cfg, "name_checks", 2010, {"key": key, "names": {}})
    runner.part_path(cfg, "name_checks", 2010).write_text("not json")  # never parsed
    assert runner.part_current(cfg, "name_checks", 2010, key)
    assert not runner.part_current(cfg, "name_checks", 2010, {**key, "seed": 2})
    runner.key_path(cfg, "name_checks", 2010).unlink()  # a part without its key is not reused
    assert not runner.part_current(cfg, "name_checks", 2010, key)


def test_fetch_bars_streams_one_name_at_a_time() -> None:
    from datetime import UTC, datetime

    consumed: list[int] = []

    def rows():
        for i, name in enumerate(["A", "A", "B", "B", "C"]):
            consumed.append(i)
            yield (name, datetime(2010, 3, 1 + i, tzinfo=UTC), 1.0, 1.0, 1.0, 1.0, 5, None)

    class Cursor:
        def __enter__(self) -> Cursor:
            return self

        def __exit__(self, *exc: object) -> None:
            return None

        def stream(self, sql: str, params: object = None, size: int = 1):
            return rows()

    class Conn:
        def cursor(self) -> Cursor:
            return Cursor()

    start, end = datetime(2010, 1, 1, tzinfo=UTC), datetime(2011, 1, 1, tzinfo=UTC)
    out = runner.fetch_bars(Conn(), "1d", "ibkr", ["A", "B", "C"], start, end)  # type: ignore[arg-type]
    assert (
        sorted(out) == ["A", "B", "C"] and len(out["A"].t_ns) == 2 and consumed == [0, 1, 2, 3, 4]
    )


def _raw_with_defects(n: int) -> runner.RawFile:
    return runner.RawFile(
        np.array([f"T{i}" for i in range(n)]),
        np.arange(n),
        np.arange(n, dtype=np.int64),
        np.full(n, 10.0),
        np.full(n, 9.0),  # high under open: every row defective
        np.full(n, 8.0),
        np.full(n, 10.0),
        np.full(n, 1.0),
    )


def test_the_defect_cap_is_per_file_kind_and_a_day_row_has_no_rth_flag() -> None:
    n = runner.DEFECT_LIST_CAP + 20
    raw = _raw_with_defects(n)
    scan = runner.sanity_of(raw)
    log = runner.DefectLog()
    log.add(date(2010, 3, 1), raw, scan, 0, 0, "day")
    log.add(date(2010, 3, 2), raw, scan, 0, 10**18, "minute")
    kinds = [r["file_kind"] for r in log.named]
    assert kinds.count("day") == runner.DEFECT_LIST_CAP == kinds.count("minute")
    assert all(r["in_rth"] is None for r in log.named if r["file_kind"] == "day")
    assert all(r["in_rth"] is True for r in log.named if r["file_kind"] == "minute")
    assert log.n_named == 2 * n


def test_a_flat_identical_pair_agrees_and_exactly_one_flat_side_does_not() -> None:
    flat = np.zeros(60)
    varying = np.random.default_rng(2).normal(0, 0.01, 60)
    assert nc.return_correlation(flat, flat.copy()) == 1.0
    assert nc.return_correlation(flat, varying) == 0.0
    assert nc.return_correlation(varying, flat) == 0.0
    assert nc.return_correlation(flat, np.full(60, 0.001)) == 0.0  # both flat, not identical


def test_a_part_write_removes_the_old_key_first_and_a_stale_part_is_refused(
    tmp_path, monkeypatch
) -> None:
    from pathlib import Path

    cfg = runner.Config(Path(tmp_path), Path(tmp_path), 1, 6, (2010,), False, 0.0)
    key = runner.sample_key(cfg)
    runner.write_part(cfg, "session", 2010, {"key": key})
    assert runner.part_current(cfg, "session", 2010, key)
    original = runner.write_json

    def failing(path: Path, payload: object) -> None:
        raise OSError("disk full")

    monkeypatch.setattr(runner, "write_json", failing)
    with pytest.raises(OSError):
        runner.write_part(cfg, "session", 2010, {"key": {**key, "seed": 2}})
    monkeypatch.setattr(runner, "write_json", original)
    assert not runner.part_current(cfg, "session", 2010, key)  # no sidecar stands for a torn part
    runner.write_part(cfg, "session", 2010, {"key": key})
    assert set(runner.all_parts(cfg, "session", key)) == {2010}
    with pytest.raises(RuntimeError, match="another key"):  # the second check: the embedded key
        runner.all_parts(cfg, "session", {**key, "seed": 9})


def test_volume_band_parts_are_checked_against_their_per_era_key(tmp_path) -> None:
    from pathlib import Path

    cfg = runner.Config(Path(tmp_path), Path(tmp_path), 1, 6, (2010,), False, 0.0)
    key = {"seed": 1, "exchange_map_sha256": "a"}
    runner.write_part(cfg, "volume_bands", 2010, {"key": key})
    assert set(runner.all_parts(cfg, "volume_bands", keys={2010: key})) == {2010}
    with pytest.raises(RuntimeError, match="another key"):
        runner.all_parts(cfg, "volume_bands", keys={2010: {**key, "exchange_map_sha256": "b"}})
