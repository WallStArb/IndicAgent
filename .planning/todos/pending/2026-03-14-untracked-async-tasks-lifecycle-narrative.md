# Track asyncio.create_task() Results in Lifecycle and Narrative Services

**Priority:** Medium
**Effort:** Small (1–2h)
**Created:** 2026-03-14
**Related:** `2026-03-07-improve-llm-call-tracking.md` (narrative service), `2026-02-28-offload-plugin-pipeline-to-thread-pool.md` (async concurrency)

## Problem

Both `signal_lifecycle_service.py` and `ai_narrative_service.py` spawn fire-and-forget `asyncio.create_task()` calls in their inner loops without tracking or awaiting the results:

**signal_lifecycle_service.py** — lines 373, 412, 514:
```python
asyncio.create_task(self._kafka_producer.publish(...))     # outcome publish
asyncio.create_task(self._publish_terminal_event(...))     # twice per exit
```
Called inside `_evaluate_signals_against_bar()` which runs per-signal per-bar. Under full load (60 symbols × 4 TFs × ~50 active signals), this spawns thousands of untracked tasks per minute.

**ai_narrative_service.py** — lines 1001, 1011:
```python
asyncio.create_task(self._run_narrative_call(..., "narrative_short", ...))
asyncio.create_task(self._run_narrative_call(..., "narrative_deep", ...))
```
Ollama timeout is 60s — if it stalls, tasks pile up. No failure visibility.

## Risks

- **Unbounded accumulation**: asyncio event loop queues tasks until completion; backpressure from slow Kafka/Ollama is invisible
- **Silent failures**: exceptions inside untracked tasks are swallowed (Python 3.11 logs them as warnings but doesn't propagate)
- **OOM risk** in narrative service: two LLM tasks per signal × 60 symbols × 4 TFs can easily reach 1000+ pending tasks if Ollama network stalls

## Fix

Track tasks in a set, add a done-callback to remove on completion and log errors:

```python
# In __init__:
self._pending_tasks: set[asyncio.Task] = set()

# When spawning:
task = asyncio.create_task(self._kafka_producer.publish(...))
self._pending_tasks.add(task)
task.add_done_callback(self._pending_tasks.discard)

# On shutdown:
if self._pending_tasks:
    await asyncio.gather(*self._pending_tasks, return_exceptions=True)
```

Add error logging in the done-callback:
```python
def _on_task_done(self, task: asyncio.Task) -> None:
    self._pending_tasks.discard(task)
    if not task.cancelled() and task.exception():
        self.logger.error("background task failed", error=str(task.exception()))
```

## Files

- `services/signal_lifecycle_service.py` — lifecycle Kafka publish tasks
- `services/ai_narrative_service.py` — narrative LLM call tasks

## Notes

- `asyncio.TaskGroup` (Python 3.11+) would be cleaner but requires restructuring the loop — the `_pending_tasks` set pattern is lower-risk
- This is distinct from the LLM tracking todo (`2026-03-07`) which is about what data gets logged, not task lifecycle
