"""CI guard: every daemon-shaped class under services/ extends BaseDaemon, BaseWriter, or
BaseBatch -- directly or transitively.

Nothing else mechanically enforces this (todo 157). A new services/*.py class that hand-rolls
its own asyncio loop instead of extending one of these bases silently loses all 5 mandatory
OTel signals (agent_last_message_timestamp_seconds, agent_crash_total, agent_dlq_total,
watchdog_notify_total, watchdog_notify_suppressed_total) with zero CI failure -- see
src/core/agent/base.py and the "OTel Health Contract" section of CLAUDE.md.

Static analysis only -- ast.parse, no imports of services/*.py. Importing a service module
has real side effects (Kafka clients, FastAPI app construction, env var reads at import time)
that don't belong in a unit test. Ancestry is resolved by building a class-name -> base-name
graph from every module-level class def found under src/ and services/, then walking that
graph -- equivalent to checking MRO membership without executing any module code. This also
means it correctly resolves indirect bases: AlphaSwarm/NarrativeSwarm extend
BaseGroupCoordinator (src/intelligence/ai/group_coordinator.py), which itself extends
BaseDaemon -- a check limited to *direct* bases would false-positive on both.

Candidate ("daemon-shaped class") heuristic, per todo 157's own definition: a module-level
class in services/*.py that either
  (a) defines an async `run` or `_run` method directly, or
  (b) has a BaseDaemon._to_snake_case()-derived agent_id that appears as a key in
      service_auditor.py's _AGENT_ID_TO_UNIT dict (the table that maps a running agent's
      derived identity to its systemd unit).
Anything not matching (a) or (b) -- config/request dataclasses, NamedTuples, exception
classes, TypedDicts, pydantic request models -- is not a daemon and is correctly out of
scope; loosening the heuristic to catch these would just produce noise.

Files with zero module-level classes (a `def main()` entrypoint script, no class at all) are
out of scope by construction -- a class-MRO check cannot fire on a file with no class. This
covers the 4 oneshot `_agent.py` scripts CLAUDE.md's "Oneshot _agent.py exceptions" gotcha
already documents (feature_validation_agent.py, hmm_training_agent.py, ml_training_agent.py,
ml_signal_training_agent.py), plus thin services/ wrapper scripts that import and run a
BaseDaemon subclass defined under src/ instead of services/ (outbox_dispatcher_agent.py ->
src/config/outbox_publisher.py's OutboxPublisher; self_healer.py's FastAPI lifespan
constructs src/self_healing/engine.py's SelfHealingEngine, which is an HTTP webhook receiver,
not a BaseDaemon subclass at all -- a different, legitimate runtime pattern). None of these
need an allow-list entry: they never produce a candidate for this heuristic to flag.

CI-clean: no DB, no network -- pure filesystem parse (plus one import of the zero-side-effect
`_to_snake_case` helper from src/core/agent/base.py, itself already imported by other passing
unit tests, e.g. tests/unit/core/test_base_agent.py).
"""

from __future__ import annotations

import ast
import functools
from pathlib import Path

from src.core.agent.base import _to_snake_case
from tests.unit._allow_list_scan import stale_allow_list_entries, unexpected_violations

_REPO_ROOT = Path(__file__).parent.parent.parent
_SERVICES_DIR = _REPO_ROOT / "services"
_SRC_DIR = _REPO_ROOT / "src"
_SERVICE_AUDITOR_PATH = _SERVICES_DIR / "service_auditor.py"

_BASE_CLASS_ROOTS = frozenset({"BaseDaemon", "BaseWriter", "BaseBatch"})

# (qualified name "relative/path.py::ClassName") -> reason. Every daemon-shaped candidate
# class in services/*.py whose static ancestry doesn't reach BaseDaemon/BaseWriter/BaseBatch
# must appear here with a real reason, or be fixed to extend one of those bases.
_ALLOW_LIST: dict[str, str] = {}


def _class_bases(node: ast.ClassDef) -> list[str]:
    """Base-class identifiers for a ClassDef, resolving both `Foo` and `mod.Foo` forms."""
    bases: list[str] = []
    for b in node.bases:
        if isinstance(b, ast.Name):
            bases.append(b.id)
        elif isinstance(b, ast.Attribute):
            bases.append(b.attr)
    return bases


def _has_async_run_method(node: ast.ClassDef) -> bool:
    return any(isinstance(n, ast.AsyncFunctionDef) and n.name in ("run", "_run") for n in node.body)


@functools.lru_cache(maxsize=1)
def _agent_id_to_unit_keys() -> frozenset[str]:
    """Statically extract _AGENT_ID_TO_UNIT's string keys from service_auditor.py without
    importing it (that module pulls in aiohttp/asyncpg/Kafka client construction)."""
    tree = ast.parse(_SERVICE_AUDITOR_PATH.read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            if node.target.id == "_AGENT_ID_TO_UNIT" and isinstance(node.value, ast.Dict):
                return frozenset(
                    k.value
                    for k in node.value.keys
                    if isinstance(k, ast.Constant) and isinstance(k.value, str)
                )
    raise AssertionError(
        "_AGENT_ID_TO_UNIT not found in service_auditor.py -- this test's static extraction "
        "is out of sync with a rename/refactor of that dict."
    )


@functools.lru_cache(maxsize=1)
def _base_class_graph() -> dict[str, list[str]]:
    """Maps every module-level class name under src/ and services/ to its declared base
    names. Class names are assumed unique enough for ancestry-walk purposes (this codebase's
    naming convention derives one class name per concept -- see CLAUDE.md's Naming section);
    a name collision would only cause a false negative-to-positive drift here, not a silent
    pass, since an unresolved base name simply dead-ends the walk."""
    graph: dict[str, list[str]] = {}
    for search_dir in (_SRC_DIR, _SERVICES_DIR):
        for path in search_dir.rglob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8", errors="ignore"), filename=str(path))
            for node in tree.body:
                if isinstance(node, ast.ClassDef):
                    graph[node.name] = _class_bases(node)
    return graph


def _reaches_base_class_root(class_name: str) -> bool:
    """BFS over the static base-class graph -- the ast-only equivalent of `cls.__mro__`."""
    graph = _base_class_graph()
    seen: set[str] = set()
    queue = [class_name]
    while queue:
        name = queue.pop()
        if name in _BASE_CLASS_ROOTS:
            return True
        if name in seen:
            continue
        seen.add(name)
        queue.extend(graph.get(name, []))
    return False


@functools.lru_cache(maxsize=1)
def _find_candidates() -> dict[str, tuple[str, bool]]:
    """Returns {qualified_name: (class_name, is_compliant)} for every daemon-shaped
    candidate class found in services/*.py."""
    agent_ids = _agent_id_to_unit_keys()
    candidates: dict[str, tuple[str, bool]] = {}
    for path in sorted(_SERVICES_DIR.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8", errors="ignore"), filename=str(path))
        for node in tree.body:
            if not isinstance(node, ast.ClassDef):
                continue
            is_candidate = _has_async_run_method(node) or (_to_snake_case(node.name) in agent_ids)
            if not is_candidate:
                continue
            qualified = f"{path.relative_to(_REPO_ROOT)}::{node.name}"
            candidates[qualified] = (node.name, _reaches_base_class_root(node.name))
    return candidates


def test_every_daemon_shaped_service_class_extends_a_base_class():
    candidates = _find_candidates()
    noncompliant = (qualified for qualified, (_, compliant) in candidates.items() if not compliant)
    unexpected = unexpected_violations(noncompliant, _ALLOW_LIST)
    assert not unexpected, (
        "Daemon-shaped class(es) not extending BaseDaemon/BaseWriter/BaseBatch (directly "
        f"or transitively): {[(q, candidates[q][0]) for q in unexpected]}. Either extend "
        "one of those bases (preferred -- this is what wires the 5 mandatory OTel "
        "signals), or add an entry to _ALLOW_LIST in this file with a one-line reason if "
        "this is a genuine, deliberate exception."
    )


def test_base_class_allow_list_has_no_stale_entries():
    stale = stale_allow_list_entries(_find_candidates(), _ALLOW_LIST)
    assert not stale, (
        f"Allow-list entries that no longer match any daemon-shaped candidate class: "
        f"{stale}. Either the class was fixed to extend a base (remove its entry here) or "
        "moved/renamed (update the qualified name)."
    )


def test_allow_list_entries_are_actually_noncompliant():
    """Guards against a stale allow-list entry masking a class that was already fixed to
    extend a base -- if it's compliant, it doesn't need an excuse."""
    candidates = _find_candidates()
    unnecessary = {
        qualified
        for qualified in _ALLOW_LIST
        if qualified in candidates and candidates[qualified][1]
    }
    assert not unnecessary, (
        f"Allow-list entries for class(es) that are actually compliant already: "
        f"{unnecessary}. Remove these entries -- they no longer excuse anything."
    )
