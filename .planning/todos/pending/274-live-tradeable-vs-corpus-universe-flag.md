# 274: Separate "corpus universe" from "live-tradeable universe" on instruments

**Filed:** 2026-08-06

## What happened

While building the nightly incremental backfill job (todo/session work following the 111→231
active-instrument expansion), the user asked whether we should track "what symbols to get data
for" separately from "what symbols are live trading" and "what symbols we want to run the corpus
against" — i.e., three potentially-different scopes currently collapsed into one `is_active`
boolean on `instruments`.

Checked the schema: `instruments` has only `symbol`, `contract_details`, `is_active`,
`created_at`, `updated_at`, `base`, `expiry`. No column or tag distinguishes "eligible for live
IBKR streaming" from "part of the backfill/corpus measurement universe." `get_active_contracts()`
is the single source everyone (backfill, feature_factory, ic_engine, regime models) reads from.

## Why this matters

IBKR's 80-simultaneous-subscription cap (`reqMktData`/`reqHistoricalData(keepUpToDate=True)`)
is a hard ceiling on live trading, documented in `src/providers/CLAUDE.md`. The active universe
is already 231 (151 over that cap) and the user is discussing growing the corpus universe
further (S&P 500 / NDX 100 / Russell 1000 scale, deferred per 2026-08-06 discussion — see
memory `project_universe_expansion_and_ibkr_recalibration_2026_08_06.md` and session notes).
Without a schema-level split, there's no way to answer "which ~80 of these should actually be
live-tradeable" without hand-picking at restart time, and no way to grow the corpus/backfill
universe independently of that constraint.

## Action needed

Follow-up discussion the same session sharpened this into three separable dimensions, not one
flag vs. `is_active`:
1. **Backfill-eligible** — should OHLCV be fetched/maintained for this symbol at all.
2. **Compute-eligible (corpus)** — should feature_factory/ic_engine/regime models run against
   it. Probably a subset of (1) — data can exist before it's trusted/mature enough to feed
   compute (e.g. a symbol still being evaluated, or too new to have enough history).
3. **Live-tradeable** — eligible for live IBKR streaming (`reqMktData`/
   `keepUpToDate=True`), hard-capped at 80 simultaneous subscriptions. Almost certainly the
   narrowest subset.

These are likely near-hierarchical (live-tradeable ⊆ compute-eligible ⊆ backfill-eligible) but
worth confirming that's actually true rather than assumed — e.g. "backfill now, decide
compute-eligibility later" is a plausible real state (a newly-added symbol with data still
accumulating).

Design a schema for this (separate boolean columns on `instruments`, or `instrument_tags`
entries per dimension) rather than the single `is_active` boolean everything reads today. Needs:
- A migration adding the column(s)/tag(s).
- A decision on default semantics for existing rows (does today's `is_active=true` map to all
  three being true, or does it become "backfill-eligible" only, requiring an explicit migration
  step to mark the current compute/live subsets?).
- Whether `get_active_contracts()` gets sibling functions (`get_compute_eligible_contracts()`,
  `get_live_tradeable_contracts()`) or an optional dimension filter param.
- Live-tradeable only matters operationally once `indicagent-ibkr-provider` is un-paused (see
  root CLAUDE.md's "Live IBKR ingestion chain is intentionally stopped" note) — not urgent for
  that piece, but the backfill-vs-compute split could matter sooner, e.g. for the nightly
  incremental backfill job (this same session) once the universe grows large enough that
  backfilling everything doesn't mean every symbol is corpus-ready yet.

Not blocking the nightly incremental backfill job (same session) — that job operates on
`is_active` only, same as every other corpus consumer today.
