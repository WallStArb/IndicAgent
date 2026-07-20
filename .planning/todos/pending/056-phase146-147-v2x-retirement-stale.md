**Operator call made 2026-07-19: archive v2.x (not delete), decouple decommission from Phase 148's
proof gates (execute independently, not gated behind it).** ROADMAP.md's Phase 147/148 sections
rewritten same day per the sketch below (147 collapsed to one-wave CORPUS-07 evaluation, 148's
Depends-on/SCORE-04/05 reframed). Remaining scope on **this** todo is now just the actual
decommission-in-fact execution, tracked below — not blocked on anything, ready whenever picked up:

**Correction 2026-07-19 — checked actual state before writing this plan, it's more done than
expected:** `src/intelligence/archive/` already exists (`i5_patterns/`, `smc_context/`,
`confluence/`) and `register_plugins.py` already imports I5 (patterns) and I6 (SMC/confluence)
entirely from there — that slice of the "archive the plugin tree" work is done, not remaining
scope. What's actually still live: `src/intelligence/trading/` (I7, ~54 files: both plugins and
the shared utilities `src/intelligence/CLAUDE.md` documents as load-bearing —
`plugin_utils.py`/`signal_schema.py`/`trade_framer.py`/`lifecycle_tracker.py` etc.).
`archive/trading_i7/` also already exists with a near-identical 48-file listing — looks like a
copy taken at some point, not a completed `git mv` cutover (register_plugins.py still imports
`volume_zscore` live from `src.intelligence.trading`, not from the archive copy). This needs a
real diff between `trading/` and `archive/trading_i7/` before touching anything — determine
whether the archive copy is current, stale, or was a false start, and untangle which files in
live `trading/` are genuinely dead plugins vs. still-referenced shared utilities before any
`git mv`. Do not treat this as a fresh archival task; treat it as *finishing* an already-started,
partially-abandoned one.

**Remaining action items (revised):**
1. Diff `src/intelligence/trading/` against `src/intelligence/archive/trading_i7/` to establish
   ground truth on what's already covered vs. still needs moving.
2. Complete the I7 plugin cutover to archive (or confirm the existing archive copy is current and
   just needs `register_plugins.py`'s imports switched over + the live copies deleted).
3. Disable (not just leave failed) `indicagent-intelligence-pipeline.service` and
   `indicagent-feature-writer.service` — both already dead, but explicit disable/mask documents
   intent instead of leaving an ambiguous "failed" state.
4. Archive (rename with a legacy prefix, do not `DROP`) `signal_events`, `trade_frames`,
   `trade_executions`, `signal_ledger` (the view) — frozen since 2026-06-22, but rename preserves
   the data untouched in case of dispute or later reference.
5. Update CLAUDE.md's Architecture section once done to describe an actually-archived system
   (path, not just "failed" status).

**Sizing:** smaller than it first looked (most of I5/I6 already archived) but item 1-2 (untangling
a partially-completed, possibly-abandoned prior cutover attempt) needs real investigation before
any file is moved or deleted — don't assume the live `trading/` copy is safe to delete without
confirming the archive copy is actually a faithful, current superset first.

---

# Phase 147 gate dangles on unrun work; Phase 148's v2.x retirement half describes retiring an already-dead system

**Filename says "146/147"; current numbers are 147/148** (I7 Alpha Scorer Transition / Alpha
Scoring System + v2.x Retirement Gate) — filename kept as-is per this repo's no-rename
convention, body below uses current numbers throughout.

**Found:** 2026-07-03, via ROADMAP reconciliation pass (`.planning/research/2026-07-03-roadmap-reconciliation.md`, finding F3).

Three compounding problems, not yet fixed in ROADMAP.md (deliberately left for an operator call
first — see below):

1. **Phase 147's conditional gate cites CORPUS-07, which was never run.** Phase 141 is
   ✅ COMPLETE with requirements CORPUS-01..06 — no CORPUS-07 anywhere in its actual requirement
   list. The only trace of "CORPUS-07" is a next-steps recommendation (item 7) in
   `docs/analysis/ic-validation-report-58sym.md`. As written, 147's gate can never fire.
2. **Topdown D7 already pre-committed the outcome the gate was waiting for:** "Phase 147
   collapses to retirement-by-default now... rare survivors become predictors via D1 — no
   adapter contract, no `alpha.i7.mixing_weight_*` keys, no I7-03 ensemble ingestion path." The
   ROADMAP's 147 still specs the full I7-01..05 conversion apparatus (3 plan waves, mixing-weight
   APR keys, an `alpha_score` column on `signal_events`) that D7 already ruled unnecessary.
3. **v2.x is dead in fact, not merely deprecated** (bottomup audit §1.1/§5.1): `intelligence-pipeline.service`
   failed with `ExecStart` pointing at a deleted file, the I7 signal topic has had no producer
   since the D-09 cutover, `signal_events`/`trade_frames` frozen at 1,601 rows since 2026-06-22,
   CLAUDE.md itself marks the whole tier ARCHIVED. Phase 148's SCORE-04 (v3 vs v2.x counterfactual
   comparison "on the same symbols/period") has no comparable v2.x data population and never will;
   SCORE-05's retirement procedure describes disabling a systemd unit that's already failed-dead.

**Concrete fix sketched in the reconciliation doc (F3, not yet applied):**
- Phase 147 collapses to one wave: run the CORPUS-07 plugin-capture analysis itself as this
  phase's first deliverable; default outcome is retirement per D7; any survivor registers as an
  ordinary predictor (feature-grain, measured by `ic_engine`, per intel-15's grain rule) — delete
  I7-02/03/04 as requirements.
- Phase 148: change Depends-on from `i7_conversion_complete = 1` to "Phase 147's CORPUS-07
  evaluation complete." Reframe SCORE-04 as a documentation note (why no comparison population
  exists) or delete it. Reframe SCORE-05 from "retirement" to "decommission-in-fact" (unit
  removal, table archival, doc cleanup). The two-gate *promotion* half (SCORE-01/02/03) is
  unchanged and remains the real milestone exit — this only shrinks the retirement half.

**Blocked on an operator call, deliberately not decided unilaterally** (bottomup Open Q1):
**archive v2.x cleanly vs. delete outright**, and whether the SCORE-05 decommission checklist
should execute *before* Phase 148 (cheap cleanup, independent of the v3 proof gate) rather than
gated behind it as currently structured. Conflating "prove v3" with "bury the v2.x corpse" holds
free cleanup hostage to a statistical gate it doesn't need.

**Action:** get the operator call above, then rewrite Phase 147/148 per the sketch. Not urgent
in the sense that nothing breaks today, but 147 currently can't ever pass its own gate as
written — worth fixing before either phase is planned.
