# Pipeline Reset Sentinel Event — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Auto-clear stale dashboard state when `pipeline_reset.py` runs, with no manual browser reload.

**Architecture:** `pipeline_reset.py` publishes a `pipeline_reset` event to a `system:events` Redis stream after clearing streams. The SSE handler forwards it as `system_event`. The dashboard's `useMarketStream` hook listens and nulls intelligence/signal/narrative state while preserving tick/bar/session data.

**Tech Stack:** Python (redis-py, sync), FastAPI SSE (async), TypeScript/React (EventSource API)

---

### Task 1: Add `system_events` stream key helper

**Files:**
- Modify: `src/core/stream_keys.py` (append after `llm_outcomes_stream`)
- Test: `tests/unit/test_stream_keys.py`

**Step 1: Write the failing test**

Add to `tests/unit/test_stream_keys.py`:

```python
from src.core.stream_keys import system_events


def test_system_events_no_prefix():
    assert system_events("") == "system:events"


def test_system_events_with_env_prefix():
    assert system_events("development:") == "development:system:events"
```

**Step 2: Run to verify it fails**

```
.venv/bin/pytest tests/unit/test_stream_keys.py -v
```

Expected: `ImportError: cannot import name 'system_events'`

**Step 3: Add the helper to `src/core/stream_keys.py`**

Add after the `llm_outcomes_stream` function (around line 75):

```python
def system_events(env_prefix: str) -> str:
    """Global stream for system-level events (e.g. pipeline_reset sentinel).

    Intentionally excluded from pipeline_reset _REDIS_PATTERNS so it survives
    the stream clear — reconnecting SSE clients still see the event via snapshot.
    """
    return f"{env_prefix}system:events"
```

Also add `"system_events"` to the `Literal` type in `get_stream_maxlen` signature and add a branch:
```python
    if kind == "system_events":
        return 50
```

**Step 4: Run to verify it passes**

```
.venv/bin/pytest tests/unit/test_stream_keys.py -v
```

Expected: all tests PASS

**Step 5: Commit**

```bash
git add src/core/stream_keys.py tests/unit/test_stream_keys.py
git commit -m "feat(stream-keys): add system_events key helper"
```

---

### Task 2: Wire `system:events` into the SSE handler

**Files:**
- Modify: `src/api/routes/sse.py`
- Test: `tests/unit/test_sse_stream_builder.py`

**Step 1: Write the failing tests**

Add to `tests/unit/test_sse_stream_builder.py`:

```python
def test_build_stream_list_includes_system_events():
    """Stream list always includes the global system:events stream."""
    from src.api.routes.sse import _build_stream_list
    streams = _build_stream_list(["ES"], "1m")
    assert any("system:events" in s for s in streams), \
        f"No system:events stream in {streams}"


def test_build_stream_list_includes_system_events_once():
    """system:events appears exactly once regardless of symbol count."""
    from src.api.routes.sse import _build_stream_list
    streams = _build_stream_list(["ES", "NQ", "RTY"], "1m")
    system_streams = [s for s in streams if "system:events" in s]
    assert len(system_streams) == 1, f"Expected 1 system:events, got {system_streams}"


def test_event_name_for_system_events_stream():
    """system:events maps to system_event."""
    from src.api.routes.sse import _event_name_for_stream
    assert _event_name_for_stream("system:events") == "system_event"


def test_event_name_for_env_prefixed_system_events():
    """Env-prefixed system:events maps to system_event."""
    from src.api.routes.sse import _event_name_for_stream
    assert _event_name_for_stream("development:system:events") == "system_event"
```

**Step 2: Run to verify they fail**

```
.venv/bin/pytest tests/unit/test_sse_stream_builder.py -v
```

Expected: 4 new tests FAIL

**Step 3: Update `src/api/routes/sse.py`**

First, add the import at the top with the other stream key imports:
```python
from ...core.stream_keys import system_events as sk_system_events
```

In `_build_stream_list()`, after the group narrative streams block (around line 118), append the system stream once:
```python
    # System events stream — global, not per-symbol
    streams.append(sk_system_events(env_prefix))
    return streams
```

In `_event_name_for_stream()`, add a branch before the final `return "message"` (around line 145):
```python
    if candidate.startswith("system:"):
        return "system_event"
```

**Step 4: Run to verify they pass**

```
.venv/bin/pytest tests/unit/test_sse_stream_builder.py -v
```

Expected: all tests PASS (including pre-existing ones)

**Step 5: Run full unit suite to check for regressions**

```
.venv/bin/pytest tests/unit/ -v --tb=short -q
```

Expected: all passing, no regressions

**Step 6: Commit**

```bash
git add src/api/routes/sse.py tests/unit/test_sse_stream_builder.py
git commit -m "feat(sse): add system:events stream to SSE subscription list"
```

---

### Task 3: Publish sentinel from `pipeline_reset.py`

**Files:**
- Modify: `production/scripts/pipeline_reset.py`
- Test: `tests/unit/scripts/test_pipeline_reset.py`

**Step 1: Write the failing test**

Add to `tests/unit/scripts/test_pipeline_reset.py`:

```python
def test_publish_reset_sentinel_publishes_correct_payload():
    """publish_reset_sentinel calls xadd with pipeline_reset event and symbol list."""
    from production.scripts.pipeline_reset import publish_reset_sentinel

    r = MagicMock()
    symbols = ["ESH6", "NQH6"]

    publish_reset_sentinel(r, env_prefix="development:", symbols=symbols)

    r.xadd.assert_called_once()
    call_args = r.xadd.call_args
    stream_key = call_args.args[0]
    payload = call_args.args[1]

    assert stream_key == "development:system:events"
    assert payload["event"] == "pipeline_reset"
    assert "ESH6" in payload["symbols"]
    assert "NQH6" in payload["symbols"]
    assert "ts" in payload


def test_publish_reset_sentinel_uses_maxlen_50():
    """xadd is called with maxlen=50 to cap stream size."""
    from production.scripts.pipeline_reset import publish_reset_sentinel

    r = MagicMock()
    publish_reset_sentinel(r, env_prefix="", symbols=["ESH6"])

    call_kwargs = r.xadd.call_args.kwargs
    assert call_kwargs.get("maxlen") == 50


def test_publish_reset_sentinel_uses_no_prefix():
    """Without env prefix, key is just 'system:events'."""
    from production.scripts.pipeline_reset import publish_reset_sentinel

    r = MagicMock()
    publish_reset_sentinel(r, env_prefix="", symbols=["ESH6"])

    stream_key = r.xadd.call_args.args[0]
    assert stream_key == "system:events"
```

**Step 2: Run to verify they fail**

```
.venv/bin/pytest tests/unit/scripts/test_pipeline_reset.py -v
```

Expected: 3 new tests FAIL with `ImportError: cannot import name 'publish_reset_sentinel'`

**Step 3: Add `publish_reset_sentinel` to `production/scripts/pipeline_reset.py`**

Add `import json` to the existing imports at the top (it may already be there — check first).

Add a new function after `clear_redis_streams()` (around line 121):

```python
def publish_reset_sentinel(r: redis.Redis, env_prefix: str, symbols: list[str]) -> None:
    """Publish a pipeline_reset event to system:events so SSE clients auto-clear state."""
    from src.core.stream_keys import system_events as sk_system_events

    key = sk_system_events(env_prefix)
    r.xadd(
        key,
        {
            "event": "pipeline_reset",
            "ts": datetime.now(UTC).isoformat(),
            "symbols": json.dumps(symbols),
        },
        maxlen=50,
    )
```

Then in `main()`, after the `clear_redis_streams` call and print (Stage 2, around line 252), add:

```python
    # Publish sentinel so connected SSE clients auto-clear stale state
    publish_reset_sentinel(r, env_prefix, target_symbols or [c.symbol for c in contracts])
    print("      Published pipeline_reset sentinel to system:events")
```

Note: `target_symbols` is defined in Stage 3 (DB truncation). Move the `target_symbols` assignment up to just before Stage 2 so it's available for the sentinel call. The current code has it at the top of Stage 3:

```python
    target_symbols = [s.strip() for s in args.symbols.split(",") if s.strip()] if args.symbols else None
```

Move this line to just before `_pause_for_services("stop", _STOP_SERVICES)` so it's available throughout.

**Step 4: Run to verify they pass**

```
.venv/bin/pytest tests/unit/scripts/test_pipeline_reset.py -v
```

Expected: all tests PASS (including pre-existing ones)

**Step 5: Run full unit suite**

```
.venv/bin/pytest tests/unit/ -v --tb=short -q
```

Expected: all passing

**Step 6: Commit**

```bash
git add production/scripts/pipeline_reset.py tests/unit/scripts/test_pipeline_reset.py
git commit -m "feat(pipeline-reset): publish sentinel to system:events after stream clear"
```

---

### Task 4: Handle `system_event` in the dashboard

**Files:**
- Modify: `dashboard/src/hooks/use-market-stream.ts`

No TypeScript test runner is configured (`tsconfig.json` excludes `**/__tests__/**`).
Verify correctness by TypeScript type-check only.

**Step 1: Add the event listener to `use-market-stream.ts`**

In the `useEffect` that sets up the SSE connection, add the `system_event` listener
after the `narrative_data` listener block (around line 688, just before the `return`
cleanup function):

```typescript
    // --- Pipeline reset sentinel — clear stale intelligence/signal/narrative state ---
    es.addEventListener("system_event", (evt) => {
      const { payload } = JSON.parse(evt.data) as { payload: Record<string, string> };
      if (payload.event !== "pipeline_reset") return;

      // Parse the symbol list from the sentinel payload.
      // Falls back to all active symbols if parsing fails.
      let resetSymbols: string[];
      try {
        resetSymbols = (JSON.parse(String(payload.symbols || "[]")) as string[]).map(contractToBase);
      } catch {
        resetSymbols = symbols;
      }

      setSymbolData((prev) => {
        const next = { ...prev };
        for (const sym of resetSymbols) {
          if (!next[sym]) continue;
          // Preserve tick, bar, session, prevClose — they're still valid.
          // Null out everything that flows through the intelligence pipeline.
          next[sym] = {
            ...next[sym],
            indicators: null,
            structure: null,
            context: null,
            patterns: null,
            smartMoney: null,
            confluence: null,
            signal: null,
            tfSignals: {},
            signalsByTf: {},
            indicatorsByTf: {},
            intelligenceByTf: {},
          };
        }
        return next;
      });

      setNarratives((prev) => {
        const next = { ...prev };
        for (const sym of resetSymbols) {
          for (const key of Object.keys(next).filter((k) => k.startsWith(`${sym}:`))) {
            delete next[key];
          }
        }
        return next;
      });

      setGroupNarratives({});
      touch();
    });
```

**Step 2: TypeScript type-check**

```bash
cd dashboard && npx tsc --noEmit 2>&1 | head -40
```

Expected: no errors

**Step 3: Lint check**

```bash
.venv/bin/ruff check . --fix
```

Expected: 0 errors (TypeScript files not checked by ruff)

**Step 4: Full unit test suite**

```
.venv/bin/pytest tests/unit/ -v --tb=short -q
```

Expected: all passing, count unchanged (no Python changes in this task)

**Step 5: Commit**

```bash
git add dashboard/src/hooks/use-market-stream.ts
git commit -m "feat(dashboard): clear stale state on pipeline_reset sentinel event"
```

---

### Task 5: Verify end-to-end

**Step 1: Run full test suite**

```
.venv/bin/pytest tests/unit/ -v --tb=short -q
```

Expected: all passing

**Step 2: Run ruff**

```
.venv/bin/ruff check .
```

Expected: 0 errors (only pre-existing E501 allowed)

**Step 3: Verify `pipeline_reset.py --dry-run` does NOT publish sentinel**

The sentinel is published inside `main()` after the `if args.dry_run: return` guard,
so `--dry-run` exits before it. Confirm by reading the code — the dry-run guard is at
line ~234-236 and returns before Stage 2.

**Step 4: Manual verification (optional)**

Run `pipeline_reset.py` against a dev environment with the dashboard open. After Stage 2
completes ("Published pipeline_reset sentinel"), signal cards and narratives should
blank out within ~5 seconds (next `xread` cycle). Tick prices and session data remain.

**Step 5: Final commit if any cleanup needed, then tag**

```bash
git log --oneline -5
```

Confirm all 4 feature commits are present. No tag needed — milestone housekeeping
is handled separately.
