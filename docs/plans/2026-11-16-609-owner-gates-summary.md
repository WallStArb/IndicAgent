# Owner decisions for the stage 2 universe and the first counted tests

**Status:** Summary, 2026-11-16. Every item below is a draft or an open call; nothing is adopted, built or run, and no real-data number exists for any family. The recommendations are the lead's (indicagent-52); this page only gathers them in one place.
**Author:** indicagent-65 for the lead. Sources are named in the last column of each table; nothing here replaces them.

## What the owner is deciding, in one paragraph

The data gate is nearly closed (step 7 through D4). What stands between the rebuilt data and the first counted tests is a short chain: adopt the identity amendment, install the stage 2 identity map and instrument rows, load 1d for every ticker, show the owner the member counts by year, build the membership table, then run the corpus rerun and the first families. Each item below either sits on that chain or fixes something about the families that will run on it. Nine of the ten recommendations are adopt; the tenth, the plan call, is lapse after a verified capture.

## On the critical path

| # | Decision | Recommendation | What it unblocks | Cost of waiting | Where it is written |
|---|---|---|---|---|---|
| 1 | Pit-anchor identity amendment (key kinds, runs, span boundaries, bridging of a single missing month, the absent-month end rule), revised 2026-11-16 | Adopt | The pit install (about 34,000 new securities, inactive instrument rows, identifiers and spans), then the all-ticker 1d load and the membership build. The whole 609 chain waits on it | Every day of delay is a day of the chain: nothing after it can start. The install is reversible (a rolled-back rehearsal proves the rollback first) | `docs/plans/2026-11-15-pit-anchor-map-and-stage2-instruments.md`, section 1 and the 2026-11-16 revision |
| 2 | Membership after the last Massive list: closed list, no entrants, L = 2026-11-09 | Adopt | Building membership rows for month-ends after 2026-11-09, which only a book's forward shadow reads. It adds no look and changes no test on the discovery vintage | Nothing until a book freezes; the build refuses those months without it | `docs/plans/2026-11-15-stage2-membership-after-archive-end-amendment-draft.md` |
| 3 | 5m tier amendment ($25M entry, $12.5M exit, nested in the membership) | Adopt | The 5m tier load and cost estimate, and so every intraday family on the new universe | The daily families are unaffected; intraday waits. The estimate is measured before the load, so nothing is committed by adopting | `docs/plans/2026-11-15-stage2-5m-tier-and-intraday-universe.md`, part 1 |
| 4 | Seen-name holdout (the 231 names of the 2026-09-13 screen and the 13-name cross-asset set, about 5 percent of the membership, excluded from both panels) | Adopt | A clean statement of every family's universe: the seen names stay off the data that shaped the earlier looks, so no second disclosure cell is needed | Without it each family discloses the seen names as a prior look touching about 5 percent of the panel, which costs power in the disclosure and is harder to defend | top-three drafts, section 2 |

## On the first counted tests

| # | Decision | Recommendation | What it unblocks | Cost of waiting | Where it is written |
|---|---|---|---|---|---|
| 5 | A1, the daily residual family moves from `daily_unseen` (1,269 names) to the membership and core panels | Adopt | The first counted daily family on the stage 2 universe: residual momentum and the three reversal members R1 to R3 | The family keeps its smaller, survivors-only universe and its draft registration, so the breadth gain of stage 2 is not used | daily residual prereg, section 10 |
| 6 | A2, a sixth member (information discreteness, M3) | Adopt | A complete first batch for the family, registered before any result | Low: the family can run on five members and add M3 later as a counted variant, at the price of rerunning B2 | daily residual prereg, section 10 and the top-three drafts |
| 7 | E23, the ledger entry for the three published-prior families (12 series) | Adopt | Recording the counted design choices before any result, which E18 requires | The three families cannot register without it | top-three drafts, section 6 |
| 8 | E24, the family 10 daily volume-shock members (4 series) | Adopt | A third registration on the same gate, sequenced after the three above | Low; it queues behind them in any case | `docs/plans/2026-11-15-family10-volume-shock-prereg-draft.md`, section 8 |
| 9 | E26, family 9 (52-week-high anchoring, 1 member, 2 series, expected sign positive against a seen opposite-sign corpus look) | Adopt | A fourth registration; E25 stays reserved for realized semivariance and E27 is free | Low; it queues behind the others | `docs/plans/2026-11-15-family9-52week-high-prereg-draft.md`, section 8 |

Items 5 and 6 depend on item 4. None of items 5 to 9 moves a recorded spec hash. The clean-data rule (E21) still holds until the owner lifts it for the families: no real-data hypothesis test runs while the rebuild is in progress.

## Dated and outward-facing

| # | Decision | Recommendation | What it unblocks | Cost of waiting | Where it is written |
|---|---|---|---|---|---|
| 10 | Renew or lapse the Massive plan (lapses about 2026-12-10; the exact date is on the account page) | Lapse, after the pre-lapse capture and verification are done. This spends money with an outside vendor, so it is the owner's call | Nothing on the chain needs a renewed plan: the archive and reference tree are on disk twice, canonical uses Massive only to 2026-11-16, and the Alpaca tail matched Massive at a median volume ratio of 0.99993 in 2026. Renewal buys a second witness and a self-updating archive | The capture steps have to run before the lapse date, so the owner's answer is needed by early December. The plan price is not recorded in the repo, so the owner supplies it: renew only if one more month is trivially cheap and a named consumer needs data after 2026-12-10 | `docs/plans/2026-11-15-massive-plan-lapse-deadlines.md` |

## Order that loses no time

1. Adopt item 1 first: it is the only gate on the chain that cannot be worked around, and the lead can start the install rehearsal the moment D4 passes.
2. Items 2 to 4 before the membership build is shown to the owner (the member counts by year are the owner's next look, after the all-ticker load and the unplaced-share table).
3. Items 5 to 9 before the first family is registered; they can be adopted together in one reading.
4. Item 10 by early December, with the capture checklist running between now and then.

## What this page does not ask

The owner is not asked to review code, rerun anything or pick a method. The pit-anchor branch has been reviewed and its fixes are in a held worktree; the install rehearses and rolls back before anything is written. The unplaced-share measurement (the preregistered survivorship residual, by year and type) is a step the lead runs before membership is built and shows to the owner with the member counts.
