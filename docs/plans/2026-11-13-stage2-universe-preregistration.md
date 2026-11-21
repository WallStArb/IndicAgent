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

## Amendment 2026-11-18 (ADOPTED 2026-11-18, owner decision taken through the lead; pre-look: no return-based look at the universe has happened)

Four amendments drafted 2026-11-15 and 2026-11-16 are adopted as written, each a dated design choice under E18. None adds a counted look or series, and none moves a recorded spec hash. The text lives in the named documents, which this section does not restate.
- Pit-anchor identity details (key kinds, one key per record, runs and bridging of a single missing month, securities, span boundaries and the absent-month end rule, additive-only install, the unplaced report), including the 2026-11-16 revision: `docs/plans/2026-11-15-pit-anchor-map-and-stage2-instruments.md`, section 1.
- Membership after the last Massive list (L = 2026-11-09): a closed list, no entrants, rule id `stage2-closed-list`, disclosure of the member count and the excluded newcomers at every freeze and confirmation: `docs/plans/2026-11-15-stage2-membership-after-archive-end-amendment-draft.md`, Part 1.
- The 5m tier ($25M entry, $12.5M exit, nested in the membership, `RULE_ID` bumped): `docs/plans/2026-11-15-stage2-5m-tier-and-intraday-universe.md`, Part 1.
- The seen-name holdout (the 231 names of the 2026-09-13 screen and the cross-asset set, excluded from both panels by a pinned list): `docs/plans/2026-11-15-published-prior-top3-prereg-drafts.md`, section 2; its counted choices are in ledger E23.

## Amendment 2026-11-19 (lead, correction, pre-look: no return-based look at the universe has happened)

Where canonical 1d for the new names comes from. The 2026-11-14 amendment says `--apply` selects into canonical every slot Massive wins. That is not what the all-ticker 1d load does: the bulk path writes `ohlcv_raw` only, and canonical 1d is written by the daily stage of `services.bar_derivation` alone. The daily timer reads active instruments only, so the stage 2 names (inactive instruments) reach canonical through one explicit `--stage daily --symbols` run after gate 3, before membership is built. The s5 rehearsal of 2026-11-19 read canonical before that run and found 1,365 members at 2026, not about 4,150, which is how the gap showed. No rule, floor or threshold changes. Their splits are not recorded (todo 646), so their canonical closes are as traded.

## Amendment 2026-11-20 (lead, enforcement of the closed list, pre-look: no return-based look at the universe has happened)

The closed list's candidate set is pinned (todo 645). `CLOSED_LIST_CANDIDATES_SHA256 = e13546aa78be46026b204ea5de46cbd09a181c177f6a14cc206cbbeaf3b1b29c` is the sha256 of the sorted `symbol|type` lines, one per line with a trailing newline, that the list at L = 2026-11-09 places (13,103 lines), taken from the data on 2026-11-20 before any closed-list month was built. The membership writer refuses, writing nothing, any month after L when the live set at L no longer hashes to it, so a later pit install or `ticker_event` write cannot admit an entrant; moving the constant is a dated amendment. No rule, floor or threshold changes, and no counted look is added.

## Amendment 2026-11-21 (PROPOSED, pending owner adoption; lead, security type once per security, pre-look: no return-based look at the universe has happened)

Status: proposed. Nothing is applied: migration 606 and the writer are built and rehearsed in a rolled-back transaction only. On adoption the lead records the owner ruling here and in the ledger. No frozen section above changes.

Why. The membership decided eligibility from the `type` field of the list row of each month-end, so a name with no label on a list, or no row on that list, was ineligible that month and lost its hysteresis state. Measured 2026-11-20: labels are missing on 62 percent of the 2008 list rows, 50 percent of 2012 and 47 percent of June 2016; the member count steps from 2,188 to 3,640 at 2016-10 with the label coverage, not the market; 1,289 symbols have gaps inside their span. Massive rebuilt its lists in 2025 (rows of the 2005 and 2016 lists carry `last_updated_utc` 2025), so a label is not point in time: it does not time a real event and was not known at its date. A security's type is persistent metadata, so it is resolved once.

Rule (pre-registered constants in `src/intelligence/security_type.py`, `TYPE_RULE_ID = security-type-2026-11-21`, not APR keys).
- One type per security (symbol), from every typed list row its own ticker carried on any captured list date (the ticker the symbol's live span places on that date), counted once per list date, written to the append-only table `security_type` (symbol, rule id, type, class conflict, evidence, source) by one writer.
- Class mapping, in this order: ETN, WARRANT, RIGHT, PFD, ADRP win over every other label, in that order; then the ETF class (ETF, INDEX, ETS, ETV; an instrument that trades has no index label, and 1,357 of 1,740 INDEX symbols also carry another ETF-class label); then FUND; then CS or ADRC by list-date count (CS on a tie); then UNIT; then any other label by count. `ELIGIBLE_TYPES` (CS, ADRC, ETF) and every floor, window and price element above are unchanged.
- A security that no list typed has no row and is not eligible. A missing label is never filled or guessed. Name patterns, ticker-only overview records and a name fallback (the B pattern) are not adopted: B reached precision 0.9944 in sample but 0.9721 on names last listed before 2013, and the untyped residual is early-era and dead.
- `RULE_ID` becomes `stage2-2026-11-21`. The membership writer reads `security_type`, refuses to build while it holds no row for the rule, keeps the snapshot completeness check for the list of each month-end, and drops the alphabetical tie-break between two rows of one date. Months after L read the table restricted to the securities the list at L places (item 1 of the 2026-11-18 amendment is unchanged: a security the list at L does not place is not a member at any later t). The writer reads only lists dated up to L and raises on a later one, and a re-run recomputes the rows and raises when they differ from the stored ones.
- `CLOSED_LIST_CANDIDATES_SHA256` is re-pinned to the sha256 of the sorted `symbol|type` lines (trailing newline each) of the securities the list at L places (13,103, each with its `security_type` under the rule; the whole table holds 29,204 securities, digest `6a9168f46cb217c4a316d55bf8acc882373ffb1019b4a82bb2cc2260404380b3`): `730622aeeafca7eb60329980a979df1cfda8d334428aab0cde9a4913f1c2586b`, 13,103 lines, from a rolled-back rehearsal on the data of 2026-11-21. The placement install changes the spans the labels attach through, so the pin moves once more after it (runbook step 7), by a dated entry here.

Disclosures (disclosed, none gated).
- Temporal integrity: the type of a security is the vendor's present reading of it and may postdate the month-end it is applied to (a name that changed class after t carries one type throughout). Disagreement is counted, not hidden: 823 of 29,204 typed securities carry labels from more than one class (`class_conflict`; 557 carry both FUND and CS, and a business development company labelled FUND is a known error), and the carry disagreement counts measured on 2026-11-20 are 11 to 16 per tested date.
- Survivorship direction: a security of the early, sparsely labelled era is eligible only if some list, early or late, typed it, so a name that lived into the well-labelled era is typed back to 2003 while a name that died untyped stays out. Early-era membership therefore tilts toward names that survived to be labelled, a known-sign look-ahead on the type, the survivorship this universe exists to remove, in the early years only. It is disclosed here and at every freeze; the share of early-era member-days that rest on a type taken only from a later list is not measured.
- Untyped remainder: 6,026 placed securities have no typed row in any list; the untyped residual at December 31 is 2,230 (2004), 1,581 (2008), 706 (2012), 24 (2016), 46 (2020), 0 (2024), all inactive names. They stay out of the membership. A capture to type them (OpenFIGI reaches 259 of the 6,026, all inactive and early-era) is dropped by materiality (lead ruling 2026-11-21).
- Member counts, rehearsal on the current spans (before the placement install), hysteresis walked from 2003-09: 3,007 at 2008-06-30 (2,138 under the label rule), 3,129 at 2012-06-29 (2,023), 3,824 at 2016-09-30 (2,188). The highest month-end count by year: 1,988 (2003), 2,283 (2004), 2,527 (2005), 2,753 (2006), 2,986 (2007), 3,037 (2008), 2,846 (2009), 3,014 (2010), 3,204 (2011), 3,139 (2012), 3,500 (2013), 3,804 (2014), 3,913 (2015), 3,887 (2016). Years whose maximum stays under the 2,950 lower end of the 2026-11-12 sizing (2003 to 2006 and 2009) are disclosed, not gated and not chased; the gap that remains is untyped inactive names and the placement install.

No rule floor, window or price value changes, and no counted look or series is added.

