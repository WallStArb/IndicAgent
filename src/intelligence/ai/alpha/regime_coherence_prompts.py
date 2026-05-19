"""regime_coherence_prompts.py -- versioned prompt registry for RegimeCoherenceComputeAgent.

Per D-05: regime_coherence_v1 assesses whether the I7 winner setup TYPE is appropriate
for the current HMM regime + trend regime.
Per D-16: render_full_context iterates AIContext.model_fields -- open-ended, future-proof.
"""

from __future__ import annotations

from typing import Any

from src.core.ai.context import render_full_context
from src.core.ai.prompt_utils import DIRECTION_LABELS, fmt

ACTIVE_VERSION = "regime_coherence_v1"

PROMPT_REGISTRY: dict[str, str] = {
    "regime_coherence_v1": """You are a regime-coherence analyst. Decide whether the setup TYPE \
(momentum / mean-reversion / breakout / SMC) is appropriate for the current HMM regime \
and trend regime.

SIGNAL CONTEXT:
- Symbol: {symbol}
- Timeframe: {timeframe}
- Setup: {winner_plugin} ({winner_direction_label}, confidence {winner_confidence})

FULL TYPED CONTEXT (every non-None tier from the intelligence pipeline.
null entries indicate the upstream plugin did not produce a value for this bar):

{full_context_block}

TASK: Evaluate whether the setup TYPE matches the current regime. Consider:
- Does a mean-reversion setup fire in a strongly trending regime?
- Does a trend-following setup fire in a ranging / choppy regime?
- Are SMC setups supported by HMM/BOCPD regime state?
- Do CTF alignment scores support or conflict with the setup type?

Semantics:
- regime_fit=1.0 means the setup TYPE matches the regime perfectly.
- regime_fit=0.0 means it strongly mismatches the current regime.
- mismatches is a list of short label strings describing each detected conflict.

Begin your response with {{ and end with }}. No prose before or after the JSON:
{{
    "regime_fit": <float 0.0-1.0>,
    "confidence": <float 0.0-1.0>,
    "mismatches": ["<label1>", "<label2>"],
    "reasoning": "<one short sentence>"
}}

Rules:
- regime_fit and confidence must be floats in [0.0, 1.0]
- mismatches can be an empty list if no conflicts detected
- reasoning must be one short sentence summarising your judgement
""",
}


def build_regime_coherence_prompt(ctx: Any) -> str:
    """Build the regime coherence prompt.

    Requires typed AIContext (v1 only — no legacy dict path).
    """
    from src.core.ai.context import AIContext

    if not isinstance(ctx, AIContext):
        raise TypeError(
            "build_regime_coherence_prompt requires AIContext, got " f"{type(ctx).__name__}"
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
