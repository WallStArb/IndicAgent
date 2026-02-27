# AI Narrative Redesign — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Replace always-on qwen3:8b per-signal narration with two gated modes: per-signal (confidence > 0.7, TF ≥ 5m only) + group synthesis (phi4-mini, change-driven), reducing Ollama from 550%+ CPU to idle-except-when-needed.

**Architecture:** A single `AINarrativeService` runs two async loops — the existing per-signal loop (gated by TF + confidence), and a new group synthesis loop (polls every 30s, fires only when any group member's direction or regime changes). The service maintains an in-memory `_latest_signals` cache fed by the per-signal loop; the group loop reads this cache to build cross-asset prompts. State persistence in Redis prevents false-fire on restart.

**Tech Stack:** Python asyncio, redis.asyncio, urllib.request (no new deps), pytest-asyncio for tests, Next.js/React for dashboard changes.

**Design doc:** `docs/plans/2026-02-26-narrative-redesign.md`

---

## Task 1: Add `narratives_group` stream key to stream_keys.py

**Files:**
- Modify: `src/core/stream_keys.py`
- Test: `tests/unit/test_stream_keys.py`

**Step 1: Check if test_stream_keys.py exists**

```bash
ls tests/unit/test_stream_keys.py 2>/dev/null || echo "not found"
```

If it doesn't exist, create it (step 2). If it does, add the new test to it (step 2b).

**Step 2: Write the failing test**

Create `tests/unit/test_stream_keys.py` (or add to existing):
```python
"""Tests for stream key helpers."""
from src.core.stream_keys import narratives_group


def test_narratives_group_no_prefix():
    key = narratives_group("", "equity")
    assert key == "narratives:group:equity"


def test_narratives_group_with_env_prefix():
    key = narratives_group("development:", "metals")
    assert key == "development:narratives:group:metals"


def test_narratives_group_all_groups():
    groups = ["equity", "energy", "metals", "rates", "fx_crypto", "ag"]
    for g in groups:
        key = narratives_group("", g)
        assert key == f"narratives:group:{g}"
```

**Step 3: Run test to verify it fails**

```bash
.venv/bin/pytest tests/unit/test_stream_keys.py -v
```
Expected: FAIL with `ImportError: cannot import name 'narratives_group'`

**Step 4: Add `narratives_group` to stream_keys.py**

In `src/core/stream_keys.py`, after the existing `narratives()` function (line 46), add:
```python
def narratives_group(env_prefix: str, group_name: str) -> str:
    return f"{env_prefix}narratives:group:{group_name}"
```

Also update the `get_stream_maxlen` `kind` literal to include `"narratives_group"` and add a branch:
```python
# In get_stream_maxlen, add to the Literal type and after the narratives branch:
if kind == "narratives_group":
    return 50
```

**Step 5: Run test to verify it passes**

```bash
.venv/bin/pytest tests/unit/test_stream_keys.py -v
```
Expected: PASS (3 tests)

**Step 6: Commit**

```bash
git add src/core/stream_keys.py tests/unit/test_stream_keys.py
git commit -m "feat(stream-keys): add narratives_group key helper for group synthesis streams"
```

---

## Task 2: Add per-signal filter (TF + confidence) and reduce timeout to 60s

The per-signal loop currently calls qwen3:8b for every direction≠0 signal on all TFs.
After this task: 1m is always skipped; confidence ≤ 0.7 is skipped; timeout drops to 60s.

**Files:**
- Modify: `services/ai_narrative_service.py`
- Modify: `tests/unit/service_tests/test_ai_narrative_service.py`

**Step 1: Update the existing "skips" test to expect the new timeout AND add filter tests**

In `tests/unit/service_tests/test_ai_narrative_service.py`, update and add:

```python
def test_service_initializes_with_default_config():
    """Service creates expected attributes from default config."""
    svc = _make_service()
    assert svc.ollama_model == "qwen3:8b"
    assert svc.ollama_timeout == 60.0          # changed from 120 → 60
    assert "ESH6" in svc.config["service"]["symbols"]
    assert svc.env_prefix == ""


@pytest.mark.asyncio
async def test_process_message_skips_1m_timeframe():
    """1m signals are always skipped — never worth per-signal LLM cost."""
    svc = _make_service()
    svc.redis_client = AsyncMock()
    fields = {
        b"direction": b"1",
        b"symbol": b"ESH6",
        b"timeframe": b"1m",
        b"timestamp": b"2026-02-26T10:01:00",
        b"confidence": b"0.85",  # high confidence but 1m — still skip
        b"confluence_score": b"0.80",
        b"setup_plugin": b"trad_TrendFollowing",
        b"signal_type": b"trend_following",
        b"entry_price": b"5100.00",
        b"stop_loss": b"5092.00",
        b"targets": b"5110.00",
        b"regime_context": b"trending_up",
        b"supporting_factors": b"BOS",
    }
    with patch("services.ai_narrative_service.call_ollama_async") as mock_ollama:
        await svc._process_single_message(
            "ESH6", "1m", fields, "signals:ESH6:1m:aggregated", b"1-0"
        )
        mock_ollama.assert_not_called()
    svc.redis_client.xack.assert_called_once()


@pytest.mark.asyncio
async def test_process_message_skips_low_confidence():
    """Confidence ≤ 0.70 is skipped even on an eligible timeframe."""
    svc = _make_service()
    svc.redis_client = AsyncMock()
    fields = {
        b"direction": b"1",
        b"symbol": b"ESH6",
        b"timeframe": b"5m",
        b"timestamp": b"2026-02-26T10:05:00",
        b"confidence": b"0.65",  # below threshold
        b"confluence_score": b"0.70",
        b"setup_plugin": b"trad_TrendFollowing",
        b"signal_type": b"trend_following",
        b"entry_price": b"5100.00",
        b"stop_loss": b"5092.00",
        b"targets": b"5110.00",
        b"regime_context": b"trending_up",
        b"supporting_factors": b"BOS",
    }
    with patch("services.ai_narrative_service.call_ollama_async") as mock_ollama:
        await svc._process_single_message(
            "ESH6", "5m", fields, "signals:ESH6:5m:aggregated", b"1-0"
        )
        mock_ollama.assert_not_called()
    svc.redis_client.xack.assert_called_once()


@pytest.mark.asyncio
async def test_process_message_allows_5m_high_confidence():
    """5m signal with confidence > 0.70 proceeds to Ollama."""
    svc = _make_service()
    svc.redis_client = AsyncMock()
    fields = {
        b"direction": b"1",
        b"symbol": b"ESH6",
        b"timeframe": b"5m",
        b"timestamp": b"2026-02-26T10:05:00",
        b"confidence": b"0.75",  # above threshold
        b"confluence_score": b"0.80",
        b"setup_plugin": b"trad_TrendFollowing",
        b"signal_type": b"trend_following",
        b"entry_price": b"5100.00",
        b"stop_loss": b"5092.00",
        b"targets": b"5110.00",
        b"regime_context": b"trending_up",
        b"supporting_factors": b"BOS",
    }
    with patch(
        "services.ai_narrative_service.call_ollama_async",
        return_value="ES bullish setup forming.",
    ) as mock_ollama:
        await svc._process_single_message(
            "ESH6", "5m", fields, "signals:ESH6:5m:aggregated", b"1-0"
        )
        mock_ollama.assert_called_once()
```

**Step 2: Run tests to verify they fail**

```bash
.venv/bin/pytest tests/unit/service_tests/test_ai_narrative_service.py -v
```
Expected: the 3 new tests FAIL, `test_service_initializes_with_default_config` FAIL (timeout wrong)

**Step 3: Implement the filter in `services/ai_narrative_service.py`**

3a. Add constant at the top of the file (after `SYSTEM_PROMPT`):
```python
# Per-signal narrative gating
_NARRATIVE_ELIGIBLE_TFS = {"5m", "15m", "1h"}
_NARRATIVE_MIN_CONFIDENCE = 0.70
```

3b. In `_load_config`, change the ollama default timeout:
```python
"timeout_sec": 60.0,  # was 120.0; qwen3:8b needs ~60s max on CPU
```

3c. In `_process_single_message`, add the TF + confidence filter immediately after `if signal_data is None:`:
```python
signal_data = parse_aggregated_signal(fields)
if signal_data is None:
    self.narratives_skipped_total.inc()
    return  # finally will xack

# Gate: per-signal narrative only for eligible TFs and high-confidence signals
if timeframe not in _NARRATIVE_ELIGIBLE_TFS:
    self.narratives_skipped_total.inc()
    self.logger.debug(
        "Per-signal narrative skipped: ineligible TF",
        symbol=symbol, timeframe=timeframe,
    )
    return  # finally will xack

if signal_data["confidence"] <= _NARRATIVE_MIN_CONFIDENCE:
    self.narratives_skipped_total.inc()
    self.logger.debug(
        "Per-signal narrative skipped: low confidence",
        symbol=symbol, timeframe=timeframe,
        confidence=signal_data["confidence"],
    )
    return  # finally will xack
```

**Step 4: Run tests to verify they pass**

```bash
.venv/bin/pytest tests/unit/service_tests/test_ai_narrative_service.py -v
```
Expected: all PASS (7 tests including the 4 new ones)

**Step 5: Commit**

```bash
git add services/ai_narrative_service.py tests/unit/service_tests/test_ai_narrative_service.py
git commit -m "feat(narrative): gate per-signal narratives to TF≥5m + confidence>0.7, reduce timeout 120→60s"
```

---

## Task 3: Add group synthesis pure helpers (ASSET_GROUPS, prompt builder, fingerprinting)

All pure functions — easy to unit-test without Redis or Ollama.

**Files:**
- Modify: `services/ai_narrative_service.py`
- Create: `tests/unit/service_tests/test_ai_narrative_group.py`

**Step 1: Write failing tests**

Create `tests/unit/service_tests/test_ai_narrative_group.py`:
```python
"""Tests for group synthesis pure helpers."""
import pytest


def test_asset_groups_covers_all_23_contracts():
    from services.ai_narrative_service import ASSET_GROUPS
    all_symbols = [sym for syms in ASSET_GROUPS.values() for sym in syms]
    # 23 active contracts (see CLAUDE.md)
    expected = {
        "ESH6", "NQH6", "RTYH6", "YMH6",          # equity
        "CLJ6", "BZJ6", "NGJ6",                     # energy
        "GCJ6", "SIH6", "HGH6", "PLJ6",             # metals
        "ZNH6", "ZFH6", "ZBH6", "ZTH6", "SR1H6",   # rates
        "VXH6",                                      # volatility — in equity group
        "ZSH6", "ZCH6", "ZWH6",                     # ag
        "6EH6", "6JH6", "BTCH6",                    # fx_crypto
    }
    # All contracts appear in exactly one group
    assert set(all_symbols) == expected
    assert len(all_symbols) == len(expected)  # no duplicates


def test_symbol_to_group_lookup():
    from services.ai_narrative_service import SYMBOL_TO_GROUP
    assert SYMBOL_TO_GROUP["ESH6"] == "equity"
    assert SYMBOL_TO_GROUP["CLJ6"] == "energy"
    assert SYMBOL_TO_GROUP["GCJ6"] == "metals"
    assert SYMBOL_TO_GROUP["ZNH6"] == "rates"
    assert SYMBOL_TO_GROUP["6EH6"] == "fx_crypto"
    assert SYMBOL_TO_GROUP["ZSH6"] == "ag"


def test_build_group_synthesis_prompt_contains_key_info():
    from services.ai_narrative_service import build_group_synthesis_prompt
    signals = {
        "ESH6:5m": {
            "symbol": "ESH6", "timeframe": "5m", "direction": 1,
            "direction_label": "Bullish", "confidence": 0.82,
            "setup_plugin": "trad_TrendFollowing", "regime_context": "trending_up",
        },
        "NQH6:5m": {
            "symbol": "NQH6", "timeframe": "5m", "direction": -1,
            "direction_label": "Bearish", "confidence": 0.74,
            "setup_plugin": "trad_MeanReversion", "regime_context": "ranging",
        },
    }
    prompt = build_group_synthesis_prompt("equity", signals)
    assert "equity" in prompt.lower()
    assert "ESH6" in prompt
    assert "NQH6" in prompt
    assert "Bullish" in prompt
    assert "Bearish" in prompt
    assert "/no_think" in prompt


def test_build_group_synthesis_prompt_empty_signals():
    """Empty signals dict still returns a valid (minimal) prompt."""
    from services.ai_narrative_service import build_group_synthesis_prompt
    prompt = build_group_synthesis_prompt("ag", {})
    assert "ag" in prompt.lower()
    assert "no signals" in prompt.lower() or len(prompt) > 10


def test_extract_group_fingerprint():
    from services.ai_narrative_service import extract_group_fingerprint
    signals = {
        "ESH6:5m": {"direction": 1, "regime_context": "trending_up"},
        "NQH6:15m": {"direction": -1, "regime_context": "ranging"},
        "RTYH6:1h": {"direction": 0, "regime_context": "low_vol"},  # zero → excluded
    }
    fp = extract_group_fingerprint(signals)
    assert fp == {
        "ESH6:5m": (1, "trending_up"),
        "NQH6:15m": (-1, "ranging"),
    }
    # direction=0 should not appear — no actionable state
    assert "RTYH6:1h" not in fp
```

**Step 2: Run tests to verify they fail**

```bash
.venv/bin/pytest tests/unit/service_tests/test_ai_narrative_group.py -v
```
Expected: FAIL with `ImportError`

**Step 3: Add group constants and helpers to `services/ai_narrative_service.py`**

Add after the existing `SYSTEM_PROMPT` constant (before `parse_aggregated_signal`):

```python
GROUP_SYSTEM_PROMPT = (
    "You are a professional multi-asset futures analyst. "
    "Given signals across related instruments, write a concise 2-3 sentence "
    "group synthesis covering cross-asset themes and directional bias. "
    "Be specific. No disclaimers."
)

# Asset group definitions — contract codes for active front-month (Feb 2026)
ASSET_GROUPS: dict[str, list[str]] = {
    "equity":   ["ESH6", "NQH6", "RTYH6", "YMH6", "VXH6"],
    "energy":   ["CLJ6", "BZJ6", "NGJ6"],
    "metals":   ["GCJ6", "SIH6", "HGH6", "PLJ6"],
    "rates":    ["ZNH6", "ZFH6", "ZBH6", "ZTH6", "SR1H6"],
    "fx_crypto": ["6EH6", "6JH6", "BTCH6"],
    "ag":       ["ZSH6", "ZCH6", "ZWH6"],
}

# Reverse lookup: contract_code → group_name
SYMBOL_TO_GROUP: dict[str, str] = {
    sym: group
    for group, symbols in ASSET_GROUPS.items()
    for sym in symbols
}

# TFs considered for group synthesis signal state
_GROUP_SYNTHESIS_TFS = ("5m", "15m", "1h")
```

Add these pure functions (still before `parse_aggregated_signal` or after it, grouped together):

```python
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
```

**Step 4: Run tests to verify they pass**

```bash
.venv/bin/pytest tests/unit/service_tests/test_ai_narrative_group.py -v
```
Expected: PASS (5 tests)

**Step 5: Commit**

```bash
git add services/ai_narrative_service.py tests/unit/service_tests/test_ai_narrative_group.py
git commit -m "feat(narrative): add group synthesis helpers — ASSET_GROUPS, build_group_synthesis_prompt, extract_group_fingerprint"
```

---

## Task 4: Add in-memory signal cache + group synthesis loop to service

The service needs:
1. `_latest_signals: dict[str, dict]` — updated whenever ANY signal is parsed (before filtering)
2. `_group_synthesis_loop()` — runs every 30s, compares fingerprint, calls phi4-mini on change

**Files:**
- Modify: `services/ai_narrative_service.py`
- Modify: `tests/unit/service_tests/test_ai_narrative_service.py`

**Step 1: Write failing test for group synthesis loop**

Add to `tests/unit/service_tests/test_ai_narrative_service.py`:

```python
@pytest.mark.asyncio
async def test_latest_signals_cache_updated_for_any_signal():
    """_latest_signals is updated even for 1m/low-confidence signals (group loop needs them)."""
    svc = _make_service()
    svc.redis_client = AsyncMock()

    fields = {
        b"direction": b"1",
        b"symbol": b"ESH6",
        b"timeframe": b"1m",
        b"timestamp": b"2026-02-26T10:01:00",
        b"confidence": b"0.85",
        b"confluence_score": b"0.80",
        b"setup_plugin": b"trad_TrendFollowing",
        b"signal_type": b"trend_following",
        b"entry_price": b"5100.00",
        b"stop_loss": b"5092.00",
        b"targets": b"5110.00",
        b"regime_context": b"trending_up",
        b"supporting_factors": b"BOS",
    }
    with patch("services.ai_narrative_service.call_ollama_async"):
        await svc._process_single_message(
            "ESH6", "1m", fields, "signals:ESH6:1m:aggregated", b"1-0"
        )
    # Cache updated even though 1m is filtered from per-signal narration
    assert "ESH6:1m" in svc._latest_signals
    assert svc._latest_signals["ESH6:1m"]["direction"] == 1


@pytest.mark.asyncio
async def test_group_synthesis_fires_on_fingerprint_change():
    """Group synthesis loop publishes a narrative when fingerprint changes."""
    svc = _make_service()
    svc.redis_client = AsyncMock()
    # Simulate a cached signal for an equity member
    svc._latest_signals["ESH6:5m"] = {
        "direction": 1, "direction_label": "Bullish", "confidence": 0.82,
        "setup_plugin": "trad_TrendFollowing", "regime_context": "trending_up",
        "symbol": "ESH6", "timeframe": "5m",
    }
    # Redis: no prior state (returns None → fingerprint mismatch → synthesize)
    svc.redis_client.hget.return_value = None

    with patch(
        "services.ai_narrative_service.call_ollama_async",
        return_value="Equity group showing bullish momentum.",
    ):
        await svc._synthesize_group("equity")

    # Should publish stream + update state
    svc.redis_client.xadd.assert_called_once()
    svc.redis_client.hset.assert_called()


@pytest.mark.asyncio
async def test_group_synthesis_skips_when_fingerprint_unchanged():
    """Group synthesis loop does NOT call Ollama if nothing changed."""
    svc = _make_service()
    svc.redis_client = AsyncMock()
    svc._latest_signals["ESH6:5m"] = {
        "direction": 1, "regime_context": "trending_up",
        "direction_label": "Bullish", "confidence": 0.82,
        "setup_plugin": "trad_TrendFollowing",
        "symbol": "ESH6", "timeframe": "5m",
    }
    import json
    # Pre-populate Redis state with the same fingerprint
    prior_fp = {"ESH6:5m": [1, "trending_up"]}
    svc.redis_client.hget.return_value = json.dumps(prior_fp).encode()

    with patch("services.ai_narrative_service.call_ollama_async") as mock_ollama:
        await svc._synthesize_group("equity")
        mock_ollama.assert_not_called()

    svc.redis_client.xadd.assert_not_called()
```

**Step 2: Run tests to verify they fail**

```bash
.venv/bin/pytest tests/unit/service_tests/test_ai_narrative_service.py::test_latest_signals_cache_updated_for_any_signal tests/unit/service_tests/test_ai_narrative_service.py::test_group_synthesis_fires_on_fingerprint_change tests/unit/service_tests/test_ai_narrative_service.py::test_group_synthesis_skips_when_fingerprint_unchanged -v
```
Expected: FAIL (AttributeError on `svc._latest_signals`, `svc._synthesize_group`)

**Step 3: Implement cache + group synthesis in `AINarrativeService`**

3a. In `__init__`, add after `self._error_count = 0`:
```python
self.group_model: str = self.config["ollama"].get("group_model", "phi4-mini:3.8b")

# In-memory cache: "SYMBOL:TF" → latest parsed signal dict (any direction)
self._latest_signals: dict[str, dict] = {}

# Metrics for group synthesis
self.group_narratives_generated = counter(
    "narrative_group_generated_total",
    "Total group narratives generated",
)
```

3b. In `_load_config` default_config, add `group_model` to ollama section:
```python
"ollama": {
    "base_url": "http://localhost:11434",
    "model": "qwen3:8b",
    "group_model": "phi4-mini:3.8b",
    "timeout_sec": 60.0,
    "num_predict": 500,
},
```

3c. In `_process_single_message`, add cache update BEFORE the TF/confidence gate check (so the cache always reflects the latest signal, even for skipped ones). Insert right after `if signal_data is None: ... return`:
```python
# Always cache latest signal for group synthesis (regardless of per-signal filter)
cache_key_mem = f"{symbol}:{timeframe}"
self._latest_signals[cache_key_mem] = signal_data
```

3d. Add the `_synthesize_group` method (extract from the loop for testability):
```python
async def _synthesize_group(self, group_name: str) -> None:
    """Check if group state changed and publish synthesis if so."""
    group_symbols = ASSET_GROUPS.get(group_name, [])

    # Gather current signals for this group across synthesis TFs
    current_signals: dict[str, dict] = {}
    for sym in group_symbols:
        for tf in _GROUP_SYNTHESIS_TFS:
            key = f"{sym}:{tf}"
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

    # Build prompt and call phi4-mini
    prompt = build_group_synthesis_prompt(group_name, current_signals)
    t0 = time.time()
    narrative_text = await call_ollama_async(
        self.ollama_base_url,
        self.group_model,
        prompt,
        self.ollama_timeout,
        300,  # phi4-mini is smaller; 300 tokens is plenty
    )
    latency_ms = (time.time() - t0) * 1000

    if narrative_text:
        from src.core.stream_keys import narratives_group as sk_narratives_group
        stream_out = sk_narratives_group(self.env_prefix, group_name)
        ts = datetime.now(tz=UTC).isoformat()
        msg = {
            "group": group_name,
            "narrative": narrative_text,
            "timestamp": ts,
            "model": self.group_model,
            "latency_ms": str(int(latency_ms)),
        }
        await self.redis_client.xadd(stream_out, msg, maxlen=50, approximate=True)
        cache_key_hash = f"{self.env_prefix}narrative:group:{group_name}:latest"
        await self.redis_client.hset(cache_key_hash, mapping=msg)
        await self.redis_client.expire(cache_key_hash, 3600)  # 1 hour TTL

        # Persist new fingerprint so we don't re-fire on next loop iteration
        await self.redis_client.hset(
            state_redis_key,
            "fingerprint_json",
            json.dumps({k: list(v) for k, v in current_fp.items()}),
        )
        await self.redis_client.expire(state_redis_key, 86400)  # 24h TTL

        self.group_narratives_generated.inc()
        self.logger.info(
            "Group narrative published",
            group=group_name,
            signals=len(current_signals),
            latency_ms=round(latency_ms, 1),
        )
    else:
        self.logger.warning("Group Ollama returned no narrative", group=group_name)
```

3e. Add the `_group_synthesis_loop` method:
```python
async def _group_synthesis_loop(self) -> None:
    """Run group synthesis every 30s — fires Ollama only on material changes."""
    self.logger.info("Starting group synthesis loop")
    while self.running and not self.shutdown_requested:
        try:
            await asyncio.sleep(30)
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
```

3f. In `start()`, add `_group_synthesis_loop` to the tasks list:
```python
tasks = [
    asyncio.create_task(self._process_loop()),
    asyncio.create_task(self._health_monitor_loop()),
    asyncio.create_task(self._group_synthesis_loop()),
]
```

**Step 4: Run tests**

```bash
.venv/bin/pytest tests/unit/service_tests/test_ai_narrative_service.py -v
```
Expected: all PASS (10 tests)

```bash
.venv/bin/pytest tests/unit/service_tests/test_ai_narrative_group.py -v
```
Expected: still PASS (5 tests)

**Step 5: Commit**

```bash
git add services/ai_narrative_service.py tests/unit/service_tests/test_ai_narrative_service.py
git commit -m "feat(narrative): add in-memory signal cache and group synthesis loop (phi4-mini, change-driven)"
```

---

## Task 5: Fix SIGTERM — cancel asyncio tasks cleanly

**Problem:** `signal.signal(SIGTERM, handler)` sets `shutdown_requested = True` but the `asyncio.sleep(30)` in `_group_synthesis_loop` and the `block=100ms` xreadgroup calls don't wake up. A 120s Ollama timeout caused SIGKILL. Now we're at 60s, but we still need the event loop to wake up cleanly on SIGTERM.

**Fix:** Use `loop.add_signal_handler` (asyncio-aware) to cancel tasks via an asyncio.Event, instead of a plain signal handler that only sets a flag.

**Files:**
- Modify: `services/ai_narrative_service.py`

**Step 1: Write a test for the shutdown event**

Add to `tests/unit/service_tests/test_ai_narrative_service.py`:

```python
def test_service_has_shutdown_event():
    """Service exposes an asyncio.Event for clean shutdown coordination."""
    svc = _make_service()
    assert hasattr(svc, "shutdown_event")
    import asyncio
    assert isinstance(svc.shutdown_event, asyncio.Event)
    assert not svc.shutdown_event.is_set()
```

**Step 2: Run test to verify it fails**

```bash
.venv/bin/pytest tests/unit/service_tests/test_ai_narrative_service.py::test_service_has_shutdown_event -v
```
Expected: FAIL (AttributeError)

**Step 3: Implement the fix**

3a. In `__init__`, replace the signal handler setup section:
```python
# Remove these two lines:
# signal.signal(signal.SIGINT, self._signal_handler)
# signal.signal(signal.SIGTERM, self._signal_handler)

# Replace with asyncio.Event-based shutdown coordination:
self.shutdown_event = asyncio.Event()
```

3b. Replace `_signal_handler` with a new `_register_signal_handlers` method that sets up asyncio-aware handlers:
```python
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
```

3c. In `_process_loop`, replace `await asyncio.sleep(interval)` with:
```python
# Wake up early if shutdown requested
try:
    await asyncio.wait_for(
        self.shutdown_event.wait(),
        timeout=self.config["service"]["processing_interval"],
    )
except asyncio.TimeoutError:
    pass
```

3d. In `_group_synthesis_loop`, replace `await asyncio.sleep(30)` with:
```python
try:
    await asyncio.wait_for(self.shutdown_event.wait(), timeout=30)
    break  # shutdown requested
except asyncio.TimeoutError:
    pass  # normal — run synthesis
```

3e. In `start()`, register handlers after getting the loop:
```python
async def start(self) -> None:
    self.logger.info("Starting AI Narrative Service", config=self.config["service"])
    try:
        loop = asyncio.get_running_loop()
        self._register_signal_handlers(loop)
        await self._connect_redis()
        ...
```

**Step 4: Run all tests**

```bash
.venv/bin/pytest tests/unit/service_tests/ -v
```
Expected: all PASS (11 tests)

**Step 5: Commit**

```bash
git add services/ai_narrative_service.py tests/unit/service_tests/test_ai_narrative_service.py
git commit -m "fix(narrative): asyncio-aware SIGTERM handler — tasks cancel cleanly instead of SIGKILL loop"
```

---

## Task 6: Update systemd unit with TimeoutStopSec=75

**Files:**
- Modify: `services/indicagent-ai-narrative.service`

**Step 1: Read the file first** (already done above — line 1-22)

**Step 2: Add `TimeoutStopSec=75` to the [Service] section**

In `services/indicagent-ai-narrative.service`, add after `RestartSec=10`:
```ini
TimeoutStopSec=75
```

This gives systemd 75s to stop the service (60s Ollama timeout + 15s margin), preventing SIGKILL.

**Step 3: Copy the updated unit to systemd and reload**

```bash
sudo cp services/indicagent-ai-narrative.service /etc/systemd/system/
sudo systemctl daemon-reload
```

**Step 4: Verify the unit file is correct**

```bash
sudo systemctl cat indicagent-ai-narrative | grep TimeoutStop
```
Expected: `TimeoutStopSec=75`

**Step 5: Commit**

```bash
git add services/indicagent-ai-narrative.service
git commit -m "fix(narrative): add TimeoutStopSec=75 to systemd unit — prevents SIGKILL during Ollama call"
```

---

## Task 7: Add group narrative streams to SSE route

The frontend needs to receive group narratives via SSE. The SSE endpoint's `_build_stream_list` must include the 6 `narratives:group:GROUP_NAME` streams. These are global (not per-symbol), so they're added once per connection regardless of which symbols are selected.

**Files:**
- Modify: `src/api/routes/sse.py`
- Modify: `src/core/stream_keys.py` (import `narratives_group`)

**Step 1: Write a test for `_build_stream_list` containing group streams**

Check if there's an existing SSE test:
```bash
ls tests/unit/ | grep sse
```

If not, add to `tests/unit/test_sse_routes.py` (create it):
```python
"""Tests for SSE route helpers."""
from unittest.mock import patch, MagicMock


def _mock_settings(env="development"):
    s = MagicMock()
    s.env_name = env
    s.contracts = []
    return s


def test_build_stream_list_includes_group_narrative_streams():
    """SSE stream list always includes 6 group narrative streams."""
    with patch("src.api.routes.sse.Settings", return_value=_mock_settings(env="")):
        from src.api.routes.sse import _build_stream_list
        streams = _build_stream_list(["ES"], "1m")
    group_streams = [s for s in streams if ":group:" in s]
    assert len(group_streams) == 6
    groups = {s.split(":")[-1] for s in group_streams}
    assert groups == {"equity", "energy", "metals", "rates", "fx_crypto", "ag"}
```

**Step 2: Run test to verify it fails**

```bash
.venv/bin/pytest tests/unit/test_sse_routes.py::test_build_stream_list_includes_group_narrative_streams -v
```
Expected: FAIL

**Step 3: Update `_build_stream_list` in `src/api/routes/sse.py`**

3a. Add import at the top with the other stream key imports:
```python
from ...core.stream_keys import narratives_group as sk_narratives_group
```

3b. Add constant for group names (can be inline or imported from service — keep it local to avoid cross-module coupling):
```python
_NARRATIVE_GROUPS = ("equity", "energy", "metals", "rates", "fx_crypto", "ag")
```

3c. In `_build_stream_list`, append group streams after the per-symbol loop (using a set to deduplicate since this is called once per SSE connection anyway):
```python
def _build_stream_list(symbols: list[str], timeframe: str) -> list[str]:
    settings = Settings()
    env_prefix = f"{settings.env_name}:" if settings.env_name else ""
    timeframes = [tf.strip() for tf in timeframe.split(",") if tf.strip()]
    streams: list[str] = []
    for sym in symbols:
        contract = _resolve_contract(sym)
        streams.append(sk_live_tick(env_prefix, contract))
        for tf in timeframes:
            streams.append(sk_market(env_prefix, contract, tf))
            streams.append(sk_indicators(env_prefix, contract, tf))
            streams.append(sk_intelligence(env_prefix, contract, tf))
            streams.append(sk_signals_aggregated(env_prefix, contract, tf))
            streams.append(sk_narratives(env_prefix, contract, tf))
    # Group narrative streams — global, not per-symbol
    for group in _NARRATIVE_GROUPS:
        streams.append(sk_narratives_group(env_prefix, group))
    return streams
```

3d. Update `_event_name_for_stream` to handle `narratives:group:*` correctly. The current check `if candidate.startswith("narratives:")` returns `"narrative_data"` — this is correct and will also match `narratives:group:*`. No change needed there.

**Step 4: Run test**

```bash
.venv/bin/pytest tests/unit/test_sse_routes.py -v
```
Expected: PASS

```bash
.venv/bin/pytest tests/unit/ -v --tb=short 2>&1 | tail -20
```
Expected: all existing tests still pass

**Step 5: Commit**

```bash
git add src/api/routes/sse.py tests/unit/test_sse_routes.py
git commit -m "feat(sse): include 6 group narrative streams in SSE subscription"
```

---

## Task 8: Dashboard — consume group narratives and update narrative panel

**Files:**
- Modify: `dashboard/src/lib/types.ts`
- Modify: `dashboard/src/hooks/use-market-stream.ts`
- Modify: `dashboard/src/components/narrative-panel.tsx`

**Step 1: Add `GroupNarrativeData` type to `dashboard/src/lib/types.ts`**

After the `NarrativeData` interface (around line 208):
```typescript
export interface GroupNarrativeData {
  group: string;                 // e.g. "equity"
  narrative: string;
  timestamp: string;
  receivedAt: number;
  model: string;
}
```

**Step 2: Add group narrative state + SYMBOL_TO_GROUP in `use-market-stream.ts`**

2a. Add the import of the new type:
The `GroupNarrativeData` type is already in `@/lib/types` after Task 8 Step 1.

Update the import line:
```typescript
import type {
  SymbolData,
  IndicatorData,
  StructureData,
  ContextData,
  PatternData,
  SmartMoneyData,
  ConfluenceData,
  SignalData,
  NarrativeData,
  GroupNarrativeData,      // add this
  ConnectionStatus,
  Timeframe,
  PerTfSignal,
  IntelligenceTfData,
  SessionState,
} from "@/lib/types";
```

2b. Add a `SYMBOL_TO_GROUP` lookup map near the top of the file (after the imports):
```typescript
/** Map base symbol → asset group name (matches backend ASSET_GROUPS). */
const SYMBOL_TO_GROUP: Record<string, string> = {
  ES: "equity", NQ: "equity", RTY: "equity", YM: "equity", VX: "equity",
  CL: "energy", BZ: "energy", NG: "energy",
  GC: "metals", SI: "metals", HG: "metals", PL: "metals",
  ZN: "rates", ZF: "rates", ZB: "rates", ZT: "rates", SR1: "rates",
  "6E": "fx_crypto", "6J": "fx_crypto", BTC: "fx_crypto",
  ZS: "ag", ZC: "ag", ZW: "ag",
};
```

2c. Add `groupNarratives` state alongside `narratives`:
```typescript
const [groupNarratives, setGroupNarratives] = useState<Record<string, GroupNarrativeData>>({});
```

2d. Update the `narrative_data` event handler to branch on group vs per-symbol:

Replace the existing `narrative_data` handler with:
```typescript
// --- AI narrative data (I8) — per-symbol and group ---
es.addEventListener("narrative_data", (evt) => {
  const { stream, payload } = JSON.parse(evt.data);
  const streamStr = stream as string;

  if (streamStr.includes(":group:")) {
    // Group synthesis narrative: stream = "narratives:group:equity"
    const parts = streamStr.split(":");
    const groupName = parts[parts.length - 1];
    if (!groupName || !payload.narrative) return;
    setGroupNarratives((prev) => ({
      ...prev,
      [groupName]: {
        group: groupName,
        narrative: String(payload.narrative),
        timestamp: String(payload.timestamp || ""),
        receivedAt: Date.now(),
        model: String(payload.model || ""),
      },
    }));
  } else {
    // Per-symbol narrative: stream = "narratives:ESH6:5m"
    const sym = contractToBase(payload.symbol || "");
    if (!sym || !payload.narrative) return;
    const parts = streamStr.split(":");
    const tf = parts[parts.length - 1] || timeframe;
    const key = `${sym}:${tf}`;
    setNarratives((prev) => ({
      ...prev,
      [key]: {
        symbol: sym,
        timeframe: tf,
        narrative: String(payload.narrative),
        action_bias: String(payload.action_bias || ""),
        timestamp: String(payload.timestamp || ""),
        receivedAt: Date.now(),
      },
    }));
  }
  touch();
});
```

2e. Update the return value of `useMarketStream` to expose `groupNarratives`:
```typescript
return { symbolData, connectionStatus, lastUpdate, narratives, groupNarratives };
```

**Step 3: Find where `useMarketStream` return value is consumed**

```bash
grep -r "useMarketStream" dashboard/src --include="*.tsx" --include="*.ts" -l
```

Read the consuming file(s) and add `groupNarratives` to the destructure.

**Step 4: Update `narrative-panel.tsx` to show group narrative as default**

The panel currently accepts `narratives: Record<string, NarrativeData>` and shows all in a horizontal scroll.

New behavior:
- Default view: group narrative for the active symbol's group
- Override: per-signal narrative for the active `${sym}:${tf}` if it exists

Update the component signature and logic:

```typescript
"use client";

import { useMemo } from "react";
import type { NarrativeData, GroupNarrativeData } from "@/lib/types";

/** Map base symbol → asset group (must match backend ASSET_GROUPS). */
const SYMBOL_TO_GROUP: Record<string, string> = {
  ES: "equity", NQ: "equity", RTY: "equity", YM: "equity", VX: "equity",
  CL: "energy", BZ: "energy", NG: "energy",
  GC: "metals", SI: "metals", HG: "metals", PL: "metals",
  ZN: "rates", ZF: "rates", ZB: "rates", ZT: "rates", SR1: "rates",
  "6E": "fx_crypto", "6J": "fx_crypto", BTC: "fx_crypto",
  ZS: "ag", ZC: "ag", ZW: "ag",
};

interface NarrativePanelProps {
  narratives: Record<string, NarrativeData>;
  groupNarratives: Record<string, GroupNarrativeData>;
  activeSymbol: string;       // base symbol, e.g. "ES"
  activeTimeframe: string;    // e.g. "5m"
}

const STALE_AFTER_MS = 60 * 60 * 1000;

export function NarrativePanel({
  narratives,
  groupNarratives,
  activeSymbol,
  activeTimeframe,
}: NarrativePanelProps) {
  const { displayNarrative, isGroup } = useMemo(() => {
    // Prefer per-signal narrative for active symbol+TF
    const perSignalKey = `${activeSymbol}:${activeTimeframe}`;
    const perSignal = narratives[perSignalKey];
    if (perSignal) {
      return { displayNarrative: perSignal, isGroup: false };
    }

    // Fall back to group narrative
    const group = SYMBOL_TO_GROUP[activeSymbol];
    const groupNarrative = group ? groupNarratives[group] : undefined;
    if (groupNarrative) {
      return { displayNarrative: groupNarrative, isGroup: true };
    }

    return { displayNarrative: null, isGroup: false };
  }, [narratives, groupNarratives, activeSymbol, activeTimeframe]);

  if (!displayNarrative) {
    return (
      <div className="px-3 py-1.5 flex items-center gap-2 border-t border-[var(--border-subtle)] bg-[var(--bg-surface)]">
        <span className="text-[0.55rem] font-semibold uppercase tracking-widest text-[var(--text-muted)] shrink-0">
          AI
        </span>
        <span className="text-[0.6rem] text-[var(--text-muted)] italic">
          Waiting for signals...
        </span>
      </div>
    );
  }

  if (isGroup) {
    const gn = displayNarrative as GroupNarrativeData;
    const isStale = Date.now() - gn.receivedAt > STALE_AFTER_MS;
    const group = SYMBOL_TO_GROUP[activeSymbol] ?? "group";
    return (
      <div
        className="border-t border-[var(--border-subtle)] bg-[var(--bg-surface)] shrink-0 px-3 py-2"
        style={{ opacity: isStale ? 0.45 : 1 }}
      >
        <div className="flex items-center gap-1.5 mb-1">
          <span className="text-[0.55rem] font-bold text-[var(--text-primary)] uppercase font-data">
            {group}
          </span>
          <span className="text-[0.5rem] text-[var(--text-muted)] bg-[var(--bg-elevated)] px-1 rounded">
            GROUP
          </span>
          {isStale && (
            <span className="text-[0.45rem] text-[var(--text-muted)] italic ml-auto">stale</span>
          )}
        </div>
        <p className="text-[0.6rem] text-[var(--text-secondary)] italic leading-relaxed line-clamp-3 m-0">
          {gn.narrative}
        </p>
      </div>
    );
  }

  // Per-signal narrative (existing NarrativeCard rendering, simplified to single card)
  const n = displayNarrative as NarrativeData;
  return (
    <div className="border-t border-[var(--border-subtle)] bg-[var(--bg-surface)] shrink-0">
      <NarrativeCard data={n} />
    </div>
  );
}

function NarrativeCard({ data }: { data: NarrativeData }) {
  const isStale = Date.now() - data.receivedAt > STALE_AFTER_MS;
  const barTimeStr = data.timestamp
    ? new Date(data.timestamp).toLocaleTimeString([], {
        hour: "2-digit", minute: "2-digit", hour12: false,
      })
    : null;
  const barDate = data.timestamp ? new Date(data.timestamp) : null;
  const isToday = barDate ? barDate.toDateString() === new Date().toDateString() : true;
  const barDateStr =
    barDate && !isToday
      ? barDate.toLocaleDateString([], { month: "short", day: "numeric" })
      : null;
  const isBullish = data.action_bias === "bullish";
  const accentColor = isBullish ? "var(--green)" : "var(--red)";

  return (
    <div
      className="flex flex-col gap-1 px-3 py-2"
      style={{
        borderLeftWidth: "2px",
        borderLeftStyle: "solid",
        borderLeftColor: isStale ? "var(--border-subtle)" : accentColor,
        opacity: isStale ? 0.45 : 1,
        transition: "opacity 0.5s ease-out",
      }}
    >
      <div className="flex items-center gap-1.5">
        <span className="text-[0.55rem] font-bold text-[var(--text-primary)] font-data">
          {data.symbol}
        </span>
        <span className="text-[0.5rem] text-[var(--text-muted)] bg-[var(--bg-elevated)] px-1 rounded">
          {data.timeframe.toUpperCase()}
        </span>
        <span
          className="text-[0.5rem] font-semibold uppercase tracking-wider"
          style={{ color: isStale ? "var(--text-muted)" : accentColor }}
        >
          {data.action_bias}
        </span>
        <div className="ml-auto flex items-center gap-1 shrink-0">
          {barDateStr && <span className="text-[0.5rem] text-[var(--text-muted)]">{barDateStr}</span>}
          {barTimeStr && <span className="text-[0.5rem] font-data text-[var(--text-muted)]">{barTimeStr}</span>}
          {isStale && <span className="text-[0.45rem] text-[var(--text-muted)] italic">stale</span>}
        </div>
      </div>
      <p className="text-[0.6rem] text-[var(--text-secondary)] italic leading-relaxed line-clamp-5 m-0">
        {data.narrative}
      </p>
    </div>
  );
}
```

**Step 5: Find and update the `NarrativePanel` call site(s)**

```bash
grep -r "NarrativePanel" dashboard/src --include="*.tsx" -n
```

Read the file. Add `groupNarratives`, `activeSymbol`, `activeTimeframe` props to the call site. These values come from the dashboard's existing `activeSymbol`/`activeTimeframe` state and `groupNarratives` from `useMarketStream`.

**Step 6: Build check**

```bash
cd dashboard && npm run build 2>&1 | tail -30
```
Expected: no TypeScript errors. Fix any type errors found.

**Step 7: Commit**

```bash
git add dashboard/src/lib/types.ts dashboard/src/hooks/use-market-stream.ts dashboard/src/components/narrative-panel.tsx
git commit -m "feat(dashboard): group narrative as default view, per-signal override for active symbol+TF"
```

---

## Task 9: Verification + deploy

**Step 1: Run full test suite**

```bash
.venv/bin/pytest tests/unit/ -v --tb=short 2>&1 | tail -30
```
Expected: ≥ 602 + new tests passing, 0 failures

**Step 2: Run linter**

```bash
.venv/bin/ruff check services/ai_narrative_service.py src/core/stream_keys.py src/api/routes/sse.py --fix
```
Expected: 0 errors

**Step 3: Copy updated systemd unit**

```bash
sudo cp services/indicagent-ai-narrative.service /etc/systemd/system/
sudo systemctl daemon-reload
```

**Step 4: Restart the service**

```bash
sudo systemctl restart indicagent-ai-narrative
sudo systemctl status indicagent-ai-narrative
```
Expected: active (running)

**Step 5: Watch logs for group synthesis**

```bash
journalctl -u indicagent-ai-narrative -f
```
Expected within 30s: `"Group narrative published"` log entries for groups with active signals.
Expected: `"Per-signal narrative skipped: ineligible TF"` for 1m signals.

**Step 6: Restart API for SSE changes**

```bash
sudo systemctl restart indicagent-api
```

**Step 7: Check Ollama CPU**

```bash
top -bn1 | grep -i ollama
```
Expected: CPU < 10% at rest (spikes only when synthesis runs)

**Step 8: Manual SSE test**

```bash
curl -N "http://localhost:8000/api/sse/events?symbols=ES&timeframe=1m,5m,15m,1h" 2>/dev/null | grep -m3 "narrative"
```
Expected: `narrative_data` events appear within 30s of group synthesis firing.

**Step 9: Final commit if any post-verification tweaks made**

```bash
git add -A
git commit -m "chore(narrative): post-deploy verification tweaks"
```

---

## Success Criteria Checklist

- [ ] `narratives_group` stream key test passes
- [ ] 1m signals never trigger Ollama (per-signal filter test passes)
- [ ] Confidence ≤ 0.70 signals never trigger Ollama
- [ ] Group synthesis fires within 30s of a material direction/regime change
- [ ] Group synthesis does NOT fire when nothing changed (fingerprint test passes)
- [ ] All 602+ unit tests pass, 0 ruff errors
- [ ] Service stops cleanly in < 70s (`systemctl stop indicagent-ai-narrative` completes fast)
- [ ] Dashboard shows group narrative by default, per-signal when high-confidence event fires
- [ ] Server load average < 2 at rest (Ollama idle between synthesis events)
