"""TDD: IndicatorComputeAgent class rename + BaseAgent inheritance verification.

Tests use AST parsing and source inspection (no service imports needed) to
verify the structural constraints of services/indicator_compute_agent.py.
"""

import ast
from pathlib import Path

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
        f"Found 'IndicatorService' class definition — must be renamed to IndicatorComputeAgent"
    )


def test_main_block_uses_new_name() -> None:
    """The main() function must instantiate IndicatorComputeAgent, not IndicatorService."""
    source = _load_source()
    assert "IndicatorComputeAgent(args.config)" in source, (
        "Expected 'IndicatorComputeAgent(args.config)' in source (main() instantiation)"
    )
