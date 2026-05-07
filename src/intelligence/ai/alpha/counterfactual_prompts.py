"""counterfactual_prompts.py -- versioned prompt registry for CounterfactualAgentComputeAgent.

Per D-03: prompt version tracked in every alpha_multiplier_shadow row via features JSONB.
Per D-16: render_full_context iterates AIContext.model_fields -- open-ended, future-proof.
Phase 80 D-06: counterfactual reasoning -- validation/invalidation conditions.
"""

from __future__ import annotations

from src.core.ai.context import AIContext, render_full_context
from src.core.ai.prompt_utils import DIRECTION_LABELS, fmt

ACTIVE_VERSION = "counterfactual_v1"

PROMPT_REGISTRY: dict[str, str] = {
    "counterfactual_v1": """You are a counterfactual reasoning analyst. Given the I7 winner signal, list what conditions must hold for it to succeed (validation_conditions) and what would invalidate it (invalidation_conditions), then judge how plausible each set is given the current pipeline context.

SIGNAL CONTEXT:
- Symbol: {symbol}
- Timeframe: {timeframe}
- Setup: {winner_plugin} ({winner_direction_label}, confidence {winner_confidence})

FULL TYPED CONTEXT (every non-None tier from the intelligence pipeline.
null entries indicate the upstream plugin did not produce a value for this bar):

{full_context_block}

TASK: Reason counterfactually about this signal.
1. List the conditions that MUST hold for the signal to succeed (validation_conditions).
2. List the conditions that would INVALIDATE or negate the signal (invalidation_conditions).
3. Judge the overall plausibility: are the validation conditions likely AND the invalidation conditions unlikely?

Definitions:
- plausibility=1.0 means validation conditions are highly likely AND invalidation conditions are unlikely.
- plausibility=0.0 means the opposite: validation conditions are unlikely or invalidation conditions are likely.
- confidence = how certain you are in your plausibility assessment given the data available.

Respond with JSON ONLY:
{{
    "plausibility": <float 0.0-1.0>,
    "confidence": <float 0.0-1.0>,
    "validation_conditions": ["<short clause>", "<short clause>"],
    "invalidation_conditions": ["<short clause>", "<short clause>"],
    "reasoning": "<one short sentence>"
}}
""",
}


def build_counterfactual_prompt(ctx: AIContext) -> str:
    """Build the counterfactual prompt from a typed AIContext.

    Raises TypeError if ctx is not an AIContext instance.
    """
    if not isinstance(ctx, AIContext):
        raise TypeError(
            "build_counterfactual_prompt requires AIContext, got " f"{type(ctx).__name__}"
        )

    template = PROMPT_REGISTRY[ACTIVE_VERSION]
    i7 = ctx.i7
    return template.format(
        symbol=ctx.symbol,
        timeframe=ctx.timeframe,
        winner_plugin=(i7.winner_plugin if i7 else None) or "unknown",
        winner_direction_label=DIRECTION_LABELS.get(
            (i7.winner_direction if i7 else 0) or 0, "UNKNOWN"
        ),
        winner_confidence=fmt(i7.winner_confidence if i7 else None, ".0%"),
        full_context_block=render_full_context(ctx),
    )
