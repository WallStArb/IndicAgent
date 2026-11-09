"""The corpus rerun step runner (186-31): the DAG, its refusals, the pin gate, the pilot, the
span and completeness checks, adoption and the caveat. An in-memory store stands in for
corpus_run / corpus_run_step / provenance_batch and every effect is a fake; the data gate's
one-transaction persistence runs against the real schema in
tests/integration/test_corpus_rerun_store.py."""

from __future__ import annotations

import dataclasses
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

import services.corpus_rerun as cr
from services.corpus_rerun_apr import CorpusRerunApr
from services.corpus_rerun_budget import RowCounts

RUN = "1b4e28ba-2fa1-11d2-883f-0016d3cca427"
OTHER = "6fa459ea-ee8a-3ca4-894e-db77e160355e"
COMMIT = "a" * 40
CODE_KEY = "c" * 64
APR_HASH = "d" * 64
WORKTREE = Path("/srv/indicagent-corpus-run")
TIMERS = ("indicagent-ibkr-history-fetcher.timer", "indicagent-alpaca-nightly.timer")


def _jan1(year: int) -> datetime:
    return datetime(year, 1, 1, tzinfo=UTC)


SPANS = ((_jan1(2010), _jan1(2013)), (_jan1(2013), _jan1(2016)))
CAVEAT = {"code": "survivorship_pre2016_ibkr_5m", "text": "biased", "counts": {"names": 3}}


def _counts() -> list[list[Any]]:
    """100 1h, 400 15m and 1,000 5m rows a month 2010-2015 and 10 1d rows a month, one
    symbol chunk."""
    cells = {}
    for year in range(2010, 2016):
        for month in range(1, 13):
            cells[("1h", 0, date(year, month, 1))] = 100
            cells[("15m", 0, date(year, month, 1))] = 400
            cells[("5m", 0, date(year, month, 1))] = 1000
            cells[("1d", 0, date(year, month, 1))] = 10
    return cr.counts_record(RowCounts(cells))


APR = CorpusRerunApr(
    max_disk_fraction=0.7,
    disk_reserve_bytes=50 * 10**9,
    bytes_per_row_uncompressed=1379,
    compression_ratio=6.0,
    stored_bytes_per_spool_byte=0.37,
    max_missing_session_fraction=0.01,
    max_missing_1d_session_fraction=0.01,
    min_session_bar_fraction=0.9,
    blocking_timers=TIMERS,
    max_null_fraction=0.05,
)


def _run(**overrides) -> cr.CorpusRun:
    values = {
        "run_id": RUN,
        "code_commit": COMMIT,
        "code_key": CODE_KEY,
        "horizon": datetime(2026, 11, 1, tzinfo=UTC),
        "apr_hash": APR_HASH,
        "spans": SPANS,
        "free_bytes_at_launch": 700 * 10**9,
        "caveats": (),
        "measured": {"row_counts": _counts()},
    }
    values.update(overrides)
    return cr.CorpusRun(**values)


class FakeStore:
    """corpus_run, corpus_run_step and the provenance rows the runner reads, in memory."""

    def __init__(self, run: cr.CorpusRun):
        self.run = run
        self.steps: dict[str, cr.StepRow] = {}
        self.data_gate: dict | None = None
        self.provenance: dict[str, str | None] = {}  # completed batch_key -> run_id
        self.units: dict[str, list[tuple[str, str | None]]] = {}
        self.open: list[tuple[str, str]] = []
        self.uncompressed: list[tuple[str, datetime]] = []
        self.reaching = (0, None)
        self.writes: list[str] = []
        self.loaded: dict[tuple, int] = {}  # (tf, lo, hi) -> rows this run loaded
        # batch_key -> (tf, unit_stats); a key without an entry carries a healthy count
        self.stats: dict[str, tuple[str, dict | None]] = {}
        self.lookaheads: dict[str, dict[int, int]] = {"1h": {1: 9}, "1d": {1: 9}}

    def step(self, run_id, name):
        return self.steps.get(name)

    def begin(self, run_id, name):
        self.writes.append(f"begin {name}")
        self.steps[name] = cr.StepRow("started", {})

    def finish(self, run_id, name, status, summary):
        self.writes.append(f"{status} {name}")
        self.steps[name] = cr.StepRow(status, cr._json(summary))

    def complete_data_gate(self, run_id, name, record, caveat, summary):
        self.data_gate = record
        if not any(c.get("code") == caveat["code"] for c in self.run.caveats):
            self.run = dataclasses.replace(self.run, caveats=(*self.run.caveats, dict(caveat)))
        self.finish(run_id, name, "completed", summary)

    def merge_measured(self, run_id, patch):
        self.run = dataclasses.replace(self.run, measured={**self.run.measured, **cr._json(patch)})

    def load_run(self, run_id):
        return self.run

    def completed_rows(self, keys):
        return {k: self.provenance[k] for k in keys if k in self.provenance}

    def unit_completed(self, unit_key):
        return self.units.get(unit_key, [])

    def open_rows(self, run_id):
        return self.open

    def adoptions(self, run_id):
        return {
            a["batch_key"]: a["adopted_from_run_id"]
            for row in self.steps.values()
            if row.status == "completed"
            for a in row.summary.get("adopted", [])
        }

    def completed_summaries(self, run_id):
        return {n: r.summary for n, r in self.steps.items() if r.status == "completed"}

    def uncompressed_chunks(self, before):
        return [c for c in self.uncompressed if c[1] <= before]

    def rows_reaching(self, oos_start):
        return self.reaching

    def unit_stats(self, keys):
        """A key with a test-set entry carries it; otherwise each key is one healthy unit on
        every target tf (so every expected tf has present rows)."""
        healthy = {"swing_high_dist_atr": {"present": 100, "nan_present": 1}}
        rows = []
        for k in keys:
            if k in self.stats:
                rows.append((k, *self.stats[k]))
            else:
                rows += [(k, tf, healthy) for tf in ("5m", "15m", "1h", "1d")]
        return rows

    def loaded_rows(self, run_id, tf, lo, hi):
        return self.loaded.get((tf, lo, hi), 0)

    def pooled_lookaheads(self):
        return self.lookaheads


def _stage_summary(keys, *, failed=0, adopted=(), bpr=1379.0, sps=0.37, rows=100, blind=()):
    return {
        "units_total": len(keys),
        "units_failed": failed,
        "units_abandoned": 0,
        "disk_refused": None,
        "scope_batch_keys": list(keys),
        "adopted": [dict(a) for a in adopted],
        "bytes_per_row_max": bpr,
        "stored_per_spool_max": sps,
        "rows_loaded": rows,
        "digest_blind_symbols": list(blind),
    }


class FakeRebuild:
    """run_rebuild_stage stand-in: each call returns a summary for a fresh unit, completed under
    the run in the store, unless the test queues its own summaries."""

    def __init__(self, store: FakeStore):
        self.store = store
        self.calls: list[dict] = []
        self.queued: list[dict] = []

    def __call__(self, **kwargs):
        self.calls.append(kwargs)
        if self.queued:
            return self.queued.pop(0)
        key = f"{len(self.calls):064x}"
        self.store.provenance[key] = kwargs["run_id"]
        return _stage_summary([key])


def _result(ok=True, caveat=CAVEAT):
    record = {"ok": ok, "names_checked": 3, "failing_name_years": [] if ok else [["X", 2010]]}
    return SimpleNamespace(ok=ok, caveat=caveat if ok else None, as_record=lambda: record)


@dataclasses.dataclass
class World:
    runner: cr.CorpusRerun
    store: FakeStore
    rebuild: FakeRebuild
    commands: list
    state: dict


def _world(run: cr.CorpusRun | None = None, **state_overrides) -> World:
    store = FakeStore(run or _run())
    rebuild = FakeRebuild(store)
    commands: list = []
    state = {
        "toplevel": WORKTREE,
        "head": COMMIT,
        "code_key": CODE_KEY,
        "apr_hash": APR_HASH,
        "module_files": [str(WORKTREE / "services/__init__.py")],
        "lock_free": True,
        "enabled": "disabled",
        "active": "inactive",
        "free": 700 * 10**9,
        "gate": _result(),
        "returncodes": {},
        "planned": ([], set()),
        "compression": {"1d": 5.0, "1h": 7.0},
        "wal": 16 * 10**9,
        "report": {"outcomes": []},
    }
    state.update(state_overrides)

    def run_command(argv, cwd):
        commands.append((list(argv), cwd))
        name = next((a for a in argv if a.endswith(".py") or a.startswith("services.")), argv[0])
        return state["returncodes"].get(Path(name).name, 0), f"ran {name}"

    deps = cr.Deps(
        settings=SimpleNamespace(),
        conn=object(),
        python="/venv/bin/python",
        worktree=WORKTREE,
        spool_root=Path("/main/logs/rebuild_spool"),
        run_data_gate=lambda conn, settings, apr, horizon: state["gate"],
        run_stage=rebuild,
        planned_units=lambda settings, conn, horizon: state["planned"],
        symbol_chunks=lambda: [("AAA", "BBB")],
        run_command=run_command,
        git_head=lambda path: state["head"],
        toplevel=lambda: state["toplevel"],
        identity=lambda: {"code_key": state["code_key"], "apr_hash": state["apr_hash"]},
        module_files=lambda: state["module_files"],
        fetcher_lock_free=lambda: state["lock_free"],
        systemctl=lambda verb, unit: state["enabled"] if verb == "is-enabled" else state["active"],
        no_live_run=lambda: SimpleNamespace(name="no_live_run", ok=True, detail="quiet"),
        preconditions=lambda intraday, disk: [
            SimpleNamespace(name="disk_guard", ok=True, detail="ok")
        ],
        free_bytes=lambda: state["free"],
        wal_bytes=lambda: state["wal"],
        chunk_interval=lambda: timedelta(days=360),
        db_load=lambda: {"other_active": 1, "xact_commit": 10, "blks_read": 5},
        measure_compression=lambda symbols, tf: {
            "rows": 10,
            "ratio": state["compression"][tf],
        },
        read_json=lambda path: state["report"],
        object_columns=frozenset({"swing_high_dist_atr"}),
        applicable=lambda tf: frozenset({"swing_high_dist_atr", "adx"}),
        apr_value=lambda key: {
            "infra.feature_factory.workers": 4,
            "feature.factory.target_timeframes": '["5m", "15m", "1h", "1d"]',
            "alpha.ic_measure.horizons": {"1h": [1], "1d": [1]},
            "alpha.validation.oos_start": "2025-12-24T05:15:00Z",
        }[key],
    )
    return World(cr.CorpusRerun(store.run, store, deps, APR), store, rebuild, commands, state)


def _complete(world: World, *names: str, **summary) -> None:
    for name in names:
        world.store.steps[name] = cr.StepRow("completed", dict(summary))


def _through(world: World, name: str) -> None:
    """Complete every step before `name` by hand."""
    for step in world.runner.steps:
        if step.name == name:
            return
        _complete(world, step.name)


# ---------------------------------------------------------------------------
# The DAG and its refusals
# ---------------------------------------------------------------------------


def test_the_order_is_fixed_and_span_major():
    names = [s.name for s in cr.build_steps(SPANS)]
    assert names == [
        "data_gate", "pin_gate", "pilot", "stage_1d",
        "s1.1h", "s1.15m", "s1.5m", "s2.1h", "s2.15m", "s2.5m",
        "feature_complete", "ic_measure", "d19_bound", "canary",
    ]  # fmt: skip
    steps = cr.build_steps(SPANS)
    assert all(b.upstream == a.name for a, b in zip(steps, steps[1:]))
    assert steps[0].upstream is None


def test_a_step_without_its_upstream_row_is_refused_before_any_write():
    world = _world()
    with pytest.raises(cr.StepRefused, match="upstream step data_gate has not run"):
        world.runner.execute("pin_gate")
    assert world.store.writes == []


def test_a_step_whose_upstream_failed_is_refused_before_any_write():
    world = _world()
    world.store.steps["data_gate"] = cr.StepRow("failed", {})
    with pytest.raises(cr.StepRefused, match="data_gate is failed"):
        world.runner.execute("pin_gate")
    assert world.store.writes == []


def test_there_is_no_skip_flag():
    with pytest.raises(SystemExit):
        cr._parse_args(["--run-id", RUN, "--through", "canary", "--from-step", "pilot"])
    with pytest.raises(SystemExit):
        cr._parse_args(["--run-id", RUN])  # a run id needs --step or --through


def test_a_completed_step_reinvoked_is_a_no_op_reporting_its_outcome():
    world = _world()
    world.store.steps["data_gate"] = cr.StepRow("completed", {"ok": True, "names_checked": 3})
    assert world.runner.execute("data_gate") == {"ok": True, "names_checked": 3}
    assert world.store.writes == []


def test_through_stops_at_the_first_failure():
    world = _world(gate=_result(ok=False))
    with pytest.raises(cr.StepFailed):
        world.runner.through("canary")
    assert set(world.store.steps) == {"data_gate"}


# ---------------------------------------------------------------------------
# data_gate
# ---------------------------------------------------------------------------


def test_a_passing_data_gate_records_the_result_and_the_caveat_once():
    world = _world()
    world.runner.execute("data_gate")
    assert world.store.data_gate["ok"] is True
    assert [c["code"] for c in world.store.run.caveats] == [CAVEAT["code"]]
    # the step failed later and is retried: the caveat is not appended twice
    world.store.steps["data_gate"] = cr.StepRow("failed", {})
    world.runner.execute("data_gate")
    assert [c["code"] for c in world.store.run.caveats] == [CAVEAT["code"]]
    assert world.store.steps["data_gate"].status == "completed"


def test_a_refused_data_gate_writes_its_counts_to_the_step_and_no_caveat():
    world = _world(gate=_result(ok=False))
    with pytest.raises(cr.StepFailed, match="refused"):
        world.runner.execute("data_gate")
    row = world.store.steps["data_gate"]
    assert row.status == "failed" and row.summary["failing_name_years"] == [["X", 2010]]
    assert world.store.run.caveats == () and world.store.data_gate is None


def test_a_passing_data_gate_without_a_caveat_fails():
    world = _world(gate=SimpleNamespace(ok=True, caveat=None, as_record=lambda: {"ok": True}))
    with pytest.raises(cr.StepFailed, match="no survivorship caveat"):
        world.runner.execute("data_gate")
    assert world.store.run.caveats == ()


# ---------------------------------------------------------------------------
# pin_gate
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "override, failing",
    [
        ({"head": "b" * 40}, "head"),
        ({"code_key": "e" * 64}, "code_key"),
        ({"apr_hash": "f" * 64}, "apr_hash"),
        ({"toplevel": Path("/home/bg/dev/indicagent")}, "worktree"),
        ({"module_files": ["/home/bg/dev/indicagent/services/__init__.py"]}, "imports"),
        ({"lock_free": False}, "fetcher_lock"),
        ({"enabled": "enabled"}, f"timer:{TIMERS[0]}"),
        ({"active": "active"}, f"timer:{TIMERS[0]}"),
        ({"enabled": ""}, f"timer:{TIMERS[0]}"),  # an unknown unit is not proof it is off
    ],
)
def test_the_pin_gate_refuses(override, failing):
    world = _world(**override)
    _complete(world, "data_gate")
    with pytest.raises(cr.StepFailed, match=failing):
        world.runner.execute("pin_gate")
    checks = {c["name"]: c["ok"] for c in world.store.steps["pin_gate"].summary["pin_checks"]}
    assert checks[failing] is False
    assert world.rebuild.calls == []


def test_the_pin_gate_passes_and_records_every_check():
    world = _world()
    _complete(world, "data_gate")
    summary = world.runner.execute("pin_gate")
    names = {c["name"] for c in summary["pin_checks"]}
    assert {"worktree", "head", "code_key", "imports", "fetcher_lock", "fraction_limit"} <= names
    assert {f"timer:{t}" for t in TIMERS} <= names and "disk_guard" in names


def test_the_pin_gate_refuses_growth_that_leaves_no_room_for_the_next_step():
    world = _world(free=200 * 10**9)  # 500 GB grown of a 490 GB limit
    _complete(world, "data_gate")
    with pytest.raises(cr.StepFailed, match="fraction_limit"):
        world.runner.execute("pin_gate")


def test_every_compute_step_repeats_the_pin_checks():
    world = _world()
    _through(world, "s1.1h")
    world.state["lock_free"] = False
    with pytest.raises(cr.StepFailed, match="fetcher_lock"):
        world.runner.execute("s1.1h")
    assert world.rebuild.calls == []


# ---------------------------------------------------------------------------
# pilot
# ---------------------------------------------------------------------------


def test_the_pilot_runs_chunk_0_of_stage_1d_and_one_1h_unit_of_span_1_and_measures():
    world = _world()
    _through(world, "pilot")
    summary = world.runner.execute("pilot")
    daily, hourly = world.rebuild.calls
    assert daily["timeframes"] == ["1d"] and daily["chunk_indices"] == [0]
    assert hourly["timeframes"] == ["1h"] and hourly["chunk_indices"] == [0]
    assert hourly["span"] == (_jan1(2010), _jan1(2011))
    assert all(c["symbols"] is None and c["run_id"] == RUN for c in world.rebuild.calls)
    assert all(c["spool_root"] == Path("/main/logs/rebuild_spool") for c in world.rebuild.calls)
    gates = [argv for argv, _ in world.commands]
    assert any("ops_feature_column_screen.py" in a for argv in gates for a in argv)
    pilot_screen = next(argv for argv in gates if "ops_feature_column_screen.py" in argv[1])
    assert "--null-gate" in pilot_screen  # G6 fails in the pilot hour, not after days
    assert any("AAA:1h" in argv for argv in gates)
    measured = world.store.run.measured
    assert measured["pilot_bytes_per_row_intraday"] == 1379.0 and "pilot_db_load" in measured
    assert summary["reprojection"]


def test_the_pilot_fails_before_stage_1d_when_measured_intraday_bytes_overflow_a_span():
    world = _world()
    _through(world, "pilot")
    original = world.rebuild.__call__

    def heavy(**kwargs):
        summary = original(**kwargs)
        if kwargs["timeframes"] == ["1h"]:
            # 36,000 rows in a 3-year span at 20 MB a row: 720 GB, past the 490 GB limit
            summary["bytes_per_row_max"] = 2e7
        return summary

    world.runner.deps.run_stage = heavy
    with pytest.raises(cr.StepFailed, match="overflow the run's spans"):
        world.runner.execute("pilot")
    assert len(world.rebuild.calls) == 2  # chunk 0 of 1d and the 1h unit, nothing more
    with pytest.raises(cr.StepRefused, match="pilot is failed"):
        world.runner.execute("stage_1d")
    assert len(world.rebuild.calls) == 2


def _heavy_pilot(world: World) -> None:
    """Pilot units measuring 5.27 MB a row (spool ratio large enough that spools are noise): the
    run's spans fit at a 6x compression ratio and overflow uncompressed."""
    original = world.rebuild.__call__

    def heavy(**kwargs):
        summary = original(**kwargs)
        summary["bytes_per_row_max"] = 5.27e6
        summary["stored_per_spool_max"] = 1e9
        return summary

    world.runner.deps.run_stage = heavy


def test_the_pilot_measures_the_compression_ratio_and_reprojects_with_it():
    world = _world()
    _through(world, "pilot")
    _heavy_pilot(world)
    summary = world.runner.execute("pilot")
    measured = world.store.run.measured
    assert measured["compression_ratio_measured"] == 5.0  # the smaller of 1d and 1h
    assert measured["pilot_compression"]["1h"]["ratio"] == 7.0
    assert summary["reprojection"]
    assert world.runner._inputs().compression_ratio == 5.0  # every later projection uses it


def test_the_pilot_refuses_before_stage_1d_when_the_measured_ratio_overflows_a_span():
    world = _world(compression={"1d": 1.0, "1h": 1.0})
    _through(world, "pilot")
    _heavy_pilot(world)
    with pytest.raises(cr.StepFailed, match="compression ratio overflow"):
        world.runner.execute("pilot")
    with pytest.raises(cr.StepRefused, match="pilot is failed"):
        world.runner.execute("stage_1d")


def test_every_step_of_a_two_span_plan_passes_its_disk_gate_at_the_plans_own_numbers():
    """Plan the spans, then walk every compute step with the growth since launch set to the
    footprint the plan models for that step's start: the fraction gate passes everywhere."""
    from services.corpus_rerun_budget import footprint_before, plan_spans, project, split_years

    probe = _world(wal=0)
    counts = probe.runner._counts()
    inputs = probe.runner._inputs()
    # the limit sits exactly at the two-span plan's own largest peak: no slack to hide a
    # double count
    two = project(split_years(counts, 2), counts, inputs)
    launch = int(max(p.total for p in two) / 0.7) + 1
    plan = plan_spans(counts, dataclasses.replace(inputs, free_bytes_at_launch=launch))
    assert len(plan.spans) == 2
    world = _world(run=_run(spans=tuple(plan.spans), free_bytes_at_launch=launch), wal=0)
    budget_inputs = world.runner._inputs()
    for step in world.runner.steps:
        if step.kind not in ("stage_1d", "span"):
            continue
        tf = step.tf if step.kind == "span" else "1d"
        growth = footprint_before(plan.spans, step.span_index, tf, counts, budget_inputs)
        world.state["free"] = launch - int(growth)
        checks = {c["name"]: c for c in world.runner.pin_checks(step)}
        assert checks["fraction_limit"]["ok"], (step.name, checks["fraction_limit"]["detail"])


def test_a_resumed_step_does_not_count_its_loaded_rows_as_growth_again():
    world = _world()
    step = world.runner.by_name["s1.5m"]
    inputs = world.runner._inputs()
    full = world.runner._increment(step, inputs)
    world.store.loaded[("5m", *SPANS[0])] = 18_000  # half of span 1's 5m rows
    assert world.runner._increment(step, inputs) == pytest.approx(full - 18_000 * 1379)


def test_feature_complete_runs_the_null_share_gate_per_tf():
    world = _world(planned=(_specs("k1"), set()))
    _through(world, "feature_complete")
    world.store.provenance["k1"] = RUN
    world.runner.execute("feature_complete")
    screens = [argv for argv, _ in world.commands if "ops_feature_column_screen.py" in argv[1]]
    assert len(screens) == 4 and all("--null-gate" in argv for argv in screens)


def test_the_pinned_apr_keys_come_from_every_gate():
    keys = set(cr.pinned_apr_keys(["1h", "1d"]))
    assert {
        "threshold.pilot_gate.warmup_gap_bars",
        "threshold.pilot_gate.zero_share_max",
        "infra.pilot_gate.names",
        "infra.corpus_rerun.max_null_fraction",
        "infra.corpus_rerun.blocking_timers",
        "infra.hmm.rolling_block_rows",
        "threshold.bar_integrity.report_max_age_hours",
        "feature.factory.target_timeframes",
        "infra.feature_factory.rebuild_symbols_per_chunk",
        "alpha.validation.oos_start",
        "alpha.ic_measure.horizons",
    } <= keys
    from services.ic_measure import apr_keys_read

    assert set(apr_keys_read("1h")) <= keys


def test_the_apr_hash_moves_with_any_pinned_value():
    @dataclasses.dataclass
    class Config:
        window: int = 5

    base = cr.apr_hash({"threshold.pilot_gate.zero_share_max": 0.25}, Config())
    assert base == cr.apr_hash({"threshold.pilot_gate.zero_share_max": 0.25}, Config())
    assert base != cr.apr_hash({"threshold.pilot_gate.zero_share_max": 0.3}, Config())
    assert base != cr.apr_hash({"threshold.pilot_gate.zero_share_max": 0.25}, Config(6))


def test_the_pilot_fails_on_a_failed_gate():
    world = _world(returncodes={"ops_pilot_compute_gate.py": 1})
    _through(world, "pilot")
    with pytest.raises(cr.StepFailed, match="G4-G5"):
        world.runner.execute("pilot")


# ---------------------------------------------------------------------------
# stage and span steps
# ---------------------------------------------------------------------------


def test_a_span_step_runs_the_full_universe_on_its_span_with_the_run_guard():
    world = _world()
    _through(world, "s2.15m")
    world.runner.execute("s2.15m")
    (call,) = world.rebuild.calls
    assert call["timeframes"] == ["15m"] and call["span"] == SPANS[1] and call["symbols"] is None
    guard = call["disk_guard"]
    assert guard.free_bytes_at_launch == 700 * 10**9 and guard.max_disk_fraction == 0.7


def test_a_span_step_fails_on_a_failed_unit():
    world = _world()
    _through(world, "s1.1h")
    world.store.provenance["k1"] = RUN
    world.rebuild.queued = [_stage_summary(["k1"], failed=1)]
    with pytest.raises(cr.StepFailed, match="units_failed 1"):
        world.runner.execute("s1.1h")


def test_a_span_step_fails_on_a_unit_completed_under_another_run():
    world = _world()
    _through(world, "s1.1h")
    world.store.provenance.update({"k1": RUN, "k2": OTHER})
    world.rebuild.queued = [_stage_summary(["k1", "k2"])]
    with pytest.raises(cr.StepFailed, match=f"completed under another run.*k2 \\(run {OTHER}\\)"):
        world.runner.execute("s1.1h")


def test_a_span_step_fails_on_a_unit_without_a_completed_row():
    world = _world()
    _through(world, "s1.1h")
    world.rebuild.queued = [_stage_summary(["k9"])]
    with pytest.raises(cr.StepFailed, match="without a completed row"):
        world.runner.execute("s1.1h")


def test_a_second_run_over_identical_inputs_adopts_every_unit_and_passes():
    world = _world()
    _through(world, "s1.1h")
    world.store.provenance.update({"k1": OTHER, "k2": OTHER})
    adopted = [
        {"unit_key": "u", "batch_key": k, "adopted_from_run_id": OTHER} for k in ("k1", "k2")
    ]
    world.rebuild.queued = [_stage_summary(["k1", "k2"], adopted=adopted)]
    summary = world.runner.execute("s1.1h")
    assert summary["adopted"] == adopted
    assert world.store.adoptions(RUN) == {"k1": OTHER, "k2": OTHER}


def test_a_tampered_adoption_with_another_batch_key_is_refused():
    world = _world()
    _through(world, "s1.1h")
    world.store.provenance.update({"k1": OTHER})
    tampered = [{"unit_key": "u", "batch_key": "k-other", "adopted_from_run_id": OTHER}]
    world.rebuild.queued = [_stage_summary(["k1"], adopted=tampered)]
    with pytest.raises(cr.StepFailed, match="completed under another run"):
        world.runner.execute("s1.1h")


def test_a_span_5m_step_fails_while_a_chunk_ending_by_its_end_is_uncompressed():
    world = _world()
    _through(world, "s1.5m")
    world.store.uncompressed = [("_hyper_1_7_chunk", datetime(2012, 9, 1, tzinfo=UTC))]
    with pytest.raises(cr.StepFailed, match="1 chunks ending by 2013-01-01 uncompressed"):
        world.runner.execute("s1.5m")
    # the straddling chunk (ending after the span) is allowed to stay open
    world.store.uncompressed = [("_hyper_1_8_chunk", datetime(2013, 8, 27, tzinfo=UTC))]
    world.runner.execute("s1.5m")


def test_stage_maxima_reach_corpus_run_measured():
    world = _world()
    _through(world, "stage_1d")
    world.store.provenance["k1"] = RUN
    world.rebuild.queued = [_stage_summary(["k1"], bpr=1500.0, sps=0.41)]
    world.runner.execute("stage_1d")
    assert world.store.run.measured["bytes_per_row_max"] == 1500.0
    assert world.runner._guard().stored_bytes_per_spool_byte == pytest.approx(0.41)


# ---------------------------------------------------------------------------
# feature_complete
# ---------------------------------------------------------------------------


def _specs(*keys):
    return [SimpleNamespace(batch_key=k) for k in keys]


def test_feature_complete_lists_a_unit_completed_under_another_run():
    world = _world(planned=(_specs("k1", "k2"), set()))
    _through(world, "feature_complete")
    world.store.provenance.update({"k1": RUN, "k2": OTHER})
    with pytest.raises(cr.StepFailed, match="1 units completed under another run"):
        world.runner.execute("feature_complete")
    foreign = world.store.steps["feature_complete"].summary["units_foreign"]
    assert foreign == [{"batch_key": "k2", "run_id": OTHER}]


def test_feature_complete_fails_on_a_digest_blind_symbol_from_a_stage():
    world = _world(planned=(_specs("k1"), set()))
    _through(world, "feature_complete")
    _complete(world, "s1.5m", digest_blind_symbols=["ZZZ"])
    world.store.provenance["k1"] = RUN
    with pytest.raises(cr.StepFailed, match="1 digest-blind symbols"):
        world.runner.execute("feature_complete")


def test_feature_complete_fails_on_a_started_row_under_the_run_and_a_failed_screen():
    world = _world(planned=(_specs("k1"), set()), returncodes={"ops_feature_column_screen.py": 1})
    _through(world, "feature_complete")
    world.store.provenance["k1"] = RUN
    world.store.open = [("k7", "started")]
    with pytest.raises(cr.StepFailed, match="1 started or failed rows.*column screen"):
        world.runner.execute("feature_complete")


def test_feature_complete_passes_with_own_and_adopted_units():
    world = _world(planned=(_specs("k1", "k2"), set()))
    _through(world, "feature_complete")
    _complete(
        world, "s1.1h", adopted=[{"unit_key": "u", "batch_key": "k2", "adopted_from_run_id": OTHER}]
    )
    world.store.provenance.update({"k1": RUN, "k2": OTHER})
    summary = world.runner.execute("feature_complete")
    assert summary["units_planned"] == 2 and set(summary["column_screen"]) == {
        "5m",
        "15m",
        "1h",
        "1d",
    }


# ---------------------------------------------------------------------------
# ic_measure, d19_bound, canary
# ---------------------------------------------------------------------------


def _ic_units(world: World, owner: str, status: str = "loaded", reported_key=None) -> None:
    """Every expected ic_measure unit completed under `owner`, and the run's report listing
    each with `status` (and the batch key it computed, the completed row's by default)."""
    from services._batch_utils import bulk_load_unit_key
    from services.ic_measure import TARGET_TABLE, job_replace_where, job_writer

    outcomes = []
    for job in ("proposer", "regime_volatility"):
        for tf in ("1h", "1d"):
            key = bulk_load_unit_key(job_writer(job), TARGET_TABLE, tf, job_replace_where(job, tf))
            batch = f"bk-{job}-{tf}"
            world.store.units[key] = [(batch, owner)]
            outcomes.append({"unit_key": key, "batch_key": reported_key or batch, "status": status})
    world.state["report"] = {"outcomes": outcomes, "failures": []}


def test_the_caveat_reaches_the_ic_measure_and_canary_summaries_verbatim():
    world = _world(run=_run(caveats=(CAVEAT,)))
    _through(world, "ic_measure")
    _ic_units(world, RUN)
    ic = world.runner.execute("ic_measure")
    assert ic["caveats"] == [CAVEAT] and ic["adopted"] == []
    argv, cwd = world.commands[-1]
    assert argv[1:5] == ["-m", "services.ic_measure", "--run-id", RUN] and cwd == WORKTREE
    assert argv[5] == "--report" and argv[6].endswith(f"ic_measure_{RUN}.json")
    world.runner.execute("d19_bound")
    canary = world.runner.execute("canary")
    assert canary["caveats"] == [CAVEAT]
    assert world.commands[-1][0][-2:] == ["--run-id", RUN]


def test_ic_measure_adopts_exactly_the_units_it_reported_skipped():
    world = _world()
    _through(world, "ic_measure")
    _ic_units(world, OTHER, status="skipped")
    summary = world.runner.execute("ic_measure")
    assert len(summary["adopted"]) == 4
    assert {a["adopted_from_run_id"] for a in summary["adopted"]} == {OTHER}


@pytest.mark.parametrize(
    "status, reported_key",
    [
        ("loaded", None),  # this run loaded it, then a manual run replaced it under OTHER
        ("skipped_concurrent", None),  # another writer completed it between check and lock
        ("skipped", "bk-something-else"),  # the completed row is not the identity it skipped
    ],
)
def test_a_manual_ic_measure_unit_written_mid_window_is_not_adopted(status, reported_key):
    world = _world()
    _through(world, "ic_measure")
    _ic_units(world, OTHER, status=status, reported_key=reported_key)
    with pytest.raises(cr.StepFailed, match="ic_measure units"):
        world.runner.execute("ic_measure")
    assert "adopted" not in world.store.steps["ic_measure"].summary or not (
        world.store.steps["ic_measure"].summary["adopted"]
    )
    assert world.store.adoptions(RUN) == {}


def test_ic_measure_fails_on_a_unit_missing_from_its_report():
    world = _world()
    _through(world, "ic_measure")
    _ic_units(world, RUN)
    world.state["report"]["outcomes"].pop()
    with pytest.raises(cr.StepFailed, match="no outcome in the ic_measure report"):
        world.runner.execute("ic_measure")


def test_ic_measure_fails_on_a_missing_or_unexpected_lookahead():
    world = _world()
    _through(world, "ic_measure")
    _ic_units(world, RUN)
    world.store.lookaheads = {"1h": {1: 9, 6: 9}}
    with pytest.raises(
        cr.StepFailed, match="1d: no POOLED rows at lookaheads \\[1\\].*1h: unexpected"
    ):
        world.runner.execute("ic_measure")


def test_ic_measure_fails_on_its_exit_code():
    world = _world(returncodes={"services.ic_measure": 1})
    _through(world, "ic_measure")
    with pytest.raises(cr.StepFailed, match="ic_measure exited 1"):
        world.runner.execute("ic_measure")


def test_d19_bound_fails_on_a_row_reaching_oos_start():
    world = _world()
    _through(world, "d19_bound")
    world.store.reaching = (2, datetime(2026, 1, 2, tzinfo=UTC))
    with pytest.raises(cr.StepFailed, match="2 feature_ic_scores rows reach oos_start"):
        world.runner.execute("d19_bound")


def test_the_canary_fails_on_its_exit_code():
    world = _world(returncodes={"ops_canary_integrity_assert.py": 1})
    _through(world, "canary")
    with pytest.raises(cr.StepFailed, match="canary exited 1"):
        world.runner.execute("canary")


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------


def test_logs_and_the_worktree_derive_from_the_main_checkout(monkeypatch, tmp_path):
    main = tmp_path / "indicagent"
    monkeypatch.setattr(cr, "_git", lambda args, cwd: str(main / ".git"))
    worktree_dir = tmp_path / "scratch" / "wt" / "services"
    assert cr.main_logs_dir(worktree_dir) == main / "logs"
    assert cr.run_worktree(RUN, main) == tmp_path / f"indicagent-corpus-run-{RUN}"


def test_the_main_checkout_of_this_checkout_holds_the_git_common_dir():
    root = cr.main_checkout_root()
    assert (root / ".git").exists()


# ---------------------------------------------------------------------------
# Stored rows at launch: only adoptable units are on disk for good (review round 2)
# ---------------------------------------------------------------------------


class _StoredConn:
    """Answers stored_row_counts' three reads: any completed unit, the completed batch keys,
    and the adoptable units' stored rows; records the unit arrays it was asked for."""

    def __init__(self, any_completed: bool, completed: set[str], stored_rows: list[tuple]):
        self.any_completed = any_completed
        self.completed = completed
        self.stored_rows = stored_rows
        self.unit_queries: list[tuple] = []

    def cursor(self):
        conn = self

        class _Cur:
            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

            def execute(self, sql, params):
                self.sql, self.params = sql, params
                if "WITH c AS" in sql:
                    conn.unit_queries.append(params)

            def fetchone(self):
                return (conn.any_completed,)

            def fetchall(self):
                if "WITH c AS" in self.sql:
                    return conn.stored_rows
                return [(k,) for k in self.params[0] if k in conn.completed]

        return _Cur()


def _unit(key: str, tf: str = "5m", year: int = 2010):
    return SimpleNamespace(
        batch_key=key,
        tf=tf,
        symbols=("AAA", "BBB"),
        range_start=_jan1(year),
        range_end=_jan1(year + 1),
    )


CHUNKS = [("AAA", "BBB")]


def test_a_new_run_over_a_dead_runs_rows_at_another_code_key_projects_them_as_growth():
    """feature_vectors holds a dead run's completed units, but this run's code key renames every
    unit: nothing is adoptable, so the stored rows are not subtracted and the plan counts the
    whole rewrite as growth."""
    conn = _StoredConn(True, completed={"old-key"}, stored_rows=[("5m", 0, date(2010, 1, 1), 999)])
    planned = lambda settings, c, horizon: ([_unit("new-key")], set())  # noqa: E731
    stored = cr.stored_row_counts(conn, object(), _jan1(2026), CHUNKS, planned=planned)
    assert stored.cells == {} and conn.unit_queries == []
    counts = RowCounts({("5m", 0, date(2010, m, 1)): 1000 for m in range(1, 13)})
    inputs = _world().runner._inputs()
    from services.corpus_rerun_budget import plan_spans

    fresh = plan_spans(counts, inputs)
    over_dead = plan_spans(counts, inputs, stored=stored)
    assert [p.total for p in over_dead.peaks] == [p.total for p in fresh.peaks]


def test_only_the_rows_of_units_the_run_would_adopt_count_as_stored():
    rows = [("5m", 0, date(2010, 1, 1), 1000)]
    conn = _StoredConn(True, completed={"same-key"}, stored_rows=rows)
    planned = lambda settings, c, horizon: (  # noqa: E731
        [_unit("same-key"), _unit("renamed", year=2011)],
        set(),
    )
    stored = cr.stored_row_counts(conn, object(), _jan1(2026), CHUNKS, planned=planned)
    assert stored.cells == {("5m", 0, date(2010, 1, 1)): 1000}
    (params,) = conn.unit_queries
    assert params[2:] == (["5m"], [0], [_jan1(2010)], [_jan1(2011)])  # the adoptable unit only


def test_an_empty_table_plans_nothing_to_find_stored_rows():
    def planned(*a):
        raise AssertionError("must not plan the full scope")

    conn = _StoredConn(False, set(), [])
    assert cr.stored_row_counts(conn, object(), _jan1(2026), CHUNKS, planned=planned).cells == {}


# ---------------------------------------------------------------------------
# G6 for object and event columns: the NULL share of present rows (review round 4)
# ---------------------------------------------------------------------------

_OBJECTS = frozenset({"swing_high_dist_atr", "bars_since_vol_spike_fast"})


def _gate(rows, applicable=None, tfs=None):
    applies = applicable or (lambda tf: _OBJECTS | {"adx"})
    expected = tfs if tfs is not None else sorted({tf for _key, tf, _stats in rows})
    return cr.object_share_gate(rows, _OBJECTS, applies, 0.05, expected)


def _counted(key, tf, **counts):
    return (key, tf, {c: {"present": p, "nan_present": n} for c, (p, n) in counts.items()})


def test_a_95_percent_nan_swing_column_on_present_rows_fails():
    rows = [
        _counted("k1", "5m", swing_high_dist_atr=(1000, 950), bars_since_vol_spike_fast=(800, 0)),
        _counted("k2", "5m", swing_high_dist_atr=(1000, 950), bars_since_vol_spike_fast=(700, 0)),
    ]
    gate = _gate(rows)
    assert len(gate["failing"]) == 1 and "swing_high_dist_atr" in gate["failing"][0]
    assert gate["shares"]["5m"]["swing_high_dist_atr"] == pytest.approx(0.95)


def test_a_column_nan_only_where_its_object_is_absent_passes():
    """Absent rows are not present: they never enter the share, however many there are."""
    rows = [_counted("k1", "5m", swing_high_dist_atr=(40, 0), bars_since_vol_spike_fast=(5, 0))]
    gate = _gate(rows)
    assert gate["failing"] == [] and gate["shares"]["5m"]["swing_high_dist_atr"] == 0.0


def test_present_zero_on_an_applicable_tf_fails_and_on_another_tf_does_not():
    rows = [_counted("k1", "1d", swing_high_dist_atr=(0, 0), bars_since_vol_spike_fast=(9, 0))]
    gate = _gate(rows)
    assert gate["failing"] == ["tf 1d swing_high_dist_atr: present = 0 on a tf where it applies"]
    not_on_1d = _gate(rows, applicable=lambda tf: {"bars_since_vol_spike_fast"})
    assert not_on_1d["failing"] == []


def test_a_unit_without_unit_stats_fails():
    gate = _gate([("k" * 12, "5m", None)], tfs=[])
    assert gate["failing"] and "carries no unit_stats" in gate["failing"][0]


def test_an_expected_tf_with_no_unit_at_all_fails_present_zero():
    rows = [_counted("k1", "5m", swing_high_dist_atr=(50, 0), bars_since_vol_spike_fast=(9, 0))]
    gate = _gate(rows, tfs=["5m", "15m"])
    assert sorted(gate["failing"]) == [
        "tf 15m bars_since_vol_spike_fast: present = 0 on a tf where it applies",
        "tf 15m swing_high_dist_atr: present = 0 on a tf where it applies",
    ]


def test_feature_complete_and_the_pilot_run_the_object_gate():
    world = _world(planned=(_specs("k1"), set()))
    _through(world, "feature_complete")
    world.store.provenance["k1"] = RUN
    world.store.stats["k1"] = ("1h", {"swing_high_dist_atr": {"present": 100, "nan_present": 96}})
    with pytest.raises(cr.StepFailed, match="object or event column shares fail"):
        world.runner.execute("feature_complete")
    pilot = _world()
    _through(pilot, "pilot")
    pilot.store.stats = {
        f"{i:064x}": ("1h", {"swing_high_dist_atr": {"present": 0, "nan_present": 0}})
        for i in (1, 2)
    }
    with pytest.raises(cr.StepFailed, match="G6-objects"):
        pilot.runner.execute("pilot")
