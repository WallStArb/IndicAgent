"""Shared LLM provider infrastructure — moved from src/intelligence/llm_providers.py (Phase 56-01).

Usage:
    from src.core.llm import LLMProviderChain

    chain = LLMProviderChain(call_type="narrative")
    text = await chain.generate(prompt, system, max_tokens=500, timeout=30.0)
"""
from src.core.llm.providers import LLMChain, LLMProvider, OllamaProvider, OpenRouterProvider, ZAIProvider
from src.core.llm.chain import LLMProviderChain

__all__ = [
    "LLMChain",
    "LLMProvider",
    "OllamaProvider",
    "OpenRouterProvider",
    "ZAIProvider",
    "LLMProviderChain",
]
