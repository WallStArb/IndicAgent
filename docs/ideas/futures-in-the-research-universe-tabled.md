# Futures in the research universe: tabled

**Status:** Idea, tabled by the owner. Not planned; reopen only when the conditions below hold.
**Author:** Claude Sonnet 5.5, interactive session, 2026-10-03, from the owner's decision stated in
conversation. The archived-doc pointers were checked to exist; none of their designs was re-verified
against today's code.
**Origin:** Futures were the starting point of the project. They were tabled because roll and symbol
changes added complexity the core system did not need while it was being refined.

## State today

- `instruments` holds 18 futures (ES, NQ, YM, RTY, ZT, ZF, ZN, ZB, CL, NG, GC, SI, HG, ZC, ZS, ZW, VIX,
  VX) and 4 FX pairs (EURUSD, GBPUSD, USDCHF, USDJPY), all `is_active = false`, with no bars.
  `contract_metadata` has 52 rows from the earlier roll work.
- The 1,529 active names are equities and ETFs. Commodity, rate, currency and managed-futures
  exposure comes through funds (USO, DBMF, KMLM, CTA and similar), which carry their own roll cost
  and decay.
- The nightly roll batch (`indicagent-roll-batch.timer`, `scripts/ops/roll/ops_roll_batch.py`)
  exists and is disabled.

## Why it is hard

A futures series is a chain of contracts, not one instrument. Each roll changes the symbol, leaves a
price gap between contracts, and needs a rule for which contract is front, when to switch and how to
adjust history. Research needs a point-in-time contract history; the panel assumes one symbol per
row over the whole span (`point_in_time`, `no_fill`, `asset_agnostic`).

## Conditions to reopen

1. 185 and 186 have landed and the forward runner (188) is running, so the system is no longer being
   refined underneath this.
2. A written roll and back-adjustment rule, decided before any bar is fetched (the select-without-
   outcomes rule applies).
3. A point-in-time contract history as an input to S0, so a read for t sees the contract that was
   front at t.
4. A margin-based cost model for promotion; the commission-per-share model does not apply.
5. A family that needs futures, such as trend or carry across asset classes that the ETFs cannot
   express. Without one, there is no reason to build it.

## Earlier work

Archived, kept for history. Check each before reusing; the roll agents they describe were deleted.

- `docs/research/archive/futures-roll-simplification.md` (adopted 2026-05-26): calendar-driven nightly
  batch in place of a 24/7 roll agent.
- `docs/plans/archive/2026-05-26-roll-compute-simplification.md`: the plan for that batch.
- `docs/plans/archive/2026-03-17-automated-roll-detection-design.md` and
  `docs/plans/archive/2026-04-02-contract-lifecycle-automation-design.md`: the earlier detection and
  lifecycle designs.
- `.planning/IDEAS.md`: three open bullets (roll premium feature, continuous contract support, roll
  detection improvements).
