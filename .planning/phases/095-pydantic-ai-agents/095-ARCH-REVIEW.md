---
phase: 095-pydantic-ai-agents
reviewed: 2026-06-02T00:00:00Z
depth: deep
files_reviewed: 16
files_reviewed_list:
  - src/core/ai/worker_context.py
  - src/core/ai/llm_adapter.py
  - src/core/ai/base_agent.py
  - src/core/llm/chain.py
  - src/core/llm/litellm_backend.py
  - src/intelligence/ai/alpha/skeptic_agent.py
  - services/alpha_swarm.py
  - src/api/routes/ai_stats.py
  - tools/validate_skeptic.py
  - tests/unit/core/test_core_ai_worker_context.py
  - tests/unit/core/test_core_ai_llm_adapter.py
  - tests/unit/core/test_core_ai_base_agent.py
  - tests/unit/core/test_llm_response_format.py
  - tests/unit/services/test_alpha_swarm.py
  - tests/unit/services/test_skeptic_agent.py
  - tests/integration/test_swarm_graduation_loop.py
findings:
  critical: 4
  warning: 7
  info: 4
  total: 15
status: issues_found
---

# Phase 095: Code Review Report — Pydantic-AI Agent Execution Layer

**Reviewed:** 2026-06-02
**Depth:** deep (cross-file, call-chain tracing, weight learning correctness, async correctness)
**Files Reviewed:** 16
**Status:** issues_found

## Summary

The Phase 095 implementation is structurally sound. The pydantic-ai integration (`WorkerContext`, `LLMAdapter`, `_run_typed()`) is well-designed: the Ring 0/1 boundary is respected, the single-use FunctionModel pattern is correct, and the per-request call_id stamping prevents duplicate audit rows on retries. The graduation loop (Spearman weight learning) and signal dispatch pipeline are architecturally clean.

Four blockers and seven warnings were found. The most severe: `tools/validate_skeptic.py` is completely broken — it queries a table (`alpha_multiplier_shadow`) that is no longer written to and a column (`pnl_r`) that was moved to `signal_outcomes` in migration 095. Two silent data-corruption paths exist in `alpha_swarm.py`: a falsy-zero bug in the confidence gate and a multiplier=1.0 default in lineage recording that diverges from the dispatch value. The graduation Spearman query allows NULL `pnl_r` rows through without filtering, causing the exception handler to silently default `rho=0.0`.

---

## Critical Issues

### CR-01: `validate_skeptic.py` queries stale table and dropped columns

**File:** `tools/validate_skeptic.py:42,74,75`
**Issue:** `fetch_validation_data()` queries `alpha_multiplier_shadow` (replaced by `signal_lineage` in Phase 078) and JOINs directly to `signal_ledger` for `pnl_r`, `exit_at`, and `outcome` columns. Migration 095 moved all mutable lifecycle fields (`pnl_r`, `exit_at`, `outcome`) to the `signal_outcomes` table; `signal_ledger` no longer has those columns. The tool will either return zero rows (if `alpha_multiplier_shadow` is empty) or raise a PostgreSQL column-not-found error on the JOIN. No statistical validation is possible with this query.

```python
# BROKEN — alpha_multiplier_shadow is no longer written to (LineageRecorder replaced it).
# pnl_r, exit_at, outcome no longer exist on signal_ledger (migration 095 moved them to signal_outcomes).
FROM alpha_multiplier_shadow s
JOIN signal_ledger l ON s.signal_id::uuid = l.signal_id::uuid
WHERE l.exit_at IS NOT NULL AND l.outcome IS NOT NULL
```

**Fix:** Replace with a query against `signal_lineage` + `signal_ledger_full`:

```sql
SELECT
    sl.signal_id,
    sl.source AS agent_id,
    sl.symbol,
    sl.tf,
    sl.multiplier,
    (sl.metadata->'payload'->>'confidence')::float AS confidence,
    sl.ts,
    ledger.outcome,
    ledger.pnl_r
FROM signal_lineage sl
JOIN signal_ledger_full ledger ON ledger.signal_id = sl.signal_id
WHERE sl.event_type = 'agent_prediction'
  AND sl.source = $1
  AND sl.multiplier IS NOT NULL
  AND ledger.outcome IS NOT NULL
  AND ledger.pnl_r IS NOT NULL
  AND sl.ts >= NOW() - $2::interval
```

---

### CR-02: Graduation query allows NULL `pnl_r` rows; `spearmanr()` raises, silently defaults to `rho=0.0`

**File:** `services/alpha_swarm.py:302-338`
**Issue:** The graduation query filters `ledger.outcome IS NOT NULL` but NOT `ledger.pnl_r IS NOT NULL`. Outcomes such as `never_activated` can have a non-null `outcome` but a null `pnl_r`. asyncpg returns `None` for NULL, and `scipy.stats.spearmanr([..., None, ...], [...])` raises `TypeError: '<' not supported between instances of 'NoneType' and 'float'`. The `except Exception: rho = 0.0` at line 338 silently catches this and uses `rho=0.0`, producing `weight = max(floor, 0.5) = 0.5`. An agent whose Spearman computation errored silently gets the same weight as a completely untested agent. This poisons the weight store without any log entry.

```python
# CURRENT (broken) — no pnl_r filter
WHERE sl.event_type = 'agent_prediction'
  AND sl.source = $1
  AND sl.multiplier IS NOT NULL
  AND ledger.outcome IS NOT NULL      # <-- pnl_r can still be NULL here
  AND sl.ts > NOW() - INTERVAL '30 days'
```

**Fix:** Add `AND ledger.pnl_r IS NOT NULL` to the WHERE clause:

```sql
WHERE sl.event_type = 'agent_prediction'
  AND sl.source = $1
  AND sl.multiplier IS NOT NULL
  AND ledger.outcome IS NOT NULL
  AND ledger.pnl_r IS NOT NULL        -- <-- add this
  AND sl.ts > NOW() - INTERVAL '30 days'
```

Additionally, add a log line in the `except Exception` block so silent failures become visible:

```python
except Exception as exc:
    logger.warning(
        "graduation.spearman_failed", agent_id=agent_id, tf=tf, n=n, error=str(exc)
    )
    rho = 0.0
```

---

### CR-03: Falsy-zero bug in confidence gate and adjusted-confidence calculation

**File:** `services/alpha_swarm.py:494-496,620-621`
**Issue:** Both lines use `x or y` chaining to fall back between confidence fields. This treats `confidence=0.0` as falsy, so a signal with `confidence=0.0` silently reads `pre_quality_confidence` instead. At line 494-496, this means a zero-confidence signal could pass the gate if `pre_quality_confidence` is above `SWARM_MIN_CONFIDENCE`. At line 620-621, the adjusted_confidence emitted on the output topic uses the wrong field's value.

```python
# BROKEN: 0.0 is falsy — skips to pre_quality_confidence when confidence==0.0
signal_confidence = float(
    raw_signal.get("confidence") or raw_signal.get("pre_quality_confidence") or 0.0
)
# ...
original_confidence = signal_dict.get("confidence") or signal_dict.get(
    "pre_quality_confidence", 0.5
)
```

**Fix:** Use explicit `is None` checks:

```python
# Gate (line 494-496)
_conf = raw_signal.get("confidence")
if _conf is None:
    _conf = raw_signal.get("pre_quality_confidence")
signal_confidence = float(_conf) if _conf is not None else 0.0

# Adjusted confidence (line 620-621)
original_confidence = signal_dict.get("confidence")
if original_confidence is None:
    original_confidence = signal_dict.get("pre_quality_confidence", 0.5)
if not isinstance(original_confidence, (int, float)):
    original_confidence = 0.5
```

---

### CR-04: Lineage `multiplier=1.0` default diverges from dispatch `multiplier=None`

**File:** `services/alpha_swarm.py:703`
**Issue:** When a successful `AgentOutput` has no `"multiplier"` key in its payload, `_record_swarm_result` records `multiplier=1.0` in `signal_lineage` (line 703), while `_compute_final_multiplier` uses `result.payload.get("multiplier")` which returns `None` and skips the agent from the weighted average (line 412). The two code paths are inconsistent: lineage records 1.0 (contributing to future Spearman weight learning) while dispatch treats the agent as having produced no multiplier. This means the graduation loop could learn a positive Spearman correlation for a "1.0 phantom" that never actually influenced signals, silently biasing agent weights upward.

```python
# line 703 — lineage records 1.0
multiplier = None if is_error else result.payload.get("multiplier", 1.0)

# line 412 — dispatch skips the agent
m = result.payload.get("multiplier")  # None -> continue
if m is None:
    continue
```

**Fix:** Use consistent `None` default in `_record_swarm_result` so agents that don't emit a multiplier are excluded from Spearman training data:

```python
# _record_swarm_result line 703
multiplier = None if is_error else result.payload.get("multiplier")  # None, not 1.0
```

---

## Warnings

### WR-01: `rho_result.correlation is not None` guard is incorrect — the attribute is never `None`, it's NaN

**File:** `services/alpha_swarm.py:335-336`
**Issue:** `scipy.stats.spearmanr()` returns a `SignificanceResult` whose `.correlation` attribute is `nan` for degenerate inputs (e.g., constant array), never `None`. The `is not None` check at line 336 always evaluates to `True`, making the `else 0.0` branch dead code. The actual NaN guard on line 340 (`if rho != rho`) correctly handles the NaN case, but the misleading check suggests the author misunderstood the return type. Future maintainers may remove the line 340 guard thinking the `is not None` already covers it.

```python
# CURRENT (misleading): rho_result.correlation is never None
rho = (
    float(rho_result.correlation) if rho_result.correlation is not None else 0.0
)
if rho != rho:  # NaN guard
    rho = 0.0
```

**Fix:** Remove the dead `is not None` branch; keep only the NaN guard:

```python
try:
    rho = float(stats.spearmanr(multipliers, pnl_rs).statistic)
except Exception as exc:
    logger.warning("graduation.spearman_failed", ..., error=str(exc))
    rho = 0.0
if rho != rho:  # NaN guard for constant inputs
    rho = 0.0
```

Note: `.statistic` is the canonical attribute name in modern scipy (`SignificanceResult`); `.correlation` is a legacy alias. Using `.statistic` is clearer.

---

### WR-02: `_run_typed` comment says empty `ModelResponse` is "converted to neutral by compute() wrapper" — misleading framing

**File:** `src/core/ai/llm_adapter.py:146-149`
**Issue:** The comment at line 146-149 states "the agent's compute() wrapper converts this to neutral." This is true, but it happens via an exception thrown by pydantic-ai when it sees an empty `parts` list — not via a clean `None` return that the caller checks. With `retries=1`, pydantic-ai will re-enter `_request` a second time before giving up, minting a second `call_id` and making a second `chain.generate()` call. This is correct behavior, but it means a `chain.generate()` returning `None` costs up to 2 LLM calls before the neutral fallback is reached. The comment doesn't document this retry amplification.

**Fix:** Update the comment to document the retry path:

```python
# 6. None means all providers failed or guardrails rejected. Return empty ModelResponse;
#    pydantic-ai will retry once more (retries=1) via a second _request() call before
#    raising UnexpectedModelBehavior, which compute() catches and converts to neutral.
```

---

### WR-03: Weight learning look-ahead: the 30-day window is agnostic to signal resolution lag

**File:** `services/alpha_swarm.py:314`
**Issue:** The query filters `sl.ts > NOW() - INTERVAL '30 days'` using the time the agent made its prediction. Signals can remain unresolved for multiple days. This means a 30-day weight learning window actually uses predictions from up to 30 days ago, but outcomes may be biased toward faster-resolving setups (because slow-resolving ones from 29+ days ago haven't exited yet and are excluded by `ledger.outcome IS NOT NULL`). The effective training set is thus younger and shorter-holding-period-biased than the window implies. On a 30-day window with `min_n=100`, this is potentially significant for longer timeframes like 4h and 1d.

**Fix:** Either extend the window (e.g., 90 days for 4h/1d instruments), or filter by resolution time rather than prediction time:

```sql
AND ledger.exit_at > NOW() - INTERVAL '30 days'  -- resolved within window
```

This also prevents the subtle look-ahead of counting predictions from 28 days ago whose outcomes arrived last week but aren't representative of the model's current state.

---

### WR-04: `_process_one_signal` acquires semaphore AFTER context build and enrichment

**File:** `services/alpha_swarm.py:519-538`
**Issue:** The semaphore controls concurrent LLM calls (line 538), but `_context_cache.build()` (line 519) and `_enrich_context()` (line 534) are called BEFORE the semaphore is acquired. Under high load, when `SWARM_MAX_CONCURRENT_CALLS` slots are full, every incoming signal still builds context (a non-trivial operation: tier aggregation across the cache) and enriches it before blocking at the semaphore. This defeats the semaphore's purpose of limiting the total compute cost per signal, not just the LLM call portion. The context data built pre-semaphore may also be stale by the time the semaphore is acquired under heavy backpressure.

**Fix:** Move the semaphore acquire to before the full context build (or at minimum before the per-agent contexts in the try block). The SMC-only context for `_enrich_context` is lightweight and can stay outside if needed, but the per-agent context builds should be inside the semaphore.

---

### WR-05: `stated_confidence` NaN propagation in `calibration_error` via `(metadata->'payload'->>'confidence')::float`

**File:** `services/alpha_swarm.py:306,344-346`
**Issue:** The SQL expression `(sl.metadata->'payload'->>'confidence')::float` returns `NULL` if the `payload.confidence` JSON key is absent, and the Python code filters `if g["stated_confidence"] is not None`. However, if `payload.confidence` exists but holds a non-numeric string (e.g., `"N/A"` from a prompt formatting bug), the PostgreSQL `::float` cast would raise an exception at the DB level, crashing the entire `_evaluate_agent` call for that agent. The outer `try/except` in `_run_graduation_cycle` would catch it, but this would permanently skip that agent's weight update until the bad row is manually cleaned.

**Fix:** Use `NULLIF` to guard the cast:

```sql
NULLIF((sl.metadata->'payload'->>'confidence'), '')::float AS stated_confidence
```

---

### WR-06: `_SWARM_AGENT_TO_TRANSFORM` map is defined but never used in the reviewed code

**File:** `services/alpha_swarm.py:74-80`
**Issue:** `_SWARM_AGENT_TO_TRANSFORM` maps agent IDs to `(transform_name, tier_level)` tuples and is referenced in docstrings ("D-22"), but there is no call site in this file that reads from it. `_record_swarm_result` uses `agent.agent_id` and `agent.group` directly without consulting the map. If this was intended to gate which agents get lineage recorded at tier 6, it is silently bypassed.

**Fix:** Either wire it into `_record_swarm_result` where `tier_level` is needed, or delete the constant and its references in comments. Dead constants with authoritative-sounding names cause future maintainers to trust them.

---

### WR-07: `_resolve_lead()` is defined but never called in `_process_one_signal` or `_record_swarm_result`

**File:** `services/alpha_swarm.py:91-100`
**Issue:** `_resolve_lead()` and `_LEAD_MAP` are tested and documented (ES -> NQ lead resolution for correlation), but no call site exists in the signal processing pipeline. The lead-context-based correlation feature was deleted in Phase 078, but the dead function and map were not removed. Tests for `_resolve_lead()` pass (they test a function that does nothing in production), creating false confidence that lead-index logic is active.

**Fix:** Remove `_resolve_lead()`, `_LEAD_MAP`, and the associated tests (`test_lead_map_*`, `test_es_lead_is_nq`). If lead-index correlation is planned for a future phase, re-introduce at that time.

---

## Info

### IN-01: `import time as _time` inside hot path function is repeated on every signal

**File:** `services/alpha_swarm.py:501`
**Issue:** `import time as _time` is a local import inside `_process_one_signal()`, which is invoked for every qualifying signal. Python module imports are cached after the first call (no re-import penalty), but the lookup through `sys.modules` on every call is unnecessary noise. The standard `time` module is safe to import at module level.

**Fix:** Move `import time` to the module-level imports at the top of the file.

---

### IN-02: `_build_audit_context` sets `called_at` to a timestamp that is immediately discarded in `_run_typed`

**File:** `src/core/ai/base_agent.py:397-401`
**Issue:** The `_run_typed()` inline comment (line 397-401) acknowledges that `_build_audit_context()` stamps `called_at=datetime.now()` which is then overwritten by `LLMAdapter._request()` with a fresh timestamp. The first timestamp is wasted. This is low-cost but the ambiguity makes the audit trail harder to reason about.

**Fix:** Either pass `called_at=""` explicitly to `_build_audit_context()` for the `_run_typed()` path, or add a `skip_called_at` flag. The simpler option is to just pop it from the base dict:

```python
audit_context = self._build_audit_context(context, prompt, call_id="")
audit_context.pop("called_at", None)  # adapter stamps fresh timestamp per request
```

---

### IN-03: `test_build_prompt_fills_fields` assertion `"N/A" not in prompt` is fragile

**File:** `tests/unit/services/test_skeptic_agent.py:63`
**Issue:** The test asserts `"N/A" not in prompt` for the v1 path after providing a dict where `vol_percentile`, `ts`, `ctf_score`, and `ctf_structure_alignment` are explicitly `None`. These keys are not template variables in the v1 template, so their None values are harmless. However, if the template is extended to include any of these fields and the test dict is not updated, the assertion will silently pass even though `N/A` appears in the output (because the new field is absent from the test context). The test should assert on specific expected field values instead.

**Fix:** Replace the negative assertion with positive assertions on specific fields:

```python
assert "12.50" in prompt  # atr
assert "25.3" in prompt   # adx
assert "55.0" in prompt   # rsi
assert "4500.00" in prompt  # vwap
```

---

### IN-04: `output_schema` ClassVar on `SkepticEvaluator` is acknowledged as duplicate of `result_type` but has no removal plan

**File:** `src/intelligence/ai/alpha/skeptic_agent.py:49-54`
**Issue:** The TODO comment on line 47 notes that `output_schema` duplicates `result_type = SkepticResult`. As long as both exist, a maintainer changing `SkepticResult`'s fields must update both, and the schema enforcement for other agents is split across two mechanisms. The comment correctly identifies the retirement plan but leaves it open-ended.

**Fix:** Create a GitHub issue or add a `# TODO(Phase-097):` tag with the explicit target phase, so the debt doesn't persist silently across multiple planning cycles.

---

_Reviewed: 2026-06-02_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: deep_
