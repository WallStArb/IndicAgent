"""
src.core.memory — Ring 0 memory subsystem contract layer.

Public surface re-exported here so Wave 2 implementations and Ring 1 clients
import from a single stable path: ``from src.core.memory import Episode, ...``

No DB, Ollama, or Ring 1 imports in this package — Protocols and frozen
dataclasses only. Wave 2 Plans 03-05 implement these contracts.

Feature flag: Settings.agent_memory_enabled (default False, MEM-03 shadow gate).
"""

from __future__ import annotations

from src.core.memory.backends import (
    CalibrationBackend,
    EpisodicBackend,
    Mem0Backend,
    RegimeBackend,
)
from src.core.memory.types import CalibrationStats, Episode, RegimeHistory

__all__ = [
    # Return-type dataclasses
    "Episode",
    "CalibrationStats",
    "RegimeHistory",
    # Backend Protocols
    "EpisodicBackend",
    "CalibrationBackend",
    "RegimeBackend",
    "Mem0Backend",
]
