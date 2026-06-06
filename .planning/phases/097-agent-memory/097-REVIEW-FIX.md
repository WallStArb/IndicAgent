---
phase: 097-agent-memory
reviewed: 2026-06-06T00:00:00Z
depth: standard
files_reviewed: 12
files_reviewed_list:
  - config/memory.yaml
  - docs/operations/memory-performance.md
  - production/scripts/memory_recall_benchmark.py
  - services/alpha_swarm.py
  - src/config/settings.py
  - src/core/ai/base_agent.py
  - src/core/memory/client.py
  - src/core/memory/embedding.py
  - src/core/memory/factory.py
  - tests/unit/core/test_base_agent_memory_wiring.py
  - tests/unit/core/test_embedding_service.py
  - tests/unit/core/test_memory_client.py
findings:
  critical: 2
  warning: 4
  info: 3
  total: 9
status: issues_found
---

# Phase 097 (Gap Closure): Code Review Report

**Reviewed:** 2026-06-06T00:00:00Z
**Depth:** standard
**Files Reviewed:** 12
**Status:** issues_found

## Summary

Review covers the three gap-closure plans (097-07 through 097-09): MemoryClient wiring through WorkerContext, embed timeout via `asyncio.wait_for`, and the EmbeddingService litellm migration. The wiring and timeout mechanics are structurally sound. Two critical issues were found: `config/memory.yaml` is dead configuration that is never loaded (its values are silently ignored, creating a false tuning surface), and the `--seed-only` flag in the benchmark defeats itself by triggering cleanup in the `finally` block. Four warnings address a zero-value falsy bug in serialization, mislabeled OTel metrics, missing latency metrics on failure paths, and a double-embed per iteration in the benchmark. Three info items cover test coverage gaps and documentation arithmetic.

## Critical Issues

### CR-01: `config/memory.yaml` is never loaded — all tunables silently ignored

**File:** `config/memory.yaml:1-51` / `src/core/memory/factory.py:87-93`

**Issue:** `config/memory.yaml` documents six tunable parameters (`epoch_decay`, `recall_limit`, `over_fetch_multiplier`, `hnsw_ef_search`, `timeout_ms`, `embed_timeout_ms`) but no code in `src/` or `services/` ever loads this file. There are zero `import yaml`, `yaml.safe_load`, or `ruamel` references in the memory subsystem. `build_memory_client()` constructs `MemoryClient` at `factory.py:87-93` using `MemoryClient` default arguments (`recall_limit=10`, `embed_timeout_ms=30`) — not values from the YAML. An operator editing `config/memory.yaml` to tune recall performance receives no feedback that the changes have no effect.

**Fix:** Either load the YAML in `build_memory_client()` and pass the values through, or delete `config/memory.yaml` and document the tunables as `Settings` fields with `validation_alias` env-var overrides (consistent with the rest of the codebase). The Settings pattern is preferred — it avoids a second config file format.

```python
# Option A: add to Settings (preferred — consistent with codebase pattern)
recall_limit: int = Field(default=10, validation_alias="MEMORY_RECALL_LIMIT")
embed_timeout_ms: int = Field(default=30, validation_alias="MEMORY_EMBED_TIMEOUT_MS")

# Then in factory.py:
client = MemoryClient(
    ...
    recall_limit=settings.recall_limit,
    embed_timeout_ms=settings.embed_timeout_ms,
)
```

---

### CR-02: `--seed-only` flag deletes seeded rows immediately via `finally` block

**File:** `production/scripts/memory_recall_benchmark.py:376-429`

**Issue:** `args.seed_only` causes a `return` at line 378, which is inside the `try` block at line 370. Python executes `finally` on all exits from a `try` block, including `return`. The `finally` at line 425 calls `cleanup_bench_rows(pool)`, which deletes all seeded rows. The `--seed-only` mode advertises "Seed rows and exit" but the rows are deleted before the process exits. The seeded cohort is never visible in the DB.

**Fix:** Move the seed-only early exit to before the `try` block, or use a flag to suppress cleanup in `finally`:

```python
    n_seeded = await seed_bench_rows(pool)
    print(f"  Inserted {n_seeded} rows into memory_episodes_labeled")

    if args.seed_only:
        print("\nSeed-only mode — rows retained. Run cleanup manually when done.")
        await pool.close()
        return

    try:
        # Benchmark
        ...
    finally:
        print("\n[4/4] Cleaning up BENCH rows...")
        await cleanup_bench_rows(pool)
        await pool.close()
```

---

## Warnings

### WR-01: Falsy zero drops legitimate percentile tokens in `EmbeddingService.serialize()`

**File:** `src/core/memory/embedding.py:130-164`

**Issue:** Eight numeric fields use `or`-chaining to select between primary and fallback attribute names:

```python
trend_score = getattr(context, "trend_score", None) or getattr(context, "ctf_trend", None)
rsi_pct = getattr(context, "rsi_pct", None) or getattr(context, "rsi_percentile", None)
atr_pct = getattr(context, "atr_pct", None) or getattr(context, "atr_percentile", None)
# ...and four more
```

`0.0` is falsy in Python. When `rsi_pct=0.0` (RSI at the 0th percentile — a genuine extreme reading), the `or` evaluates to `getattr(context, "rsi_percentile", None)`. If that fallback is also absent, the result is `None` and the `rsi_pct` token is silently omitted from the embedding text. Extreme readings at zero — which carry the strongest regime signal — are the most likely to be silently dropped. This corrupts embedding text at exactly the moments when embeddings should have the highest discriminative power.

**Fix:** Use explicit `is None` guards:

```python
trend_score = getattr(context, "trend_score", None)
if trend_score is None:
    trend_score = getattr(context, "ctf_trend", None)
if trend_score is not None:
    tokens.append(f"trend:{trend_score:.2f}")
```

---

### WR-02: Outer `except Exception` in `MemoryClient.recall()` mislabels all errors as `"timeout"` in OTel

**File:** `src/core/memory/client.py:170-177`

**Issue:** The outer `except Exception` block at line 170 unconditionally records `result="timeout"` for any non-timeout exception:

```python
except Exception as error:
    ...
    MEMORY_RECALL_RESULTS_TOTAL.add(1, {"tier": "1", "result": "timeout"})
```

A DB connection failure, an invalid return type from `EpisodicBackend`, or a `KeyError` in the recall path all produce `result="timeout"` in the `memory_recall_results_total` metric. Grafana dashboards alert on `result="timeout"` for the embed-timeout budget gate. A DB outage is indistinguishable from a latency spike in the metric. The comment at line 173-174 acknowledges this is intentional, but the `memory_recall_results_total` OTel spec in the docstring (line 10) lists `timeout` as a distinct outcome, implying it means "timed out", not "any error".

**Fix:** Add a distinct `"error"` label for non-timeout exceptions:

```python
except Exception as error:
    elapsed_ms = (time.monotonic() - t0) * 1000.0
    MEMORY_RECALL_LATENCY_MS.record(elapsed_ms, {"tier": "1", "symbol": symbol})
    MEMORY_RECALL_RESULTS_TOTAL.add(1, {"tier": "1", "result": "error"})
    log.warning("memory_client.recall_failed", agent_id=agent_id, error=str(error))
    return []
```

---

### WR-03: `MEMORY_EMBED_LATENCY_MS` not recorded on `embed()` failure or dim-mismatch paths

**File:** `src/core/memory/embedding.py:192-211`

**Issue:** `MEMORY_EMBED_LATENCY_MS` is only recorded on the success path (line 201). The dimension-mismatch branch (line 198, `return None`) and the exception branch (line 211, `return None`) both exit without recording the latency. During Ollama degradation (which is precisely when latency matters most), the embed histogram goes silent. p95 computed from the histogram reflects only healthy calls; degraded calls are invisible.

**Fix:** Move the latency record above the early return, or use `try/finally`:

```python
async def embed(self, text: str) -> list[float] | None:
    t0 = time.monotonic()
    try:
        response = await litellm.aembedding(
            model=self._model, input=[text], api_base=self._api_base
        )
        vector: list[float] = response.data[0]["embedding"]
        if len(vector) != _EMBED_DIM:
            log.warning("embedding_dimension_mismatch", ...)
            return None
        return vector
    except Exception as error:
        log.warning("embedding_failed", ...)
        return None
    finally:
        elapsed_ms = (time.monotonic() - t0) * 1000
        MEMORY_EMBED_LATENCY_MS.record(elapsed_ms, {"batch": "false"})
```

---

### WR-04: Benchmark calls `embed_context()` twice per iteration — doubles Ollama load in live mode

**File:** `production/scripts/memory_recall_benchmark.py:270-278`

**Issue:** Each benchmark iteration explicitly calls `embedding.embed_context(ctx)` at line 272 to measure external embed latency, then immediately calls `client.recall(ctx, ...)` at line 277. `MemoryClient.recall()` internally calls `self._embedding.embed_context(context)` at `client.py:125-128`. This means every benchmark iteration makes two embedding calls. In fake-embed mode the cost is negligible (list copy). In `--live-embed` mode, each iteration fires two Ollama HTTP requests. With `n=1000` (default), this issues 2,000 embedding requests instead of 1,000. More importantly, `hnsw_p95 = total_p95 - embed_p95` uses the external embed timing to approximate the internal embed contribution — this is a proxy, not a direct measurement, and can over- or under-estimate depending on Ollama scheduling jitter.

**Fix:** Time the embed step inside a real `recall()` using the existing OTel histogram (`MEMORY_EMBED_LATENCY_MS`) rather than a second external call. For isolation of the HNSW-only path, time the `EpisodicBackend.recall()` call directly:

```python
# Instead of:
t_embed_start = time.monotonic()
_ = await embedding.embed_context(ctx)
embed_times.append(...)

t0 = time.monotonic()
await client.recall(ctx, agent_id=_BENCH_AGENT_ID)
latencies.append(...)

# Use:
t0 = time.monotonic()
await client.recall(ctx, agent_id=_BENCH_AGENT_ID)
latencies.append((time.monotonic() - t0) * 1000.0)
# Then read MEMORY_EMBED_LATENCY_MS histogram from OTel for embed breakdown
```

---

## Info

### IN-01: Test for `serialize()` swing token uses fallback attribute name, not primary

**File:** `tests/unit/core/test_embedding_service.py:117-122`

**Issue:** `test_serialize_swing_structure_token` passes `swing="HL"` to `_context_with_percentiles()`, which creates a `SimpleNamespace` with attribute `swing`. `EmbeddingService.serialize()` looks for `swing_structure` first (line 150), then falls back to `swing`. The test exercises only the fallback path. If `swing_structure` were broken in the primary lookup (e.g., renamed to `swing_label`), this test would still pass via the fallback. No test verifies the primary attribute name `swing_structure`.

**Fix:** Add a test case with `swing_structure="HL"` (no `swing` attribute), assert `"swing:HL"` appears.

---

### IN-02: `config/memory.yaml` documents a budget that exceeds the stated agent ceiling

**File:** `config/memory.yaml:36-50`

**Issue:** Line 36 says "10ms margin under 50ms agent budget" justifying `timeout_ms=40`. Line 49 then states "Total recall budget: embed_timeout_ms (30ms) + backend timeout_ms (40ms) = 70ms". The 70ms total ceiling is 40% over the 50ms budget the file cites as its constraint. The doc is internally inconsistent: the 50ms ceiling and the 70ms arithmetic cannot both be correct bounds for the same operation. (Note: this is a docs issue in a config file that is already dead code per CR-01, but correcting it before making the file live prevents confusion.)

**Fix:** Update the comment to accurately state the budget: the 40ms backend gate and the 30ms embed gate are individual sub-budgets; the 50ms total agent budget is not met by their sum. Either reduce one of them (e.g., `embed_timeout_ms=10`) or document that the 50ms budget is an aspirational target, not a hard ceiling on the combined path.

---

### IN-03: `hasattr(agent, "set_memory_client")` guard in `AlphaSwarm._setup()` is always true

**File:** `services/alpha_swarm.py:147-149`

**Issue:**

```python
for agent in self._agents:
    if hasattr(agent, "set_memory_client"):
        agent.set_memory_client(self._memory_client)
```

All agents in `self._agents` are `Evaluator` subclasses, which extend `BaseAIWorker`. `set_memory_client()` is defined on `BaseAIWorker`. The `hasattr` check is always `True`. It suggests uncertainty about the agent type that does not exist — all swarm agents inherit from `Evaluator -> BaseAIWorker`. The check silently masks future refactoring where an agent is accidentally not derived from `BaseAIWorker`.

**Fix:** Remove the `hasattr` guard and call `set_memory_client()` directly. If forward compatibility with non-`BaseAIWorker` agents is genuinely needed, add a type assertion instead:

```python
for agent in self._agents:
    agent.set_memory_client(self._memory_client)
```

---

_Reviewed: 2026-06-06T00:00:00Z_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
