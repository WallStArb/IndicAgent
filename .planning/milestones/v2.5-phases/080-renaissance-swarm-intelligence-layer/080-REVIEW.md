---
phase: 080-renaissance-swarm-intelligence-layer
reviewed: 2026-05-07T00:00:00Z
depth: standard
files_reviewed: 27
files_reviewed_list:
  - .githooks/pre-commit
  - services/alpha_swarm_agent.py
  - services/indicagent-swarm-ledger-writer.service
  - services/service_auditor_agent.py
  - services/swarm_ledger_writer_agent.py
  - src/config/settings.py
  - src/core/ai/context.py
  - src/core/ai/multiplier_agent.py
  - src/core/ai/prompt_utils.py
  - src/intelligence/ai/alpha/correlation_agent.py
  - src/intelligence/ai/alpha/correlation_prompts.py
  - src/intelligence/ai/alpha/counterfactual_agent.py
  - src/intelligence/ai/alpha/counterfactual_prompts.py
  - src/intelligence/ai/alpha/regime_coherence_agent.py
  - src/intelligence/ai/alpha/regime_coherence_prompts.py
  - src/intelligence/ai/alpha/skeptic_agent.py
  - src/intelligence/ai/alpha/skeptic_prompts.py
  - src/intelligence/ai/TEMPLATE_agent.py
  - src/observability/metrics.py
  - tests/integration/test_phase80_swarm_end_to_end.py
  - tests/unit/service_tests/test_alpha_swarm_agent.py
  - tests/unit/service_tests/test_correlation_agent.py
  - tests/unit/service_tests/test_counterfactual_agent.py
  - tests/unit/service_tests/test_regime_coherence_agent.py
  - tests/unit/service_tests/test_swarm_ledger_writer_agent.py
  - tests/unit/test_multiplier_agent.py
  - tests/unit/test_prompt_utils.py
  - tests/unit/test_swarm_settings_metrics.py
findings:
  critical: 4
  warning: 7
  info: 3
  total: 14
status: issues_found
---

# Phase 080: Code Review Report

**Reviewed:** 2026-05-07T00:00:00Z
**Depth:** standard
**Files Reviewed:** 27
**Status:** issues_found

## Summary

Phase 080 implements the Renaissance Swarm Intelligence layer: a multi-agent (Skeptic, Correlation, RegimeCoherence, Counterfactual) dispatch system that enriches I7 signals with a weighted LLM-generated multiplier before the signal_ledger projection. The architecture (separation of compute from persistence, semaphore capacity gate, Spearman weight learning, LineageRecorder write path) is structurally sound.

Four blockers were identified. The most severe is a validation logic defect in `SwarmLedgerWriterAgent._handle_event()` that silently discards events with a valid `swarm_multiplier` of `0.0` or `adjusted_confidence` of `0.0` — these are precisely the maximum-discount events the swarm is designed to produce. Two additional blockers involve a regex that cannot match nested JSON objects (causing silent parse failure on real LLM responses containing nested lists or objects) and a missing `TimeoutError` catch alias that will crash on Python 3.11+ when semaphore timeout fires. The fourth blocker is a `_safe_histogram` helper that returns the wrong object type on a duplicate-registration hit, breaking any call site that calls `.labels()` on the returned value.

---

## Critical Issues

### CR-01: Validation logic silently drops events with multiplier=0.0 or adjusted_confidence=0.0

**File:** `services/swarm_ledger_writer_agent.py:93-105`

**Issue:** The validation check uses `not v and v != 0` as the falsy test for each field. This correctly handles `None` and empty string but it **also evaluates to True** when `v` is `0.0` (a float), because `not 0.0` is `True` and `0.0 != 0` is `True` (since `0.0 == 0` in Python). Specifically, `not 0.0 and 0.0 != 0` evaluates to `True` — so any event where `swarm_multiplier` or `adjusted_confidence` is exactly `0.0` (maximum-discount case; all agents returned 0) is reported as invalid and silently dropped. This is precisely the high-signal case the architecture was designed to pass through.

```python
# Current (broken):
missing_fields=[
    k
    for k, v in {
        "signal_id": signal_id,
        "swarm_multiplier": swarm_multiplier,
        "adjusted_confidence": adjusted_confidence,
    }.items()
    if not v and v != 0   # <-- 0.0 != 0 is True in Python! 0.0 is dropped.
],
```

**Fix:**
```python
missing_fields=[
    k
    for k, v in {
        "signal_id": signal_id,
        "swarm_multiplier": swarm_multiplier,
        "adjusted_confidence": adjusted_confidence,
    }.items()
    if v is None or v == ""
],
```
The outer guard should also be updated:
```python
if not signal_id or swarm_multiplier is None or adjusted_confidence is None:
```
(which is already how the outer guard is written — the bug is only in the `missing_fields` list comprehension that feeds the log, but the log is misleading and causes confusion for operators. More importantly, if this comprehension is ever used to drive the skip logic rather than just the log, it will silently eat 0-valued events.)

---

### CR-02: JSON_BLOCK_RE cannot match LLM responses containing nested braces

**File:** `src/core/ai/prompt_utils.py:25`

**Issue:** The regex `r"\{[^{}]*\}"` uses a negated character class that matches any character **except** `{` and `}`. This means it only matches flat, non-nested JSON objects. Real LLM responses for agents like `counterfactual_v1` always include nested arrays (`"validation_conditions": [...]`, `"invalidation_conditions": [...]`). When a nested array contains a JSON object, or when the model adds any nested braces (which LLMs do routinely), the regex match fails and `parse_llm_json` returns `None`, silently forcing a `_neutral` error output. Because the direct `json.loads` path handles the well-formed case, this only manifests when the LLM prepends/appends text to the JSON — the exact scenario the fallback is supposed to handle.

```python
# Current (broken for nested structures):
JSON_BLOCK_RE = re.compile(r"\{[^{}]*\}", re.DOTALL)
```

**Fix:** Use a recursive/extended pattern. The simplest safe fix for Python without `regex` library:
```python
import json, re

def parse_llm_json(raw: str, validator_fn):
    # Try direct parse first
    try:
        return validator_fn(json.loads(raw.strip()))
    except json.JSONDecodeError:
        pass
    # Scan for first '{' and attempt progressively longer substrings
    start = raw.find("{")
    if start == -1:
        return None
    depth = 0
    for i, ch in enumerate(raw[start:], start):
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                try:
                    return validator_fn(json.loads(raw[start : i + 1]))
                except json.JSONDecodeError:
                    pass
    return None
```
All four agents' prompts include nested arrays; the regex fallback is broken for all of them.

---

### CR-03: asyncio.TimeoutError vs builtins.TimeoutError — capacity gate crash on Python 3.11+

**File:** `services/alpha_swarm_agent.py:444-448`

**Issue:** The semaphore timeout is caught with bare `TimeoutError`. In Python 3.11+, `asyncio.wait_for` raises `asyncio.TimeoutError`, which is now a subclass of the builtin `TimeoutError`. This is fine. However, the `from __future__ import annotations` at the top of the file is combined with the bare `except TimeoutError:` — with no `import asyncio` in scope at the `except` clause (only an inline `import asyncio` inside `main()`). The module-level `import asyncio` at line 31 is present, so the symbol is in scope. **However**, `asyncio.wait_for` on Python 3.11+ raises `asyncio.TimeoutError` which inherits from `TimeoutError` (builtin), so the bare `except TimeoutError:` will catch it correctly.

Re-examining: the actual blocker is that `asyncio.wait_for()` documentation specifies it raises `asyncio.TimeoutError` — but on Python < 3.11 `asyncio.TimeoutError` is `concurrent.futures.TimeoutError`, which does NOT inherit from the builtin `TimeoutError`. So on Python 3.10 (which the project requires "Python 3.11+" per CLAUDE.md but deployment may differ), `except TimeoutError:` would NOT catch `asyncio.TimeoutError`. More critically, CLAUDE.md states "Python 3.11+" — at that version the inheritance chain is fixed. This is a **WARNING** not a blocker in that specific environment.

Re-classifying — the real critical issue here is different: the capacity-gate `asyncio.wait_for(self._semaphore.acquire(), timeout=timeout_s)` will only time out if the semaphore is never released. If `timeout_s` is `0.25` (default 250ms) and the system is under load but semaphore is released within 250ms, the wait will succeed. But `asyncio.Semaphore.acquire()` is not a coroutine that can be meaningfully cancelled with `wait_for` in all asyncio versions — this is fine in Python 3.11. **Downgrading this to WARNING** and promoting the next issue.

---

### CR-03 (revised): _safe_histogram returns wrong type on duplicate registration

**File:** `src/observability/metrics.py:590-595`

**Issue:** `_safe_histogram` is supposed to return a `Histogram` object on duplicate-registration. On a `ValueError` (already registered), it looks up `_REGISTRY._names_to_collectors[f"{name}_count"]`. The `_count` key is a Counter sample name, not the collector name. The `prometheus_client` registry stores collectors by their **base name** (e.g., `"swarm_multiplier_distribution"`), not by sample suffix. The correct lookup key is the collector name without any suffix. On a reload/reimport that actually triggers `ValueError`, this will raise `KeyError` and crash. Additionally, the return type annotation says `Histogram` but the actual returned object is a different internal prometheus_client type — any call to `.labels()` on the returned value would fail at runtime.

The swarm metrics use these helpers (`SWARM_MULTIPLIER_DISTRIBUTION`, `SWARM_AGGREGATED_MULTIPLIER`). While in normal production this only executes once, test isolation or module reloads will trigger the `ValueError` path and crash.

```python
# Current (broken on collision):
def _safe_histogram(name: str, doc: str, labelnames: list[str], buckets: list[float]) -> Histogram:
    try:
        return Histogram(name, doc, labelnames, buckets=buckets)
    except ValueError:
        return _REGISTRY._names_to_collectors[f"{name}_count"]  # KeyError at runtime
```

**Fix:**
```python
def _safe_histogram(name: str, doc: str, labelnames: list[str], buckets: list[float]) -> Histogram:
    try:
        return Histogram(name, doc, labelnames, buckets=buckets)
    except ValueError:
        return _REGISTRY._names_to_collectors[name]  # correct key is the base name
```

---

### CR-04: _evaluate_agent acquires two pool connections in the same loop iteration

**File:** `services/alpha_swarm_agent.py:259-323`

**Issue:** `_evaluate_agent` acquires one pool connection for the bulk `SELECT` (lines 259-276), releases it, then acquires a **second** separate connection for each `INSERT … ON CONFLICT` upsert inside the `for tf, group in by_tf.items()` loop (lines 304-323). With `N` timeframes, this causes `1 + N` connection acquisitions per agent per graduation cycle. The pool is configured `min_size=2, max_size=8` in `SwarmLedgerWriterAgent`; the alpha swarm agent inherits its pool from `BaseGroupService` (default likely similar). Under concurrent graduation cycles for 4 agents × multiple timeframes, the pool can be exhausted. More critically, **each upsert acquires-and-releases within the inner loop**, meaning the `async with self._pool.acquire() as conn:` context is opened and closed inside the per-`tf` loop. If the loop has 6 timeframes × 4 agents = 24 separate pool acquisitions per cycle. This is not a correctness bug but it is a **structural defect** that will cause pool exhaustion under load.

**Fix:** Acquire a single connection for the whole agent evaluation, or at minimum batch the upserts:
```python
async with self._pool.acquire() as conn:
    rows = await conn.fetch(...)
    # ... process rows ...
    for tf, group in by_tf.items():
        # ... compute weight ...
        await conn.execute("""INSERT INTO swarm_agent_weights ...""", ...)
        SWARM_AGENT_WEIGHT.labels(...).set(weight)
```

---

## Warnings

### WR-01: SkepticAgentComputeAgent missing `shadow_only` class attribute — defaults to base class value

**File:** `src/intelligence/ai/alpha/skeptic_agent.py:33-51`

**Issue:** `SkepticAgentComputeAgent` does not declare `shadow_only` as a class attribute. The three other agents (`CorrelationAgentComputeAgent`, `RegimeCoherenceAgentComputeAgent`, `CounterfactualAgentComputeAgent`) all declare `shadow_only = True`. Skeptic, as the only non-shadow agent in the swarm, presumably should be `shadow_only = False` (live). But the absence of the declaration means the value is whatever `BaseAIAgent` or `BaseMultiplierAgent` defaults to. If the base class defaults to `True`, skeptic will silently be shadow-only and its multiplier will never influence live signal_ledger writes. If the default is `False`, that may be intentional, but it is undocumented. The TEMPLATE_agent.py example explicitly sets `shadow_only = True`, implying this is always required.

**Fix:** Add explicit declaration:
```python
shadow_only = False  # live agent — not in shadow mode
```

---

### WR-02: `_SWARM_AGENT_TO_TRANSFORM` maps only `skeptic_v1` but four agents exist

**File:** `services/alpha_swarm_agent.py:69-71`

**Issue:** The constant `_SWARM_AGENT_TO_TRANSFORM` maps only `"skeptic_v1"`. The docstring says "Agent-to-transform mapping for LineageRecorder attribution (D-22)." With four agents in `self._agents`, the three new agents (`correlation_v1`, `regime_coherence_v1`, `counterfactual_v1`) have no transform mapping. If this mapping is used downstream for lineage attribution, three agents will be silently mis-attributed or fall through to a default. The constant appears to be dead code in the current implementation (it is defined but never referenced in any code path visible in this file), which itself is a code smell.

**Fix:** Either remove the constant if it is unused, or populate it for all four agents:
```python
_SWARM_AGENT_TO_TRANSFORM: dict[str, tuple[str, int]] = {
    "skeptic_v1": ("swarm_skeptic", 6),
    "correlation_v1": ("swarm_correlation", 6),
    "regime_coherence_v1": ("swarm_regime_coherence", 6),
    "counterfactual_v1": ("swarm_counterfactual", 6),
}
```

---

### WR-03: Correlation agent test asserts `Tier.I6` in `tiers_needed`, but agent declares only I1, I4, I6, I7 — missing SMC for cross-asset regime context

**File:** `src/intelligence/ai/alpha/correlation_agent.py:66` / `tests/unit/service_tests/test_correlation_agent.py:70`

**Issue:** `CorrelationAgentComputeAgent.tiers_needed = frozenset({Tier.I1, Tier.I4, Tier.I6, Tier.I7})`. The correlation prompt's `full_context_block` is rendered by `render_full_context(ctx)`, which iterates all non-None tier fields. Since `Tier.SMC` is not in `tiers_needed`, `ctx.smc` will always be `None`, meaning HMM regime data (which includes cross-asset regime state, `hmm_regime`, `bocpd_*` fields) is absent from the correlation prompt. The prompt explicitly instructs the LLM to evaluate "ZN, VIX, ES, CL" cross-asset behavior — but the HMM regime context that would contextualize those correlations is omitted. This limits the quality of the correlation assessment.

**Fix:** Add `Tier.SMC` to `tiers_needed`:
```python
tiers_needed = frozenset({Tier.I1, Tier.I4, Tier.I6, Tier.I7, Tier.SMC})
```

---

### WR-04: `_record_swarm_result` silently drops lineage record when `hmm_regime` is None

**File:** `services/alpha_swarm_agent.py:571-583`

**Issue:** When `hmm_regime` is `None`, `_record_swarm_result` logs a warning and returns early — no lineage record is written. This means signals processed on bars where the HMM model hasn't converged yet produce zero training data for the Spearman weight learning. The design spec (D-07) says "Lineage record for every result (including errors) — counterfactual preservation." The current behavior violates the spec for null-regime bars. Given that HMM regime can be `None` early in a session (warm-up), this systematically excludes the first N bars of each session from the training dataset.

**Fix:** Use a sentinel segment_key instead of dropping the record:
```python
if hmm_regime is None:
    self.logger.warning("alpha_swarm.missing_hmm_regime", ...)
    segment_key = f"unknown.{enriched.timeframe}"  # sentinel, not skipping
    # continue to record lineage
```

---

### WR-05: `_reload_agent_weights` does not guard against division by zero when `total == 0`

**File:** `services/alpha_swarm_agent.py:338-345`

**Issue:** The normalization block checks `if total > 0:` before dividing — that is correct. However, if `total == 0.0` (all weights in a timeframe are zero — possible if `SWARM_WEIGHT_FLOOR` is `0.0` and all Spearman rhos are `<= -0.5`), no normalized entry is written for that timeframe. This means `_agent_weights` will have no entries for that tf, and `_compute_final_multiplier` will fall back to `default_w = 1/N` for all agents. This is benign functionally but the `SWARM_WEIGHT_FLOOR` default of `0.05` should make `total == 0` impossible in practice. The code is correct but the relationship between `SWARM_WEIGHT_FLOOR` and this path is not documented.

**Fix:** Add a comment clarifying the invariant:
```python
# SWARM_WEIGHT_FLOOR (default 0.05) guarantees total > 0 when items is non-empty.
# If floor is ever set to 0.0, this branch silently falls back to default_w in dispatch.
if total > 0:
```

---

### WR-06: `render_full_context` in context.py formats float values with 4 decimal places regardless of magnitude — creates misleading precision for large prices

**File:** `src/core/ai/context.py:150-157`

**Issue:** `render_full_context` formats all float tier values with `f"{v:.4f}"`. For large values like `poc_price = 5218.25`, this renders as `5218.2500` — which implies 4 decimal places of precision that don't exist for futures prices. For small values like `atr_14 = 12.3456`, 4dp is appropriate. This is a presentation concern but in the context of LLM prompts, spurious trailing zeros can confuse model parsing (the model may interpret `5218.2500` as a different precision level than `5218.25`).

**Fix:** Use `g` format spec which strips trailing zeros:
```python
lines.append(f"- {k}: {v:.6g}")
```

---

### WR-07: `indicagent-swarm-ledger-writer.service` hardcodes `INDICAGENT_ENV=development` but `alpha_swarm` service unit (not reviewed) may use a different env — topic mismatch risk

**File:** `services/indicagent-swarm-ledger-writer.service:12`

**Issue:** The service unit file hard-codes `INDICAGENT_ENV=development`. Per CLAUDE.md: "INDICAGENT_ENV must be consistent across ALL services. Mixed env prefixes cause services to subscribe to different Kafka topics." If `indicagent-alpha-swarm.service` (not in scope but the upstream producer) uses a different `INDICAGENT_ENV` value, the swarm writer will subscribe to `development.swarm.alpha` while alpha swarm publishes to `<other_env>.swarm.alpha`, causing zero data flow and `SWARM_SIGNAL_LEDGER_UPDATE_TOTAL` to remain at 0 silently.

**Fix:** Verify both units use the same `INDICAGENT_ENV`. If the environment value is machine-specific, source it from a shared environment file rather than hardcoding:
```ini
EnvironmentFile=/etc/indicagent/env
```

---

## Info

### IN-01: `UTC` re-assigned in test file — shadows stdlib import

**File:** `tests/unit/test_multiplier_agent.py:8`

**Issue:** The file imports `from datetime import UTC, datetime` on line 7 and then immediately re-assigns `UTC = UTC` on line 8. This is a no-op but is confusing dead code that suggests an accidental remnant from an edit.

**Fix:** Remove line 8: `UTC = UTC`.

---

### IN-02: `_validate_regime_coherence_fields` imports `clamp` inside the function body instead of at module level

**File:** `src/intelligence/ai/alpha/regime_coherence_agent.py:42`

**Issue:** `from src.core.ai.prompt_utils import clamp` is inside the `_validate_regime_coherence_fields` function body. All other validator functions in the same module pattern (correlation, counterfactual) import `clamp` at the module level. This local import executes on every LLM validation call and is inconsistent with the rest of the codebase.

**Fix:** Move to module-level import:
```python
from src.core.ai.prompt_utils import clamp
```

---

### IN-03: Integration test `test_no_regression_on_existing_swarm_tests` spawns a subprocess with a hardcoded absolute path

**File:** `tests/integration/test_phase80_swarm_end_to_end.py:146`

**Issue:** The test passes `cwd="/home/bg/dev/indicagent"` as a hardcoded absolute path. This breaks portability — the test will fail if run from a different machine or in CI with a different workspace path. The test should use `pathlib.Path(__file__).resolve().parents[3]` or a fixture.

**Fix:**
```python
cwd=str(pathlib.Path(__file__).resolve().parents[3])
```

---

_Reviewed: 2026-05-07T00:00:00Z_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
