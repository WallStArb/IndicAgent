"""Runner order and refusals (D-02, D-03, D-04, D-25) with a fake ledger, a fake snapshot
builder and a throwaway git repository."""

import asyncio
import subprocess
import textwrap

import numpy as np
import pytest

from src.intelligence.research import panel as panel_mod
from src.intelligence.research import runner as runner_mod
from src.intelligence.research import store
from src.intelligence.research.families.common import declared_memory_rows
from src.intelligence.research.ledger import LedgerRefusal
from src.intelligence.research.panel import Panel
from src.intelligence.research.runner import BudgetConfig, RunContext, RunRefused, run_family
from src.intelligence.research.spec import load_spec_from_file, load_spec_from_head

BPS = 4
SESSIONS = 400
SPEC_PATH = "research/specs/f.yaml"
MEMBER = "src.intelligence.research.families.intraday_periodicity.same_slot_mean"


def _spec_text(member=MEMBER, mem1=None):
    mem1 = declared_memory_rows(1, BPS) if mem1 is None else mem1
    return textwrap.dedent(f"""
        kind: family
        family: test_fam
        prior_source: docs/plans/prereg.md
        horizon: 2
        factor_spec: vintage_1
        panel:
          universe: compute_eligible
          tf: 15m
          bars_per_session: {BPS}
          start: "2010-01-01"
          end_exclusive: "2012-01-01"
        members:
          - name: lag1
            signal: {member}
            params: {{window_sessions: 1}}
            slot_history_sessions: 1
            declared_memory_rows: {mem1}
          - name: mean5
            signal: {MEMBER}
            params: {{window_sessions: 5}}
            slot_history_sessions: 5
            declared_memory_rows: {declared_memory_rows(5, BPS)}
        construction:
          name: rank_vol_neutral
          direction: 1
          coverage_floor: 20
          vol_window_sessions: 20
          vol_min_finite_fraction: 0.5
        scoring:
          session_scoring: true
          trading_start: "2010-01-01"
          sub_periods: [["2010-01-01", "2011-12-31"]]
          min_shift: 5
          bootstrap_mean_block: 5
          bootstrap_reps: 200
          seed: 1
          warmup_sessions: 20
          calibration_refit_sessions: 10
          coverage_fraction: 0.5
          ridge_epsilon_fraction: 0.1
          mv_condition_max: 1000.0
          ic_shrinkage_k: 100.0
        guards: {{seed: 3, n_random: 1, max_rows: 6, s1_probe_sessions: 330}}
        costs: {{bps_low: 1.0, bps_high: 5.0}}
        """)


def _panel(seed=0, m=30):
    rng = np.random.default_rng(seed)
    n = SESSIONS * BPS
    groups = np.arange(m) % 5
    r = (
        rng.normal(0, 0.002, n)[:, None] * rng.uniform(0.5, 1.5, m)
        + rng.normal(0, 0.0015, (n, 5))[:, groups]
        + rng.normal(0, 0.001, (n, m))
    )
    close = 100 * np.exp(np.cumsum(r, axis=0))
    opens = close * np.exp(-0.3 * r)
    missing = rng.random((n, m)) < 0.02
    close[missing] = np.nan
    opens[missing] = np.nan
    days = np.datetime64("2010-01-04T14:30") + np.repeat(np.arange(SESSIONS), BPS) * np.timedelta64(
        1, "D"
    )
    ts = days + np.tile(np.arange(BPS), SESSIONS) * np.timedelta64(15, "m")
    return Panel(
        tf="15m",
        symbols=tuple(f"S{i}" for i in range(m)),
        timestamps=ts,
        bars_per_session=BPS,
        valid=np.ones(n, dtype=bool),
        open=opens,
        close=close,
        volume=np.where(missing, np.nan, 1e5),
        manifest={
            "start": "2010-01-01",
            "end_exclusive": "2012-01-01",
            "universe": "compute_eligible",
        },
    )


class FakeLedger:
    def __init__(self, *, prior=False, refuse=False, fail_finish=False):
        self.calls = []
        self.prior, self.refuse, self.fail_finish = prior, refuse, fail_finish
        self.status = {}

    async def has_real_run(self, spec_hash):
        self.calls.append("has_real_run")
        return self.prior

    async def charged_book_tests(self, vintage):
        return 0

    async def start_runs(self, request, identities, run_concepts):
        self.calls.append("start_runs")
        if self.refuse:
            raise LedgerRefusal("budget exhausted")
        ids = {name: f"run-{i}" for i, name in enumerate(run_concepts)}
        self.status.update({v: "started" for v in ids.values()})
        return ids

    async def finish_run(self, run_id, *, status, snapshot_hash, evidence):
        self.calls.append(("finish_run", status))
        if self.fail_finish:
            raise ConnectionError("database went away")
        self.status[run_id] = status
        self.snapshot_hash = snapshot_hash
        self.evidence = evidence


def _git(root, *args):
    subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True)


@pytest.fixture(scope="module")
def saved_panel(tmp_path_factory):
    return panel_mod.save(_panel(), tmp_path_factory.mktemp("panels"))


@pytest.fixture
def repo(tmp_path):
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "config", "user.email", "t@example.com")
    _git(tmp_path, "config", "user.name", "t")
    (tmp_path / "research/specs").mkdir(parents=True)
    (tmp_path / "src/intelligence").mkdir(parents=True)
    (tmp_path / SPEC_PATH).write_text(_spec_text())
    (tmp_path / "src/intelligence/x.py").write_text("X = 1\n")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-q", "-m", "init")
    return tmp_path


def _ctx(repo, ledger, saved_panel, calls, budget_m=1):
    async def build(dsn, out_dir, spec):
        calls.append("build_snapshot")
        ledger.calls.append("build_snapshot")
        return saved_panel

    return RunContext(
        root=repo,
        budget=BudgetConfig(vintage_id="test", budget_m=budget_m, screen_alpha=0.05),
        ledger=ledger,
        build_snapshot=build,
    )


def _run(loaded, ctx, **kw):
    return asyncio.run(run_family(loaded, ctx, mode="real", **kw))


def test_real_mode_order(repo, saved_panel):
    ledger, calls = FakeLedger(), []
    out = _run(load_spec_from_head(repo, SPEC_PATH), _ctx(repo, ledger, saved_panel, calls))
    assert ledger.calls[:3] == ["has_real_run", "start_runs", "build_snapshot"]
    assert ledger.calls[3:] == [("finish_run", "completed")] * 2
    assert {v["status"] for v in out.values()} == {"completed"}
    assert ledger.snapshot_hash == store.verify(saved_panel)
    assert len(ledger.snapshot_hash) == 64
    assert ledger.evidence["power"] is None


def _refused(repo, saved_panel, ledger=None, loaded=None):
    ledger = ledger or FakeLedger()
    calls = []
    loaded = loaded or load_spec_from_head(repo, SPEC_PATH)
    with pytest.raises(RunRefused):
        _run(loaded, _ctx(repo, ledger, saved_panel, calls))
    assert "start_runs" not in ledger.calls or ledger.refuse
    assert calls == []
    return ledger


def test_refuses_untracked_spec(repo, saved_panel):
    (repo / "research/specs/new.yaml").write_text(_spec_text())
    loaded = load_spec_from_file(repo / "research/specs/new.yaml", root=repo)
    _refused(repo, saved_panel, loaded=loaded)


def test_refuses_spec_modified_after_commit(repo, saved_panel):
    loaded = load_spec_from_head(repo, SPEC_PATH)
    (repo / SPEC_PATH).write_text(_spec_text() + "# edited\n")
    _refused(repo, saved_panel, loaded=loaded)


def test_refuses_untracked_code(repo, saved_panel):
    (repo / "src/intelligence/new.py").write_text("Y = 2\n")
    _refused(repo, saved_panel)


def test_refuses_prior_real_run(repo, saved_panel):
    ledger = _refused(repo, saved_panel, ledger=FakeLedger(prior=True))
    assert "start_runs" not in ledger.calls


def test_ledger_refusal_becomes_run_refused(repo, saved_panel):
    _refused(repo, saved_panel, ledger=FakeLedger(refuse=True))


def test_refuses_inconsistent_declared_memory(repo, saved_panel):
    (repo / SPEC_PATH).write_text(_spec_text(mem1=999))
    _git(repo, "commit", "-qam", "bad memory")
    _refused(repo, saved_panel)


def _peek(x):
    out = np.full(x.shape, np.nan)
    out[:-1] = x[1:]
    return out


def test_guard_failure_ends_rows_guard_failed(repo, saved_panel, monkeypatch):
    real_resolve = runner_mod.resolve_member

    def resolve(dotted):
        fn = real_resolve(dotted)
        if dotted.endswith(".same_slot_mean"):

            def peeking(x, **kw):
                out = fn(_peek(x), **kw)
                out[~np.isfinite(x)] = np.nan  # keep integrity clean so the probe is reached
                return out

            return peeking
        return fn

    monkeypatch.setattr(runner_mod, "resolve_member", resolve)
    ledger, calls = FakeLedger(), []
    out = _run(load_spec_from_head(repo, SPEC_PATH), _ctx(repo, ledger, saved_panel, calls))
    assert {v["status"] for v in out.values()} == {"guard_failed"}
    assert "lookahead" in ledger.evidence["error"]


def test_evidence_runs_have_no_shift_floor(repo, saved_panel):
    """E16: the shift null is a diagnostic; a small panel is recorded, never refused."""
    ledger, calls = FakeLedger(), []
    out = _run(
        load_spec_from_head(repo, SPEC_PATH), _ctx(repo, ledger, saved_panel, calls, budget_m=30)
    )
    assert {v["status"] for v in out.values()} == {"completed"}
    assert ledger.evidence["decision"]["statistic"] == "hac_timing_t"
    assert 0 < ledger.evidence["shift_null"]["n_shifts"] < 600


def test_exception_ends_rows_failed_and_propagates(repo, saved_panel, monkeypatch):
    def boom(*args, **kwargs):
        raise RuntimeError("evaluate exploded")

    monkeypatch.setattr(runner_mod, "evaluate", boom)
    ledger, calls = FakeLedger(), []
    with pytest.raises(RuntimeError, match="exploded"):
        _run(load_spec_from_head(repo, SPEC_PATH), _ctx(repo, ledger, saved_panel, calls))
    assert set(ledger.status.values()) == {"failed"}
    assert "exploded" in ledger.evidence["error"]


def test_hard_crash_leaves_rows_started(repo, saved_panel):
    ledger, calls = FakeLedger(fail_finish=True), []
    with pytest.raises(ConnectionError):
        _run(load_spec_from_head(repo, SPEC_PATH), _ctx(repo, ledger, saved_panel, calls))
    assert set(ledger.status.values()) == {"started"}


def test_synthetic_mode_touches_no_git_ledger_or_snapshot(repo, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("provenance called in synthetic mode")

    for name in ("repo_root", "require_committed", "require_clean", "head_commit"):
        monkeypatch.setattr(runner_mod.provenance, name, forbidden)
    loaded = load_spec_from_file(repo / SPEC_PATH, root=repo)
    ctx = RunContext(root=repo, budget=BudgetConfig("test", 1, 0.05), build_snapshot=forbidden)
    out = asyncio.run(run_family(loaded, ctx, mode="synthetic", panel=_panel()))
    assert {v["status"] for v in out.values()} == {"completed"}
    assert {v["run_id"] for v in out.values()} == {None}
    rec = out["lag1"]["evidence"]
    assert rec["hashes"]["snapshot_hash"] is None and rec["shift_null"]["n_shifts"] >= 20


def test_store_verify_returns_digest_and_detects_tampering(saved_panel, tmp_path):
    digest = store.verify(saved_panel)
    assert len(digest) == 64 and saved_panel.name.endswith(digest[:16])
    copy = tmp_path / saved_panel.name
    copy.mkdir()
    for f in saved_panel.iterdir():
        (copy / f.name).write_bytes(f.read_bytes())
    arr = np.load(copy / "close.npy")
    arr[0, 0] = 1.0
    np.save(copy / "close.npy", arr)
    with pytest.raises(ValueError, match="mismatch"):
        store.verify(copy)


def test_universe_symbols_rejects_unknown_dimension():
    from src.intelligence.research.snapshot import universe_symbols

    with pytest.raises(ValueError, match="unknown universe dimension"):
        asyncio.run(universe_symbols("postgresql://nowhere/none", "is_active; DROP TABLE x"))
