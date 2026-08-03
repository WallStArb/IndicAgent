---
status: pending
priority: P2
filed: 2026-07-13
source: doc-organization session — consolidating 106/076/041 (all folded into design docs
  2026-07-13) into one tracked item per user request
---

**Registered as ROADMAP Phase 145** — see `.planning/ROADMAP.md` for the live phase entry.
**Unblocked 2026-07-22** — Phase 144's D-05 verdict landed (F1 not triggered for TLT/rates;
F2 triggered for 15m/5m, pending todo 170's `volatility_pct` substitution check before any
challenger model is considered). Bumped P3→P2: this is now real, actionable design work, not
just a blocked placeholder. `/gsd-discuss-phase 145` or `/gsd-plan-phase 145` can run — read
Phase 144's full verdict in ROADMAP.md first, since the row-grain decision below should be
informed by it (a group that's genuinely deficient on both axes at some tfs, like rates at
15m/5m, is a live example the Option A/B decision needs to handle, not a hypothetical).

# Stratification & Classification Registries

Single todo for this cluster. Umbrella doc: `docs/research/stratification-governance-registries.md`.
Canonical docs: `stratification-dimension-unification.md`, `stratification-security-
classification-hierarchy.md`, `stratification-instrument-tag-calibrator.md`.

## Current state, by component

**StratificationDimension (provider contract):** design complete, `Protocol` written. Real work
remaining — writing the actual code, ratifying the `concept_registry` row-grain decision (Option
A vs. B, both fully specced in `concept-unified-registry.md`'s Domain Vetting section) — was
gated on Phase 144's D-05 empirical verdict. **That verdict landed 2026-07-22**: F1 not
triggered (TLT/rates' per-symbol HMM stays deficient vs. cross-sectional), F2 triggered for
15m/5m (rates cross-sectional is ALSO deficient there — neither axis currently works, see
todo 170 for the pending `volatility_pct` check before concluding a new axis is needed). See
`stratification-dimension-unification.md`'s "Formalization revival note" for the original
trigger definition.

**New candidate dimensions** (correlation regime, liquidity regime, term structure regime,
posterior-weighted soft stratification): specced in `stratification-dimension-unification.md`'s
backlog paragraph.
Enter through the same substitution-test + orthogonality gate as every other candidate once the
contract above is real — not a bespoke build, and not gated separately from it.

**Security Classification Hierarchy (GICS-style):** draft design, unscheduled milestone
(individual-equities era, no ROADMAP phase yet). No near-term action.

**Instrument Tag Calibrator:** draft design. Separately, its own canonical doc carries an open
question (tag_vocabulary's 6-category taxonomy has 3-4 concrete design flaws — see
`stratification-instrument-tag-calibrator.md`'s "Open question" section) that should resolve
before or alongside this calibrator's own build, and independently before commodity/fx
`regime_group` entries are ever enabled (unrelated gate, own timing).

## Not yet done

Revive the StratificationDimension formalization — unblocked as of 2026-07-22 (see above), not
yet started. Everything else here (new candidates, tag taxonomy audit) either enters through
that same gate or has its own independent, unrelated trigger — see each component's canonical
doc, not duplicated here.
