# Phase 094: Instructor Structured Output - Research

**Researched:** 2026-05-20
**Domain:** Instructor library + LiteLLM integration + BaseAIAgent structured parse refactor
**Confidence:** HIGH

---

## Summary

Phase 094 replaces the `_parse_multiplier_response` + `_validate_*_fields` boilerplate across 4 alpha agents (skeptic, correlation, counterfactual, regime_coherence) with Instructor-enforced structured output. Instead of returning a raw string and parsing it manually, each agent calls `_llm_generate_structured()` on `BaseAIAgent`, which uses `instructor.from_litellm(acompletion)` to enforce a Pydantic `BaseModel` result type and retry on validation failure.

The critical architectural question is whether `instructor.from_litellm(acompletion)` bypasses `LiteLLMBackend` (the Phase 093 deliverable). It does — `acompletion` is the raw LiteLLM async function, not the `LiteLLMBackend` wrapper. This means Instructor's retry loop calls `acompletion` directly, bypassing `LiteLLMBackend`'s circuit breakers and provider fallback routing. The design doc acknowledges this and defers the circuit-breaker integration to Phase 3 (Pydantic AI). This is an acceptable tradeoff for Phase 094 given the scope, but needs to be documented.

**Primary recommendation:** Implement exactly as described in the design doc. Use `instructor.from_litellm(acompletion)` as a module-level singleton. Accept the circuit-breaker bypass as a known limitation. Document it clearly with a TODO for Phase 095 to integrate.

---

## Standard Stack

### Core

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| instructor | >=1.3.0 | Structured output + auto-retry on Pydantic `ValidationError` | Wraps LiteLLM `acompletion`; `from_litellm` API confirmed stable in current PyPI version 1.15.1 |
| pydantic | >=2.0 (already at 2.13.3) | Result model definitions | Already installed; `BaseModel` + `Field` validators replace `_validate_*_fields` |
| litellm | >=1.40.0 (Phase 093 dep) | Provides `acompletion` that Instructor wraps | Phase 093 installs this |

### Supporting

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| openai | (installed by instructor) | Required by LiteLLM and Instructor internally | Installed transitively; no direct use |

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| `instructor.from_litellm(acompletion)` | `instructor.from_provider("litellm/...", async_client=True)` | `from_provider` does NOT support "litellm" as a provider per GitHub issue #1710; `from_litellm` is the correct path |
| `instructor.from_litellm(acompletion)` | Wrap `LiteLLMBackend` directly | `LiteLLMBackend` is not an OpenAI-compatible client object; Instructor needs the raw `acompletion` callable |

**Installation:**
```bash
uv pip install instructor
```
(adds `instructor>=1.3.0` to requirements.txt; `openai` is a transitive dep)

---

## Architecture Patterns

### Recommended Project Structure

No new directories. Files are:
```
src/core/ai/
├── structured_client.py    # NEW — instructor.from_litellm singleton
├── base_agent.py           # MODIFY — add _llm_generate_structured()
└── multiplier_agent.py     # MODIFY — remove _parse_multiplier_response

src/intelligence/ai/alpha/
├── skeptic_prompts.py      # MODIFY — add SkepticResult, delete _validate_skeptic_fields
├── skeptic_agent.py        # MODIFY — use structured call
├── correlation_agent.py    # MODIFY — add CorrelationResult, migrate
├── counterfactual_agent.py # MODIFY — add CounterfactualResult, migrate
└── regime_coherence_agent.py # MODIFY — add RegimeCoherenceResult, migrate
```

### Pattern 1: Instructor Singleton

**What:** Module-level `INSTRUCTOR_CLIENT = instructor.from_litellm(acompletion)` in `structured_client.py`. The design doc aliases it in `base_agent.py` as `_INSTRUCTOR_CLIENT` for test patchability.

**When to use:** All structured LLM calls in `BaseAIAgent` subclasses.

```python
# src/core/ai/structured_client.py
import instructor
from litellm import acompletion

INSTRUCTOR_CLIENT = instructor.from_litellm(acompletion)
```

```python
# src/core/ai/base_agent.py (module level)
from src.core.ai.structured_client import INSTRUCTOR_CLIENT
_INSTRUCTOR_CLIENT = INSTRUCTOR_CLIENT  # alias for test patching
```

### Pattern 2: _llm_generate_structured Method

**What:** New async method on `BaseAIAgent` that replaces the `_llm_generate` + `_parse_multiplier_response` two-step.

**Key signature difference from `_llm_generate`:** Takes `result_type: type[_T]` and returns `_T | None`. No `call_id` return — Instructor handles retry internally.

```python
async def _llm_generate_structured(
    self,
    context: AIContext,
    result_type: type[_T],
    prompt: str,
    system: str,
    max_tokens: int,
    timeout: float,
    max_retries: int = 2,
) -> _T | None:
    providers = getattr(getattr(self._llm, "_inner", None), "providers", None) or []
    if not providers:
        return None
    # calls _INSTRUCTOR_CLIENT.chat.completions.create(
    #   model=providers[0], messages=[...], response_model=result_type,
    #   max_tokens=max_tokens, max_retries=max_retries
    # ) wrapped in asyncio.wait_for(timeout=timeout)
```

**IMPORTANT — provider selection:** `_INSTRUCTOR_CLIENT` calls `acompletion` directly with a model string. The `providers` list from `LiteLLMBackend` (post-093) is `list[str]` of LiteLLM model strings (e.g. `"ollama/nemotron-3-nano:4b"`). Pass `providers[0]` — primary only. Fallback is NOT automatic here (unlike `LiteLLMBackend.generate()` which tries all providers in sequence). This is the known circuit-breaker bypass tradeoff.

### Pattern 3: Per-Agent Result Model

**What:** Each agent defines a Pydantic `BaseModel` in its prompts file (same file as the prompt it replaces). Validators use `Field(ge=0.0, le=1.0)` instead of `clamp()` calls. `field_validator` handles coercion for `list[str]` fields.

```python
# In skeptic_prompts.py — replaces _validate_skeptic_fields
class SkepticResult(BaseModel):
    failure_probability: float = Field(ge=0.0, le=1.0)
    confidence: float = Field(ge=0.0, le=1.0)
    risk_factors: list[str] = Field(default_factory=list)
    reasoning: str = Field(max_length=500)

    @field_validator("risk_factors", mode="before")
    @classmethod
    def coerce_to_list(cls, v: object) -> list[str]:
        if not isinstance(v, list):
            return [str(v)]
        return [str(x) for x in v]
```

### Anti-Patterns to Avoid

- **Do not wrap `LiteLLMBackend` with Instructor:** `LiteLLMBackend` is not an OpenAI client; it returns `str | None`. Instructor needs a callable that returns a completion response object.
- **Do not use `instructor.from_provider("litellm/...")`.** GitHub issue #1710 confirms this path doesn't work. Use `from_litellm(acompletion)`.
- **Do not call `_report_parse_failure(call_id)` in the structured path:** Instructor retries before returning. If it returns None (all retries exhausted), there's no `call_id` to report — the audit trail write doesn't happen. This is a known gap vs the `_llm_generate` path (see Open Questions).
- **Do not add `_llm_generate_structured` to the TEMPLATE_agent.py without also noting it doesn't update `llm_calls`.** The template currently shows the old parse pattern; it must be updated after this phase.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| JSON retry on parse failure | Custom retry loop checking response | `instructor.from_litellm(acompletion)` with `max_retries=2` | Instructor injects the Pydantic `ValidationError` into the prompt and retries — implementing this correctly requires understanding of Instructor's prompt injection format |
| Structured JSON coercion | `_validate_*_fields` + regex fallback | `BaseModel` + `field_validator` | Pydantic handles type coercion, field missing defaults, and range checks |

---

## Common Pitfalls

### Pitfall 1: from_litellm is async when given acompletion — confirmed

**What goes wrong:** Developer questions whether `from_litellm(acompletion)` returns a sync or async client.

**Why it happens:** The function name doesn't hint at async.

**How to avoid:** Confirmed via LiteLLM docs and GitHub examples: `from_litellm(acompletion)` returns an `AsyncInstructor` when passed the `acompletion` callable. The call is `await client.chat.completions.create(...)`. This is correct for the async `_llm_generate_structured` method.

**Warning signs:** If tests fail with "object is not awaitable", the sync `completion` was used instead of `acompletion`.

### Pitfall 2: Circuit breaker bypass

**What goes wrong:** Instructor calls `acompletion` directly. If Ollama is down, `LiteLLMBackend`'s circuit breaker (`_OLLAMA_CB`) does NOT open — only `LiteLLMBackend.generate()` checks it. The Instructor path will keep hammering Ollama until `max_retries` is exhausted.

**Why it happens:** Instructor wraps the raw callable, not `LiteLLMBackend`.

**How to avoid:** For Phase 094, accept this. The `asyncio.wait_for(timeout=timeout)` wrapper still enforces `latency_budget_ms`. Phase 095 (Pydantic AI) will integrate with `LiteLLMBackend` properly. Document this with a TODO comment in `structured_client.py`.

**Warning signs:** After Ollama goes down, alpha swarm LLM calls appear to timeout slowly instead of failing fast.

### Pitfall 3: No llm_calls audit trail on the structured path

**What goes wrong:** `_llm_generate` writes to `llm_calls` via `_publish_audit` in `LLMProviderChain`. `_llm_generate_structured` calls `acompletion` directly — no Kafka audit event, no `llm_calls` row.

**Why it happens:** Audit wiring lives in `LLMProviderChain._publish_audit`, which is bypassed.

**How to avoid:** This is a known Phase 094 limitation per the design doc ("Phase 3 (Pydantic AI) will unify both paths"). For the `parse_success` metric (STRUCT-OUT-03), the design doc correctly proposes measuring the before/after parse failure rate from the existing `llm_calls` rows that DO exist. Since `_llm_generate_structured` never produces `parse_success=False` rows (Instructor retries internally), the delta is directly observable: pre-migration rows have `parse_success=False` at the historical rate; post-migration there are no structured-path rows at all in `llm_calls`. The `LLM_PARSE_FAILURES` OTel counter (already in `observability/metrics.py`) is the observable metric — it stops incrementing for migrated agents.

**Warning signs:** After migration, `llm_calls` table has no rows for the 4 migrated agents. This is expected and correct.

### Pitfall 4: gemma4:e4b JSON mode concern

**What goes wrong:** gemma4:e4b requires explicit system message starting with `"OUTPUT ONLY RAW JSON..."` (see CLAUDE.md rule). Instructor may override or prepend to the system message on retry, potentially removing the mandatory JSON enforcement prefix.

**Why it happens:** Instructor's retry loop appends the `ValidationError` message to the conversation but typically doesn't modify the original system message. However, the injected retry message format is Instructor-controlled.

**How to avoid:** Keep the explicit `"OUTPUT ONLY RAW JSON. NO PROSE..."` system message. Instructor appends the validation error to the user turn, not the system turn. The existing `_SYSTEM_MESSAGE` strings in each agent file should be passed unchanged to `_llm_generate_structured(system=_SYSTEM_MESSAGE, ...)`.

**Note on production model:** nemotron-3-nano:4b is the current production model (not gemma4:e4b for alpha swarm). The JSON enforcement prefix is still required since the CLAUDE.md rule applies generally.

### Pitfall 5: output_schema ClassVar removal — TEMPLATE_agent.py also needs updating

**What goes wrong:** After removing `output_schema: ClassVar[dict]` from the 4 migrated agents, `TEMPLATE_agent.py` still shows the old pattern.

**How to avoid:** Update `TEMPLATE_agent.py` in Task 8 (cleanup) to show the new `_llm_generate_structured` + result model pattern.

---

## Code Examples

### Verified: Instructor async with litellm (from LiteLLM docs)

```python
# Source: https://docs.litellm.ai/docs/tutorials/instructor
import instructor
from litellm import acompletion
from pydantic import BaseModel

client = instructor.from_litellm(acompletion)

class User(BaseModel):
    name: str
    age: int

async def extract(text: str) -> User:
    return await client.chat.completions.create(
        model="ollama/nemotron-3-nano:4b",
        response_model=User,
        messages=[{"role": "user", "content": text}],
        max_retries=3,
    )
```

### Verified: _validate_skeptic_fields pattern to be deleted

```python
# Source: src/intelligence/ai/alpha/skeptic_prompts.py (lines 103-136)
# This entire function is replaced by SkepticResult BaseModel
def _validate_skeptic_fields(data: dict) -> dict[str, Any] | None:
    if not isinstance(data, dict):
        return None
    fp = data.get("failure_probability")
    conf = data.get("confidence")
    if not isinstance(fp, (int, float)) or not isinstance(conf, (int, float)):
        return None
    fp = clamp(float(fp), 0.0, 1.0)
    conf = clamp(float(conf), 0.0, 1.0)
    ...
```

### Verified: Current _parse_multiplier_response call chain

```python
# Source: src/intelligence/ai/alpha/skeptic_agent.py (line 85)
# AND src/core/ai/multiplier_agent.py (line 35-42)
# Two-step: LLM returns str -> parse -> validate -> dict
parsed = self._parse_multiplier_response(response, _validate_skeptic_fields)
# delegates to: parse_llm_json(raw, validator_fn) in prompt_utils.py
```

---

## Research Findings: 8 Specific Questions

### Q1: Does llm_calls already have parse_success column?

**Answer:** YES, confirmed via `\d llm_calls`. Column exists: `parse_success boolean DEFAULT true`. No migration needed. The column is already queryable for STRUCT-OUT-03 observability.

**Confidence:** HIGH (direct DB query)

### Q2: Is instructor.from_litellm(acompletion) async?

**Answer:** YES. `from_litellm(acompletion)` returns an `AsyncInstructor` instance. The call is `await client.chat.completions.create(...)`. Confirmed via LiteLLM docs and GitHub examples.

**Confidence:** HIGH (official docs + multiple source verification)

### Q3: Instructor retry vs existing circuit breakers in LiteLLMBackend

**Answer:** BYPASSED. `instructor.from_litellm(acompletion)` calls the raw `litellm.acompletion` function directly. `LiteLLMBackend`'s `_OLLAMA_CB` and `_REMOTE_CB` circuit breakers are NOT consulted. Instructor's `max_retries` loop retries on `ValidationError` only (parse failures), not on provider failures. Provider failures raise exceptions that propagate up to the `except Exception` handler in `_llm_generate_structured`, which returns `None`.

**Impact:** In practice, the `asyncio.wait_for(timeout=timeout)` wrapper (using `latency_budget_ms` = 120s) bounds the damage. For Phase 094, this is accepted. Phase 095 unifies.

**Confidence:** HIGH (verified by tracing the call path; `acompletion` is a module-level function in litellm, not the `LiteLLMBackend` instance)

### Q4: Instructor + gemma4:e4b / nemotron-3-nano:4b via Ollama/LiteLLM

**Answer:** Works with caveats. Instructor uses LiteLLM's JSON mode when available. For local Ollama models, Instructor auto-selects `TOOLS` or `JSON` mode based on model capabilities. The `"OUTPUT ONLY RAW JSON..."` system message prefix should be kept to reinforce JSON compliance (gemma4:e4b rule in CLAUDE.md). Instructor's retry adds the `ValidationError` to the user message, not the system message, so the JSON enforcement prefix survives retries.

**Confidence:** MEDIUM (inferred from Instructor behavior docs; not live-tested)

### Q5: Does _parse_multiplier_response do anything beyond JSON parsing?

**Answer:** No. `BaseMultiplierAgent._parse_multiplier_response` delegates entirely to `parse_llm_json(raw, validator_fn)` in `prompt_utils.py`. The validator functions do: (1) type check, (2) `clamp()` floats to [0,1], (3) coerce list/str fields. All of these are directly replaced by Pydantic `Field(ge=0, le=1)` and `field_validator`. Nothing is lost.

**Confidence:** HIGH (read source: `multiplier_agent.py` lines 35-42, `prompt_utils.py`)

### Q6: Are there other callers of _parse_multiplier_response or parse_llm_json?

**Answer:** Only the 4 alpha agents + `TEMPLATE_agent.py`. `parse_llm_json` is only imported in `multiplier_agent.py`. After migration, `parse_llm_json` in `prompt_utils.py` can stay (it may be useful for non-structured callers) or be deleted — check for any remaining references first.

Files with `_parse_multiplier_response` or `parse_llm_json`:
- `src/core/ai/multiplier_agent.py` — definition (delete after migration)
- `src/core/ai/prompt_utils.py` — definition of `parse_llm_json`
- `src/intelligence/ai/TEMPLATE_agent.py` — shows old pattern (must update)
- `src/intelligence/ai/alpha/skeptic_agent.py` — caller (migrate)
- `src/intelligence/ai/alpha/correlation_agent.py` — caller (migrate)
- `src/intelligence/ai/alpha/counterfactual_agent.py` — caller (migrate)
- `src/intelligence/ai/alpha/regime_coherence_agent.py` — caller (migrate)

**Confidence:** HIGH (grep verified)

### Q7: Are all _validate_*_fields functions the same pattern?

**Answer:** YES, structurally identical. All 4 functions: (1) check `isinstance(data, dict)`, (2) extract numeric fields and check type, (3) `clamp()` floats to [0,1], (4) coerce `list[str]` fields, (5) return sanitized dict or None. The specific field names differ:

- `_validate_skeptic_fields`: `failure_probability`, `confidence`, `risk_factors`, `reasoning`
- `_validate_correlation_fields`: `coherence_score`, `confidence`, `contradicting_assets`, `reasoning`
- `_validate_counterfactual_fields`: `plausibility`, `confidence`, `validation_conditions`, `invalidation_conditions`, `alternative_scenario`
- `_validate_regime_coherence_fields`: `regime_fit`, `confidence`, `supporting_factors`, `warning_factors`

Note: `_validate_skeptic_fields` and `_validate_regime_coherence_fields` live in their respective `_prompts.py` files. `_validate_correlation_fields` and `_validate_counterfactual_fields` are defined inline in the agent files.

**Confidence:** HIGH (read all 4 agent files)

### Q8: Does _llm_generate() write to llm_calls? Does _llm_generate_structured need to?

**Answer:** YES, `_llm_generate()` writes to `llm_calls` via `LLMProviderChain._publish_audit()` (audited via Kafka). `_llm_generate_structured()` does NOT write to `llm_calls` because it bypasses `LLMProviderChain`. This is a known Phase 094 gap. STRUCT-OUT-03 (parse_success observability) is still satisfied because: (a) the existing `parse_success` column in `llm_calls` already shows pre-migration failures, (b) the `LLM_PARSE_FAILURES` OTel counter stops incrementing for migrated agents post-migration, and (c) the delta is directly measurable. A Phase 095 TODO comment should note that `LiteLLMBackend` audit integration is needed.

**Confidence:** HIGH (read chain.py lines 245-273, base_agent.py lines 215-253)

---

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| `instructor.from_openai()`, `instructor.patch()` | `instructor.from_provider()` or `from_litellm()` | Instructor ~1.0 (2024) | Old patterns removed in recent versions |
| `from_provider("litellm/...")` | `from_litellm(acompletion)` | Current | `from_provider` doesn't support litellm as provider name (GitHub issue #1710) |

**Deprecated/outdated:**
- `instructor.patch()`: Removed in instructor 1.x — do not use
- `instructor.from_openai()`: Legacy helper removed — use `from_provider("openai/...")` or `from_litellm`

---

## Open Questions

1. **Audit trail gap for structured path**
   - What we know: `_llm_generate_structured` bypasses `LLMProviderChain._publish_audit`; no `llm_calls` row written
   - What's unclear: Does Phase 094 need to add minimal audit instrumentation, or is the OTel counter enough for STRUCT-OUT-03?
   - Recommendation: The OTel `LLM_PARSE_FAILURES` counter (decreases to zero) is sufficient to satisfy STRUCT-OUT-03 in Phase 094. Add a TODO comment. Full audit integration in Phase 095.

2. **instructor version compatibility with Python 3.13**
   - What we know: Project uses Python 3.13, pydantic 2.13.3. Instructor 1.15.1 is the latest (2026-04-03).
   - What's unclear: Whether `>=1.3.0` pin is sufficient or a tighter bound is needed.
   - Recommendation: Pin `instructor>=1.3.0,<2.0.0` to guard against breaking API changes. Verify install before writing code.

3. **max_retries default: 2 or 3?**
   - Design doc says `max_retries=2` but STRUCT-OUT-02 requirement says "retries up to max_retries=3".
   - Recommendation: Use `max_retries=2` in the implementation (matching design doc), with a method parameter default. Tests can verify retry count independently of the requirement wording.

---

## Sources

### Primary (HIGH confidence)

- Direct DB query: `\d llm_calls` — confirmed `parse_success boolean` column exists
- `src/core/ai/base_agent.py` — `_llm_generate` signature, audit context, `_report_parse_failure`
- `src/core/ai/multiplier_agent.py` — `_parse_multiplier_response` delegates to `parse_llm_json`
- `src/intelligence/ai/alpha/skeptic_agent.py` — current parse boilerplate pattern
- `src/intelligence/ai/alpha/skeptic_prompts.py` — `_validate_skeptic_fields` function (to be deleted)
- `src/core/llm/chain.py` — `_publish_audit`, `_generate_inner`, `_publish_parse_failure`
- `requirements.txt` — pydantic 2.12.0+, no openai, no litellm, no instructor present
- `docs/plans/2026-05-20-phase2-instructor.md` — PRIMARY design doc; authoritative for task structure

### Secondary (MEDIUM confidence)

- [LiteLLM Instructor tutorial](https://docs.litellm.ai/docs/tutorials/instructor) — confirms `from_litellm(acompletion)` async usage pattern
- [Instructor PyPI](https://pypi.org/project/instructor/) — latest version 1.15.1 (2026-04-03), litellm is optional extra
- [Instructor migration guide](https://python.useinstructor.com/concepts/migration/) — confirms old `patch()` patterns removed

### Tertiary (LOW confidence — needs verification)

- [GitHub issue #1710](https://github.com/567-labs/instructor/issues/1710) — `from_provider("litellm/...")` doesn't work; use `from_litellm` instead — cited by WebSearch, not directly verified

---

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — instructor confirmed available, pydantic 2.13.3 already installed, litellm is Phase 093 dep
- Architecture: HIGH — design doc provides exact patterns; verified against current source files
- Pitfalls: HIGH for Q1-Q6 (verified from source); MEDIUM for Q4 (gemma/ollama live test not run)
- Open questions: 3 minor, non-blocking items

**Research date:** 2026-05-20
**Valid until:** 2026-06-20 (instructor API is stable; litellm changes frequently but `from_litellm` path is stable)

---

## Phase 093 Dependency Status

**Phase 093 (LiteLLM Backend) is NOT yet shipped.** `src/core/llm/litellm_backend.py` does not exist and `litellm` is not installed in the venv. Phase 094 planning must note that all deliverables depend on Phase 093 being merged first. The design doc states this explicitly.

**What Phase 093 provides that Phase 094 uses:**
- `litellm` installed in the venv (enables `from litellm import acompletion`)
- `LiteLLMBackend` with `.providers` as `list[str]` of LiteLLM model strings
- `LLMProviderChain._inner` swapped to `LiteLLMBackend(settings)` — `providers[0]` gives the model string for Instructor calls

**What Phase 094 does NOT need from Phase 093:**
- Instructor does not call `LiteLLMBackend.generate()` — it calls `acompletion` directly
- Phase 094 only reads `self._llm._inner.providers` to extract the primary model string
