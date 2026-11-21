---
status: pending
priority: P2
filed: 2026-11-21
source: indicagent-66 gate lane, 2026-11-21 (4,615 members since 2026-09 are inactive instruments)
owner: lead
---

# The forward feed covers about a quarter of the current stage 2 members

## What

Stage 2 onboards its names as inactive instruments, and the Alpaca nightly reads only active ones. 4,615 members since 2026-09 are inactive, 4,590 of them with bars through 2026-11-12 or 13 (the Massive archive). Since the 2026-11-16 seam only 1,514 symbols have a new 1d bar (the 1,529 active names, through 2026-11-20). `is_active` is false by design for these; 80 of the 85 inactive 2026 members are live products with an open ticker span (BAR, PLTM, TSLY, NVDY, AMZY, GOOY, APLY, MSOX and others, mostly ETFs).

## Requirement to question first (Musk step 1)

A frozen book trades and is confirmed on its own forward span, so the forward feed needs every name a book can hold, not every member. Which members can a book hold at all is set by the tier and the construction rule, not by membership. Decide that set before changing any instrument row.

## Done when

1. The set of names a book or the forward runner can read is stated (tier names ever in a book candidate universe, or the 5,192 tier securities, or a smaller closed list), with the count of those that are inactive.
2. A decision between the onboarding SOP's stage 2 exception (an active row for live tier names, through the SOP, never a hand-written `instruments` row) and a separate forward feed for them, with the nightly cost (requests and minutes) of each.
3. The nightly's raw capture covers the chosen set, and the forward runner reads it.

## Not blocking

The first counted run (data horizon 2026-11-01) and the 1d-first corpus rerun read the Massive archive and do not need the forward feed. Block this before the first book freeze, not before the pin.
