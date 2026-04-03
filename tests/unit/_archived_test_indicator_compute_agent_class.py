"""TDD: IndicatorComputeAgent class rename + BaseAgent inheritance verification.

Tests use AST parsing and source inspection (no service imports needed) to
verify the structural constraints of services/indicator_compute_agent.py.
"""

import ast
import asyncio
from pathlib import Path
from unittest.mock import MagicMock

import pytest

AGENT_FILE = Path(__file__).parent.parent.parent / "services" / "indicator_compute_agent.py"


def _load_source() -> str:
    return AGENT_FILE.read_text()


def _parse_class_names() -> list[str]:
    tree = ast.parse(_load_source())
    return [node.name for node in ast.walk(tree) if isinstance(node, ast.ClassDef)]


def test_class_is_indicator_compute_agent() -> None:
    """The file must define a class named IndicatorComputeAgent."""
    class_names = _parse_class_names()
    assert "IndicatorComputeAgent" in class_names, (
        f"Expected 'IndicatorComputeAgent' in class names, got: {class_names}"
    )


def test_inherits_base_agent() -> None:
    """IndicatorComputeAgent must inherit from BaseAgent."""
    source = _load_source()
    assert "BaseAgent" in source, "Expected 'BaseAgent' to appear in source (inheritance)"


def test_no_indicator_service_class_def() -> None:
    """No class named IndicatorService must remain in the file."""
    class_names = _parse_class_names()
    assert "IndicatorService" not in class_names, (
        "Found 'IndicatorService' class definition — must be renamed to IndicatorComputeAgent"
    )


def test_main_block_uses_new_name() -> None:
    """The main() function must instantiate IndicatorComputeAgent, not IndicatorService."""
    source = _load_source()
    assert "IndicatorComputeAgent(args.config)" in source, (
        "Expected 'IndicatorComputeAgent(args.config)' in source (main() instantiation)"
    )


class TestIndicatorComputeAgentLifecycle:
    """D-17: Lifecycle contract tests for IndicatorComputeAgent.

    Uses __new__ injection pattern (CLAUDE.md) to bypass __init__ and test
    lifecycle properties in isolation — no Kafka, DB, or I/O required.
    """

    def setup_method(self):
        from services.indicator_compute_agent import IndicatorComputeAgent

        self.agent = IndicatorComputeAgent.__new__(IndicatorComputeAgent)
        self.agent.name = "indicator_compute_agent"
        self.agent._stop_event = asyncio.Event()
        self.agent._metrics_port = 9109
        self.agent.logger = MagicMock()
        self.agent.tracer = MagicMock()
        self.agent.config = {}
        self.agent.env_name = "development"

    def test_topics_consumed_returns_list(self):
        """topics_consumed must return a non-empty list of topic strings."""
        topics = self.agent.topics_consumed
        assert isinstance(topics, list)
        assert len(topics) > 0

    def test_topics_produced_returns_list(self):
        """topics_produced must return a non-empty list of topic strings."""
        topics = self.agent.topics_produced
        assert isinstance(topics, list)
        assert len(topics) > 0

    def test_running_property_true_when_stop_event_not_set(self):
        """running property must return True before stop_event is set."""
        assert self.agent.running is True

    def test_running_property_false_when_stop_event_set(self):
        """running property must return False after stop_event is set."""
        self.agent._stop_event.set()
        assert self.agent.running is False

    def test_lag_threshold_messages_returns_positive_int(self):
        """lag_threshold_messages must return a positive integer."""
        threshold = self.agent.lag_threshold_messages
        assert isinstance(threshold, int)
        assert threshold > 0

    @pytest.mark.asyncio
    async def test_lifecycle_methods_are_coroutines(self):
        """_setup, _run, and _teardown must all be awaitable coroutines."""
        assert asyncio.iscoroutinefunction(self.agent._setup)
        assert asyncio.iscoroutinefunction(self.agent._run)
        assert asyncio.iscoroutinefunction(self.agent._teardown)
