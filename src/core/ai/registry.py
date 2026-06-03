"""Agent Registry: YAML-driven agent instantiation for swarm coordinators.

Operators add or reconfigure agents by editing config/agents.yaml and restarting.
No Python file changes, no deployment, no code review required for agent config changes.

Core components:
- AgentSpec: Pydantic validation of YAML entries
- _REGISTRY: Module-level dict of agent_id -> agent class (populated by __init_subclass__)
- AgentRegistry.build: Constructs agents from YAML, validates, applies overrides
- RegistryError / RegistryConfigError: Exception classes

Ring 0: No runtime imports from Ring 1 except via TYPE_CHECKING.
"""

from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import TYPE_CHECKING

import yaml
from pydantic import BaseModel, ConfigDict, ValidationError, field_validator

if TYPE_CHECKING:
    from src.core.ai.agent_dependencies import AgentDependencies
    from src.core.ai.base_agent import BaseAIWorker


# Module-level mutable global. Population happens at import time under the
# CPython import lock + GIL; the single-process-per-swarm deployment model
# means no true parallel mutation. Treated read-only after _import_all().
_REGISTRY: dict[str, type[BaseAIWorker]] = {}

# Deterministic path resolution from repo root, not CWD.
# registry.py is at src/core/ai/registry.py -> parents[3] is repo root.
_REPO_ROOT = Path(__file__).resolve().parents[3]
_DEFAULT_YAML = _REPO_ROOT / "config" / "agents.yaml"


class RegistryError(Exception):
    """Raised when an agent_id is not in _REGISTRY."""


class RegistryConfigError(Exception):
    """Raised when agents.yaml is missing, malformed, or fails validation."""


class AgentSpec(BaseModel):
    """Pydantic validation model for a single YAML agent entry.

    Required fields:
        agent_id: The unique identifier (must match a class attribute)

    Optional fields (fall back to class attribute when absent):
        shadow_only: default: class attr (always True for new agents). YAML can
            set True but CANNOT force False — shadow_registry DB has final authority.
        latency_budget_ms: default: class attr (operational tuning)
        prompt_version: default: class ACTIVE_VERSION (A/B test pinning)
        model_override: default: OLLAMA_MODEL env var (per-agent override)
    """

    model_config = ConfigDict(extra="forbid")

    agent_id: str
    shadow_only: bool | None = None
    latency_budget_ms: float | None = None
    prompt_version: str | None = None
    model_override: str | None = None

    @field_validator("shadow_only")
    @classmethod
    def _reject_force_production(cls, v: bool | None) -> bool | None:
        """Reject shadow_only: false in YAML.

        Production promotion requires the statistical gate in shadow_registry.
        Operators can shadow agents (true) but cannot force production (false).
        """
        if v is False:
            raise ValueError(
                "shadow_only: false is rejected in agents.yaml — "
                "production promotion requires the statistical gate in shadow_registry"
            )
        return v


def _load_specs(group: str, yaml_path: Path | None = None) -> list[AgentSpec]:
    """Load and validate AgentSpec entries from agents.yaml for a group.

    Args:
        group: The YAML section key (e.g., "alpha", "narrative", "risk")
        yaml_path: Optional override path (defaults to config/agents.yaml at repo root)

    Returns:
        List of validated AgentSpec objects (empty if group missing or empty)

    Raises:
        RegistryConfigError: If YAML file missing, malformed, or validation fails
    """
    path = yaml_path or _DEFAULT_YAML
    if not path.exists():
        raise RegistryConfigError(f"agents.yaml not found at {path}")

    try:
        with open(path, encoding="utf-8") as f:
            raw = yaml.safe_load(f) or {}
    except yaml.YAMLError as exc:
        raise RegistryConfigError(f"Failed to parse agents.yaml: {exc}") from exc

    group_entries = raw.get(group, [])
    if not group_entries:
        return []

    specs = []
    for entry in group_entries:
        try:
            specs.append(AgentSpec.model_validate(entry))
        except ValidationError as exc:
            raise RegistryConfigError(f"Invalid agent spec in group '{group}': {exc}") from exc

    # Duplicate agent_id detection (consensus concern 3)
    agent_ids = [s.agent_id for s in specs]
    duplicates = [aid for aid, count in Counter(agent_ids).items() if count > 1]
    if duplicates:
        raise RegistryConfigError(
            f"Duplicate agent_id(s) in group '{group}': {sorted(duplicates)} "
            "— each agent_id may appear at most once per group"
        )

    return specs


class AgentRegistry:
    """Registry-driven agent construction for swarm coordinators.

    Provides:
    - validate(): Check that all agent_ids in specs are known to _REGISTRY
    - build(): Construct agent instances from specs, apply YAML overrides,
      cross-check group placement, and return the list

    The registry is populated at import time by BaseAIWorker.__init_subclass__.
    Operators edit config/agents.yaml and restart to reconfigure agents.
    """

    @staticmethod
    def validate(group: str, specs: list[AgentSpec]) -> None:
        """Validate that all agent_ids in specs are registered.

        Returns early (no raise) when specs is empty — this allows the
        scaffolded 'risk: []' group to be inert. Empty-group policy for
        active groups (alpha, narrative) is enforced by the caller in
        BaseGroupCoordinator._setup, not here.

        Args:
            group: The group name for error messages
            specs: List of AgentSpec objects to validate

        Raises:
            RegistryConfigError: If any agent_id is not in _REGISTRY
        """
        if not specs:
            return

        unknown = [s.agent_id for s in specs if s.agent_id not in _REGISTRY]
        if unknown:
            raise RegistryConfigError(
                f"Unknown agent_id(s) in group '{group}': {unknown}. " f"Known: {sorted(_REGISTRY)}"
            )

    @staticmethod
    def build(group: str, agent_dependencies: AgentDependencies) -> list[BaseAIWorker]:
        """Construct agent instances from YAML specs for a group.

        Steps:
        1. Load specs from agents.yaml via _load_specs
        2. Validate all agent_ids are known
        3. For each spec: resolve class, cross-check group, construct instance,
           apply YAML overrides (shadow_only, latency_budget_ms, prompt_version)

        Args:
            group: The YAML section key (e.g., "alpha", "narrative")
            agent_dependencies: The dependency container (llm_chain, pool, settings)

        Returns:
            List of constructed agent instances

        Raises:
            RegistryConfigError: On unknown agent_id, group mismatch, or load failure
        """
        specs = _load_specs(group)
        AgentRegistry.validate(group, specs)

        agents = []
        for spec in specs:
            cls = _REGISTRY[spec.agent_id]

            # Cross-check: class.group must match the requested group (consensus concern 4)
            if cls.group != group:
                raise RegistryConfigError(
                    f"Agent '{spec.agent_id}' (class {cls.__name__}) declares group "
                    f"'{cls.group}' but is listed under group '{group}' in agents.yaml"
                )

            # Construct via the unified dependencies signature
            agent = cls(dependencies=agent_dependencies)

            # Apply YAML overrides when present (None means use class default)
            if spec.shadow_only is not None:
                agent.shadow_only = spec.shadow_only
            if spec.latency_budget_ms is not None:
                agent.latency_budget_ms = spec.latency_budget_ms
                agent._timeout_s = spec.latency_budget_ms / 1000.0
            if spec.prompt_version is not None:
                agent.prompt_version = spec.prompt_version

            agents.append(agent)

        return agents
