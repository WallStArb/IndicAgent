"""S2b alignment and S3 guards for feature and kernel members (plan 184-10).

Synthetic snapshots are written the way snapshot.build_panel lays them out: equal-tf arrays in the
book dir, a coarser source as a child dir, a finer source as an int32 source-row index plus
referenced values and the raw probe bars.
"""

import dataclasses
from datetime import date

import numpy as np
import pytest

from src.intelligence.bars.sessions import nyse_sessions
from src.intelligence.research import align, clock, guards, kernel_source, smoothing, snapshot
from src.intelligence.research import panel as panel_mod
from src.intelligence.research import runner as runner_mod
from src.intelligence.research.runner import InputSources
from src.intelligence.research.spec import parse_spec_text
from tests.unit.research.mtf_fixtures import daily_grid, intraday_grid
from tests.unit.research.test_runner_feature_spec import (
    BLOCK,
    CONFIG,
    CONFIGS,
    FEATURE,
    PIN,
    feature_member,
    kernel_member,
    make_spec,
)
from tests.unit.research.test_runner_order import _spec_text

SESSIONS = sorted(nyse_sessions(date(2024, 3, 4), date(2024, 6, 28)))
SYMS = tuple(f"S{i}" for i in range(8))
FLOOR = 3


def spec_of(members, *, tf="1d", bps=1):
    spec = make_spec(members, tf=tf, bps=bps)
    construction = spec.construction.model_copy(update={"coverage_floor": FLOOR})
    return spec.model_copy(update={"construction": construction})


def manifest_for(*tfs, probe=()):
    return {
        "sources": {
            tf: {
                "config_hash": PIN,
                "provenance": {**BLOCK, "code_key": f"ck-{tf}"},
                "probe_symbols": list(probe),
            }
            for tf in tfs
        }
    }


def book_panel(tf, tfs, seed=0, probe=()):
    grid = (daily_grid if tf == "1d" else lambda s, y, z: intraday_grid(tf, s, y, z))(
        SESSIONS, SYMS, seed
    )
    return dataclasses.replace(
        grid,
        closes_at=clock.closes_at(grid.timestamps, grid.valid, tf, grid.bars_per_session),
        manifest=manifest_for(*tfs, probe=probe),
    )


def with_range(panel):
    """High and low around the close, as S0 captures them for a kernel that reads them."""
    return dataclasses.replace(panel, high=panel.close * 1.01, low=panel.close * 0.99)


def attach(book, tmp_path, extra=None, children=None):
    path = panel_mod.save(book, tmp_path / "book", extra or {})
    return dataclasses.replace(book, sources=InputSources(path, book.symbols, children or {}))


def stored_values(shape, seed=1, nan_rate=0.05):
    rng = np.random.default_rng(seed)
    values = rng.normal(size=shape).astype(np.float32)
    values[rng.random(shape) < nan_rate] = np.nan
    return values


def feature_name(tf):
    return f"feature__{tf}__{FEATURE}"


def equal_snapshot(tmp_path, member, *, kernel=False, values=None):
    """A 1d book with a 1d source in its own dir."""
    book = book_panel("1d", ("1d",))
    if kernel:
        book = with_range(book)
        col = member.input.column
        values = kernel_source.kernel_source(
            book,
            [col],
            dict(member.input.windows),
            CONFIG,
            max_gap_rows=member.input.max_gap_rows,
            high=book.high,
            low=book.low,
        ).values[col]
        name = f"kernel__1d__{member.name}"
    else:
        values = stored_values(book.close.shape) if values is None else values
        name = feature_name("1d")
    return attach(book, tmp_path, {name: values}), values


def finer_snapshot(tmp_path, member, *, values=None, kernel=False):
    """A 1d book with a 1h source, laid out as snapshot._finer_source persists it."""
    book = book_panel("1d", ("1h",), probe=SYMS[:3])
    src = intraday_grid("1h", SESSIONS, SYMS, 5)
    if kernel:
        src = with_range(src)
        col = member.input.column
        values = kernel_source.kernel_source(
            src,
            [col],
            dict(member.input.windows),
            CONFIG,
            max_gap_rows=member.input.max_gap_rows,
            high=src.high,
            low=src.low,
        ).values[col]
    elif values is None:
        values = stored_values(src.close.shape)
    src_closes = clock.closes_at(src.timestamps, src.valid, "1h", 7)
    idx = align.align_index(
        np.isfinite(values), src_closes, book.closes_at, member.input.max_age_rows
    )
    rows = np.unique(idx[idx >= 0])
    ref = np.full((len(rows), idx.shape[1]), np.nan, dtype=np.float32)
    for j in range(idx.shape[1]):
        used = idx[:, j]
        hit = used >= 0
        ref[np.searchsorted(rows, used[hit]), j] = values[used[hit], j]
    extra = {
        "src_ts__1h": src.timestamps,
        "src_valid__1h": src.valid,
        f"idx__{member.name}": idx,
        f"ref_rows__{member.name}": rows.astype(np.int32),
        f"ref_values__{member.name}": ref,
    }
    if kernel:
        probe = np.full((len(src.timestamps), 3, 5), np.nan)
        for i in range(3):
            for f, field in ((0, "open"), (1, "high"), (2, "low"), (3, "close"), (4, "volume")):
                probe[:, i, f] = getattr(src, field)[:, i]
        extra["probe_bars__1h"] = probe
    return attach(book, tmp_path, extra), values, src


def fn_of(spec, m, panel):
    return runner_mod._member_fn(spec, m, panel.bars_per_session)


ROWS = np.array([30, 45, 60, 75])


def guard(spec, m, panel, rows=ROWS):
    return runner_mod._guard_input_member(spec, m, panel, fn_of(spec, m, panel), rows)


# --- dispatch -----------------------------------------------------------------------------


def test_dispatch_resid_bar_member_gets_the_same_object():
    spec = parse_spec_text(_spec_text())
    resid = np.zeros((4, 3))
    for m in spec.members:
        assert runner_mod.member_input(spec, m, None, resid) is resid


def test_dispatch_equal_tf_feature_is_aligned_in_s2b(tmp_path):
    spec = spec_of([feature_member("f1")])
    m = spec.members[0]
    panel, values = equal_snapshot(tmp_path, m)
    x = runner_mod.member_input(spec, m, panel, None)
    assert x.dtype == np.float32
    expected = align.align(values, panel.closes_at, panel.closes_at, 1)
    assert np.array_equal(x, expected, equal_nan=True)
    # a single missing source row ages one row (carry within max_age_rows=1), two do not
    gap = values.copy()
    gap[10, 0] = gap[20, 0] = gap[21, 0] = np.nan
    panel2, _ = equal_snapshot(tmp_path / "g", m, values=gap)
    y = runner_mod.member_input(spec, m, panel2, None)
    assert y[10, 0] == gap[9, 0] and y[20, 0] == gap[19, 0] and np.isnan(y[21, 0])


def test_dispatch_coarser_source_reads_the_prior_session_until_the_close(tmp_path):
    spec = spec_of([feature_member("f1", tf="1d", bps=7)], tf="1h", bps=7)
    m = spec.members[0]
    book = book_panel("1h", ("1d",))
    daily = daily_grid(SESSIONS, SYMS, 3)
    values = stored_values(daily.close.shape, nan_rate=0)
    child = panel_mod.save(daily, tmp_path / "child", {feature_name("1d"): values})
    panel = attach(book, tmp_path, children={"1d": child})
    x = runner_mod.member_input(spec, m, panel, None)
    day = 10
    rows = slice(day * 7, day * 7 + 7)
    # the six bars closing before 16:00 read yesterday's value; the 15:30 bucket closes at 16:00
    assert np.array_equal(x[rows][:6], np.broadcast_to(values[day - 1], (6, len(SYMS))))
    assert np.array_equal(x[rows][6], values[day])


def test_input_member_without_loaded_sources_names_the_tf():
    spec = spec_of([feature_member("f1", tf="1h")])
    with pytest.raises(ValueError, match="1h"):
        runner_mod.member_input(spec, spec.members[0], book_panel("1d", ("1h",)), None)


def test_members_universe_narrowing_selects_columns(tmp_path):
    spec = spec_of([feature_member("f1")])
    m = spec.members[0]
    panel, values = equal_snapshot(tmp_path, m)
    narrow = panel_mod.select_symbols(panel, [SYMS[1], SYMS[4], SYMS[6]])
    assert narrow.sources is panel.sources
    x = runner_mod.member_input(spec, m, narrow, None)
    full = runner_mod.member_input(spec, m, panel, None)
    assert np.array_equal(x, full[:, [1, 4, 6]], equal_nan=True)
    bogus = dataclasses.replace(narrow, symbols=("S1", "S4", "S6~1"))
    with pytest.raises(runner_mod.RunRefused, match="S6~1"):
        runner_mod.member_input(spec, m, bogus, None)


# --- replay -------------------------------------------------------------------------------


def test_replay_finer_source_is_bit_equal_to_align_and_calls_no_align_index(tmp_path, monkeypatch):
    spec = spec_of([feature_member("f1", tf="1h")])
    m = spec.members[0]
    panel, values, src = finer_snapshot(tmp_path, m)

    def boom(*a, **k):
        raise AssertionError("align_index called for a finer source")

    src_closes = clock.closes_at(src.timestamps, src.valid, "1h", 7)
    expected = align.align(values, src_closes, panel.closes_at, m.input.max_age_rows)
    monkeypatch.setattr(runner_mod.align, "align_index", boom)
    x = runner_mod.member_input(spec, m, panel, None)
    assert x.dtype == np.float32 and np.array_equal(x, expected, equal_nan=True)
    # the full-length 1h value array was never written, so nothing could have loaded it
    assert not panel.sources.has(feature_name("1h"))
    assert panel.sources.array(f"ref_values__{m.name}").shape[0] < values.shape[0]


def test_dispatch_1d_value_on_a_1h_book_follows_the_close(tmp_path):
    # D7 guard 2: the 1h book never reads the same-session daily value before the 16:00 close
    spec = spec_of([feature_member("f1", tf="1d", bps=7)], tf="1h", bps=7)
    m = spec.members[0]
    book = book_panel("1h", ("1d",))
    daily = daily_grid(SESSIONS, SYMS, 3)
    values = stored_values(daily.close.shape, nan_rate=0)
    child = panel_mod.save(daily, tmp_path / "child", {feature_name("1d"): values})
    panel = attach(book, tmp_path, children={"1d": child})
    index = runner_mod.member_index(spec, m, panel)
    align.check_alignment(
        index.src_idx, index.src_closes, panel.closes_at, 1, np.arange(len(panel.timestamps))
    )


# --- smoothing ----------------------------------------------------------------------------


def test_smoothing_is_applied_after_alignment(tmp_path):
    spec = spec_of([feature_member("f1", smoothing=5)])
    m = spec.members[0]
    panel, values = equal_snapshot(
        tmp_path, m, values=stored_values((len(SESSIONS), 8), nan_rate=0)
    )
    aligned = align.align(values, panel.closes_at, panel.closes_at, 1)
    assert np.array_equal(
        runner_mod.member_input(spec, m, panel, None),
        smoothing.smooth(aligned, 5),
        equal_nan=True,
    )


# --- S3: every scored row ----------------------------------------------------------------


def test_every_row_a_clean_index_passes_and_reports_the_rows_checked(tmp_path):
    spec = spec_of([feature_member("f1", tf="1h")])
    m = spec.members[0]
    panel, _, _ = finer_snapshot(tmp_path, m)
    reach, report = guard(spec, m, panel)
    assert report["alignment_rows_checked"] == len(panel.timestamps)
    assert report["kind"] == "feature" and report["source_tf"] == "1h"


def retarget(tmp_path, panel, m, edit):
    idx = np.array(panel.sources.array(f"idx__{m.name}"))
    edit(idx)
    np.save(panel.sources.path / f"idx__{m.name}.npy", idx)
    return (
        dataclasses.replace(panel, sources=InputSources(panel.sources.path, panel.symbols, {})),
        idx,
    )


def test_every_row_an_index_past_the_decision_close_fails(tmp_path):
    spec = spec_of([feature_member("f1", tf="1h")])
    m = spec.members[0]
    panel, _, src = finer_snapshot(tmp_path, m)
    ref_rows = panel.sources.array(f"ref_rows__{m.name}")

    def edit(idx):
        t = 50
        later = next(r for r in ref_rows if r > idx[t, 2])
        idx[t, 2] = later

    bad, _ = retarget(tmp_path, panel, m, edit)
    with pytest.raises(guards.GuardFailure, match=r"lookahead: destination row 50"):
        guard(spec, m, bad)


def test_every_row_an_index_past_max_age_fails(tmp_path):
    spec = spec_of([feature_member("f1", tf="1h")])
    m = spec.members[0]
    panel, _, _ = finer_snapshot(tmp_path, m)
    ref_rows = panel.sources.array(f"ref_rows__{m.name}")

    def edit(idx):
        idx[60, 1] = ref_rows[0]

    bad, _ = retarget(tmp_path, panel, m, edit)
    with pytest.raises(guards.GuardFailure, match="max age"):
        guard(spec, m, bad)


def test_every_row_masks_nothing_it_has_to_check_but_the_prefix(tmp_path):
    spec = spec_of([feature_member("f1", tf="1h")])
    m = spec.members[0]
    panel, _, _ = finer_snapshot(tmp_path, m)
    ref_rows = panel.sources.array(f"ref_rows__{m.name}")
    cut = str(np.datetime_as_string(panel.timestamps[20], unit="s"))
    manifest = {**panel.manifest, "warmup_prefix": {"scored_start": cut + "+00:00"}}

    def edit(idx):
        idx[5, 2] = ref_rows[-1]  # a future read inside the prefix

    bad, _ = retarget(tmp_path, dataclasses.replace(panel, manifest=manifest), m, edit)
    bad = dataclasses.replace(bad, manifest=manifest)
    _, report = guard(spec, m, bad)
    assert report["alignment_rows_checked"] == len(panel.timestamps) - 20

    def edit_scored(idx):
        idx[25, 2] = ref_rows[-1]

    worse, _ = retarget(tmp_path, bad, m, edit_scored)
    with pytest.raises(guards.GuardFailure, match="lookahead"):
        guard(spec, m, dataclasses.replace(worse, manifest=manifest))


def test_src_avail_is_recomputed_so_a_tampered_source_grid_fails_the_check(tmp_path):
    spec = spec_of([feature_member("f1", tf="1h")])
    m = spec.members[0]
    panel, _, _ = finer_snapshot(tmp_path, m)
    valid = np.array(panel.sources.array("src_valid__1h"))
    valid[:20] = False  # rows the persisted index reads now have no availability
    np.save(panel.sources.path / "src_valid__1h.npy", valid)
    bad = dataclasses.replace(panel, sources=InputSources(panel.sources.path, panel.symbols, {}))
    with pytest.raises(guards.GuardFailure, match="lookahead"):
        guard(spec, m, bad)


# --- S3: memory, causality, code key ------------------------------------------------------


def test_memory_declared_at_the_one_memory_object(tmp_path):
    spec = spec_of([feature_member("f1", smoothing=5)])
    m = spec.members[0]
    values = stored_values((len(SESSIONS), 8), nan_rate=0)
    panel, _ = equal_snapshot(tmp_path, m, values=values)
    reach, report = guard(spec, m, panel, rows=np.array([30, 45]))
    memory = runner_mod._member_memory(spec, m, CONFIGS)
    assert report["declared_reach"] == memory.transform_rows
    assert 0 <= reach <= memory.transform_rows


def test_code_key_is_cited_for_a_stored_feature(tmp_path):
    spec = spec_of([feature_member("f1")])
    m = spec.members[0]
    panel, _ = equal_snapshot(tmp_path, m)
    _, report = guard(spec, m, panel)
    assert report["code_key"] == "ck-1d"
    assert "phase 186" in report["value_causality"]


def test_causality_a_future_value_in_a_probed_member_fails(tmp_path):
    spec = spec_of([feature_member("f1")])
    m = spec.members[0]
    panel, _ = equal_snapshot(tmp_path, m)

    def leaky(a):
        out = np.array(a, dtype=float)
        out[:-1] = out[1:]
        return out

    with pytest.raises(guards.GuardFailure, match="lookahead"):
        runner_mod._guard_input_member(spec, m, panel, leaky, ROWS)


# --- kernel members -----------------------------------------------------------------------


def test_kernel_e2e_equal_tf_passes(tmp_path):
    spec = spec_of([kernel_member("k1", family="rk_price_percentile")])
    m = spec.members[0]
    panel, _ = equal_snapshot(tmp_path, m, kernel=True)
    _, report = guard(spec, m, panel)
    assert report["kernel_probe_symbols"] == list(SYMS[: snapshot.PROBE_SYMBOLS])
    assert report["kernel_probe_rows"] == len(ROWS)
    assert "rk_price_percentile" in " ".join(report["kernel_truncation"])


def test_kernel_e2e_finer_source_passes_from_the_probe_bars(tmp_path):
    spec = spec_of([kernel_member("k1", family="rk_price_percentile", tf="1h")])
    m = spec.members[0]
    panel, _, _ = finer_snapshot(tmp_path, m, kernel=True)
    _, report = guard(spec, m, panel)
    assert report["kernel_probe_symbols"] == list(SYMS[:3])


def test_persisted_equal_a_future_value_in_the_stored_kernel_fails(tmp_path):
    spec = spec_of([kernel_member("k1", family="rk_price_percentile")])
    m = spec.members[0]
    book = with_range(book_panel("1d", ("1d",)))
    col = m.input.column
    real = kernel_source.kernel_source(
        book,
        [col],
        dict(m.input.windows),
        CONFIG,
        max_gap_rows=m.input.max_gap_rows,
        high=book.high,
        low=book.low,
    ).values[col]
    shifted = real.copy()
    shifted[:-1] = real[1:]
    panel = attach(book, tmp_path, {f"kernel__1d__{m.name}": shifted})
    with pytest.raises(guards.GuardFailure, match="differs from the kernel recomputed"):
        guard(spec, m, panel)


def test_persisted_equal_a_future_value_in_ref_values_fails(tmp_path):
    spec = spec_of([kernel_member("k1", family="rk_price_percentile", tf="1h")])
    m = spec.members[0]
    panel, _, _ = finer_snapshot(tmp_path, m, kernel=True)
    ref = np.array(panel.sources.array(f"ref_values__{m.name}"))
    ref[40, :3] += 1.0
    np.save(panel.sources.path / f"ref_values__{m.name}.npy", ref)
    with pytest.raises(guards.GuardFailure, match="differs from the kernel recomputed"):
        guard(
            spec,
            m,
            dataclasses.replace(panel, sources=InputSources(panel.sources.path, panel.symbols, {})),
        )


def test_kernel_e2e_a_planted_acausal_kernel_fails(tmp_path, monkeypatch):
    real = kernel_source.kernel_source

    def leaky(panel, outputs, windows, config, **kw):
        result = real(panel, outputs, windows, config, **kw)
        column = result.values[outputs[0]].copy()
        column[:-1] = column[1:]  # row t carries row t + 1's value
        column[-1] = np.nan
        return dataclasses.replace(result, values={**result.values, outputs[0]: column})

    monkeypatch.setattr(kernel_source, "kernel_source", leaky)
    spec = spec_of([kernel_member("k1", family="rk_price_percentile")])
    m = spec.members[0]
    panel, _ = equal_snapshot(tmp_path, m, kernel=True)  # stored with the same leaky kernel
    with pytest.raises(guards.GuardFailure, match=r"lookahead: member k1 alpha row"):
        guard(spec, m, panel)


# --- S0 -> S8 on a synthetic panel -------------------------------------------------------


def test_synthetic_run_with_a_stored_feature_member_completes_s0_to_s8(tmp_path):
    import asyncio

    from src.intelligence.research.runner import BudgetConfig, RunContext, run_family
    from src.intelligence.research.spec import LoadedSpec

    sessions = sorted(nyse_sessions(date(2010, 1, 4), date(2011, 12, 30)))
    n, m = len(sessions), 30
    rng = np.random.default_rng(4)
    r = rng.normal(0, 0.01, (n, m))
    close = 100 * np.exp(np.cumsum(r, axis=0))
    ts = np.array(sessions, dtype="datetime64[D]")
    valid = np.ones(n, dtype=bool)
    book = panel_mod.Panel(
        tf="1d",
        symbols=tuple(f"S{i:02d}" for i in range(m)),
        timestamps=ts,
        bars_per_session=1,
        valid=valid,
        open=close * np.exp(-0.3 * r),
        close=close,
        volume=np.full((n, m), 1e5),
        manifest={
            "start": "2010-01-04",
            "end_exclusive": "2012-01-03",
            "universe": "compute_eligible",
            **manifest_for("1d"),
        },
        closes_at=clock.closes_at(ts, valid, "1d", 1),
    )
    # a source that predicts the next session's return, so the run has something to find
    feature = np.vstack([r[1:], np.full((1, m), np.nan)]).astype(np.float32)
    panel = attach(book, tmp_path, {feature_name("1d"): feature})
    spec = spec_of([feature_member("f1")])
    loaded = LoadedSpec("research/specs/f.yaml", spec, "", "hash", None)
    ctx = RunContext(root=tmp_path, budget=BudgetConfig("test", 1, 0.05))
    out = asyncio.run(run_family(loaded, ctx, mode="synthetic", panel=panel))
    assert out["f1"]["status"] == "completed", out["f1"]
    assert "decision" in out["f1"]["evidence"]
