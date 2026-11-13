"""Round 5 calibration of the era gate (design 8a amendments 2026-11-12 rule 2 and 2026-11-13).

A gate is calibrated only when it fails in BOTH directions: each injected systemic defect stops
the era, and an un-injected benign era (small natural defects, the incumbent's cent rounding, a
close-convention residual the reference period also shows) does not. Population: 1,000 names of 150
sessions in the target era, 300 in each reference era; the injected share is 200 names.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import asdict
from datetime import date

import numpy as np
import pytest

from scripts.ops.bars import ops_massive_load_checks as runner
from src.intelligence.bars import massive_name_checks as nc
from src.intelligence.bars.sessions import nyse_sessions

N_BARS = 150
TARGET_ERA = 2010  # not a reference era: the reference eras only calibrate, they cannot stop
REFERENCE = (2014, 2015, 2016)
DAYS = sorted(nyse_sessions(date(2010, 1, 1), date(2010, 12, 31)))[:N_BARS]
KEYS = np.array(DAYS, dtype="datetime64[D]")

#: close, open-high-low are kept apart so a close-only defect leaves the other fields agreeing
Series = tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]
Injector = Callable[[Series, np.random.Generator, int], Series]


def _bars(ohlc: Series) -> runner.Bars:
    return runner.Bars(
        KEYS.astype("datetime64[ns]").astype("int64"),
        KEYS,
        ohlc,
        np.full(N_BARS, 1e6),
        None,
        None,
    )


def _name_series(rng: np.random.Generator) -> Series:
    close = 25 * np.exp(np.cumsum(rng.normal(0, 0.01, N_BARS)))
    return (close * 0.99, close * 1.01, close * 0.98, close)


def _facts(name: str, massive: Series, incumbent: Series) -> nc.NameFacts | None:
    """The runner's own path: compare_arm, the stored detail, the judged facts."""
    inc = tuple(np.round(a, 2) for a in incumbent)  # IBKR stores cents
    result = runner.compare_arm("1d", "ibkr", _bars(massive), _bars(inc), [], {})
    assert result is not None
    detail = {"arms": {"ibkr": {"5m": asdict(result)}}}
    gate = runner.judged_timeframes({"5m": result}, nc.ERA_NO_ACTION, True)
    return runner._name_facts(name, detail, "5m", gate[2])


def _era(
    era: int,
    n_names: int,
    seed: int,
    *,
    injected: int = 0,
    inject: Injector | None = None,
    natural_defects: int = 0,
    convention_share: float = 0.0,
) -> list[nc.NameFacts]:
    rng = np.random.default_rng(seed)
    out: list[nc.NameFacts] = []
    for i in range(n_names):
        series = _name_series(rng)
        massive = series
        if i < natural_defects:  # a few names with a 3 percent close error on 10 percent of days
            bad = rng.random(N_BARS) < 0.1
            close = np.where(bad, series[3] * 1.03, series[3])
            massive = (*series[:3], close)
        if convention_share and i % 2 == 0:  # the day file's close differs a little, inside H-L
            hit = rng.random(N_BARS) < convention_share
            massive = (*series[:3], np.where(hit, series[3] * 1.002, series[3]))
        if inject is not None and i >= n_names - injected:
            massive = inject(massive, rng, i)
        facts = _facts(f"N{era}_{i}", massive, series)
        assert facts is not None
        out.append(facts)
    return out


def _judge(target: list[nc.NameFacts], reference: dict[int, list[nc.NameFacts]], tf: str = "5m"):
    judged = {(e, tf): f for e, f in reference.items()}
    judged[(TARGET_ERA, tf)] = target
    return runner.era_verdicts(judged, [TARGET_ERA, *reference])[(TARGET_ERA, tf)]


@pytest.fixture(scope="module")
def reference() -> dict[int, list[nc.NameFacts]]:
    return {e: _era(e, 300, seed=e, natural_defects=3) for e in REFERENCE}


def _x100(m: Series, rng: np.random.Generator, i: int) -> Series:
    return tuple(a * 100 for a in m)  # type: ignore[return-value]


def _missing_split(m: Series, rng: np.random.Generator, i: int) -> Series:
    """The frozen table lacks a 2:1 split mid-year: raw Massive is double the adjusted incumbent
    before it."""
    k = N_BARS // 2
    return tuple(np.where(np.arange(N_BARS) < k, a * 2.0, a) for a in m)  # type: ignore[return-value]


def _close_5pct_off(m: Series, rng: np.random.Generator, i: int) -> Series:
    bad = rng.random(N_BARS) < 0.30
    return (*m[:3], np.where(bad, m[3] * 1.05, m[3]))


@pytest.mark.parametrize(
    ("label", "inject", "expected_reason"),
    [
        ("x100 on all fields", _x100, "level_class_share"),
        ("missing mid-year split", _missing_split, "level_class_share"),
        ("close 5 percent off on 30 percent of days", _close_5pct_off, "flagged_share"),
    ],
)
def test_each_injected_systemic_defect_stops_the_era(
    reference: dict[int, list[nc.NameFacts]], label: str, inject: Injector, expected_reason: str
) -> None:
    target = _era(TARGET_ERA, 1000, seed=99, injected=200, inject=inject, natural_defects=3)
    verdict = _judge(target, reference)
    assert verdict.verdict == nc.ERA_STOP, (label, verdict)
    assert any(r.startswith(expected_reason) for r in verdict.reasons), (label, verdict.reasons)
    # the same defect also stops the 1d timeframe, never degrading into 'unresolved'
    assert _judge(target, reference, "1d").verdict == nc.ERA_STOP


def test_an_uninjected_benign_era_passes(reference: dict[int, list[nc.NameFacts]]) -> None:
    target = _era(TARGET_ERA, 1000, seed=98, natural_defects=3)
    for tf in ("5m", "1d"):
        verdict = _judge(target, reference, tf)
        assert verdict.verdict == nc.ERA_OK, verdict
        assert verdict.n_judged == 1000 and not verdict.reasons


def test_a_few_defective_names_flag_but_do_not_stop(
    reference: dict[int, list[nc.NameFacts]],
) -> None:
    """Calibration direction two: 1 percent of names carry a 5 percent close error; the era
    counters stay under the 2 percent floor, so the defect is a flag, not a stop."""
    target = _era(TARGET_ERA, 1000, seed=97, injected=10, inject=_close_5pct_off)
    verdict = _judge(target, reference)
    assert verdict.verdict in (nc.ERA_OK, nc.ERA_OK_CONVENTION), verdict


def test_a_close_convention_residual_is_unresolved_for_1d_and_ok_convention_for_5m() -> None:
    """The reference period carries the same small closing-print differences (inside the bar's
    high-low and within its p99), so the era is not a stop: the 1d verdict is unresolved by rule
    5 and the 5m verdict is ok_convention, both data driven."""
    ref = {e: _era(e, 300, seed=e, convention_share=0.30) for e in REFERENCE}
    target = _era(TARGET_ERA, 1000, seed=96, convention_share=0.30)
    one_d = _judge(target, ref, "1d")
    five_m = _judge(target, ref, "5m")
    assert one_d.return_residual > nc.OTHER_INVESTIGATE_MAX_SHARE
    assert one_d.verdict == nc.ERA_UNRESOLVED and five_m.verdict == nc.ERA_OK_CONVENTION


def test_a_last_print_beyond_the_reference_cap_is_unexplained_and_stops(
    reference: dict[int, list[nc.NameFacts]],
) -> None:
    """The last_print class is size capped: a close 1 percent off inside the high-low range on
    30 percent of days across the whole era is beyond a reference that shows none."""
    ref = {e: _era(e, 300, seed=e, convention_share=0.30) for e in REFERENCE}  # 0.2 percent prints
    big = _era(TARGET_ERA, 1000, seed=95, injected=1000, inject=_close_1pct_inside_range)
    verdict = _judge(big, ref)
    assert verdict.verdict == nc.ERA_STOP and "unexplained_other" in verdict.reasons


def _close_1pct_inside_range(m: Series, rng: np.random.Generator, i: int) -> Series:
    bad = rng.random(N_BARS) < 0.30
    return (*m[:3], np.where(bad, m[3] * 1.01, m[3]))


def test_an_empty_clean_set_is_never_ok(reference: dict[int, list[nc.NameFacts]]) -> None:
    every = _era(TARGET_ERA, 400, seed=94, injected=400, inject=_x100)
    verdict = _judge(every, reference)
    assert verdict.verdict == nc.ERA_STOP and "empty_clean_set" in verdict.reasons


def test_an_era_without_judged_names_writes_an_explicit_verdict(
    reference: dict[int, list[nc.NameFacts]],
) -> None:
    verdict = _judge([], reference)
    assert verdict.verdict == nc.ERA_NO_DETECTOR and verdict.reasons == ("no_judged_names",)


def test_other_concentration_flags_few_carriers_and_stops_many() -> None:
    """Unexplained pairs above 0.5 percent of all matched pairs: at most 50 carrying names are
    flagged (other_concentration), more than 50 stop the era."""

    def facts(i: int, other: int) -> nc.NameFacts:
        c = nc.AgreementCounts(1000, 1000 - other, 1000 - other, {"other": other}, 999, 999, 0, 0)
        return nc.NameFacts(f"S{i}", c, False, "", 0.0)

    thresholds = nc.counter_thresholds([])
    few = [facts(i, 200 if i < 40 else 0) for i in range(1000)]  # 40 carriers: 0.8 percent overall
    v = nc.judge_era("5m", few, thresholds, 0)
    assert v.verdict == nc.ERA_OK and len(v.other_concentration) == 40
    many = [facts(i, 100 if i < 200 else 0) for i in range(1000)]  # 200 carriers
    v = nc.judge_era("5m", many, thresholds, 0)
    assert v.verdict == nc.ERA_STOP and "unexplained_other" in v.reasons


def test_a_defect_inside_a_reference_era_still_stops_it(
    reference: dict[int, list[nc.NameFacts]],
) -> None:
    """A reference era is judged against the OTHER reference eras: against its own counters the
    3x rule could never fire."""
    judged = {(e, "5m"): f for e, f in reference.items()}
    judged[(2015, "5m")] = _era(2015, 1000, seed=93, injected=200, inject=_x100)
    verdict = runner.era_verdicts(judged, list(REFERENCE))[(2015, "5m")]
    assert verdict.verdict == nc.ERA_STOP and "level_class_share>0.0200" in verdict.reasons
    clean = runner.era_verdicts({(e, "5m"): f for e, f in reference.items()}, list(REFERENCE))
    assert all(v.verdict == nc.ERA_OK for (_, tf), v in clean.items() if tf == "5m")


def _detail(massive: Series, incumbent: Series) -> dict:
    inc = tuple(np.round(a, 2) for a in incumbent)
    res = {
        tf: asdict(runner.compare_arm("1d", "ibkr", _bars(massive), _bars(inc), [], {}))
        for tf in ("1d", "5m")
    }
    return {
        "listed": True,
        "preclass": nc.ERA_NO_ACTION,
        "alpaca_epoch_seam_possible": False,
        "probable_ibkr_non_split_adjustment": False,
        "splits_in_window": [],
        "arms": {"ibkr": res, "alpaca": {}},
    }


def _write_run(tmp_path, injected_era: int | None) -> tuple[runner.Config, dict]:
    from pathlib import Path

    cfg = runner.Config(Path(tmp_path), Path(tmp_path), 1, 6, (2010, 2014, 2015), False, 0.0)
    keys = {}
    for era in cfg.eras:
        rng = np.random.default_rng(era)
        names = {}
        for i in range(40):
            series = _name_series(rng)
            massive = _x100(series, rng, i) if era == injected_era and i < 10 else series
            names[f"N{i}"] = _detail(massive, series)
        keys[era] = {"era": era}
        runner.write_json(
            runner.part_path(cfg, "name_checks", era),
            {"key": keys[era], "era": era, "names": names},
        )
    return cfg, keys


def test_stage_c_assembly_closes_the_partition_with_every_outcome_class(tmp_path) -> None:
    cfg, keys = _write_run(tmp_path, None)
    summary = runner.assemble_stage_c(cfg, None, [f"N{i}" for i in range(40)], ["U"], keys, "s")
    assert summary["partition"]["status"] == "complete"
    counts = summary["partition"]["counts"]
    assert counts["pass"] == 120 and counts["unmapped"] == 3 and counts["stop"] == 0
    assert summary["vendor_wide_return_agreement"] == "ok"
    assert (tmp_path / "stageC_era_tables.csv").exists()


def test_stage_c_assembly_stops_the_injected_era_and_only_that_era(tmp_path) -> None:
    cfg, keys = _write_run(tmp_path, 2010)  # 10 of 40 names: x100 on all fields
    summary = runner.assemble_stage_c(cfg, None, [f"N{i}" for i in range(40)], ["U"], keys, "s")
    counts = summary["partition"]["counts"]
    assert set(summary["stop_eras_all_sources"]) == {"2010"}
    assert counts["stop"] == 40 and counts["pass"] == 80 and counts["unmapped"] == 3
    assert summary["vendor_wide_return_agreement"] == "stop"
