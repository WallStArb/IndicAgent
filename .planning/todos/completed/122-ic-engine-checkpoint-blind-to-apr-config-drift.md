---
status: closed
moved_to_deferred: 2026-07-18
closed: 2026-07-23 — shipped via Phase 162-03
---

**CLOSED 2026-07-23 (Phase 162-03):** the fingerprint mechanism this todo asked for shipped, and
goes further than the original ask — every `ICEngineConfig` field (39 total) is partitioned into
`_COMPUTATIONAL_CONFIG_FIELDS`/`_OPERATIONAL_CONFIG_FIELDS`, exhaustively and disjointly (crash-loud
test if a future field lands in neither), and `_compute_apr_snapshot_key()` moves the fingerprint
only on a computational-field change. Mid-run APR drift now invalidates in-flight work the same
way a code change does. The old `.pkl` checkpoint system this todo was originally about
(`_checkpoint_dir`/`_load_checkpoint`/`_save_checkpoint`) was deleted outright, not patched --
cross-run fingerprinting + immediate per-symbol DB writes made it fully redundant.

**Moved to deferred/ 2026-07-18 (priorities/matrix reconciliation pass):** already self-deferred
in this file's own text to todo 134/ROADMAP **Phase 162** (plan 162-02 absorbs this fingerprint
gap as a special case of the general cross-run staleness check). Grouped with siblings
[133](133-cross-sectional-bootstrap-threads-not-per-tf.md) (162-01) and
[134](134-ic-engine-incremental-recompute.md) (162-02 core) for consistency — all three are
Phase 162 raw material, not independently pending/ items. Revive at `/gsd-plan-phase 162`, or
standalone if an APR-drift incident forces the issue first (per this file's own text below).

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

**Gate:** superseded in scope by [134](134-ic-engine-incremental-recompute.md) (2026-07-18) --
134's persisted code+APR fingerprint mechanism solves this cell's intra-run drift gap as a
special case of the general cross-run staleness check. Fix inline here only if an APR change
lands mid-run before 134's phase is discussed/planned; otherwise let 134 absorb it.
