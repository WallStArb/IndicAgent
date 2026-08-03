---
status: completed
priority: P3
filed: 2026-08-02
closed: 2026-08-02
source: re-running the original nonlinear_interaction_combiner 1h finding script from a prior session that appeared "hung"
---

## What

`scripts/analysis/nonlinear_interaction_combiner_lightgbm_check.py` (the ORIGINAL 1h script that produced
the nonlinear_interaction_combiner finding cited throughout `docs/research/data-edge-source-thesis.md` and STATE.md,
`point_ic=0.258`) now gets OOM-killed (SIGKILL, exit 137) before it prints even its first line
of output ("Loaded N equity 1h rows"). Confirmed live 2026-08-02: RSS grew to ~22GB, host swap
hit 19Gi/22Gi used, 4.9Gi RAM free, before the process was killed to protect the box (Postgres +
live indicagent services run on this same host).

This is the same failure mode todo 188 already flagged and deferred *for the 15m replication*
(~8.1M rows, `SELECT fv.*` loading all columns into one pandas DataFrame via
`[dict(r) for r in rows]`) — it turns out the 1h script now hits it too. The corpus has grown
since this script was written (263 `feature_vectors` columns today vs. the ~150 the script's own
docstring cites, plus Phase 164/165 primitive additions and general history growth), so a load
that was previously safe for 1h no longer is.

This also explains a "hung" background job from a prior session that this session investigated:
it wasn't a `nohup`/tool-survival bug — the process was actually getting killed (0-byte log,
no dmesg/journalctl OOM trace visible without sudo, but the swap/RSS signature matches an
OOM/heavy-swap-thrash death) and the session's tracking just never learned that.

## Next step

Apply the same fix direction todo 188 already scoped for 15m to this script too: project only
the needed columns in SQL (not `SELECT fv.*`), or chunk the read (server-side cursor /
`fetch` in batches) instead of materializing the full row set as Python dicts before handing to
pandas. Once fixed, both the 1h re-verification (relevant given `forward_returns` was truncated
and rebuilt under todo 208's corrected definition since this finding was first produced) and the
15m replication (todo 188) can reuse the same memory-safe loader.

Not urgent — the existing 1h finding and 1d replication numbers already in
`docs/research/data-edge-source-thesis.md` are unaffected; this only blocks *re-running* either.

## Resolution (2026-08-02, same session)

Added `_fetch_frame_chunked()` to `nonlinear_interaction_combiner_lightgbm_check.py`: streams `_FV_SQL`
via an asyncpg server-side cursor in 100k-row batches (list of `Record`s straight into
`pd.DataFrame`, no `[dict(r) for r in rows]` intermediate), downcasting float64->float32 per
batch before concatenating. Also changed `_train_and_predict_oos`'s `X` to `np.float32` (was
`float`, doubling the already-large feature matrix). Both replication scripts
(`nonlinear_interaction_combiner_replication_1d.py`, `..._15m.py`) updated to import and use the same
helper instead of their own copies of the unsafe pattern (removed now-unused `asyncpg` imports).

Verified live: the 1h script ran end to end, RSS stayed bounded (no OOM), exit 0. This also
delivered the re-verification the corpus correction (todo 208) made worth doing: tree_score mean
point_ic=0.2139 (80/80 pass) vs `ctf_momentum`'s 0.0533 (79/80), cross-sectional-neutral
0.1822 vs 0.0511 (both clear CI) — finding holds, magnitude down ~30-40% from the pre-208-fix
0.2992/0.258 numbers (expected effect of correcting the target variable). Full result recorded in
[[project_t3_t5_edge_thesis_results_2026_07_26]]. 15m replication (todo 188, ~8.1M rows) can now
reuse the same fixed loader but hasn't been re-run yet — `_train_and_predict_oos`'s `y` and
LightGBM's own per-fold memory footprint at that row count are still unverified at scale.
