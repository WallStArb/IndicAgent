---
status: closed
priority: P3
filed: 2026-11-01
closed: 2026-11-01
source: data-layer redundancy audit (docs/plans/archive/2026-11-01-data-layer-redundancy-audit.md)
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

Closed 2026-11-01, one delete and one keep-with-note:

- Deleted: `ops_export_known_answer_fixtures.py`. Evidence: every file in tests/fixtures/bars is
  committed (clean status), the unit tests only read the frozen files
  (test_daily_rule, test_integrity_checks, test_scrub_rules, test_flag_parity among them), no test
  regenerates a fixture at test time, and the exporter's only other reference was its own
  raw-boundary allow-list row (removed). The README's "Regenerate with" section is replaced by the
  frozen note; the exporter lives in git history if a regeneration is ever genuinely needed.
- Kept with note: `ops_scrub_historical_pass.py`. 185-42-SUMMARY's rationale verified live: it is
  the only emitter of the `bar_scrub` / `historical_pass_complete` integrity fact, and
  `ops_data_bar_check`'s condition 1 (`scrub_pass_complete`, _SCRUB_MONITOR) reads that fact and
  takes its evidence timestamp from it; a fresh `--tf 1d --apply` is still required after any 1d
  revision. The emitter role is live, so the todo closes as keep-with-note, not delete.
