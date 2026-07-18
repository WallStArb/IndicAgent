---
status: completed
priority: P3
filed: 2026-07-13
closed: 2026-07-18
source: roadmap priority-ordering session — found while cross-referencing ROADMAP.md's
  "Planned Phases — Priority Order" section against the backlog matrix
---

# Score Phases 156-159 (v4.0 Execution Layer) in the backlog matrix

**Resolved 2026-07-18** — added four rows to `docs/research/intelligence-lifecycle-backlog-matrix.md`'s
MEDIUM tier: Phase 156 (L / Low / High-eventual), Phase 157 (L-XL / Med / High-eventual), Phase
158 (L-XL / **High** risk — first phase where a bug has direct capital consequence, not just a
stale measurement / High-eventual), Phase 159 (M-L / Low / High-eventual). Confirmed the todo's
own hypothesis: absence of a score was never a low-reward verdict, just an unscored gap — all
four carry High/eventual reward since they're the literal execution layer the endgame (personal
live trading capital) is gated on. Phase 158 correctly scores materially higher risk than its
siblings.

`docs/research/intelligence-lifecycle-backlog-matrix.md` scores every other planned
phase on Effort/Risk/Reward. Phases 156-159 (Portfolio State Foundation, Position Sizing & Risk
Management, Live Execution Layer, Cost Calibration Feedback Loop) were numbered 2026-07-12 —
four days after the matrix was last written — so they were never scored at all, not scored low.

**Why this matters:** the phases are correctly hard-gated on v3.2 complete + `alpha_events`
schema frozen (a real dependency fact), but "far out on the dependency graph" and "low value"
are different questions. Don't let the absence of a score get silently read as a low-reward
verdict when nobody has actually made that call.

**What to do:** add a "Phases" row (or four) for 156-159 to the matrix with real Effort/Risk/
Reward scoring, consistent with how Phase 148/151/etc. are scored — likely HIGH or MEDIUM given
this is the actual live-capital execution layer the whole project's endgame is gated on, but
don't presume the number, score it properly.
