# PRIORITIES.md decision log

**What this is:** durable reasoning behind `.planning/todos/PRIORITIES.md` that isn't obvious
from the current tier list alone — active multi-step sequencing decisions, process rules learned
the hard way, and pointers to where folded/superseded content actually lives now. This is not a
full audit trail: closed-todo history, superseded diagnoses, and dated correction narratives with
no forward reference value were pruned 2026-07-14 rather than archived — once a fix has shipped
and the code/commit/completed-todo-file is the record, restating the debugging path here added
weight without adding usable information. Keep this doc itself lean on the same principle: add an
entry only if someone doing future work would actually need it.

---

## Process rules learned this project

**A "Gate:" line written once at filing time rots.** Anything sitting in `deferred/` more than
~2 weeks should have its gate re-checked against live state before being cited as still-blocked,
not trusted at face value (found via todo 020, which cited a gate that had already cleared).

**Never bake a live-progress snapshot (percent complete, symbol count, ETA) into a static
planning doc.** It goes stale within hours and is a recurring source of drift. State only
"in progress" or "complete as of DATE" — point at STATE.md or a live query for current progress.

## The locked sequencing chain — rationale

**Decision (2026-07-10, project owner confirmed; reaffirmed 2026-07-11 twice; full detail:
`docs/plans/2026-07-11-ic-quality-and-sign-symmetry-strategy.md`):** todos 093 → 091 → 097 → 094
→ [E1-vs-E2 A/B re-run] → 096 → 088 must run in this order, not in parallel or reordered by tier.

**Why:** 091, 097, and 094 all read or directly affect `ic_ci_lower`/`ic_ci_upper`, and 094
independently requires a full `ic_engine` re-run — sequencing 091 and 097 first means one corpus
re-run serves all three fixes instead of splitting across multiple, and 094's eligibility redesign
runs against the already-corrected CI and return-target measurement rather than the old one. 096
was inserted after 094 because its stride-bias finding (see below) directly informs 088's
censoring-vs-decay question. This chain is why 097 and 088 sit in P1/P2 tiers by effort despite
being just as blocking as the P0 rows — tier reflects independence/size, not exemption from order.

**096's fix, for reproducibility:** `_compute_ic_rolling_metrics` now uses a fixed subsampled-bar
window (`alpha.ic.sharpe_window_size_subsampled=100`, migration 230) instead of raw-bars÷stride,
removing a `sqrt(window_size_ratio)` deflation at long lookaheads. Threshold rescale shipped same
migration: `alpha.ensemble_ic.decay_threshold` 0.1→0.05, `alpha.ensemble.sharpe_floor` 0.05→0.025,
`alpha.feature_registry.min_ic_sharpe_default` 0.5→0.25. Verify: `python
scripts/analysis/ic_sharpe_stride_bias_check.py`.

**088 and 096 are separately-sequenced steps, not one item** — they were briefly merged in error
once (2026-07-12) and reverted; this is on record because it directly triggered Concept Registry's
build trigger (a governance gap letting distinct work get silently conflated).

## Standing diagnostics (re-run periodically, not one-time)

**Crowding proxy regression** (`scripts/analysis/crowding_proxy_regression.py`, todo 072):
baseline run against pre-143.1-fix `alpha_frames` found max R²=0.2674 at 1d/mid_bull, 0.003-0.09
at the primary 5m/15m strata — no crowding alarm at that baseline. Re-run each future corpus
epoch; see `docs/analysis/crowding-proxy-report.md` for the current number.

## Where folded content actually lives

**Concept Registry / Controlled Vocabulary / Stratification cluster (2026-07-13):** consolidated
from a scatter of 5 separate items (058, 105, 106, 076, 041) to exactly 3 top-level todos — 112
(Concept Registry), 110 (Controlled Vocabulary), 111 (Stratification & Classification). The
deferred/speculative content from 105, 106, 076, and 041 was folded directly into the design docs
they were forward-looking notes on, not kept as separate files:
- `concept-unified-registry.md` — regime_model domain seeding sequence (from 105/106)
- `stratification-dimension-unification.md` — new candidate dimensions + formalization revival
  note (from 076)
- `stratification-instrument-tag-calibrator.md` — tag taxonomy open question (from 041)

058 (Concept Registry MVP) stays in `completed/` as a frozen historical record only — it
duplicated 112's scope and was closed as a dedup, not because the work shipped (it hasn't).
