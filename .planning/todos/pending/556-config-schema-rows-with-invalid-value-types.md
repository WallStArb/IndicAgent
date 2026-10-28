---
status: pending
priority: P2
filed: 2026-10-28
source: found raising infra.backfill.fetch_concurrency; ConfigService.set refused it
---

# Ten config_schema rows carry a value_type the validator rejects

## What

`ConfigService.set` validates against `value_type` in `src/config/config_schema.py`, which knows
`int`, `float`, `bool`, `str`, `string` and `json`. Ten live keys carry `integer` or `text`, so
every `ConfigService.set` on them raises `Unknown value_type` and a change has to go in by direct
SQL, which skips the validation and the outbox:

- `integer`: `alpha.ic.min_obs_daily_features`, `alpha.selection.stepm.reps`,
  `alpha.selection.stepm.seed`, `infra.alpaca.nightly_deadline_minutes`,
  `infra.alpaca.nightly_max_requests`, `infra.alpaca.nightly_window_days`,
  `infra.alpaca.rate_limit_max_requests`;
- `text`: `infra.bar_derivation.daily_write_method`, `infra.bar_derivation.grid_write_method`,
  `infra.bar_derivation.rebuild_state_table`.

`infra.backfill.fetch_concurrency` had the same defect and was corrected by migration 531.

## Why not already done

Correcting the type changes what `ConfigService.get` returns (an int instead of the stored
string), and readers may rely on either. Read each key's readers first.

## Plan

1. For each key, list its readers; confirm each casts or accepts both forms.
2. One migration setting `integer` to `int` and `text` to `str`.
3. A schema test: every `config_schema.value_type` is one `validate_value` accepts.

## Done when

No `config_schema` row has a value type the validator rejects, and the schema test is green.
