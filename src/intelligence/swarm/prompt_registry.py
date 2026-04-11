"""PromptRegistry — bounded template registry for LLM swarm agents.

All LLM agents must fetch prompts from here — never build from raw market data f-strings.
This prevents prompt injection from malformed OHLCV values.
"""
from __future__ import annotations


class PromptRegistry:
    """Registry of LLM prompt templates by name."""

    def __init__(self) -> None:
        self._templates: dict[str, str] = {}

    def register(self, name: str, template: str) -> None:
        """Register a named prompt template."""
        self._templates[name] = template

    def render(self, template_name: str, **kwargs) -> str:
        """Render a template by name with the provided kwargs.

        Raises KeyError if template not registered.
        Uses str.format_map() — only substitutes named placeholders.
        Template variables may use any key name including 'name'.
        """
        template = self._templates[template_name]
        # format_map safely substitutes only named keys — no f-string injection risk
        return template.format_map(kwargs)

    def names(self) -> list[str]:
        return list(self._templates.keys())
