# 122 - ic_engine checkpoint content-key doesn't cover APR config drift mid-run

**Found:** 2026-07-15, during /simplify review of the [todo 121](121-ic-engine-coarse-resume-no-checkpoint.md)
fix (`_checkpoint_content_key()` in services/ic_engine.py).

**Gap:** the content key hashes `.py` source bytes under `src/` and `services/` only. It has no
visibility into `ConfigService`/APR values read from `config_state` at runtime (`alpha.*`,
`infra.ic_engine.*`, etc. -- see CLAUDE.md's Adaptive Parameter Registry). If an operator changes
a routing-relevant APR key (e.g. a `regime_group` threshold, a clustering parameter) mid-run via
the `/config/parameters` dashboard, with zero Python file changes, a resumed checkpoint would be
silently treated as valid even though it was computed under stale config. This is the same class
of correctness risk the 2026-07-12 incident (that motivated checkpoint invalidation in the first
place) was about -- just triggered by config instead of code.

**Fix scope:** snapshot the specific APR keys `ic_engine` actually reads (its routing/clustering
config surface) into the checkpoint directory key or checkpoint payload itself, so a config change
mid-run invalidates in-flight checkpoints the same way a code change does. Needs to enumerate
which `ConfigService.get()` calls in `services/ic_engine.py` are routing/computation-affecting
(vs. purely operational, e.g. batch sizes) before deciding what to include in the fingerprint.

**Priority:** not yet triaged into PRIORITIES.md -- low urgency, no known incident yet (unlike
todo 121, which came from a real ~31h loss). Worth fixing before the next long ic_engine run if
an APR change is planned to land during that window.
