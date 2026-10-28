---
status: closed
priority: P2
closed: 2026-10-28
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

## Closed 2026-10-28

Migration 532 sets the seven `integer` keys to `int` and the three `text` keys to `str`, applied live
and verified (zero rows with an unknown type; `validate_value` accepts the stored values).
Readers checked: the integer keys are cast with `int()` or unread (`alpha.ic.min_obs_daily_features`
has no reader); the write-method keys are read with `str()`; `rebuild_state_table` is a JSON
document read as a raw string and parsed by `ops_intraday_venue_recovery.py`, so it is `str`, not
`json`. The schema test is `tests/integration/test_config_schema_value_types.py`; it did not run
here because the integration replay fails at migration 526 on the stale test baseline (todo 495).
