"""AgentRegistry — tracks live agents for introspection and health checks.

Singleton: multiple instantiations return the same object via __new__.
Test isolation: reset with ``AgentRegistry._instance = None`` between tests.
"""

from __future__ import annotations

from typing import ClassVar

from src.core.agent.base import BaseAgent


class AgentRegistry:
    """Singleton registry for all live BaseAgent instances.

    Usage::

        registry = AgentRegistry()
        registry.register(my_agent)
        print(registry.list_names())   # ["my_agent"]
        agent = registry.get("my_agent")
    """

    _instance: ClassVar[AgentRegistry | None] = None
    _agents: dict[str, BaseAgent]

    def __new__(cls) -> AgentRegistry:
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._agents = {}
        return cls._instance

    def register(self, agent: BaseAgent) -> None:
        """Register an agent by name. Overwrites any prior registration with the same name."""
        self._agents[agent.name] = agent

    def list_names(self) -> list[str]:
        """Return the names of all registered agents."""
        return list(self._agents.keys())

    def get(self, name: str) -> BaseAgent | None:
        """Return the agent registered under ``name``, or None if not found."""
        return self._agents.get(name)
