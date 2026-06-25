---
phase: 140-ic-engine-correctness
plan: P0
type: execute
wave: 1
depends_on: []
files_modified:
  - services/ic_engine.py
  - services/forward_return_writer.py
  - production/scripts/corpus_pipeline_run.sh
  - tests/unit/test_ic_engine_stride.py
  - tests/unit/test_forward_return_session_boundary.py
autonomous: true

must_haves:
  truths:
    - "The 1-bar (fast) IC scale subsamples at stride=1, not stride=60 — n_independent for fast is ~60x the extended scale"
    - "Degenerate-feature detection runs on full regime data (X_regime), producing one shared non_degenerate_mask of shape (n_features,) reused across all scales"
    - "Intraday (5m/15m/1h) forward returns set complete_{scale}=false when the forward bar crosses to a different America/New_York calendar date"
    - "Daily (1d) forward returns are unchanged — complete_{scale} = (open_{scale} IS NOT NULL)"
    - "ic_engine accepts --training-window-end CLI arg; the value is normalized to UTC and naive datetimes are rejected; defaults to MAX(bar_ts) with a warning log"
    - "corpus_pipeline_run.sh captures the training_window_end freeze point AFTER step 1 (feature factory) completes, so step 2 (forward_return_writer) and step 4 (ic_engine) consume the same frozen universe"
    - "all_results_global is removed from ic_engine main loop"
  artifacts:
    - path: "services/ic_engine.py"
      provides: "Per-scale subsampling, UTC-normalized --training-window-end arg, all_results_global removed"
      contains: "scale_stride"
    - path: "services/forward_return_writer.py"
      provides: "tf-aware _build_forward_return_sql with ET session-boundary complete_ flags"
      contains: "America/New_York"
    - path: "production/scripts/corpus_pipeline_run.sh"
      provides: "Captures training_window_end after step 1 and passes --training-window-end to ic_engine step"
  key_links:
    - from: "forward_return_writer._build_forward_return_sql"
      to: "complete_{scale} session-boundary gate"
      via: "fwd_ts_{scale} AT TIME ZONE 'America/New_York'"
      pattern: "fwd_ts_.*America/New_York"
    - from: "ic_engine per-scale loop"
      to: "_compute_ic_rolling_metrics"
      via: "scale_stride passed per scale"
      pattern: "scale_stride"
---

<objective>
Fix the two P0 correctness blockers in the IC engine plus the two trivial P2 cleanups that share `ic_engine.py` and need no schema change. These changes MUST be committed before the running corpus pipeline reaches step 2 (forward_return_writer) and step 4 (ic_engine).

Purpose: The current stride bug starves short-horizon IC estimates of statistical power (throws away 60x observations for the 1-bar scale), and overnight-gap contamination silently conflates intraday microstructure with overnight position risk in the forward-return labels. Both corrupt every downstream IC score.

Output: Refactored per-scale subsampling, ET session-boundary forward-return labeling, UTC-normalized `--training-window-end` CLI arg, a freeze-point fix in the corpus script, and removal of the unbounded `all_results_global` accumulator.
</objective>

<execution_context>
@~/.claude/get-shit-done/workflows/execute-plan.md
@~/.claude/get-shit-done/templates/summary.md
</execution_context>

<context>
@.planning/PROJECT.md
@.planning/STATE.md
@.planning/phases/140-ic-engine-correctness/140-RESEARCH.md
@.planning/todos/pending/001-ic-engine-correctness-p0.md
@CLAUDE.md
</context>

<tasks>

<task type="auto">
  <name>Task 1: Per-scale stride subsampling in ic_engine.py</name>
  <read_first>
    - services/ic_engine.py (lines 600-760 — the regime loop, subsampling block, per-scale loop, and _compute_ic_rolling_metrics call site)
    - .planning/phases/140-ic-engine-correctness/140-RESEARCH.md (Issue 1 + "Per-Scale Subsampling Refactor" + Pitfall 1 and Pitfall 2)
  </read_first>
  <action>
    In `_compute_symbol_tf` (services/ic_engine.py), move subsampling from the regime level into the per-scale loop.

    1. DELETE the regime-level subsampling block at lines 617-623:
       `max_lookahead = max(lookaheads.values())`, `stride = max(subsample_min_stride, max_lookahead)`,
       `sub_idx = ...`, `X_sub = ...`, `returns_sub = ...`, `complete_sub = ...`, `n_independent = len(sub_idx)`.

    2. Move degenerate detection to operate on the FULL regime data `X_regime` (not the subsample):
       `feature_stds = np.std(X_regime, axis=0)`, then `degenerate_mask = feature_stds < 1e-8`,
       `non_degenerate_mask = ~degenerate_mask`. Compute `n_degenerate` and emit the existing
       `IC_ENGINE_CELLS_SKIPPED_TOTAL` degenerate metric exactly as before. Compute
       `X_regime_nd = X_regime[:, non_degenerate_mask]` once. The `non_degenerate_mask` has shape
       `(n_features,)` and is shared across all scales (a feature either has variance over the regime
       or it does not — it is NOT recomputed per scale).

    3. Inside `for scale_idx, scale in enumerate(_SCALES):` compute per-scale subsampling at the TOP of the loop body:
       ```
       lookahead_bars = lookaheads[scale]
       scale_stride = max(subsample_min_stride, lookahead_bars)
       sub_idx = np.arange(0, n_regime_raw, scale_stride)
       X_sub_nd = X_regime_nd[sub_idx]
       returns_sub = returns_regime[sub_idx]
       complete_sub = complete_regime[sub_idx]
       n_independent = len(sub_idx)
       ```
       Keep the existing `if n_independent < min_reliable_n:` skip guard but move it inside the scale loop
       (it now gates per scale). Preserve the existing `IC_ENGINE_CELLS_SKIPPED_TOTAL` insufficient_n metric.

    4. Replace `ranks_X_full = rankdata(X_sub_nd, axis=0)` (was computed once per regime at line 653) with a
       per-scale `ranks_X_scale = rankdata(X_sub_nd, axis=0)` inside the loop. The downstream
       `scale_complete = complete_sub[:, scale_idx]` and `returns_scale = returns_sub[:, scale_idx]` lines stay,
       but now reference the per-scale `complete_sub`/`returns_sub`. Where the code currently does
       `ranks_X_scale = ranks_X_full[valid_mask]`, change it to `ranks_X_scale = ranks_X_scale[valid_mask]`
       (rank the per-scale subsample, then filter by valid_mask).

    5. Update the `_compute_ic_rolling_metrics(...)` call at lines 749-760: pass `X_sub_nd` (not the old
       `X_sub`), `returns_sub`, `scale_idx`, `complete_sub[:, scale_idx]`, `apr`, `non_degenerate_mask`,
       `n_features`, and `scale_stride` as the final argument (NOT the deleted `stride`/`max_lookahead`).
       NOTE: `_compute_ic_rolling_metrics` already expects the full-feature `X` and uses `non_degenerate_mask`
       internally — verify the signature; if it expects the non-degenerate matrix, pass `X_sub_nd`. Read the
       function body before changing the call to confirm which matrix shape it expects.

    6. The walk-forward embargo currently uses `embargo_bars = max_lookahead`. Since `max_lookahead` is deleted,
       set `embargo_bars = max(lookaheads.values())` locally (it remains the maximum forward window = 60, an
       APR-derived value, not a magic number). Keep the existing comment explaining the derivation.

    Do NOT change the BH-FDR collection logic, the result dict fields, or the INSERT — those are out of scope
    for this task (P2 plan handles clustering).
  </action>
  <verify>
    - `.venv/bin/ruff check services/ic_engine.py` — clean
    - `grep -n "scale_stride" services/ic_engine.py` returns the per-scale assignment and the metrics call
    - `grep -n "max_lookahead =" services/ic_engine.py` returns nothing (variable removed)
    - `grep -n "np.std(X_regime" services/ic_engine.py` confirms degenerate detection on full regime data
    - Run a scoped ic_engine on one symbol after the migration plan lands, OR add the unit test below
  </verify>
  <acceptance_criteria>
    - Source: regime-level subsampling block (old lines 617-623) is deleted; `scale_stride = max(subsample_min_stride, lookahead_bars)` appears inside the `for scale_idx, scale in enumerate(_SCALES):` loop.
    - Source: `feature_stds = np.std(X_regime, axis=0)` — degenerate detection uses `X_regime`, not a subsample.
    - Source: `_compute_ic_rolling_metrics` call passes `scale_stride` as its stride argument; no reference to a single regime-level `stride` remains.
    - Behavior: a unit test in tests/unit/ (add `tests/unit/test_ic_engine_stride.py`) asserts that for lookaheads {fast:1, mid:5, slow:20, extended:60} and a fixed-size regime matrix, `len(np.arange(0, n, max(min_stride, lookahead)))` for fast is strictly greater than for extended (per-scale independence count differs by scale).
    - Behavior (degenerate-mask reuse regression — finding 6): the same test constructs an `X_regime` of shape `(n_rows, n_features)` with at least one constant (degenerate) column, computes `non_degenerate_mask = ~(np.std(X_regime, axis=0) < 1e-8)`, and asserts: (a) `non_degenerate_mask.shape == (n_features,)`, i.e. it is computed on full-regime feature space, not a subsample; (b) the mask is identical when recomputed on any per-scale subsample of a non-pathological feature set — proving the mask is computed ONCE on `X_regime` and shared across scales, never recomputed per scale.
    - Test: `.venv/bin/pytest tests/unit/test_ic_engine_stride.py -q` passes.
  </acceptance_criteria>
  <done>The 1-bar IC scale subsamples at its own stride; degenerate mask is computed once on full regime data (shape (n_features,)) and shared across scales; metrics receive the per-scale stride.</done>
</task>

<task type="auto">
  <name>Task 2: ET session-boundary forward returns in forward_return_writer.py</name>
  <read_first>
    - services/forward_return_writer.py (lines 120-235 — _build_forward_return_sql and the docstring formula; line 312 call site in _label_symbol_tf)
    - .planning/phases/140-ic-engine-correctness/140-RESEARCH.md (Issue 2 + "Session Boundary SQL" + Pitfall 3 + the Issue 2 fix-pattern code block)
  </read_first>
  <action>
    In services/forward_return_writer.py, make `_build_forward_return_sql` timeframe-aware so intraday forward
    returns exclude overnight/cross-session gaps.

    1. Change the signature from `_build_forward_return_sql(lookaheads: dict[str, int])` to
       `_build_forward_return_sql(lookaheads: dict[str, int], tf: str)`.

    2. Compute `is_intraday = tf in ("5m", "15m", "1h")` at the top.

    3. For intraday TFs, add forward-timestamp LEAD columns to the `windowed` CTE — one per scale:
       `LEAD(m.timestamp, {n + 1}) OVER w AS fwd_ts_{scale}` for each `scale, n in lookaheads.items()`.
       (Mirror the existing `lead_col_list` construction. The frame `ROWS BETWEEN CURRENT ROW AND {frame_size}
       FOLLOWING` already covers these LEADs.)

    4. Branch the `complete_col_list` on `is_intraday`:
       - Intraday:
         ```
         (open_{scale} IS NOT NULL
          AND (fwd_ts_{scale} AT TIME ZONE 'America/New_York')::date
              = (bar_ts AT TIME ZONE 'America/New_York')::date
         ) AS complete_{scale}
         ```
         (Use `bar_ts` — the aliased `m.timestamp` from the CTE SELECT — for the current-bar date.)
       - Daily (1d) and any non-intraday: keep the existing
         `(open_{scale} IS NOT NULL) AS complete_{scale}`.

    5. The intraday SELECT must expose `fwd_ts_{scale}` from the CTE so the outer query can reference it in the
       complete_ expression. Add the `fwd_ts_{scale}` columns to the CTE SELECT list (intraday branch only).

    6. Update the call site at line 312 in `_label_symbol_tf`: `forward_return_sql = _build_forward_return_sql(lookaheads, tf)`.
       `_label_symbol_tf` already receives `tf` — pass it through.

    7. Use `AT TIME ZONE 'America/New_York'` (handles DST automatically). Do NOT hardcode any UTC offset.
       `market_data_ohlcv.timestamp` is UTC.

    Add a one-line note in production/scripts/corpus_pipeline_run.sh near the forward_return_writer step
    comment: forward_returns must be truncated and re-run from scratch after this fix (HWM logic would otherwise
    skip rows with stale complete_ flags — see Pitfall 3). Do not change pipeline execution flow in this task.
  </action>
  <verify>
    - `.venv/bin/ruff check services/forward_return_writer.py` — clean
    - `grep -n "America/New_York" services/forward_return_writer.py` returns the intraday complete_ gate
    - `grep -n "_build_forward_return_sql(lookaheads, tf)" services/forward_return_writer.py` confirms updated call site
    - SQL string for tf='1d' contains `(open_extended IS NOT NULL) AS complete_extended` and NO `America/New_York`
    - SQL string for tf='5m' contains `fwd_ts_fast` and `America/New_York`
  </verify>
  <acceptance_criteria>
    - Source: `_build_forward_return_sql(lookaheads: dict[str, int], tf: str)` — `tf` parameter present.
    - Source: intraday branch emits `fwd_ts_{scale}` LEAD columns and a date-equality gate using `AT TIME ZONE 'America/New_York'`; daily branch emits the unchanged `(open_{scale} IS NOT NULL)`.
    - Source: call site `_build_forward_return_sql(lookaheads, tf)` updated in `_label_symbol_tf`.
    - Behavior (SQL shape): a unit test in `tests/unit/test_forward_return_session_boundary.py` calls `_build_forward_return_sql({"fast":1,"mid":5,"slow":20,"extended":60}, "5m")` and asserts the returned SQL contains `fwd_ts_fast` and `America/New_York`; calls it with `"1d"` and asserts the SQL does NOT contain `America/New_York`.
    - Behavior (actual ET / DST boundary — finding 6): the same test adds a DST spring-forward case validating the date-boundary semantics the SQL relies on. Using `zoneinfo.ZoneInfo("America/New_York")`, assert that a current bar and its forward bar straddling the 2024-03-10 02:00 ET DST transition resolve to DIFFERENT `America/New_York` calendar dates and therefore must be flagged cross-session (complete=false). Concretely: a current bar at 2024-03-09 21:00 UTC (= 16:00 ET, 2024-03-09) and a forward bar at 2024-03-10 13:30 UTC (= 09:30 EDT, 2024-03-10) have unequal ET dates — `(.astimezone(ny).date())` differs — so the `complete_{scale}` date-equality gate must be False. This proves the AT TIME ZONE date comparison correctly handles the spring-forward transition rather than only checking SQL text.
    - Test: `.venv/bin/pytest tests/unit/test_forward_return_session_boundary.py -q` passes.
  </acceptance_criteria>
  <done>Intraday forward returns are flagged incomplete when the forward bar crosses the ET trading date (including the DST spring-forward boundary); daily returns are unchanged; corpus script notes the required truncation.</done>
</task>

<task type="auto">
  <name>Task 3: Remove all_results_global and add --training-window-end to ic_engine + forward_return_writer</name>
  <read_first>
    - services/ic_engine.py (lines 1033-1200 — main(), argparse, training_window_end derivation, the pool.map loop)
    - services/forward_return_writer.py (main(), argparse, _label_symbol_tf query — find WHERE clause on bar_ts)
    - production/scripts/corpus_pipeline_run.sh (step-1 through step-4 invocations; --from-step resume logic)
    - .planning/phases/140-ic-engine-correctness/140-RESEARCH.md (Issue 7 + Issue 8, exact code blocks)
  </read_first>
  <action>
    The freeze point must be enforced EXPLICITLY by both services — not implicitly by batch ordering.
    A silent universe mismatch (forward returns computed on more bars than IC scores) is a data-integrity
    violation that could corrupt every downstream IC score without error. Relying on sequential ordering
    is an assumption, not a guarantee.

    **A. services/ic_engine.py `main()`:**

    1. (Issue 7) Delete `all_results_global: list[dict] = []` and the corresponding
       `all_results_global.extend(result["all_results"])` line in the pool.map loop.
       `_emit_health_gauges` uses `result["all_results"]` (the per-symbol dict) directly — not
       the global list. Removal is functionally inert.

    2. (Issue 8) Add argparse argument after `--workers`:
       ```
       parser.add_argument(
           "--training-window-end",
           default=None,
           help="Explicit training window end (ISO 8601, timezone-aware/UTC). "
                "Default: MAX(bar_ts) FROM feature_vectors with a warning. "
                "Set explicitly to keep PKs stable across multi-run corpus builds.",
       )
       ```

    3. Replace the unconditional MAX query with:
       ```
       if args.training_window_end:
           training_window_end = datetime.fromisoformat(args.training_window_end)
           if training_window_end.tzinfo is None:
               raise ValueError(
                   "--training-window-end must be timezone-aware ISO 8601 (UTC). "
                   "Naive datetimes are rejected to preserve the UTC-only invariant."
               )
           training_window_end = training_window_end.astimezone(UTC)
           _logger.info("ic_engine.training_window_end_explicit", value=str(training_window_end))
       else:
           with conn.cursor() as cur:
               cur.execute("SELECT MAX(bar_ts) FROM feature_vectors")
               training_window_end = cur.fetchone()[0]
           _logger.warning(
               "ic_engine.training_window_end_from_max",
               value=str(training_window_end),
               note="Pass --training-window-end to stabilize PKs across runs",
           )
       ```

    **B. services/forward_return_writer.py `main()`:**

    4. Add the same argparse argument (identical signature) to forward_return_writer.py.

    5. Apply the same UTC parse/reject/normalize pattern. When provided, pass `training_window_end`
       as an upper bound on the bars processed: in `_label_symbol_tf` (or its query), add
       `AND bar_ts <= %(training_window_end)s` to the WHERE clause selecting bars from
       `feature_vectors`. When not provided, query MAX and warn (same pattern as ic_engine).
       This ensures forward_return_writer only computes labels for bars within the frozen universe.

    **C. production/scripts/corpus_pipeline_run.sh:**

    6. Capture `TRAINING_WINDOW_END` immediately AFTER step 1 (feature_factory) returns,
       outside any step-gating branch so `--from-step >= 2` resumes still execute it:
       ```
       TRAINING_WINDOW_END=$(PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent \
           -tAc "SELECT MAX(bar_ts) FROM feature_vectors")
       ```

    7. Pass `--training-window-end "$TRAINING_WINDOW_END"` to BOTH:
       - The step-2 forward_return_writer invocation
       - The step-4 ic_engine invocation

    Both services now enforce the freeze point explicitly. Universe consistency is no longer a
    function of batch ordering — it is an invariant enforced at each service boundary.

    Do NOT touch the per-scale loop or BH-FDR logic (owned by Task 1 / P2 plan).
  </action>
  <verify>
    - `.venv/bin/ruff check services/ic_engine.py services/forward_return_writer.py` — clean
    - `grep -n "all_results_global" services/ic_engine.py` returns nothing
    - `grep -n "training-window-end" services/ic_engine.py` returns the argparse arg
    - `grep -n "training-window-end" services/forward_return_writer.py` returns the argparse arg
    - `grep -n "tzinfo is None" services/ic_engine.py services/forward_return_writer.py` confirms both reject naive datetimes
    - `grep -n "training_window_end_from_max" services/ic_engine.py services/forward_return_writer.py` returns warning in both
    - `grep -n "TRAINING_WINDOW_END" production/scripts/corpus_pipeline_run.sh` returns the capture + two passthroughs (step 2 and step 4)
    - `python -c "import ast; ast.parse(open('services/ic_engine.py').read())"` — parses
    - `python -c "import ast; ast.parse(open('services/forward_return_writer.py').read())"` — parses
  </verify>
  <acceptance_criteria>
    - Source: no occurrence of `all_results_global` in services/ic_engine.py.
    - Source: both ic_engine.py and forward_return_writer.py define `--training-window-end` in argparse with `default=None`.
    - Source: both services reject naive datetimes (`tzinfo is None` → `ValueError`) and normalize to UTC.
    - Source: forward_return_writer applies `AND bar_ts <= training_window_end` in its bar-selection query when the arg is provided.
    - Source: corpus_pipeline_run.sh captures `TRAINING_WINDOW_END` after step 1 and passes `--training-window-end "$TRAINING_WINDOW_END"` to BOTH step-2 (forward_return_writer) and step-4 (ic_engine) invocations.
    - Source: the capture is NOT inside the step-1 branch — `--from-step 2` resumes must still freeze the value.
    - Behavior: `python services/ic_engine.py --help` and `python services/forward_return_writer.py --help` both list `--training-window-end`.
  </acceptance_criteria>
  <done>The unbounded accumulator is gone. Both services enforce the training-window-end freeze explicitly with UTC normalization and naive-datetime rejection. Universe consistency is an enforced invariant, not a batch-ordering assumption.</done>
</task>

</tasks>

<verification>
- `.venv/bin/ruff check services/ic_engine.py services/forward_return_writer.py` — clean
- `.venv/bin/pytest tests/unit/test_ic_engine_stride.py tests/unit/test_forward_return_session_boundary.py -q` — pass
- `.venv/bin/pytest tests/unit/ -q` — no new failures vs baseline (test_pipeline_backpressure is a known pre-existing failure)
- `python services/ic_engine.py --help` shows `--training-window-end`
</verification>

<success_criteria>
- Per-scale stride: fast scale n_independent ~60x extended scale (different `n_independent` per scale in feature_ic_scores after a run)
- Intraday forward returns gate `complete_{scale}` on same ET calendar date (DST-safe); daily unchanged
- `all_results_global` removed; UTC-normalized `--training-window-end` CLI arg present (naive rejected) and wired into corpus script with the freeze point captured AFTER step 1
- Changes committed BEFORE the corpus pipeline reaches step 2 (forward_return_writer)
</success_criteria>

<output>
After completion, create `.planning/phases/140-ic-engine-correctness/140-P0-SUMMARY.md`
</output>
</content>
</invoke>
