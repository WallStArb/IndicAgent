"""LLM provider abstraction — Anthropic/Z.ai (primary), OpenRouter (secondary), Ollama (fallback).

Usage:
    chain = LLMChain([
        AnthropicProvider("claude-sonnet-4.6", api_key="sk-..."),
        OpenRouterProvider("meta-llama/llama-3.3-70b-instruct:free", api_key="sk-..."),
        OllamaProvider("qwen3.5:9b"),
    ])
    text = await chain.generate(prompt, system, max_tokens=500, timeout=30.0)
    # chain.last_provider_id tells you which provider succeeded
"""
from __future__ import annotations

import json
import urllib.request
from asyncio import to_thread
from typing import Protocol, runtime_checkable

import structlog

logger = structlog.get_logger(__name__)


@runtime_checkable
class LLMProvider(Protocol):
    """Minimal protocol every LLM backend must satisfy."""

    provider_id: str

    async def generate(
        self,
        prompt: str,
        system: str,
        max_tokens: int,
        timeout: float,
    ) -> str | None:
        """Return generated text, or None on failure."""
        ...


class OpenRouterProvider:
    """Calls OpenRouter /api/v1/chat/completions (OpenAI-compatible)."""

    def __init__(
        self,
        model: str,
        api_key: str,
        base_url: str = "https://openrouter.ai/api/v1",
    ) -> None:
        self.model = model
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.provider_id = f"openrouter:{model}"

    async def generate(
        self,
        prompt: str,
        system: str,
        max_tokens: int,
        timeout: float,
    ) -> str | None:
        def _call() -> str | None:
            payload = {
                "model": self.model,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user",   "content": prompt},
                ],
                "max_tokens": max_tokens,
                "stream": False,
            }
            data = json.dumps(payload).encode()
            req = urllib.request.Request(
                f"{self.base_url}/chat/completions",
                data=data,
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {self.api_key}",
                },
            )
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                result = json.loads(resp.read())
            choices = result.get("choices") or []
            if not choices:
                return None
            return choices[0].get("message", {}).get("content", "").strip() or None

        try:
            return await to_thread(_call)
        except Exception as exc:
            logger.warning("OpenRouter call failed", model=self.model, error=str(exc))
            return None


class AnthropicProvider:
    """Calls Anthropic API v1/messages (supports Z.ai proxy)."""

    ANTHROPIC_VERSION = "2023-06-01"

    def __init__(
        self,
        model: str,
        api_key: str,
        base_url: str = "https://api.anthropic.com",
    ) -> None:
        self.model = model
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.provider_id = f"anthropic:{model}"

    async def generate(
        self,
        prompt: str,
        system: str,
        max_tokens: int,
        timeout: float,
    ) -> str | None:
        def _call() -> str | None:
            payload = {
                "model": self.model,
                "max_tokens": max_tokens,
                "system": system,
                "messages": [
                    {"role": "user", "content": prompt},
                ],
            }
            data = json.dumps(payload).encode()
            req = urllib.request.Request(
                f"{self.base_url}/v1/messages",
                data=data,
                headers={
                    "Content-Type": "application/json",
                    "x-api-key": self.api_key,
                    "anthropic-version": self.ANTHROPIC_VERSION,
                },
            )
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                result = json.loads(resp.read())
            content_block = result.get("content", [])
            if not content_block:
                return None
            return content_block[0].get("text", "").strip() or None

        try:
            return await to_thread(_call)
        except Exception as exc:
            logger.warning("Anthropic call failed", model=self.model, error=str(exc))
            return None


class ZAIProvider:
    """Calls Z.ai API (OpenAI-compatible) with GLM-5 model.

    Z.ai provides GLM-5, a SOTA foundation model for agentic engineering.
    API: https://api.z.ai/api/paas/v4/chat/completions

    Usage:
        provider = ZAIProvider(model="glm-5", api_key="your-api-key")
        text = await provider.generate(prompt, system, max_tokens=500, timeout=30.0)
    """

    def __init__(
        self,
        model: str = "glm-5",
        api_key: str = "",
        base_url: str = "https://api.z.ai/api/paas/v4",
        timeout: float = 30.0,
    ) -> None:
        self.model = model
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.provider_id = f"zai:{model}"

    async def generate(
        self,
        prompt: str,
        system: str,
        max_tokens: int,
        timeout: float,
    ) -> str | None:
        """Return generated text, or None on failure."""

        def _call() -> str | None:
            payload = {
                "model": self.model,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": prompt},
                ],
                "max_tokens": max_tokens,
                "stream": False,
            }
            data = json.dumps(payload).encode()
            req = urllib.request.Request(
                f"{self.base_url}/chat/completions",
                data=data,
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {self.api_key}",
                },
            )
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                result = json.loads(resp.read())
            choices = result.get("choices") or []
            if not choices:
                return None
            return choices[0].get("message", {}).get("content", "").strip() or None

        try:
            return await to_thread(_call)
        except Exception as exc:
            logger.warning("ZAI call failed", model=self.model, error=str(exc))
            return None


class OllamaProvider:
    """Calls local Ollama /api/chat."""

    def __init__(
        self,
        model: str,
        base_url: str = "http://localhost:11434",
    ) -> None:
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.provider_id = f"ollama:{model}"

    async def generate(
        self,
        prompt: str,
        system: str,
        max_tokens: int,
        timeout: float,
    ) -> str | None:
        def _call() -> str | None:
            payload = {
                "model": self.model,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user",   "content": prompt},
                ],
                "stream": False,
                "options": {"num_predict": max_tokens},
            }
            data = json.dumps(payload).encode()
            req = urllib.request.Request(
                f"{self.base_url}/api/chat",
                data=data,
                headers={"Content-Type": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                result = json.loads(resp.read())
            return result.get("message", {}).get("content", "").strip() or None

        try:
            return await to_thread(_call)
        except Exception as exc:
            logger.warning("Ollama call failed", model=self.model, error=str(exc))
            return None


class LLMChain:
    """Try each provider in order; return first non-None result."""

    def __init__(self, providers: list[LLMProvider]) -> None:
        self.providers = providers
        self.last_provider_id: str | None = None

    async def generate(
        self,
        prompt: str,
        system: str,
        max_tokens: int,
        timeout: float,
    ) -> str | None:
        for provider in self.providers:
            result = await provider.generate(prompt, system, max_tokens, timeout)
            if result is not None:
                self.last_provider_id = provider.provider_id
                return result
        self.last_provider_id = None
        return None
