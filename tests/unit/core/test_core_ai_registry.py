"""Unit tests for the agent registry system.

Tests cover:
- AgentSpec validation (extra keys, shadow_only rejection)
- Self-registration via __init_subclass__
- Duplicate agent_id detection (class and YAML)
- Unknown agent_id failure
- Group mismatch detection
- Empty group leniency
- YAML loading and path resolution
"""

from __future__ import annotations

from pathlib import Path

import pytest

from src.core.ai.base_agent import BaseAIWorker
from src.core.ai.registry import (
    _REGISTRY,
    AgentRegistry,
    AgentSpec,
    RegistryConfigError,
    RegistryError,
    _load_specs,
)

# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def clean_registry():
    """Fixture that cleans the registry before and after each test."""
    # Store original registry state
    original = dict(_REGISTRY)
    _REGISTRY.clear()
    yield
    # Restore original state
    _REGISTRY.clear()
    _REGISTRY.update(original)


@pytest.fixture
def test_agent_alpha(clean_registry):
    """Create a test agent in the 'alpha' group."""

    class TestAlphaAgent(BaseAIWorker):
        agent_id = "test_alpha_agent"
        group = "alpha"
        shadow_only = True

    return TestAlphaAgent


@pytest.fixture
def test_agent_narrative(clean_registry):
    """Create a test agent in the 'narrative' group."""

    class TestNarrativeAgent(BaseAIWorker):
        agent_id = "test_narrative_agent"
        group = "narrative"
        shadow_only = True

    return TestNarrativeAgent


# =============================================================================
# AgentSpec Validation Tests
# =============================================================================


def test_agent_spec_with_only_agent_id_is_valid():
    """Test that AgentSpec with only required agent_id field is valid."""
    spec = AgentSpec(agent_id="test_agent")
    assert spec.agent_id == "test_agent"
    assert spec.shadow_only is None
    assert spec.latency_budget_ms is None


def test_agent_spec_with_shadow_only_false_raises_validation_error():
    """Test that shadow_only=False is rejected at validation time."""
    with pytest.raises(ValueError) as exc_info:
        AgentSpec(agent_id="test_agent", shadow_only=False)
    assert "shadow_only: false is rejected" in str(exc_info.value)


def test_agent_spec_with_unknown_key_raises_validation_error():
    """Test that extra='forbid' rejects unknown YAML keys."""
    with pytest.raises(ValueError) as exc_info:
        AgentSpec(agent_id="test_agent", bogus_key=1)
    assert "Extra inputs are not permitted" in str(exc_info.value)


def test_agent_spec_with_shadow_only_true_is_valid():
    """Test that shadow_only=True is accepted."""
    spec = AgentSpec(agent_id="test_agent", shadow_only=True)
    assert spec.shadow_only is True


def test_agent_spec_with_all_optional_fields():
    """Test that all optional fields can be set."""
    spec = AgentSpec(
        agent_id="test_agent",
        shadow_only=True,
        latency_budget_ms=3000.0,
        prompt_version="v2",
        model_override="ollama/gemma4:e4b",
    )
    assert spec.agent_id == "test_agent"
    assert spec.shadow_only is True
    assert spec.latency_budget_ms == 3000.0
    assert spec.prompt_version == "v2"
    assert spec.model_override == "ollama/gemma4:e4b"


# =============================================================================
# Self-Registration Tests
# =============================================================================


def test_base_ai_worker_with_empty_agent_id_does_not_register(clean_registry):
    """Test that BaseAIWorker (agent_id='') does NOT register."""

    class NoRegAgent(BaseAIWorker):
        agent_id = ""
        group = "test"

        async def _compute(self, context):
            from src.core.ai.output import AgentOutput

            return AgentOutput(signal_id="", decision="neutral", confidence=0.0)

    NoRegAgent()
    assert "" not in _REGISTRY


def test_evaluator_does_not_register(clean_registry):
    """Test that Evaluator (agent_id='') does NOT register."""
    from src.core.ai.evaluator import Evaluator

    # Evaluator inherits agent_id="" from BaseAIWorker
    assert Evaluator.agent_id == ""
    assert "" not in _REGISTRY


def test_duplicate_class_agent_id_raises_registry_error(clean_registry):
    """Test that defining two classes with the same non-empty agent_id raises."""

    class DupAgent1(BaseAIWorker):
        agent_id = "duplicate_id"
        group = "alpha"

    with pytest.raises(RegistryError) as exc_info:
        # This should raise during class definition
        class DupAgent2(BaseAIWorker):
            agent_id = "duplicate_id"
            group = "narrative"

    assert "Duplicate agent_id 'duplicate_id'" in str(exc_info.value)
    assert "DupAgent1" in str(exc_info.value)
    assert "DupAgent2" in str(exc_info.value)


def test_concrete_agent_self_registers_on_import(clean_registry):
    """Test that importing a concrete agent registers it in _REGISTRY."""
    # Import the real skeptic agent  # noqa: F401 — import has side-effect of registration
    import src.intelligence.ai.alpha.skeptic_agent  # noqa: F401

    assert "skeptic" in _REGISTRY
    assert _REGISTRY["skeptic"].__name__ == "SkepticEvaluator"


# =============================================================================
# Registry Validation Tests
# =============================================================================


def test_registry_validate_with_unknown_agent_id_raises(clean_registry, test_agent_alpha):
    """Test that AgentRegistry.validate raises on unknown agent_id."""
    specs = [AgentSpec(agent_id="does_not_exist")]
    with pytest.raises(RegistryConfigError) as exc_info:
        AgentRegistry.validate("alpha", specs)
    assert "Unknown agent_id(s)" in str(exc_info.value)
    assert "does_not_exist" in str(exc_info.value)
    # Known IDs should be listed
    assert "test_alpha_agent" in str(exc_info.value)


def test_registry_validate_with_empty_specs_returns_no_raise(clean_registry):
    """Test that AgentRegistry.validate([]) returns without raising."""
    # This allows the scaffolded 'risk: []' group to be inert
    AgentRegistry.validate("alpha", [])


# =============================================================================
# YAML Loading and Duplicate Detection Tests
# =============================================================================


def test_load_specs_from_valid_yaml(tmp_path, clean_registry):
    """Test that _load_specs parses a valid YAML section correctly."""
    yaml_file = tmp_path / "test_agents.yaml"
    yaml_file.write_text("""
alpha:
  - agent_id: agent_a
  - agent_id: agent_b
    shadow_only: true
    latency_budget_ms: 2000
""")

    specs = _load_specs("alpha", yaml_path=yaml_file)
    assert len(specs) == 2
    assert specs[0].agent_id == "agent_a"
    assert specs[1].agent_id == "agent_b"
    assert specs[1].shadow_only is True
    assert specs[1].latency_budget_ms == 2000.0


def test_load_specs_with_duplicate_yaml_agent_id_raises(tmp_path, clean_registry):
    """Test that _load_specs raises on duplicate agent_id in same group."""
    yaml_file = tmp_path / "test_agents.yaml"
    yaml_file.write_text("""
alpha:
  - agent_id: duplicate_agent
  - agent_id: duplicate_agent
""")

    with pytest.raises(RegistryConfigError) as exc_info:
        _load_specs("alpha", yaml_path=yaml_file)
    assert "Duplicate agent_id(s) in group 'alpha'" in str(exc_info.value)
    assert "duplicate_agent" in str(exc_info.value)


def test_load_specs_with_missing_group_returns_empty(tmp_path, clean_registry):
    """Test that _load_specs returns empty list when group missing."""
    yaml_file = tmp_path / "test_agents.yaml"
    yaml_file.write_text("""
narrative:
  - agent_id: agent_n
""")

    specs = _load_specs("alpha", yaml_path=yaml_file)
    assert specs == []


def test_load_specs_with_empty_group_returns_empty(tmp_path, clean_registry):
    """Test that _load_specs returns empty list for empty group."""
    yaml_file = tmp_path / "test_agents.yaml"
    yaml_file.write_text("""
alpha: []
""")

    specs = _load_specs("alpha", yaml_path=yaml_file)
    assert specs == []


def test_load_specs_with_missing_yaml_file_raises(tmp_path, clean_registry):
    """Test that _load_specs raises when YAML file not found."""
    nonexistent = tmp_path / "nonexistent.yaml"
    with pytest.raises(RegistryConfigError) as exc_info:
        _load_specs("alpha", yaml_path=nonexistent)
    assert "agents.yaml not found" in str(exc_info.value)


def test_load_specs_with_invalid_yaml_raises(tmp_path, clean_registry):
    """Test that _load_specs raises on malformed YAML."""
    yaml_file = tmp_path / "test_agents.yaml"
    yaml_file.write_text("invalid: yaml: content: [")

    with pytest.raises(RegistryConfigError) as exc_info:
        _load_specs("alpha", yaml_path=yaml_file)
    assert "Failed to parse agents.yaml" in str(exc_info.value)


# =============================================================================
# Group Mismatch Detection Tests
# =============================================================================


def test_registry_build_with_group_mismatch_raises(clean_registry):
    """Test that AgentRegistry.build raises when class.group != yaml group."""

    class WrongGroupAgent(BaseAIWorker):
        agent_id = "test_wrong_group"
        group = "alpha"  # Declares alpha

    _REGISTRY["test_wrong_group"] = WrongGroupAgent

    # Create a mock YAML that lists this agent under 'narrative'
    yaml_file = Path("/tmp/test_wrong_group.yaml")
    yaml_file.write_text("""
narrative:
  - agent_id: test_wrong_group
""")

    # Mock _load_specs to return our spec
    from src.core.ai import registry

    original_load = registry._load_specs

    def mock_load(group, yaml_path=None):
        if group == "narrative":
            return [AgentSpec(agent_id="test_wrong_group")]
        return original_load(group, yaml_path)

    registry._load_specs = mock_load

    try:
        with pytest.raises(RegistryConfigError) as exc_info:
            # Build should fail because class says 'alpha' but YAML says 'narrative'
            AgentRegistry.build(
                "narrative",
                agent_dependencies=type("AgentDependencies", (), {})(),
            )
        assert "declares group 'alpha' but is listed under group 'narrative'" in str(exc_info.value)
    finally:
        registry._load_specs = original_load


# =============================================================================
# Default YAML Path Resolution Tests
# =============================================================================


def test_default_yaml_path_resolves_from_repo_root():
    """Test that _DEFAULT_YAML points to config/agents.yaml at repo root."""
    from src.core.ai.registry import _DEFAULT_YAML

    assert _DEFAULT_YAML.name == "agents.yaml"
    assert _DEFAULT_YAML.parent.name == "config"
    # Should be an absolute path
    assert _DEFAULT_YAML.is_absolute()
