"""Runner spec-time checks and S0 requests for feature and kernel members (plan 184-09)."""

import asyncio
import dataclasses
from datetime import UTC, datetime
from types import SimpleNamespace

import numpy as np
import pytest

from src.intelligence.research import feature_inputs as fi
from src.intelligence.research import null_battery_persistent as nbp
from src.intelligence.research import panel as panel_mod
from src.intelligence.research import runner as runner_mod
from src.intelligence.research import snapshot, store
from src.intelligence.research.book import book_memory
from src.intelligence.research.combiner import EqualWeight
from src.intelligence.research.horizon import HorizonRule
from src.intelligence.research.member_memory import (
    feature_member_memory_rows,
    feature_member_memory_sessions,
    warmup_prefix_sessions,
)
from src.intelligence.research.null_battery import MEASURED_SLOT_EFFECT_SD, MEASURED_STATIC_CELL_SD
from src.intelligence.research.null_battery_persistent import BatteryCertificate
from src.intelligence.research.runner import RunContext, RunRefused
from src.intelligence.research.smoothing import smoothing_memory_sessions
from src.intelligence.research.spec import parse_spec_text
from src.intelligence.research.timing import e17_memory
from tests.unit.research.test_feature_inputs import REG, _as_stored, _real_config
from tests.unit.research.test_runner_order import _spec_text
from tests.unit.research.test_spec import BOOK, FAMILY

CONFIG = _real_config()
BLOCK = {
    "projection": fi.config_projection(_as_stored(CONFIG)),
    "projection_hash": fi.config_projection_hash(fi.config_projection(_as_stored(CONFIG))),
}
PIN = BLOCK["projection_hash"]
OTHER_PIN = "cd" * 32
CONFIGS = {"1d": CONFIG, "1h": CONFIG, "15m": CONFIG}
FEATURE = "price_percentile_slow"
KERNEL = "rk_vwap_dev"
BIG = 10**6
START, END = "2010-01-04", "2012-01-03"
CENTRED = "src.intelligence.research.families.features.centred"
BPS_OF = {"1d": 1, "1h": 7, "15m": 26, "5m": 78}


def feature_in(column=FEATURE, tf="1d", pin=PIN, max_age=1):
    return (
        f"    input: {{kind: feature, column: {column}, tf: {tf}, max_age_rows: {max_age}, "
        f"config_projection_hash: {pin}, coverage_floor: 0.8}}\n"
    )


def kernel_in(family=KERNEL, window=20, tf="1d", pin=PIN, max_age=1, gap=2):
    return (
        f"    input: {{kind: kernel, column: {family}_w{window}, tf: {tf}, "
        f"max_age_rows: {max_age}, config_projection_hash: {pin}, "
        f"windows: {{{family}: {window}}}, max_gap_rows: {gap}}}\n"
    )


def source_rows(inp_tf, column, *, max_age=1, smoothing=None, slot=1, book_bps=1, kernel=None):
    if kernel is None:
        bars = fi.column_memory_bars(column, CONFIG, REG)
    else:
        from src.intelligence.research.kernel_source import kernel_member_memory_bars

        bars = kernel_member_memory_bars(column, kernel, CONFIG)
    return feature_member_memory_rows(
        source_memory_bars=bars,
        source_bars_per_session=BPS_OF[inp_tf],
        max_age_rows=max_age,
        smoothing_half_life=smoothing,
        slot_history_sessions=slot,
        book_bars_per_session=book_bps,
    )


def member_text(name, input_yaml, rows, smoothing=None):
    out = (
        f"  - name: {name}\n    signal: {CENTRED}\n    params: {{sign: 1}}\n"
        f"    slot_history_sessions: 1\n    declared_memory_rows: {rows}\n{input_yaml}"
    )
    if smoothing is not None:
        out += f"    smoothing_half_life: {smoothing}\n"
    return out


def make_spec_text(members, *, tf="1d", bps=1, horizon=1):
    text = FAMILY.replace("family: fam_one", "family: features")
    text = text.replace("horizon: 2", f"horizon: {horizon}")
    text = text.replace("tf: 15m", f"tf: {tf}").replace(
        "bars_per_session: 26", f"bars_per_session: {bps}\n  fields: [closes_at]"
    )
    text = text.replace('"2006-07-01"', f'"{START}"').replace('"2025-12-24"', f'"{END}"')
    head, rest = text.split("members:\n", 1)
    tail = rest.split("construction:", 1)[1]
    return head + "members:\n" + "".join(members) + "construction:" + tail


def make_spec(members, **kw):
    return parse_spec_text(make_spec_text(members, **kw))


def feature_member(name="m1", *, tf="1d", column=FEATURE, smoothing=None, max_age=1, bps=1):
    rows = source_rows(tf, column, max_age=max_age, smoothing=smoothing, book_bps=bps)
    return member_text(name, feature_in(column, tf, max_age=max_age), rows, smoothing)


def kernel_member(name="k1", *, family=KERNEL, window=20, tf="1d", max_age=1):
    kernel = {family: window}
    col = f"{family}_w{window}"
    rows = source_rows(tf, col, max_age=max_age, kernel=kernel)
    return member_text(name, kernel_in(family, window, tf, max_age=max_age), rows)


def cert(**kw):
    base = BatteryCertificate("feature", None, None, "1d", "1d", 1, "equal_weight", 1, None, BIG)
    return dataclasses.replace(base, **kw)


@pytest.fixture
def certs(monkeypatch):
    def install(*items):
        monkeypatch.setattr(nbp, "PASSING_CERTIFICATES", tuple(items))

    return install


# --- memory -------------------------------------------------------------------------------


def test_memory_matching_declaration_proceeds(certs):
    certs(cert())
    spec = make_spec([feature_member()])
    runner_mod._check_spec(spec)
    runner_mod._check_member_memory(spec, CONFIGS)
    mem = runner_mod._member_memory(spec, spec.members[0], CONFIGS)
    assert mem.rows == spec.members[0].declared_memory_rows


def test_memory_mismatch_is_refused_naming_member_and_values(certs):
    certs(cert())
    spec = make_spec([feature_member()])
    want = spec.members[0].declared_memory_rows
    bad = spec.model_copy(
        update={"members": [spec.members[0].model_copy(update={"declared_memory_rows": want + 1})]}
    )
    with pytest.raises(RunRefused, match=rf"m1.*{want + 1}.*{want}"):
        runner_mod._check_member_memory(bad, CONFIGS)


def test_memory_uses_the_provenance_config(certs):
    certs(cert())
    spec = make_spec([feature_member()])
    other = dataclasses.replace(CONFIG, percentile_window_slow=CONFIG.percentile_window_slow + 10)
    mem = runner_mod._member_memory(spec, spec.members[0], {"1d": other})
    assert mem.rows == mem.sessions == spec.members[0].declared_memory_rows + 10
    with pytest.raises(RunRefused, match="m1"):
        runner_mod._check_member_memory(spec, {"1d": other})


def test_memory_smoothing_adds_its_sessions(certs):
    certs(cert(smoothing_half_life=21))
    plain = make_spec([feature_member()])
    smooth = make_spec([feature_member(smoothing=21)])
    a = runner_mod._member_memory(plain, plain.members[0], CONFIGS)
    b = runner_mod._member_memory(smooth, smooth.members[0], CONFIGS)
    assert b.sessions == a.sessions + smoothing_memory_sessions(21)
    runner_mod._check_member_memory(smooth, CONFIGS)


def test_memory_resid_bar_member_keeps_the_old_rule():
    spec = parse_spec_text(_spec_text())
    runner_mod._check_spec(spec)
    for m in spec.members:
        mem = runner_mod._member_memory(spec, m, None)
        assert (mem.rows, mem.sessions) == (m.declared_memory_rows, m.slot_history_sessions)
    bad = spec.model_copy(
        update={"members": [spec.members[0].model_copy(update={"declared_memory_rows": 1})]}
    )
    with pytest.raises(RunRefused, match="declared_memory_rows"):
        runner_mod._check_spec(bad)


# --- hmm / regime origin ------------------------------------------------------------------


def test_hmm_regime_column_passes_spec_load_and_s0_stops_the_run(certs, monkeypatch, tmp_path):
    column = next(c for c in REG.feature_columns() if REG.by_output(c).origin == "regime")
    certs(cert())
    # Every regime-origin column is path dependent today, so spec load would stop it on B1g
    # first; lift that rule to show origin alone is not refused at spec load (S0's B1j is).
    monkeypatch.setattr(fi, "refuse_path_dependent", lambda column, registry: None)
    spec = make_spec([member_text("h1", feature_in(column), 10)])
    runner_mod._check_spec(spec)

    async def build(dsn, out, sp):
        raise ValueError("B1j: a covering batch predates the 186-26 rebuild")

    def boom(*a, **k):
        raise AssertionError("a member was computed")

    monkeypatch.setattr(runner_mod, "compute_members", boom)
    ctx = RunContext(
        root=tmp_path,
        budget=runner_mod.BudgetConfig("v", 1, 0.05),
        build_snapshot=build,
    )
    with pytest.raises(ValueError, match="B1j"):
        asyncio.run(runner_mod._analysis_panel(spec, ctx, real=True, panel=None))


# --- unknown / path dependent -------------------------------------------------------------


@pytest.mark.parametrize("mode", ["real", "exploration", "synthetic"])
def test_unknown_column_is_refused_at_spec_load(mode):
    spec = make_spec([member_text("u", feature_in("no_such_column"), 10)])
    with pytest.raises(RunRefused, match="no_such_column"):
        runner_mod._check_spec(spec, mode=mode)


def test_unknown_kernel_is_refused_at_spec_load():
    spec = make_spec([member_text("u", kernel_in("rk_nonesuch", 20), 10)])
    with pytest.raises(RunRefused, match="rk_nonesuch"):
        runner_mod._check_spec(spec, mode="synthetic")


def test_path_dependent_stored_column_is_refused_at_spec_load():
    path_dependent = next(c for c in REG.feature_columns() if REG.is_path_dependent(c))
    spec = make_spec([member_text("p", feature_in(path_dependent), 10)])
    with pytest.raises(RunRefused, match="path dependent"):
        runner_mod._check_spec(spec, mode="synthetic")


def test_path_dependent_kernel_is_refused_at_spec_load(monkeypatch):
    from src.intelligence.features.contract.registry import KernelRegistry

    spec = make_spec([kernel_member()])
    monkeypatch.setattr(KernelRegistry, "is_path_dependent", lambda self, output: True)
    with pytest.raises(RunRefused, match="path dependent"):
        runner_mod._check_spec(spec, mode="synthetic")


def test_not_applicable_column_is_refused_per_tf():
    na = next(c for c in REG.feature_columns() if c in REG.not_applicable_outputs("1d"))
    spec = make_spec([member_text("n", feature_in(na), 10)])
    with pytest.raises(RunRefused, match="not applicable"):
        runner_mod._check_spec(spec, mode="synthetic")


# --- static gate --------------------------------------------------------------------------


def test_static_gate_admits_the_features_family():
    spec = make_spec([feature_member()])
    assert runner_mod.static_gate(spec).battery == nbp.__name__


# --- certificate --------------------------------------------------------------------------


@pytest.mark.parametrize("mode", ["real", "exploration"])
def test_certificate_present_admits_absent_refuses(certs, mode):
    spec = make_spec([feature_member(tf="1h")])
    certs(cert(source_tf="1h"))
    runner_mod._check_spec(spec, mode=mode)
    certs(cert(source_tf="15m"))
    with pytest.raises(RunRefused, match="source_tf"):
        runner_mod._check_spec(spec, mode=mode)
    certs()
    with pytest.raises(RunRefused, match="certificate"):
        runner_mod._check_spec(spec, mode=mode)
    runner_mod._check_spec(spec, mode="synthetic")


def test_certificate_smoothing_needs_its_own_cell(certs):
    spec = make_spec([feature_member(smoothing=5)])
    certs(cert())
    with pytest.raises(RunRefused, match="smoothing_half_life"):
        runner_mod._check_spec(spec)
    certs(cert(smoothing_half_life=5))
    runner_mod._check_spec(spec)


def test_certificate_kernel_window_must_match(certs):
    spec = make_spec([kernel_member(family="rk_high_dist", window=252)])
    kernel_cert = cert(identity="rk_high_dist", window=126, max_gap_rows=2)
    certs(kernel_cert)
    with pytest.raises(RunRefused, match="window"):
        runner_mod._check_spec(spec)
    certs(dataclasses.replace(kernel_cert, window=252))
    runner_mod._check_spec(spec)


def test_certificate_max_age_must_match(certs):
    certs(cert())
    spec = make_spec([feature_member(max_age=2)])
    with pytest.raises(RunRefused, match="max_age_rows"):
        runner_mod._check_spec(spec)


def test_certificate_memory_bound_is_checked_before_any_bar_fetch(certs):
    certs(cert(source_memory_bars_max=10))
    spec = make_spec([feature_member()])
    runner_mod._check_spec(spec)  # the memory test is deferred until the config is known
    with pytest.raises(RunRefused, match="source_memory_bars"):
        runner_mod._check_member_memory(spec, CONFIGS)


# --- supported subset ---------------------------------------------------------------------


def _subset_cases():
    one_h = make_spec([feature_member(tf="1d", bps=7)], tf="1h", bps=7)
    fifteen = make_spec([feature_member(tf="1d", bps=26)], tf="15m", bps=26)
    daily_h2 = make_spec([feature_member()], horizon=2)
    one_h_src = make_spec([feature_member(tf="1h", bps=7)], tf="1h", bps=7)
    return [one_h_src, fifteen, daily_h2]


@pytest.mark.parametrize("index", [0, 1, 2])
def test_subset_outside_is_refused_naming_the_review_row(certs, index):
    certs(cert(), cert(source_tf="1h", book_tf="1h"), cert(book_tf="15m"))
    spec = _subset_cases()[index]
    with pytest.raises(RunRefused, match="184-REVIEWS row 4"):
        runner_mod._check_spec(spec)
    runner_mod._check_spec(spec, mode="synthetic")


def test_subset_refuses_a_ridge_combiner_and_a_horizon_rule(certs):
    certs(cert())
    spec = make_spec([feature_member()])
    ridge = parse_spec_text(BOOK)
    with pytest.raises(RunRefused, match="184-REVIEWS row 4"):
        runner_mod._check_spec(spec, book=ridge)
    equal = BOOK.replace(
        "combiner: {window_sessions: 252, refit_sessions: 21, penalty: 1.0, min_obs: 10000}",
        'combiner: {kind: equal_weight, signs: {"features.m1": 1}}',
    )
    runner_mod._check_spec(spec, book=parse_spec_text(equal))
    ruled = equal.replace("guards:", "horizon_rule: {kappa: 0.5}\nguards:")
    with pytest.raises(RunRefused, match="184-REVIEWS row 4"):
        runner_mod._check_spec(spec, book=parse_spec_text(ruled))


# --- E17 L --------------------------------------------------------------------------------


@pytest.mark.parametrize(("tf", "bps"), [("1d", 1), ("1h", 7)])
def test_e17_l_is_timing_e17_memory_over_member_sessions(tf, bps):
    spec = make_spec([feature_member(tf="1d", bps=bps)], tf=tf, bps=bps)
    manifest = {"sources": {"1d": {"provenance": BLOCK}}}
    mems = runner_mod._member_memories(spec, manifest)
    mm = mems["m1"]
    rows_sessions = [
        feature_member_memory_sessions(
            source_memory_bars=fi.column_memory_bars(FEATURE, CONFIG, REG),
            source_bars_per_session=1,
            max_age_rows=1,
            smoothing_half_life=None,
            slot_history_sessions=1,
            book_bars_per_session=bps,
        )
    ]
    assert [mm.sessions] == rows_sessions
    book = book_memory([mm.sessions], [mm.rows], 1, EqualWeight((1.0,)), HorizonRule(), bps)
    assert book.member == e17_memory(mm.sessions, 1, bps)


# --- pins ---------------------------------------------------------------------------------


def test_two_pins_on_one_source_tf_are_refused():
    a = member_text("a", feature_in(pin=PIN), 10)
    b = member_text("b", feature_in(column="rsi_slow", pin=OTHER_PIN), 10)
    spec = make_spec([a, b])
    with pytest.raises(RunRefused, match="config_projection_hash"):
        runner_mod._check_spec(spec, mode="synthetic")


# --- S0 request ---------------------------------------------------------------------------


def test_high_low_kernel_on_the_book_tf_adds_high_low_to_the_fields():
    plain = make_spec([feature_member()])
    assert runner_mod._build_fields(plain) == ("closes_at",)
    spec = make_spec([kernel_member()])  # vwap_dev reads high and low
    assert runner_mod._build_fields(spec) == ("closes_at", "high", "low")
    dist = make_spec([kernel_member(family="rk_high_dist", window=126)])
    assert runner_mod._build_fields(dist) == ("closes_at",)
    on_hourly = make_spec([kernel_member(tf="1h")])  # the source is not the book's own tf
    assert runner_mod._build_fields(on_hourly) == ("closes_at",)


def test_build_request_orders_configs_then_build(monkeypatch, certs):
    certs(cert(), cert(identity=KERNEL, window=20, source_tf="1h", max_gap_rows=2))
    spec = make_spec([feature_member(), kernel_member(tf="1h")])
    calls = []

    async def symbols(dsn, dimension):
        return ["A", "B"]

    async def configs(dsn, sources, start, end, *, symbols):
        calls.append(("source_configs", [s.tf for s in sources], tuple(symbols)))
        return {s.tf: {"block": BLOCK, "config": CONFIG} for s in sources}

    async def build(dsn, out, **kwargs):
        calls.append(("build_panel", kwargs))
        return out

    monkeypatch.setattr(snapshot, "universe_symbols", symbols)
    monkeypatch.setattr(snapshot, "source_configs", configs)
    monkeypatch.setattr(snapshot, "build_panel", build)
    asyncio.run(runner_mod._default_build("dsn", "out", spec))
    assert [c[0] for c in calls] == ["source_configs", "build_panel"]
    kw = calls[1][1]
    assert "closes_at" in kw["fields"]
    want = warmup_prefix_sessions(
        [runner_mod._member_memory(spec, m, CONFIGS).sessions for m in spec.members]
    )
    assert kw["warmup_sessions"] == want > 0
    by_tf = {s.tf: s for s in kw["sources"]}
    assert set(by_tf) == {"1d", "1h"}
    assert by_tf["1d"].pinned_config_projection_hash == PIN
    f = by_tf["1d"].members[0]
    assert (f.member, f.kind, f.column, f.coverage_floor) == ("m1", "feature", FEATURE, 0.8)
    k = by_tf["1h"].members[0]
    assert (k.kind, k.windows, k.max_gap_rows) == ("kernel", {KERNEL: 20}, 2)
    assert by_tf["1h"].need_high_low is True  # vwap_dev reads high and low
    assert by_tf["1d"].need_high_low is False


def test_build_without_input_members_is_exactly_todays_call(monkeypatch):
    spec = parse_spec_text(_spec_text())
    seen = {}

    async def symbols(dsn, dimension):
        return ["A"]

    async def build(dsn, out, **kwargs):
        seen.update(kwargs)
        return out

    async def no_configs(*a, **k):
        raise AssertionError("source_configs called")

    monkeypatch.setattr(snapshot, "universe_symbols", symbols)
    monkeypatch.setattr(snapshot, "build_panel", build)
    monkeypatch.setattr(snapshot, "source_configs", no_configs)
    asyncio.run(runner_mod._default_build("dsn", "out", spec))
    assert "warmup_sessions" not in seen and "sources" not in seen
    assert seen["fields"] == ()


# --- snapshot match -----------------------------------------------------------------------


def _manifest(spec, *, sessions=None, fetch_start=None, pin=PIN, tfs=("1d",)):
    required = warmup_prefix_sessions(
        [runner_mod._member_memory(spec, m, CONFIGS).sessions for m in spec.members]
    )
    n = required if sessions is None else sessions
    scored = datetime(2010, 1, 4, tzinfo=UTC)
    fetch = fetch_start or snapshot.warmup_fetch_start(scored, "1d", n)
    return {
        "start": START,
        "end_exclusive": END,
        "universe": "compute_eligible",
        "sources": {
            tf: {
                "config_hash": pin,
                "provenance": {**BLOCK, "projection_hash": BLOCK["projection_hash"]},
            }
            for tf in tfs
        },
        "warmup_prefix": {
            "sessions": n,
            "fetch_start": fetch.isoformat(),
            "scored_start": scored.isoformat(),
        },
    }


def _load(monkeypatch, spec, manifest, *, closes=True):
    stub = SimpleNamespace(
        tf=spec.panel.tf,
        bars_per_session=spec.panel.bars_per_session,
        symbols=("A",),
        manifest=manifest,
        closes_at=np.zeros(1, dtype="datetime64[ns]") if closes else None,
    )
    monkeypatch.setattr(store, "verify", lambda path: "digest")
    monkeypatch.setattr(panel_mod, "load", lambda path: stub)
    monkeypatch.setattr(runner_mod.dividends, "load_grid", lambda path: None)
    monkeypatch.setattr(snapshot, "verify_sources", lambda path: {})
    monkeypatch.setattr(runner_mod, "_prepare_panel", lambda spec, source, **kw: (source, None))
    monkeypatch.setattr(runner_mod, "_attach_sources", lambda panel, sources: panel)
    ctx = RunContext(root=None, budget=None, snapshot="path")
    return asyncio.run(runner_mod._load_panel(spec, ctx))


def test_match_accepts_a_snapshot_built_for_the_spec(monkeypatch, certs):
    certs(cert())
    spec = make_spec([feature_member()])
    _load(monkeypatch, spec, _manifest(spec))


@pytest.mark.parametrize(
    "edit",
    [
        lambda m: m.update(sources={}),
        lambda m: m["sources"]["1d"].update(config_hash=OTHER_PIN),
        lambda m: m["sources"].update({"1h": dict(m["sources"]["1d"])}),
        lambda m: m.update(warmup_prefix=dict(m["warmup_prefix"], sessions=1)),
    ],
)
def test_match_refuses_a_snapshot_for_another_spec(monkeypatch, edit, certs):
    certs(cert())
    spec = make_spec([feature_member()])
    manifest = _manifest(spec)
    edit(manifest)
    with pytest.raises(ValueError, match="snapshot does not match the spec"):
        _load(monkeypatch, spec, manifest)


def test_match_refuses_missing_closes_at(monkeypatch, certs):
    certs(cert())
    spec = make_spec([feature_member()])
    with pytest.raises(ValueError, match="snapshot does not match the spec"):
        _load(monkeypatch, spec, _manifest(spec), closes=False)


def test_prefix_calendar_is_recomputed_not_trusted(monkeypatch, certs):
    certs(cert())
    spec = make_spec([feature_member()])
    required = _manifest(spec)["warmup_prefix"]["sessions"]
    assert required > 2
    short = snapshot.warmup_fetch_start(datetime(2010, 1, 4, tzinfo=UTC), "1d", 2)
    manifest = _manifest(spec, sessions=required, fetch_start=short)
    with pytest.raises(ValueError, match="snapshot does not match the spec"):
        _load(monkeypatch, spec, manifest)
    off_open = datetime(2009, 12, 12, 5, tzinfo=UTC)  # a Saturday
    manifest = _manifest(spec, sessions=required, fetch_start=off_open)
    with pytest.raises(ValueError, match="snapshot does not match the spec"):
        _load(monkeypatch, spec, manifest)


def test_a_snapshot_with_a_prefix_is_refused_for_a_spec_without_input_members(monkeypatch):
    spec = parse_spec_text(_spec_text())
    manifest = {
        "start": spec.panel.start,
        "end_exclusive": spec.panel.end_exclusive,
        "universe": "compute_eligible",
        "warmup_prefix": {"sessions": 3},
    }
    with pytest.raises(ValueError, match="snapshot does not match the spec"):
        _load(monkeypatch, spec, manifest)


def test_a_tampered_child_dir_fails_verify_sources(tmp_path):
    from tests.unit.research.test_runner_order import _panel

    child = panel_mod.save(_panel(m=3), tmp_path / "sources" / "1d")
    sha = store.verify(child)
    parent_panel = _panel(m=3)
    parent_panel = dataclasses.replace(
        parent_panel,
        manifest={"sources": {"1d": {"dir": str(child.relative_to(tmp_path)), "sha256": sha}}},
    )
    parent = panel_mod.save(parent_panel, tmp_path)
    assert list(snapshot.verify_sources(parent)) == ["1d"]
    victim = next(p for p in child.iterdir() if p.suffix == ".npy")
    victim.write_bytes(victim.read_bytes()[:-8] + b"\x00" * 8)
    with pytest.raises(ValueError):
        snapshot.verify_sources(parent)


# --- scored span --------------------------------------------------------------------------


def test_prefix_rows_are_never_traded():
    spec = make_spec([feature_member()])
    cfg = dataclasses.replace(spec.scoring.evaluation_config(), trading_start="2009-12-01")
    days = np.arange(np.datetime64("2009-12-01"), np.datetime64("2010-03-01"))
    days = days[(days.astype("datetime64[D]").astype(int) + 4) % 7 < 5]
    ts = days.astype("datetime64[ns]")
    base = dict(timestamps=ts, valid=np.ones(len(ts), dtype=bool))
    plain = SimpleNamespace(manifest={}, **base)
    prefixed = SimpleNamespace(
        manifest={"warmup_prefix": {"scored_start": "2010-01-04T00:00:00+00:00"}}, **base
    )
    free = runner_mod._trade(plain, cfg)
    masked = runner_mod._trade(prefixed, cfg)
    cut = np.datetime64("2010-01-04")
    assert not masked[ts < cut.astype("datetime64[ns]")].any()
    assert (masked == (free & (ts >= cut.astype("datetime64[ns]")))).all()
    assert masked.sum() == (ts >= cut.astype("datetime64[ns]")).sum()
    # the unprefixed run on the scored span trades the same sessions
    scored_only = SimpleNamespace(
        timestamps=ts[ts >= cut.astype("datetime64[ns]")],
        valid=np.ones(int((ts >= cut.astype("datetime64[ns]")).sum()), dtype=bool),
        manifest={},
    )
    assert set(ts[masked]) == set(scored_only.timestamps[runner_mod._trade(scored_only, cfg)])


def test_bars_per_session_table_matches_the_battery():
    assert runner_mod._BARS_PER_SESSION == nbp._SOURCE_BARS


def test_input_members_outside_the_first_family_are_refused(certs):
    certs(cert())
    first = SimpleNamespace(model=parse_spec_text(_spec_text()))
    later = SimpleNamespace(model=make_spec([feature_member()]))
    loaded = SimpleNamespace(
        families=[first, later], model=parse_spec_text(BOOK), path="p", blob_sha=None
    )
    with pytest.raises(RunRefused, match="first family"):
        runner_mod._check_spec_tree(loaded, "real")


# --- todo 588 part A ----------------------------------------------------------------------


def _with_signal(member_yaml, signal):
    return member_yaml.replace(CENTRED, signal)


def test_b2_an_input_member_must_use_the_certified_function(certs):
    certs(cert())
    other = "src.intelligence.research.families.intraday_periodicity.same_slot_mean"
    spec = make_spec([_with_signal(feature_member(), other)])
    with pytest.raises(RunRefused, match=r"families\.features\.centred"):
        runner_mod._check_spec(spec)
    runner_mod._check_spec(spec, mode="synthetic")  # the battery itself runs open
    runner_mod._check_spec(make_spec([feature_member()]))


def test_m3_two_input_members_on_one_route_are_refused(certs):
    certs(cert())
    spec = make_spec([feature_member("a"), feature_member("b")])
    with pytest.raises(RunRefused, match="certified composition"):
        runner_mod._check_spec(spec)
    runner_mod._check_spec(spec, mode="synthetic")


def _two_routes(monkeypatch, *, certified=True, passing=2, third=False):
    """A 1d feature route and a 1h feature route on a 1d book; the pair is a certified
    composition when `certified`."""
    a, b = cert(), cert(source_tf="1h")
    monkeypatch.setattr(nbp, "PASSING_CERTIFICATES", (a, b)[:passing])
    monkeypatch.setattr(nbp, "CERTIFIED_BOOKS", (frozenset({a, b}),) if certified else ())
    members = [feature_member("a"), feature_member("b", tf="1h")]
    if third:
        members.append(feature_member("c", tf="1h"))
    return make_spec(members)


def test_part_b_a_certified_two_member_composition_is_admitted(monkeypatch):
    spec = _two_routes(monkeypatch)
    runner_mod._check_spec(spec)
    runner_mod._check_member_memory(spec, CONFIGS)


def test_part_b_an_uncertified_composition_is_refused(monkeypatch):
    spec = _two_routes(monkeypatch, certified=False)
    with pytest.raises(RunRefused, match="certified composition"):
        runner_mod._check_spec(spec)


def test_part_b_a_composition_needs_every_route_passing(monkeypatch):
    spec = _two_routes(monkeypatch, passing=1)
    with pytest.raises(RunRefused, match="no battery certificate covers"):
        runner_mod._check_spec(spec)


def test_part_b_a_composition_is_exactly_its_members(monkeypatch):
    spec = _two_routes(monkeypatch, third=True)
    with pytest.raises(RunRefused, match="certified composition"):
        runner_mod._check_spec(spec)


def test_part_b_static_gate_of_a_composition_is_the_weakest_route(monkeypatch):
    spec = _two_routes(monkeypatch)
    spec = spec.model_copy(update={"family": "features"})
    gate = runner_mod.static_gate(spec)
    assert gate.static_sd == (0.0,) and gate.time_of_day == (0.0,)


def _residual_member(spec):
    from src.intelligence.research.families.common import declared_memory_rows

    FACTOR_SPECS = runner_mod.FACTOR_SPECS
    want = declared_memory_rows(
        1, spec.panel.analysis_bars_per_session, FACTOR_SPECS[spec.factor_spec]
    )
    return spec.members[0].model_copy(
        update={
            "name": "r1",
            "input": None,
            "params": {},
            "signal": "src.intelligence.research.families.intraday_periodicity.same_slot_mean",
            "declared_memory_rows": want,
        }
    )


def test_m3_input_and_residual_members_do_not_mix(certs):
    certs(cert())
    spec = make_spec([feature_member()])
    mixed = spec.model_copy(update={"members": [*spec.members, _residual_member(spec)]})
    with pytest.raises(RunRefused, match="mixing input members and residual"):
        runner_mod._check_spec(mixed)
    runner_mod._check_spec(mixed, mode="synthetic")


def test_m3_the_book_wide_check_spans_families(certs):
    certs(cert())
    inp = make_spec([feature_member()])
    plain = inp.model_copy(update={"members": [_residual_member(inp)]})
    runner_mod._check_input_mix([inp])
    runner_mod._check_input_mix([plain])
    with pytest.raises(RunRefused, match="mixing input members and residual"):
        runner_mod._check_input_mix([inp, plain])
    with pytest.raises(RunRefused, match="more than one family"):
        runner_mod._check_input_mix([inp, inp])


def test_item8_slot_history_zero_is_allowed_for_an_input_member_only(certs):
    certs(cert())
    rows = source_rows("1d", FEATURE, slot=0)
    zero = member_text("m1", feature_in(), rows).replace(
        "slot_history_sessions: 1", "slot_history_sessions: 0"
    )
    spec = make_spec([zero])
    assert spec.members[0].slot_history_sessions == 0
    runner_mod._check_spec(spec)
    runner_mod._check_member_memory(spec, CONFIGS)
    residual = _spec_text().replace("slot_history_sessions: 1", "slot_history_sessions: 0", 1)
    with pytest.raises(ValueError, match="slot_history_sessions must be at least 1"):
        parse_spec_text(residual)


def test_b1_the_static_gate_is_the_members_certificate_only(certs, monkeypatch):
    spec = make_spec([feature_member()])
    seen = []
    monkeypatch.setattr(
        nbp, "static_gate", lambda certificates=None: seen.append(certificates) or "gate"
    )
    certs(cert())
    assert runner_mod.static_gate(spec) == "gate"
    assert seen == [[cert()]]
    certs()  # an uncovered member adds no certificate; admission refuses it with a reason
    runner_mod.static_gate(spec)
    assert seen[-1] == []


def test_b1_the_real_gate_is_the_ceiling_the_certificates_own_cells_held(certs):
    """End to end on the real battery (todo 588 part B): a route is gated at the largest stress
    its own passing cells held, so a measured size above it is refused."""
    spec = make_spec([feature_member(tf="1h", bps=1)])
    real = nbp.PASSING_CERTIFICATES[0]
    certs(real)
    gate = runner_mod.static_gate(spec)
    assert gate.static_sd == (pytest.approx(2 * MEASURED_STATIC_CELL_SD),)
    assert gate.time_of_day == (pytest.approx(2 * MEASURED_SLOT_EFFECT_SD),)
    unstressed = nbp.static_gate([dataclasses.replace(real, window=7)])
    assert unstressed.static_sd == (0.0,) and unstressed.time_of_day == (0.0,)


def test_m2_unmatched_rows_inside_the_scored_span_refuse():
    ts = np.array(["2010-01-04", "2010-01-05", "2010-01-06"], dtype="datetime64[ns]")
    grid = SimpleNamespace(timestamps=ts)
    scored_lo = datetime(2010, 1, 5, tzinfo=UTC)
    scored = np.array([False, True, True])

    def row(day, v=1.0):
        return ("A", datetime.fromisoformat(f"{day}T00:00:00+00:00"), v)

    def call(rows):
        return snapshot._feature_rows_to_grid(
            rows, grid, ["A"], [FEATURE], REG, CONFIG, scored, scored_lo
        )

    call([row("2010-01-05")])  # all matched
    call([row("2010-01-05"), row("2009-12-31")])  # unmatched warmup row: counted, not refused
    with pytest.raises(ValueError, match="inside the scored span"):
        call([row("2010-01-05"), row("2010-01-07")])  # off-grid inside the span
    with pytest.raises(ValueError, match="inside the scored span"):
        call([row("2010-01-05"), ("ZZ", datetime(2010, 1, 6, tzinfo=UTC), 1.0)])  # unknown name


def _run_features_family(repo, ctx):
    from src.intelligence.research.spec import load_spec_from_head

    loaded = load_spec_from_head(repo, "research/specs/f.yaml")
    return asyncio.run(runner_mod.run_family(loaded, ctx, mode="real"))


def test_m1_a_memory_refusal_opens_no_research_run(certs, monkeypatch, tmp_path):
    """The provenance config disagrees with the declared memory: refused before start_runs, so
    no spec hash is burned."""
    import subprocess

    from tests.unit.research.test_runner_order import FakeLedger

    certs(cert())
    repo = tmp_path
    for args in (
        ("init", "-q"),
        ("config", "user.email", "t@example.com"),
        ("config", "user.name", "t"),
    ):
        subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)
    (repo / "research/specs").mkdir(parents=True)
    text = make_spec_text([feature_member()]).replace(
        "  session_scoring: true\n", "  session_scoring: true\n  timing_statistic: e17\n", 1
    )
    (repo / "research/specs/f.yaml").write_text(text)
    subprocess.run(["git", "-C", str(repo), "add", "."], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-q", "-m", "i"], check=True)

    other = dataclasses.replace(CONFIG, percentile_window_slow=CONFIG.percentile_window_slow + 10)

    async def symbols(dsn, dimension):
        return ["A"]

    async def configs(dsn, sources, start, end, *, symbols):
        return {s.tf: {"block": BLOCK, "config": other} for s in sources}

    async def never_built(*a, **k):
        raise AssertionError("a snapshot was built")

    monkeypatch.setattr(snapshot, "universe_symbols", symbols)
    monkeypatch.setattr(snapshot, "source_configs", configs)
    monkeypatch.setattr(snapshot, "build_panel", never_built)
    ledger = FakeLedger()
    ctx = RunContext(
        root=repo,
        budget=runner_mod.BudgetConfig("v", 1, 0.05),
        ledger=ledger,
        dsn="dsn",
        snapshot_dir=tmp_path,
    )
    with pytest.raises(RunRefused, match="declared_memory_rows"):
        _run_features_family(repo, ctx)
    assert "start_runs" not in ledger.calls
    assert not any(isinstance(c, tuple) for c in ledger.calls)  # no finish_run either


def test_m1_preflight_reads_a_handed_snapshots_manifest(certs, monkeypatch):
    certs(cert())
    spec = make_spec([feature_member()])
    other = {"sources": {"1d": {"provenance": {**BLOCK}}}}
    ctx = RunContext(root=None, budget=None, snapshot="path")
    monkeypatch.setattr(store, "read_meta", lambda path: {"manifest": other})
    asyncio.run(runner_mod.preflight_member_memory(spec, ctx))  # matching memory: proceeds
    bad = spec.model_copy(
        update={
            "members": [
                spec.members[0].model_copy(
                    update={"declared_memory_rows": spec.members[0].declared_memory_rows + 1}
                )
            ]
        }
    )
    with pytest.raises(RunRefused, match="declared_memory_rows"):
        asyncio.run(runner_mod.preflight_member_memory(bad, ctx))
