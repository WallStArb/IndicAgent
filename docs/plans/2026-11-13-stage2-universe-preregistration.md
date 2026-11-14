# Stage 2 universe: preregistration

Author: lead session indicagent-d0, 2026-11-13
Informed by: todo 609 (sizing measured 2026-11-12 on 50.2M day-file rows, owner agreed), owner ruling 2026-11-13 (IBKR removed; Massive is the identity and price source), `docs/plans/2026-11-10-massive-admission-db-design.md` sections 8b and 11, evidence rules E15 to E18 and E21.

Status: ADOPTED by the owner 2026-11-13 (floor $1M in and $0.5M out; types common stock, ADR and ETF; core panel at 90 percent of month-ends). Frozen: nothing below changes after any return-based look at the universe; a change is a dated amendment, counted as a design choice under E18.

## Why

Breadth (more independent bets per date) and a survivorship-free sample are the two largest levers on finding a statistically significant edge. Today's research universe is 1,529 current names, which is survivors only. The Massive archive holds about 36,700 tickers from 2003-09-10, including every dead and merged name. A point-in-time rule over that archive gives about 4,150 members at a typical month-end (2,950 to 6,040), about 16,000 securities over the archive, with delisted names present while they qualified.

The research universe and the tradable set are separate questions (owner 2026-11-13: "there should be more of a universe than 2000"). The universe is where signals are learned, so it is wide; capacity and cost decide what is traded, at promotion (positive net expectation), never inside the universe. A $1M median daily dollar volume name still takes a $25k position at 2.5 percent of daily volume.

## The rule (preregistered values)

Membership is decided at each month-end t, effective for the following month, from data available at t only.

| Element | Value | Note |
|---|---|---|
| Security type | common stock or ETF, from Massive reference types (captured, never live) | ADRs of operating companies count as common stock; preferreds, warrants, units, rights, ETNs and closed-end funds are out |
| Liquidity | trailing 60-session median of close x volume at or above $1M to enter (owner 2026-11-13) | measured 2026-11-12: about 4,154 members at a typical month-end (2,947 to 6,041), 16,045 securities ever |
| Hysteresis | a member leaves only below $0.5M (half the entry floor) | keeps N and the cross-section stable |
| Price | close at or above $1 on t | |
| History | at least 60 sessions of the security's own bars before t | |
| Identity | one security = one entity-map identifier (FIGI); a reused ticker is two securities | spans the map cannot place are not members on those dates |
| Point in time | every input is known at t: bars through t, reference answers as captured, splits known at t | the dollar-volume window uses split-adjusted volume as of t |

The values are research-design constants recorded here and in the spec hash of every run that reads the universe. They are not APR keys: a tunable universe would invite tuning after seeing results, so a change is a dated amendment here, never a `config_state` write.

## Two panels for every test

Every feature or family runs on two panels: the point-in-time universe above, and a constant core (securities that are members on at least 90 percent of month-ends over the vintage). A universe effect then separates from a feature effect on the same securities. Features compute on every security with 1d data; membership only gates the IC panel, so an entering name arrives with warmed features.

## Tiers

- 1d: every member, loaded for every ticker in the archive (about 50M raw rows).
- 5m: the top liquidity tier only, nested inside the membership so 1d and 5m results compare on the same securities. The tier size is set from a measured cost estimate (rows and feature-compute time per name-year) before any 5m load; the estimate and the chosen size are recorded here as an amendment before loading.

## Gates (in order)

1. Step 7 has proven itself (canonical is Massive then Alpaca, D1 passed).
2. This preregistration is adopted by the owner.
3. `ops_massive_load.py --all-tickers` loads 1d for every ticker behind the identity map, gated per year (compare 0 real differences, canonical unchanged).
4. Dead-name instrument rows enter through the onboarding SOP's stage 2 exception, never hand-written.
5. `universe_membership` is built (one writer) and the member count by year is shown to the owner before any compute.
6. The 5m tier cost estimate, then the tier load.

## Failure modes designed against

- Choosing the floor, type filter or core threshold after seeing results: fixed here first.
- Ticker reuse mixing two companies: identity is the entity map, never the ticker string. With IBKR removed there is no external witness for the new names, so the identity map's gap rate on the all-ticker set is measured and reported before membership is built; unplaced spans are not members.
- Point-in-time leakage: membership at t reads only data known at t.
- Missing delisting returns: a delisted name's final bars are checked present in 1d; a member that vanishes without a final bar is listed.
- Silent compute growth: the 5m tier and feature compute are gated on a measured estimate.

## Amendment 2026-11-13 (lead, pre-look: no return-based look at the universe has happened)

Identity. Measured 2026-11-13 (todo 609 task A): the entity map is anchored on IBKR contract details, captured for our 1,529 names only, so with IBKR removed it places no ticker beyond them (22.7 percent of the rows that meet the $1M rule). An upper bound from Massive's own captured ticker events places 54.3 percent, and the unplaced half is concentrated in dead names and early years (common stock: 30.7 percent placed in 2003, 85.7 percent in 2026), which is the survivorship this stage exists to remove. Amended identity element: the anchor is Massive's point-in-time ticker reference, captured as one snapshot per NYSE month-end from 2003-09 to the archive end (active and delisted tickers) before the plan lapses about 2026-12-10. Key: composite FIGI; where absent, CIK plus share class plus type, with the key kind recorded. A (ticker, month-end) is placed when exactly one key claims it. Whatever stays unplaced is excluded from membership, and the survivorship residual (unplaced share of rows meeting the rule, by year and type) is measured after the capture and recorded here before membership is built.

## Amendment 2026-11-14 (lead indicagent-13, pre-look: no return-based look at the universe has happened)

Gate order and the meaning of "canonical unchanged". Review of the `--all-tickers` code (commits af094a955, ab64a0409, 2211c80e6) found two defects in the gate text; no rule, floor or threshold changes.
- Gate 4 (dead-name instrument rows) and the identity-map rebuild on the pit anchor (`--pit-snapshots`) come before gate 3. The load already covers every span in `ticker_event`; `--all-tickers` widens only the completeness check, and a dead name exists as an instrument only after gate 4, so run in the old order it loads nothing extra. The flag now exits 2 when no name outside the active set has a span.
- Gate 3's "canonical unchanged" means unchanged for every name already in canonical, proven by the per-year compare. New names necessarily gain canonical rows, because after step 7 Massive is ranked for 1d and `--apply` selects into canonical every slot it wins.
Effective gate order: 1, 2, 4 with the map rebuild on the pit anchor, 3, 5, 6.
