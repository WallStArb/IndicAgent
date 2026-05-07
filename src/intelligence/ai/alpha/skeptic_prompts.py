"""skeptic_prompts.py -- versioned prompt registry for SkepticAgent.

Per D-03: prompt version tracked in every alpha_multiplier_shadow row via features JSONB.
Per D-16: render_full_context iterates AIContext.model_fields -- open-ended, future-proof.
Per D-17: ACTIVE_VERSION = "skeptic_v2".
"""

from __future__ import annotations

from typing import Any

from src.core.ai.context import render_full_context
from src.core.ai.prompt_utils import DIRECTION_LABELS, fmt

ACTIVE_VERSION = "skeptic_v2"

PROMPT_REGISTRY: dict[str, str] = {
    "skeptic_v1": """You are a skeptical trading analyst reviewing a signal for potential failure.

SIGNAL CONTEXT:
- Symbol: {symbol}
- Timeframe: {timeframe}
- Setup: {winner_plugin} ({winner_direction_label}, confidence {winner_confidence})
- Price: {price}
- Volume: {volume}

INDICATORS:
- ATR(14): {atr}
- RSI(14): {rsi}
- ADX: {adx}

REGIME:
- HMM regime: {hmm_regime} (0=ranging, 1=trending_up, 2=trending_down)
- Trend regime: {trend_regime}
- Vol regime: {vol_regime}
- GARCH vol ratio: {garch_vol_ratio}

CROSS-TIMEFRAME CONFLUENCE:
- CTF trend alignment: {ctf_trend_alignment}
- CTF regime agreement: {ctf_regime_agreement}
- CTF FVG alignment: {ctf_fvg_alignment}
- CTF OB alignment: {ctf_ob_alignment}

LEVELS:
- VWAP: {vwap}
- POC (session): {poc_price}
- POC (rolling): {poc_price_rolling}

TASK: Identify what is WRONG with this signal. Be contrarian.

Respond with JSON ONLY:
{{
    "failure_probability": <float 0.0-1.0>,
    "confidence": <float 0.0-1.0>,
    "risk_factors": ["<factor1>", "<factor2>"],
    "reasoning": "<1-2 sentence explanation>"
}}

Rules:
- failure_probability=0.0 means nothing wrong, great signal
- failure_probability=1.0 means will definitely fail
- Look for: regime mismatches, weak confluence, exhaustion, adverse levels, volume anomalies
- confidence = how certain you are in your failure_probability assessment
""",
}

PROMPT_REGISTRY[
    "skeptic_v2"
] = """You are a skeptical trading analyst reviewing a signal for potential failure.

SIGNAL CONTEXT:
- Symbol: {symbol}
- Timeframe: {timeframe}
- Setup: {winner_plugin} ({winner_direction_label}, confidence {winner_confidence})

FULL TYPED CONTEXT (every non-None tier from the intelligence pipeline.
null entries indicate the upstream plugin did not produce a value for this bar):

{full_context_block}

TASK: Identify what is WRONG with this signal. Be contrarian. You may
reference any field above by name. Do not invent fields not present.

Respond with JSON ONLY:
{{
    "failure_probability": <float 0.0-1.0>,
    "confidence": <float 0.0-1.0>,
    "risk_factors": ["<factor1>", "<factor2>"],
    "reasoning": "<1-2 sentence explanation>"
}}

Rules:
- failure_probability=0.0 means nothing wrong, great signal
- failure_probability=1.0 means will definitely fail
- Look for: regime mismatches, weak confluence, exhaustion, adverse levels,
  microstructure divergence (OFI/CVD), regime change risk (BOCPD/HMM), cross-asset
  divergence (corr_z), volume anomaly (volume_z_score).
"""


def _validate_skeptic_fields(data: dict) -> dict[str, Any] | None:
    """Validate and sanitize the parsed skeptic response fields.

    Moved here from skeptic_agent.py per D-03: field validators belong in the
    prompts file alongside the prompt content they validate.
    """
    if not isinstance(data, dict):
        return None

    fp = data.get("failure_probability")
    conf = data.get("confidence")

    if not isinstance(fp, (int, float)) or not isinstance(conf, (int, float)):
        return None

    fp = max(0.0, min(1.0, float(fp)))
    conf = max(0.0, min(1.0, float(conf)))

    risk_factors = data.get("risk_factors", [])
    if not isinstance(risk_factors, list):
        risk_factors = [str(risk_factors)]
    else:
        risk_factors = [str(rf) for rf in risk_factors]

    reasoning = data.get("reasoning", "")
    if not isinstance(reasoning, str):
        reasoning = str(reasoning)

    return {
        "failure_probability": fp,
        "confidence": conf,
        "risk_factors": risk_factors,
        "reasoning": reasoning,
    }


def build_skeptic_prompt(ctx: Any) -> str:
    """Build the skeptic prompt.

    v1 path: ctx is a dict (legacy 24-field flat dict from _context_to_dict).
    v2 path: ctx is the typed AIContext object -- full pipeline tiers rendered.
    """
    from src.core.ai.context import AIContext

    template = PROMPT_REGISTRY[ACTIVE_VERSION]
    if ACTIVE_VERSION == "skeptic_v2":
        if not isinstance(ctx, AIContext):
            raise TypeError("skeptic_v2 requires AIContext, got " f"{type(ctx).__name__}")
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

    # v1 legacy path -- dict-input formatting verbatim
    return template.format(
        symbol=ctx.get("symbol", "N/A"),
        timeframe=ctx.get("timeframe", "N/A"),
        winner_plugin=ctx.get("winner_plugin") or "unknown",
        winner_direction_label=DIRECTION_LABELS.get(
            ctx.get("winner_direction", 0),
            "UNKNOWN",
        ),
        winner_confidence=fmt(ctx.get("winner_confidence"), ".0%"),
        price=fmt(ctx.get("price"), ".2f"),
        volume=fmt(ctx.get("volume"), ".0f"),
        atr=fmt(ctx.get("atr"), ".2f"),
        rsi=fmt(ctx.get("rsi"), ".1f"),
        adx=fmt(ctx.get("adx"), ".1f"),
        hmm_regime=str(ctx.get("hmm_regime")) if ctx.get("hmm_regime") is not None else "N/A",
        trend_regime=fmt(ctx.get("trend_regime"), ".2f"),
        vol_regime=fmt(ctx.get("vol_regime"), ".2f"),
        garch_vol_ratio=fmt(ctx.get("garch_vol_ratio"), ".2f"),
        ctf_trend_alignment=fmt(ctx.get("ctf_trend_alignment"), ".2f"),
        ctf_regime_agreement=fmt(ctx.get("ctf_regime_agreement"), ".2f"),
        ctf_fvg_alignment=fmt(ctx.get("ctf_fvg_alignment"), ".2f"),
        ctf_ob_alignment=fmt(ctx.get("ctf_ob_alignment"), ".2f"),
        vwap=fmt(ctx.get("vwap"), ".2f"),
        poc_price=fmt(ctx.get("poc_price"), ".2f"),
        poc_price_rolling=fmt(ctx.get("poc_price_rolling"), ".2f"),
    )
