"""Explicit agent module imports — trigger __init_subclass__ self-registration.

Analogous to the TIER_I* lists in register_plugins.py.

To add a new agent:
  1. Create the agent class in src/intelligence/ai/<group>/<name>_agent.py
  2. Add the module path to AGENT_MODULES below
  3. Add the entry to config/agents.yaml
  4. Restart the swarm service

No filesystem scanning. Every import here is deliberate and auditable.
"""

from __future__ import annotations

_AGENT_MODULES = [
    "src.intelligence.ai.alpha.skeptic_agent",
    "src.intelligence.ai.alpha.correlation_agent",
    "src.intelligence.ai.alpha.regime_coherence_agent",
    "src.intelligence.ai.alpha.counterfactual_agent",
    "src.intelligence.ai.alpha.ml_scorer_agent",
    "src.intelligence.ai.narrative.narrative_agent",
]


def _import_all() -> None:
    """Import all agent modules to trigger __init_subclass__ registration.

    Called once inside BaseGroupCoordinator._setup() before AgentRegistry.build().
    Lazy import inside _setup() avoids circular imports at module load time.
    """
    import importlib

    for module_path in _AGENT_MODULES:
        importlib.import_module(module_path)


__all__ = ["_AGENT_MODULES", "_import_all"]
