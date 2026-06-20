# Phase 124: Signal Universe Integrity + Cold-Start Hardening - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-06-14
**Phase:** 124-signal-universe-integrity-cold-start-hardening
**Areas discussed:** Plugin fix approach, CTF cold-start storage shape, Wave split & ordering, Fire-rate target & validation

---

## Plugin fix approach

| Option | Description | Selected |
|--------|-------------|----------|
| Hybrid (structural rewrite for the 3) | Edge detection for the 2 structural-event plugins; structural rewrite for the 3 continuous-score plugins | |
| Follow spec literally (D1-D5) | Onset guards, cooldown, rising-edge, threshold-crossing, departure+return as written | |
| Structural rewrite for all 5 | All 5 detection conditions rewritten; broad metric → context filter; trigger → structural event | ✓ |

**User's choice:** Structural rewrite for all 5, with the standing Renaissance-council directive (data integrity paramount, build a foundation each iteration refines, think like Renaissance senior engineers / Jim Simons).
**Notes:** The `i7-signal-quality-findings` memory explicitly warns against "an onset guard on top of a still-too-broad condition" because the raw signal universe IS the training data. Deduping a noisy population lowers count but leaves contamination. The spec's onset-guard/cooldown mechanics (D1, D2, D4) are superseded; the spec's edge/structural fixes (D3, D5) are retained and reinforced.

---

## CTF cold-start storage shape

| Option | Description | Selected |
|--------|-------------|----------|
| Promote to columns now | Migration promoting 4 CTF sub-scores to top-level nullable columns; backfill from JSONB; strip JSONB for single source of truth; IS NULL-only guard | ✓ |
| JSONB-bounded merge, no migration | ON CONFLICT DO UPDATE merges JSONB with per-key IS NULL guard; no schema change | |
| Defer cold-start fix to Phase 127 | Do plugin rewrites + warmup in 124; defer ON CONFLICT fix to 127 | |

**User's choice:** Promote to columns now — "pulling it forward if it's the long-term design/goal makes sense."
**Notes:** Scout found the spec's D8 SQL targets non-existent columns (only `cross_timeframe_context` JSONB exists). The roadmap success criterion (`WHERE ctf_score IS NULL`) presumes columns, so promoting aligns with intent. Renaissance refinement: single source of truth — strip CTF keys from JSONB after backfill to prevent drift. IS NULL-only guard (Phase 123 locked None-vs-0.0). Spec's file path is stale: `services/feature_writer.py`, not `src/intelligence/writers/`.

---

## Wave split & ordering

| Option | Description | Selected |
|--------|-------------|----------|
| Two waves: A deterministic, B behavioral | Wave A: migration + guard + reader migration + warmup (unit-test gated). Wave B: 5 plugin rewrites + D6 sanity. Authoritative validation deferred to 126. | ✓ |
| Single wave, everything together | All three tracks committed together | |
| Split into two phases (roadmap amend) | 124a mechanical, 124b behavioral | |

**User's choice:** Two waves — "1 is correct," with Renaissance-council directive.
**Notes:** DAG-clean — the three tracks are independent. Wave A first (deterministic foundation), Wave B after (behavioral, needs fire-rate iteration). 124 does NOT run a full replay; the whole point of the refactor is the replay runs once (Phase 126) over corrected everything.

---

## Fire-rate target & validation

| Option | Description | Selected |
|--------|-------------|----------|
| Diagnostic, not target | Fire-rate confirms structure is tight; 124 sanity = aggregate reduction + segmented no-hotspot; 126 authoritative = reference band or justification + edge | ✓ |
| <3% hard gate (spec literal) | Accept whatever lands under 3% | |
| 1% reference band hard gate in 124 | Iterate until all 5 at ~1% | |

**User's choice:** Diagnostic, not target — "1 seems right and maybe we can refine like Jim Simons would want."
**Notes:** Renaissance refinement: segment by regime. Aggregate fire-rate hides regime-specific noise (a 2% aggregate might be 8% in one regime). D6 SQL measures fire-rate by `setup_plugin × symbol × timeframe × regime`; no segment hotspot >~5%. Validation table in 124 is `signal_ledger.setup_plugin` (3-table migration is 127-129; researcher confirms `signal_events` not yet created).

---

## Claude's Discretion

- Exact migration number (confirm global max; beware 120/121 conflicts)
- JSONB null/missing-key/empty-string normalization during backfill
- Whether `--warmup`'s `skip_signals` path already exists in `run_historical_pipeline.py`
- Per-plugin structural trigger geometry within the D-02 mandates
- Commit sequence within each wave

## Deferred Ideas

- CounterfactualTracker daemon + I6 DB bootstrap at daemon startup (Phase 130, v2.11) — permanent live cold-start fix
- Full historical cold-start correction (pre-Phase-123 0.0 rows) — Phase 126 clean replay
- Authoritative fire-rate + edge validation — Phase 126
- 3-table signal schema — Phase 127-129
- APR parameter migration — Phase 125
