---
phase: 131
reviewers: [claude-self-review]
reviewed_at: "2026-06-17T13:00:00-04:00"
plans_reviewed:
  - 131-01-PLAN.md
  - 131-02-PLAN.md
  - 131-03-PLAN.md
  - 131-04-PLAN.md
  - 131-05-PLAN.md
  - 131-06-PLAN.md
  - 131-07-PLAN.md
reviewer_notes: "External CLIs unavailable for headless capture: Ollama API not responding to /v1/chat/completions; Antigravity has known non-TTY stdout drop (see memory feedback_review_tooling.md); Codex blocked until 2026-07-02. This review is a second-pass architectural analysis from the plan content in context."
---

# Cross-AI Plan Review — Phase 131: Signal Generation Integrity

## Claude Self-Review (second-pass architectural analysis)

### 1. Summary

The 7 plans form a well-sequenced fix set for a high-severity, multi-root-cause corpus corruption. The diagnostic-first ordering (D-06), wave dependency graph, and verification gate in Wave 4 reflect sound engineering judgment. Three concerns warrant attention before execution: (1) Plans 131-03 and 131-04 both write to `replay_symbol()` in the same file in the same wave — the gsd-executor may create merge conflicts during parallel execution; (2) the intelligence_cache seed in Plan 131-04 T-02 uses tuple-positional column mapping that could silently mismap if query column order shifts; (3) the AnchoredVWAPReversion restructuring in 131-05 is the most complex change in the phase and the acceptance criteria do not verify that the reclaim *direction* gate still evaluates correctly on the `_is_near_zero_exit` path.

### 2. Strengths

- **D-06 gate is correct and load-bearing.** Making Plan 131-01 diagnostic-only (no fix code) before 131-03 writes the A4 fix is the right call. The research findings explicitly marked A4 as unconfirmed; the plan respects this. If A4 is refuted, 131-03 has a documented abort path.

- **A7 path split is correctly identified.** Plan 131-04 explicitly notes that `replay_symbol()` does NOT use `FeaturePipelineExecutor` and seeds `intelligence_cache` directly (psycopg2, synchronous) rather than `self._last_events` (asyncpg, async). This is the correct split — conflating the two would produce a fix that passes unit tests but fails in replay.

- **Cold-start scoping.** The 316-bar cold-start exception (79 symbols × 4 TFs, bar 1 each in Phase 133 TRUNCATE rebuild) is correctly excluded from the ≥85% gate. This prevents the gate from being gamed by running a small-window replay where most bars are cold-start.

- **B6 separation of concerns.** Distinguishing "audit query crashed" from "data invariant violated" in Plan 131-06 is the correct fix. The Phase 127 rebuild was declared failed when data was likely intact. Per-symbol batching is the right approach to avoid full-table-scan timeouts.

- **CrossAssetDivergence `_CORPUS_EXCLUDABLE = True` marker.** This gives the verification script a machine-readable way to distinguish architectural live-only plugins from bugs without hardcoding plugin names. Well-designed.

- **B7 is additive-only.** Plan 131-02 adds a `COUNT(DISTINCT signal_id)` query alongside the existing JOIN-inflated total rather than replacing it. This means the existing alert thresholds and log parsers are unaffected.

### 3. Concerns

**HIGH — Plans 131-03 and 131-04 both write to `replay_symbol()` in `run_historical_pipeline.py` in Wave 2 (parallel execution).**

Plan 131-03 T-01 adds the `_symbol_asset_class` lookup block near line 1640 (initialization section). Plan 131-04 T-02 adds the `intelligence_cache` seed block and `--no-seed` argparse flag to the same function and file.

If gsd-execute-phase spawns both plans as parallel agents, both will read the file, make changes, and write back. The second write will overwrite the first agent's changes. The gsd-executor normally prevents this via `wave` + `depends_on` — but Wave 2 has both plans at `wave: 2` with no inter-dependency. The plan checker noted this but called it "non-blocking" because they touch "different sections."

**Risk:** In practice, concurrent file writes produce non-deterministic results. The executor must run 131-03 and 131-04 sequentially within Wave 2, not in parallel for files they share.

**Mitigation:** Add `131-03` to `131-04.depends_on` — or explicitly note in 131-04's action that it must be applied to the already-modified file from 131-03.

---

**HIGH — intelligence_cache seed uses tuple-positional column mapping.**

In Plan 131-04 T-02, the seed code does:
```python
_col_names = ["trend_direction", "trend_strength", "trend_bars_elapsed", "trend_confirmed"]
_seed_dict = dict(zip(_col_names, _seed_row))
```

This works only if the SELECT clause columns appear in exactly that order. If the query is ever modified (additional column added, order changed), values silently map to wrong keys. `extract_trend_sign()` reading `trend_direction=None` would return 0, silently reverting to the pre-fix behavior.

**Mitigation:** Use `cursor.description` to build the column name mapping at runtime:
```python
col_names = [desc[0] for desc in cur.description]
_seed_dict = dict(zip(col_names, _seed_row))
```
Or use `psycopg2.extras.RealDictCursor` to get named-column results automatically.

---

**MEDIUM — AnchoredVWAPReversion: direction gate on `_is_near_zero_exit` path not verified.**

The `_is_near_zero_exit` restructuring correctly detects the reclaim bar, but the reclaim condition at lines 175-191 depends on the departure direction (sigma was positive → close must cross back below VWAP; sigma was negative → close must cross above VWAP). On the near-zero-exit bar, `departure_sigma` holds the historical departure value (still valid), so the direction logic should work. However:

1. The acceptance criteria check for `_is_near_zero_exit` appearing 4 times and state-clearing after `make_signal_from_frame()` — but do NOT verify that the plugin fires correctly for the specific case where `abs(sigma) < sigma_min` AND `close crosses VWAP` AND `departure_sigma is not None`.

2. The plan says "velocity, reclaim, HMM, Hurst gates all remain as gates in the existing order" — but the velocity gate checks `abs(sigma) >= min_sigma_for_velocity` which may also fail on the near-zero-exit bar (sigma is near zero by definition). Clarify whether the velocity gate should be bypassed on the reclaim bar or applied with the reclaim bar's sigma value.

**Mitigation:** Add a targeted unit test: mock a departure state, then call compute_full() with a bar that has `abs(sigma) < sigma_min` and `close` crossing back across `vwap_anchor`. Assert the plugin fires and that the next call (simulating the following bar) does NOT fire.

---

**MEDIUM — Plan 131-03 frontmatter `files_modified` includes `src/intelligence/trading/anchored_vwap_reversion.py`.**

T-03 modifies the CrossAssetDivergence plugin file (found via `register_plugins.py`), not `anchored_vwap_reversion.py`. That file is modified by Plan 131-05. This is a frontmatter annotation error — execution is not affected but it will cause incorrect SUMMARY.md artifact tracking.

**Mitigation:** Fix the `files_modified` in 131-03-PLAN.md to reflect the actual CrossAssetDivergence plugin file path.

---

**MEDIUM — `_seed_last_events_from_db()` on `FeaturePipelineExecutor` won't be called by the Phase 131 verification replay.**

The replay verification in 131-07 uses `run_historical_pipeline.py` which calls `replay_symbol()` directly (not `FeaturePipelineExecutor`). The `_seed_last_events_from_db()` method added to `FeaturePipelineExecutor` in 131-04 T-01 is for the live production path. It's correct to add it, but the Phase 131 verification replay tests only the `intelligence_cache` seed in `replay_symbol()` (131-04 T-02). If the FeaturePipelineExecutor seed has a bug, it won't be caught until live operation post-Phase 133.

**Mitigation:** Add a unit test that calls `_seed_last_events_from_db()` with a mock db and verifies `self._last_events` is populated with the correct structure.

---

**LOW — Plan 131-07 T-02 control group may be overwritten by T-03 before it can be queried.**

T-02 runs the seeded replay for ESM6 for `--since 2026-06-10`. T-03 runs a 2-week replay `--since 2026-06-03` that covers the same date range. If T-02's control group query (step 4 in T-02 action) runs after T-03, it will compare against T-03's seeded output, not the unseeded output. The plan says to run the control query "before step 2's --overwrite-features" but T-03 also uses `--overwrite-features`. Task ordering within 131-07 must be strictly sequential: T-01 → T-02 (including control query) → T-03.

**Mitigation:** This is already implicit in the task ID ordering, but the action text should be explicit: "Do NOT run T-03 until T-02's control group query is recorded."

---

**LOW — A4 fix uses `COALESCE(cm.asset_class, i.asset_class)` but doesn't handle the case where both are NULL.**

If a symbol appears in neither `contract_metadata` nor `instruments`, `_symbol_asset_class` will be `None` and the injection is skipped (guarded by `if _symbol_asset_class is not None:`). This is correct behavior for unknown symbols. The plan doesn't address what happens in this case — presumably the run_i7_and_persist() call proceeds without asset_class and may still produce the same plugin errors as before. Document this case in the function comment.

### 4. Suggestions

1. **Add `131-03` to `131-04`'s `depends_on`** to prevent parallel writes to the same file. Alternatively, consolidate the replay_symbol() changes from both plans into a single plan.

2. **Use `cur.description` for column name mapping** in the intelligence_cache seed (Plan 131-04 T-02) to make column mapping robust to query changes.

3. **Add a unit test for AnchoredVWAPReversion reclaim detection** (Plan 131-05). Mock a departure state, present a near-zero-exit bar that also crosses VWAP, and assert fire + no-duplicate behavior.

4. **Fix frontmatter `files_modified` in 131-03** — replace `src/intelligence/trading/anchored_vwap_reversion.py` with the actual CrossAssetDivergence plugin file path (found via `grep -r "CrossAssetDivergence" src/intelligence/register_plugins.py`).

5. **Clarify velocity gate behavior on near-zero-exit bar** (Plan 131-05) — explicitly state whether the velocity gate uses the current bar's sigma (near-zero) or departure_sigma (stored). If it uses current sigma, it may block reclaim detection for low-sigma reclaim bars.

6. **Add `--no-seed` to _WorkerArgs NamedTuple note** — Plan 131-04 T-02 mentions updating `_WorkerArgs` but the acceptance criteria don't verify this. Add: `grep -n "seed_from_db" production/scripts/run_historical_pipeline.py | grep "WorkerArgs\|NamedTuple"` to acceptance criteria.

### 5. Risk Assessment

**Overall Risk: MEDIUM**

The plan set is well-sequenced and addresses real, confirmed bugs. The highest risks are:
- Parallel write conflict between 131-03 and 131-04 (mitigatable by adding a dependency)
- Tuple-positional column mapping in the A7 seed (mitigatable by using `cur.description`)
- AnchoredVWAPReversion restructuring complexity (mitigatable by adding a unit test)

The verification gate in Plan 131-07 is rigorous: the ≥85% ctf_score distribution check with a `--no-seed` control group provides strong evidence of fix correctness. The risk is that bugs in the fix produce ctf_score values in the 0.01–0.05 range (technically non-zero but incorrect), which would pass the > 0.05 threshold test. A more robust check would compare the distribution shape against expected ranges (e.g., median ctf_score for trending bars > 0.3).

The plan correctly defers Phase 133 full rebuild until this verification passes. That gate discipline is the most important risk mitigation in the entire phase.

---

## Consensus Summary

Only one reviewer invoked (external CLIs unavailable for this session).

### Agreed Strengths
- Diagnostic-first sequencing (D-06) prevents writing a fix against an unconfirmed root cause
- A7 path split (FeaturePipelineExecutor vs intelligence_cache) is correctly identified
- Cold-start scoping protects the ≥85% verification gate
- B6 separates audit infrastructure failure from data integrity failure

### Top Concerns (for `/gsd-plan-phase 131 --reviews` to address)
1. **Plans 131-03 and 131-04 share `run_historical_pipeline.py` in Wave 2 without a dependency** — add `131-03` to `131-04.depends_on`
2. **Tuple-positional column mapping in intelligence_cache seed** — use `cur.description` for safety
3. **AnchoredVWAPReversion velocity gate behavior on reclaim bar** — clarify and add unit test

### Divergent Views
N/A — single reviewer.
