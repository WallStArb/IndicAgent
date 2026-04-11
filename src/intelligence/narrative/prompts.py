"""Pure prompt-building functions for market narrative generation.

All functions accept BarIntelligenceRecord and return str.
No I/O, no LLM calls, no Kafka — fully testable without infrastructure.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.intelligence.schemas import BarIntelligenceRecord

_STRUCTURAL_LABELS: dict[str, str] = {
    "LiquiditySweepReclaim": "SWEEP RECLAIM",
    "LiquidityHunt": "LIQUIDITY HUNT",
    "FVGFill": "FVG FILL",
    "CHoCHReversal": "REVERSAL",
    "SupplyDemandSetup": "S/D RECLAIM",
    "TrendFollowing": "TREND CONTINUATION",
    "MeanReversion": "MEAN REVERSION",
    "MTFAlignment": "MTF ALIGNMENT",
    "SqueezeExpansion": "SQUEEZE BREAK",
    "MomentumBreakout": "BREAKOUT",
    "VWAPDeviation": "VWAP RECLAIM",
    "PatternCompletion": "PATTERN COMPLETE",
    "DivergenceStack": "DIVERGENCE",
    "RegimeTransition": "REGIME SHIFT",
    "GapAnalysisSetup": "GAP SETUP",
    "CandlestickPatternSetup": "CANDLE PATTERN",
    "SessionExtremesSetup": "SESSION EXTREME",
}

_REGIME_LABELS = {0: "Ranging", 1: "Trending Up", 2: "Trending Down"}


def _structural_label(plugin: str) -> str:
    bare = plugin.split("_", 1)[-1] if "_" in plugin else plugin
    return _STRUCTURAL_LABELS.get(bare, bare.upper()[:16])


def _direction_label(direction: int) -> str:
    return "Bullish" if direction > 0 else "Bearish"


def build_short_prompt(record: "BarIntelligenceRecord") -> str:
    """Two-sentence prompt. confidence >= 0.75 → direct; 0.50-0.74 → conditional; < 0.50 → monitor."""
    intel = record.intelligence
    symbol = intel.symbol
    tf = intel.tf
    direction = record.winner_direction or 0
    confidence = record.winner_confidence or 0.0
    plugin = record.winner_plugin or ""
    close = intel.bar.close
    atr = getattr(intel.i1, "atr_14", None) or 1.0
    regime = getattr(intel.i4, "hmm_regime", None)
    regime_prob = getattr(intel.i4, "hmm_regime_prob", None)
    ctf = getattr(intel.i6, "ctf_trend_alignment", None)

    stop = round(close - atr * 1.5, 2) if direction > 0 else round(close + atr * 1.5, 2)
    entry = close

    if confidence >= 0.75:
        exec_line = (
            f"Sentence 2 (Execution — DIRECT): State entry at {entry} with stop at {stop}. "
            f"High conviction — instruct PM to act now."
        )
    elif confidence >= 0.50:
        exec_line = (
            f"Sentence 2 (Execution — CONDITIONAL): Name the exact condition before entering. "
            f"Entry {entry}, stop {stop}."
        )
    else:
        exec_line = (
            f"Sentence 2 (Monitor): Name what level confirms this setup. Frame as 'watch' not 'enter'."
        )

    regime_line = ""
    if regime is not None and regime_prob is not None:
        regime_line = f"Regime: {_REGIME_LABELS.get(regime, str(regime))} (prob {float(regime_prob):.0%})\n"

    ctf_line = f"CTF Alignment: {ctf:.2f}\n" if ctf is not None else ""

    return (
        f"/no_think\n\n"
        f"Symbol: {symbol} {tf} — {_direction_label(direction)} (confidence {confidence:.0%})\n"
        f"Structure: {_structural_label(plugin)}\n"
        f"{regime_line}"
        f"{ctf_line}"
        f"Entry: {entry} | Stop: {stop}\n\n"
        f"Write exactly 2 sentences:\n"
        f"Sentence 1 (Context — STRUCTURAL): What is the market doing and why does this level matter?\n"
        f"{exec_line}"
    )


def build_deep_prompt(record: "BarIntelligenceRecord") -> str:
    """Three-sentence prompt: Confluence + Key Levels + Guidance/Invalidation."""
    intel = record.intelligence
    symbol = intel.symbol
    tf = intel.tf
    direction = record.winner_direction or 0
    confidence = record.winner_confidence or 0.0
    plugin = record.winner_plugin or ""
    close = intel.bar.close
    atr = getattr(intel.i1, "atr_14", None) or 1.0
    regime = getattr(intel.i4, "hmm_regime", None)
    regime_prob = getattr(intel.i4, "hmm_regime_prob", None)
    ctf_trend = getattr(intel.i6, "ctf_trend_alignment", None)
    ctf_regime = getattr(intel.i6, "ctf_regime_agreement", None)

    stop = round(close - atr * 1.5, 2) if direction > 0 else round(close + atr * 1.5, 2)
    entry = close
    target = round(close + atr * 3.0, 2) if direction > 0 else round(close - atr * 3.0, 2)
    rr = round(abs(target - entry) / max(abs(stop - entry), 0.01), 1)

    regime_line = ""
    if regime is not None and regime_prob is not None:
        regime_line = f"Regime: {_REGIME_LABELS.get(regime, str(regime))} (HMM prob {float(regime_prob):.0%})\n"

    confluence_parts = []
    if ctf_trend is not None:
        confluence_parts.append(f"CTF trend {ctf_trend:.2f}")
    if ctf_regime is not None:
        confluence_parts.append(f"regime agree {ctf_regime:.2f}")
    confluence_line = f"Confluence: {', '.join(confluence_parts)}\n" if confluence_parts else ""

    return (
        f"/no_think\n\n"
        f"Symbol: {symbol} {tf} — {_direction_label(direction)} (confidence {confidence:.0%})\n"
        f"Structure: {_structural_label(plugin)}\n"
        f"{regime_line}"
        f"{confluence_line}"
        f"Entry: {entry} | Stop: {stop} | T1: {target} (R:R {rr})\n\n"
        f"Write exactly 3 sentences:\n"
        f"Sentence 1 (Confluence): Name every source aligning — timeframes, SMC structure, HMM state, zone.\n"
        f"Sentence 2 (Key Levels): Entry rationale (why THIS level). Stop placement logic. T1 significance.\n"
        f"Sentence 3 (Guidance + Invalidation): Confidence-weighted sizing. End with what invalidates thesis."
    )
