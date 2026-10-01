"""JSON over HTTP for batch fetches from external APIs.

One GET returning parsed JSON, with retries on transport errors, server errors (5xx) and rate
limiting (429) through `retry_with_backoff`. Any other client error (4xx) is not retried: it will not
change on a second try.
Callers pass their own `httpx.AsyncClient` so one client, and its connection pool, serves a whole
run. A secret carried in the query string (an API key) is redacted from the error message, and the
exception chain is dropped so the request URL cannot reach a log through a traceback.
"""

from __future__ import annotations

from typing import Any

import httpx

from src.core.retry_utils import retry_with_backoff

__all__ = ["HttpJsonError", "get_json"]


class HttpJsonError(Exception):
    """A request failed after its retries, or returned a client error or invalid JSON."""


class _Retryable(Exception):
    """A 5xx or 429 response: retried."""


async def get_json(
    client: httpx.AsyncClient,
    url: str,
    params: dict[str, str],
    *,
    secret: str = "",
    max_attempts: int = 3,
) -> Any:
    async def once() -> Any:
        response = await client.get(url, params=params)
        if response.status_code >= 500 or response.status_code == 429:
            raise _Retryable(f"HTTP {response.status_code}")
        response.raise_for_status()
        return response.json()

    try:
        return await retry_with_backoff(
            once, max_attempts=max_attempts, retry_on=(httpx.TransportError, _Retryable)
        )
    except Exception as error:
        message = f"{type(error).__name__}: {error}"
        if secret:
            message = message.replace(secret, "<redacted>")
        raise HttpJsonError(message[:200]) from None
