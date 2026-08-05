---
status: closed
priority: P0
filed: 2026-08-04
closed: 2026-08-04
source: blocked todo 243's Phase 167 Gate 1 re-verification -- the re-verification harness's
  own self-check found zero eligible OOS rows. Root-cause theory revised same day after reading
  docs/plans/OOS-EVAL-PROTOCOL.md and tracing ops_corpus_pipeline_run.sh -- the original theory
  ("step 3 got silently skipped") was plausible but wrong; corrected below.
---

# Phase 167's Gate 1/Gate 2 depend on `forward_returns` having rows in the OOS holdout region --
# by design, the normal pipeline never puts them there, and no reusable step does either

## What (corrected diagnosis -- supersedes this file's original framing)

**Original theory, now known incomplete:** "`forward_return_writer` (pipeline step 3) got
silently skipped by a `--from-step 5` resume." Plausible on the data alone (`forward_returns`
frozen right at the OOS boundary at all 4 tfs), but wrong as a root cause -- it is NOT possible
for the *normal* pipeline invocation of step 3 to ever populate `forward_returns` past
`oos_start`, skip or no skip.

**What's actually true, confirmed by reading `docs/plans/OOS-EVAL-PROTOCOL.md` and
`ops_corpus_pipeline_run.sh`:** the OOS holdout is enforced by TWO independent, deliberate
layers (Phase 141.1): the orchestrator clamps `TRAINING_WINDOW_END = LEAST(MAX(bar_ts),
oos_start)` before ever calling `forward_return_writer.py`/`ic_engine.py`, AND both of those
scripts' `--training-window-end` CLI flag is `required=True` with **no bare-`MAX(bar_ts)`
fallback** -- an invocation missing the flag refuses to run rather than silently consume the
holdout. This is good, deliberate, working-as-intended engineering: `forward_returns` is NOT
supposed to have rows past `oos_start` from the normal pipeline. That's the holdout doing its
job, not a bug.

The protocol names exactly two sanctioned ways to actually SCORE against the holdout once it's
worth looking at: `scripts/ops/corpus/ops_oos_holdout_eval.py` (interim diagnostic -- explicitly
"never a promotion gate") and `EnsembleICEngine` in OOS mode (the authoritative scorer, "run at
most once per milestone gate" -- re-running after seeing a result to check if it now passes is
explicitly forbidden). Critically, **`ops_oos_holdout_eval.py` never depends on `forward_returns`
having OOS rows at all** -- it computes forward returns ON THE FLY, read-only, straight from
`market_data_ohlcv_tradeable` opens via `forward_log_return()` (the same pure function
`forward_return_writer.py` uses to build what it persists). That's the pattern this whole class
of problem is supposed to use.

**The actual gap:** `cross_sectional_spread_tracker.py --evaluate-gate` (Phase 167's Gate 1) is a
THIRD OOS scorer, built after the protocol was written, that was never folded into it. It has no
reference to `OOS-EVAL-PROTOCOL.md` anywhere in its module, no defined cadence rule, and --
unlike the sanctioned diagnostic scorer -- it reads `return_fast`/`return_slow` directly from the
persisted `forward_returns` table (`_GATE_PANEL_SQL`, `_GATE_ROWS_SQL` via `construction_spreads`)
instead of computing them on the fly. Its 2026-07-27 `gate1_passes=true` verdict almost certainly
consumed a one-off, undocumented manual population of `forward_returns`' OOS region (there is no
committed script that does this) that a subsequent, routine, CORRECT
`infrastructure_truncate_derived_tables.sh` run (`TRUNCATE forward_returns;`, confirmed present
in that script, "before a full corpus re-backfill") then wiped -- with nothing to repopulate it,
because nothing sanctioned ever populates that region in the first place.

## Why this matters

The system has a rigorously engineered holdout (no notes -- two independent enforcement layers,
loud-crash-not-silent-fallback discipline, a pre-registered protocol document). What it does NOT
have is a rigorously engineered way to ever SCORE that holdout for constructions built after
Phase 144 -- Gate 1/Gate 2 bolted on a THIRD ad hoc path that (a) duplicates a solved problem
(computing OOS returns without needing a persisted table) instead of reusing the pattern
`ops_oos_holdout_eval.py` already established, and (b) is silently destroyed by a routine,
correct, everyday maintenance operation with zero warning -- a milestone-defining "PASSED"
verdict can go to "unmeasurable" with no signal anywhere in the system. Exactly the class of
silent fragility CLAUDE.md's north star treats as unacceptable, and a genuine SoC/reuse gap:
building a new persisted-table dependency where a proven, simpler, already-built compute-on-read
pattern was sitting right there.

## Fix (design, not yet executed)

Reuse `ops_oos_holdout_eval.py`'s pattern, not a new pipeline stage: compute
`return_fast`/`return_slow` for the OOS window on the fly via `forward_log_return()` against
`market_data_ohlcv_tradeable` opens, exactly as that scorer already does, instead of depending on
`forward_returns` having OOS rows. This is strictly simpler than any fix that tries to
(re)populate a persisted table in the holdout region -- no new pipeline stage, no new fragile
freshness dependency, and it matches the one pattern this codebase already trusts for this exact
problem.

Two tiers this naturally splits into, matching `OOS-EVAL-PROTOCOL.md`'s own diagnostic-vs-
authoritative distinction:

- **Diagnostic tier (cheap, safe, re-runnable anytime, matches `ops_oos_holdout_eval.py`
  exactly):** todo 243's re-verification script
  (`scripts/analysis/phase167_gate1_ctf_join_fix_reverify_15m.py`) can be converted to compute
  returns on the fly instead of joining `forward_returns` -- fully self-sufficient, needs no
  corpus-pipeline step to have run first. **Caveat that must be stated, not hidden:**
  `forward_return_writer.py` applies suspect-value flagging and cross-symbol corroboration
  (`_apply_cross_symbol_corroboration`) on top of the raw `forward_log_return()` output before
  persisting -- a naive on-the-fly recomputation will not byte-for-byte match what the
  authoritative pipeline would have written. Good enough for a first-look diagnostic (matches
  `ops_oos_holdout_eval.py`'s own accepted scope: "diagnostic only... never a promotion gate"),
  not a substitute for an authoritative re-verification.
- **Authoritative tier:** would require the real `forward_return_writer.py` (with its
  suspect/corroboration logic intact) to genuinely populate the OOS region -- the "separate,
  rare, pre-committed OOS evaluation step" the protocol already names as existing but which has
  no committed, reusable script implementing it for anything past the feature-IC level. Building
  that script is real, scoped work; running it is a genuine "look at the holdout" event.

## Open judgment call for the user -- not something to decide unilaterally

`OOS-EVAL-PROTOCOL.md`'s cadence rule: *"The authoritative OOS scoring is run at most once per
milestone gate. Re-running it to check if it passes now after a tweak is forbidden."* Phase 167
already spent its one look (2026-07-27, `gate1_passes=true`). Todo 243 found that look was made
against a `ctf_momentum` value contaminated by an unrelated, independently-discovered data
lookahead bug -- arguably that means the *feature itself* wasn't the one Phase 167 believed it
was scoring, not that the *holdout* was peeked at twice for the same measurement. Whether
re-scoring Gate 1 under the corrected join counts as a legitimate first real look (bug fix,
discovered independent of the OOS result) or a forbidden second look (protocol says don't
renegotiate after seeing a result) is exactly the kind of pre-commitment-discipline question this
protocol exists to keep out of ad hoc, in-the-moment agent judgment. Flag to the user before
running any authoritative-tier re-verification; the diagnostic tier is lower-stakes and more
defensible to run freely (matching `ops_oos_holdout_eval.py`'s own "may be run more freely" rule)
but its result should be labeled diagnostic-only in whatever it produces.

## Fix -- DONE 2026-08-04: D-04 run-once governance wired into `cross_sectional_spread_tracker.py`

Investigating the cadence question directly (checking `gate_evaluations`/`.planning/gate_look_log.jsonl`
for whether Phase 167's 2026-07-27 look was ever recorded) found something more concrete than a
philosophical question: this project already has a proven, reusable, run-once-enforced gate
governance primitive (`gate_evaluations` table + `.planning/gate_look_log.jsonl` append-only
audit trail, `fetch_sql_sha256` drift detection) -- built for Phase 148's gates
(`ops_oos_gate1_signal_eval.py`, `gate_id`s `gate1_signal`/`gate2_execution`) and reused
correctly for Phase 166's (`gate166_baseline`/`gate166_scalar`). **Phase 167's Gate 1/Gate 2
never used it at all** -- confirmed via a direct read of `gate_look_log.jsonl` (4 entries total,
all Phase 148/166, zero Phase 167 rows) and `gate_evaluations` (same 4 rows, same gap). It wrote
only to `logs/construction_verdicts/*.json`, a freely-re-runnable file with no re-run guard.
This resolves the cadence question mechanically rather than by interpretation: there is no
recorded completed look for this construction in the system of record, so a first real,
protocol-compliant run is unambiguously a first look, not a second one.

**Fix applied**: `services/cross_sectional_spread_tracker.py`'s `_run_evaluate_gate()` and
`_run_evaluate_attribution()` now write one `gate_evaluations` row (`gate_id`s
`gate1_ctf_momentum_decile_ls`/`gate2_ctf_momentum_decile_ls`, disambiguated by construction
name so a future construction sharing this module never collides) plus one
`.planning/gate_look_log.jsonl` entry per real run, reusing `ops_oos_gate1_signal_eval.py`'s
exact pattern (`_write_gate_result`: atomic re-assert-no-prior-row-then-INSERT in one
transaction; `_append_gate_look_log`: append-only, embeds an `oos_start`/APR-values/
`fetch_sql_sha256` snapshot for drift auditing) rather than inventing a second mechanism for the
same discipline. A new `--dry-run` CLI flag (matching Phase 148's script's own UX) lets
dev-time verification run without consuming the one-shot gate. The existing
`write_verdict_artifact` JSON-file mechanism is unchanged and remains freely re-runnable -- it's
a human-inspection convenience, not the governance layer. 5 new unit tests added
(`tests/unit/test_cross_sectional_spread_tracker.py`), full `tests/unit/` suite green (2
pre-existing, unrelated skips), ruff/black clean.

**All remaining items DONE 2026-08-04:**
- `counterfactual_tracker.py`'s own `--evaluate-gate` (Phase 142B) has the SAME gap -- split out
  to its own todo ([255](255-counterfactual-tracker-evaluate-gate-no-d04-governance.md)) rather
  than expanding this fix's blast radius past the construction that was actually blocking todo
  243. Deliberately not fixed here.
- `CorpusManifest` emission added to `forward_return_writer.py` (parity fix -- every other batch
  step had it, this one didn't). Both the `--reclassify-suspect-only` early-return path and the
  full run path now emit a manifest; per-cell failures recorded via `manifest.add_error()` (which
  correctly flips status to `"failed"` even on a partial run, matching `ensure_success_for`'s
  strict-success contract) rather than silently reporting a degraded run as clean. Outer fatal
  exception path also wired, matching `ic_engine.py`'s established convention exactly
  (manifest write wrapped so a manifest-write failure never masks the original error).
- `cross_sectional_spread_tracker.py`'s gates folded into `docs/plans/OOS-EVAL-PROTOCOL.md`'s
  prose as a named third scorer ("Construction-level scorer, Phase 167+"), with its own cadence
  rule explicitly extending the "at most once per milestone gate" discipline per-construction, and
  an explicit note that `gate_evaluations`/`gate_look_log.jsonl` is the system of record for
  whether a `gate_id` has already had its look -- plus a flagged-not-resolved judgment call
  (does a corrected input to an existing construction earn a fresh look under a new `gate_id`, or
  does the protocol's spirit still treat it as the same gate) that this investigation actually
  ran into (see todo 243's 2026-08-04 "answered the wrong question" correction) and shouldn't be
  silently re-litigated by picking a new `gate_id` to route around the guard next time.
- `construction_spreads` (Phase 167's own table) repopulated via `--backfill` 2026-08-04 (130,625
  bars, full 2006-2026 corpus, 61.85s, zero errors).

Full `tests/unit/` suite green after all changes, ruff/black clean.

## Diagnostic-tier result, 2026-08-04 -- raises the stakes on the authoritative-tier prerequisite

The diagnostic-tier script (todo 243, on-the-fly returns per the fix design above) ran
successfully: self-check reproduced the recorded `gate1_passes=true` against the leaked join,
then found `gate1_passes=FALSE` against the corrected join -- both scales' CI go negative, and
the shuffled-ranking null no longer clears (fast `null_p` 0.675, slow 1.0). Consistent with the
SPY single-symbol pilot. This is diagnostic evidence, not an authoritative verdict -- it does not
replicate `forward_return_writer.py`'s suspect-value/corroboration corrections, which is exactly
the gap this todo's authoritative-tier fix (a genuine `forward_returns` OOS-region population)
would close. The diagnostic result raises the practical importance of actually doing that:
if the authoritative re-run confirms the same direction, Phase 167's PASS verdict does not
survive, which is a milestone-level finding, not a minor correction.

## Cross-refs

- [todo 243](243-ctf-momentum-batch-join-lookahead-bias.md) -- the re-verification script this
  gap blocks; fix design above makes it self-sufficient once converted to on-the-fly returns.
- `docs/plans/OOS-EVAL-PROTOCOL.md` -- the governing document Gate 1/Gate 2 should have been
  folded into and wasn't.
- `scripts/ops/corpus/ops_oos_holdout_eval.py` -- the pattern to reuse (compute-on-read,
  `forward_log_return()`, no persisted-table dependency).
- `scripts/infrastructure/backfill/infrastructure_truncate_derived_tables.sh` -- confirms
  `forward_returns`/`construction_spreads` truncation is routine, expected corpus-rebuild
  behavior, not an anomaly.
