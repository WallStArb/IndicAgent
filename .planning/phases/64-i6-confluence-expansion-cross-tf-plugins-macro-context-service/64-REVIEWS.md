---
phase: 64
reviewers: [coderabbit]
reviewed_at: 2026-04-27T07:30:00Z
plans_reviewed: [64-00-PLAN.md, 64-01-PLAN.md, 64-02-PLAN.md, 64-03A-PLAN.md, 64-03B-PLAN.md, 64-03C-PLAN.md, 64-04-PLAN.md]
---

# Cross-AI Plan Review — Phase 64

## CodeRabbit Review

**Summary:**
CodeRabbit conducted an extensive review of the Phase 64 implementation, analyzing code changes, plan documents, systemd unit files, and test infrastructure. The review identified 20 issues across multiple severity levels, ranging from critical look-ahead bugs in backtesting logic to documentation inconsistencies and hardcoded deployment paths. Key strengths include comprehensive plan coverage and test infrastructure, while concerns focus on data integrity issues (macro signal conflicts), async/await misuse, and validation gate reliability.

### Strengths

- **Comprehensive test coverage:** Unit tests provided for flight-to-quality macro factor, including edge cases for missing symbols
- **Rigorous validation approach:** Plans 00 and 04 establish backtest infrastructure and IC/p-value validation gates before production deployment
- **Gradient-first discipline:** All I6 plugins specified as continuous gradients [-1,+1] or [0,1], avoiding binary step functions
- **Architectural consistency:** Plans follow existing patterns from `CrossTimeframeConfluencePlugin` and use established gradient utilities
- **Schema extension strategy:** I6Confluence schema extended incrementally rather than split, maintaining backward compatibility
- **Validation gate sequencing:** Plan 01 must validate (IC > 0.05, p < 0.05, N>=30) before Plan 02 execution begins, enforcing effect size requirements

### Concerns

**HIGH Severity:**

- **Look-ahead bug in backtest logic (Plan 04, lines 340-353):** `window_df = df.iloc[i - window_bars : i + window_bars]` includes future data, causing lookahead bias. The slice should be `df.iloc[i - window_bars : i]` to match the `lookback=window_bars` parameter. This invalidates backtest results.
- **Index out-of-range bug (Plan 04, line 356):** `window_df.iloc[i]["ts"]` uses index from original `df`, causing IndexError. Should use position relative to `window_df` (e.g., `center = len(window_df)//2; ts = window_df.iloc[center]["ts"]`).
- **Macro signal data loss (macro_compute_agent.py, lines 276-308):** `ON CONFLICT (ts, symbol, timeframe) DO NOTHING` silently drops rows when different macro signal types (yield_curve vs ftq) conflict. Different macro factors overwrite each other instead of coexisting. Solution: add `signal_type` column to distinguish conflicts or use upsert to update only relevant columns.
- **DB connection leak (Plan 04, lines 314-325):** asyncpg connection created without `try/finally` or async context manager, leaking connections on exceptions.

**MEDIUM Severity:**

- **Async/await misuse (Plan 04, line 190):** `await backtest_i6_plugin(...)` used on synchronous function returning DataFrame. Remove `await` or convert function to async.
- **Hardcoded deployment paths (indicagent-macro-compute.service, lines 9-14):** Systemd unit uses `/home/bg/dev/indicagent` paths while running as `User=indicant`. Production will fail. Use `${APP_HOME}` env var or deployable paths.
- **FTQ symbol attribution bug (macro_compute_agent.py, lines 179-198):** FTQ signal published/persisted under incoming bar's symbol (e.g., random ES tick) instead of canonical "FTQ" or "SPY_TLT" symbol, making downstream queries impossible.
- **Field name mismatch (Plan 04, line 177):** Mapping uses `"ctf_squeeze_divergence"` but plugin emits `"ctf_squeeze_expansion"`. Plugin class name is `CrossTFSqueezeExpansionPlugin`, not "Divergence".
- **Missing dependency (Plan 01, line 6):** `depends_on: []` but plugin uses `gradient_utils.py` delivered by Phase 65. Should include Phase 65 to ensure ordering.
- **Non-deterministic field name derivation (64-03-GAPCLOSURE-PLAN.md, line 194):** `plugin_class().outputs.copy().pop()` instantiates plugin to get field name, calling `__init__` and depending on set iteration order. Use class-level metadata instead.

**LOW Severity:**

- **Docstring inconsistencies:** Multiple docstrings incorrect (Plan 01 line 446: "7 I6 CTF" should be "8"; Plan 02 lines 194-197: output range stated as [-1,+1] but implementation uses [0,1]).
- **Unused variable (flight_to_quality.py, line 62):** `min_required` assigned but never used.
- **Test insufficient lookback (test_flight_to_quality.py, lines 146-160):** `lookback=2` causes failure due to insufficient SPY history, not missing TLT. Use `lookback=1` to properly test missing symbol path.
- **Hardcoded repo URL (indicagent-macro-compute.service, line 3):** Placeholder URL `"https://github.com/your-repo/indicagent"` should be actual repository.
- **Weak separator formatting (64-03-GAPCLOSURE-PLAN.md, lines 518-520):** `echo "="` prints single "=" instead of full separator bar.
- **Duplicated field mapping (64-03-GAPCLOSURE-PLAN.md, lines 444-450):** Hardcoded `field_map` duplicates logic from `backtest_cross_tf_plugins.py`. Should import shared constant.
- **Expensive re-backtest (64-03-GAPCLOSURE-PLAN.md, lines 639-641):** `backtest_main()` re-runs full 6-month backtest instead of loading cached CSV results.

### Suggestions

1. **Fix look-ahead bugs immediately:** These invalidate the validation gate. Change `df.iloc[i - window_bars : i + window_bars]` to `df.iloc[i - window_bars : i]` and fix index references.
2. **Add signal_type to macro_features schema:** Distinguish yield_curve vs ftq signals in conflict handling. Use `ON CONFLICT ... DO UPDATE SET yield_curve_slope = EXCLUDED.yield_curve_slope` to update only relevant columns.
3. **Canonicalize FTQ symbol:** Publish/persist FTQ under "FTQ" symbol, not incoming bar symbol. Guard computation to only run on SPY/TLT updates.
4. **Use systemd EnvironmentFile:** Replace hardcoded `/home/bg` paths with `${APP_HOME}` and `${VENV_BIN}` loaded from environment file.
5. **Fix async/await:** Remove `await` from synchronous `backtest_i6_plugin()` calls or convert function to async.
6. **Add Phase 65 dependency:** Update Plan 01 `depends_on: ["65"]` to ensure gradient_utils.py exists before plugin build.
7. **Class-level metadata for field names:** Don't instantiate plugins to derive output names. Use `plugin_class.outputs` frozenset directly.
8. **Cache backtest results:** Load CSV files from Plan 00 output instead of re-running full backtest in Plan 04.
9. **Correct docstrings:** Update all field counts and output ranges to match implementation.
10. **Fix systemd metadata:** Update repo URL, use environment variables for paths, ensure `User=indicant` can access all paths.

### Risk Assessment

**Overall Risk Level: HIGH**

**Justification:**
- **CRITICAL:** Look-ahead bugs in backtesting infrastructure (Plans 00/04) mean the validation gate cannot be trusted. IC/p-values computed on biased data.
- **CRITICAL:** Macro signal data loss from `ON CONFLICT DO NOTHING` means yield curve and FTQ signals will overwrite each other, losing data.
- **HIGH:** Async/await misuse and DB connection leaks will cause runtime failures in production.
- **MEDIUM:** Hardcoded paths guarantee deployment failure in production environments.
- **MEDIUM:** Missing Phase 65 dependency will cause import errors during Plan 01 execution.

The combination of data integrity issues (look-ahead bias, signal conflicts), runtime failures (async misuse, leaks), and deployment blockers (hardcoded paths) makes this phase high-risk. The validation gate intended to ensure quality is itself compromised by look-ahead bugs, creating a false sense of security.

**Recommendation:** Address all HIGH and MEDIUM severity issues before execution. Do not proceed to Plan 02 until Plan 01 validation is confirmed on unbiased backtest results.

---

## Gemini Review

**Status:** FAILED - Tool access error

Gemini CLI attempted to invoke file system tools (`list_directory`, `glob`, `grep_search`) to locate detailed plan documents but these tools are not available in prompt-only mode. The review failed to complete.

**Error Output:**
```
I will search for the detailed plan documents in the `.planning/phases` and `docs/plans` directories...
call:default_api:list_directory{dir_path:.planning/phases}
I will use the `glob` tool to find any files related to "Phase 64"...
call:default_api:glob{pattern:**/*64*}
I will attempt to list the files using a shell command...
I will use `grep_search` to search for "Phase 64"...
```

**Resolution:** Gemini CLI requires full file system access for multi-file reviews. Consider providing all plan content directly in the prompt or using a different invocation method.

---

## Ollama Review

**Status:** FAILED - Service unavailable

Ollama local model server at `http://localhost:11434` did not respond within timeout. The service may not be running or no models are loaded.

**Error Output:**
```
Ollama review failed
```

**Resolution:** Start Ollama service with `ollama serve` and ensure a model is pulled (e.g., `ollama pull llama3`), or skip this reviewer.

---

## Consensus Summary

**Reviewers completing successfully:** 1 of 3 (coderabbit only)
- ✅ CodeRabbit
- ❌ Gemini (tool access error)
- ❌ Ollama (service unavailable)

### Agreed Strengths

(Only one reviewer completed — no consensus possible)

### Agreed Concerns

(Only one reviewer completed — no consensus possible)

### Divergent Views

(Only one reviewer completed — no divergence possible)

### Next Steps

1. **Address HIGH-severity issues** before any plan execution, especially look-ahead bugs in backtesting.
2. **Re-run review** after fixes to validate corrections.
3. **Consider alternative reviewers** if Gemini/Ollama cannot be configured for tool access.
4. **Validation gate verification:** After fixing look-ahead bugs, manually verify backtest produces sensible IC/p-values before trusting automation.

---

*Review generated: 2026-04-27T07:30:00Z*
*Phase: 64 - I6 Confluence Expansion*
*Plans reviewed: 7 documents (00-04 plus gap closure)*
*Tool versions: CodeRabbit (current), Gemini CLI (prompt-only mode failed), Ollama (service down)*
