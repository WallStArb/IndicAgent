"""volume_prompts.py -- versioned prompt registry for VolumeAgent.

Per D-03: prompt version tracked in every alpha_multiplier_shadow row via
features JSONB.
"""
from __future__ import annotations

from typing import Any

from src.intelligence.swarm.context import SwarmContext

ACTIVE_VERSION = "volume_v1"

PROMPT_REGISTRY: dict[str, str] = {
    "volume_v1": (
        """You are a volume profile analyst reviewing a trading signal """
        """for potential failure due to inadequate volume support or fake-out """
        """price action.

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

SESSION VOLUME PROFILE (resets daily, use for 5m):
- POC (session): {poc_price}
- VAH (session): {vah}
- VAL (session): {val}

STRUCTURAL VOLUME PROFILE (rolling, use for 15m+):
- POC (rolling): {poc_price_rolling}
- VAH (rolling): {vah_rolling}
- VAL (rolling): {val_rolling}

VOLUME DYNAMICS:
- Price in value area: {price_in_value_area}
- Distance to VAH (ATR): {distance_to_vah_atr}
- Distance to VAL (ATR): {distance_to_val_atr}

CROSS-TIMEFRAME CONFLUENCE:
- CTF trend alignment: {ctf_trend_alignment}
- CTF regime agreement: {ctf_regime_agreement}

TASK: Determine if this signal's price action is supported by volume or
if it is a low-volume sweep/fake-out.

Respond with JSON ONLY:
{{
    "failure_probability": <float 0.0-1.0>,
    "confidence": <float 0.0-1.0>,
    "risk_factors": ["<factor1>", "<factor2>"],
    "reasoning": "<1-2 sentence explanation>"
}}

Rules:
- failure_probability=0.0 means strong volume support, legitimate breakout
- failure_probability=1.0 means no volume support, likely fake-out/sweep
- Look for: breakout above VAH on declining volume, sweep below VAL with no
  follow-through, POC shift not confirmed, volume divergence from price
- confidence = how certain you are in your volume assessment
- If volume profile data is N/A, reduce confidence and set """
        """failure_probability closer to 0.5 (neutral)
"""
    ),
}

_DIRECTION_LABELS = {1: "LONG", -1: "SHORT", 0: "FLAT"}


def _fmt(val: Any, spec: str) -> str:
    """Format a numeric value with the given format spec, or return N/A."""
    if isinstance(val, (int, float)):
        return format(val, spec)
    return "N/A"


def build_volume_prompt(ctx: SwarmContext) -> str:
    """Build the volume prompt from SwarmContext.

    Per D-16: reads ctx.volume_profile (dict set by
    SwarmDispatchService._enrich_context).
    """
    template = PROMPT_REGISTRY[ACTIVE_VERSION]
    vp = ctx.volume_profile or {}

    return template.format(
        symbol=ctx.symbol,
        timeframe=ctx.timeframe,
        winner_plugin=ctx.winner_plugin or "unknown",
        winner_direction_label=_DIRECTION_LABELS.get(
            ctx.winner_direction or 0, "UNKNOWN",
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
        poc_price=_fmt(ctx.poc_price, ".2f"),
        vah=_fmt(vp.get("vah"), ".2f"),
        val=_fmt(vp.get("val"), ".2f"),
        poc_price_rolling=_fmt(ctx.poc_price_rolling, ".2f"),
        vah_rolling=_fmt(vp.get("vah_rolling"), ".2f"),
        val_rolling=_fmt(vp.get("val_rolling"), ".2f"),
        price_in_value_area=_fmt(vp.get("price_in_value_area"), ".3f"),
        distance_to_vah_atr=_fmt(vp.get("distance_to_vah_atr"), ".3f"),
        distance_to_val_atr=_fmt(vp.get("distance_to_val_atr"), ".3f"),
        ctf_trend_alignment=_fmt(ctx.ctf_trend_alignment, ".2f"),
        ctf_regime_agreement=_fmt(ctx.ctf_regime_agreement, ".2f"),
    )
