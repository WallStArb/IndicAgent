# I8 Narrative Three-Tier Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Replace the single thin narrative call with a three-tier system: deterministic signal bar (instant), short narrative (2-sentence Context+Execution, ~500ms), deep narrative (3-sentence confluence story, ~5-8s).

**Architecture:** At signal time, fetch intelligence context via XREVRANGE on `intelligence:SYMBOL:TF`. Fire two concurrent async tasks — `narrative_short` and `narrative_deep` — each publishing independently to the narratives stream when ready. Dashboard renders signal bar immediately from signal data, short narrative on arrival, deep narrative on expand. No model hardcoding; routing system optimizes each call type independently.

**Tech Stack:** Python asyncio, Redis streams (xrevrange), Next.js/TypeScript, OpenRouter via LLMChain, existing `_apply_score_routing()` + `llm_writer_service`

**Design doc:** `docs/plans/2026-03-09-i8-narrative-redesign.md`
**Supersedes:** `docs/plans/2026-03-08-i8-narrative-implementation.md`

---

## Task 1: Intelligence Context Extraction (pure functions)

**Files:**
- Modify: `services/ai_narrative_service.py`
- Test: `tests/unit/service_tests/test_ai_narrative_helpers.py`

These are pure functions with no I/O — easy to test in isolation. They sit alongside `build_narrative_prompt()` (which will be retired in Task 4).

**Step 1: Write the failing tests**

Add to `tests/unit/service_tests/test_ai_narrative_helpers.py`:

```python
from services.ai_narrative_service import (
    extract_short_context,
    extract_deep_context,
    build_short_prompt,
    build_deep_prompt,
    build_action_tag,
    get_structural_label,
)

_SIGNAL = {
    "symbol": "GCJ6", "timeframe": "5m", "direction": 1,
    "direction_label": "Bullish", "confidence": 0.78,
    "setup_plugin": "LiquiditySweepReclaim", "signal_type": "sweep_long",
    "entry_price": "5108.7", "stop_loss": "5100.47",
    "profit_target": "5143.84", "risk_reward_ratio": "4.27",
    "regime_context": "bullish", "supporting_factors": "ma_alignment_bullish,fvg_fill",
    "signal_id": "sig-abc123", "timestamp": "2026-03-09T14:20:00Z",
}

_INTEL = {
    "hmm_regime": "2", "hmm_regime_prob": "0.87",
    "fvg_bottom": "5095.0", "fvg_top": "5108.0",
    "ob_bottom": "5099.0", "ob_top": "5110.0",
    "confluence_score": "0.82", "trend_confluence_score": "0.75",
    "killzone_name": "london", "in_london_killzone": "1",
    "nearest_demand_low": "5090.0", "nearest_demand_high": "5098.0",
}

def test_extract_short_context_includes_regime():
    ctx = extract_short_context(_SIGNAL, _INTEL)
    assert ctx["hmm_regime"] == "2"
    assert ctx["hmm_regime_prob"] == "0.87"
    assert ctx["killzone"] == "london"

def test_extract_short_context_includes_signal_fields():
    ctx = extract_short_context(_SIGNAL, _INTEL)
    assert ctx["confidence"] == 0.78
    assert ctx["entry"] == "5108.7"
    assert ctx["stop"] == "5100.47"
    assert ctx["target_1"] == "5143.84"

def test_extract_short_context_empty_intel():
    ctx = extract_short_context(_SIGNAL, {})
    assert ctx["entry"] == "5108.7"
    assert ctx["hmm_regime"] is None

def test_extract_deep_context_includes_fvg_bounds():
    ctx = extract_deep_context(_SIGNAL, _INTEL)
    assert ctx["fvg_bottom"] == "5095.0"
    assert ctx["fvg_top"] == "5108.0"
    assert ctx["ob_bottom"] == "5099.0"

def test_extract_deep_context_is_superset_of_short():
    short = extract_short_context(_SIGNAL, _INTEL)
    deep = extract_deep_context(_SIGNAL, _INTEL)
    for key in short:
        assert key in deep

def test_build_short_prompt_contains_key_fields():
    ctx = extract_short_context(_SIGNAL, _INTEL)
    prompt = build_short_prompt(_SIGNAL, ctx)
    assert "5108.7" in prompt
    assert "5100.47" in prompt
    assert "78%" in prompt or "0.78" in prompt
    assert "london" in prompt.lower() or "killzone" in prompt.lower()

def test_build_short_prompt_includes_confidence_instruction():
    ctx = extract_short_context(_SIGNAL, _INTEL)
    prompt = build_short_prompt(_SIGNAL, ctx)
    # High confidence (78%) → must instruct direct entry
    assert "direct" in prompt.lower() or "entry" in prompt.lower() or "act now" in prompt.lower()

def test_build_short_prompt_low_confidence_instructs_wait():
    low_signal = {**_SIGNAL, "confidence": 0.52}
    ctx = extract_short_context(low_signal, _INTEL)
    prompt = build_short_prompt(low_signal, ctx)
    assert "wait" in prompt.lower() or "conditional" in prompt.lower()

def test_build_deep_prompt_contains_fvg_bounds():
    ctx = extract_deep_context(_SIGNAL, _INTEL)
    prompt = build_deep_prompt(_SIGNAL, ctx)
    assert "5095" in prompt or "fvg" in prompt.lower()

def test_build_action_tag_high_confidence_bullish():
    tag = build_action_tag(_SIGNAL)
    assert "BULLISH" in tag
    assert "WAIT" not in tag

def test_build_action_tag_mid_confidence_shows_wait():
    sig = {**_SIGNAL, "confidence": 0.60}
    tag = build_action_tag(sig)
    assert "WAIT" in tag
    assert "BULLISH" in tag

def test_build_action_tag_low_confidence_shows_monitor():
    sig = {**_SIGNAL, "confidence": 0.40}
    tag = build_action_tag(sig)
    assert "MONITOR" in tag

def test_build_action_tag_bearish():
    sig = {**_SIGNAL, "direction": -1, "direction_label": "Bearish"}
    tag = build_action_tag(sig)
    assert "BEARISH" in tag

def test_get_structural_label_sweep():
    assert get_structural_label("LiquiditySweepReclaim") == "SWEEP RECLAIM"

def test_get_structural_label_fvg():
    assert get_structural_label("FVGFill") == "FVG FILL"

def test_get_structural_label_choch():
    assert get_structural_label("CHoCHReversal") == "REVERSAL"

def test_get_structural_label_unknown():
    label = get_structural_label("UnknownPlugin")
    assert isinstance(label, str)
    assert len(label) > 0
```

**Step 2: Run to confirm failure**

```bash
.venv/bin/pytest tests/unit/service_tests/test_ai_narrative_helpers.py -x -q 2>&1 | head -20
```
Expected: ImportError (functions don't exist yet)

**Step 3: Implement the functions**

Add to `services/ai_narrative_service.py` below `build_narrative_prompt()`:

```python
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

    >75%: [BULLISH RECLAIM] / [BEARISH BREAKDOWN]
    50-75%: [WAIT — BULLISH] / [WAIT — BEARISH]
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
        return f"[WAIT — {direction_word}]"


def extract_short_context(signal: dict[str, Any], intel: dict[str, Any]) -> dict[str, Any]:
    """Pre-digest intelligence data for the short narrative prompt.

    Only the conclusion-level fields — regime label, top structural event,
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
    ctx.update({
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
    })
    return ctx


def build_short_prompt(signal: dict[str, Any], ctx: dict[str, Any]) -> str:
    """Build the short narrative user prompt (2-sentence Context+Execution)."""
    confidence = ctx["confidence"]
    confidence_pct = f"{confidence:.0%}"

    # Confidence-gated execution instruction
    if confidence >= 0.75:
        execution_instruction = (
            f"Sentence 2 (Execution — DIRECT): State the exact entry price and stop. "
            f"This is high-conviction — tell the PM to act now at {ctx['entry']} "
            f"with stop at {ctx['stop']}."
        )
    elif confidence >= 0.50:
        execution_instruction = (
            f"Sentence 2 (Execution — CONDITIONAL): Name the exact condition the PM "
            f"must wait for before entering. Entry {ctx['entry']}, stop {ctx['stop']}."
        )
    else:
        execution_instruction = (
            f"Sentence 2 (Monitor): Name what level or condition would confirm this "
            f"setup before acting. Frame as 'watch' not 'enter'."
        )

    regime_line = ""
    if ctx.get("hmm_regime_label") and ctx.get("hmm_regime_prob"):
        regime_line = (
            f"Regime: {ctx['hmm_regime_label']} "
            f"(HMM state {ctx['hmm_regime']}, prob {float(ctx['hmm_regime_prob']):.0%})\n"
        )

    killzone_line = f"Killzone: {ctx['killzone']} open active\n" if ctx.get("killzone") else ""
    confluence_line = (
        f"Confluence: {ctx['confluence_score']}\n" if ctx.get("confluence_score") else ""
    )

    return (
        f"/no_think\n\n"
        f"Symbol: {ctx['symbol']} {ctx['timeframe']} — {ctx['direction_label']} "
        f"(confidence {confidence_pct})\n"
        f"Structure: {ctx['structural_label']}\n"
        f"{regime_line}"
        f"{killzone_line}"
        f"{confluence_line}"
        f"Entry: {ctx['entry']} | Stop: {ctx['stop']} | T1: {ctx['target_1']} (R:R {ctx['rr']})\n\n"
        f"Write exactly 2 sentences:\n"
        f"Sentence 1 (Context — STRUCTURAL): What is the market doing right now and why "
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
        fvg_line = f"FVG: {ctx['fvg_bottom']}–{ctx['fvg_top']}\n"

    ob_line = ""
    if ctx.get("ob_bottom") and ctx.get("ob_top"):
        ob_line = f"Order Block: {ctx['ob_bottom']}–{ctx['ob_top']}\n"

    sd_line = ""
    if ctx.get("nearest_demand_low") and ctx.get("nearest_demand_high"):
        sd_line = (
            f"Demand Zone: {ctx['nearest_demand_low']}–{ctx['nearest_demand_high']}\n"
        )
    elif ctx.get("nearest_supply_low") and ctx.get("nearest_supply_high"):
        sd_line = (
            f"Supply Zone: {ctx['nearest_supply_low']}–{ctx['nearest_supply_high']}\n"
        )

    regime_line = ""
    if ctx.get("hmm_regime_label") and ctx.get("hmm_regime_prob"):
        regime_line = (
            f"Regime: {ctx['hmm_regime_label']} "
            f"(HMM state {ctx['hmm_regime']}, prob {float(ctx['hmm_regime_prob']):.0%})\n"
        )

    factors_line = (
        f"Supporting factors: {ctx['supporting_factors']}\n"
        if ctx.get("supporting_factors") else ""
    )

    return (
        f"/no_think\n\n"
        f"Symbol: {ctx['symbol']} {ctx['timeframe']} — {ctx['direction_label']} "
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
        f"Sentence 1 (Confluence): Name every source aligning — which timeframes, "
        f"what SMC structure, what HMM state, what zone. Be specific with level names.\n"
        f"Sentence 2 (Key Levels): Entry rationale (not just the price — why THIS level). "
        f"Stop placement logic. T1 target significance.\n"
        f"Sentence 3 (Guidance + Invalidation): Confidence-weighted sizing or timing "
        f"guidance. Always end with what would invalidate this thesis."
    )
```

**Step 4: Run tests**

```bash
.venv/bin/pytest tests/unit/service_tests/test_ai_narrative_helpers.py -v 2>&1 | tail -20
```
Expected: all new tests pass

**Step 5: Commit**

```bash
git add services/ai_narrative_service.py tests/unit/service_tests/test_ai_narrative_helpers.py
git commit -m "feat(i8): add intelligence context extraction and three-tier prompt builders"
```

---

## Task 2: Update System Prompt and Chains

**Files:**
- Modify: `services/ai_narrative_service.py` (lines 51–57 SYSTEM_PROMPT, lines 330–362 `_build_chains`)
- Test: `tests/unit/service_tests/test_ai_narrative_service.py`

**Step 1: Write failing test for system prompt voice**

Add to `tests/unit/service_tests/test_ai_narrative_service.py`:

```python
from services.ai_narrative_service import SYSTEM_PROMPT

def test_system_prompt_prohibits_passive_voice_phrases():
    banned = ["capitalize", "execute long", "protect the position", "suggests", "price momentum"]
    for phrase in banned:
        assert phrase not in SYSTEM_PROMPT.lower(), f"Banned phrase found: {phrase}"

def test_system_prompt_establishes_analyst_voice():
    assert "trading desk" in SYSTEM_PROMPT.lower() or "analyst" in SYSTEM_PROMPT.lower()
    assert "passive voice" in SYSTEM_PROMPT.lower() or "precise" in SYSTEM_PROMPT.lower()

def test_service_has_short_chain():
    svc = AIMarketNarrativeService.__new__(AIMarketNarrativeService)
    svc._build_chains()
    assert hasattr(svc, "short_chain")
    assert hasattr(svc, "deep_chain")

def test_service_short_chain_is_separate_from_deep_chain():
    svc = AIMarketNarrativeService.__new__(AIMarketNarrativeService)
    svc._build_chains()
    assert svc.short_chain is not svc.deep_chain
```

**Step 2: Run to confirm failure**

```bash
.venv/bin/pytest tests/unit/service_tests/test_ai_narrative_service.py::test_system_prompt_prohibits_passive_voice_phrases tests/unit/service_tests/test_ai_narrative_service.py::test_service_has_short_chain -v
```

**Step 3: Replace SYSTEM_PROMPT and update _build_chains**

Replace the `SYSTEM_PROMPT` constant (lines ~51–57):

```python
SYSTEM_PROMPT = (
    "You are a senior trading desk analyst briefing a portfolio manager. "
    "Write with precision and economy — every word must earn its place. "
    "Never use passive voice. "
    "Never hedge with 'suggests' or 'indicates' — the system computed these signals "
    "with statistical confidence; state conclusions directly. "
    "Never restate the setup name or direction label — the PM already sees those. "
    "Never use these phrases: 'capitalize on', 'execute long orders', "
    "'protect the position', 'price momentum suggests', 'within the established regime', "
    "'deliver a risk-to-reward'. "
    "Your job: explain WHY this structure matters right now and WHAT to do about it."
)
```

In `_build_chains()`, add `short_chain` and `deep_chain` alongside existing chains:

```python
    self.short_chain = LLMChain([_make_provider(s) for s in pcfg["narrative_short"]])
    self.deep_chain  = LLMChain([_make_provider(s) for s in pcfg["narrative_deep"]])
    # Keep per_signal_chain as alias during transition (removed in Task 3)
    self.per_signal_chain = self.short_chain
    self.group_chain = LLMChain([_make_provider(s) for s in pcfg["group"]])
```

Add `narrative_short` and `narrative_deep` provider configs to the JSON config file. Find it:

```bash
grep -n "config\|providers\|per_signal" services/ai_narrative_service.py | grep "load\|open\|json\|config" | head -5
```

Add to the config JSON (same providers as `per_signal` initially — routing optimizes over time):
```json
"narrative_short": [
    {"type": "openrouter", "model": "z-ai/glm-4.7-flash"}
],
"narrative_deep": [
    {"type": "openrouter", "model": "z-ai/glm-4.7-flash"}
]
```

**Step 4: Update `_apply_score_routing()` to include new call types**

Replace the chain loop:
```python
        for call_type, _chain in [
            ("narrative_short", self.short_chain),
            ("narrative_deep",  self.deep_chain),
            ("group_synthesis", self.group_chain),
        ]:
```

**Step 5: Run tests**

```bash
.venv/bin/pytest tests/unit/service_tests/test_ai_narrative_service.py -v 2>&1 | tail -20
```

**Step 6: Commit**

```bash
git add services/ai_narrative_service.py
git commit -m "feat(i8): replace per_signal chain with short/deep chains, update system prompt voice"
```

---

## Task 3: Fetch Intelligence Context + Two Concurrent Calls

**Files:**
- Modify: `services/ai_narrative_service.py` — `_process_single_message()`
- Add import: `from src.core.stream_keys import intelligence as sk_intelligence`
- Test: `tests/unit/service_tests/test_ai_narrative_service.py`

**Step 1: Write failing tests**

```python
@pytest.mark.asyncio
async def test_process_message_fires_two_narrative_tasks():
    """Both narrative_short and narrative_deep are published for a high-confidence signal."""
    svc = AIMarketNarrativeService.__new__(AIMarketNarrativeService)
    svc.narratives_skipped_total = MagicMock(); svc.narratives_skipped_total.inc = MagicMock()
    svc.narratives_generated_total = MagicMock(); svc.narratives_generated_total.inc = MagicMock()
    svc.ollama_latency_ms = MagicMock(); svc.ollama_latency_ms.set = MagicMock()
    svc.error_count_total = MagicMock(); svc.error_count_total.inc = MagicMock()
    svc.logger = structlog.get_logger()
    svc._latest_signals = {}
    svc._latest_signals_lock = asyncio.Lock()
    svc._preferred_models = {}
    svc._error_count = 0
    svc._total_narratives = 0
    svc.env_prefix = "test:"
    svc._per_signal_timeout = 30.0

    published_call_types = []
    async def mock_xadd(stream, data, **kwargs):
        if "call_type" in data:
            published_call_types.append(data["call_type"])
        return b"1234-0"

    mock_redis = AsyncMock()
    mock_redis.xrevrange = AsyncMock(return_value=[])  # no intel context
    mock_redis.xadd = mock_xadd
    svc.redis_client = mock_redis

    mock_chain = AsyncMock()
    mock_chain.generate = AsyncMock(return_value="Test narrative.")
    mock_chain.last_provider_id = "openrouter/glm-4.7"
    svc.short_chain = mock_chain
    svc.deep_chain = mock_chain

    fields = {
        b"symbol": b"ESH6", b"timeframe": b"5m", b"direction": b"1",
        b"confidence": b"0.80", b"setup_plugin": b"TrendFollowing",
        b"entry_price": b"6650.0", b"stop_loss": b"6640.0",
        b"profit_target": b"6670.0", b"risk_reward_ratio": b"2.0",
        b"regime_context": b"bullish", b"supporting_factors": b"",
        b"signal_id": b"sig-1", b"timestamp": b"2026-03-09T14:00:00Z",
        b"direction_label": b"Bullish", b"confluence_score": b"0.75",
        b"signal_type": b"trend_long",
    }

    result = await svc._process_single_message("ESH6", "5m", fields, "stream", b"1-0")
    # Allow background tasks to complete
    await asyncio.sleep(0.1)

    assert result is True
    assert "narrative_short" in published_call_types
    assert "narrative_deep" in published_call_types

@pytest.mark.asyncio
async def test_narrative_stream_message_has_type_field():
    """Published narrative messages include a 'narrative_type' field."""
    # Similar setup as above...
    # Assert that xadd calls include "narrative_type": "short" or "narrative_type": "deep"
    pass  # Implement after verifying first test passes
```

**Step 2: Run to confirm failure**

```bash
.venv/bin/pytest tests/unit/service_tests/test_ai_narrative_service.py::test_process_message_fires_two_narrative_tasks -v
```

**Step 3: Rewrite `_process_single_message()`**

Replace the per-signal LLM call section with two concurrent background tasks:

```python
            # Fetch intelligence context for enriched prompts
            intel_ctx: dict[str, Any] = {}
            if self.redis_client:
                intel_stream = sk_intelligence(self.env_prefix, symbol, timeframe)
                try:
                    msgs = await self.redis_client.xrevrange(intel_stream, count=1)
                    if msgs:
                        raw_fields = msgs[0][1]
                        intel_ctx = {
                            k.decode() if isinstance(k, bytes) else k:
                            v.decode() if isinstance(v, bytes) else v
                            for k, v in raw_fields.items()
                        }
                except Exception as e:
                    self.logger.warning("Intelligence context fetch failed", error=str(e))

            short_ctx = extract_short_context(signal_data, intel_ctx)
            deep_ctx  = extract_deep_context(signal_data, intel_ctx)
            short_prompt = build_short_prompt(signal_data, short_ctx)
            deep_prompt  = build_deep_prompt(signal_data, deep_ctx)

            # Fire both calls as background tasks — each publishes when ready
            asyncio.create_task(
                self._run_narrative_call(
                    signal_data, symbol, timeframe,
                    "narrative_short", short_prompt, self.short_chain,
                )
            )
            asyncio.create_task(
                self._run_narrative_call(
                    signal_data, symbol, timeframe,
                    "narrative_deep", deep_prompt, self.deep_chain,
                )
            )
            return True
```

Add new method `_run_narrative_call()`:

```python
    async def _run_narrative_call(
        self,
        signal_data: dict[str, Any],
        symbol: str,
        timeframe: str,
        call_type: str,
        prompt: str,
        chain: Any,
    ) -> None:
        """Run a single narrative LLM call and publish result to the narratives stream."""
        regime_key = signal_data.get("regime_context", "")
        preferred = (
            self._preferred_models.get(call_type, {}).get(regime_key)
            or self._preferred_models.get(call_type, {}).get("__all__")
        )
        if preferred:
            _promote_model_in_chain(chain, preferred)

        t0 = time.time()
        try:
            narrative_text = await chain.generate(
                prompt, SYSTEM_PROMPT,
                max_tokens=500,
                timeout=self._per_signal_timeout,
            )
        except Exception as e:
            self.logger.warning("Narrative call failed", call_type=call_type, error=str(e))
            narrative_text = None
        latency_ms = (time.time() - t0) * 1000

        if self.redis_client:
            payload = _build_llm_call_payload(
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
                llm_calls_stream(self.env_prefix), payload, maxlen=500, approximate=True
            )

        if narrative_text and self.redis_client:
            stream_out = sk_narratives(self.env_prefix, symbol, timeframe)
            msg = {
                "symbol": symbol,
                "timeframe": timeframe,
                "timestamp": signal_data["timestamp"],
                "signal_id": signal_data.get("signal_id", ""),
                "narrative_type": call_type.replace("narrative_", ""),  # "short" | "deep"
                "narrative": narrative_text,
                "action_bias": signal_data["direction_label"].lower(),
                "action_tag": build_action_tag(signal_data),
                "confidence": str(signal_data["confidence"]),
                "model": chain.last_provider_id or "unknown",
                "latency_ms": str(int(latency_ms)),
            }
            await self.redis_client.xadd(stream_out, msg, maxlen=100, approximate=True)

            if call_type == "narrative_short":
                # Update latest hash (short is the "primary" for backward compat)
                cache_key = f"{self.env_prefix}narrative:{symbol}:{timeframe}:latest"
                await self.redis_client.hset(cache_key, mapping=msg)
                await self.redis_client.expire(cache_key, 90)
                self.narratives_generated_total.inc()
                self._total_narratives += 1
                self.ollama_latency_ms.set(latency_ms)

        self.logger.info(
            "Narrative published",
            call_type=call_type,
            symbol=symbol,
            timeframe=timeframe,
            latency_ms=round(latency_ms, 1),
        )
```

Also add `sk_intelligence` import:
```python
from src.core.stream_keys import intelligence as sk_intelligence  # noqa: E402
```

**Step 4: Run all narrative service tests**

```bash
.venv/bin/pytest tests/unit/service_tests/test_ai_narrative_service.py tests/unit/service_tests/test_ai_narrative_helpers.py -v 2>&1 | tail -30
```

Expected: all pass. Fix any tests that used `per_signal` call_type — update to `narrative_short`.

**Step 5: Commit**

```bash
git add services/ai_narrative_service.py
git commit -m "feat(i8): two concurrent narrative calls with intelligence context enrichment"
```

---

## Task 4: Update Dashboard Types and Stream Handler

**Files:**
- Modify: `dashboard/src/lib/types.ts`
- Modify: `dashboard/src/hooks/use-market-stream.ts`

**Step 1: Update NarrativeData type**

In `dashboard/src/lib/types.ts`, replace `NarrativeData`:

```typescript
export interface NarrativeData {
  symbol: string;
  timeframe: string;
  action_bias: string;           // "bullish" | "bearish"
  action_tag: string;            // "[BULLISH RECLAIM]" etc. — from signal data
  narrative_short?: string;      // 2-sentence Context+Execution
  narrative_deep?: string;       // 3-sentence confluence story (arrives later)
  timestamp: string;
  receivedAt: number;
  signal_id?: string;            // correlates short + deep events
  // Keep for backward compat during transition
  narrative?: string;
}
```

**Step 2: Update SSE handler in use-market-stream.ts**

Replace the `narrative_data` event handler (around line 650):

```typescript
es.addEventListener("narrative_data", (evt) => {
  try {
    const payload = JSON.parse((evt as MessageEvent).data);
    const narrativeType: string = payload.narrative_type ?? "short";

    // Group synthesis narrative
    if (payload.group) {
      const groupName = String(payload.group);
      if (!groupName || !payload.narrative) return;
      setGroupNarratives(prev => ({
        ...prev,
        [groupName]: {
          group: groupName,
          narrative: String(payload.narrative),
          timestamp: String(payload.timestamp ?? ""),
          receivedAt: Date.now(),
          model: String(payload.model ?? ""),
        },
      }));
      return;
    }

    // Per-symbol narrative — merge short and deep into same entry
    const sym = String(payload.symbol ?? "");
    const tf  = String(payload.timeframe ?? "");
    if (!sym || !tf) return;
    const key = `${sym}:${tf}`;

    setNarratives(prev => {
      const existing = prev[key] ?? {
        symbol: sym, timeframe: tf,
        action_bias: "", action_tag: "",
        timestamp: "", receivedAt: 0,
      };
      return {
        ...prev,
        [key]: {
          ...existing,
          action_bias: String(payload.action_bias ?? existing.action_bias),
          action_tag:  String(payload.action_tag  ?? existing.action_tag),
          timestamp:   String(payload.timestamp   ?? existing.timestamp),
          signal_id:   String(payload.signal_id   ?? existing.signal_id ?? ""),
          receivedAt: Date.now(),
          ...(narrativeType === "short"
            ? { narrative_short: String(payload.narrative), narrative: String(payload.narrative) }
            : { narrative_deep:  String(payload.narrative) }
          ),
        },
      };
    });
  } catch {
    // malformed event
  }
});
```

**Step 3: Run TypeScript check**

```bash
cd dashboard && npx tsc --noEmit 2>&1 | head -30
```

Fix any type errors. Expected: no errors.

**Step 4: Commit**

```bash
git add dashboard/src/lib/types.ts dashboard/src/hooks/use-market-stream.ts
git commit -m "feat(i8): update NarrativeData types and SSE handler for two-tier narratives"
```

---

## Task 5: Update Narrative Panel UI

**Files:**
- Modify: `dashboard/src/components/narrative-panel.tsx`

**Step 1: Read current component**

```bash
cat dashboard/src/components/narrative-panel.tsx
```

**Step 2: Update to three-tier layout**

The panel should:
1. Show `action_tag` as a badge above the narrative (deterministic, always available from signal data)
2. Show `narrative_short` as the primary text (2 sentences)
3. Show an expand/collapse toggle for `narrative_deep`
4. Show a subtle skeleton/spinner if `narrative_short` is missing but signal exists

Key pattern (add expand state):
```typescript
const [expanded, setExpanded] = useState(false);

// action_tag from narrative data (or derive it client-side from signal data)
const actionTag = narrative?.action_tag ?? "";
const shortText = narrative?.narrative_short ?? narrative?.narrative ?? null;
const deepText  = narrative?.narrative_deep ?? null;
```

Render:
```tsx
{actionTag && (
  <div className="text-xs font-mono text-amber-400 mb-1">{actionTag}</div>
)}
{shortText ? (
  <p className="text-sm leading-relaxed">{shortText}</p>
) : (
  <div className="h-8 bg-white/5 rounded animate-pulse" />  {/* skeleton */}
)}
{shortText && (
  <button
    onClick={() => setExpanded(e => !e)}
    className="text-xs text-white/40 hover:text-white/60 mt-2"
  >
    {expanded ? "▲ Hide analysis" : "▼ Full analysis"}
  </button>
)}
{expanded && (
  deepText
    ? <p className="text-sm leading-relaxed mt-2 text-white/80">{deepText}</p>
    : <div className="h-12 bg-white/5 rounded animate-pulse mt-2" />
)}
```

**Step 3: Check dev server renders correctly**

```bash
cd dashboard && npm run dev -- --port 3000 --hostname 0.0.0.0 > /tmp/dash.log 2>&1 &
sleep 3 && tail -5 /tmp/dash.log
```

Open dashboard, verify signal cards show action tag, short narrative, expand button.

**Step 4: Commit**

```bash
git add dashboard/src/components/narrative-panel.tsx
git commit -m "feat(i8): three-tier narrative panel — action tag, short, deep expand/collapse"
```

---

## Task 6: Update AI Narrative Service Config File

**Files:**
- Find and modify the narrative service JSON config (contains `providers` key)

**Step 1: Find config file**

```bash
grep -n "load\|open.*json\|config_path\|narrative.*json" services/ai_narrative_service.py | head -10
```

**Step 2: Add narrative_short and narrative_deep provider entries**

Add to the `providers` object in the config JSON (same entry as `per_signal` initially):
```json
"narrative_short": [
    {"type": "openrouter", "model": "z-ai/glm-4.7-flash"}
],
"narrative_deep": [
    {"type": "openrouter", "model": "z-ai/glm-4.7-flash"}
]
```

**Step 3: Verify service starts without error**

```bash
.venv/bin/python -c "
from services.ai_narrative_service import AIMarketNarrativeService
svc = AIMarketNarrativeService.__new__(AIMarketNarrativeService)
svc._build_chains()
print('short_chain:', svc.short_chain)
print('deep_chain:', svc.deep_chain)
print('OK')
"
```
Expected: prints chain objects, no error.

**Step 4: Run full unit test suite**

```bash
.venv/bin/pytest tests/unit/ -q --tb=short 2>&1 | tail -10
```
Expected: all passing, no regressions.

**Step 5: Commit**

```bash
git add <config-file>
git commit -m "feat(i8): add narrative_short and narrative_deep provider configs"
```

---

## Task 7: Integration Verification

**Step 1: Restart the narrative service**

Ask user to run:
```bash
sudo systemctl restart indicagent-ai-narrative
journalctl -u indicagent-ai-narrative -f
```

**Step 2: Watch for two-tier calls**

```bash
.venv/bin/python -c "
import redis, json
r = redis.Redis()
# Watch llm_calls stream for narrative_short and narrative_deep
msgs = r.xrevrange('development:llm_calls:stream', count=20)
for _, fields in msgs:
    ct = fields.get(b'call_type', b'').decode()
    if ct in ('narrative_short', 'narrative_deep'):
        print(ct, fields.get(b'symbol', b'').decode(), fields.get(b'latency_ms', b'').decode(), 'ms')
"
```
Expected: see `narrative_short` and `narrative_deep` entries appearing in pairs.

**Step 3: Verify narratives stream has narrative_type field**

```bash
.venv/bin/python -c "
import redis
r = redis.Redis()
msgs = r.xrevrange('development:narratives:ESH6:5m', count=5)
for _, fields in msgs:
    print(fields.get(b'narrative_type', b'?').decode(), '|', fields.get(b'narrative', b'').decode()[:80])
"
```
Expected: see `short` and `deep` entries.

**Step 4: Add ROADMAP backlog entry for this completed phase**

Update `.planning/ROADMAP.md` — move "I8 Narrative Two-Tier Redesign" from Tier 1 backlog to the Progress table as the next phase after 21.

**Step 5: Final test run**

```bash
.venv/bin/pytest tests/unit/ -q 2>&1 | tail -5
```
Expected: 1318+ tests passing.

**Step 6: Commit**

```bash
git add .planning/ROADMAP.md
git commit -m "docs(i8): mark narrative redesign as active phase in roadmap"
```
