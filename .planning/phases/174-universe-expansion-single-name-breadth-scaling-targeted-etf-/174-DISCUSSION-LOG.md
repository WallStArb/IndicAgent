# Phase 174: Universe Expansion: Single-Name Breadth Scaling + Targeted ETF Gap-Fill - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-09-14
**Phase:** 174-Universe Expansion: Single-Name Breadth Scaling + Targeted ETF Gap-Fill
**Areas discussed:** Target universe & sourcing, ic_engine OOM fix approach, ETF gap-fill list, Instrument governance schema (todo 274)

---

## Target universe & sourcing

| Option | Description | Selected |
|--------|-------------|----------|
| Defer count to research | Todo 371 already proved 182 symbols OOM-kills ic_engine's largest cells; committing to a number first risks locking in an infeasible target | ✓ |
| Lock moderate target (~400-500) | Roughly double current 231 | |
| Lock large target (Russell 1000 scale, ~1000) | Matches maximal-coverage philosophy directly, highest collision risk with unresolved compute constraints | |

**User's choice:** Defer count to research.

| Option | Description | Selected |
|--------|-------------|----------|
| Russell 3000 (full) | Maximal coverage, most down-cap variety | (as population definition) |
| Russell 1000 only | Large+mid cap only, safer liquidity, stays in the already-tested efficient segment | |
| Targeted down-cap sample (curated) | Purpose-built to test down-cap hypothesis, but discretionary selection | |

**User's choice:** "1 or 3 — think like a council of senior engineers at Renaissance, channel Jim Simons, ruthlessly eliminate complexity, guard against hidden biases."

**Notes:** Claude reasoned through this explicitly (4-question test: 10x volume / hidden bias / DAG / manual step eliminated) rather than picking from the menu as framed. Conclusion: option 3 as framed (a hand-curated down-cap list) is itself a selection-bias trap — deciding which small-caps look "promising" in advance smuggles in a prior about where signal lives. Synthesized answer: Russell 3000 as the definitional target *population* (systematic, no cherry-picking — this is really option 1), implemented via a market-cap-stratified *random* sample (unbiased, proportional across cap-deciles) as the actual pilot scope. User locked this synthesis in.

| Option | Description | Selected |
|--------|-------------|----------|
| Active-only + parallel research | Don't block the pilot on an unresolved data-availability question (todo 376) | ✓ |
| Require delisted-inclusion research first | More rigorous but risks delay on a question that may be a dead end | |

**User's choice:** Active-only + parallel research.

---

## ic_engine OOM fix approach

Claude reasoned through the 4 fix options from todo 371 explicitly before presenting a recommendation (same council-of-senior-engineers framing, reiterated by the user mid-discussion as a standing instruction for this session).

| Option | Description | Selected |
|--------|-------------|----------|
| Pre-flight estimate + disk-streaming | Makes the crash-loud guard reachable before OOM; bounds peak memory by chunk size regardless of total cell size — the structural fix | ✓ |
| Subsample oversized cells | Keeps the run alive but silently changes what's measured — rejected as a *default*; may exist only as an explicit, visible, pre-registered escape hatch | |
| Bigger box only | Zero code change but fails the "survives 10x volume" test — already the applied stopgap, not a durable fix | |

**User's choice:** Pre-flight estimate + disk-streaming, lock it in.
**Notes:** Reasoning: bigger-box just relocates the OOM to a larger N given the phase's own breadth-scaling goal; the identical failure shape already recurred once (todo 290, `regime_volatility`'s obs-matrix) making this a systemic pattern, not a one-off; an uncontrolled kernel OOM-killer is itself an operational-safety issue (incident log shows it named an unrelated process, `JTS-DeadlockMon`, as invoker — nondeterministic collateral risk).

---

## ETF gap-fill list

| Option | Description | Selected |
|--------|-------------|----------|
| Bundle into Phase 174 | Same instrument-onboarding machinery (schema, backfill, ic_engine scaling) already being built | ✓ |
| Split into own phase | Keeps Phase 174 focused purely on single-name breadth hypothesis | |

**User's choice:** Bundle in.

| Option (multiSelect) | Description | Selected |
|--------|-------------|----------|
| Momentum | Zero representation currently | ✓ |
| Quality | Zero representation currently | ✓ |
| Low-volatility | Zero representation currently, complements the vol-term-structure gap | |
| None — EM-FX + vol only | Narrows to the two clearest gaps | |

**User's choice:** Momentum + Quality. Low-vol dropped from scope. EM-FX and vol stay in scope per prior-session exposure-gap findings (not re-asked — already established).
**Notes:** Exact tickers explicitly deferred to research/planning (liquidity, expense ratio, history-depth screening) — not a discussion-phase decision.

---

## Instrument governance schema (todo 274)

Claude reasoned through the 4-question test again before presenting a recommendation.

| Option | Description | Selected |
|--------|-------------|----------|
| Build the 3-way split now | Backfill-eligible / compute-eligible / live-tradeable, applied to new instruments as added | ✓ |
| Defer again, keep single `is_active` flag | Ships faster but repeats the postponement pattern through an even larger expansion | |

**User's choice:** Build it now, lock it in.
**Notes:** Reasoning: this gap already survived the 111→231 expansion untouched; deferring through a larger (Russell-3000-scale) expansion compounds the same debt and makes the eventual retroactive migration (splitting thousands of already-`is_active=true` rows) harder than classifying correctly as names are added. IBKR's 80-subscription cap only binds live streaming — confirmed dormant and non-blocking for this phase's backfill/measurement work (`src/providers/CLAUDE.md`) — but the single-flag model becomes a silent, nondeterministic landmine whenever live trading eventually resumes against a much larger "active" universe.

Todo 282 (instrument_metadata backfill gap from the prior expansion) folded in alongside this as D-08 — same instrument-onboarding surface being touched, cheap to fix the process this time rather than let it recur a third time.

---

## Claude's Discretion

- Exact ETF tickers for momentum/quality/EM-FX/vol gap-fill — research/planning screens for liquidity, expense ratio, history depth.
- Exact stratification scheme for the market-cap-stratified sample (number of cap-deciles, sample size per decile).
- Schema shape for the 3-way instrument-governance split (separate boolean columns vs. `instrument_tags` entries; default semantics for existing rows).

## Deferred Ideas

- Nautilus Trader (OSS execution/backtest-parity engine) — future execution-layer phase candidate, not this phase.
- Qlib, Vectorbt — evaluated and rejected for current needs (raised by user mid-session as a general build-vs-OSS question, not phase-specific).
- Full futures backfill (todo 377) — explicitly out of scope. If pursued later: target only CL/NG/HG/ZC/ZS/ZW/VX/GBPUSD/USDCHF (9 instruments, not all 22), after a separate continuous-contract-construction design.
