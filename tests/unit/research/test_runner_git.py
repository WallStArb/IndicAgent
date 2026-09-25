"""Git provenance refusals (D-02), each on a throwaway repository."""

import subprocess
import sys

import pytest

from src.intelligence.research.provenance import (
    ProvenanceRefusal,
    dirty_paths,
    head_commit,
    loaded_first_party_files,
    require_clean,
    require_committed,
)

SPEC = "research/specs/f.yaml"


def _git(root, *args):
    return subprocess.run(
        ["git", "-C", str(root), *args], check=True, capture_output=True, text=True
    ).stdout.strip()


@pytest.fixture
def repo(tmp_path):
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "config", "user.email", "t@example.com")
    _git(tmp_path, "config", "user.name", "t")
    (tmp_path / "research/specs").mkdir(parents=True)
    (tmp_path / "src/intelligence/families").mkdir(parents=True)
    (tmp_path / SPEC).write_text("kind: family\n")
    (tmp_path / "src/intelligence/x.py").write_text("X = 1\n")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-q", "-m", "init")
    return tmp_path


def test_clean_committed_spec_passes_and_returns_blob(repo):
    assert require_committed(repo, SPEC) == _git(repo, "rev-parse", f"HEAD:{SPEC}")


def test_staged_only_spec_is_not_committed(repo):
    (repo / "research/specs/new.yaml").write_text("kind: family\n")
    _git(repo, "add", "research/specs/new.yaml")
    with pytest.raises(ProvenanceRefusal, match="not committed"):
        require_committed(repo, "research/specs/new.yaml")


def test_untracked_spec_is_not_committed(repo):
    (repo / "research/specs/new.yaml").write_text("kind: family\n")
    with pytest.raises(ProvenanceRefusal, match="not committed"):
        require_committed(repo, "research/specs/new.yaml")


@pytest.mark.parametrize("stage", [False, True])
def test_edited_spec_differs_from_head(repo, stage):
    (repo / SPEC).write_text("kind: family\nedited: 1\n")
    if stage:
        _git(repo, "add", SPEC)
    with pytest.raises(ProvenanceRefusal, match="differs from HEAD"):
        require_committed(repo, SPEC)


def test_require_clean_passes_on_a_clean_tree(repo):
    require_clean(repo)
    assert dirty_paths(repo, ["src/intelligence"]) == []


@pytest.mark.parametrize("stage", [False, True])
def test_modified_code_refuses(repo, stage):
    (repo / "src/intelligence/x.py").write_text("X = 2\n")
    if stage:
        _git(repo, "add", "src/intelligence/x.py")
    with pytest.raises(ProvenanceRefusal, match="src/intelligence/x.py"):
        require_clean(repo)


@pytest.mark.parametrize("path", ["src/intelligence/families/new.py", "research/specs/other.yaml"])
def test_untracked_code_or_spec_refuses(repo, path):
    (repo / path).write_text("new\n")
    with pytest.raises(ProvenanceRefusal, match=path):
        require_clean(repo)


def test_dirty_file_outside_checked_paths_is_ignored(repo):
    (repo / "docs").mkdir()
    (repo / "docs/notes.md").write_text("draft\n")
    require_clean(repo)


def test_loaded_first_party_files_lists_modules_under_root(repo, monkeypatch):
    (repo / "src/mod_probe_183.py").write_text("Y = 1\n")
    monkeypatch.syspath_prepend(str(repo / "src"))
    import mod_probe_183  # noqa: F401

    try:
        files = loaded_first_party_files(repo)
    finally:
        sys.modules.pop("mod_probe_183", None)
    assert "src/mod_probe_183.py" in files
    assert all(not f.startswith("/") for f in files)


def test_head_commit_is_forty_hex(repo):
    commit = head_commit(repo)
    assert commit == _git(repo, "rev-parse", "HEAD")
    assert len(commit) == 40
