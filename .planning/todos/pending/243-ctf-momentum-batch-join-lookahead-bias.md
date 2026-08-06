---
status: fixed-pending-recompute-decision
priority: P0
filed: 2026-08-03
fixed: 2026-08-03
source: code-reviewer subagent review of todo 241's live-path fix, mechanism
  independently verified against source before filing
---

# `ctf_momentum`'s batch/corpus join selects the still-forming HTF bar, not the last
# completed one -- real lookahead in every published IC number at 5m/15m/1h

## What

Higher-timeframe bars are stamped by **period start**, not close
(`src/core/service_utils.py:76`: *"For all higher TFs ts is the period start; close = ts +
duration"*; confirmed independently in `src/core/bar_accumulator.py:158`,
`_floor_to_period`).

`backfill_feature_factory.py`'s `_build_ctf_series()` builds a `{htf_bar_ts: (ctf_momentum,
ctf_vwap_align, ctf_regime_align)}` dict from HTF bars. The join back onto LTF rows
(`feature_factory.py:6925`) is:

```python
_idx = bisect.bisect_right(ctf_ts_list, bar_ts) - 1
```

For a 5m bar at `bar_ts=10:05`, with 1h bars stamped `[09:00, 10:00, 11:00, ...]`:
`bisect_right([...,10:00,11:00,...], 10:05) - 1` lands on the `10:00` HTF bar -- the bar
covering 10:00-11:00, which has **not closed yet** as of 10:05 (closes at 11:00). But
`_build_ctf_series` computes Wilder RSI from `closes = np.array([b["close"] for b in
htf_bars])` -- the `10:00` bar's `close` value used in that RSI is only known once the bar
actually finishes forming, at 11:00. Using it to characterize the moment at 10:05 is
lookahead: at that exact wall-clock instant in a real trading scenario, that closing price
does not exist yet.

Same shape at every affected tf:

| LTF | HTF | Lookahead window |
|---|---|---|
| 5m | 1h | up to 55 minutes |
| 15m | 1h | up to 55 minutes |
| 1h | 1d | up to a full trading day |
| 1d | 1d (self-referential) | **none -- this case is fine** |

The `1d` case is genuinely safe: batch only ever processes historical, already-fully-closed
daily bars (backfill runs after the fact), so `bisect_right` selecting "the current bar
itself" is valid there -- exactly what `_build_ctf_series`'s own comment claims ("bisect_right
selects the current bar's CTF which is valid since the bar has closed at computation time").
That comment is true for 1d only; it does not hold for the cross-timeframe cases, where the
selected HTF bar is a *different, still-open* bar relative to the LTF row's own timestamp.

This affects all three CTF fields sharing this join (`ctf_momentum`, `ctf_vwap_align`,
`ctf_regime_align`), not just `ctf_momentum`.

## How this was found

Discovered as a code-review finding on todo 241 (ctf_momentum live/batch divergence fix).
Todo 241's live-path replacement (`feature_vector_pipeline.py`'s
`_update_ctf_cache_from_htf_bar`) only ever reads fully-closed bars from `self._bar_history`
(bars are appended to that buffer only after the bar closes) -- it is therefore genuinely
causal, and as a direct consequence **cannot** and does not reproduce batch's current
(lookahead-contaminated) values for 5m/15m/1h. Todo 241's own regression test was corrected
to state this honestly rather than claim false parity
(`tests/unit/services/test_ctf_momentum_live_batch_parity.py`'s module docstring).

## Why this matters

`services/cross_sectional_spread_tracker.py` ranks directly on `ctf_momentum`
(`_FEATURE = "ctf_momentum"`) -- the sole ranking signal for Phase 167's
`cross_sectional_relative_value` construction, **the first and only construction in this
project to pass both live Validation Gates**. Since live IBKR ingestion is intentionally
stopped, essentially every `ctf_momentum` value in `feature_vectors` today originated from
this lookahead-contaminated batch path. Phase 167's validated result was measured, at least
in part, against a feature containing real future information -- a live-path integrity gap in
this project's single most consequential proof to date, and exactly the kind of "silent wrong
answer" CLAUDE.md's north star treats as unacceptable.

**Not yet quantified.** The mechanism is confirmed and mechanically airtight (traced through
actual `bisect` semantics against actual bar-stamping code, not inferred). The *magnitude* --
how much this moves `ctf_momentum`'s measured IC, and whether it's enough to flip Phase 167's
Gate 1/Gate 2 verdicts -- is unmeasured. Do not assume it invalidates Phase 167 without
measuring; also do not dismiss it as immaterial without measuring. This is the explicit
project mandate: "earn promotion through proof," which cuts both ways here.

## Fix -- APPLIED 2026-08-03

Applied the correctness fix (zero-cost, no recompute triggered): `_rekey_ctf_series_to_actual_close()`
(new function, `services/backfill_feature_factory.py`) re-keys `_build_ctf_series`'s dict from HTF
period-start to each bar's **actual** close -- the next HTF bar's own start -- for genuine
cross-timeframe pairs (`tf != htf_tf`) before the `bisect_right` join runs. The 1d self-referential
case (`tf == htf_tf`) is returned unchanged, as originally scoped.

Rejected the two originally-proposed approaches in favor of a third: neither `ts + TF_DURATIONS[htf_tf]`
(flat offset) nor `bisect_left` against unshifted keys is correct, because HTF bars are not always
their full nominal duration. **Confirmed against production data** (`market_data_ohlcv_tradeable`,
SPY 1h, 2026-07-27): the RTH-session-opening 1h bar is a genuine 30-minute partial (13:30-14:00 UTC,
gap-to-next = 30min), not a full 60-minute bar. A flat `+3600s` offset would overshoot that bar's true
close by 30 minutes, silently routing 5m/15m rows in the overshoot window to a stale, older bar instead
of the correct, already-closed partial one -- found during code review of the flat-offset fix, before
it shipped. The applied fix instead keys each bar by its **actual successor's start timestamp** (the
only value that is always correct, partial bar or not); the last HTF bar in any given fetch has no
known successor and is dropped from the re-keyed dict rather than guessed at.

Regression tests: `tests/unit/services/test_ctf_momentum_live_batch_parity.py`'s
`TestCtfBatchJoinLookaheadFix` (4 tests) -- exercises `_rekey_ctf_series_to_actual_close()` directly
(not a duplicated re-key expression), covering the original lookahead scenario, the partial-bar
scenario, and the 1d self-referential no-op. Full `tests/unit/` suite green, ruff/black clean.
Peer-reviewed (code-reviewer subagent) before finalizing; the partial-bar finding it raised is what's
now fixed.

## Next step (per user direction 2026-08-03: measure before touching the corpus)

The join fix itself is done and affects only *future* backfill/recompute runs -- it does not
retroactively touch any existing `feature_vectors` row. What's still explicitly gated on the user:

1. **Read-only measurement first.** Quantify how much the fixed join changes `ctf_momentum`'s
   measured per-symbol/cross-sectional IC at 5m/15m/1h -- rerun (or diff against) the existing
   `ic_engine`/nonlinear_interaction_combiner-style measurement scripts with the corrected join
   applied to a scoped sample, without touching the live `feature_vectors` corpus.
2. Based on that measurement, decide: (a) is a corpus-wide recompute of `ctf_momentum`
   (and `ctf_vwap_align`/`ctf_regime_align`) warranted, and (b) does Phase 167's Gate 1/Gate 2
   verdict need re-running under corrected values. Both are real, expensive, load-bearing
   decisions -- explicitly the user's call, not something to trigger unilaterally.
3. Only after 1-2: re-run affected IC/gate measurements for real against a corpus computed with
   the now-fixed join, update `docs/research/data-edge-source-thesis.md` and Phase 167's verdict
   record with the corrected numbers.

**Escalated 2026-08-04 -- this is no longer just the `nonlinear_interaction_combiner` research
thread's problem.** Tracing `_run_evaluate_gate()` (`cross_sectional_spread_tracker.py:1196`)
found Gate 1 reads `construction_spreads` rows built from a decile-ranking of
`feature_vectors.ctf_momentum` directly (`_PANEL_SQL_BACKFILL`) -- the exact leaked column. The
recorded verdict (`logs/construction_verdicts/gate1_latest.json`, 2026-07-27,
`gate1_passes=true`) is therefore built on the same contaminated data as
`nonlinear_interaction_combiner`'s now-retracted "substantial" claim. STATE.md updated 2026-08-04
to mark Phase 167 UNVERIFIED and Phase 168 (its direct follow-on) DO-NOT-EXECUTE pending
re-check.

**Full cross-sectional Gate 1 re-verification built 2026-08-04**:
`scripts/analysis/phase167_gate1_ctf_join_fix_reverify_15m.py` -- reuses every pure Gate 1
function from `cross_sectional_spread_tracker.py` unmodified (`decile_legs`, `spread_from_legs`,
`one_way_turnover`, `net_spread_by_cost_bps`, `evaluate_spread_gate`,
`shuffled_ranking_null_p`), rebuilds the full equity-universe panel in memory with corrected
`ctf_momentum` (via `_build_ctf_series`/`_rekey_ctf_series_to_actual_close`, same functions the
SPY single-symbol pilots used), and includes a self-check pass that must reproduce the known
`gate1_passes=true` verdict against the original leaked values before trusting any corrected-join
output. Read-only -- no `construction_spreads`/`feature_vectors` writes.

**Run 2026-08-04, first attempt: self-check ABORTED -- blocked on a separate, newly-discovered
corpus-state problem** ([todo 253](253-forward-returns-frozen-at-oos-boundary-corpus-rebuild-skipped-step3.md)):
`construction_spreads` empty, `forward_returns` frozen at `oos_start` for all 4 tfs, so the
original script (which read `return_fast`/`return_slow` from `forward_returns`) had zero eligible
OOS rows. Root cause turned out structural, not a skipped step: Phase 141.1's OOS holdout
enforcement makes it impossible for the normal pipeline to ever write `forward_returns` past
`oos_start` (`docs/plans/OOS-EVAL-PROTOCOL.md`) -- full detail in todo 253, including the D-04
gate-governance fix landed the same day (`gate_evaluations`/`gate_look_log.jsonl` now wired into
`cross_sectional_spread_tracker.py`, confirming no prior recorded look for this construction
existed, resolving the cadence question).

**Run 2026-08-04, second attempt (DIAGNOSTIC TIER): SUCCEEDED, verdict FLIPS.** Rewrote the
script to compute OOS `return_fast`/`return_slow` on the fly via `forward_log_return()` against
raw `market_data_ohlcv_tradeable` bars -- the same pattern `ops_oos_holdout_eval.py` already
uses, no `forward_returns` dependency (todo 253's fix design). Self-check against the ORIGINAL
leaked join reproduced the recorded `gate1_passes=true` -- harness confirmed faithful. **Against
the CORRECTED join: `gate1_passes=FALSE`.** Both scales' `ci_lower` go negative (fast: 0.000187
-> -0.000141; slow: 0.000164 -> -0.000486), and the shuffled-ranking null no longer clears either
scale (fast `null_p` 0.0 -> 0.675, slow 0.0 -> 1.0 -- slow's observed spread is now met or beaten
by every one of 40 null draws). Same direction as the SPY single-symbol pilot (15m point_ic
+0.0746 -> +0.0047, CI crossing zero) -- two independent measurements now agree. Artifact:
`logs/construction_verdicts/gate1_ctf_join_reverify_15m_DIAGNOSTIC_20260804T165458Z.json`.

**Still diagnostic-tier, not authoritative** (skips `forward_return_writer.py`'s suspect-value/
cross-symbol-corroboration corrections; an authoritative re-run needs `forward_returns` genuinely
repopulated past `oos_start`, todo 253's remaining scope). Materially raises confidence the
eventual authoritative re-run will also fail, but does not settle it -- do not close this todo or
reverse STATE.md's "Phase 167 UNVERIFIED, do not start Phase 168" call on diagnostic evidence
alone.

**Run 2026-08-04, third attempt: todo 253's `forward_returns` fix landed cleanly, but the
follow-on `--backfill`/`--evaluate-gate` run answered the WRONG question -- caught same day,
correction below.** With `forward_returns`' OOS region genuinely populated (todo 253's
authoritative fix, real `forward_return_writer.py`, real corroboration logic, 302,039 rows, zero
failures), `cross_sectional_spread_tracker.py --backfill` + `--evaluate-gate` were run for what
was intended as the real authoritative re-verification. Recorded `gate1_passes=True`
(`gate_evaluations`, gate_id `gate1_ctf_momentum_decile_ls`, committed via the new D-04
governance). **That PASS does not test the corrected join.** `cross_sectional_spread_tracker.py`
reads `ctf_momentum` directly from `feature_vectors` (`_PANEL_SQL_TEMPLATE`), and
`feature_vectors.ctf_momentum` was never recomputed with this todo's own join fix -- the
corpus-wide recompute question (this file's "Next step," item 2) was explicitly left to the user
and was never triggered. **Verified directly, not assumed**: SPY 2026-01-05 15:00 UTC's stored
`ctf_momentum` (0.2321) matches the OLD leaked-join computation bit-for-bit; the corrected join
gives -0.1281 for the identical bar. **What this run actually established**: the original,
still-leaked `ctf_momentum` reconfirms its 2026-07-27 PASS on a complete, properly-corroborated
OOS window (3,803 bars / 147 clusters, up from the original run's 650/130 -- the corpus simply
has more OOS history now) -- a real, useful result (rules out "the 2026-07-27 PASS was itself a
data-quality artifact of an incomplete OOS window"), but it is not the corrected-join
re-verification this todo exists to get. **New blocker for the real test**: `_write_gate_result`'s
D-04 run-once guard (working exactly as designed) now refuses a second write for gate_id
`gate1_ctf_momentum_decile_ls` -- testing the corrected join through the real production Gate 1
path needs either a distinct gate_id (e.g. suffixed by a join-version/compute-version marker) or
an explicit decision on how the already-recorded PASS should be treated once/if the corpus is
actually recomputed. **The corpus-wide `ctf_momentum`/`ctf_vwap_align`/`ctf_regime_align`
recompute decision (this file's "Next step" item 2, still the user's call, still not made) is now
the hard blocker for the actual answer** -- not a diagnostic-tier limitation anymore, since the
authoritative machinery is otherwise fully ready and proven correct.

**Run 2026-08-05 night into 2026-08-06: `--apply` write attempt launched, killed -- real
batching defect found, plus undetected contention with a concurrent OHLCV backfill.**
`scripts/ops/corpus/ops_ctf_columns_recompute_15m.py --apply` was launched in the background
(per the dry-run validation above) to actually write the corrected 80-symbol/15m corpus. It ran
10+ hours (started ~23:31, still going the next morning) without finishing. Root cause: the
script's `cur.executemany()` call (psycopg3) sends each row as its own network round-trip rather
than a true batched statement -- confirmed via `pg_stat_activity` showing individual single-row
`UPDATE feature_vectors ... WHERE symbol=$4 AND tf=$5 AND bar_ts=$6` statements executing one at
a time. At ~1-2ms/round-trip, 8.28M rows is hours of pure overhead, matching the observed
runtime. **Compounding factor, only found after the fact**: the run was concurrent with the
client-id 41 OHLCV backfill (`infrastructure_run_historical_pipeline.py`, todo 259's in-flight
111/135-symbol fetch, itself running 24+ hours at the time) -- contention on top of the batching
defect. The process check done before launching only grepped for known heavy-job script names
(`backfill_feature_factory`/`ic_engine`/`regime_writer`); it didn't match
`infrastructure_run_historical_pipeline.py`'s name, so the collision went undetected until
diagnosed live. User confirmed the OHLCV backfill is expected/intentional right now (todo 259
is real, in-progress, sequenced ahead of the Phase 151 waves 6-7 corpus recompute per STATE.md).
The `--apply` run was killed as a result -- safe to kill: per-symbol `conn.commit()` means
whatever alphabetically-early symbols it reached stay correctly written, and the script's
changed-row comparison logic makes re-running fully idempotent. **Verified post-kill**: SPY
(late-alphabet among the 80) still reads `0.23211576956201058` -- the old leaked value -- at the
known spot-check bar (`2026-01-05 15:00:00+00`), confirming the run died before reaching S and
nothing downstream of that point got corrupted mid-write.

**Not yet retried.** Before the next `--apply` attempt: (1) fix the batching -- a real
multi-row `UPDATE ... FROM (VALUES ...)` per symbol (or psycopg3 pipeline mode) instead of
`executemany()`, which should take this from 10+ hours to low minutes, matching the dry-run's
92-second read-only baseline; (2) don't run it concurrently with todo 259's OHLCV backfill --
either wait for that to finish or confirm real DB/CPU headroom first, and grep `ps aux` broadly
rather than for a fixed list of known script names before launching any second heavy write job
(see [[feedback_always_parallel_tracks]], reinforced by this exact miss).

**Run 2026-08-06, batching fix applied + verified on SPY.** Rewrote
`_recompute_symbol`'s write path to use `services/_batch_utils.py`'s `bulk_update_by_key()`
(COPY into a temp table + one JOIN-UPDATE) instead of `cur.executemany()` -- same helper
`regime_writer.py` already uses for its own `feature_vectors` writes, no new pattern
introduced. Ruff/black clean.

**Operational gotcha hit and resolved during verification**: an earlier bounded test run was
wrapped in `timeout 60`, which killed the *client-side* python process but left the Postgres
backend running server-side (`pg_stat_activity` showed it still `active` on the same UPDATE a
minute later) -- a second attempt then blocked waiting on a `transactionid` lock held by the
orphaned first one. Resolved via `pg_terminate_backend()` on the orphaned pid. Lesson: don't
wrap a real DB-writing invocation of this script in `timeout` again; let it run to completion
or kill it deliberately (`kill <pid>`) and confirm via `pg_stat_activity`/`ps aux` that both the
client process and the server backend are actually gone before retrying, not just the client.

**Real single-symbol write, SPY, succeeded**: `--apply --symbols SPY` completed in **145.7s**
(130,372 rows examined, 129,153 written). Spot-check confirms the fix:
`bar_ts='2026-01-05 15:00:00+00'` now reads `-0.12805604993218622`, matching the plan's expected
`-0.1281` (was the leaked `0.2321` before this run).

**145.7s for one symbol is much better than the dead 10+-hour run, but not the "low minutes"
originally hoped for -- root cause is very likely `feature_vectors`' TimescaleDB compression,
not the batching fix's own overhead.** Confirmed live: `feature_vectors` is a compressed
hypertable, currently 80 compressed chunks + 3 uncompressed (`chunk_compression_stats`).
SPY carries the corpus's longest 15m history, so its UPDATE likely touches most/all 80
compressed chunks, each requiring on-the-fly decompression before the row-level UPDATE can
apply -- exactly the failure mode `docs/foundation/performance-investigation-sop.md` calls out
("check chunk count/compression status as first-class suspects" for a slow write against a
TimescaleDB hypertable). **Do not extrapolate SPY's 145.7s linearly to all 80 symbols** --
symbols with shorter history spans fewer chunks and should be proportionally faster, but the
real full-corpus runtime is unmeasured. A plausible range is tens of minutes to low hours, not
the 92-second dry-run baseline (that number was read-only and never paid the decompression
cost the write path does -- exactly the SOP's "never trust a read-only test for a write-path
question" warning, confirmed the hard way here).

**Still gated on user go-ahead for the full 80-symbol run** -- current conditions are favorable
(DB load low, todo 259's OHLCV backfill isn't hitting Postgres, only IBKR), but the runtime
uncertainty and the scale of the write (up to ~8.7M more rows) mean this stays an explicit
go/no-go rather than something to launch unilaterally, consistent with this file's own earlier
"Next step" framing.

## Cross-refs

- [todo 241](241-ctf-momentum-live-batch-compute-divergence.md) -- the live-path fix that
  surfaced this via code review; live's implementation is correct and does not need to change
  for this todo
- [todo 189](../completed/189-ctf-momentum-1d-self-referential-htf-not-cross-timeframe.md) --
  documents the 1d self-referential case, unaffected by this bug
- `docs/research/data-edge-source-thesis.md` -- cites `ctf_momentum` as "the strongest, most
  cross-regime-consistent-sign symbol-varying signal" for `cross_sectional_relative_value`;
  needs a caveat pointing here until measured
