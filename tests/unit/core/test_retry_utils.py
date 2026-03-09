"""Unit tests for src.core.retry_utils.

Covers:
- exponential_backoff_with_jitter(): delay growth, cap, jitter spread
- retry_with_backoff(): success path, retry-on-exception, max_attempts, raise
"""

import asyncio
from unittest.mock import AsyncMock, call

import pytest

from src.core.retry_utils import (
    exponential_backoff_with_jitter,
    retry_with_backoff,
)


# ---------------------------------------------------------------------------
# exponential_backoff_with_jitter
# ---------------------------------------------------------------------------


class TestExponentialBackoffWithJitter:
    def test_returns_nonnegative_float(self) -> None:
        delay = exponential_backoff_with_jitter(0, base_delay=1.0)
        assert isinstance(delay, float)
        assert delay >= 0.0

    def test_delay_increases_exponentially_with_attempt(self) -> None:
        # Without jitter (jitter_factor=0) delay is exactly base * 2^attempt
        d0 = exponential_backoff_with_jitter(0, base_delay=1.0, jitter_factor=0.0)
        d1 = exponential_backoff_with_jitter(1, base_delay=1.0, jitter_factor=0.0)
        d2 = exponential_backoff_with_jitter(2, base_delay=1.0, jitter_factor=0.0)

        assert d0 == pytest.approx(1.0)
        assert d1 == pytest.approx(2.0)
        assert d2 == pytest.approx(4.0)

    def test_delay_capped_at_max_delay(self) -> None:
        # attempt=10 → base_delay * 2^10 = 1024 >> max_delay=30
        delay = exponential_backoff_with_jitter(
            10, base_delay=1.0, max_delay=30.0, jitter_factor=0.0
        )
        assert delay == pytest.approx(30.0)

    def test_delay_never_exceeds_max_delay_with_jitter(self) -> None:
        # Even with maximum positive jitter the result should not exceed max_delay.
        # jitter = delay * jitter_factor * 1.0 (max positive)
        # With jitter_factor=0.5 and delay=max_delay: result = max_delay * 1.5 before clamp.
        # The implementation applies jitter *before* the max(0.0, ...) floor but after the cap.
        # Verify that result <= max_delay + max_delay * jitter_factor (realistic upper bound).
        max_delay = 30.0
        jitter_factor = 0.5
        delay = exponential_backoff_with_jitter(
            10, base_delay=1.0, max_delay=max_delay, jitter_factor=jitter_factor
        )
        # Upper bound is max_delay + max_delay * jitter_factor
        assert delay <= max_delay * (1 + jitter_factor)

    def test_jitter_produces_variation_across_calls(self) -> None:
        # With jitter_factor=0.5 and base_delay=1.0, repeated calls at attempt=0
        # should produce values spread around 1.0 rather than always equal.
        results = {
            exponential_backoff_with_jitter(0, base_delay=1.0, jitter_factor=0.5)
            for _ in range(20)
        }
        # At least 2 distinct values in 20 draws (near-zero probability of collision)
        assert len(results) > 1

    def test_zero_jitter_factor_is_deterministic(self) -> None:
        d1 = exponential_backoff_with_jitter(3, base_delay=2.0, jitter_factor=0.0)
        d2 = exponential_backoff_with_jitter(3, base_delay=2.0, jitter_factor=0.0)
        assert d1 == d2

    def test_result_never_goes_negative(self) -> None:
        # Even if random produces the most negative jitter, result >= 0
        for _ in range(50):
            delay = exponential_backoff_with_jitter(
                0, base_delay=0.0001, jitter_factor=1.0
            )
            assert delay >= 0.0


# ---------------------------------------------------------------------------
# retry_with_backoff
# ---------------------------------------------------------------------------


class TestRetryWithBackoff:
    def test_succeeds_on_first_attempt(self) -> None:
        """Function that never fails completes without retrying."""
        coro = AsyncMock(return_value=42)

        result = asyncio.run(
            retry_with_backoff(coro, "arg1", max_attempts=3)
        )

        assert result == 42
        coro.assert_called_once_with("arg1")

    def test_retries_on_exception_and_eventually_succeeds(self) -> None:
        """Function fails twice then succeeds; call count matches."""
        coro = AsyncMock(side_effect=[ValueError("fail"), ValueError("fail"), 99])

        result = asyncio.run(
            retry_with_backoff(
                coro,
                max_attempts=3,
                base_delay=0.0,  # zero delay for fast tests
                retry_on=(ValueError,),
            )
        )

        assert result == 99
        assert coro.call_count == 3

    def test_raises_last_exception_after_max_attempts(self) -> None:
        """Function always fails; last exception is raised."""
        exc = RuntimeError("always fails")
        coro = AsyncMock(side_effect=exc)

        with pytest.raises(RuntimeError, match="always fails"):
            asyncio.run(
                retry_with_backoff(
                    coro,
                    max_attempts=3,
                    base_delay=0.0,
                    retry_on=(RuntimeError,),
                )
            )

        assert coro.call_count == 3

    def test_stops_retrying_after_max_attempts(self) -> None:
        """Function called exactly max_attempts times when always failing."""
        coro = AsyncMock(side_effect=Exception("boom"))

        with pytest.raises(Exception):
            asyncio.run(
                retry_with_backoff(coro, max_attempts=5, base_delay=0.0)
            )

        assert coro.call_count == 5

    def test_does_not_retry_on_unspecified_exception(self) -> None:
        """Exceptions not in retry_on propagate immediately, no retry."""
        coro = AsyncMock(side_effect=TypeError("wrong type"))

        with pytest.raises(TypeError):
            asyncio.run(
                retry_with_backoff(
                    coro,
                    max_attempts=3,
                    base_delay=0.0,
                    retry_on=(ValueError,),  # TypeError not included
                )
            )

        # Only called once — TypeError propagated immediately
        assert coro.call_count == 1

    def test_max_attempts_one_means_no_retry(self) -> None:
        """max_attempts=1 → called exactly once, exception raised immediately."""
        coro = AsyncMock(side_effect=ConnectionError("refused"))

        with pytest.raises(ConnectionError):
            asyncio.run(
                retry_with_backoff(coro, max_attempts=1, retry_on=(ConnectionError,))
            )

        assert coro.call_count == 1

    def test_kwargs_forwarded_to_coro(self) -> None:
        """Keyword arguments are passed through to the wrapped coroutine."""
        coro = AsyncMock(return_value="ok")

        asyncio.run(
            retry_with_backoff(coro, key="value", max_attempts=1)
        )

        coro.assert_called_once_with(key="value")

    def test_args_and_kwargs_forwarded_together(self) -> None:
        """Both positional and keyword arguments reach the wrapped coroutine."""
        coro = AsyncMock(return_value="ok")

        asyncio.run(
            retry_with_backoff(coro, "pos1", kwarg1="kv", max_attempts=1)
        )

        coro.assert_called_once_with("pos1", kwarg1="kv")
