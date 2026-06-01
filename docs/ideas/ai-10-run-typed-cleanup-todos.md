# Phase 095 _run_typed Deferred Cleanup

Captured during `/simplify` pass on Phase 095 (2026-05-31). All four items were
judged out of scope for the diff but worth tracking.

---

## 1. Consolidate span error-recording to `observed_span`

**Where:** `src/core/ai/base_agent.py` — `_run_typed`, `_llm_generate`, `_llm_generate_structured`

All three methods repeat the same `with self.tracer.start_as_current_span(...) as span: try/except span.set_status(ERROR) + record_exception + raise` skeleton. `observed_span()` in `src/observability/spans.py` does this automatically.

**Blocker:** `observed_span` carries an editorial "pipeline-only" restriction in its docstring. Lift that restriction, then replace the manual try/except in all three methods. No behavior change — purely a maintenance improvement.

---

## 2. `TypedOutputMixin` — move `_run_typed` off `BaseAIWorker`

**Where:** `src/core/ai/base_agent.py` — `result_type` ClassVar, `_run_typed()`, `__init_subclass__` guard

`_run_typed()` lives on `BaseAIWorker`, so every agent inherits a method that raises `RuntimeError` on them by design if they don't set `result_type`. The right depth: a `TypedOutputMixin` with an abstract `result_type` property, mixed in only by agents that declare structured output. This makes the contract visible from the type signature rather than enforced at call time.

**Precondition:** More agents need to adopt `_run_typed()` first so the pattern is stable before abstracting it.

---

## 3. `output_schema` retirement in `Evaluator`

**Where:** `src/intelligence/ai/alpha/skeptic_agent.py`, and `src/core/ai/evaluator.py`

`SkepticEvaluator.output_schema` documents the same four fields that `result_type = SkepticResult` enforces structurally via Pydantic. After the `_run_typed()` migration, `output_schema` is vestigial documentation — it no longer gates anything at runtime.

**Precondition:** All `Evaluator` subclasses migrate to `_run_typed()`. Then remove `output_schema` from `Evaluator` and all subclasses.

---

## 4. `called_at` redundancy in `_run_typed` audit context

**Where:** `src/core/ai/base_agent.py:385` and `src/core/ai/llm_adapter.py:128`

`_build_audit_context()` computes `called_at = format_iso_ts(datetime.now(UTC))` and includes it in the base dict. `llm_adapter._request()` unconditionally overwrites it with a fresh `datetime.now(UTC)` before every chain call. The outer `called_at` is always discarded.

**Fix:** Either omit `called_at` from the dict when building the audit base for the `_run_typed` path, or document the placeholder intent explicitly so readers understand the first timestamp is intentionally a throwaway. Note: `_llm_generate` goes through `chain.generate()` (not the adapter), so its `called_at` is actually used — don't remove it from `_build_audit_context` globally.
