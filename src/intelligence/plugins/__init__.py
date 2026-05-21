"""Plugin infrastructure package.

Re-exports all public names from base.py for backward compatibility.
Existing code using ``from src.intelligence.plugins import InputSpec`` continues
to work unchanged.
"""

from src.intelligence.plugins.base import (
    IndicatorPlugin,
    InputSpec,
    PatternPlugin,
    PluginRegistry,
    registry,
)

__all__ = [
    "InputSpec",
    "IndicatorPlugin",
    "PatternPlugin",
    "PluginRegistry",
    "registry",
]
