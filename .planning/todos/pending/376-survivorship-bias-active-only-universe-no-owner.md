---
status: pending
priority: P2
filed: 2026-09-13
source: adversarial council review of the personal-scale edge determination program's fired
  kill criterion (`.planning/STATE.md` Strategic Plan section, 2026-09-13) -- flagged as "the
  one genuinely unresolved integrity gap... no owner," never previously filed as its own
  tracked item
---

# Survivorship bias: 100% of the trading universe is `is_active=true`, zero delisted names

## What

Every symbol in the corpus (231 active names, plus 22 registered-but-never-backfilled
futures/FX) satisfies `instruments.is_active=true`. Zero delisted/defunct securities exist
anywhere in `instruments` or `market_data_ohlcv`. Every IC/edge measurement this project has
ever run -- every row in `docs/research/construction-verdict-ledger.md`, every personal-scale
pre-registration -- is implicitly conditioned on "still trading as of universe-construction
time," which is a look-ahead-flavored selection: names that failed badly enough to delist
(bankruptcy, forced merger, exchange removal) are structurally absent, and those names are
disproportionately likely to have carried strong momentum/mean-reversion signal in their
final stretch.

This is not a new concern -- `.planning/STATE.md`'s Strategic Plan section has flagged it
inline since the 2026-09-12 program closure ("no owner, flag it before citing any IC number
here as a hard ceiling") -- but it had no todo, so it wasn't tracked anywhere PRIORITIES.md's
drift audits would catch, and nothing forced a periodic re-check of whether it's still
unaddressed.

## Why this matters now

Universe expansion is the prescribed next phase (STATE.md, kill criterion rule 3). Any
decision about which/how-many new instruments to add should account for whether the expansion
methodology perpetuates the same active-only selection (likely, if new symbols are sourced
the same way the original 231 were) or has a chance to correct it (e.g., sourcing historical
constituents of an index that includes since-delisted members).

## Action item 1 status: UNRESOLVED (2026-09-15, Phase 174 Plan 04)

Full evidence and method: `docs/research/russell3000-sourcing-and-delisted-feasibility.md`
("Delisted-constituent feasibility" section). Summary: tested 3 named delisted tickers
(SIVB, TWTR, ATVI) against Yahoo Finance's free chart API (confirmed structurally absent --
explicit "symbol may be delisted" 404 for all 3) and stooq.com (blocked by a client-side JS
proof-of-work challenge, not testable without a browser). Live IBKR was NOT tested --
`ib-gateway` is down and this task deliberately did not restart it (Plan 10 owns that restart).
Verdict is UNRESOLVED, not NOT OBTAINABLE: the two most plausible real paths (IBKR once the
gateway is back, or a paid survivorship-bias-free vendor like Norgate Data/Polygon.io/CRSP)
remain untested, not failed. Per D-03, this does not change Phase 174's pilot scope, which
stays active-only regardless.

## Action

Not a code fix -- a data-sourcing and documentation question:

1. Determine whether IBKR (or another already-integrated provider) can supply historical bars
   for delisted securities at all, or whether this requires a different data source entirely
   (e.g., a survivorship-bias-free index constituent history).
2. If obtainable at reasonable cost/effort: scope a follow-on to backfill a delisted-name
   sample and re-run at least one closed construction (a cheap re-verification, not the full
   14-construction ledger) to get an empirical read on whether the bias is large enough to
   matter at this corpus's typical effect sizes (recall: effective breadth ~8.4, most IC
   magnitudes in the 0.03-0.06 range -- a bias comparable to that range would be
   load-bearing).
3. If not obtainable: document that explicitly as a permanent, structural corpus limitation
   (not a "someday" item) so every future IC citation carries the caveat by reference to this
   todo rather than by hoping STATE.md's inline note gets re-read.

## Cross-refs

- `.planning/STATE.md` Strategic Plan section -- original flag, 2026-09-12/13.
- `docs/research/construction-verdict-ledger.md` -- every verdict this bias potentially
  affects.
- `docs/plans/2026-09-02-personal-scale-edge-determination-plan.md` -- the program whose
  closure surfaced this as the one unresolved integrity gap.
