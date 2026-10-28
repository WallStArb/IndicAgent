"""The research ledger renderer (phase 187 plan 13 Task 3): pure text from fixture rows, and the
one-path, no-op-when-unchanged commit step with a fake git runner. No database."""

import subprocess
from pathlib import Path

from scripts.research import render_research_ledger as r

_SELECTED = {
    "result": True,
    "vintage": "vintage_1",
    "attempts": 3,
    "sessions": ["2010-01-04", "2025-12-23", 4000],
    "fwer": 0.05,
    "block_mean": 20.0,
    "reps": 500,
    "max_horizon_sessions": 1,
    "not_selected": 2,
    "selection_set": [{"concept": "book.v1", "t": 3.1, "adjusted_p": 0.01, "run_id": "a" * 32}],
    "missing_series": [{"run_id": "b" * 32, "concept": "member.x", "status": "failed"}],
}


def _data(selection=None):
    return r.LedgerData(
        stages=[
            {
                "domain": "family",
                "name": "fam_a",
                "stage": "idea",
                "recipe_versions": 0,
                "attempts": 0,
                "tested": 0,
                "refused": 0,
            },
            {
                "domain": "book",
                "name": "book.v1",
                "stage": "tested",
                "recipe_versions": 1,
                "attempts": 2,
                "tested": 2,
                "refused": 0,
            },
        ],
        attempts=[
            {
                "vintage": "vintage_1",
                "concept": "pod.p",
                "domain": "book",
                "kind": "pod_book",
                "mode": "real",
                "status": "completed",
                "decision_t": 2.5,
                "decision_p": 0.006,
                "gross_sharpe": 1.234567,
                "mean_session_pnl": 0.001,
                "n_sessions": 100,
                "span_start": "2020-01-02",
                "span_end": "2020-06-01",
                "started_at": None,
                "run_id": "c" * 32,
            },
        ],
        legacy=[
            {
                "card_id": "legacy-a",
                "verdict": "DEAD",
                "verdict_date": "2026-09-02",
                "title": "A | pipe",
                "status_now": "closed",
            }
        ],
        pod_members={"pod.p": ["book.v1", "book.v2"]},
        selection=selection or _SELECTED,
        as_of="2026-10-28T12:00:00Z",
    )


def test_render_is_deterministic_and_marked_generated():
    first, second = r.render(_data()), r.render(_data())
    assert first == second
    assert first.startswith("<!-- GENERATED FILE. Do not edit.")
    assert r.RENDER_COMMAND in first and "as of 2026-10-28T12:00:00Z" in first


def test_sections_selection_disclosure_stages_attempts_and_legacy():
    text = r.render(_data())
    assert "1 selected of 3 counted attempts" in text and "FWER 0.05" in text
    assert "series_unavailable (1 counted attempts" in text and "member.x" in text
    assert "### idea (1)" in text and "### tested (1)" in text
    assert text.index("### tested") < text.index("### idea")  # stage order, not alphabetical
    assert "### vintage_1 (1)" in text and "1.235" in text
    assert "`pod.p` members: book.v1, book.v2" in text
    assert "## Legacy verdicts (1)" in text and "A \\| pipe" in text


def test_a_refused_selection_renders_reasons_and_no_set():
    refused = {"result": False, "refusals": ["battery fails in gating cells ['x']"]}
    text = r.render(_data(refused))
    assert "No selection set" in text and "battery fails in gating cells" in text
    assert "adjusted_p" not in text.lower() and "selected of" not in text


class FakeGit:
    def __init__(self, head_blob=None, fail_add=0):
        self.calls, self.head_blob, self.fail_add = [], head_blob, fail_add

    def __call__(self, args):
        self.calls.append(args)
        if args[0] == "rev-parse":
            code = 0 if self.head_blob else 128
            return subprocess.CompletedProcess(args, code, stdout=f"{self.head_blob}\n", stderr="")
        if args[0] == "add" and self.fail_add:
            self.fail_add -= 1
            return subprocess.CompletedProcess(args, 128, stdout="", stderr="index.lock exists")
        return subprocess.CompletedProcess(args, 0, stdout="", stderr="")


def _root(tmp_path: Path, text: str | None) -> Path:
    if text is not None:
        (tmp_path / r.OUT).parent.mkdir(parents=True)
        (tmp_path / r.OUT).write_text(text)
    return tmp_path


def test_unchanged_text_is_a_no_op_with_no_commit(tmp_path):
    root = _root(tmp_path, "same\n")
    git = FakeGit(head_blob=r._blob_hash("same\n"))
    assert r.write_and_commit(root, "same\n", run=git, retries=3) == "unchanged"
    assert all(c[0] == "rev-parse" for c in git.calls)


def test_changed_text_is_written_and_committed_with_exactly_one_path(tmp_path):
    root = _root(tmp_path, "old\n")
    git = FakeGit(head_blob=r._blob_hash("old\n"))
    assert r.write_and_commit(root, "new\n", run=git, retries=3) == "committed"
    assert (root / r.OUT).read_text() == "new\n"
    commit = [c for c in git.calls if c[0] == "commit"][0]
    assert commit[-2:] == ["--", r.OUT] and commit[1:3] == ["-m", r.COMMIT_MESSAGE]
    assert [c[-1] for c in git.calls if c[0] in ("add", "commit")] == [r.OUT, r.OUT]


def test_first_render_of_an_untracked_file_is_added_then_committed(tmp_path):
    root = _root(tmp_path, None)
    (root / "docs" / "research").mkdir(parents=True)
    git = FakeGit(head_blob=None)
    assert r.write_and_commit(root, "first\n", run=git, retries=0) == "committed"


def test_a_file_with_uncommitted_edits_is_never_overwritten(tmp_path):
    root = _root(tmp_path, "hand edit\n")
    git = FakeGit(head_blob=r._blob_hash("committed text\n"))
    out = r.write_and_commit(root, "new\n", run=git, retries=3)
    assert out.startswith("skipped") and (root / r.OUT).read_text() == "hand edit\n"
    assert not [c for c in git.calls if c[0] in ("add", "commit")]


def test_index_lock_is_retried_up_to_the_apr_count_then_skipped(tmp_path):
    root = _root(tmp_path, "old\n")
    sleeps = []
    ok = FakeGit(head_blob=r._blob_hash("old\n"), fail_add=2)
    assert r.write_and_commit(root, "new\n", run=ok, retries=3, sleep=sleeps.append) == "committed"
    assert len(sleeps) == 2
    root2 = _root(tmp_path / "b", "old\n")
    busy = FakeGit(head_blob=r._blob_hash("old\n"), fail_add=99)
    out = r.write_and_commit(root2, "new\n", run=busy, retries=2, sleep=lambda s: None)
    assert (
        out.startswith("failed:git failed") and len([c for c in busy.calls if c[0] == "add"]) == 3
    )
    assert (root2 / r.OUT).read_text() == "old\n"  # restored: no stall behind the HEAD guard


def test_a_failed_first_commit_removes_the_untracked_file(tmp_path):
    root = _root(tmp_path, None)
    (root / "docs" / "research").mkdir(parents=True)

    class Broken(FakeGit):
        def __call__(self, args):
            self.calls.append(args)
            if args[0] == "rev-parse":
                return subprocess.CompletedProcess(args, 128, stdout="", stderr="")
            return subprocess.CompletedProcess(args, 1, stdout="", stderr="pre-commit failed")

    assert r.write_and_commit(root, "first\n", run=Broken(), retries=0).startswith("failed:")
    assert not (root / r.OUT).exists()


def test_blob_hash_matches_git(tmp_path):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    (tmp_path / "f").write_text("hello\n")
    out = subprocess.run(
        ["git", "-C", str(tmp_path), "hash-object", "f"], capture_output=True, text=True, check=True
    )
    assert r._blob_hash("hello\n") == out.stdout.strip()


def test_unit_and_timer_files_and_apr_migration_exist():
    root = Path(__file__).resolve().parents[3]
    assert (
        "Type=oneshot"
        in (root / "production/systemd/indicagent-research-ledger-render.service").read_text()
    )
    timer = (root / "production/systemd/indicagent-research-ledger-render.timer").read_text()
    assert "07:15:00 UTC" in timer and "Persistent=true" in timer
    sql = (root / "production/migrations/536_research_ledger_render_apr.sql").read_text()
    assert r.RETRIES_KEY in sql
