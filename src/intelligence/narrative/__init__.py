"""Narrative intelligence module — prompt building, parsing, orchestration.

Pure functions in prompts.py and parsers.py have no I/O dependencies.
NarrativeOrchestrator requires LLMProviderChain from src.core.llm (Plan 56-01).
"""

from src.intelligence.narrative.orchestrator import NarrativeOrchestrator
from src.intelligence.narrative.parsers import parse_bar_intelligence_record
from src.intelligence.narrative.prompts import build_deep_prompt, build_short_prompt

__all__ = [
    "NarrativeOrchestrator",
    "build_short_prompt",
    "build_deep_prompt",
    "parse_bar_intelligence_record",
]
