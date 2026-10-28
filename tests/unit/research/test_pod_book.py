"""Pod books: the pure pod series (plan 187-10 Task 1) and run_pod on a fake ledger (Task 2)."""

import asyncio
import dataclasses
import hashlib
import subprocess

import numpy as np
import pytest

from src.intelligence.research.ledger import AttemptSeries, PinnedRun
from src.intelligence.research.pod import pod_series, run_pod, series_sha256
from src.intelligence.research.runner import BudgetConfig, RunContext, RunRefused
from src.intelligence.research.spec import load_spec_from_head
from src.intelligence.statistics.hac import hac_mean_test
from tests.unit.research.test_runner_order import FakeLedger
from tests.unit.research.test_spec import BOOK, FAMILY


def _series(days, values):
    return AttemptSeries(
        sessions=np.array(days, dtype="datetime64[D]"), values=np.array(values, dtype=np.float64)
    )


A = _series(["2024-01-02", "2024-01-03", "2024-01-05", "2024-01-08"], [1.0, 2.0, 3.0, 4.0])
B = _series(["2024-01-03", "2024-01-04", "2024-01-05", "2024-01-08"], [0.5, 9.0, -1.0, 0.25])
C = _series(["2024-01-02", "2024-01-03", "2024-01-08"], [10.0, 20.0, 30.0])


def test_the_sum_runs_on_the_common_sessions_only():
    pod = pod_series([A, B, C])
    assert (
        pod.series.sessions.tolist()
        == np.array(["2024-01-03", "2024-01-08"], dtype="datetime64[D]").tolist()
    )
    np.testing.assert_array_equal(pod.series.values, [2.0 + 0.5 + 20.0, 4.0 + 0.25 + 30.0])
    assert pod.dropped == (2, 2, 1)


def test_the_pod_statistic_is_the_hac_test_on_the_hand_sum():
    rng = np.random.default_rng(0)
    days = np.arange("2020-01-01", "2021-06-01", dtype="datetime64[D]")
    a = _series(days[::1], rng.normal(size=days.size))
    b = _series(days[::2], rng.normal(size=days[::2].size))
    pod = pod_series([a, b])
    hand = a.values[::2] + b.values
    np.testing.assert_array_equal(pod.series.values, hand)
    assert hac_mean_test(pod.series.values) == hac_mean_test(hand)


def test_disjoint_calendars_give_no_series():
    early = _series(["2024-01-02", "2024-01-03"], [1.0, 2.0])
    late = _series(["2024-02-01"], [1.0])
    pod = pod_series([early, late])
    assert pod.series is None and pod.dropped == (2, 1)


@pytest.mark.parametrize(
    "members",
    [
        [A],
        [A, _series(["2024-01-03", "2024-01-02"], [1.0, 2.0])],  # out of order
        [A, _series(["2024-01-03", "2024-01-04"], [1.0, np.nan])],  # a filled or untested row
    ],
)
def test_malformed_members_are_refused(members):
    with pytest.raises(ValueError):
        pod_series(members)


def test_series_sha256_is_the_documented_content_hash():
    expected = hashlib.sha256(
        A.sessions.astype("<i8").tobytes() + A.values.astype("<f8").tobytes()
    ).hexdigest()
    assert series_sha256(A) == expected
    moved = _series(A.sessions, A.values + np.array([0, 0, 0, np.spacing(4.0)]))
    assert series_sha256(moved) != expected  # one ulp moves it


# run_pod against a fake ledger (Task 2).

RUNS = ("0b8e3c1a-1111-4a2b-9c3d-000000000001", "0b8e3c1a-2222-4a2b-9c3d-000000000002")
POD_PATH = "research/specs/pod.yaml"


def _git(root, *args):
    subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True)


def _pod_repo(root, pins):
    root.mkdir(parents=True, exist_ok=True)
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "t@example.com")
    _git(root, "config", "user.name", "t")
    specs = root / "research/specs"
    specs.mkdir(parents=True)
    (specs / "fam.yaml").write_text(FAMILY)
    (specs / "book_a.yaml").write_text(BOOK)
    (specs / "book_b.yaml").write_text(BOOK.replace("book: book_one", "book: book_two"))
    lines = "".join(
        f"\n  - {{book: research/specs/book_{x}.yaml, run_id: {r}, series_sha256: {h}}}"
        for x, r, h in pins
    )
    (root / POD_PATH).write_text(
        "kind: pod_book\npod: pod_one\nprior_source: docs/plans/prereg.md\nbooks:" + lines + "\n"
    )
    _git(root, "add", ".")
    _git(root, "commit", "-q", "-m", "init")
    return load_spec_from_head(root, POD_PATH)


class PodLedger(FakeLedger):
    def __init__(self, runs, **kwargs):
        super().__init__(**kwargs)
        self.runs = runs

    async def pinned_run(self, run_id):
        self.calls.append("pinned_run")
        return self.runs.get(run_id)

    async def start_runs(self, request, identities, run_concepts):
        self.request, self.identities = request, identities
        return await super().start_runs(request, identities, run_concepts)


def _setup(tmp_path, **overrides):
    """Two completed, powered member book tests with series A and B, and a pod pinned to them."""
    series = {RUNS[0]: A, RUNS[1]: B}
    pins = [("a", RUNS[0], series_sha256(A)), ("b", RUNS[1], series_sha256(B))]
    loaded = _pod_repo(tmp_path, overrides.pop("pins", pins))
    runs = {}
    for book, run_id in zip(loaded.books, RUNS, strict=True):
        runs[run_id] = PinnedRun(
            run_id,
            "book_test",
            "completed",
            book.spec_hash,
            "test",
            {
                "power": {"powered": True},
                "turnover_per_session": 0.5,
                "decision": {"statistic": "hac_timing_t_e17"},
            },
            series[run_id],
        )
    for run_id, change in overrides.pop("runs", {}).items():
        runs[run_id] = dataclasses.replace(runs[run_id], **change) if change else None
    ledger = PodLedger(runs)
    ctx = RunContext(root=tmp_path, budget=BudgetConfig("test", 1, 0.05), ledger=ledger)
    return loaded, ctx, ledger


def test_a_pod_run_records_the_summed_series_and_its_headline(tmp_path):
    loaded, ctx, ledger = _setup(tmp_path)
    result = asyncio.run(run_pod(loaded, ctx, mode="real"))
    assert ledger.request.kind == "pod_book" and ledger.request.mode == "real"
    (identity,) = ledger.identities
    assert identity.kind == "pod" and identity.parents == ("book.book_one", "book.book_two")
    pod = pod_series([A, B]).series
    stored = ledger.series[result["run_id"]]
    np.testing.assert_array_equal(stored.values, pod.values)
    decision = result["evidence"]["decision"]
    assert decision["t"] == hac_mean_test(pod.values).t
    headline = ("t", "p", "annualized_sharpe", "mean_session_pnl", "n_sessions")
    assert all(decision[k] is not None for k in headline)
    assert result["evidence"]["turnover_per_session"] == 1.0
    assert [m["run_id"] for m in result["evidence"]["members"]] == list(RUNS)
    assert [m["sessions_dropped"] for m in result["evidence"]["members"]] == [1, 1]
    assert ledger.status[result["run_id"]] == "completed"


@pytest.mark.parametrize(
    "runs, word",
    [
        ({RUNS[1]: None}, "no such run"),
        ({RUNS[1]: {"status": "failed"}}, "not a completed book_test"),
        ({RUNS[1]: {"kind": "evidence"}}, "not a completed book_test"),
        ({RUNS[1]: {"spec_hash": "0" * 64}}, "spec hash"),
        ({RUNS[1]: {"vintage": "other"}}, "vintage"),
        ({RUNS[1]: {"series": None}}, "no stored series"),
        ({RUNS[1]: {"series": C}}, "does not hash to the pin"),
        ({RUNS[1]: {"evidence": {"power": {"powered": False}}}}, "power"),
        (
            {RUNS[1]: {"evidence": {"power": {"powered": True}, "decision": {"statistic": "e16"}}}},
            "scored by",
        ),
    ],
)
def test_a_pin_that_does_not_resolve_is_refused_before_anything_is_counted(tmp_path, runs, word):
    loaded, ctx, ledger = _setup(tmp_path, runs=runs)
    with pytest.raises(RunRefused, match=word):
        asyncio.run(run_pod(loaded, ctx, mode="real"))
    assert "start_runs" not in ledger.calls


def test_disjoint_member_series_are_refused_before_counting(tmp_path):
    late = _series(["2025-01-02"], [1.0])
    loaded, ctx, ledger = _setup(
        tmp_path,
        pins=[("a", RUNS[0], series_sha256(A)), ("b", RUNS[1], series_sha256(late))],
        runs={RUNS[1]: {"series": late}},
    )
    with pytest.raises(RunRefused, match="share no tested session"):
        asyncio.run(run_pod(loaded, ctx, mode="real"))
    assert "start_runs" not in ledger.calls


def test_a_real_pod_runs_once_and_exploration_may_repeat(tmp_path):
    loaded, ctx, ledger = _setup(tmp_path)
    ledger.prior = True
    with pytest.raises(RunRefused, match="already run"):
        asyncio.run(run_pod(loaded, ctx, mode="real"))
    result = asyncio.run(run_pod(loaded, ctx, mode="exploration"))
    assert result["status"] == "completed" and ledger.request.mode == "exploration"


def test_a_pod_the_statistic_cannot_score_is_refused_before_counting(tmp_path):
    one = _series(["2024-01-03"], [1.0])  # shares one session with A: no HAC test on n = 1
    loaded, ctx, ledger = _setup(
        tmp_path,
        pins=[("a", RUNS[0], series_sha256(A)), ("b", RUNS[1], series_sha256(one))],
        runs={RUNS[1]: {"series": one}},
    )
    with pytest.raises(RunRefused, match="at least 2"):
        asyncio.run(run_pod(loaded, ctx, mode="real"))
    assert "start_runs" not in ledger.calls


def test_two_members_pinning_one_run_are_refused(tmp_path):
    loaded, ctx, ledger = _setup(
        tmp_path, pins=[("a", RUNS[0], series_sha256(A)), ("b", RUNS[0], series_sha256(A))]
    )
    with pytest.raises(RunRefused, match="same run"):
        asyncio.run(run_pod(loaded, ctx, mode="real"))
    assert ledger.calls == []


def test_an_uncommitted_member_book_refuses_at_the_gate(tmp_path):
    loaded, ctx, ledger = _setup(tmp_path)
    book_b = tmp_path / "research/specs/book_b.yaml"
    book_b.write_text(book_b.read_text() + "# edited\n")
    with pytest.raises(RunRefused):
        asyncio.run(run_pod(loaded, ctx, mode="real"))
    assert "start_runs" not in ledger.calls


def test_a_failed_completed_write_leaves_the_row_failed(tmp_path):
    loaded, ctx, ledger = _setup(tmp_path)
    finish = ledger.finish_run

    async def flaky(run_id, *, status, **kwargs):
        if status == "completed":
            raise ConnectionError("database went away")
        return await finish(run_id, status=status, **kwargs)

    ledger.finish_run = flaky
    with pytest.raises(ConnectionError):
        asyncio.run(run_pod(loaded, ctx, mode="real"))
    assert list(ledger.status.values()) == ["failed"]


def test_select_books_reads_a_pod_horizon_from_its_member_books(tmp_path):
    from scripts.research.select_books import horizon_sessions

    loaded, _, _ = _setup(tmp_path)

    def text_at(path):
        return (tmp_path / path).read_text()

    assert horizon_sessions((tmp_path / POD_PATH).read_text(), text_at) == 1
    assert loaded.books  # the pod's members are books, each read by path
