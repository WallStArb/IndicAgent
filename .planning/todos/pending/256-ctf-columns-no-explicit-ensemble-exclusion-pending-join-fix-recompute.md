---
status: open
priority: P2
filed: 2026-08-05
source: verification pass on a cross-session finding about concept_registry eligibility
  freezing, checked against live ensemble_trainer meta-FDR logic before acting on it
---

# `ctf_momentum`/`ctf_vwap_align`/`ctf_regime_align` have no explicit ensemble-eligibility
# exclusion despite a known-leaked join (todo 243) -- currently excluded by luck, not design

## What

Todo 243 established `ctf_momentum`'s (and `ctf_vwap_align`/`ctf_regime_align`'s) batch-join
lookahead bug is real, unfixed in the live corpus (`feature_vectors` still holds pre-fix
values), and material (SPY 2026-01-05 15:00 UTC: stored +0.2321 vs corrected -0.1281, a sign
flip; Gate 1 flips PASS->FAIL under the corrected join in diagnostic-tier testing).

`ensemble_trainer.py`'s eligibility gate (`_eligibility_where`/`_meta_eligible`) has no
awareness of this. `concept_registry.status='active'` for `ctf_momentum` is unaffected by the
join bug's discovery, and `feature_status_at_eval` on already-computed `feature_ic_scores` rows
is a frozen snapshot that only syncs from `concept_registry` on a subsequent `ic_engine`
lifecycle-hook run (`_FEATURE_STATUS_REFRESH_SQL`, `ic_engine.py:1454`) -- not instantly, not
automatically on a bare registry UPDATE.

## Why this isn't urgent today (verified 2026-08-05)

Checked all three columns against live `feature_ic_scores` under the actual meta-FDR admission
logic (`_meta_eligible`, grouped per `(feature_name, tf)`, requires >=50% of that timeframe's
cells to individually pass BH-FDR with a per-tf minimum cell count):

| feature | result |
|---|---|
| `ctf_momentum` | 0/138 cells pass FDR (0%) -- fails on rate |
| `ctf_regime_align` | 1 qualifying cell per tf (15m/1d/1h) -- fails `min_cells` (2-3) in every stratum, excluded before rate is even evaluated |
| `ctf_vwap_align` | 0/2, 0/2, 2/7 by tf -- max 28.6%, fails on rate |

None currently clear admission. `max(computed_at)` across `feature_ic_scores` was 2026-07-30
21:08:59 UTC at filing time -- nothing had recomputed since, so that was the live state then.

**Update, 2026-08-07 (re-verified live, post-todo-230-resolution, post-CTF-join-fix)**: todo 230
resolved 2026-08-02 (steps 6-8 have run regularly since); the CTF join-fix recompute (option 3
below) landed 2026-08-05/07. Re-checked all three columns against the fresh, corrected-join
`feature_ic_scores` (3,640 cells each at 15m, up from 138 total across all tfs at filing time --
much larger post-universe-expansion cell count): `ctf_momentum` 0/3640 (0.0%), `ctf_regime_align`
4/3640 (0.1%), `ctf_vwap_align` 8/3640 (0.2%). **Still doesn't clear admission -- the risk this
todo names is confirmed still real and dormant, not resolved by the recompute landing.**

## Why it's still a real gap

This exclusion is an accident of these features currently being weak/sparse enough to fail
their own merits, not a designed safeguard tied to the known leak. Any future `ic_engine` run
(more accumulated history crossing a `min_cells` threshold, a regime-boundary shift) re-evaluates
this from scratch with zero memory of "this feature's current value is known-contaminated, hold
it out regardless of what the stats say." A feature that currently fails eligibility for
unrelated reasons could start passing on a later run before the join fix ever gets backfilled
into `feature_vectors`, and nothing in `ensemble_trainer.py` would refuse it.

**Correction, 2026-08-05**: the corrected-join recompute itself will NOT automatically produce
fresh IC values here either. Checked `ic_engine.py`'s staleness detection
(`_watermark_forward_returns_feature_vectors`, `ic_engine.py:980-994`): it fingerprints
`feature_vectors` by `MAX(bar_ts)` + `COUNT(*)` only, not a content hash. A surgical in-place
UPDATE to `ctf_momentum`/`ctf_vwap_align`/`ctf_regime_align` (the recompute plan's approach —
see its step 5b) changes neither, so `ic_engine` will keep treating those cells as valid
indefinitely unless explicitly run with `--refresh` scoped to the affected symbols/tf. This is a
required step in the recompute plan now, not an assumption to rely on separately.

## Fix options (not yet decided)

1. Explicit registry-level exclusion: deprecate `ctf_momentum`/`ctf_vwap_align`/`ctf_regime_align`
   in `concept_registry` now, forcing `feature_status_at_eval` to sync 'deprecated' on the next
   `ic_engine` run (via the existing status-only-stale refresh path) -- cheap, but only takes
   effect after that next run actually happens, and doesn't fix the underlying leaked values.
2. A query-level exclusion inside `ensemble_trainer.py`'s eligibility WHERE clause for named
   features pending a known data-integrity issue -- more invasive, adds a mechanism this
   codebase doesn't currently have (no existing "quarantine list" concept).
3. Just land the join-fix recompute (see
   `docs/plans/2026-08-05-ctf-join-fix-scoped-recompute-and-gate1-reverify.md`) -- makes the
   question moot rather than building a workaround for values known to be wrong.

**Update, 2026-08-07: option 3 landed** (recompute executed 2026-08-05/07) but did NOT make
the question moot as hoped -- the columns still fail to clear admission on the corrected data
(see update above), so the underlying architectural gap (no explicit exclusion mechanism tied
to the known leak, just accidental exclusion via merits) is still real and still open. Options
1/2 remain undecided; this todo stays open on that basis, not on option 3 being incomplete.

## Cross-refs

- [todo 243](../pending/243-ctf-momentum-batch-join-lookahead-bias.md) -- the underlying leak this todo is about not silently propagating
- todo 230 -- **CLOSED 2026-08-02** (was: the FATAL halt blocking steps 6-8; resolved same-day via a Binomial-tolerance fix, not a silent override -- see `project_single_security_alpha_refinement_gating_2026_08_08` memory for detail if ever needed)
- `docs/plans/2026-08-05-ctf-join-fix-scoped-recompute-and-gate1-reverify.md` -- the scoped recompute plan; executed, did not close this todo (see update above)
- `.planning/milestones/v3.1-phases/170-concept-registry-feature-domain-migration-feature-registry-r/170-05-SUMMARY.md` -- Plan 05 BLOCKED on the same empty `alpha_ensemble_ic` precondition (re-check if still relevant -- not verified in this pass)
