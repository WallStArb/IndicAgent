"""Unit tests: ic_engine checkpoint content-key derivation.

_checkpoint_content_key replaced a git-HEAD-short key (2026-07-15) -- HEAD
invalidates on any commit landing anywhere in the repo, which silently discarded
~31h of a real corpus run's checkpoints when an unrelated branch merge shifted
HEAD's hash. The content key must (1) change when a file actually imported by
ic_engine changes SEMANTICALLY, (2) stay stable across a comment/docstring-only
edit to an imported file (2026-07-29 rca_analysis, todo 198 -- raw-byte hashing
was found forcing full recompute of multi-day runs on a live comment-only
commit that altered zero computed output), and (3) stay stable when unrelated
repo files (including anything outside the src/ and services/ first-party
roots -- venvs, tests, docs) change.

No DB, no subprocess. Pure Python inspection of sys.modules.
"""

from __future__ import annotations

import sys
import types
from pathlib import Path

import pytest

_project_root = Path(__file__).parent.parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from services.ic_engine import _checkpoint_content_key


@pytest.fixture
def fake_services_module(request):
    """Yield a Path under services/ for a throwaway module, self-healing on entry.

    _checkpoint_content_key() hashes the real services/ and src/ roots by path, so the
    fake module's __file__ must genuinely live there -- tmp_path can't substitute. A
    killed test run (Ctrl-C, OOM, CI timeout) can skip the finally-block cleanup below and
    leave the file behind (happened live 2026-08-01); removing any stale file with this
    exact name BEFORE the test runs makes that self-healing on the next run, on top of the
    try/finally's normal-exit cleanup.
    """
    name = request.param
    fake_module_path = _project_root / "services" / name
    fake_module_path.unlink(missing_ok=True)
    try:
        yield fake_module_path
    finally:
        fake_module_path.unlink(missing_ok=True)


def test_content_key_is_deterministic_for_unchanged_modules() -> None:
    first = _checkpoint_content_key()
    second = _checkpoint_content_key()
    assert first == second


@pytest.mark.parametrize("fake_services_module", ["_fake_checkpoint_dep.py"], indirect=True)
def test_content_key_changes_when_a_first_party_module_changes_semantically(
    monkeypatch, fake_services_module
) -> None:
    # Simulate a real edit to a module ic_engine has imported: mutate the file
    # backing an already-loaded first-party module, then re-derive the key.
    fake_module_path = fake_services_module
    fake_module_path.write_bytes(b"x = 1\n")
    before = _checkpoint_content_key()

    monkeypatch.setitem(
        sys.modules,
        "services._fake_checkpoint_dep",
        types.SimpleNamespace(__file__=str(fake_module_path)),
    )
    after_add = _checkpoint_content_key()
    assert after_add != before

    fake_module_path.write_bytes(b"x = 2\n")
    after_edit = _checkpoint_content_key()
    assert after_edit != after_add


@pytest.mark.parametrize("fake_services_module", ["_fake_checkpoint_dep2.py"], indirect=True)
def test_content_key_ignores_comment_and_docstring_only_edits(
    monkeypatch, fake_services_module
) -> None:
    # The exact failure mode found live 2026-07-29: a "reword comment" commit
    # (services/ic_engine.py history has one -- ca4ef569) must NOT force a full
    # corpus recompute, since it changes zero computed output.
    fake_module_path = fake_services_module
    fake_module_path.write_bytes(
        b'def foo(x):\n    """original docstring."""\n    # a comment\n    return x + 1\n'
    )
    monkeypatch.setitem(
        sys.modules,
        "services._fake_checkpoint_dep2",
        types.SimpleNamespace(__file__=str(fake_module_path)),
    )
    before = _checkpoint_content_key()

    fake_module_path.write_bytes(
        b'def foo(x):\n    """a totally reworded, longer docstring."""\n'
        b"    # a completely different comment\n    return x + 1\n"
    )
    after = _checkpoint_content_key()
    assert after == before


def test_content_key_ignores_modules_outside_first_party_roots(monkeypatch) -> None:
    before = _checkpoint_content_key()

    outside_paths = (
        _project_root / ".venv" / "lib" / "fake_dep.py",  # vendored dependency
        _project_root / "tests" / "unit" / "fake_helper.py",  # test-only code
        _project_root / "docs" / "fake_notes.py",  # non-source content
    )
    for i, outside_path in enumerate(outside_paths):
        monkeypatch.setitem(
            sys.modules,
            f"tests._fake_outside_dep_{i}",
            types.SimpleNamespace(__file__=str(outside_path)),
        )

    after = _checkpoint_content_key()
    assert after == before


# 162-03 Task 3 (todo 122): the .pkl checkpoint system (_checkpoint_dir,
# _load_checkpoint, _save_checkpoint) is deleted outright -- the fingerprint
# gate + per-symbol immediate writes fully supersede it. _checkpoint_content_key
# is KEPT (reused verbatim as the fingerprint's code_content_key component),
# so this module's tests above still apply unchanged; only the now-deleted
# _checkpoint_dir's own test is removed.
