---
status: pending
priority: P3
filed: 2026-11-01
source: data-layer redundancy audit (docs/plans/2026-11-01-data-layer-redundancy-audit.md)
---

# Confirm and delete the two completed one-shot passes

- `scripts/ops/bars/ops_export_known_answer_fixtures.py`: the known-answer fixtures it exports
  live in `tests/fixtures/bars/` (committed). Confirm the fixtures are frozen in git and the
  exporter has no other producer role, then delete; the fixtures' README references it, so
  update that README in the same commit.
- `scripts/ops/bars/ops_scrub_historical_pass.py`: the historical sweep ran (185-12:
  `--tf 15m --apply`, 124,197 flags, recorded). BUT 185-42-SUMMARY records a deliberate keep:
  "the only emitter of the bar scrub provenance signal". Verify what that emitter role is
  before deleting; if the emitter role is live, the todo closes as keep-with-note instead.

Done when: both scripts either deleted with their reference repairs, or closed as
keep-with-note citing the live role.
