#!/usr/bin/env python3
"""
AI Narrative Service — I8 LLM synthesis of trading signals into human-readable narratives

Subscribes to signals:SYMBOL:TF:aggregated stream. For each selected signal,
builds a structured prompt, calls Ollama (qwen3:8b), and publishes a narrative
to narratives:SYMBOL:TF stream and narrative:SYMBOL:TF:latest hash.

Version: 1.0.0
Last Updated: 2026-02-19
Status: Production Ready
"""

from __future__ import annotations

import asyncio
import json
import os
import signal
import sys
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

import redis.asyncio as redis  # noqa: E402
import structlog  # noqa: E402

from src.config.settings import Settings, get_active_contracts  # noqa: E402
from src.core.service_utils import setup_service_logging  # noqa: E402
from src.core.stream_keys import intelligence as sk_intelligence  # noqa: E402
from src.core.stream_keys import intelligence_i8 as sk_intelligence_i8  # noqa: E402
from src.core.stream_keys import (  # noqa: E402
    llm_calls_stream,
    llm_scores_cache,
    signals_aggregated,  # noqa: E402
)
from src.core.stream_keys import narratives as sk_narratives  # noqa: E402
from src.core.stream_utils import ensure_consumer_group_with_reset  # noqa: E402
from src.observability.metrics import counter, gauge, start_metrics_server  # noqa: E402

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = (
    "You are a senior trading desk analyst briefing a portfolio manager. "
    "Write with precision and economy — every word must earn its place. "
    "Never use passive voice. "
    "State conclusions directly — the system computed these signals with statistical confidence. "
    "Do not restate the setup name or direction label — the PM already sees those. "
    "Avoid generic trading clichés and vague risk-to-reward phrasing. "
    "Your job: explain WHY this structure matters right now and WHAT to do about it."
)

# Per-signal narrative gating
_NARRATIVE_ELIGIBLE_TFS = {"5m", "15m", "1h"}
_NARRATIVE_MIN_CONFIDENCE = 0.70

GROUP_SYSTEM_PROMPT = (
    "You are a professional multi-asset futures analyst. "
    "Respond with ONLY a concise 2-3 sentence group synthesis covering cross-asset "
    "themes and directional bias — no analysis steps, no numbered sections, no headers. "
    "Be specific. No disclaimers."
)

# Asset group definitions — contract codes for active front-month (Feb 2026)
ASSET_GROUPS: dict[str, list[str]] = {
    "equity":    ["ESH6", "NQH6", "RTYH6", "YMH6", "VXH6"],
    "energy":    ["CLJ6", "BZJ6", "NGJ6"],
    "metals":    ["GCJ6", "SIH6", "HGH6", "PLJ6"],
    "rates":     ["ZNH6", "ZFH6", "ZBH6", "ZTH6", "SR1H6"],
    "fx_crypto": ["6EH6", "6JH6", "BTCH6"],
    "ag":        ["ZSH6", "ZCH6", "ZWH6"],
}

# Reverse lookup: contract_code → group_name
SYMBOL_TO_GROUP: dict[str, str] = {
    sym: group
    for group, symbols in ASSET_GROUPS.items()
    for sym in symbols
}

# TFs considered for group synthesis signal state
_GROUP_SYNTHESIS_TFS = ("5m", "15m", "1h")


def build_group_synthesis_prompt(
    group_name: str,
    signals: dict[str, dict],
) -> str:
    """Build a phi4-mini prompt for group-level cross-asset synthesis.

    Args:
        group_name: e.g. "equity"
        signals: dict keyed by "SYMBOL:TF" → parsed signal dict.
                 Only non-zero direction signals should be passed.
    """
    if not signals:
        lines = [f"Group {group_name}: no active signals at this time."]
    else:
        lines = []
        for key, sig in sorted(signals.items()):
            sym, tf = key.split(":", 1)
            confidence_pct = f"{sig.get('confidence', 0):.0%}"
            lines.append(
                f"- {sym} {tf}: {sig.get('direction_label', 'Neutral')} "
                f"(confidence {confidence_pct}) | {sig.get('setup_plugin', 'unknown')} "
                f"| {sig.get('regime_context', 'unknown')}"
            )

    signal_block = "\n".join(lines)
    return (
        f"/no_think\n\n"
        f"Group: {group_name}\n"
        f"Current signals:\n{signal_block}\n\n"
        f"Write a 2-3 sentence cross-asset synthesis for this group."
    )


def extract_group_fingerprint(
    signals: dict[str, dict],
) -> dict[str, tuple[int, str]]:
    """Extract a comparable fingerprint from a signals dict.

    Only includes entries where direction != 0 (actionable signals).
    Returns dict of "SYMBOL:TF" → (direction, regime_context).
    """
    return {
        key: (int(sig.get("direction", 0)), str(sig.get("regime_context", "")))
        for key, sig in signals.items()
        if int(sig.get("direction", 0)) != 0
    }


# ---------------------------------------------------------------------------
# Pure helper functions (no I/O — easy to test)
# ---------------------------------------------------------------------------

def parse_aggregated_signal(fields: dict[bytes, bytes]) -> dict[str, Any] | None:
    """Parse a signals:aggregated stream message into a typed signal dict.

    Returns None if direction is 0 (no actionable signal to narrate).
    """
    def _get(key: str, default: str = "") -> str:
        raw = fields.get(key.encode(), b"")
        return (raw.decode() if isinstance(raw, bytes) else str(raw)).strip() or default

    direction = int(float(_get("direction", "0")))
    if direction == 0:
        return None

    return {
        "symbol": _get("symbol"),
        "timeframe": _get("timeframe"),
        "timestamp": _get("timestamp"),
        "signal_id": _get("signal_id"),
        "direction": direction,
        "direction_label": "Bullish" if direction > 0 else "Bearish",
        "confidence": float(_get("confidence", "0.0")),
        "confluence_score": float(_get("confluence_score", "0.0")),
        "setup_plugin": _get("setup_plugin"),
        "signal_type": _get("signal_type"),
        "entry_price": _get("entry_price"),
        "stop_loss": _get("stop_loss"),
        "profit_target": _get("profit_target"),        # promoted scalar from targets[0]
        "risk_reward_ratio": _get("risk_reward_ratio"),
        "regime_context": _get("regime_context"),
        "supporting_factors": _get("supporting_factors"),
    }


# build_narrative_prompt() retired in phase 22 (three-tier redesign) — use build_short_prompt() / build_deep_prompt()


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


def get_structural_label(setup_plugin: str) -> str:
    """Map setup plugin name to a short structural label for the signal bar."""
    return _STRUCTURAL_LABELS.get(setup_plugin, setup_plugin.upper()[:16])


def build_action_tag(signal: dict[str, Any]) -> str:
    """Build deterministic action tag from signal direction and confidence.

    >=75%: [BULLISH LABEL] / [BEARISH LABEL]
    50-74%: [WAIT -- BULLISH] / [WAIT -- BEARISH]
    <50%: [MONITOR]
    """
    confidence = float(signal.get("confidence", 0))
    direction = int(signal.get("direction", 0))
    label = get_structural_label(str(signal.get("setup_plugin", "")))

    if confidence < 0.50:
        return "[MONITOR]"

    direction_word = "BULLISH" if direction > 0 else "BEARISH"

    if confidence >= 0.75:
        return f"[{direction_word} {label}]"
    else:
        return f"[WAIT \u2014 {direction_word}]"


def extract_short_context(signal: dict[str, Any], intel: dict[str, Any]) -> dict[str, Any]:
    """Pre-digest intelligence data for the short narrative prompt.

    Only the conclusion-level fields: regime label, top structural event,
    confluence count, entry/stop/target, confidence, killzone.
    """
    hmm = intel.get("hmm_regime")
    hmm_prob = intel.get("hmm_regime_prob")
    regime_labels = {"0": "ranging", "1": "trending-up", "2": "trending-down"}
    regime_label = regime_labels.get(str(hmm), "unknown") if hmm is not None else None

    killzone = None
    if intel.get("in_london_killzone") == "1":
        killzone = "London"
    elif intel.get("in_ny_killzone") == "1" or intel.get("in_ny_am_killzone") == "1":
        killzone = "NY"
    elif intel.get("in_asia_killzone") == "1":
        killzone = "Asia"
    elif intel.get("killzone_name"):
        killzone = str(intel["killzone_name"]).title()

    confluence_score = intel.get("confluence_score") or intel.get("trend_confluence_score")

    return {
        "symbol": signal.get("symbol"),
        "timeframe": signal.get("timeframe"),
        "direction_label": signal.get("direction_label"),
        "confidence": float(signal.get("confidence", 0)),
        "setup_plugin": signal.get("setup_plugin"),
        "entry": signal.get("entry_price"),
        "stop": signal.get("stop_loss"),
        "target_1": signal.get("profit_target"),
        "rr": signal.get("risk_reward_ratio"),
        "hmm_regime": str(hmm) if hmm is not None else None,
        "hmm_regime_label": regime_label,
        "hmm_regime_prob": str(hmm_prob) if hmm_prob is not None else None,
        "killzone": killzone,
        "confluence_score": str(confluence_score) if confluence_score else None,
        "structural_label": get_structural_label(str(signal.get("setup_plugin", ""))),
    }


def extract_deep_context(signal: dict[str, Any], intel: dict[str, Any]) -> dict[str, Any]:
    """Full intelligence context for the deep narrative prompt.

    Superset of extract_short_context plus: FVG bounds, OB levels,
    S/D zone levels, all targets, HMM probabilities, supporting factors.
    """
    ctx = extract_short_context(signal, intel)
    ctx.update(
        {
            "fvg_bottom": intel.get("fvg_bottom"),
            "fvg_top": intel.get("fvg_top"),
            "ob_bottom": intel.get("ob_bottom"),
            "ob_top": intel.get("ob_top"),
            "nearest_demand_low": intel.get("nearest_demand_low"),
            "nearest_demand_high": intel.get("nearest_demand_high"),
            "nearest_supply_low": intel.get("nearest_supply_low"),
            "nearest_supply_high": intel.get("nearest_supply_high"),
            "supporting_factors": signal.get("supporting_factors", ""),
            "regime_context": signal.get("regime_context"),
        }
    )
    return ctx


def build_short_prompt(signal: dict[str, Any], ctx: dict[str, Any]) -> str:
    """Build the short narrative user prompt (2-sentence Context+Execution)."""
    confidence = ctx["confidence"]
    confidence_pct = f"{confidence:.0%}"

    if confidence >= 0.75:
        execution_instruction = (
            f"Sentence 2 (Execution \u2014 DIRECT): State the exact entry price and stop. "
            f"This is high-conviction \u2014 tell the PM to act now at {ctx['entry']} "
            f"with stop at {ctx['stop']}."
        )
    elif confidence >= 0.50:
        execution_instruction = (
            f"Sentence 2 (Execution \u2014 CONDITIONAL): Name the exact condition the PM "
            f"must wait for before entering. Entry {ctx['entry']}, stop {ctx['stop']}."
        )
    else:
        execution_instruction = (
            "Sentence 2 (Monitor): Name what level or condition would confirm this "
            "setup before acting. Frame as \'watch\' not \'enter\'."
        )

    regime_line = ""
    if ctx.get("hmm_regime_label") and ctx.get("hmm_regime_prob"):
        regime_line = (
            f"Regime: {ctx['hmm_regime_label']} "
            f"(HMM state {ctx['hmm_regime']}, prob {float(ctx['hmm_regime_prob']):.0%})\n"
        )

    killzone_line = (
        f"Killzone: {ctx['killzone']} open active\n" if ctx.get("killzone") else ""
    )
    confluence_line = (
        f"Confluence: {ctx['confluence_score']}\n" if ctx.get("confluence_score") else ""
    )

    return (
        f"/no_think\n\n"
        f"Symbol: {ctx['symbol']} {ctx['timeframe']} \u2014 {ctx['direction_label']} "
        f"(confidence {confidence_pct})\n"
        f"Structure: {ctx['structural_label']}\n"
        f"{regime_line}"
        f"{killzone_line}"
        f"{confluence_line}"
        f"Entry: {ctx['entry']} | Stop: {ctx['stop']} | T1: {ctx['target_1']} (R:R {ctx['rr']})\n\n"
        f"Write exactly 2 sentences:\n"
        f"Sentence 1 (Context \u2014 STRUCTURAL): What is the market doing right now and why "
        f"does this level matter structurally? Use high-signal terminology. "
        f"Explain this is a structural event, not a random bounce.\n"
        f"{execution_instruction}"
    )


def build_deep_prompt(signal: dict[str, Any], ctx: dict[str, Any]) -> str:
    """Build the deep narrative user prompt (3-sentence confluence story)."""
    confidence = ctx["confidence"]
    confidence_pct = f"{confidence:.0%}"

    fvg_line = ""
    if ctx.get("fvg_bottom") and ctx.get("fvg_top"):
        fvg_line = f"FVG: {ctx['fvg_bottom']}\u2013{ctx['fvg_top']}\n"

    ob_line = ""
    if ctx.get("ob_bottom") and ctx.get("ob_top"):
        ob_line = f"Order Block: {ctx['ob_bottom']}\u2013{ctx['ob_top']}\n"

    sd_line = ""
    if ctx.get("nearest_demand_low") and ctx.get("nearest_demand_high"):
        sd_line = f"Demand Zone: {ctx['nearest_demand_low']}\u2013{ctx['nearest_demand_high']}\n"
    elif ctx.get("nearest_supply_low") and ctx.get("nearest_supply_high"):
        sd_line = f"Supply Zone: {ctx['nearest_supply_low']}\u2013{ctx['nearest_supply_high']}\n"

    regime_line = ""
    if ctx.get("hmm_regime_label") and ctx.get("hmm_regime_prob"):
        regime_line = (
            f"Regime: {ctx['hmm_regime_label']} "
            f"(HMM state {ctx['hmm_regime']}, prob {float(ctx['hmm_regime_prob']):.0%})\n"
        )

    factors_line = (
        f"Supporting factors: {ctx['supporting_factors']}\n"
        if ctx.get("supporting_factors")
        else ""
    )

    return (
        f"/no_think\n\n"
        f"Symbol: {ctx['symbol']} {ctx['timeframe']} \u2014 {ctx['direction_label']} "
        f"(confidence {confidence_pct})\n"
        f"Structure: {ctx['structural_label']}\n"
        f"{regime_line}"
        f"{fvg_line}"
        f"{ob_line}"
        f"{sd_line}"
        f"Entry: {ctx['entry']} | Stop: {ctx['stop']} | T1: {ctx['target_1']} (R:R {ctx['rr']})\n"
        f"{factors_line}"
        f"\n"
        f"Write exactly 3 sentences:\n"
        f"Sentence 1 (Confluence): Name every source aligning \u2014 which timeframes, "
        f"what SMC structure, what HMM state, what zone. Be specific with level names.\n"
        f"Sentence 2 (Key Levels): Entry rationale (not just the price \u2014 why THIS level). "
        f"Stop placement logic. T1 target significance.\n"
        f"Sentence 3 (Guidance + Invalidation): Confidence-weighted sizing or timing "
        f"guidance. Always end with what would invalidate this thesis."
    )


def _build_llm_call_payload(
    call_type: str,
    signal_data: dict[str, Any] | None,
    group_name: str,
    prompt: str,
    response: str | None,
    latency_ms: float,
    succeeded: bool,
    model_id: str,
) -> dict[str, str]:
    """Build the stream payload dict for a single LLM call log entry.

    All values are str — Redis stream messages require string values.
    signal_id is threaded from the signals:aggregated stream message.
    """
    sd = signal_data or {}
    return {
        "call_id":         str(uuid.uuid4()),
        "called_at":       datetime.now(tz=UTC).isoformat(),
        "call_type":       call_type,
        "signal_id":       str(sd.get("signal_id", "")),
        "group_name":      group_name,
        "symbol":          str(sd.get("symbol", "")),
        "timeframe":       str(sd.get("timeframe", "")),
        "model":           model_id,
        "provider":        model_id.split(":")[0] if model_id else "",
        "prompt":          prompt,
        "response":        response or "",
        "latency_ms":      str(int(latency_ms)),
        "tokens_est":      str(len((response or "").split())),
        "succeeded":       "1" if succeeded else "0",
        "regime":          str(sd.get("regime_context", "")),
        "session":         "",                                          # not in aggregated stream
        "entry_price":     str(sd.get("entry_price", "")),
        "stop_loss":       str(sd.get("stop_loss", "")),
        "target_price":    str(sd.get("profit_target", "")),
        "confidence":      str(sd.get("confidence", "")),
        "cis_score":       "",                                          # not in aggregated stream
        "entry_zone_low":  "",                                          # not in aggregated stream
        "entry_zone_high": "",                                          # not in aggregated stream
        "setup_type":      str(sd.get("setup_plugin", "")),
    }


def _promote_model_in_chain(chain: Any, model_provider_id: str | None) -> None:
    """Atomically move the given provider to position 0 in chain.providers.

    Uses list replacement (not in-place mutation) to be safe against concurrent
    reads from _process_loop / _group_synthesis_loop. No-op if model is already
    first, not found, or model_provider_id is None/empty.
    """
    if not model_provider_id:
        return
    current = chain.providers
    if not current:
        return
    if current[0].provider_id == model_provider_id:
        return  # already at position 0
    target = next((p for p in current if p.provider_id == model_provider_id), None)
    if target is None:
        return
    chain.providers = [target] + [p for p in current if p.provider_id != model_provider_id]


# ---------------------------------------------------------------------------
# Service class
# ---------------------------------------------------------------------------

class AINarrativeService:
    """Synthesize aggregated trading signals into LLM-generated market narratives."""

    def __init__(self, config_file: str | None = None):
        self.running = False
        self.shutdown_requested = False
        self.start_time = datetime.now(tz=UTC)

        self.config = self._load_config(config_file)
        self._setup_logging()

        self.redis_client: redis.Redis | None = None
        self.consumer_group = "ai_narrative"
        self.consumer_name = f"narrative_{os.getpid()}"

        settings = Settings()
        self.env_prefix = f"{settings.env_name}:" if settings.env_name else ""

        self.narratives_generated_total = counter(
            "narrative_generated_total",
            "Total narratives generated by AI",
        )
        self.narratives_skipped_total = counter(
            "narrative_skipped_total",
            "Total signals skipped (direction=0 or Ollama failure)",
        )
        self.ollama_latency_ms = gauge(
            "narrative_ollama_latency_ms",
            "Ollama call latency in milliseconds",
        )
        self.service_uptime_seconds = gauge(
            "narrative_service_uptime_seconds",
            "Service uptime in seconds",
        )
        self.error_count_total = counter(
            "narrative_errors_total",
            "Total errors in narrative service",
        )

        self._total_narratives = 0
        self._error_count = 0
        self._stream_map: dict[str, tuple[str, str]] = {}

        self._build_chains()

        # In-memory cache: "SYMBOL:TF" → latest parsed signal dict (any direction)
        self._latest_signals: dict[str, dict] = {}
        # Lock for concurrent access to _latest_signals
        self._latest_signals_lock = asyncio.Lock()

        # Per-regime preferred models: {call_type: {regime: model_provider_id}}
        # Populated by _apply_score_routing; used at call time for regime-aware promotion.
        self._preferred_models: dict[str, dict[str, str]] = {}

        # Metrics for group synthesis
        self.group_narratives_generated = counter(
            "narrative_group_generated_total",
            "Total group narratives generated",
        )

        self.shutdown_event = asyncio.Event()

        self.logger = structlog.get_logger(__name__)
        start_metrics_server(port=9113)

    # ------------------------------------------------------------------
    # Chain construction
    # ------------------------------------------------------------------

    def _build_chains(self) -> None:
        from src.intelligence.llm_providers import (
            LLMChain,
            OllamaProvider,
            OpenRouterProvider,
            ZAIProvider,
        )

        settings = Settings()
        zai_key = settings.zai_api_key
        zai_url = settings.zai_base_url
        zai_model = settings.zai_model
        zai_timeout = settings.zai_timeout_sec
        or_key = settings.openrouter_api_key

        pcfg = self.config["providers"]
        or_url = pcfg["openrouter_base_url"]
        ol_url = pcfg["ollama_base_url"]

        def _make_provider(spec: dict):
            if spec["type"] == "zai":
                return ZAIProvider(
                    model=spec.get("model", zai_model),
                    api_key=zai_key,
                    base_url=zai_url,
                    timeout=zai_timeout,
                )
            if spec["type"] == "openrouter":
                return OpenRouterProvider(spec["model"], api_key=or_key, base_url=or_url)
            return OllamaProvider(spec["model"], base_url=ol_url)

        self.short_chain = LLMChain([_make_provider(s) for s in pcfg["narrative_short"]])
        self.deep_chain  = LLMChain([_make_provider(s) for s in pcfg["narrative_deep"]])
        self.group_chain = LLMChain([_make_provider(s) for s in pcfg["group"]])

        self._per_signal_timeout = float(pcfg["openrouter_timeout_sec"])
        self._group_timeout = float(pcfg["openrouter_timeout_sec"])

    # ------------------------------------------------------------------
    # Configuration
    # ------------------------------------------------------------------

    def _load_config(self, config_file: str | None) -> dict[str, Any]:
        try:
            _settings = Settings()
        except Exception:
            _settings = None

        default_config: dict[str, Any] = {
            "redis": {"host": "localhost", "port": 6379, "db": 0},
            "service": {
                "symbols": get_active_contracts(_settings),
                "timeframes": ["1m", "5m", "15m", "1h"],
                "processing_interval": 0.1,
                "health_check_interval": 30,
            },
            "ollama": {
                "base_url": "http://localhost:11434",
                "model": "qwen3.5:9b",
                "group_model": "phi4-mini:3.8b",
                "timeout_sec": 60.0,
                "num_predict": 500,
            },
            "providers": {
                "openrouter_base_url": "https://openrouter.ai/api/v1",
                "openrouter_timeout_sec": 30.0,
                "ollama_base_url": "http://localhost:11434",
                "ollama_timeout_sec": 60.0,
                "per_signal": [
                    # {"type": "zai",        "model": "glm-5"},           # Commented out: insufficient balance
                    # {"type": "openrouter", "model": "z-ai/glm-4.7-flash"},           # Bypassed: paid
                    # {"type": "openrouter", "model": "qwen/qwen3.5-flash-02-23"},     # Bypassed: paid
                    {"type": "openrouter", "model": "stepfun/step-3.5-flash:free"},
                    {"type": "openrouter", "model": "meta-llama/llama-3.3-70b-instruct:free"},
                    {"type": "openrouter", "model": "arcee-ai/trinity-large-preview:free"},
                    {"type": "ollama",     "model": "qwen3.5:9b"},
                ],
                "group": [
                    # {"type": "zai",        "model": "glm-5"},           # Commented out: insufficient balance
                    # {"type": "openrouter", "model": "z-ai/glm-4.7-flash"},           # Bypassed: paid
                    # {"type": "openrouter", "model": "qwen/qwen3.5-flash-02-23"},     # Bypassed: paid
                    {"type": "openrouter", "model": "stepfun/step-3.5-flash:free"},
                    {"type": "openrouter", "model": "arcee-ai/trinity-large-preview:free"},
                    {"type": "ollama",     "model": "phi4-mini:3.8b"},
                ],
                "narrative_short": [
                    # {"type": "openrouter", "model": "z-ai/glm-4.7-flash"},           # Bypassed: paid
                    # {"type": "openrouter", "model": "qwen/qwen3.5-flash-02-23"},     # Bypassed: paid
                    {"type": "openrouter", "model": "stepfun/step-3.5-flash:free"},
                    {"type": "openrouter", "model": "meta-llama/llama-3.3-70b-instruct:free"},
                    {"type": "openrouter", "model": "arcee-ai/trinity-large-preview:free"},
                    {"type": "ollama",     "model": "qwen3.5:9b"},
                ],
                "narrative_deep": [
                    # {"type": "openrouter", "model": "z-ai/glm-4.7-flash"},           # Bypassed: paid
                    # {"type": "openrouter", "model": "qwen/qwen3.5-flash-02-23"},     # Bypassed: paid
                    {"type": "openrouter", "model": "stepfun/step-3.5-flash:free"},
                    {"type": "openrouter", "model": "meta-llama/llama-3.3-70b-instruct:free"},
                    {"type": "openrouter", "model": "arcee-ai/trinity-large-preview:free"},
                    {"type": "ollama",     "model": "qwen3.5:9b"},
                ],
            },
            "logging": {
                "level": "INFO",
                "file": "logs/ai_narrative.log",
                "max_size": "10MB",
                "backup_count": 5,
            },
        }

        if config_file and Path(config_file).exists():
            with open(config_file) as f:
                user_config = json.load(f)
            for key, value in user_config.items():
                if isinstance(value, dict) and key in default_config:
                    default_config[key].update(value)
                else:
                    default_config[key] = value

        return default_config

    def _setup_logging(self) -> None:
        setup_service_logging(
            self.config["logging"]["file"],
            level=self.config["logging"].get("level", "INFO"),
            backup_count=self.config["logging"].get("backup_count", 5),
        )

    def _register_signal_handlers(self, loop: asyncio.AbstractEventLoop) -> None:
        """Register SIGINT/SIGTERM handlers that wake the asyncio event loop."""
        def _handle_signal() -> None:
            self.logger.info("Received shutdown signal")
            self.shutdown_requested = True
            self.running = False
            self.shutdown_event.set()

        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.add_signal_handler(sig, _handle_signal)
            except (NotImplementedError, RuntimeError):
                # Fallback for environments where add_signal_handler is not supported
                signal.signal(sig, lambda s, f: _handle_signal())

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def _connect_redis(self) -> None:
        self.redis_client = redis.Redis(
            host=self.config["redis"]["host"],
            port=self.config["redis"]["port"],
            db=self.config["redis"]["db"],
            decode_responses=False,
        )
        await self.redis_client.ping()
        self.logger.info("Connected to Redis")

    async def _setup_consumer_groups(self) -> None:
        for tf in self.config["service"]["timeframes"]:
            for sym in self.config["service"]["symbols"]:
                stream_name = signals_aggregated(self.env_prefix, sym, tf)
                await ensure_consumer_group_with_reset(
                    self.redis_client, stream_name, self.consumer_group
                )
                self._stream_map[stream_name] = (sym, tf)

    async def stop(self) -> None:
        self.logger.info("Stopping AI Narrative Service")
        self.running = False
        self.shutdown_requested = True
        if self.redis_client:
            await self.redis_client.aclose()
        self.logger.info("AI Narrative Service stopped")

    # ------------------------------------------------------------------
    # Per-message processing
    # ------------------------------------------------------------------

    async def _run_narrative_call(
        self,
        signal_data: dict[str, Any],
        symbol: str,
        timeframe: str,
        call_type: str,
        prompt: str,
        chain: Any,
    ) -> None:
        """Execute a single tier LLM call end-to-end: call chain, publish to llm_calls and narratives streams.

        Each tier (narrative_short, narrative_deep) runs independently as a background task.
        narrative_short additionally updates the backward-compat latest hash and increments metrics.
        """
        try:
            regime_key = signal_data.get("regime_context", "")
            preferred = (
                self._preferred_models.get(call_type, {}).get(regime_key)
                or self._preferred_models.get(call_type, {}).get("__all__")
            )
            if preferred:
                _promote_model_in_chain(chain, preferred)

            t0 = time.time()
            narrative_text = await chain.generate(
                prompt,
                SYSTEM_PROMPT,
                max_tokens=500,
                timeout=self._per_signal_timeout,
            )
            latency_ms = (time.time() - t0) * 1000

            # Emit LLM call record to llm_calls:stream
            if self.redis_client:
                call_payload = _build_llm_call_payload(
                    call_type=call_type,
                    signal_data=signal_data,
                    group_name="",
                    prompt=prompt,
                    response=narrative_text,
                    latency_ms=latency_ms,
                    succeeded=narrative_text is not None,
                    model_id=chain.last_provider_id or "",
                )
                await self.redis_client.xadd(
                    llm_calls_stream(self.env_prefix),
                    call_payload,
                    maxlen=500,
                    approximate=True,
                )

            if not narrative_text:
                self.narratives_skipped_total.inc()
                self.logger.warning(
                    "LLM returned no narrative",
                    symbol=symbol, timeframe=timeframe, call_type=call_type,
                )
                return

            # Publish to narratives stream with narrative_type discriminator
            narrative_type = call_type.replace("narrative_", "")  # "short" or "deep"
            stream_out = sk_narratives(self.env_prefix, symbol, timeframe)
            narrative_msg = {
                "symbol": symbol,
                "timeframe": timeframe,
                "timestamp": signal_data["timestamp"],
                "narrative": narrative_text,
                "narrative_type": narrative_type,
                "action_tag": build_action_tag(signal_data),
                "action_bias": signal_data["direction_label"].lower(),
                "confidence": str(signal_data["confidence"]),
                "model": chain.last_provider_id or "unknown",
                "latency_ms": str(int(latency_ms)),
            }
            if self.redis_client:
                await self.redis_client.xadd(
                    stream_out, narrative_msg, maxlen=100, approximate=True
                )

            # narrative_short: backward-compat latest hash + metrics + i8 enrichment
            if call_type == "narrative_short":
                if self.redis_client:
                    cache_key = f"{self.env_prefix}narrative:{symbol}:{timeframe}:latest"
                    await self.redis_client.hset(cache_key, mapping=narrative_msg)
                    await self.redis_client.expire(cache_key, 90)
                    i8_stream = sk_intelligence_i8(self.env_prefix, symbol, timeframe)
                    i8_msg = {
                        "ts": signal_data["timestamp"],
                        "symbol": symbol,
                        "tf": timeframe,
                        "model": chain.last_provider_id or "unknown",
                        "confidence": str(signal_data["confidence"]),
                        "summary": narrative_text[:280],
                        "generated_at": datetime.now(tz=UTC).isoformat(),
                    }
                    await self.redis_client.xadd(
                        i8_stream, i8_msg, maxlen=200, approximate=True
                    )
                self.narratives_generated_total.inc()
                self._total_narratives += 1
                self.ollama_latency_ms.set(latency_ms)
                self.logger.info(
                    "Narrative published",
                    symbol=symbol, timeframe=timeframe,
                    bias=signal_data["direction_label"],
                    latency_ms=round(latency_ms, 1),
                )

        except Exception as e:
            self.logger.error(
                "Error in _run_narrative_call",
                symbol=symbol, timeframe=timeframe,
                call_type=call_type, error=str(e),
            )
            self.error_count_total.inc()
            self._error_count += 1

    async def _process_single_message(
        self,
        symbol: str,
        timeframe: str,
        fields: dict[bytes, bytes],
        stream_name: str,
        message_id: bytes,
    ) -> bool:
        try:
            signal_data = parse_aggregated_signal(fields)
            if signal_data is None:
                self.narratives_skipped_total.inc()
                return True

            # Always cache latest signal for group synthesis (regardless of per-signal filter)
            cache_key_mem = f"{symbol}:{timeframe}"
            async with self._latest_signals_lock:
                self._latest_signals[cache_key_mem] = signal_data

            # Gate: per-signal narrative only for eligible TFs and high-confidence signals
            if timeframe not in _NARRATIVE_ELIGIBLE_TFS:
                self.narratives_skipped_total.inc()
                self.logger.debug(
                    "Per-signal narrative skipped: ineligible TF",
                    symbol=symbol, timeframe=timeframe,
                )
                return True

            if signal_data["confidence"] <= _NARRATIVE_MIN_CONFIDENCE:
                self.narratives_skipped_total.inc()
                self.logger.debug(
                    "Per-signal narrative skipped: low confidence",
                    symbol=symbol, timeframe=timeframe,
                    confidence=signal_data["confidence"],
                )
                # Counterfactual: log that we would have called, but didn't
                if self.redis_client:
                    cf_prompt = build_short_prompt(signal_data, extract_short_context(signal_data, {}))
                    cf_payload = _build_llm_call_payload(
                        call_type="counterfactual",
                        signal_data=signal_data,
                        group_name="",
                        prompt=cf_prompt,
                        response=None,
                        latency_ms=0.0,
                        succeeded=False,
                        model_id="",
                    )
                    asyncio.create_task(self.redis_client.xadd(
                        llm_calls_stream(self.env_prefix),
                        cf_payload,
                        maxlen=500,
                        approximate=True,
                    ))
                return True

            # Fetch intelligence context for richer prompts
            intel_ctx: dict[str, Any] = {}
            if self.redis_client:
                intel_stream = sk_intelligence(self.env_prefix, symbol, timeframe)
                raw_entries = await self.redis_client.xrevrange(intel_stream, count=1)
                if raw_entries:
                    _msg_id, raw_fields = raw_entries[0]
                    intel_ctx = {
                        (k.decode() if isinstance(k, bytes) else k): (
                            v.decode() if isinstance(v, bytes) else v
                        )
                        for k, v in raw_fields.items()
                    }

            # Build tier-specific prompts using intelligence context
            short_ctx = extract_short_context(signal_data, intel_ctx)
            deep_ctx = extract_deep_context(signal_data, intel_ctx)
            short_prompt = build_short_prompt(signal_data, short_ctx)
            deep_prompt = build_deep_prompt(signal_data, deep_ctx)

            # Fire both tier tasks concurrently — neither blocks the processing loop
            asyncio.create_task(self._run_narrative_call(
                signal_data, symbol, timeframe, "narrative_short", short_prompt, self.short_chain,
            ))
            asyncio.create_task(self._run_narrative_call(
                signal_data, symbol, timeframe, "narrative_deep", deep_prompt, self.deep_chain,
            ))
            return True

        except Exception as e:
            self.logger.error(
                "Error processing signal message",
                symbol=symbol,
                timeframe=timeframe,
                error=str(e),
            )
            self.error_count_total.inc()
            self._error_count += 1
            return False

    # ------------------------------------------------------------------
    # Main service loops
    # ------------------------------------------------------------------

    async def _process_loop(self) -> None:
        self.logger.info("Starting signal stream processing loop")
        all_streams = {name: ">" for name in self._stream_map}
        while self.running and not self.shutdown_requested:
            try:
                messages = await self.redis_client.xreadgroup(
                    self.consumer_group, self.consumer_name,
                    all_streams, count=10, block=1000,
                )
                for stream_bytes, msgs in messages:
                    stream_name = (
                        stream_bytes.decode()
                        if isinstance(stream_bytes, bytes)
                        else stream_bytes
                    )
                    symbol, timeframe = self._stream_map[stream_name]
                    to_ack: list[bytes] = []
                    for message_id, fields in msgs:
                        ok = await self._process_single_message(
                            symbol, timeframe, fields, stream_name, message_id
                        )
                        if ok:
                            to_ack.append(message_id)
                    if to_ack:
                        await self.redis_client.xack(
                            stream_name, self.consumer_group, *to_ack
                        )
            except asyncio.CancelledError:
                break
            except Exception as e:
                self.logger.error("Error in narrative processing loop", error=str(e))
                self.error_count_total.inc()
                self._error_count += 1
                await asyncio.sleep(1)

    async def _health_monitor_loop(self) -> None:
        while self.running and not self.shutdown_requested:
            try:
                uptime = int((datetime.now(tz=UTC) - self.start_time).total_seconds())
                self.service_uptime_seconds.set(uptime)
                interval = self.config["service"]["health_check_interval"]
                if uptime % interval == 0:
                    self.logger.info(
                        "Health check",
                        uptime=uptime,
                        narratives_generated=self._total_narratives,
                        errors=self._error_count,
                    )
                await asyncio.sleep(interval)
            except asyncio.CancelledError:
                break
            except Exception as e:
                self.logger.error("Error in health monitor", error=str(e))
                await asyncio.sleep(5)

    async def _score_refresh_loop(self) -> None:
        """Read Redis llm_scores cache every 5 min; promote significant winner."""
        _REFRESH_INTERVAL = 300  # 5 minutes
        self.logger.info("Starting score refresh loop")
        while self.running and not self.shutdown_requested:
            try:
                try:
                    await asyncio.wait_for(self.shutdown_event.wait(), timeout=_REFRESH_INTERVAL)
                    break  # shutdown
                except TimeoutError:
                    pass
                if self.shutdown_requested:
                    break
                await self._apply_score_routing()
            except asyncio.CancelledError:
                break
            except Exception as e:
                self.logger.warning("Score refresh error", error=str(e))
                await asyncio.sleep(30)

    async def _apply_score_routing(self) -> None:
        """Read Redis score cache and promote significant winner per call_type+regime."""
        if not self.redis_client:
            return
        new_preferred: dict[str, dict[str, str]] = {}
        for call_type, _chain in [
            ("narrative_short", self.short_chain),
            ("narrative_deep",  self.deep_chain),
            ("group_synthesis", self.group_chain),
        ]:
            regime_winners: dict[str, str] = {}
            for regime in ("trending", "ranging", "volatile", "__all__"):
                cache_key = llm_scores_cache(self.env_prefix, call_type, regime)
                try:
                    raw = await self.redis_client.hgetall(cache_key)
                except Exception:
                    continue
                best_model: str | None = None
                best_avg_pnl_r: float = float("-inf")
                for model_bytes, blob_bytes in (raw or {}).items():
                    try:
                        blob = json.loads(
                            blob_bytes.decode() if isinstance(blob_bytes, bytes) else blob_bytes
                        )
                        pnl_r = float(blob.get("avg_pnl_r", 0))
                        if blob.get("is_significant") and pnl_r > best_avg_pnl_r:
                            best_avg_pnl_r = pnl_r
                            best_model = (
                                model_bytes.decode()
                                if isinstance(model_bytes, bytes)
                                else model_bytes
                            )
                    except Exception:
                        continue
                if best_model:
                    regime_winners[regime] = best_model
                    self.logger.info(
                        "Per-regime provider preferred",
                        call_type=call_type,
                        regime=regime,
                        model=best_model,
                        avg_pnl_r=best_avg_pnl_r,
                    )
            new_preferred[call_type] = regime_winners
        self._preferred_models = new_preferred

    async def _synthesize_group(self, group_name: str) -> None:
        """Check if group state changed and publish synthesis if so."""
        group_symbols = ASSET_GROUPS.get(group_name, [])

        # Gather current signals for this group across synthesis TFs
        current_signals: dict[str, dict] = {}
        for sym in group_symbols:
            for tf in _GROUP_SYNTHESIS_TFS:
                key = f"{sym}:{tf}"
                async with self._latest_signals_lock:
                    sig = self._latest_signals.get(key)
                if sig and sig.get("direction", 0) != 0:
                    current_signals[key] = sig

        # Compute fingerprint
        current_fp = extract_group_fingerprint(current_signals)

        # Compare with persisted state
        state_redis_key = f"{self.env_prefix}narrative:group:{group_name}:state"
        raw_state = await self.redis_client.hget(state_redis_key, "fingerprint_json")
        prior_fp_raw = json.loads(raw_state) if raw_state else {}
        # Redis JSON round-trip: tuples become lists; normalize for comparison
        prior_fp = {k: tuple(v) for k, v in prior_fp_raw.items()}

        if current_fp == prior_fp:
            return  # Nothing changed

        # Persist fingerprint BEFORE calling Ollama so a timeout/error doesn't
        # cause a retry loop on the next 30-second cycle.  If signals change
        # *during* the call the next iteration will detect the new fingerprint.
        await self.redis_client.hset(
            state_redis_key,
            "fingerprint_json",
            json.dumps({k: list(v) for k, v in current_fp.items()}),
        )
        await self.redis_client.expire(state_redis_key, 86400)  # 24h TTL

        # Build prompt and call group chain
        prompt = build_group_synthesis_prompt(group_name, current_signals)
        # Use __all__ regime entry for group synthesis (cross-symbol, no single regime)
        gs_preferred = self._preferred_models.get("group_synthesis", {}).get("__all__")
        if gs_preferred:
            _promote_model_in_chain(self.group_chain, gs_preferred)
        t0 = time.time()
        narrative_text = await self.group_chain.generate(
            prompt,
            GROUP_SYSTEM_PROMPT,
            max_tokens=300,
            timeout=self._group_timeout,
        )
        latency_ms = (time.time() - t0) * 1000

        # Emit group synthesis LLM call record — fire-and-forget
        if self.redis_client:
            gs_payload = _build_llm_call_payload(
                call_type="group_synthesis",
                signal_data=None,
                group_name=group_name,
                prompt=prompt,
                response=narrative_text,
                latency_ms=latency_ms,
                succeeded=narrative_text is not None,
                model_id=self.group_chain.last_provider_id or "",
            )
            asyncio.create_task(self.redis_client.xadd(
                llm_calls_stream(self.env_prefix),
                gs_payload,
                maxlen=500,
                approximate=True,
            ))

        if narrative_text:
            from src.core.stream_keys import narratives_group as sk_narratives_group
            stream_out = sk_narratives_group(self.env_prefix, group_name)
            ts = datetime.now(tz=UTC).isoformat()
            msg = {
                "group": group_name,
                "narrative": narrative_text,
                "timestamp": ts,
                "model": self.group_chain.last_provider_id or "unknown",
                "latency_ms": str(int(latency_ms)),
            }
            await self.redis_client.xadd(stream_out, msg, maxlen=50, approximate=True)
            cache_key_hash = f"{self.env_prefix}narrative:group:{group_name}:latest"
            await self.redis_client.hset(cache_key_hash, mapping=msg)
            await self.redis_client.expire(cache_key_hash, 3600)  # 1 hour TTL

            self.group_narratives_generated.inc()
            self.logger.info(
                "Group narrative published",
                group=group_name,
                signals=len(current_signals),
                latency_ms=round(latency_ms, 1),
            )
        else:
            self.logger.warning("Group Ollama returned no narrative", group=group_name)

    async def _group_synthesis_loop(self) -> None:
        """Run group synthesis every 30s — fires Ollama only on material changes."""
        self.logger.info("Starting group synthesis loop")
        while self.running and not self.shutdown_requested:
            try:
                try:
                    await asyncio.wait_for(self.shutdown_event.wait(), timeout=30)
                    break  # shutdown requested
                except TimeoutError:
                    pass  # normal — run synthesis
                if self.shutdown_requested:
                    break
                for group_name in ASSET_GROUPS:
                    if self.shutdown_requested:
                        break
                    try:
                        await self._synthesize_group(group_name)
                    except Exception as exc:
                        self.logger.error(
                            "Group synthesis failed", group=group_name, error=str(exc)
                        )
            except asyncio.CancelledError:
                break
            except Exception as exc:
                self.logger.error("Error in group synthesis loop", error=str(exc))
                await asyncio.sleep(5)

    async def start(self) -> None:
        self.logger.info("Starting AI Narrative Service", config=self.config["service"])
        try:
            loop = asyncio.get_running_loop()
            self._register_signal_handlers(loop)
            await self._connect_redis()
            await self._setup_consumer_groups()

            self.running = True
            # Apply routing at startup (before any LLM calls)
            await self._apply_score_routing()
            tasks = [
                asyncio.create_task(self._process_loop()),
                asyncio.create_task(self._health_monitor_loop()),
                asyncio.create_task(self._group_synthesis_loop()),
                asyncio.create_task(self._score_refresh_loop()),
            ]
            self.logger.info("AI Narrative Service started")
            await asyncio.gather(*tasks, return_exceptions=True)
        except Exception as e:
            self.logger.error("Failed to start service", error=str(e))
            raise
        finally:
            await self.stop()


async def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="AI Narrative Service")
    parser.add_argument("--config", help="Configuration file path")
    parser.add_argument("--foreground", action="store_true", help="Run in foreground")
    args = parser.parse_args()

    svc = AINarrativeService(args.config)

    if args.foreground:
        print("Starting AI Narrative Service in foreground...")
        print("Press Ctrl+C to stop")

    try:
        await svc.start()
    except KeyboardInterrupt:
        print("\nService stopped by user")
    except Exception as e:
        print(f"Service failed: {e}")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
