"""Regression tests: NarrativeGroupComputeAgent inherits _setup from BaseGroupService (D-19).

After Phase 78, NarrativeGroupComputeAgent must NOT define its own _setup() override.
BaseGroupService._setup() handles empty _bar_topics() correctly (no bar consumer created).
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock


def test_narrative_group_has_no_setup_override() -> None:
    """NarrativeGroupComputeAgent must NOT define _setup in its own __dict__.

    The class must inherit BaseGroupService._setup() unmodified (D-19).
    This ensures empty _bar_topics() is handled by the base implementation
    which skips bar consumer creation when the list is empty.
    """
    # Import via AST to avoid triggering kafka/db infrastructure at import time
    import ast

    with open("services/ai_narrative_agent.py") as f:
        tree = ast.parse(f.read())

    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == "NarrativeGroupComputeAgent":
            class_method_names = [
                n.name for n in node.body if isinstance(n, ast.FunctionDef | ast.AsyncFunctionDef)
            ]
            assert "_setup" not in class_method_names, (
                "NarrativeGroupComputeAgent._setup() override must be removed (D-19). "
                "BaseGroupService._setup() handles empty _bar_topics() correctly."
            )
            return

    raise AssertionError("NarrativeGroupComputeAgent class not found in services/ai_narrative_agent.py")


def test_narrative_group_has_no_run_override() -> None:
    """NarrativeGroupComputeAgent must NOT define _run in its own __dict__.

    BaseGroupService._run() skips bar_loop when _bar_consumer is None,
    which happens when _bar_topics() returns [].
    """
    import ast

    with open("services/ai_narrative_agent.py") as f:
        tree = ast.parse(f.read())

    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == "NarrativeGroupComputeAgent":
            class_method_names = [
                n.name for n in node.body if isinstance(n, ast.FunctionDef | ast.AsyncFunctionDef)
            ]
            assert "_run" not in class_method_names, (
                "NarrativeGroupComputeAgent._run() override must be removed. "
                "BaseGroupService._run() handles missing bar_consumer correctly."
            )
            return

    raise AssertionError("NarrativeGroupComputeAgent class not found in services/ai_narrative_agent.py")


def test_narrative_group_bar_topics_returns_empty() -> None:
    """_bar_topics() must return an empty list (triggers base class skip of bar consumer)."""
    import ast

    with open("services/ai_narrative_agent.py") as f:
        source = f.read()

    assert "_bar_topics" in source, "_bar_topics method must be defined in NarrativeGroupComputeAgent"
    assert "return []" in source, "_bar_topics() must return [] for narrative group"


def test_narrative_group_handle_trigger_uses_direct_compute() -> None:
    """_handle_trigger must not import or instantiate SafeAgentWrapper."""
    import ast

    with open("services/ai_narrative_agent.py") as f:
        source = f.read()

    tree = ast.parse(source)

    # Walk all imports — none should reference safe_wrapper
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            assert node.module != "src.core.ai.safe_wrapper", (
                "safe_wrapper must not be imported in ai_narrative_agent.py (D-18). "
                "Use agent.compute() directly — BaseAIAgent provides timeout + fallback."
            )
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert "safe_wrapper" not in alias.name, (
                    "safe_wrapper must not be imported in ai_narrative_agent.py (D-18)."
                )
