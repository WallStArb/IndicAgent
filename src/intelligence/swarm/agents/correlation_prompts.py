"""correlation_prompts.py -- versioned prompt registry for CorrelationAgent.

Per D-03: prompt version tracked in every alpha_multiplier_shadow row via
features JSONB.
"""
from __future__ import annotations

import re
from typing import Any

from src.intelligence.swarm.context import SwarmContext

ACTIVE_VERSION = "correlation_v1"

PROMPT_REGISTRY: dict[str, str] = {
    "correlation_v1": (
        """You are a cross-asset correlation analyst reviewing a trading """
        """signal for potential failure due to asset decorrelation.

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

CROSS-TIMEFRAME CONFLUENCE:
- CTF trend alignment: {ctf_trend_alignment}
- CTF regime agreement: {ctf_regime_agreement}
- CTF FVG alignment: {ctf_fvg_alignment}
- CTF OB alignment: {ctf_ob_alignment}

LEAD INDEX CONTEXT (for correlation comparison):
- Lead index symbol: {lead_symbol}
- Lead index trend regime: {lead_trend_regime}
- Lead index RSI: {lead_rsi}
- Lead index ADX: {lead_adx}
- Lead index HMM regime: {lead_hmm_regime}
- Lead index CTF trend alignment: {lead_ctf_trend_alignment}
- Lead index trend regime divergence: {trend_regime_divergence}

TASK: Determine if this asset has decorrelated from its lead index.
Is the signal consistent with the broader market, or is the asset diverging?

Respond with JSON ONLY:
{{
    "failure_probability": <float 0.0-1.0>,
    "confidence": <float 0.0-1.0>,
    "risk_factors": ["<factor1>", "<factor2>"],
    "reasoning": "<1-2 sentence explanation>"
}}

Rules:
- failure_probability=0.0 means asset is well-correlated, signal is consistent
- failure_probability=1.0 means severe decorrelation detected
- Look for: lead index trending up but asset diverging bearish (or vice versa),
  sector rotation, correlation breakdown in volatility regime
- confidence = how certain you are in your correlation assessment
- If lead index data is N/A, reduce confidence and set failure_probability """
        """closer to 0.5 (neutral)
"""
    ),
}

_DIRECTION_LABELS = {1: "LONG", -1: "SHORT", 0: "FLAT"}

# Lead index mapping -- must match _LEAD_INDEX_MAP in swarm_dispatch_service.py
_LEAD_INDEX_MAP: dict[str, str] = {
    "ES": "ES", "NQ": "ES", "RTY": "ES", "YM": "ES",
    "CL": "CL", "HO": "CL", "RB": "CL",
    "GC": "GC", "SI": "GC", "HG": "GC",
    "ZN": "ZN", "ZB": "ZN", "ZF": "ZN", "ZT": "ZN",
    "VX": "VX",
}


def _fmt(val: Any, spec: str) -> str:
    """Format a numeric value with the given format spec, or return N/A."""
    if isinstance(val, (int, float)):
        return format(val, spec)
    return "N/A"


def get_lead_index(symbol: str) -> str | None:
    """Get the lead index base symbol for a given symbol."""
    base_match = re.match(r"^([A-Z]+?)[A-Z]\d+$", symbol)
    if not base_match:
        return None
    return _LEAD_INDEX_MAP.get(base_match.group(1))


def build_correlation_prompt(ctx: SwarmContext) -> str:
    """Build the correlation prompt from SwarmContext.

    Per D-16: reads ctx.lead_context (proper Pydantic field).
    If lead_context is None, all lead fields show as N/A.
    """
    template = PROMPT_REGISTRY[ACTIVE_VERSION]

    lead_symbol = "N/A"
    lead_trend_regime = "N/A"
    lead_rsi = "N/A"
    lead_adx = "N/A"
    lead_hmm_regime = "N/A"
    lead_ctf_trend_alignment = "N/A"
    trend_regime_divergence = "N/A"

    if ctx.lead_context is not None:
        lc = ctx.lead_context
        lead_symbol = lc.symbol
        lead_trend_regime = _fmt(lc.trend_regime, ".2f")
        lead_rsi = _fmt(lc.rsi, ".1f")
        lead_adx = _fmt(lc.adx, ".1f")
        lead_hmm_regime = (
            str(lc.hmm_regime) if lc.hmm_regime is not None else "N/A"
        )
        lead_ctf_trend_alignment = _fmt(lc.ctf_trend_alignment, ".2f")
        if isinstance(ctx.trend_regime, (int, float)) and isinstance(
            lc.trend_regime, (int, float),
        ):
            trend_regime_divergence = f"{ctx.trend_regime - lc.trend_regime:.3f}"

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
        ctf_trend_alignment=_fmt(ctx.ctf_trend_alignment, ".2f"),
        ctf_regime_agreement=_fmt(ctx.ctf_regime_agreement, ".2f"),
        ctf_fvg_alignment=_fmt(ctx.ctf_fvg_alignment, ".2f"),
        ctf_ob_alignment=_fmt(ctx.ctf_ob_alignment, ".2f"),
        lead_symbol=lead_symbol,
        lead_trend_regime=lead_trend_regime,
        lead_rsi=lead_rsi,
        lead_adx=lead_adx,
        lead_hmm_regime=lead_hmm_regime,
        lead_ctf_trend_alignment=lead_ctf_trend_alignment,
        trend_regime_divergence=trend_regime_divergence,
    )
