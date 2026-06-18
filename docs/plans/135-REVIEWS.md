---
phase: 135
reviewers: [codex, ollama]
reviewed_at: 2026-06-18T00:00:00Z
plans_reviewed: [docs/plans/2026-06-18-post-reboot-repair-design.md]
note: antigravity skipped (IDE-mode CLI, no stdout); claude skipped (self, running in Claude Code)
---

# Cross-AI Plan Review — Phase 135

## Codex Review

**Summary**
The plan is directionally correct and scoped to real post-reboot failures, but it is not deployment-safe yet. The biggest gaps are a breaking `validate_signal` API change, an incomplete SIGTERM fix that still leaves Kafka consumers blocked, and a "single source of truth" cleanup that will be undone by the current write paths unless those are changed too. The migration/order story also needs to be made explicit before replay or startup preflight is introduced.

**Strengths**
- W1 targets the right recovery path: replay from intact bar history instead of trying to patch missing feature rows by hand.
- W2 is the right kind of prevention for a missing-column regression: fail fast at startup instead of silently dropping writes.
- W3 recognizes that `TimeoutStopSec` alone is not a fix and pairs it with code-level stop handling.
- W4 isolates the noisy plugin without removing the upstream FVG zone features the rest of the stack still uses.
- W6 is a legitimate observability correction and should improve incident triage.
- The verification query for W1 is concrete and checks the exact failure mode being repaired.

**Concerns**
- **HIGH**: W5 changes `validate_signal` from `bool` to `tuple[bool, str]`, but call sites that use truthiness (`if validate_signal(...)`) will silently pass — non-empty tuples are always truthy. `services/signal_writer.py:112`, `src/intelligence/trading/plugin_utils.py:262`, and `src/intelligence/pipeline/executor.py:898` will all pass validation incorrectly if any site is left unpatched. [`src/intelligence/trading/signal_schema.py`], [`services/signal_writer.py:112`], [`src/intelligence/trading/plugin_utils.py:262`], [`src/intelligence/pipeline/executor.py:898`]
- **HIGH**: W3 is incomplete. Adding `if not self.running: break` inside the `async for` does not unblock a consumer already waiting in `KafkaConsumerClient.messages()`. `services/intelligence_pipeline.py:671` can still hang on SIGTERM until the broker yields another message or systemd kills it. `_teardown()` only stops Kafka after `_run()` returns, so the stop path is still circular.
- **HIGH**: Migration 130 Statement 3 is not durable. `services/feature_writer.py:217` and `production/scripts/run_historical_pipeline.py:748-750` still serialize `event.i6.model_dump(exclude_none=True)` into `cross_timeframe_context`. Statement 3 removes the keys from existing rows but live write paths reintroduce them immediately. The writers must also be changed.
- **HIGH**: W2 is narrower than its description. Checking only the four promoted CTF columns does not validate "all columns referenced in `_INSERT_FEATURE_SQL`", and the query should also filter by `table_schema` to avoid false positives from another schema with the same table name.
- **MEDIUM**: W4 will affect tier wiring and test assumptions. `TIER_I7` feeds registration, replay defaults, validator checks, and count assertions — removing `fvg_fill_plugin.name` needs a broader test/update sweep than currently listed.
- **MEDIUM**: W6 as written introduces a division-by-zero risk. If `atr == 0`, `original_inside_distance / atr` raises `ZeroDivisionError` instead of emitting the intended `ValueError`. [`src/intelligence/trading/plugin_utils.py:151`], [`src/intelligence/trading/plugin_utils.py:188`]
- **LOW**: W1's verification only proves missing joins are gone. It does not prove the recovered rows have expected CTF values or that replay did not create duplicate signal/trade rows.

**Suggestions**
- Keep `validate_signal` backward-compatible, or add `validate_signal_with_reason()` / `ValidationResult` type and migrate callers incrementally.
- For shutdown, stop or cancel the Kafka consumer before waiting for the main loop to exit, or make `messages()` stop-aware; add an idle-shutdown test that proves SIGTERM completes without SIGKILL.
- Before Statement 3, strip CTF keys from live write paths in `services/feature_writer.py`, `production/scripts/run_historical_pipeline.py`, and `production/scripts/feature_replay.py`.
- In W2, query `information_schema.columns` with `table_schema = current_schema` and make the required column set explicit about scope.
- Update W4 rollout notes to include dependent registry/count tests, replay defaults, and any audit code that assumes old `TIER_I7` size.
- Fix W6 with `inside_atr = original_inside_distance / max(atr, EPSILON)` to avoid division-by-zero.
- Add one post-replay spot-check query confirming top-level CTF columns are populated on sampled rows before stripping JSONB keys.

**Risk Assessment: HIGH**
Two changes can silently degrade correctness if implemented as written: the `validate_signal` return-type change (silently passes all checks at unpatched call sites) and the SIGTERM fix (Kafka consumer remains blocked). The "single source of truth" cleanup is also not durable unless live writers are changed simultaneously.

---

## Ollama Review (nemotron-3-nano:4b)

**Summary**
The Phase 135 post-reboot plan addresses five distinct failure modes in a staged order of code changes, a replay-only historical recomputation, and a final SQL migration. The actions are intended to restore a clean, deterministic pipeline, improve observability, and prevent future silent wrong answers.

**Strengths**
- Targeted, low-risk changes — most interventions are code tweaks or data-only queries that do not disrupt production.
- Clear verification per work unit — SQL count checks, schema checks, pytest updates.
- Replay strategy is honest — only recomputes I1-I7 features on already-available bar data; no live inference attempted.
- Observability improvements — `validate_signal` now emits a failure reason; the FVGFill unit label fix closes a telemetry leak.
- Execution order respects dependencies — W6 → W5 → W4 → W3 → W2 → W1 → Migration 130 prevents schema corruption during replay.
- Systemd timeout is explicit — 90s documents intent, removes ambiguity.

**Concerns**
- **HIGH**: `_process_loop` stop condition only checks `self.running` after `record_message_consumed()`. If SIGTERM is raised before the loop yields, the kernel may hit timeout and kill the process. The async `for` does not await `self.running`; control returns to the event loop only between iterations.
- **HIGH**: W2's `_REQUIRED_COLUMNS` guard runs at startup, but there is no guard ensuring migration 130 actually completed before `_setup()` runs. A stale migration could raise `RuntimeError` only after startup, making debugging harder.
- **MEDIUM**: Replay window boundary mismatch — `run_historical_pipeline.py` covers gap 11:15 → 19:00 but the verification query uses `signal_events.ts BETWEEN '11:15' AND '19:10'`. Bars at 19:00-19:05 where `feature_ts` is NULL could still be counted as orphaned.
- **MEDIUM**: `fvg_fill_plugin.name` removal deletes only the I7 plugin; documentation says no downstream signal loses FVG data, but risk exists if a later plugin re-enables FVGFill with different semantics.
- **MEDIUM**: Validate_signal signature change — the list of 5 call sites is exhaustive only if the codebase is clean; future refactors elsewhere could break script workers or static analysis.
- **MEDIUM**: Migration 130 Statement 3 runs without an explicit transaction. If any row fails updating, the statement may error and be ignored, leaving inconsistent `cross_timeframe_context`.
- **LOW**: `original_inside_distance` still exposed raw in module-level variable; only the error-message text is wrong, not the data object.
- **LOW**: Verification checklist does not explicitly test `validate_signal({})` (empty dict) or `ok` case returning empty string.

**Suggestions**
- Tighten replay window to exactly `2026-06-18 11:15:00+00 → 2026-06-18 19:10:00+00` and align the SQL verification window to match exactly.
- In `_process_loop`, check `self.running` before processing the next message; add an integration test that triggers SIGTERM mid-run and asserts no pending messages.
- Add assertion after W4 plugin removal confirming no later plugin re-creates `fvg_fill_plugin` with different semantics.
- Wrap Migration 130 Statement 3 in a transaction:
  ```sql
  BEGIN;
  UPDATE intelligence_features
  SET cross_timeframe_context = cross_timeframe_context
      - ARRAY['ctf_score', 'ctf_trend_alignment', 'ctf_structure_alignment', 'ctf_regime_agreement']
  WHERE cross_timeframe_context ? 'ctf_score';
  COMMIT;
  ```
- Add integration test calling `validate_signal({})` and `validate_signal` with correct fields; verify `ok` case returns empty string.

**Risk Assessment: HIGH**
The P1 change in the main processing loop could leave the async pipeline in an unhandled state. The P4 runtime-schema guard is entirely missing — a stale migration could silently produce invalid JSONB. These two together raise the chance of a cascading failure (pipeline stops, DB left in inconsistent state). Implementing the loop safety fix, schema guard strengthening, and replay window alignment would bring risk to MEDIUM.

---

## Consensus Summary

Both Codex and Ollama independently rated the plan **HIGH risk** before fixes. They converged on 4 structural concerns.

### Agreed Strengths
- W1 replay approach is correct — bar data is intact, replay is the only safe recovery path
- W2 fail-fast-at-startup is the right pattern for schema guard
- W4 correctly isolates the noisy plugin without touching upstream FVG features
- Execution order (W6 → W5 → W4 → W3 → W2 → W1 → Migration) is sound
- Verification query for W1 is concrete and tests the exact failure mode

### Agreed Concerns (both reviewers, highest priority)

1. **[HIGH] W3 SIGTERM fix is incomplete** — `if not self.running: break` does not unblock a Kafka consumer already waiting for a message. Pipeline can still hang until SIGKILL. Need to cancel/close the consumer before the loop can actually exit.

2. **[HIGH] W5 validate_signal tuple return silently breaks unpatched callers** — non-empty tuples are truthy, so any `if validate_signal(sig):` left unpatched will pass validation even for invalid signals. All 5 listed call sites (and any unlisted ones) must be patched atomically.

3. **[HIGH/MEDIUM] Migration 130 Statement 3 not durable** (Codex: HIGH) — live write paths (`feature_writer.py`, `run_historical_pipeline.py`) still write CTF keys into `cross_timeframe_context`. Statement 3 cleans existing rows, but new writes re-introduce the keys immediately. Writers must be patched in the same phase.

4. **[MEDIUM] Replay window boundary** (Ollama) — the command covers `--days 1` but the verification SQL uses `19:10` as the upper bound while the restart time note says `19:00`. Align them explicitly.

### Divergent Views

- **W6 division-by-zero** (Codex only, HIGH): If `atr == 0`, `original_inside_distance / atr` raises `ZeroDivisionError`. Codex flagged this; Ollama did not. Worth fixing with `max(atr, EPSILON)`.
- **Migration 130 Statement 3 transaction** (Ollama only, MEDIUM): Should be wrapped in an explicit `BEGIN/COMMIT`. Codex focused on write-path durability instead.
- **W2 table_schema filter** (Codex only, HIGH): `information_schema.columns` should filter by `table_schema = current_schema()` to avoid false positives. Straightforward one-line addition.
- **FVGFill re-enable risk** (Ollama only, LOW): Future re-enable with different semantics could re-introduce the defect. Low risk given `shadow_only=True` governance.
