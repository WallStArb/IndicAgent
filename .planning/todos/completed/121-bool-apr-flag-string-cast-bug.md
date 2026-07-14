---
status: completed
priority: P0
filed: 2026-07-14
resolved: 2026-07-14
source: found while wiring alpha_publisher.py for todo 011 (alpha_events.is_shadow)
---

# `services/_batch_utils.py::cfg()` silently inverted every falsy bool APR flag —
# live in `alpha.ensemble.sign_symmetric`, about to recur in `alpha.publisher.is_shadow`

## Problem

`cfg(cfg_dict, key, default)` cast the raw (always-TEXT) `config_value` via
`type(default)(val)`. For a `bool` default this is `bool(val)` — and in Python,
`bool("false")` is `True`, since any non-empty string is truthy. Any bool-typed APR
flag stored as the literal string `'false'` was silently read back as `True`.

**Confirmed live impact:** `alpha.ensemble.sign_symmetric` (migration 224, Component E /
todo 094) is stored `'false'` in `config_state` — intentionally, per the migration's own
comment: "Plan 07's mainline champion (flag OFF)". `ensemble_trainer.py`'s
`EnsembleConfig.from_apr()` read it via `bool(_cfg(cfg, "alpha.ensemble.sign_symmetric",
False))` = `bool("false")` = `True`. The corpus rebuild that was in progress at the time
this was found (Phase 143.1-07, started 2026-07-14T09:08 UTC, `--from-step 5`) invokes
`ensemble_trainer.py` at Step 7 with no `--sign-symmetric` CLI override
(`scripts/ops/corpus/ops_corpus_pipeline_run.sh`), so it would have silently run with
sign-symmetric eligibility ON instead of the intended OFF — mixing up the champion
(Plan 07, flag OFF) and challenger (Plan 08, flag ON) behavior in the exact run meant to
establish the champion baseline, with no error, warning, or visible symptom. Caught
before Step 7 ran (pipeline was still mid-`ic_engine.py`, Step 4).

Would have recurred in `alpha_publisher.py`'s `is_shadow` flag, currently being wired for
todo 011: an operator flipping `alpha.publisher.is_shadow` to `'false'` at Phase 144
promotion — the one-way live-promotion switch todo 011 exists to build — would have had
no effect, since `bool("false")` still evaluates `True`. The switch would silently never
promote to live no matter what the operator set it to.

## Fix

`cfg()` now special-cases `bool` defaults: `str(val).strip().lower() == "true"`, matching
the pattern `ic_engine.py`'s `ConfigService.get_sync()` path already uses correctly for
`alpha.regime.equity_model_enabled`. Fixed once in the shared helper (all 5 callers of
`services._batch_utils.cfg`/`_cfg` inherit the fix) rather than patched at each of the 2
call sites that happened to pass a bool default — the project has explicit prior history
of the same bug class recurring at a second call site after being fixed only at the
first (`alpha_events` full-replace gap, see `alpha_publisher.py`'s own inline comment).

`ensemble_trainer.py`'s redundant `bool(...)` wrapper around `_cfg(...)` removed (now a
no-op given `cfg()` already returns a real bool). Regression tests added to
`tests/unit/test_batch_utils.py` (`TestCfg`: false-string, true-string, absent-key,
case/whitespace) and `tests/unit/test_alpha_publisher.py` (`TestIsShadow`: full
execute()-path coverage of the false-string promotion case, plus the DB-tuple write
path). Full unit suite green.

## Resolution

Commit alongside todo 011's `alpha_publisher.py` wiring, 2026-07-14. No config_state
value changed — `alpha.ensemble.sign_symmetric` was already correctly `'false'`; only the
code that misread it changed.
