"""narrative_prompts.py -- versioned prompt registry for NarrativeSynthesizer.

Renaissance design principles:
  - Full tier context rendered via shared render_full_context() (no duplication)
  - Confidence-segmented: high conviction gets direct execution guidance,
    moderate gets conditional, low gets monitor-only.
  - Every prompt version is immutable and auditable. ACTIVE_VERSION is the
    single knob; adding a version never breaks old narratives.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.intelligence.ai.context import SignalContext

from src.core.ai.prompt_utils import DIRECTION_LABELS, REGIME_LABELS, fmt
from src.intelligence.ai.context import render_full_context
from src.intelligence.trading.signal_outcome import EntryType

ACTIVE_VERSION = "narrative_v1"

_DIRECT_THRESHOLD = 0.75
_CONDITIONAL_THRESHOLD = 0.50

NARRATIVE_SYSTEM_PROMPT = (
    "You are a professional equity futures market analyst. "
    "Be direct and precise. No fluff. Use trader terminology. "
    "Never hedge with 'may', 'might', 'could' -- state what the data shows."
)

PROMPT_REGISTRY: dict[str, str] = {
    "narrative_v1": """/no_think

SIGNAL:
- Symbol: {symbol} {timeframe}
- Setup: {setup_plugin} ({direction_label}, confidence {confidence})
- Entry: {entry_price} ({entry_type}) | Stop: {stop_price} ({stop_type}) | T1: {target_price} (R:R {rr})
- Zone: [{zone_low}, {zone_high}]
- Confluence: {confluence_score} | Co-fire: {co_fire_info}
{regime_line}
FULL PIPELINE CONTEXT (populated fields from the intelligence pipeline):

{full_context_block}

{instruction_block}
""",
}

_DIRECT_INSTRUCTION = """Write exactly 2 sentences:
1. (Context): What is the market doing and why does this level matter right now?
2. (Execution -- DIRECT): State the entry, stop, and thesis. High conviction -- act now."""

_CONDITIONAL_INSTRUCTION = """Write exactly 2 sentences:
1. (Context): What is the market doing and why does this setup have potential?
2. (Execution -- CONDITIONAL): Name the exact condition that confirms entry. State entry, stop."""

_MONITOR_INSTRUCTION = """Write exactly 2 sentences:
1. (Context): What is the market doing and what level is in play?
2. (Monitor): Name what confirms this setup. Frame as 'watch' not 'enter'."""


def build_narrative_prompt(context: SignalContext) -> tuple[str, str]:
    """Build (system_prompt, user_prompt) for narrative generation.

    Segments by confidence: >=0.75 direct, 0.50-0.74 conditional, <0.50 monitor.
    Uses real signal levels from signal_ledger (not recomputed ATR approximations).
    """
    i7 = context.i7
    confidence = (i7.winner_confidence if i7 else None) or 0.0
    direction = (i7.winner_direction if i7 else None) or 0
    entry_price = i7.entry_price if i7 else None
    stop_price = i7.stop_price if i7 else None
    targets = i7.target_prices if i7 else None
    entry_type = (i7.entry_type if i7 else None) or EntryType.AT_CLOSE.value
    stop_type = (i7.stop_type if i7 else None) or "atr"
    co_fire = (i7.co_fire_count if i7 else None) or 0

    # R:R from real levels (use first target)
    target_price = targets[0] if targets else None
    rr = i7.risk_reward_ratio if (i7 and i7.risk_reward_ratio) else 0.0
    if not rr and entry_price and stop_price and target_price:
        rr = round(abs(target_price - entry_price) / max(abs(stop_price - entry_price), 0.01), 1)

    # Regime line
    smc = context.smc
    regime_val = getattr(smc, "hmm_regime", None) if smc else None
    regime_prob = getattr(smc, "hmm_regime_prob", None) if smc else None
    regime_line = ""
    if regime_val is not None and regime_prob is not None:
        regime_line = f"- Regime: {REGIME_LABELS.get(regime_val, str(regime_val))} (HMM prob {float(regime_prob):.0%})"

    # Segment by confidence
    if confidence >= _DIRECT_THRESHOLD:
        instruction_block = _DIRECT_INSTRUCTION
    elif confidence >= _CONDITIONAL_THRESHOLD:
        instruction_block = _CONDITIONAL_INSTRUCTION
    else:
        instruction_block = _MONITOR_INSTRUCTION

    template = PROMPT_REGISTRY[ACTIVE_VERSION]
    # Co-fire info
    partners = (i7.co_fire_partners if i7 else None) or []
    co_fire_info = f"{co_fire} plugins" if co_fire > 0 else "solo"

    user_prompt = template.format(
        symbol=context.symbol,
        timeframe=context.timeframe,
        setup_plugin=(i7.winner_plugin if i7 else None) or "unknown",
        direction_label=DIRECTION_LABELS.get(direction, "FLAT"),
        confidence=f"{confidence:.0%}",
        entry_price=fmt(entry_price, ".2f"),
        entry_type=entry_type,
        stop_price=fmt(stop_price, ".2f"),
        stop_type=stop_type,
        target_price=fmt(target_price, ".2f"),
        rr=f"{rr:.1f}",
        zone_low=fmt(i7.zone_low if i7 else None, ".2f"),
        zone_high=fmt(i7.zone_high if i7 else None, ".2f"),
        confluence_score=fmt(i7.confluence_score if i7 else None, ".2f"),
        co_fire_info=co_fire_info,
        regime_line=regime_line,
        full_context_block=render_full_context(context),
        instruction_block=instruction_block,
    )

    return NARRATIVE_SYSTEM_PROMPT, user_prompt
