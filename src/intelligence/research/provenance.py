"""Git provenance checks the runner refuses on before a real-data run (D-02).

A real run records a code commit and a spec blob, which mean something only if the code that
runs is the code at that commit and the spec parsed is the spec committed. So, before the
snapshot is touched:

- the spec must exist in HEAD (`git cat-file -e HEAD:<path>`; `git ls-files` is the wrong
  check, it passes for a file that is only staged) and match it in both the index and the
  working tree (`git diff --quiet HEAD -- <path>`);
- nothing may be modified, staged or untracked under src/intelligence/, research/specs/ or any
  first-party module the process has actually loaded (src/, services/, scripts/research/).
  Untracked files count: an untracked families/*.py could be imported by dotted path and be
  absent from the recorded commit.

Every git command runs as `git -C <root>`, with the root from `git rev-parse --show-toplevel`,
never the process cwd.
"""

from __future__ import annotations

import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path

_CHECKED = ("src/intelligence", "research/specs")
_FIRST_PARTY = ("src", "services", "scripts/research")


class ProvenanceRefusal(Exception):
    """A real-data run refused because the spec or code is not exactly what is committed."""


def _git(root: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-C", str(root), *args], check=check, capture_output=True, text=True
    )


def repo_root(start: Path) -> Path:
    return Path(_git(Path(start), "rev-parse", "--show-toplevel").stdout.strip())


def head_commit(root: Path) -> str:
    return _git(root, "rev-parse", "HEAD").stdout.strip()


def require_committed(root: Path, rel: str) -> str:
    """The spec's blob sha at HEAD; refuses when it is not in HEAD or differs from it."""
    if _git(root, "cat-file", "-e", f"HEAD:{rel}", check=False).returncode != 0:
        raise ProvenanceRefusal(f"spec not committed: {rel}")
    if _git(root, "diff", "--quiet", "HEAD", "--", rel, check=False).returncode != 0:
        raise ProvenanceRefusal(f"spec differs from HEAD: {rel}")
    return _git(root, "rev-parse", f"HEAD:{rel}").stdout.strip()


def dirty_paths(root: Path, paths: Sequence[str]) -> list[str]:
    """`git status --porcelain` lines (modified, staged or untracked) under `paths`."""
    if not paths:
        return []
    out = _git(root, "status", "--porcelain=v1", "--untracked-files=all", "--", *paths).stdout
    return [line for line in out.splitlines() if line.strip()]


def loaded_first_party_files(root: Path) -> list[str]:
    """Repo-relative paths of loaded modules under src/, services/ or scripts/research/."""
    root = Path(root).resolve()
    roots = [root / p for p in _FIRST_PARTY]
    found: set[str] = set()
    for module in list(sys.modules.values()):
        module_file = getattr(module, "__file__", None)
        if not module_file:
            continue
        path = Path(module_file).resolve()
        if any(path.is_relative_to(r) for r in roots):
            found.add(str(path.relative_to(root)))
    return sorted(found)


def require_clean(root: Path, extra: Sequence[str] = ()) -> None:
    dirty = dirty_paths(root, [*_CHECKED, *loaded_first_party_files(root), *extra])
    if dirty:
        raise ProvenanceRefusal("uncommitted changes in checked code or specs: " + "; ".join(dirty))
