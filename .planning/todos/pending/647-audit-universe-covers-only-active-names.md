---
status: pending
priority: P2
filed: 2026-11-19
source: lane 2 of the 609 chain, report of indicagent-0a
owner: lead
---

# The reconciliation audit and the daily derivation see only is_active names

## What

`bar_reconciliation_audit` (universe: the `backfill` dimension, `is_active = true`) and the daily derivation timer (`_DISCOVER_DAILY_SYMBOLS_SQL`, the same dimension) never visit the 33,850 inactive instruments added by the stage 2 install, so after the one explicit derivation run nothing audits or refreshes them. The audit took 6,982 s for 1,529 names, so naively widening it does not finish in a night.

## Done when

A decision and a build: a cheaper audit tier for the stage 2 names (counts, session coverage, split continuity on the membership span only) or a sampled audit with a recorded rate, and a derivation path for their later vendor restatements. Until then a recorded caveat says the dead-name history is derived once and unaudited.

## Decision (lead session e8, 2026-11-20; lead ruling: a gate before counted compute)

Requirement questioned (Musk step 1): the stage 2 dead names are in compute (that is the survivorship fix), so their history must be audited before any counted test; what is deleted is the nightly repeat. A dead name's bars are static: the Massive archive ended 2026-11-16 and nothing re-serves a delisted name, so a nightly audit or derivation of 33,850 names re-proves unchanged data (the audit took 6,982 s for 1,529 names).

1. Nightly timers keep the active universe. No widening.
2. One-shot gate `scripts/ops/bars/ops_member_history_audit.py` (read-only, over every distinct `universe_membership` symbol, active or not), pure checks in `src/intelligence/bars/member_history.py`. Zero-tolerance structural checks fail the gate (exit 1): a member with no canonical 1d bar; an OHLC invariant or non-positive price in canonical 1d; a canonical bar outside the instrument's data span; split currency (a `corporate_action` recorded after the name's newest 1d digest, the same rule as `universe_membership_writer._STALE_SPLITS_SQL`). Session coverage over the membership span is measured per name and disclosed next to the same measure over the active names; it is not a pass/fail gate (a calibrated threshold needs the measured distribution first).
3. Restatement path: no timer. A dead name is re-derived by an explicit scoped `bar_derivation` run, triggered by recorded split rows (todo 646) or a daily-rule version change; the gate's split-currency check is the staleness detector, so a stale member fails the gate until re-derived.
4. After todo 645 lands, `universe_membership_writer` should import the shared staleness SQL from the new module instead of its private copy (not edited now: 645 lane).

Caveat until the gate has run: the dead-name history is derived once and unaudited.
