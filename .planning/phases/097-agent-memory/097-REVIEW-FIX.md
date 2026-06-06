---
phase: 097-agent-memory
fixed_at: 2026-06-06T03:08:00Z
review_path: .planning/phases/097-agent-memory/097-REVIEW.md
iteration: 1
findings_in_scope: 6
fixed: 6
skipped: 0
status: all_fixed
---

# Phase 097 (Agent Memory): Code Review Fix Report

**Fixed at:** 2026-06-06T03:08:00Z
**Source review:** `.planning/phases/097-agent-memory/097-REVIEW-FIX.md` (original review findings)
**Iteration:** 1

**Summary:**
- Findings in scope: 6 (2 Critical, 4 Warning; 3 Info findings skipped per instructions)
- Fixed: 6
- Skipped: 0

## Fixed Issues

### CR-01: `config/memory.yaml` is never loaded

**Files modified:** `src/config/settings.py`, `src/core/memory/factory.py`, `config/memory.yaml` (deleted)
**Commit:** `00e8e759`
**Applied fix:** Added `memory_recall_limit: int` (env alias `MEMORY_RECALL_LIMIT`, default 10) and `memory_embed_timeout_ms: int` (env alias `MEMORY_EMBED_TIMEOUT_MS`, default 30) to `Settings`. Updated `build_memory_client()` in `factory.py` to pass `recall_limit=settings.memory_recall_limit` and `embed_timeout_ms=settings.memory_embed_timeout_ms` to `MemoryClient`. Deleted `config/memory.yaml` — the tunables are now live via env vars consistent with the rest of the codebase.

---

### CR-02: `--seed-only` flag deletes seeded rows via `finally` block

**Files modified:** `production/scripts/memory_recall_benchmark.py`
**Commit:** `0465a1d7`
**Applied fix:** Moved the seeding step and the `--seed-only` early exit to before the `try/finally` block. When `--seed-only` is set, the function now calls `await pool.close()` and returns before the `try` block is entered, so `cleanup_bench_rows()` in `finally` never runs. Seeded rows are retained in the DB as advertised.

---

### WR-01: Falsy zero drops legitimate percentile tokens in `serialize()`

**Files modified:** `src/core/memory/embedding.py`
**Commit:** `c4b95879`
**Applied fix:** Replaced all `or`-chaining on numeric fallback attributes with explicit two-step `is None` guards across all 7 numeric fields (`trend_score`, `ctf_score`, `rsi_pct`, `atr_pct`, `swing_structure`, `vol_pct`, `mom_pct`). A value of `0.0` (e.g., RSI at 0th percentile) is now correctly included in the embedding text rather than silently dropped.

---

### WR-02: Outer `except Exception` mislabels all errors as `"timeout"` in OTel

**Files modified:** `src/core/memory/client.py`
**Commit:** `75c1c005`
**Applied fix:** Changed `result="timeout"` to `result="error"` in the outer `except Exception` block of `MemoryClient.recall()`. Embed-timeout exceptions (caught by the inner `except TimeoutError`) still record `result="timeout"`. DB failures, type errors, and other non-timeout exceptions now record `result="error"`, making them distinguishable in Grafana dashboards.

---

### WR-03: `MEMORY_EMBED_LATENCY_MS` not recorded on failure paths

**Files modified:** `src/core/memory/embedding.py`
**Commit:** `f2f29933`
**Applied fix:** Moved the `MEMORY_EMBED_LATENCY_MS.record()` call from the success path to a `finally` block in `embed()`. The metric is now recorded on all three exit paths: success (returns vector), dimension mismatch (returns None), and exception (returns None). The histogram now reflects real degradation latency during Ollama failures.

---

### WR-04: Benchmark calls `embed_context()` twice per iteration

**Files modified:** `production/scripts/memory_recall_benchmark.py`
**Commit:** `84b566d1`
**Applied fix:** Removed the standalone external `embedding.embed_context(ctx)` call and `embed_times` tracking from the benchmark loop. Each iteration now calls only `client.recall()` once, which internally calls `embed_context()` as part of the recall path. In fake-embed mode the embed contribution is negligible by design and `hnsw_p95 ~ total_p95`; in live-embed mode, `total_p95` reflects the full end-to-end path. The `embed_p50_ms` / `embed_p95_ms` fields in the result dict report `0.0` in fake mode and `nan` in live mode to make the measurement scope explicit.

---

## Skipped Issues

None — all in-scope findings were fixed.

## Info Findings (out of scope)

- IN-01: `test_serialize_swing_structure_token` only exercises fallback path — not fixed (non-blocking)
- IN-02: `config/memory.yaml` budget arithmetic inconsistency — moot after CR-01 deleted the file
- IN-03: `hasattr(agent, "set_memory_client")` guard always true — not fixed (non-blocking)

## Test Results

`.venv/bin/pytest tests/unit/core/ -q --tb=short`: **515 passed, 1 skipped**

---

_Fixed: 2026-06-06T03:08:00Z_
_Fixer: Claude (gsd-code-fixer)_
_Iteration: 1_
