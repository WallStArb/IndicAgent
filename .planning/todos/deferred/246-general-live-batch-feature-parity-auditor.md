---
status: pending
priority: P2
filed: 2026-08-03
source: user question ("should we build this into a real live/batch daemon/process?") during
  the todo 243/245 ctf_momentum investigation -- checked for existing infrastructure before
  answering, found the pattern is real and recurring but nothing systematic catches it
---

# No general live-vs-batch feature-value parity check exists -- three incidents found it ad hoc, each leaves a manual "re-check when ingestion resumes" note

## What

Three separate incidents this project has now hit the same underlying gap:

- [todo 221](../completed/221-live-vix-z-flight-quality-yield-slope-z-permanently-zero.md)
  (`vix_z`/`flight_quality`/`yield_slope_z` permanently zero in live serving) -- fixed, but its
  own closing note says "**Not verified against live Kafka/IBKR** -- live ingestion is
  intentionally stopped... re-confirm with a live or replayed tick once ingestion resumes, per
  this todo's own note about resurfacing then."
- [todo 241](../completed/241-ctf-momentum-live-batch-compute-divergence.md) (`ctf_momentum` live serving
  computed a different statistic than batch) -- fixed, explicitly cites 221 as precedent for the
  same bug *class*, not just a coincidence.
- [todo 243](../pending/243-ctf-momentum-batch-join-lookahead-bias.md) (batch's own HTF join has
  real lookahead) -- found reviewing 241's fix, still open.

Each was discovered by someone asking a question or reviewing a specific fix, not by any
systematic check. Each fix's own regression test (`test_ctf_momentum_live_batch_parity.py`,
`test_feature_vector_pipeline_cross_asset.py`) only proves two CODE PATHS agree given synthetic
fixture inputs -- none of them touch real production data, so none could have caught (or can
confirm the fix of) an actual live-vs-batch divergence on real bars. Checked before filing this:
`services/feature_parity_auditor.py` sounds like it should be this, but isn't -- it's dead v2.x
code (not deployed, no systemd unit exists) checking `intelligence_features.pattern_detections`
for three unrelated I5-pattern fields, an entirely different, archived table.

## Why not build it now

Live IBKR ingestion is intentionally stopped (`project_ingestion_intentionally_paused` memory) --
there is currently zero live-computed `feature_vectors` data being produced, so a live-vs-batch
comparison daemon would have nothing to compare against. Building this now would be exactly the
"accelerate before the requirement is real" mistake CLAUDE.md's Musk-5-step process exists to
prevent. This belongs in `deferred/`, not `pending/`.

## Fix, when ingestion resumes

A single, general daemon (shaped like the existing `*_auditor.py` services) that, on a schedule:
1. For a sample of recent (symbol, tf, bar_ts) rows, re-derives what batch/backfill would have
   computed for the SAME bars (using the same code path `backfill_feature_factory.py` uses) and
   compares against what live serving actually wrote to `feature_vectors`.
2. Flags any column whose live-vs-batch delta exceeds a tolerance, per-column, via the same OTel
   gauge pattern every other auditor in this codebase already uses.
3. Replaces the current pattern of scattered, per-incident, manually-remembered "re-check this
   one field when ingestion resumes" notes (221, 241, and whatever the next one turns out to be)
   with one mechanism that would have caught todo 221's original bug, todo 241's original bug,
   and any future recurrence of the same class, automatically.

## Cross-refs

- [todo 221](../completed/221-live-vix-z-flight-quality-yield-slope-z-permanently-zero.md),
  [todo 241](../completed/241-ctf-momentum-live-batch-compute-divergence.md) -- the two precedent incidents
- `project_ingestion_intentionally_paused` (memory) -- why this is deferred, not pending
