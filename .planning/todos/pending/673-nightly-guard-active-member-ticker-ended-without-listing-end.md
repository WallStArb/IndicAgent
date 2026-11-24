---
status: pending
priority: P2
filed: 2026-11-24
source: indicagent-fb, BKH data gate refusal (corpus pilot 7c5612f0, step data_gate), lead brief 2026-11-24
---

# Nightly guard: an active member whose newest 1d bar is stale and has no listing end

## What

A name whose ticker ends (a merger, a rename, a delisting) stays active and in the universe. Until someone records a
`listing_end` row (migration only, append-only) the 1d verdict judges it to the last completed session. The trailing
unanswered sessions pass quietly until session coverage over the proven span drops under the floor, then
`proven_start_1d` turns false and the corpus data gate refuses the name. BKH: bars end 2026-11-13, coverage passed with 5
trailing sessions missing (0.99914) and failed with 6 (0.99897), so the refusal arrived 6 sessions after the ticker ended,
at the worst time (the pilot). `freshness_1d` was red for the name the whole week and nothing acted on it.

## Facts checked 2026-11-24 (indicagent-94, read only)

- The check largely exists. `integrity_checks.freshness_1d` (`src/intelligence/bars/integrity_checks.py:393`) counts the NYSE sessions after a name's latest canonical 1d bar, up to the last completed session, and fails it above APR `threshold.bar_integrity.freshness_max_lag_sessions_1d` (default 2, migration 455). A name with a recorded `listing_end_current` row is judged only to its last session; one without is judged to the last completed session, which is exactly the BKH case. The nightly D7 audit (`services/bar_reconciliation_audit.py`) records the count as the gauge `bar_integrity_failing_names{check="freshness_1d"}` (`record_alert_gauges`, line 1147), and Grafana rule `bar_freshness_1d` (`production/grafana/provisioning/alerting/alert-rules.yml:347`) fires on any value above 0, severity high, contact point `discord-ops`.
- So BKH was red from session 3 (2 allowed) and the data gate refused it at session 6. Nothing acted because (a) the gauge carries a count, never the names, (b) the rule does not separate "ended with no `listing_end`" (an action: record it) from "feed late" (wait), and (c) no receiver delivers: `docs/development/alerting.md:138` records that the Alertmanager default receiver is a no-op and the Grafana contact points hold placeholder webhooks.
- The threshold of 3 sessions in the original text is a second copy of an existing key. Reuse `threshold.bar_integrity.freshness_max_lag_sessions_1d` (2): one source of truth, and it fires three sessions before the data gate's coverage floor did for BKH.

## Spec (design only; implementer follows this)

Do not add a new service, check or APR key. Extend the D7 audit's report of the verdicts it already has:
1. In `services/bar_reconciliation_audit.py`, after the freshness verdicts are judged, build the list of failing `freshness_1d` names that are active members of `universe_membership` (latest `as_of`) and have no `listing_end_current` row, each with its latest bar date and sessions behind. Log it as one structured line (`stale_member_without_listing_end`, count, names capped at 50, the rest as a count) and write it to the audit's existing JSON report so a person can read the names.
2. Emit one extra gauge point, `bar_integrity_failing_names{check="freshness_1d_unlisted"}`, the count of that list (0 recorded when empty, so an alert resolves), through the same `record_alert_gauges` path. A second Grafana rule copies `bar_freshness_1d` for the new label with a description that says the action: "record a `listing_end` row (migration, evidence from the exchange notice) or confirm the feed is late". The existing rule stays.
3. Read-only: it never writes `listing_end` or any table (listing ends are recorded by migration with evidence, never inferred). It does not change a verdict or any threshold, so `freshness_1d`'s pass or fail for every name is unchanged.

Landing: the audit module is timer-run (`indicagent-bar-reconciliation-audit.timer`, 01:00 EST; a blocking timer of the corpus rerun) and not in the rebuild writer's import closure as far as the grep shows (it is not imported by `backfill_feature_factory` or `rebuild_preconditions`; `integrity_checks` is, listed as an unhashed import for `INFO_PROVEN_START` only). This spec edits no function in `integrity_checks.py` or `verdict_gate.py`. Gate anyway: print `rebuild_code_key()` before and after the edit (`services/backfill_feature_factory.py:1492`) and land only if equal, in a detached worktree off `origin/main`, while no corpus run is live. If the key moves, the todo waits for the corpus run to finish.

Tests: a unit test on the pure selection function (failing freshness verdict, member, no listing end -> listed; same name with a `listing_end` -> not listed; a non-member -> not listed; a name at the threshold -> not listed; empty -> count 0 and the gauge records 0); the log line carries names and sessions behind; the full audit unit suite passes; `tests/unit/test_metric_refs` style test finds the new label in the Grafana rule.

Cost and failure modes: one list over names already judged, no extra query beyond the universe membership read the audit already makes (confirm when building); the main risk is noise, a feed outage listing hundreds of names (the cap and the count line handle it; the alert's action text says to check the feed first); delivery stays the owner's step (placeholder contact points), so the new rule helps only once a receiver is wired (`docs/development/alerting.md`).

## Done when

The D7 audit logs and gauges, per night, the active members that fail `freshness_1d` with no `listing_end` row, with names and sessions behind; a Grafana rule names the action; `rebuild_code_key()` is unchanged by the edit; the tests above pass. Land after the corpus run is quiet.
