---
status: pending
priority: P3
filed: 2026-08-03
source: altitude review (/simplify) of todo 241's ctf_momentum live/batch fix
---

## What

`_CTF_HIGHER_TF` (`src/intelligence/feature_cache.py`, moved there by todo 241 as the single
shared source of truth for both `backfill_feature_factory.py`'s batch path and
`feature_vector_pipeline.py`'s live path) is a hardcoded module-level dict:

```python
_CTF_HIGHER_TF: dict[str, str] = {"5m": "1h", "15m": "1h", "1h": "1d", "1d": "1d"}
```

This is a "behavioral list" under CLAUDE.md's APR mandate category 2 -- "lists controlling
WHAT the algorithm processes" -- exactly the category the mandate says must be APR-governed
JSON (`json.loads(cfg.get_sync(key, default_json))`), not a hardcoded constant. It sits right
next to `rsi_mid_period`, which already IS APR-backed (`feature.period.rsi.mid`) via
`FeatureFactoryConfig`.

Pre-existing debt, not introduced by todo 241 -- it was already a hardcoded dict in
`backfill_feature_factory.py` before that fix; todo 241 centralized it (better traceability,
single definition instead of an implicit duplicate) but didn't change its APR status. Flagged
by the altitude-angle review agent during todo 241's `/simplify` pass.

## Why not fixed in the same session

Migrating this properly means more than adding a migration + APR key:
`feature_vector_pipeline.py`'s `_CTF_LOWER_TFS` (the inverse mapping) is currently derived at
**module import time**, before any DB/ConfigService connection exists -- APR values are only
available after `_setup()` runs. Making the mapping APR-governed means moving `_CTF_LOWER_TFS`'s
derivation from module scope into instance state built during `_setup()`/
`_prewarm_threshold_config()`, matching the pattern CLAUDE.md documents for other threshold
config (`_config_service: Any | None = None` + `set_config_service()` + `get_sync()` wrapper,
registered in `_prewarm_threshold_config()`). Real, scoped refactor -- not a drive-by addition
to a bugfix PR.

Also low urgency in practice: the mapping's values are tied to this project's fixed tf ladder
(5m/15m/1h/1d), stable since the corpus's inception and not something that's been reconsidered
independent of a much bigger change (e.g. adding a weekly timeframe, which todo 189 already
notes isn't in the corpus and isn't being pursued speculatively).

## Next step

Migration: add `feature.ctf.higher_tf_map` (JSON, default `{"5m":"1h","15m":"1h","1h":"1d","1d":"1d"}`)
to `config_schema`/`config_state`. Load in both `backfill_feature_factory.py` (already threads
`ConfigService` through) and `feature_vector_pipeline.py` (move `_CTF_LOWER_TFS` construction
into `_setup()`, store as instance state, derive the inverse mapping from the loaded dict same
as today). Remove the hardcoded module-level `_CTF_HIGHER_TF` constant once both call sites
read from APR.
