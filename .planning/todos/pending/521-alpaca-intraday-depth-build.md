---
status: pending
priority: P1
filed: 2026-10-09
source: Alpaca integration pilot (docs/plans/2026-10-09-alpaca-integration-pilot.md, executed 2026-10-09)
---

# Alpaca intraday depth build: leaf, admission, and the 2016-forward 5m/1m backfill

Deferred 2026-10-09. Gate: the depth-build plan doc written first from the
pilot's handoff decisions, then owner green-light to build. (Amended
2026-10-09 after the 189 probe verdict, todo 523: the IBKR batch tail fetch
closed, so the original build-order gate is moot; IBKR depth is per-name,
on-demand, targeted at a spec that names its need.) The evidence is already
in: the pilot pre-registered names, criteria and bounds, executed same day,
and passed everything the build needs except three named diagnoses.

Status 2026-10-10: the phase 2 all-names canonical 5m load is RUNNING
(launched by session indicagent-87 after two chunk-buffer fixes,
`6006fa217` and `a28f537ca`; log
`data/scratch/alpaca-pilot/load_apply_full.log`). The IBKR full-depth 5m
backfill is paused by design until the load's done-report; its fetcher
timer restarts then (session indicagent-7a holds the restart).

## What

Build the Alpaca loader leaf (Ring 0, credentials isolated like ib_async),
write observations through the existing capture, admit via the existing basis
machinery, and backfill 5m/1m from 2016-01-01 for the 233-name intraday
universe (~5 h, ~28k requests at Basic rates, ~2 GB; measured).

Pilot-mandated decisions it must implement:

1. Pull with `adjustment=split` (stored 1d is split-adjusted; Alpaca default
   is raw).
2. Spinoff/merger names (MMM, PFE, TMUS measured; HON, LEN, IBM, O are the
   same class from 185-52) get the corporate-action layer or per-class
   admission.
3. Store RTH-window aggregates only; never Alpaca 1d bars (extended-hours
   inclusion measured; the upstream daily convention matches the stored one).
4. Diagnose the three C3 5m names (DBC 68.7%, UUP 57.4%, PFE 39.6% pass; not
   split-related) and EWT's drop under split adjustment before their
   admission.
5. 1m storage (~7 GB) stays out unless a spec pre-registers a need.
6. Nightly verifier role rides with this build: after the IBKR backfill, pull
   the same window, run the basis comparison, d2-v3 restates on divergence.

## Why deferred, not pending

New vendor leaf plus admission work is phase-scoped (a real feature, multiple
sessions), not a single-session fix. Everything it needs from evidence is
done.

## Dependencies from the 189 lane (indicagent-7a, 2026-10-09, verified against this pilot doc)

1. **Multi-source overlap policy for 5m.** Which source wins a span once both
   IBKR and Alpaca hold real 5m for a name, and how D7's vendor-agreement
   checks extend to a second tape. The Tradier/IBKR precedent
   (`bar_source_policy` per-name rows, basis-tested admission) is the pattern;
   the build plan must write the 5m policy before the first canonical write.
2. **C8 single-day IBKR gap days become backfillable.** Days IBKR simply has
   no 5m answer for (e.g. DBMF 2019-10-16) inside Alpaca's 2016+ coverage can
   be filled from Alpaca through the same admission path, which is the
   cleanest resolution for those C8 verdicts. Pre-2016 stays IBKR-only.

Both land in the depth-build plan doc, not in code, before any canonical
write.

## Acceptance

Existing boundary tests pass unchanged (`SOURCE_ALPACA` in the bars sources
registry, no edits to admission or verdict-gate logic beyond the policy row);
the 22 pilot names' 5m basis at or above the C3 level on all 22 after the
diagnoses; volume convention verified by the H1 rule on stored rows.
