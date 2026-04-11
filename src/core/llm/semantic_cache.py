"""SemanticCache — LRU + TTL cache for LLM responses.

Key: SHA-256(system_prompt + prompt[:200] + model).
TTL is configurable per call_type (set at put() time by LLMProviderChain).
Thread-safe (asyncio single-thread assumption — no locks needed).
"""
from __future__ import annotations

import hashlib
import time
from collections import OrderedDict


class SemanticCache:
    """LRU cache with per-entry TTL for LLM responses."""

    def __init__(self, max_size: int = 500) -> None:
        self._max_size = max_size
        # OrderedDict as LRU: oldest entry at front
        self._store: OrderedDict[str, tuple[str, float]] = OrderedDict()

    def _key(self, system: str, prompt: str, model: str) -> str:
        raw = f"{system}|{prompt[:200]}|{model}"
        return hashlib.sha256(raw.encode()).hexdigest()

    def get(self, system: str, prompt: str, model: str) -> str | None:
        """Return cached response or None if miss/expired."""
        key = self._key(system, prompt, model)
        entry = self._store.get(key)
        if entry is None:
            return None
        response, expires_at = entry
        if time.monotonic() > expires_at:
            del self._store[key]
            return None
        # Move to end (most recently used)
        self._store.move_to_end(key)
        return response

    def put(self, system: str, prompt: str, model: str, response: str, ttl: float) -> None:
        """Store response with TTL in seconds."""
        key = self._key(system, prompt, model)
        expires_at = time.monotonic() + ttl
        if key in self._store:
            self._store.move_to_end(key)
        self._store[key] = (response, expires_at)
        # Evict LRU entries if over capacity
        while len(self._store) > self._max_size:
            self._store.popitem(last=False)

    def size(self) -> int:
        return len(self._store)
