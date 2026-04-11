from collections.abc import Callable, Coroutine
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import structlog
from pydantic import ValidationError

from src.intelligence.schemas import MAX_MULTIPLIER, MIN_MULTIPLIER, AlphaMultiplier

logger = structlog.get_logger(__name__)

# Nil UUID for fallback (should never be used in production)
NIL_UUID = UUID(int=0)


class SafeSwarmWrapper:
    """Defensive wrapper to enforce safety guardrails and schema validation for Swarm agents."""

    def __init__(self, agent_func: Callable[..., Coroutine[Any, Any, AlphaMultiplier]]):
        self.agent_func = agent_func

    async def __call__(self, *args, **kwargs) -> AlphaMultiplier:
        try:
            # 1. Execute Agent Logic
            result = await self.agent_func(*args, **kwargs)

            # 2. Heuristic Sanity Check (Soft-Shell)
            if not (MIN_MULTIPLIER <= result.final_alpha_multiplier <= MAX_MULTIPLIER):
                logger.error(
                    "Safety Violation: Agent returned multiplier out of safe bounds. agent_output=%s signal_id=%s",
                    result.final_alpha_multiplier,
                    str(result.signal_id),
                )
                return self._default_neutral_response(result.signal_id, "Out of bounds multiplier.")

            return result

        except ValidationError as ve:
            logger.error("Safety Violation: Agent returned invalid schema: %s", ve)
            return self._default_neutral_response(None, "Schema validation error.")
        except Exception as e:
            logger.error("Safety Violation: Unhandled agent error: %s", e, exc_info=True)
            return self._default_neutral_response(None, "Execution error.")

    def _default_neutral_response(self, signal_id: Any, error_msg: str) -> AlphaMultiplier:
        """Fallback for failed agent calls. Returns neutral multiplier (1.0 = no adjustment)."""
        logger.error("swarm_fallback", signal_id=str(signal_id), error=error_msg)
        return AlphaMultiplier(
            signal_id=signal_id or NIL_UUID,
            ts=datetime.now(UTC),
            path="deterministic",
            contributors={},
            final_alpha_multiplier=1.0,
        )
