---
phase: 64
reviewers: [coderabbit, gemini]
reviewed_at: 2026-04-28T00:09:06Z
plans_reviewed: [64-00-PLAN.md, 64-01-PLAN.md, 64-02-PLAN.md, 64-03A-PLAN.md, 64-03B-PLAN.md, 64-03C-PLAN.md, 64-04-PLAN.md]
---

# Cross-AI Plan Review — Phase 64

## CodeRabbit Review

*(Original review: 2026-04-27T07:30:00Z)*

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

*(Review: 2026-04-28T00:09:06Z — Gemini CLI prompt-only mode, plan content provided inline)*

### 1. Summary

The Phase 64 plans represent a significant architectural maturation for IndicAgent, transitioning from binary signal confluences to continuous gradient modeling ([-1, +1]) and introducing a dedicated **MacroComputeAgent**. The segmentation of macro factors into a standalone service aligns perfectly with the "Segment relentlessly" mandate. However, while the design of the plugins and agents is sound, the validation infrastructure (Plan 00/04) contains a fundamental contradiction regarding backtest feasibility, and several high-severity logic bugs identified in prior reviews (look-ahead bias and data loss) remain insufficiently addressed in the current plan descriptions.

### 2. Strengths

- **Gradient Standardization:** Moving to continuous gradients ([-1, +1]) via `gradient_utils.py` significantly improves the signal-to-noise ratio for downstream I7/I8 consumers compared to legacy binary triggers.
- **Architectural Segmentation:** Creating a standalone `MacroComputeAgent` (Decision D-07) prevents `CrossAssetComputeAgent` from becoming a "God Class" and allows for independent scaling and failure isolation.
- **Rigorous Validation Gates:** The requirement for both IC > 0.05 and Bonferroni-corrected p < 0.05 (Decision D-25) is an institutional-grade standard that prevents "p-hacking" of indicators.
- **Graceful Degradation:** Plans 01 and 03A explicitly account for missing Kafka frames or rate future data, ensuring the pipeline doesn't stall if specific instruments are illiquid.

### 3. Concerns

**HIGH Severity:**

- **Backtest Contradiction (Plan 00 vs. Plan 04):** Plan 00 intends to validate I6 plugins on 6+ months of data. However, Plan 04 states that historical backtesting of `ctf_*` fields is "ARCHITECTURALLY INFEASIBLE" because the fields are NULL in the DB. This suggests a misunderstanding of "Replay Backtesting." A proper replay should *re-calculate* the values from historical I1-I5 inputs, not just query existing rows. If the infrastructure cannot perform a true replay, the "Validation Gate" is a hollow promise.
- **Look-ahead Bias in `backtest_i6_plugin.py`:** Prior reviews flagged that the window slicing includes future data. The current plan does not explicitly detail the implementation of a "Point-in-Time" (PIT) join or a strict `ts <= current_bar_ts` filter, which is critical for I6 validation.
- **Macro Data Loss (The `ON CONFLICT` Bug):** In Plan 03A, the `macro_features` hypertable persistence likely uses a `(timestamp, symbol)` unique constraint. If multiple macro factors (Yield Curve, FTQ, USD Strength) are published at the same timestamp, `ON CONFLICT DO NOTHING` will drop all but the first factor. This effectively blinds the system to multi-factor macro confluence.

**MEDIUM Severity:**

- **FTQ Symbol Attribution:** As noted by CodeRabbit, publishing macro factors like FTQ (Flight-to-Quality) under a "random bar symbol" makes retrieval by downstream I7 agents non-deterministic. The plan lacks a definition for a canonical `GLOBAL` or `MACRO` symbol in the `macro_features` table.
- **Phase 65 Dependency (Plan 01):** Plan 01 relies on `gradient_utils.py` which is delivered by Phase 65. If Phase 65 is delayed, Plan 01-02 (the core of this phase) will block. There is no mention of a local shim or fallback.

**LOW Severity:**

- **Field Name Inconsistency:** Discrepancy between `ctf_squeeze_divergence` and `ctf_squeeze_expansion` persists in documentation vs. schema. This will cause runtime `KeyError` exceptions in the `_shadow` dict capture.

### 4. Suggestions

- **Fix Persistence Logic:** Replace `ON CONFLICT DO NOTHING` with `ON CONFLICT (ts, symbol) DO UPDATE SET ...` in the `MacroComputeAgent` to ensure that if multiple macro factors arrive for the same timestamp, they are merged into the same row.
- **Define "Replay" Methodology:** Explicitly update Plan 00 to state that `backtest_i6_plugin.py` will instantiate the plugin class and call `compute_full()` using historical I1-I5 features as inputs, rather than attempting to read `ctf_*` columns from the DB.
- **Canonical Macro Symbol:** Implement a reserved symbol (e.g., `_MACRO_`) for all non-asset-specific factors (FTQ, Yield Curve). Update `IntelligencePipelineComputeAgent` to look for this specific symbol when hydrating `frames['cross_asset']`.
- **PIT (Point-in-Time) Validation:** Add a unit test to the backtest infrastructure that specifically checks for look-ahead by "zeroing out" all data with `ts > T` and verifying that the output at `T` remains unchanged.

### 5. Risk Assessment

**Risk Level: MEDIUM-HIGH**

**Justification:**
While the architectural direction is excellent, the **Validation Risk** is high. If Plan 04's claim that historical backtesting is infeasible stands, the project is effectively deploying 5+ new confluence plugins into production with *zero* historical performance verification (Decision D-13 "shadow mode" notwithstanding). Furthermore, the unresolved "Look-ahead" and "Data Loss" bugs from the CodeRabbit findings suggest that the execution of these plans might introduce subtle, hard-to-debug alpha decay rather than clear system failures. Success is gated on fixing the "Replay" logic and ensuring the `macro_features` persistence is additive rather than exclusive.

---

## Consensus Summary

**Reviewers completing successfully:** 2 of 2
- ✅ CodeRabbit (2026-04-27)
- ✅ Gemini (2026-04-28)

### Agreed Strengths

Both reviewers identified the same strengths:
- **Gradient-first discipline:** Continuous gradients ([-1,+1]) via `gradient_utils.py` is the right approach for I6 outputs
- **Rigorous validation gates:** IC > 0.05 + Bonferroni-corrected p < 0.05 is institutional-grade rigor
- **Architectural segmentation:** Standalone `MacroComputeAgent` provides correct separation of concerns
- **Graceful degradation:** Plans account for missing instruments / unavailable data
- **Schema extension strategy:** Incremental I6Confluence extension is correct

### Agreed Concerns

Both reviewers flagged the same HIGH-severity issues:

1. **Look-ahead bias in backtest infrastructure** — Window slice includes future data, invalidating IC/p-value results. CodeRabbit identified the exact line; Gemini identified the deeper pattern (need PIT join or strict `ts <= current_bar_ts` filter).

2. **Macro signal data loss (`ON CONFLICT DO NOTHING`)** — Multiple macro factors (yield_curve, FTQ, USD strength) publishing at the same timestamp will silently drop all but the first. Both reviewers recommend `DO UPDATE SET` with column-specific merging.

3. **Validation gate reliability** — Gemini raised the deeper architectural concern: Plan 04's finding that historical backtest is infeasible for `ctf_*` fields (fields are NULL pre-2026-04-27) means the validation gate intended to gatekeep Plan 02 is itself unverifiable. The forward-only path via FeatureValidationService is correct but means deploying 5+ plugins with zero historical validation.

Both reviewers flagged the same MEDIUM concerns:
- **FTQ canonical symbol** — Needs a reserved symbol (e.g., `_MACRO_` or `FTQ`) not a random bar's symbol
- **Phase 65 dependency** — Plan 01 must declare `depends_on: ["65"]`

### Divergent Views

- **CodeRabbit** focused on specific code-level bugs (exact line numbers, specific SQL statements, async/await misuse). More tactical.
- **Gemini** focused on the deeper architectural contradiction: Plan 00 promises historical validation, Plan 04 admits it's infeasible for `ctf_*` fields — but argues the infrastructure should perform a true *replay* (calling `compute_full()` on historical I1-I5 inputs) rather than querying pre-existing `ctf_*` column values. This is a valid architectural insight that the plan documents do not fully address.

### Next Steps

1. **Address macro signal data loss** — Fix `ON CONFLICT DO NOTHING` → `DO UPDATE SET` before MacroComputeAgent prod deploy (gating item).
2. **Verify backtest look-ahead fix** — Confirm `backtest_i6_plugin.py` uses strict `ts <= current_bar_ts` (PIT join) after CodeRabbit's fix suggestions are applied.
3. **Clarify replay architecture** — Update Plan 00 to explicitly state whether backtest re-calculates from I1-I5 inputs (true replay) or reads existing `ctf_*` columns (not possible for pre-2026-04-27 data).
4. **Deploy MacroComputeAgent to prod** — Outstanding item per ROADMAP; needed to begin accumulating `macro_features` data for the ~May 10 validation gate.
5. **Canonical macro symbol** — Define `_MACRO_` or similar in `constants.py` before Plan 03C execution.

---

*Review updated: 2026-04-28T00:09:06Z*
*Phase: 64 - I6 Confluence Expansion*
*Plans reviewed: 7 documents (00-04 plus gap closure plans)*
*Tool versions: CodeRabbit (2026-04-27), Gemini CLI (2026-04-28, prompt-only mode with inline plan content)*
