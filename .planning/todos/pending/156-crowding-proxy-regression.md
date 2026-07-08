# 156 — Crowding proxy: alpha overlap with public-factor signals

**Source:** `docs/research/fable-2026-07-07-renaissance-layer-refinements.md` §10 (L7-3).
**Priority:** medium — runs against data that exists *today*, no dependency on the corpus rerun
or Phase 142B.
**Gate:** none.

## Proposal

Regress `alpha_score` (per stratum, per epoch) on 2-3 canonical public signals computed from the
same bars: 12-1 momentum, 5-day reversal, low-vol tilt. High R² doesn't invalidate the edge, but
it prices its decay risk — alpha explainable by the most public factors in existence is alpha the
crowd already trades, and its half-life should be assumed short. Report R² per epoch as a
standing manifest metric; a rising trend is a crowding alarm no IC decay monitor would catch
until later.

## Mechanics

One script; factor signals are trivial derivations of existing columns. The regression is the
measurement — the falsifiable claim is "our alpha is not just public factors," and the number
says so or doesn't. Diagnostic only, no gate change.
