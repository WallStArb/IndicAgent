import logging
from typing import Any, Callable, Coroutine
from uuid import UUID
from pydantic import ValidationError
from src.intelligence.schemas.alpha_multiplier import AlphaMultiplier, MIN_MULTIPLIER, MAX_MULTIPLIER

logger = logging.getLogger(__name__)

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
                    str(result.signal_id)
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
        """Fallback for failed agent calls."""
        return AlphaMultiplier(
            signal_id=signal_id or NIL_UUID,
            agents={},
            final_alpha_multiplier=1.0, # Default to 1.0 (Neutral)
            is_safe=False,
            validation_error=error_msg
        )
