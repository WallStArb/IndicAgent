"""Unit tests: ic_engine checkpoint content-key derivation.

_checkpoint_content_key replaced a git-HEAD-short key (2026-07-15) -- HEAD
invalidates on any commit landing anywhere in the repo, which silently discarded
~31h of a real corpus run's checkpoints when an unrelated branch merge shifted
HEAD's hash. The content key must (1) change when a file actually imported by
ic_engine changes, and (2) stay stable when unrelated repo files (including
anything outside the src/ and services/ first-party roots -- venvs, tests,
docs) change.

No DB, no subprocess. Pure Python inspection of sys.modules.
"""

from __future__ import annotations

import sys
import types
from pathlib import Path

_project_root = Path(__file__).parent.parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from services.ic_engine import _checkpoint_content_key, _checkpoint_dir


def test_content_key_is_deterministic_for_unchanged_modules() -> None:
    first = _checkpoint_content_key()
    second = _checkpoint_content_key()
    assert first == second


def test_content_key_changes_when_a_first_party_module_changes(monkeypatch) -> None:
    # Simulate a real edit to a module ic_engine has imported: mutate the file
    # backing an already-loaded first-party module, then re-derive the key.
    # Must live under services/ or src/ -- the function only hashes those roots.
    fake_module_path = _project_root / "services" / "_fake_checkpoint_dep.py"
    try:
        fake_module_path.write_bytes(b"# marker A\n")
        before = _checkpoint_content_key()

        monkeypatch.setitem(
            sys.modules,
            "services._fake_checkpoint_dep",
            types.SimpleNamespace(__file__=str(fake_module_path)),
        )
        after_add = _checkpoint_content_key()
        assert after_add != before

        fake_module_path.write_bytes(b"# marker B\n")
        after_edit = _checkpoint_content_key()
        assert after_edit != after_add
    finally:
        fake_module_path.unlink(missing_ok=True)


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


def test_checkpoint_dir_embeds_content_key() -> None:
    d = _checkpoint_dir("2025-12-24 05:15:00+00:00", "abc123def456")
    assert d.name.endswith("_abc123def456")
    assert "logs/ic_engine_checkpoints" in str(d)
