"""CI guard: BaseBatch/BaseWriter's automatic span-wrapping still exists (todo 157 item 3).

Todo 156's step 2 investigation established that span coverage for the two bounded,
per-run-unit base classes is mechanical, not per-service opt-in:

- `BaseBatch.run()` wraps every subclass's `execute()` call in
  `observed_span(f"{job_name}.execute", **self._span_attrs())`
  (src/core/agent/base_batch.py) -- any class reaching BaseBatch gets this for free.
- `BaseWriter._do_flush()` wraps every `_flush_batch()` call in `writer.flush`, and
  `BaseWriter._run()`'s default consume loop wraps every message in
  `writer.process_message` (src/core/agent/base_writer.py) -- same free-for-any-subclass
  property.

`BaseDaemon` is explicitly NOT mechanically enforceable here (156's own conclusion): its
`_run()` is abstract and runs for the life of the process with no per-unit boundary the base
class can see -- a span wrapping the whole call would never close until shutdown, an
anti-pattern for tracing backends. Direct `BaseDaemon` subclasses remain convention-only;
this test does not (and per 156's reasoning, should not) assert anything about them.

This test does NOT re-verify per-subclass compliance (test_service_base_class_compliance.py
already guards that every daemon-shaped class reaches one of these three bases -- reaching
BaseBatch/BaseWriter is sufficient for span coverage by construction, inheritance is not
optional). What IS worth guarding: a future refactor of base_batch.py/base_writer.py
accidentally removing the span-wrapping call itself, which would silently drop tracing for
all 8+ current BaseBatch subclasses and every BaseWriter subclass at once with no per-service
signal that anything changed. Static source check, not an import -- consistent with this
project's other CI-guard tests over these same base classes (avoids executing module-level
side effects).

CI-clean: no DB, no network -- pure filesystem parse.
"""

from __future__ import annotations

import ast
from pathlib import Path

_REPO_ROOT = Path(__file__).parent.parent.parent
_BASE_BATCH_PATH = _REPO_ROOT / "src" / "core" / "agent" / "base_batch.py"
_BASE_WRITER_PATH = _REPO_ROOT / "src" / "core" / "agent" / "base_writer.py"


def _find_method(tree: ast.Module, class_name: str, method_name: str) -> ast.AsyncFunctionDef:
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == class_name:
            for item in node.body:
                if isinstance(item, ast.AsyncFunctionDef) and item.name == method_name:
                    return item
    raise AssertionError(
        f"{class_name}.{method_name} not found in {class_name} -- this test's static lookup "
        "is out of sync with a rename/refactor of the base class."
    )


def _calls_containing(node: ast.AST, *, func_name: str) -> list[ast.Call]:
    """All ast.Call nodes anywhere under `node` whose called function's name matches
    `func_name` (handles both `bare_name(...)` and `obj.method(...)` call shapes)."""
    matches = []
    for sub in ast.walk(node):
        if not isinstance(sub, ast.Call):
            continue
        func = sub.func
        name = func.id if isinstance(func, ast.Name) else getattr(func, "attr", None)
        if name == func_name:
            matches.append(sub)
    return matches


def test_base_batch_run_still_wraps_execute_in_a_span():
    tree = ast.parse(_BASE_BATCH_PATH.read_text(encoding="utf-8"), filename=str(_BASE_BATCH_PATH))
    run_method = _find_method(tree, "BaseBatch", "run")
    calls = _calls_containing(run_method, func_name="observed_span")
    assert calls, (
        "BaseBatch.run() no longer calls observed_span(...) around execute() -- this was the "
        "todo 156 step 2 fix giving every BaseBatch subclass (ensemble_trainer, "
        "alpha_publisher, cross_sectional_spread_tracker, counterfactual_tracker, "
        "ensemble_ic_engine, alpha_scorer, alpha_frame_writer, tag_calibrator, and any future "
        "subclass) automatic span coverage with zero per-service code. If this was removed "
        "intentionally, each of those services now needs its own observed_span call restored."
    )


def test_base_writer_flush_still_wraps_in_a_span():
    tree = ast.parse(_BASE_WRITER_PATH.read_text(encoding="utf-8"), filename=str(_BASE_WRITER_PATH))
    flush_method = _find_method(tree, "BaseWriter", "_do_flush")
    calls = _calls_containing(flush_method, func_name="start_as_current_span")
    span_names = {
        c.args[0].value
        for c in calls
        if c.args and isinstance(c.args[0], ast.Constant) and isinstance(c.args[0].value, str)
    }
    assert "writer.flush" in span_names, (
        "BaseWriter._do_flush() no longer wraps its flush call in a 'writer.flush' span -- "
        "every BaseWriter subclass silently loses this tracing coverage."
    )


def test_base_writer_run_still_wraps_message_processing_in_a_span():
    tree = ast.parse(_BASE_WRITER_PATH.read_text(encoding="utf-8"), filename=str(_BASE_WRITER_PATH))
    run_method = _find_method(tree, "BaseWriter", "_run")
    calls = _calls_containing(run_method, func_name="start_as_current_span")
    span_names = {
        c.args[0].value
        for c in calls
        if c.args and isinstance(c.args[0], ast.Constant) and isinstance(c.args[0].value, str)
    }
    assert "writer.process_message" in span_names, (
        "BaseWriter._run()'s default consume loop no longer wraps each message in a "
        "'writer.process_message' span -- every BaseWriter subclass silently loses this "
        "tracing coverage."
    )
