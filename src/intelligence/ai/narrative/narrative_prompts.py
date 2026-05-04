"""narrative_prompts.py -- versioned prompt registry for NarrativeComputeAgent.

Renaissance design principles:
  - Full tier context rendered via shared render_full_context() (no duplication)
  - Confidence-segmented: high conviction gets direct execution guidance,
    moderate gets conditional, low gets monitor-only. The LLM doesn't decide
    what to show the PM -- the pipeline segments it.
  - Every prompt version is immutable and auditable. ACTIVE_VERSION is the
    single knob; adding a version never breaks old narratives.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.core.ai.context import AIContext

from src.core.ai.context import render_full_context

ACTIVE_VERSION = "narrative_v1"

_DIRECTION_LABELS = {1: "LONG", -1: "SHORT", 0: "FLAT"}
_REGIME_LABELS = {0: "Ranging", 1: "Trending Up", 2: "Trending Down"}

# Confidence segmentation thresholds (Renaissance: segment relentlessly)
_DIRECT_THRESHOLD = 0.75
_CONDITIONAL_THRESHOLD = 0.50


def _fmt(val: float | int | None, spec: str) -> str:
    if isinstance(val, (int, float)):
        return format(val, spec)
    return "N/A"


PROMPT_REGISTRY: dict[str, str] = {
    "narrative_v1": """/no_think

You are a professional equity futures market analyst. Be direct and precise.
No fluff. Use trader terminology. Never hedge with 'may', 'might', 'could'
-- state what the data shows.

SIGNAL:
- Symbol: {symbol} {timeframe}
- Setup: {setup_plugin} ({direction_label}, confidence {confidence})
- Entry: {entry_price} | Stop: {stop_price} | T1: {target_price} (R:R {rr})
- Entry type: {entry_type}
{regime_line}
FULL PIPELINE CONTEXT (every non-Null tier from the intelligence pipeline):

{full_context_block}

{instruction_block}
""",
}

# Instruction blocks keyed by confidence segment -- the pipeline decides what
# depth of analysis the PM needs, not the LLM.

_DIRECT_INSTRUCTION = """Write exactly 2 sentences:
1. (Context): What is the market doing and why does this level matter right now?
2. (Execution -- DIRECT): State the entry, stop, and thesis. High conviction -- act now."""

_CONDITIONAL_INSTRUCTION = """Write exactly 2 sentences:
1. (Context): What is the market doing and why does this setup have potential?
2. (Execution -- CONDITIONAL): Name the exact condition that confirms entry. State entry, stop."""

_MONITOR_INSTRUCTION = """Write exactly 2 sentences:
1. (Context): What is the market doing and what level is in play?
2. (Monitor): Name what confirms this setup. Frame as 'watch' not 'enter'."""


def build_narrative_prompt(context: AIContext) -> tuple[str, str]:
    """Build (system_prompt, user_prompt) for narrative generation.

    Returns a tuple of (system_prompt, user_prompt) -- the system prompt is
    constant across versions, the user prompt is version-specific.

    Segments by confidence: >=0.75 direct, 0.50-0.74 conditional, <0.50 monitor.
    """
    i7 = context.i7
    confidence = (i7.winner_confidence if i7 else None) or 0.0
    direction = (i7.winner_direction if i7 else None) or 0

    # Price levels from bar context
    bar = context.bar
    close = bar.close if bar else None
    i1 = context.i1
    atr = getattr(i1, "atr_14", None) if i1 else None

    if close is not None and atr:
        stop = round(close - atr * 1.5, 2) if direction > 0 else round(close + atr * 1.5, 2)
        target = round(close + atr * 3.0, 2) if direction > 0 else round(close - atr * 3.0, 2)
        rr = round(abs(target - close) / max(abs(stop - close), 0.01), 1)
        entry = close
    else:
        stop = target = entry = None
        rr = 0.0

    # Regime line
    smc = context.smc
    regime_val = getattr(smc, "hmm_regime", None) if smc else None
    regime_prob = getattr(smc, "hmm_regime_prob", None) if smc else None
    regime_line = ""
    if regime_val is not None and regime_prob is not None:
        regime_line = f"- Regime: {_REGIME_LABELS.get(regime_val, str(regime_val))} (HMM prob {float(regime_prob):.0%})"

    # Segment by confidence
    if confidence >= _DIRECT_THRESHOLD:
        instruction_block = _DIRECT_INSTRUCTION
    elif confidence >= _CONDITIONAL_THRESHOLD:
        instruction_block = _CONDITIONAL_INSTRUCTION
    else:
        instruction_block = _MONITOR_INSTRUCTION

    template = PROMPT_REGISTRY[ACTIVE_VERSION]
    user_prompt = template.format(
        symbol=context.symbol,
        timeframe=context.timeframe,
        setup_plugin=(i7.winner_plugin if i7 else None) or "unknown",
        direction_label=_DIRECTION_LABELS.get(direction, "FLAT"),
        confidence=f"{confidence:.0%}",
        entry_price=_fmt(entry, ".2f"),
        stop_price=_fmt(stop, ".2f"),
        target_price=_fmt(target, ".2f"),
        rr=f"{rr:.1f}",
        entry_type=getattr(i7, "entry_type", None) or "at_close",
        regime_line=regime_line,
        full_context_block=render_full_context(context),
        instruction_block=instruction_block,
    )

    system_prompt = (
        "You are a professional equity futures market analyst. "
        "Be direct and precise. No fluff. Use trader terminology. "
        "Never hedge with 'may', 'might', 'could' -- state what the data shows."
    )

    return system_prompt, user_prompt
