"""src.core.agent — BaseAgent, BaseWriterAgent, and ProcessManifest package."""

from src.core.agent.base import BaseAgent
from src.core.agent.base_writer import BaseWriterAgent
from src.core.agent.manifest import ProcessManifest

__all__ = ["BaseAgent", "BaseWriterAgent", "ProcessManifest"]
