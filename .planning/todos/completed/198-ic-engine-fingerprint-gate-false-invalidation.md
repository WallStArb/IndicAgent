---
status: completed
priority: P0
filed: 2026-07-29
closed: 2026-07-29
source: live diagnostic during an equity-scoped ic_engine.py run (the run todo 167 needs) —
  a routine restart to pick up todo 182's fix triggered a full, unexpected per-symbol +
  cross-sectional recompute despite the fingerprint/resume mechanism's "a killed run simply
  resumes by re-running" design promise
---

## Resolution (2026-07-29)

Two related false-invalidation bugs found and fixed in `services/ic_engine.py`'s whole-cell
fingerprint gate (Phase 162-03), plus a regression caught by peer review during the fix
itself. Full TDD throughout (every new function RED before GREEN), 4-agent `/simplify` pass,
peer code review pass, all `pytest tests/unit/`/`ruff`/`black` clean. Shipped in commit
`02cabb06`.

**1. Raw-byte content hashing invalidated on non-semantic edits.** `_checkpoint_content_key()`
hashed raw file bytes across ~30 transitively-imported first-party modules. A comment or
docstring reword to any of them moved the hash exactly as much as a real logic change, forcing
a full multi-day recompute for zero output change — proven against a real commit in this
repo's own history (`ca4ef569`, a pure comment reword). Fixed: hash AST-normalized source
(`_normalized_source_for_hash`) with docstrings blanked; comments were already outside the
AST. Verified against 9 adversarial source pairs (nested/async/class docstrings, lambdas,
f-strings, second string statements) during peer review — no false-collision risk found.

**2. A `feature_registry.status_hash` change invalidated everything, even though status never
gates what gets computed.** Verified directly against the code (`get_all_features()`, never
`get_active_features()`) — every feature is bootstrap-CI'd regardless of status; status only
feeds the `feature_status_at_eval` provenance column. Fixed: `_classify_fingerprint` now
returns a third state, `"status_only_stale"` — skip the expensive compute, refresh just that
column via a cheap targeted `UPDATE ... FROM feature_registry` (`_FEATURE_STATUS_REFRESH_SQL`).
One shared classification function, called identically by both the per-symbol and
cross-sectional prepass loops, so the two passes cannot diverge in what counts as which.

**3. (Caught in peer review, before merge) A symbol with both a genuinely invalid cell and an
unrelated status-only-stale sibling cell (different `tf`) silently never got the sibling
refreshed.** The original wiring bucketed a symbol as EITHER dispatched OR needing a status
refresh via a single `elif` — never both. The dispatched worker's redundant recompute of the
fingerprint-valid sibling hits `feature_ic_scores`' `ON CONFLICT ... DO NOTHING`
(deliberately harmless pre-fix, since a recomputed fingerprint-valid row was always
byte-identical to what's already there — no longer true once status can differ), silently
discarding the fresh status, while the post-compute fingerprint upsert (which stamps ALL of a
dispatched symbol's cells fresh, unconditionally) then marked it valid anyway. Permanent,
silent, undetectable-on-any-future-run drift — the exact "silent wrong answer" failure mode
this project treats as worse than a loud crash. Fixed: `_partition_symbol_cells` tracks
dispatch-eligibility and refresh-eligibility as two independent sets, not an either/or bucket.

**Why this mattered right now, not just in the abstract:** this bug class is exactly what cost
two consecutive restarts of the equity-scoped run this session (~26h and ~4h respectively) —
each one threw away already-committed per-symbol work rather than resuming cheaply. Root cause
of THOSE two specific incidents was traced but not fully pinned to a single file/commit (code
and `feature_registry.status_hash` both genuinely differed between runs); this fix closes the
general mechanism regardless of which specific edit triggered it.

## Not done here

- `_fingerprint_computational_key`'s exclusion of `feature_registry` is safe only because a
  separate registry-alignment gate (`main()`, "Feature registry alignment gate") forces
  membership to equal `FeatureVector`'s fields exactly — documented at both ends as a
  load-bearing coupling (peer review finding, confidence 80), not resolved into a structural
  guarantee. If that gate is ever relaxed, this needs revisiting.
- The equity-scoped `ic_engine.py` run itself (needed to close todo 167) was stopped, not
  relaunched, pending this fix — not yet rerun as of this todo's closure.
