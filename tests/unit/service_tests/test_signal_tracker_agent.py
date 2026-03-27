"""Unit tests for SignalTrackerAgent — TDD tests for 52.4 refactor."""

import ast
import pathlib

import pytest


def test_class_name():
    src = pathlib.Path("services/signal_tracker_agent.py").read_text()
    tree = ast.parse(src)
    class_names = [n.name for n in ast.walk(tree) if isinstance(n, ast.ClassDef)]
    assert "SignalTrackerAgent" in class_names
    assert "SignalLifecycleService" not in class_names


def test_inherits_base_agent():
    src = pathlib.Path("services/signal_tracker_agent.py").read_text()
    assert "BaseAgent" in src


def test_no_direct_sql():
    src = pathlib.Path("services/signal_tracker_agent.py").read_text()
    # No raw SQL in the agent class — all delegated to repository
    assert "UPDATE signal_ledger" not in src
    assert "INSERT INTO signal_ledger" not in src


def test_uses_signal_ledger_repository():
    src = pathlib.Path("services/signal_tracker_agent.py").read_text()
    assert "SignalLedgerRepository" in src


def test_has_sigterm_drain():
    src = pathlib.Path("services/signal_tracker_agent.py").read_text()
    assert "_stop_event" in src or "SIGTERM" in src
