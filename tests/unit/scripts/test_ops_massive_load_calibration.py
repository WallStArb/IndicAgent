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
from typing import NamedTuple

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
    n = len(ohlc[0])
    return runner.Bars(
        KEYS[:n].astype("datetime64[ns]").astype("int64"),
        KEYS[:n],
        ohlc,
        np.full(n, 1e6),
        None,
        None,
    )


def _name_series(rng: np.random.Generator) -> Series:
    close = 25 * np.exp(np.cumsum(rng.normal(0, 0.01, N_BARS)))
    return (close * 0.99, close * 1.01, close * 0.98, close)


class Era(NamedTuple):
    facts: list[nc.NameFacts]
    unresolved: int  # DECORRELATED names (counted by the fourth counter); thin ones never count
    thin: int = 0  # names whose daily and 5m evidence are both thin (listed, never counted)


def _facts(name: str, massive: Series, incumbent: Series) -> tuple[nc.NameFacts | None, str]:
    """The runner's own path: compare_arm, the stored detail, the judged facts. The same result
    stands for both timeframes, so the identity gate sees what a real name-era shows it."""
    inc = tuple(np.round(a, 2) for a in incumbent)  # IBKR stores cents
    result = runner.compare_arm("1d", "ibkr", _bars(massive), _bars(inc), [], {})
    assert result is not None
    detail = {"arms": {"ibkr": {"5m": asdict(result)}}}
    gate = runner.judged_timeframes({"1d": result, "5m": result}, nc.ERA_NO_ACTION, True)
    if gate[0]:
        return None, gate[1]
    return runner._name_facts(name, detail, "5m", gate[2]), ""


def _era(
    era: int,
    n_names: int,
    seed: int,
    *,
    injected: int = 0,
    inject: Injector | None = None,
    natural_defects: int = 0,
    convention_share: float = 0.0,
    injected_price_scale: float = 1.0,
    thin: int = 0,
) -> Era:
    rng = np.random.default_rng(seed)
    out: list[nc.NameFacts] = []
    unresolved = n_thin = 0
    for i in range(n_names):
        series = _name_series(rng)
        is_thin = natural_defects <= i < natural_defects + thin
        if is_thin:  # 15 sessions: under the 20-return identity minimum on both timeframes
            series = tuple(a[:15] for a in series)  # type: ignore[assignment]
        if inject is not None and i >= n_names - injected and injected_price_scale != 1.0:
            series = tuple(a * injected_price_scale for a in series)  # type: ignore[assignment]
        massive = series
        if is_thin:
            pass
        elif (
            i < natural_defects
        ):  # a few names with a 0.5 percent close error on 10 percent of days
            bad = rng.random(N_BARS) < 0.1
            close = np.where(bad, series[3] * 1.005, series[3])
            massive = (*series[:3], close)
        if (
            convention_share and i % 2 == 0 and not is_thin
        ):  # the day file's close differs a little, inside H-L
            hit = rng.random(N_BARS) < convention_share
            massive = (*series[:3], np.where(hit, series[3] * 1.002, series[3]))
        if inject is not None and i >= n_names - injected and not is_thin:
            massive = inject(massive, rng, i)
        facts, reason = _facts(f"N{era}_{i}", massive, series)
        if facts is not None:
            out.append(facts)
        elif reason == "identity_decorrelated":
            unresolved += 1
        elif reason == "identity_thin":
            n_thin += 1
        else:
            raise AssertionError(f"unexpected gate outcome {reason!r}")
    return Era(out, unresolved, n_thin)


def _judge(target: Era, reference: dict[int, Era], tf: str = "5m"):
    judged = {(e, tf): r.facts for e, r in reference.items()}
    judged[(TARGET_ERA, tf)] = target.facts
    unresolved = {(e, tf): r.unresolved for e, r in reference.items()}
    unresolved[(TARGET_ERA, tf)] = target.unresolved
    return runner.era_verdicts(judged, [TARGET_ERA, *reference], unresolved)[(TARGET_ERA, tf)]


@pytest.fixture(scope="module")
def reference() -> dict[int, Era]:
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
        ("close 5 percent off on 30 percent of days", _close_5pct_off, "identity_unresolved_share"),
    ],
)
def test_each_injected_systemic_defect_stops_the_era(
    reference: dict[int, Era], label: str, inject: Injector, expected_reason: str
) -> None:
    target = _era(TARGET_ERA, 1000, seed=99, injected=200, inject=inject, natural_defects=3)
    verdict = _judge(target, reference)
    assert verdict.verdict == nc.ERA_STOP, (label, verdict)
    assert any(r.startswith(expected_reason) for r in verdict.reasons), (label, verdict.reasons)
    # the same defect also stops the 1d timeframe, never degrading into 'unresolved'
    assert _judge(target, reference, "1d").verdict == nc.ERA_STOP


def test_an_uninjected_benign_era_passes(reference: dict[int, Era]) -> None:
    target = _era(TARGET_ERA, 1000, seed=98, natural_defects=3)
    for tf in ("5m", "1d"):
        verdict = _judge(target, reference, tf)
        assert verdict.verdict == nc.ERA_OK, verdict
        assert verdict.n_judged == 1000 and not verdict.reasons


def test_a_few_defective_names_flag_but_do_not_stop(
    reference: dict[int, Era],
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
    reference: dict[int, Era],
) -> None:
    """The last_print class is size capped: a close 0.5 percent off inside the high-low range on
    30 percent of days across the whole era is beyond a reference that shows none."""
    ref = {e: _era(e, 300, seed=e, convention_share=0.30) for e in REFERENCE}  # 0.2 percent prints
    big = _era(TARGET_ERA, 1000, seed=95, injected=1000, inject=_close_half_pct_inside_range)
    verdict = _judge(big, ref)
    assert verdict.verdict == nc.ERA_STOP and "unexplained_other" in verdict.reasons


def _close_half_pct_inside_range(m: Series, rng: np.random.Generator, i: int) -> Series:
    bad = rng.random(N_BARS) < 0.30
    return (*m[:3], np.where(bad, m[3] * 1.005, m[3]))


def test_an_empty_clean_set_is_never_ok(reference: dict[int, Era]) -> None:
    every = _era(TARGET_ERA, 400, seed=94, injected=400, inject=_x100)
    verdict = _judge(every, reference)
    assert verdict.verdict == nc.ERA_STOP and "empty_clean_set" in verdict.reasons


def test_an_era_without_judged_names_writes_an_explicit_verdict(
    reference: dict[int, Era],
) -> None:
    verdict = _judge(Era([], 0), reference)
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
    reference: dict[int, Era],
) -> None:
    """A reference era is judged against the OTHER reference eras: against its own counters the
    3x rule could never fire."""
    judged = {(e, "5m"): r.facts for e, r in reference.items()}
    injected = _era(2015, 1000, seed=93, injected=200, inject=_x100)
    judged[(2015, "5m")] = injected.facts
    unresolved = {(e, "5m"): r.unresolved for e, r in reference.items()}
    unresolved[(2015, "5m")] = injected.unresolved
    verdict = runner.era_verdicts(judged, list(REFERENCE), unresolved)[(2015, "5m")]
    assert verdict.verdict == nc.ERA_STOP and "level_class_share>0.0200" in verdict.reasons
    clean = runner.era_verdicts(
        {(e, "5m"): r.facts for e, r in reference.items()},
        list(REFERENCE),
        {(e, "5m"): r.unresolved for e, r in reference.items()},
    )
    assert all(v.verdict == nc.ERA_OK for (_, tf), v in clean.items() if tf == "5m")


def _detail(massive: Series, incumbent: Series) -> dict:
    inc = tuple(np.round(a, 2) for a in incumbent)
    res = {
        tf: asdict(runner.compare_arm("1d", "ibkr", _bars(massive), _bars(inc), [], {}))
        for tf in ("1d", "5m")
    }
    return {
        "listed": True,
        "massive_hole": False,
        "hole_witness": "",
        "split_sources": {},
        "massive_tfs": ["1d", "5m"],
        "ibkr_rescales": [],
        "preclass": nc.ERA_NO_ACTION,
        "alpaca_epoch_seam_possible": False,
        "probable_ibkr_non_split_adjustment": False,
        "splits_in_window": [],
        "splits_after_era": [],
        "split_tapes": {},
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
        runner.write_part(cfg, "name_checks", era, {"key": keys[era], "era": era, "names": names})
    return cfg, keys


def test_stage_c_assembly_closes_the_partition_with_every_outcome_class(tmp_path) -> None:
    cfg, keys = _write_run(tmp_path, None)
    summary = runner.assemble_stage_c(cfg, [f"N{i}" for i in range(40)], ["U"], keys, "s", {}, {})
    assert summary["partition"]["status"] == "complete"
    counts = summary["partition"]["counts"]
    assert counts["pass"] == 120 and counts["unmapped"] == 3 and counts["stop"] == 0
    assert summary["vendor_wide_return_agreement"] == "ok"
    assert (tmp_path / "stageC_era_tables.csv").exists()


def test_stage_c_assembly_stops_the_injected_era_and_only_that_era(tmp_path) -> None:
    cfg, keys = _write_run(tmp_path, 2010)  # 10 of 40 names: x100 on all fields
    summary = runner.assemble_stage_c(cfg, [f"N{i}" for i in range(40)], ["U"], keys, "s", {}, {})
    counts = summary["partition"]["counts"]
    assert set(summary["stop_eras_all_sources"]) == {"2010/1d", "2010/5m"}
    assert counts["stop"] == 40 and counts["pass"] == 80 and counts["unmapped"] == 3
    assert summary["vendor_wide_return_agreement"] == "stop"


def _constant_offset(bp: float) -> Injector:
    def inject(m: Series, rng: np.random.Generator, i: int) -> Series:
        return tuple(a * (1 + bp / 1e4) for a in m)  # type: ignore[return-value]

    return inject


def test_a_stable_5bp_offset_on_200_names_is_listed_and_does_not_stop(
    reference: dict[int, Era],
) -> None:
    """The 2 to 10 bp hole: on 250-dollar names a 5 bp constant offset is 12.5 cents, beyond the
    cent tolerance and the rounding class. It reads as a stable constant (adjustment_level), is
    listed, and being under 10 bp it is not a systemic counter."""
    target = _era(
        TARGET_ERA, 1000, seed=92, injected=200, inject=_constant_offset(5), injected_price_scale=10
    )
    verdict = _judge(target, reference)
    assert verdict.verdict in (nc.ERA_OK, nc.ERA_OK_CONVENTION), verdict
    assert verdict.other_share <= nc.OTHER_INVESTIGATE_MAX_SHARE
    listed = [f for f in target.facts if f.median_log_ratio > 4e-4]
    assert len(listed) == 200  # the class is attached; only the counters ignore it
    assert all(f.level_class == "" for f in listed)  # not counted: under 10 bp


def test_a_5bp_offset_that_is_not_constant_lands_in_other(reference: dict[int, Era]) -> None:
    def on_30_percent(m: Series, rng: np.random.Generator, i: int) -> Series:
        bad = rng.random(N_BARS) < 0.30  # all four fields 5 bp off on 30 percent of bars
        return tuple(np.where(bad, a * 1.0005, a) for a in m)  # type: ignore[return-value]

    target = _era(
        TARGET_ERA, 1000, seed=91, injected=200, inject=on_30_percent, injected_price_scale=10
    )
    verdict = _judge(target, reference)
    assert verdict.class_mix.get("other", 0) > 0  # no stable constant: not scale, not rounding


def test_200_thin_names_never_stop_an_era_but_200_decorrelated_names_do(
    reference: dict[int, Era],
) -> None:
    """Thin is a coverage fact and only a disagreement can stop an era: 200 names with 15 sessions
    (identity unresolved, listed) leave the verdict ok; 200 names decorrelated by a close 5 percent
    off on 30 percent of days stop it."""
    thin = _era(TARGET_ERA, 1000, seed=90, thin=200, natural_defects=3)
    assert thin.thin == 200 and thin.unresolved == 0
    verdict = _judge(thin, reference)
    assert verdict.verdict in (nc.ERA_OK, nc.ERA_OK_CONVENTION), verdict
    assert verdict.counters.identity_unresolved_share == 0.0
    decorrelated = _era(
        TARGET_ERA, 1000, seed=89, injected=200, inject=_close_5pct_off, natural_defects=3
    )
    assert decorrelated.thin == 0 and decorrelated.unresolved == 200
    stopped = _judge(decorrelated, reference)
    assert stopped.verdict == nc.ERA_STOP
    assert any(r.startswith("identity_unresolved_share") for r in stopped.reasons)


def _write_parts(tmp_path, details_by_era: dict[int, dict[str, dict]]):
    from pathlib import Path

    cfg = runner.Config(
        Path(tmp_path), Path(tmp_path), 1, 6, tuple(sorted(details_by_era)), False, 0.0
    )
    keys = {}
    for era, names in details_by_era.items():
        keys[era] = {"era": era}
        runner.write_part(cfg, "name_checks", era, {"key": keys[era], "era": era, "names": names})
    return cfg, keys


def _clean_names(era: int, n: int, seed: int) -> dict[str, dict]:
    rng = np.random.default_rng(seed)
    out = {}
    for i in range(n):
        series = _name_series(rng)
        out[f"N{i}"] = _detail(series, series)
    return out


def _outcomes(tmp_path) -> dict[tuple[str, int], tuple[str, str]]:
    import json

    cells = json.loads((tmp_path / "stageC_partition.json").read_text())["cells"]
    return {(n, e): (o, r) for n, e, o, r in cells}


def test_a_missing_in_era_split_is_flagged_and_reaches_the_ledger(tmp_path) -> None:
    """A 2:1 split missing from the frozen table on Mar 1: bars before it sit at twice the
    incumbent. It is a level break of split size, so the name-era is flagged and in the ledger,
    not passed as drift. A benign small drift still passes, listed."""
    names = _clean_names(2010, 150, seed=70)
    rng = np.random.default_rng(71)
    broken = _name_series(rng)
    before = np.array([d < date(2010, 3, 1) for d in DAYS])
    missing = tuple(np.where(before, a * 2.0, a) for a in broken)
    names["BROKEN"] = _detail(missing, broken)  # type: ignore[arg-type]
    drifting = _name_series(rng)
    ramp = 1 + np.linspace(0.0, 0.003, N_BARS)
    names["DRIFT"] = _detail(tuple(a * ramp for a in drifting), drifting)  # type: ignore[arg-type]
    cfg, keys = _write_parts(tmp_path, {2010: names})
    runner.assemble_stage_c(cfg, list(names), [], keys, "s", {}, {})
    out = _outcomes(tmp_path)
    assert out[("BROKEN", 2010)] == (nc.OUTCOME_FLAGGED, "scale_factor_split_like_1d")
    assert out[("DRIFT", 2010)][0] == nc.OUTCOME_PASS and out[("DRIFT", 2010)][1].endswith(
        "_listed"
    )
    ledger = (tmp_path / "stageC_disagreement_ledger.csv").read_text()
    assert "BROKEN" in ledger and "level_class:split_like_level" in ledger


def test_other_concentration_carriers_are_flagged_not_passed(tmp_path) -> None:
    names = _clean_names(2010, 200, seed=72)
    for i in range(30):  # 8 percent of each carrier's bars unexplained: 1.2 percent overall
        detail = names[f"N{i}"]
        for tf in ("1d", "5m"):
            detail["arms"]["ibkr"][tf]["classes"] = {"other": 12}
    cfg, keys = _write_parts(tmp_path, {2010: names})
    runner.assemble_stage_c(cfg, list(names), [], keys, "s", {}, {})
    out = _outcomes(tmp_path)
    assert all(
        out[(f"N{i}", 2010)] == (nc.OUTCOME_FLAGGED, "other_concentration") for i in range(30)
    )
    assert out[("N100", 2010)][0] == nc.OUTCOME_PASS
    assert (
        "N0|2010|other_concentration" in (tmp_path / "stageC_gap_list_additions.json").read_text()
    )


def test_a_thin_reference_era_does_not_raise_the_thresholds(
    reference: dict[int, Era],
) -> None:
    thin_facts = _era(2013, 5, seed=60, natural_defects=5).facts  # every name flagged, 5 judged
    judged = {(e, "5m"): r.facts for e, r in reference.items()}
    base = runner.era_verdicts(dict(judged), [TARGET_ERA, *reference], None)[(TARGET_ERA, "5m")]
    judged[(2014, "5m")] = thin_facts  # replace a reference era by a thin one with a high counter
    thin = runner.era_verdicts(judged, [TARGET_ERA, *reference], None)[(TARGET_ERA, "5m")]
    assert thin.thresholds["flagged_share"] <= base.thresholds["flagged_share"] or (
        thin.thresholds["flagged_share"] == nc.COUNTER_FLOOR_SHARE
    )
    assert "2014" not in thin.calibration.split(",")


def test_a_1d_unresolved_era_never_flags_carriers_through_1d(tmp_path) -> None:
    """The 1d close convention (residual above 0.5 percent, every name still at 99 percent) makes
    the 1d verdict unresolved; carriers of unexplained pairs seen only on 1d stay pass."""
    names = _clean_names(2010, 200, seed=73)
    for i, detail in enumerate(names.values()):
        one_d = detail["arms"]["ibkr"]["1d"]
        one_d["n_ret_agree"] = one_d["n_ret_pairs"] - 1  # 148 of 149: 99.3 percent, residual 0.67
        if i < 30:
            one_d["classes"] = {"other": 12}
    cfg, keys = _write_parts(tmp_path, {2010: names})
    summary = runner.assemble_stage_c(cfg, list(names), [], keys, "s", {}, {})
    out = _outcomes(tmp_path)
    assert summary["unresolved_1d_eras"] == [2010]
    assert all(out[(f"N{i}", 2010)][0] == nc.OUTCOME_PASS for i in range(30))


def _flat_stale(m: Series, rng: np.random.Generator, i: int) -> Series:
    return tuple(np.full(N_BARS, 25.0) for _ in m)  # type: ignore[return-value]


def test_200_flat_stale_massive_series_stop_the_era(reference: dict[int, Era]) -> None:
    """A degenerate series (zero variance on one arm while the other varies) is a disagreement:
    decorrelated, never thin."""
    target = _era(TARGET_ERA, 1000, seed=88, injected=200, inject=_flat_stale, natural_defects=3)
    assert target.thin == 0 and target.unresolved == 200
    verdict = _judge(target, reference)
    assert verdict.verdict == nc.ERA_STOP
    assert any(r.startswith("identity_unresolved_share") for r in verdict.reasons)


def test_a_close_convention_at_the_reference_rate_is_unresolved_for_1d_5m_alone() -> None:
    """The close convention present in the reference eras at the SAME rate as in the target: the
    names fail the return test but the disagreement is explained at the reference rate, so the
    class counters stay quiet. 1d is unresolved (close convention), 5m is ok, the era does not
    stop."""
    ref_1d = {e: _era(e, 300, seed=e, convention_share=0.30) for e in REFERENCE}
    ref_5m = {e: _era(e, 300, seed=e + 100) for e in REFERENCE}
    one_d = _era(TARGET_ERA, 1000, seed=87, convention_share=0.30)
    five_m = _era(TARGET_ERA, 1000, seed=86)
    judged = {(e, "1d"): r.facts for e, r in ref_1d.items()}
    judged |= {(e, "5m"): r.facts for e, r in ref_5m.items()}
    judged[(TARGET_ERA, "1d")], judged[(TARGET_ERA, "5m")] = one_d.facts, five_m.facts
    out = runner.era_verdicts(judged, [TARGET_ERA, *REFERENCE])
    assert sum(f.flagged for f in one_d.facts) > 100  # the names do fail the return test
    assert out[(TARGET_ERA, "1d")].verdict == nc.ERA_UNRESOLVED
    assert "close_convention" in out[(TARGET_ERA, "1d")].reasons
    assert out[(TARGET_ERA, "5m")].verdict == nc.ERA_OK
    assert runner._close_convention_unresolved(out[(TARGET_ERA, "1d")])


def _last_print_facts(n_names: int, hit_share: float, bars: int) -> list[nc.NameFacts]:
    """Names where ``bars`` of 150 are a capped last_print (a 20 bp close difference) on
    ``hit_share`` of the names."""
    out = []
    for i in range(n_names):
        k = bars if i < n_names * hit_share else 0
        counts = nc.AgreementCounts(
            150,
            150 - k,
            150 - k,
            {"last_print": k} if k else {},
            149,
            149 - 2 * k,
            150,
            150,
            {20: k} if k else {},
        )
        out.append(nc.NameFacts(f"L{i}", counts, 149 - 2 * k < 0.99 * 149, "", 0.0))
    return out


def test_a_capped_last_print_above_the_reference_rate_is_unresolved_on_1d_and_stops_on_5m() -> None:
    """Which-side-is-right on the 1d close needs a third witness: 1d is unresolved (close
    convention), never a stop; on 5m the same counter still stops."""
    ref = {e: _last_print_facts(300, 0.05, 1) for e in REFERENCE}
    target = _last_print_facts(1000, 0.6, 5)
    for tf, verdict in (("1d", nc.ERA_UNRESOLVED), ("5m", nc.ERA_STOP)):
        judged = {(e, tf): f for e, f in ref.items()} | {(TARGET_ERA, tf): target}
        out = runner.era_verdicts(judged, [TARGET_ERA, *REFERENCE])[(TARGET_ERA, tf)]
        assert out.verdict == verdict, (tf, out)
        assert out.counters.last_print_share > out.thresholds["last_print_share"]
    one_d = runner.era_verdicts(
        {(e, "1d"): f for e, f in ref.items()} | {(TARGET_ERA, "1d"): target},
        [TARGET_ERA, *REFERENCE],
    )[(TARGET_ERA, "1d")]
    assert "close_convention" in one_d.reasons


def test_a_whole_era_one_session_shift_on_the_1d_file_stops() -> None:
    def shifted(m: Series, rng: np.random.Generator, i: int) -> Series:
        return tuple(np.roll(a, 1) for a in m)  # type: ignore[return-value]

    ref = {e: _era(e, 300, seed=e) for e in REFERENCE}
    target = _era(TARGET_ERA, 1000, seed=83, injected=1000, inject=shifted)
    judged = {(e, "1d"): r.facts for e, r in ref.items()}
    judged[(TARGET_ERA, "1d")] = target.facts
    unresolved = {(e, "1d"): 0 for e in REFERENCE} | {(TARGET_ERA, "1d"): target.unresolved}
    out = runner.era_verdicts(judged, [TARGET_ERA, *REFERENCE], unresolved)
    assert out[(TARGET_ERA, "1d")].verdict == nc.ERA_STOP


def _shift_facts(n_names: int, hit_share: float, bars: int) -> list[nc.NameFacts]:
    """Names where ``bars`` of 150 bars are classed time_shift (a bar-stamp convention) on
    ``hit_share`` of the names: the returns fail but the disagreement is explained."""
    out = []
    for i in range(n_names):
        k = bars if i < n_names * hit_share else 0
        counts = nc.AgreementCounts(
            150, 150 - k, 150 - k, {"time_shift": k} if k else {}, 149, 149 - 2 * k, 150, 150
        )
        out.append(nc.NameFacts(f"S{i}", counts, 149 - 2 * k < 0.99 * 149, "", 0.0))
    return out


def test_a_bar_stamp_convention_passes_at_the_reference_rate_and_stops_when_absent_there() -> None:
    """5 of 150 bars time-shifted on 60 percent of the names. Present in the reference eras at
    the same rate: calibrated, the era is ok_convention. Absent from them: the time_shift
    counter stops the era."""
    same = {e: _shift_facts(300, 0.6, 5) for e in REFERENCE}
    judged = {(e, "5m"): f for e, f in same.items()} | {
        (TARGET_ERA, "5m"): _shift_facts(1000, 0.6, 5)
    }
    passes = runner.era_verdicts(judged, [TARGET_ERA, *REFERENCE])[(TARGET_ERA, "5m")]
    assert passes.verdict == nc.ERA_OK_CONVENTION, passes
    assert passes.counters.time_shift_share == pytest.approx(0.6)
    none = {e: _shift_facts(300, 0.0, 0) for e in REFERENCE}
    judged = {(e, "5m"): f for e, f in none.items()} | {
        (TARGET_ERA, "5m"): _shift_facts(1000, 0.6, 5)
    }
    stops = runner.era_verdicts(judged, [TARGET_ERA, *REFERENCE])[(TARGET_ERA, "5m")]
    assert stops.verdict == nc.ERA_STOP
    assert any(r.startswith("time_shift_share") for r in stops.reasons)


def test_the_same_era_with_a_real_defect_still_stops() -> None:
    ref_1d = {e: _era(e, 300, seed=e, convention_share=0.004) for e in REFERENCE}
    target = _era(
        TARGET_ERA,
        1000,
        seed=85,
        convention_share=0.30,
        injected=200,
        inject=_close_5pct_off,
    )
    judged = {(e, "1d"): r.facts for e, r in ref_1d.items()}
    judged[(TARGET_ERA, "1d")] = target.facts
    unresolved = {(TARGET_ERA, "1d"): target.unresolved} | {(e, "1d"): 0 for e in REFERENCE}
    out = runner.era_verdicts(judged, [TARGET_ERA, *REFERENCE], unresolved)
    assert out[(TARGET_ERA, "1d")].verdict == nc.ERA_STOP


def test_a_stop_on_one_timeframe_stops_only_the_cells_judged_on_it() -> None:
    outcomes = {
        ("A", 2010): ("pass", ""),
        ("B", 2010): ("pass", ""),
        ("C", 2010): ("flagged", "price_agreement_1d"),
        ("D", 2010): ("no_detector", "no_detector"),
        ("E", 2010): ("not_listed_in_era", "not_listed_in_era"),
    }
    tfs = {
        ("A", 2010): ("1d",),
        ("B", 2010): ("5m",),
        ("C", 2010): ("1d", "5m"),
        ("D", 2010): ("5m",),
    }
    out = runner.apply_timeframe_stops(outcomes, tfs, {}, {(2010, "1d"): "x"})
    assert out[("A", 2010)][0] == "stop" and out[("B", 2010)][0] == "pass"
    assert out[("C", 2010)][0] == "flagged"  # judged on 5m too, which is not stopped
    assert out[("D", 2010)][0] == "no_detector"  # a price stop cannot reach a detector-less cell
    both = runner.apply_timeframe_stops(outcomes, tfs, {}, {(2010, "1d"): "x", (2010, "5m"): "y"})
    assert both[("C", 2010)][0] == "stop" and both[("B", 2010)][0] == "stop"
    assert both[("D", 2010)][0] == "no_detector" and both[("E", 2010)][0] == "not_listed_in_era"


def test_a_stage_a_session_stop_reaches_the_no_detector_cells_of_its_timeframe() -> None:
    outcomes = {("P", 2004): ("no_detector", "no_detector"), ("Q", 2004): ("no_detector", "x")}
    tfs = {("P", 2004): ("5m",), ("Q", 2004): ("1d",)}
    out = runner.apply_timeframe_stops(outcomes, tfs, {(2004, "5m"): "session"}, {})
    assert out[("P", 2004)] == ("stop", "systemic_stop:5m:session")
    assert out[("Q", 2004)][0] == "no_detector"  # its timeframe (1d) is not stopped


def test_the_return_residual_is_a_share_in_zero_one(tmp_path) -> None:
    import csv

    cfg, keys = _write_run(tmp_path, 2010)
    runner.assemble_stage_c(cfg, [f"N{i}" for i in range(40)], ["U"], keys, "s", {}, {})
    for row in csv.DictReader((tmp_path / "stageC_era_tables.csv").open()):
        if row["return_residual"] not in ("", "nan"):
            assert 0.0 <= float(row["return_residual"]) <= 1.0, row


def test_a_stopped_era_timeframe_writes_its_top_contributors_with_timestamps(tmp_path) -> None:
    import csv

    cfg, keys = _write_run(tmp_path, 2010)
    runner.assemble_stage_c(cfg, [f"N{i}" for i in range(40)], ["U"], keys, "s", {}, {})
    rows = list(csv.DictReader((tmp_path / "stageC_stop_contributors.csv").open()))
    assert {r["timeframe"] for r in rows} == {"1d", "5m"} and {r["era"] for r in rows} == {"2010"}
    assert float(rows[0]["unexplained_share"]) >= 0 and "scale" in rows[0]["class_mix"]
    assert rows[0]["first_disagree"] and rows[0]["last_disagree"] >= rows[0]["first_disagree"]


# ---- the definition witness (design 8a, r5i): incumbent close = Massive's last RTH trade -------
def _definition_facts(
    n_names: int, seed: int, *, incumbent_is_last: bool, defect_names: int = 0
) -> Era:
    """1d names whose day-file close is the official close and whose last RTH 5m close differs from
    it by up to 40 bp (beyond rounding). The incumbent carries the last trade (``incumbent_is_last``) or the official
    close. ``defect_names`` of them also carry a 5 percent close error on 30 percent of days."""
    rng = np.random.default_rng(seed)
    out: list[nc.NameFacts] = []
    unresolved = 0
    for i in range(n_names):
        series = _name_series(rng)
        official = series[3]
        last = official * (1 + rng.uniform(-0.004, 0.004, N_BARS))
        incumbent = np.round(last if incumbent_is_last else official, 2)
        inc_series = (incumbent * 0.99, incumbent * 1.01, incumbent * 0.98, incumbent)
        massive = series
        if i < defect_names:
            bad = rng.random(N_BARS) < 0.30
            massive = (*series[:3], np.where(bad, official * 1.05, official))
        witness = (KEYS.astype("int64"), last)
        result = runner.compare_arm(
            "1d", "ibkr", _bars(massive), _bars(inc_series), [], {}, witness
        )
        detail = {"arms": {"ibkr": {"1d": asdict(result)}}}
        gate = runner.judged_timeframes({"1d": result}, nc.ERA_NO_ACTION, True)
        if gate.outcome:
            unresolved += gate.reason == "identity_decorrelated"
            continue
        facts = runner._name_facts(f"D{seed}_{i}", detail, "1d", gate.usable)
        if facts is not None:
            out.append(facts)
    return Era(out, unresolved)


def test_a_witnessed_close_definition_is_unresolved_and_a_real_defect_in_it_still_stops() -> None:
    ref = {e: _definition_facts(300, e, incumbent_is_last=False) for e in REFERENCE}
    for e in REFERENCE:  # the reference rate: the day-file match dominates, no era is witnessed
        assert not nc.close_definition_witnessed(ref[e].facts)
    witnessed = _definition_facts(1000, 70, incumbent_is_last=True)
    day, last = nc.definition_shares(witnessed.facts)
    assert last - day > nc.DEFINITION_MARGIN and last > 0.9 and day < 0.6, (day, last)

    def judge(target: Era):
        judged = {(e, "1d"): r.facts for e, r in ref.items()} | {(TARGET_ERA, "1d"): target.facts}
        unres = {(e, "1d"): 0 for e in REFERENCE} | {(TARGET_ERA, "1d"): target.unresolved}
        return runner.era_verdicts(judged, [TARGET_ERA, *REFERENCE], unres)[(TARGET_ERA, "1d")]

    v = judge(witnessed)
    assert v.verdict == nc.ERA_UNRESOLVED and "close_definition_witnessed" in v.reasons
    assert v.close_definition_witnessed and v.share_last_trade > v.share_dayfile
    assert runner._close_convention_unresolved(v)
    defect = judge(_definition_facts(1000, 71, incumbent_is_last=True, defect_names=200))
    assert defect.verdict == nc.ERA_STOP


def test_the_same_data_without_a_witness_counts_the_definition_bars_as_other() -> None:
    """When the incumbent follows the OFFICIAL close the last-trade match is low: no witness, so a
    stray close_definition bar is not explained."""
    plain = _definition_facts(300, 72, incumbent_is_last=False)
    assert not nc.close_definition_witnessed(plain.facts)
    folded = nc.fold_definition(
        nc.NameFacts(
            "X",
            nc.AgreementCounts(
                150,
                140,
                140,
                {"close_definition": 10},
                149,
                149,
                150,
                150,
                def_fallback={"other": 6, "rounding": 4},
            ),
            False,
            "",
            0.0,
        )
    )
    assert folded.counts.n_class == {"other": 6, "rounding": 4}  # each bar's own fallback


def test_bars_of_a_level_drift_name_are_scale_only_near_the_local_drift_level() -> None:
    n = 100
    close = np.linspace(20, 30, n)
    drift = 1 + np.linspace(0.0, 0.01, n)  # a 1 percent drift across the era
    big = np.zeros(n, dtype=bool)
    big[[20, 50, 80]] = True  # a few 20 percent bars
    massive = close * drift * np.where(big, 1.2, 1.0)
    labels = nc.classify_disagreements(
        _name_ohlc(massive), _name_ohlc(close), None, None, 0.0001, [], True
    )
    assert set(labels[~big]) - {""} == {"scale"}  # an agreeing bar carries no label
    assert set(labels[big]) == {"other"}  # larger errors stay other
    none = nc.classify_disagreements(
        _name_ohlc(close * 1.003), _name_ohlc(close), None, None, 0.0001, [], False
    )
    assert set(none) == {"other"}


def _name_ohlc(close: np.ndarray):
    return (close * 0.99, close * 1.01, close * 0.98, close.copy())


def test_the_fold_is_one_place_and_contributors_and_class_totals_read_it() -> None:
    counts = nc.AgreementCounts(
        150, 140, 140, {"close_definition": 10}, 149, 149, 150, 150,
        def_fallback={"rounding": 10}, n_alt=150, n_alt_dayfile=150, n_alt_last=0,
    )  # fmt: skip
    facts = [nc.NameFacts(f"F{i}", counts, False, "", 0.0) for i in range(30)]
    folded, witness = runner.fold_unwitnessed({(2010, "1d"): facts}, [2010])
    assert not witness[(2010, "1d")]
    assert folded[(2010, "1d")][0].counts.n_class == {"rounding": 10}
    assert runner._folded_classes(
        {"classes": {"close_definition": 10}, "def_fallback": {"rounding": 10}}
    ) == {"rounding": 10}
