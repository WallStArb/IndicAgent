from typing import Any, Protocol, runtime_checkable

from src.intelligence.schemas.alpha_multiplier import AlphaMultiplier


@runtime_checkable
class IAlphaContributor(Protocol):
    """
    Standard interface for all intelligence contributions to the Signal Lifecycle.
    Ensures decoupled execution between Path A (Deterministic) and Path B (LLM-Swarm).
    """
    async def get_multiplier(self, sid: str, context: dict[str, Any]) -> AlphaMultiplier:
        """
        Compute an alpha multiplier given signal ID and market context.
        Must be thread-safe and non-blocking if possible.
        """
        ...
