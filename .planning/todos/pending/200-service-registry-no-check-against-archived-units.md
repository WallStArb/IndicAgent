---
status: pending
priority: P2
filed: 2026-07-27
source: /simplify altitude review of the feature_vector_writer deploy fix
---

# service_auditor.py's registry has no check against pointing at archived/nonexistent units -- same collision has now happened twice

## What

`services/service_auditor.py`'s `_AGENT_ID_TO_UNIT`/`_DAG_ORDER` dicts are hand-maintained
literal string tables with no structural check that a value actually corresponds to a live,
non-archived systemd unit. This just caused a real ~18-day silent outage: `feature_vector_writer`
was mapped to `indicagent-feature-writer`, the archived v2.x unit (confirmed dead, `ExecStart`
points at `services/feature_writer.py`, which doesn't exist on disk) -- so the auditor was
monitoring a unit that was *supposed* to be dead and never alerted that the real v3.0
`FeatureVectorWriter` had no systemd unit deployed at all.

**This is not the first occurrence.** `tests/unit/services/test_service_auditor.py`'s
`test_agent_id_to_unit_feature_writer_key` docstring says the dict *key* was already renamed
once before, in Phase 138-P0 (`feature_writer` -> `feature_vector_writer`) -- but that rename
only fixed the key, not the value, leaving the mapping pointed at the wrong unit ever since.
This todo's fix (2026-07-27) is the second pass at the same collision, and the same session
also found the fix's own first draft missed 2 systemd files (`wave4.target`'s `After=`,
`llm-writer.service`'s `Wants=`) and 4 test assertions still hardcoding the old string --
caught only by a follow-up `/simplify` review, not by any structural check.

## Why this matters

CLAUDE.md's "Migrate-as-you-go" and "File/class renames require test sweep" gotchas exist for
exactly this failure mode, but a grep sweep is manual and was skipped twice. A cheap automated
check would catch it the moment it's introduced instead of after weeks of silent data staleness.

## Proposed fix

Extend the existing boundary-test pattern this project already uses elsewhere
(`tests/unit/test_market_data_ohlcv_boundary.py`'s allow-list-with-reason pattern) into a new
`tests/unit/services/test_service_auditor_registry_integrity.py` that asserts:

1. Every `_AGENT_ID_TO_UNIT` value and every `_DAG_ORDER` key corresponds to a `.service`/
   `.target` file that actually exists under `production/systemd/`.
2. None of those values match a small deny-list of confirmed-archived unit names (the v2.x
   units CLAUDE.md's Architecture section already flags: `indicagent-feature-writer`,
   `indicagent-intelligence-pipeline`, etc.) -- so pointing a v3.0 agent_id at a known-archived
   unit fails the test immediately instead of silently degrading.

Out of scope for this todo (bigger, separate): a deploy-time/CI check that every `services/*.py`
class actually has a corresponding systemd unit file at all (the root cause of THIS specific
incident -- the class existed, fully built, with no unit ever created). Worth its own todo if
this one's fix doesn't already surface it.
