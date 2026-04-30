"""skeptic_prompts.py -- versioned prompt registry for SkepticAgent.

Per D-03: prompt version tracked in every alpha_multiplier_shadow row via features JSONB.
Per D-16: _render_full_context iterates AIContext.model_fields — open-ended, future-proof.
Per D-17: ACTIVE_VERSION = "skeptic_v2".
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from src.core.ai.context import AIContext

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

_DIRECTION_LABELS = {1: "LONG", -1: "SHORT", 0: "FLAT"}


def _fmt(val: Any, spec: str) -> str:
    """Format a numeric value with the given format spec, or return N/A."""
    if isinstance(val, (int, float)):
        return format(val, spec)
    return "N/A"


# Top-level AIContext fields that are NOT pipeline tiers — skip in rendering.
# Pipeline tiers are everything else that is a Pydantic BaseModel instance.
_CONTEXT_NON_TIER_FIELDS: frozenset[str] = frozenset({
    "signal_id",
    "symbol",
    "timeframe",
    "ts",
    "trigger",
    "bar",
    "i7",  # custom types — rendered separately if at all
    "lead_context",
    "volume_profile",
})


def _render_full_context(ctx: AIContext) -> str:
    """Render every non-None pipeline tier on AIContext as deterministic LLM-friendly text.

    Open-ended (D-16): iterates ctx.model_fields, NOT a hardcoded tier list.
    Any new tier added to AIContext (e.g., a future `qualitative` tier from the
    qualitative-intelligence-layer design doc) automatically appears with zero
    prompt-engineering work.

    Each non-None tier is a `## <tier_name>` section. Float values format to 4
    decimal places; None renders as `null` (explicit absence).
    """
    from pydantic import BaseModel

    lines: list[str] = []
    for field_name in sorted(ctx.__class__.model_fields):
        if field_name in _CONTEXT_NON_TIER_FIELDS:
            continue
        value = getattr(ctx, field_name, None)
        if value is None:
            continue
        if not isinstance(value, BaseModel):
            continue
        tier_dict = value.model_dump()
        if not tier_dict:
            continue
        lines.append(f"## {field_name}")
        for k, v in sorted(tier_dict.items()):
            if v is None:
                lines.append(f"- {k}: null")
            elif isinstance(v, float):
                lines.append(f"- {k}: {v:.4f}")
            else:
                lines.append(f"- {k}: {v}")
    return "\n".join(lines) if lines else "(no features available)"


PROMPT_REGISTRY["skeptic_v2"] = """You are a skeptical trading analyst reviewing a signal for potential failure.

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


def build_skeptic_prompt(ctx: Any) -> str:
    """Build the skeptic prompt.

    v1 path: ctx is a dict (legacy 24-field flat dict from _context_to_dict).
    v2 path: ctx is the typed AIContext object — full pipeline tiers rendered.
    """
    from src.core.ai.context import AIContext

    template = PROMPT_REGISTRY[ACTIVE_VERSION]
    if ACTIVE_VERSION == "skeptic_v2":
        if not isinstance(ctx, AIContext):
            raise TypeError(
                "skeptic_v2 requires AIContext, got "
                f"{type(ctx).__name__}"
            )
        i7 = ctx.i7
        return template.format(
            symbol=ctx.symbol,
            timeframe=ctx.timeframe,
            winner_plugin=(i7.winner_plugin if i7 else None) or "unknown",
            winner_direction_label=_DIRECTION_LABELS.get(
                (i7.winner_direction if i7 else 0) or 0, "UNKNOWN"
            ),
            winner_confidence=_fmt(
                i7.winner_confidence if i7 else None, ".0%"
            ),
            full_context_block=_render_full_context(ctx),
        )

    # v1 legacy path — dict-input formatting verbatim
    return template.format(
        symbol=ctx.get("symbol", "N/A"),
        timeframe=ctx.get("timeframe", "N/A"),
        winner_plugin=ctx.get("winner_plugin") or "unknown",
        winner_direction_label=_DIRECTION_LABELS.get(
            ctx.get("winner_direction", 0),
            "UNKNOWN",
        ),
        winner_confidence=_fmt(ctx.get("winner_confidence"), ".0%"),
        price=_fmt(ctx.get("price"), ".2f"),
        volume=_fmt(ctx.get("volume"), ".0f"),
        atr=_fmt(ctx.get("atr"), ".2f"),
        rsi=_fmt(ctx.get("rsi"), ".1f"),
        adx=_fmt(ctx.get("adx"), ".1f"),
        hmm_regime=str(ctx.get("hmm_regime")) if ctx.get("hmm_regime") is not None else "N/A",
        trend_regime=_fmt(ctx.get("trend_regime"), ".2f"),
        vol_regime=_fmt(ctx.get("vol_regime"), ".2f"),
        garch_vol_ratio=_fmt(ctx.get("garch_vol_ratio"), ".2f"),
        ctf_trend_alignment=_fmt(ctx.get("ctf_trend_alignment"), ".2f"),
        ctf_regime_agreement=_fmt(ctx.get("ctf_regime_agreement"), ".2f"),
        ctf_fvg_alignment=_fmt(ctx.get("ctf_fvg_alignment"), ".2f"),
        ctf_ob_alignment=_fmt(ctx.get("ctf_ob_alignment"), ".2f"),
        vwap=_fmt(ctx.get("vwap"), ".2f"),
        poc_price=_fmt(ctx.get("poc_price"), ".2f"),
        poc_price_rolling=_fmt(ctx.get("poc_price_rolling"), ".2f"),
    )
