# 089 — ensemble_ic_engine recurring cadence

Source: Phase 142B Plan 02 (`CounterfactualTracker`), filed per D-10's follow-on requirement.

`CounterfactualTracker`'s IC-decay exit trigger reads the most-recent `alpha_ensemble_ic` row
for a frame's `(symbol, tf, regime)` cell regardless of its age (D-08 — no freshness gate
blocks the read). The age of that row is now instrumented via the
`counterfactual_tracker_ic_row_age_seconds` point gauge (D-10), so staleness is observable
instead of silent, per this project's "instrument everything" principle.

But no recurring `ensemble_ic_engine` schedule exists today — not even a disabled systemd
timer, the unit simply doesn't exist. `ensemble_ic_engine.py` currently only runs ad hoc,
invoked manually or inside the corpus pipeline script. This means the IC-decay trigger's
input can go arbitrarily stale between manual corpus runs.

**Explicitly out of scope for Phase 142B (D-09):** bundling a recurring cadence into this
phase would blur the 142A/142B measurement-instrument boundary — 142A owns signal IC and its
cadence, 142B owns frame outcome. A stale IC read degrades gracefully here: the early
IC-decay exit simply fires later than ideal; frames still close correctly via
stop/target/max_hold, so nothing produces a silently wrong P&L number. Not a correctness
emergency, but real latent staleness risk once `CounterfactualTracker` runs nightly against
live `alpha_frames`.

**Proposed fix:** establish a recurring `ensemble_ic_engine` systemd timer (weekly cadence
matches its own measurement design — see `services/ensemble_ic_engine.py`'s docstring),
registered in `service_auditor.py`'s `_DAG_ORDER`/`_ONESHOT_UNITS` alongside the other
Phase 138/139/142A/142B oneshots. Once live, consider whether
`counterfactual_tracker_ic_row_age_seconds` should feed an `alert.lag.*` APR-backed
threshold so `ServiceAuditor` can flag staleness the same way it flags consumer lag
elsewhere in the DAG.

Non-blocking future work; reference D-08/D-09/D-10 (142B-CONTEXT.md) and the
`counterfactual_tracker_ic_row_age_seconds` gauge (`src/observability/metrics.py`) as the
observability hook this todo would consume.
