---
status: pending
priority: P3
filed: 2026-07-30
source: final-review re-review of docs/superpowers/plans/2026-07-30-per-tf-active-scale-set.md
---

# `corpus_manifest_verifier.py`'s `_load_apr_values` treats an explicit empty
# active-scale list the same as an absent key -- inconsistent with the Ring 2 path

## Problem

`src/observability/corpus_manifest_verifier.py:111`: `active_scales_by_tf[tf] =
tuple(parsed) if parsed else default_scales` -- an operator configuring
`alpha.ic.active_scales.{tf} = []` (a deliberate "no scales active" state) is silently
treated identically to the key being absent, and falls back to the tf's full default
scale set instead of a genuinely empty active set. This is inconsistent with
`services/_batch_utils.py`'s `canonicalize_active_scales([])`, which correctly returns
a genuinely empty tuple (verified directly: `canonicalize_active_scales([]) == ()`).

Found during the per-tf active-scale-set plan's final-review fix-round re-review,
correctly flagged as out of scope for that fix (a Ring-0-file quirk, not the finding
under verification) rather than silently patched.

## Fix

Change the truthy check to an explicit `is not None` / absence check, matching
`canonicalize_active_scales`'s semantics: distinguish "key absent -> use default" from
"key present but configured empty -> genuinely empty active set".

## Sizing

Trivial, single-line, low urgency -- no live tf is currently configured to `[]`; this
is a defense against a future misconfiguration matching an existing inconsistency, not
an active bug.

## References

- `src/observability/corpus_manifest_verifier.py:111`
- `services/_batch_utils.py`'s `canonicalize_active_scales` -- the Ring 2 path this
  should match semantics with
- `docs/superpowers/plans/2026-07-30-per-tf-active-scale-set.md` -- the plan whose final
  review surfaced this
