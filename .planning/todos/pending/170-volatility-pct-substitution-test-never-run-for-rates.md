---
status: pending
priority: P1
filed: 2026-07-22
source: found while closing Phase 144's D-05 gate (symbol_hmm restoration fix, worktree
  restore-symbol-hmm-ic-measurement) -- F2 triggered for rates/15m/5m (neither per-symbol
  HMM nor cross-sectional separates IC there), and the pre-registered next step explicitly
  requires confirming this check first, before considering a new model.
---

# `volatility_pct`'s substitution test for `rates` was proposed 2026-07-02 but never run or tracked

## What's wrong

Phase 144's D-05 gate just produced a real verdict (2026-07-22): F1 not triggered (TLT's
per-symbol HMM stays deficient, demotion holds) and **F2 triggered for `rates` at 15m and
5m** — neither per-symbol HMM nor the new cross-sectional label separates IC at high
frequency for this group. Per `docs/research/fable-2026-07-07-phase144-conditioning-decision.md`
§4, F2 is the pre-registered build trigger for a factor-augmented HMM challenger (option c)
— **but only "pending confirmation that `volatility_pct` hasn't already separately passed
its own substitution gate for `rates`."** Building a new, heavier HMM variant when a cheaper
candidate dimension might already resolve the gap would be exactly the kind of premature
complexity this project's own principles warn against.

Checked: `volatility_pct` was named as a rates fallback candidate as far back as
`docs/research/fable-2026-07-07-phase144-conditioning-decision.md` (option (b)'s adoption:
"stratify on cross-sectional + `volatility_pct` if and when that candidate passes its own
substitution gate") and was explicitly listed in the original v3.15 milestone batch
(`stratification-dimension-unification.md`'s "Sequencing" section: "The `volatility_pct`
substitution test," alongside Phase 144 and todo 041). **No todo, PLAN.md, or verification
doc tracks whether this test has ever actually run.** Given how many `ic_engine` corpus
rebuilds have happened since (143.1-07, today's scoped rates re-run, others), it's plausible
this fell through the cracks of "batched into Phase 144's re-run" without anyone confirming
it as its own explicit step.

## Fix direction

Cheap and well-scoped — `stratification-dimension-unification.md` line ~307 describes a
"zero-schema-change first probe" specifically for this candidate: run `ic_engine` stratified
by `volatility_pct` instead of (or alongside) the incumbent labels and compare IC separation
directly, before committing to any schema change. `volatility_pct` and `dispersion` are
explicitly **exempt from the orthogonality-vs-other-candidates gate** (already measurably
distinct), so this doesn't need the full multi-candidate governance pass — just the
substitution test itself:
- Pass criterion (per the same doc): IC Sharpe increases >10% in at least one joint cell,
  N > 20,000 bars in that cell.
- Scope to `rates`, 15m and 5m specifically (the two tfs F2 triggered on) — no need to
  re-litigate `equity` or other tfs where cross-sectional already separates cleanly.

**Do this before considering the factor-augmented HMM challenger** — if `volatility_pct`
passes, the challenger becomes unnecessary (Musk step 1: question whether the more complex
build is even required before doing steps 2-5). If it fails too, that's a real, useful
negative result — `rates` at high frequency may simply be a harder stratification problem,
worth knowing either way.

## References

- `docs/research/fable-2026-07-07-phase144-conditioning-decision.md` §4 (F2) — the
  pre-registered trigger this todo's check gates
- `docs/research/stratification-dimension-unification.md` lines 227, 287, 307, 399, 500 —
  the candidate's design, exemption status, and probe method
- `.planning/ROADMAP.md`'s Phase 144 section — the live D-05 verdict this todo follows from
