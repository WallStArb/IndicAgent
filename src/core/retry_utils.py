"""Retry utilities with exponential backoff and jitter.

Implements the Renaissance principle "degrade gracefully, adapt automatically":
when external APIs fail, retry with increasing delays spread across a time
window (jitter) to prevent thundering herd — concurrent processes all hitting
the same endpoint simultaneously after a transient failure.

Usage::

    from src.core.retry_utils import retry_with_backoff

    result = await retry_with_backoff(
        my_async_fn, arg1, arg2,
        max_attempts=3,
        retry_on=(ConnectionError, TimeoutError),
    )
"""

import asyncio
import random
from collections.abc import Callable
from typing import Any

__all__ = ["exponential_backoff_with_jitter", "retry_with_backoff"]


def exponential_backoff_with_jitter(
    attempt: int,
    base_delay: float = 1.0,
    max_delay: float = 30.0,
    jitter_factor: float = 0.5,
) -> float:
    """Calculate exponential backoff delay with jitter.

    Args:
        attempt: Current retry attempt (0-indexed).
        base_delay: Base delay in seconds (default: 1.0s).
        max_delay: Maximum delay cap in seconds (default: 30.0s).
        jitter_factor: Jitter as a fraction of the computed delay
            (default: 0.5 = ±50%).  Must be in [0.0, 1.0].

    Returns:
        Delay in seconds with jitter applied, clamped to [0.0, max_delay].

    Jitter prevents the thundering herd problem: when multiple processes
    retry simultaneously after an external API failure, spreading their
    retry intervals avoids a coordinated spike that would overwhelm the
    recovering service.

    Examples::

        # attempt=0 → ~1.0s  (base_delay * 2^0)
        # attempt=1 → ~2.0s  (base_delay * 2^1)
        # attempt=2 → ~4.0s  (base_delay * 2^2)
        # attempt=10 → capped at max_delay (30.0s by default)
    """
    # Exponential backoff: base_delay * 2^attempt
    delay = base_delay * (2**attempt)

    # Cap at max_delay before applying jitter
    delay = min(delay, max_delay)

    # Add jitter: uniformly distributed in [-jitter_factor, +jitter_factor]
    jitter = delay * jitter_factor * (random.random() * 2 - 1)

    # Ensure delay never goes negative
    return max(0.0, delay + jitter)


async def retry_with_backoff(
    coro_fn: Callable,
    *args: Any,
    max_attempts: int = 3,
    base_delay: float = 1.0,
    max_delay: float = 30.0,
    jitter_factor: float = 0.5,
    retry_on: tuple[type[Exception], ...] = (Exception,),
    **kwargs: Any,
) -> Any:
    """Async retry wrapper with exponential backoff and jitter.

    Retries ``coro_fn`` up to ``max_attempts`` times, sleeping between
    attempts with an exponentially increasing, jitter-spread delay.  On
    the final attempt the caught exception is re-raised so the caller
    receives the real error without it being swallowed.

    Args:
        coro_fn: Async callable to retry.
        *args: Positional arguments forwarded to ``coro_fn``.
        max_attempts: Maximum number of call attempts (default: 3).
            A value of 1 means no retries — the function is called once.
        base_delay: Base delay in seconds between attempts (default: 1.0s).
        max_delay: Maximum delay cap in seconds (default: 30.0s).
        jitter_factor: Jitter fraction applied to computed delay
            (default: 0.5 = ±50%).
        retry_on: Tuple of exception types that trigger a retry.
            Exceptions not in this tuple propagate immediately without
            retrying (default: all ``Exception`` subclasses).
        **kwargs: Keyword arguments forwarded to ``coro_fn``.

    Returns:
        The return value of the first successful ``coro_fn`` call.

    Raises:
        Last exception caught after all ``max_attempts`` are exhausted.

    Examples::

        # Retry up to 5 times, only on connection-related errors
        result = await retry_with_backoff(
            fetch_data, symbol,
            max_attempts=5,
            retry_on=(ConnectionError, TimeoutError),
        )
    """
    last_exception: Exception | None = None

    for attempt in range(max_attempts):
        try:
            return await coro_fn(*args, **kwargs)
        except retry_on as exc:
            last_exception = exc

            if attempt < max_attempts - 1:
                # Not the final attempt — sleep then retry
                delay = exponential_backoff_with_jitter(
                    attempt, base_delay, max_delay, jitter_factor
                )
                await asyncio.sleep(delay)
            else:
                # Final attempt — propagate the exception directly
                raise

    # Unreachable: the loop always either returns or raises.
    # Included to satisfy type checkers.
    if last_exception is not None:
        raise last_exception
    raise RuntimeError("retry_with_backoff exhausted attempts without exception")
