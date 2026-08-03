---
status: completed
priority: P2
filed: 2026-08-03
closed: 2026-08-03
source: live-verified via journalctl after a chain script's misleading "exit 0"
---

## What

`scripts/analysis/nonlinear_interaction_combiner_replication_15m.py` OOM-killed again, 2026-08-03
04:12:41 UTC, PID 4144329, `anon-rss:21671400kB` (~21.7GB) at kill time -- confirmed via
`journalctl` kernel log (`oom-kill:... task=python,pid=4144329`), not inferred. This is the
THIRD distinct OOM on this script, and it survived both prior fixes:

1. Todo 231: `[dict(r) for r in rows]` -> `pd.DataFrame` on the full fetch replaced with
   `fetch_frame_chunked()` (server-side cursor, batched, float32 downcast). Fixed 1h.
2. A follow-on fix (same session, documented in `_nonlinear_interaction_combiner_shared.py`'s
   `train_and_predict_oos` docstring): `del df` before training starts, so the ~230-column
   source frame doesn't coexist with X through the whole walk-forward loop.

Both are already merged and already used by this run (confirmed via `git status`/`git diff` --
`_nonlinear_interaction_combiner_shared.py` has both). 15m still hit ~21.7GB anon-rss regardless. X alone
is a known, printed quantity (`Training matrix: N rows x 248 cols, ~X GB (float32)` -- the log
line never printed this time because the process died before flushing its buffered stdout, so
we don't have 15m's own number, but `_nonlinear_interaction_combiner_shared.py`'s docstring estimates
~8.6GB for X at 15m's ~8.5M rows). ~21.7GB - ~8.6GB leaves ~13GB unaccounted for by the raw
array alone -- the leading suspect is LightGBM's own internal `Dataset`/histogram-bin
construction on the final expanding-window fold (train on ~85% of ~8.5M rows x 248 cols),
which is well documented to run several times the raw float32 array's footprint. Not yet
confirmed with a profiler -- this is a hypothesis, not a measured root cause.

A misleading side-symptom worth fixing regardless of the OOM: the orchestrating chain script
(ad hoc, run via `Bash ... run_in_background`, not committed to the repo) reported "15m done ...
exit 0" in its log even though the process was SIGKILL'd by the OOM killer. Whatever captured
`$?` was capturing the wrong command's exit status (likely a `tee` or similar in the pipeline),
not the killed Python process's own 137. Any future one-off chain script for this family of
scripts should redirect straight (`cmd > log 2>&1`, `echo "exit $?"` immediately after, no
intermediate pipe stage) so exit codes stay trustworthy.

## Next step

Not resolved. Options to investigate, in rough order of cost:
- Reduce LightGBM memory footprint directly: lower `max_bin` (default 255 -- histogram memory
  scales with it), consider `Dataset(..., free_raw_data=True)` explicitly (sklearn API default
  unconfirmed), or force `gc.collect()` between folds if Python-level references to the
  previous fold's Booster/Dataset are lingering.
- Profile the actual peak (py-spy or a manual RSS-vs-fold-number print) rather than continuing
  to guess at the ~13GB gap.
- Fall back to training only on a random row-subsample of the final fold's training set (with a
  documented, APR-backed subsample rate) if LightGBM's own footprint can't be brought down
  further -- last resort, changes the methodology slightly (should be noted in the thesis doc
  if taken).
- Floor option: run 15m on a bigger-memory box / temporarily stop other services during the run,
  if this remains a one-off measurement rather than something to make routinely reproducible.

15m remains the directly-actionable tf for nonlinear_interaction_combiner (Phase 167's live construction trades there) --
this blocks the one nonlinear_interaction_combiner replication that would actually confirm/deny relevance to production,
not just "is nonlinear_interaction_combiner real in general" (already answered yes, small, at 1h/1d).

## Resolution (2026-08-03, `superpowers:systematic-debugging` via a background Opus 5 agent)

**This todo's own LightGBM-Dataset hypothesis was wrong -- refuted, not confirmed.** Every OOM
kill happened BEFORE training started; LightGBM's own peak was ~6GB on the largest fold and was
never the actual problem. Root cause, measured (instrumented RSS sampling + `malloc_trim` to
separate live vs allocator-retained memory) rather than estimated: the wide ~8.5M-row x 264-col
pandas DataFrame's *existence* was the defect, not any single operation on it. The fetch alone
consumed 18.5GB before any post-processing (asyncpg `Record` objects cost 9.4x the bytes they
become as a DataFrame; the cursor's own prefetch buffer plus the script's accumulation list
doubled that further), and every subsequent full-frame pandas op (sort, `.iloc` reorder, column
extraction) stacked another ~9.3GB on top. No ordering of small patches fit in 29GB -- which is
exactly why the first three fixes (this todo, the `del df` follow-on, todo 231's chunked fetch)
each closed one hole and immediately hit the next.

Also refuted: the `PerformanceWarning: DataFrame is highly fragmented` line seen in earlier
attempts was a red herring -- measured identical `.iloc` cost (1x frame) on both a fragmented
and a clean-heap frame.

**Fix:** `_nonlinear_interaction_combiner_shared.py` rewritten (`fetch_training_matrix()` replaces
`fetch_frame_chunked()` + `extract_training_arrays()`, both deleted) to build the training
matrix directly from asyncpg rows in two passes -- narrow key/target columns first (computes the
causal-demeaning warmup mask and each row's destination index), then the wide feature columns
streamed and scattered straight into a preallocated `X` array. Never materializes a wide
DataFrame at all. This is the same pattern `services/ensemble_trainer.py:909-928` already uses
in production; the nonlinear_interaction_combiner scripts' own docstring had declined to adopt it on the grounds that the
scripts "lean on pandas for column introspection at ~250-column width" -- that objection did not
survive scrutiny (the feature list comes from the prepared statement's schema; the one genuinely
pandas-shaped step, causal per-symbol demeaning, needs three narrow columns, not 248).

**Verified, not just reasoned:** 1d re-run under the new code produced a per-symbol CSV
bit-identical to its pre-change output (pure architecture fix, zero numerical delta -- required
one correction along the way, matching pass 1's `return_fast` dtype to float32 to match the old
path's rounding). 15m itself completed in ~56 min, peak 14.65GB (was killed at ~21.8GB four
times), zero OOMs confirmed via `journalctl` for the run window, `pytest tests/unit/ -q` fully
green (independently re-run and confirmed, not just taken on the agent's word).

**15m result:** tree mean `point_ic`=0.2899 (80/80 pass CI, 80/80 survive BH-FDR positive) vs
`ctf_momentum`'s 0.0677. Cross-sectional-neutral: tree 0.2506 (`ci_lower`=0.2489) vs baseline
0.0610 (`ci_lower`=0.0593). Much closer to 1h's magnitude than 1d's -- nonlinear_interaction_combiner is not uniformly small
across timeframes, it's substantial at both 1h and 15m (the tf that actually matters) and small
specifically at 1d. Full detail: `docs/research/data-edge-source-thesis.md`'s nonlinear_interaction_combiner section (v1.8).
