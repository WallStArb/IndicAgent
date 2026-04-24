"""skeptic_prompts.py -- versioned prompt registry for SkepticAgent.

Per D-03: prompt version tracked in every alpha_multiplier_shadow row via features JSONB.
"""
from __future__ import annotations

from typing import Any

from src.intelligence.swarm.context import SwarmContext

ACTIVE_VERSION = "skeptic_v1"

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

_DIRECTION_LABELS = {1: "LONG", -1: "SHORT", 0: "FLAT"}


def _fmt(val: Any, spec: str) -> str:
    """Format a numeric value with the given format spec, or return N/A."""
    if isinstance(val, (int, float)):
        return format(val, spec)
    return "N/A"


def build_skeptic_prompt(ctx: SwarmContext) -> str:
    """Build the skeptic prompt from SwarmContext, filling all available fields.

    Per D-01: send all available features as structured context.
    Uses ACTIVE_VERSION to select the prompt template from registry.
    """
    template = PROMPT_REGISTRY[ACTIVE_VERSION]
    return template.format(
        symbol=ctx.symbol,
        timeframe=ctx.timeframe,
        winner_plugin=ctx.winner_plugin or "unknown",
        winner_direction_label=_DIRECTION_LABELS.get(
            ctx.winner_direction, "UNKNOWN",
        ),
        winner_confidence=_fmt(ctx.winner_confidence, ".0%"),
        price=_fmt(ctx.price, ".2f"),
        volume=_fmt(ctx.volume, ".0f"),
        atr=_fmt(ctx.atr, ".2f"),
        rsi=_fmt(ctx.rsi, ".1f"),
        adx=_fmt(ctx.adx, ".1f"),
        hmm_regime=(
            str(ctx.hmm_regime) if ctx.hmm_regime is not None else "N/A"
        ),
        trend_regime=_fmt(ctx.trend_regime, ".2f"),
        vol_regime=_fmt(ctx.vol_regime, ".2f"),
        garch_vol_ratio=_fmt(ctx.garch_vol_ratio, ".2f"),
        ctf_trend_alignment=_fmt(ctx.ctf_trend_alignment, ".2f"),
        ctf_regime_agreement=_fmt(ctx.ctf_regime_agreement, ".2f"),
        ctf_fvg_alignment=_fmt(ctx.ctf_fvg_alignment, ".2f"),
        ctf_ob_alignment=_fmt(ctx.ctf_ob_alignment, ".2f"),
        vwap=_fmt(ctx.vwap, ".2f"),
        poc_price=_fmt(ctx.poc_price, ".2f"),
        poc_price_rolling=_fmt(ctx.poc_price_rolling, ".2f"),
    )
