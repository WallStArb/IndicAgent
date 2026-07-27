---
status: completed
completed: 2026-07-15
resolved_by: 53267bbd
---

## Resolution (2026-07-15)

Shipped in commit `53267bbd` ("fix(alphaengine): key ic_engine checkpoint invalidation on code
content, not git HEAD"). `_git_head_short` is gone from `services/ic_engine.py`; checkpoint
directories are now keyed by `_checkpoint_content_key()`, a SHA-256 hash of every first-party
module (`src/`, `services/`) actually imported into the process, derived from `sys.modules`
rather than a hand-maintained list. Verified live in code as of 2026-07-17 during todo 130 work.
Found sitting unclosed in `pending/` during a pre-reboot housekeeping pass — moving to
`completed/` now. Note: todo 122 (checkpoint content-key blind to APR config drift) is a
distinct, still-open gap in the same area and was NOT resolved by this fix.

# 121 - ic_engine checkpoint invalidation keys on repo HEAD, not on its own dependencies

**Found:** 2026-07-15, during a real incident. `ops_corpus_pipeline_run.sh --from-step 5` ran
30h51m (Jul 14 09:08 EDT -> Jul 15 15:59 EDT), finished the full 80-symbol per-symbol pass,
crashed during the cross-sectional pass on a transient dropped DB connection
(`server closed the connection unexpectedly`). Resumed at 16:18 EDT with the documented
`--from-step 5` command -- expected the per-symbol checkpoint mechanism
(`_save_checkpoint`/`_load_checkpoint`, services/ic_engine.py:2140-2170) to skip the 80 symbols
already computed. It didn't: `n_to_compute: 80`, zero resumed, full per-symbol pass repeated
(~31hrs of compute wasted).

**Root cause (confirmed):** checkpoints are stored under
`logs/ic_engine_checkpoints/<training_window_end>_<git_head_short>/` (`_checkpoint_dir`,
services/ic_engine.py:2135), keyed on `git rev-parse --short HEAD` (`_git_head_short`,
services/ic_engine.py:2113). This key was deliberately added 2026-07-12 after a real near-miss
(a routing-logic fix landed mid-run and could have made stale checkpoints replay against new
code). But the key is *any* commit reaching HEAD, not "did a file ic_engine.py actually depends
on change." Between the first run's start (HEAD=`39a1713c`) and the resume (HEAD=`eb5a9814`,
`Merge branch 'regime-boundary-churn-diagnostic'`), an unrelated commit landed on `main` --
diagnostic tooling that never touches ic_engine.py or its imports. That alone shifted the
checkpoint directory path, so the resume found zero checkpoints under the new HEAD despite 80
valid ones sitting on disk under the old one. On a long-lived multi-day pipeline run, *any*
commit anywhere in the repo (this one included, from an unrelated branch merge) silently voids
all in-flight checkpoints.

**Fix scope:** narrow the invalidation key from "repo HEAD" to a content hash of what
ic_engine.py actually depends on -- e.g. hash `services/ic_engine.py` +
`src/intelligence/statistics/ic_math.py` + whatever else is on its real import graph, not the
full repo state. Preserves the original 2026-07-12 safety intent (code that changed under a
running job invalidates its checkpoints) without penalizing unrelated concurrent work landing on
`main`. Alternative: key on the specific module mtimes/hashes rather than git at all, so local
uncommitted edits are caught too (current git-HEAD keying has that gap either way).

**Priority:** not yet triaged into PRIORITIES.md -- raise next planning pass. This will recur on
every multi-day `ic_engine` run as long as `main` sees any commits during the run, which is the
normal case in this repo (concurrent sessions land unrelated work regularly, per
[[feedback_concurrent_sessions_shared_dir]]).
