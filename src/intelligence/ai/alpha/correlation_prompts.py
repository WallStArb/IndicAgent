"""correlation_prompts.py -- versioned prompt registry for CorrelationAgent.

Per D-04: prompt version tracked in every alpha_multiplier_shadow row via features JSONB.
Per D-16: render_full_context iterates AIContext.model_fields -- open-ended, future-proof.
ACTIVE_VERSION = "correlation_v1" matches agent_id per D-04.
"""

from __future__ import annotations

from typing import Any

from src.core.ai.context import render_full_context
from src.core.ai.prompt_utils import DIRECTION_LABELS, fmt

ACTIVE_VERSION = "correlation_v1"

PROMPT_REGISTRY: dict[str, str] = {
    "correlation_v1": """You are a cross-asset coherence analyst evaluating whether intermarket behavior supports or contradicts a trading signal.

SIGNAL CONTEXT:
- Symbol: {symbol}
- Timeframe: {timeframe}
- Setup: {winner_plugin} ({winner_direction_label}, confidence {winner_confidence})

FULL TYPED CONTEXT (every non-None tier from the intelligence pipeline.
null entries indicate the upstream plugin did not produce a value for this bar):

{full_context_block}

TASK: Evaluate whether the cross-asset environment (ZN, VIX, ES, CL) supports or contradicts this signal.

Consider:
- ZN (bonds): rising ZN = risk-off; falling ZN = risk-on
- VIX (volatility): elevated/rising VIX = risk-off, caution for longs
- ES (S&P 500): broad market trend direction alignment or divergence
- CL (crude oil): inflation/risk appetite proxy

coherence_score semantics:
- 1.0 = cross-asset behavior strongly supports the signal direction
- 0.5 = neutral / mixed intermarket signals
- 0.0 = cross-asset behavior directly contradicts the signal direction

Begin your response with {{ and end with }}. No prose before or after the JSON:
{{
    "coherence_score": <float 0.0-1.0>,
    "confidence": <float 0.0-1.0>,
    "contradicting_assets": ["<symbol1>", "<symbol2>"],
    "reasoning": "<one short sentence>"
}}

Rules:
- coherence_score and confidence must be in [0.0, 1.0]
- contradicting_assets is an array of asset symbols that are diverging (empty array if none)
- reasoning must be one sentence explaining the intermarket stance
"""
}


def build_correlation_prompt(ctx: Any) -> str:
    """Build the correlation prompt for CorrelationComputeAgent.

    ctx must be a typed AIContext object (correlation_v1 path).
    Raises TypeError if ctx is not an AIContext.
    """
    from src.core.ai.context import AIContext

    if not isinstance(ctx, AIContext):
        raise TypeError(f"correlation_v1 requires AIContext, got {type(ctx).__name__}")
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
