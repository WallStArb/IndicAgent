---
status: pending
priority: P1
filed: 2026-11-12
source: owner 2026-11-12 ("30,000++ securities from Massive, 1,500 on IBKR"); todo 600 stage 2; lead ruling
---

# Stage 2 universe: a point-in-time, survivorship-free universe from the Massive archive

## Why

The archive holds 30,000+ tickers over 2003-2026; our canonical universe is 1,529 current names (stage 1 only deepens their history, it does not remove survivorship or add breadth). Breadth (more independent bets) and a survivorship-free sample are the two largest levers on finding significant edge, and the archive is already paid for and verified. Measured 2026-11-12 on the day files: a typical session carries about 10,500 tickers in 2024 and 7,800 in 2008 and 2015; names with close x volume above $1M a day number about 4,900 (2024) and 4,500 (2015), above $10M about 2,600 and 2,300, above $100M about 800 and 600. So the investable set is a few thousand names a day, not 30,000; the rest is warrants, units, preferreds, ETNs and micro-caps.

## Measured 2026-11-12 (the proposed rule on the 50.2M day-file rows, 36,735 tickers, month-end membership)

Rule: month-end t, 60-session median of close x volume at or above the floor, close at or above $1, at least 60 sessions. Matched to our 1,529 by ticker symbol (a reused ticker can match falsely), no security-type filter yet (a plain-ticker proxy, letters only and at most 5 characters, barely moves the counts).

| Floor | Distinct names ever in | Already ours | NEW | Members per month-end (median, min, max) |
|---|---|---|---|---|
| $1M | 16,045 | 1,525 | 14,520 | 4,154 (2,947 to 6,041) |
| $5M | 10,231 | 1,481 | 8,750 | 2,616 (1,588 to 4,169) |
| $10M (proposed) | 8,003 | 1,448 | 6,555 | 2,026 (1,033 to 3,454) |
| $25M | 5,525 | 1,355 | 4,170 | 1,313 (571 to 2,539) |

At the proposed $10M floor about 6,555 securities are new (dead and merged names, and names that were never on our list), about 2,000 are members at any month-end, and 1,448 of our 1,529 qualify. Owner 2026-11-12 agreed with this sizing; the floor itself is preregistered before any look. Ongoing capture for the new names after the Massive plan lapses is Alpaca (same upstream, nightly SIP); Massive plus Alpaca covers history and the forward feed.

## Ruling (lead 2026-11-12)

1. Raw is permanent and complete at 1d: load the 1d day files for every ticker in the archive into `ohlcv_raw` (about 50M rows, trivial). 5m is NOT loaded for all names (billions of rows); it follows the tier below.
2. The research universe is a rule, never a screen on returns: a point-in-time `universe_membership` table (month-end, as of t) built from Massive's own data. Proposed rule, frozen in a preregistration before any look and its thresholds APR keys: security type common stock or ETF from the Massive reference types; trailing 60-session median dollar volume at or above a floor (start at $10M, about 2,600 names a day); close at or above $1; at least 60 sessions of history. Delisted and merged names stay in while they meet the rule on the date, which is what removes survivorship.
3. Identity: the key rule for reused tickers uses the entity map (FIGI, ticker events, spans); a reused ticker is two securities. Dead-name instrument rows go through the onboarding SOP exception the design reserved for stage 2 (owner-approved, recorded); never hand-written `instruments` rows.
4. Tiers by cost: 1d for the whole membership (cheap, the first counted tests on daily families run here); 5m only for names in the top liquidity tier, sized by a measured `feature_vectors` cost estimate (5m is about 69 percent of the table today).
5. Executability: the floor is also the tradability floor for a personal book (spread, borrow); costs never enter a test statistic, but names below the floor are out of promotion.

6. IC comparability (owner question 2026-11-12). IC is cross-sectional per date over that date's members; what stays fixed is the rule and each security's identity key, not the name list (a frozen list is the survivorship bias). Four design points: (a) every feature tests on two panels, the point-in-time universe and a constant core (names that qualify throughout, close to today's list), so a universe effect separates from a feature effect on the same securities; (b) hysteresis (enter at the floor, leave at half of it) keeps the cross-section stable and N steady; (c) features compute on every name with 1d data, membership only gates the IC panel, so a name entering already has warmed features; (d) the 5m tier nests inside the membership, so 1d and 5m results compare on the same securities. The universe rule is part of the spec hash and snapshot pin.

## Failure modes to design against

Choosing the floor or type filter after seeing results (it is a counted design choice; fix it first); ticker reuse mixing two companies; point-in-time leakage (membership uses only data known at t, including the dollar-volume window); stage 2 loads moving canonical before step 7 proves; universe growth silently multiplying corpus compute (gate on the measured estimate); a delisted name's final bars (delisting return) missing from 1d.

## Gates

Step 7 and the 8a checks pass first (stage 1 is the data gate; this does not jump it). Then: the membership rule preregistered and recorded; the membership table built and its count by year reported; 1d raw loaded for all tickers with the load-engine gate per year (compare 0 real differences, canonical unchanged); a cost estimate for 5m and feature compute at the proposed tiers; owner sees the count by year before any compute.

## Preregistration draft (2026-11-13)

`docs/plans/2026-11-13-stage2-universe-preregistration.md` (ADOPTED by the owner 2026-11-13: $1M in, $0.5M out, about 4,150 members a day; stocks, ADRs and ETFs; core panel 90 percent). Owner 2026-11-13: "we will expand the universe". Changes from the ruling above: identity is Massive's entity map only (IBKR removed), and the rule values are research-design constants in the preregistration and the spec hash, not APR keys.

## Next step

After 8a and step 7: write the preregistration (rule, thresholds, type source) and the 1d all-ticker load plan; extend `ops_massive_load.py` with an `--all-tickers` mode behind the identity map. Design hook: `docs/plans/2026-11-10-massive-admission-db-design.md` section 8b stage 2 and section 11.

## Blocker I2: the 5m tier and the intraday corpus universe (draft 2026-11-15)

The corpus universe (every name ever a member) must not feed the 5m data gate: a 1d-only name would fail its 5m term. Draft amendment (5m tier: member and 60-session median at or above $25M in, $12.5M out), the intraday variant of `corpus_universe`, the gate change with exact files and code-key impact, and the order against I1 and the corpus rerun pin: `docs/plans/2026-11-15-stage2-5m-tier-and-intraday-universe.md`. Not applied; owner adoption comes first.

## Status 2026-11-16 (indicagent-65)

- Pit-anchor identity map and the stage 2 instrument writer (gaps G1 and G2) are built, independently reviewed and fixed in the held worktree `wt-pit-map`. Review fixes: a single missing month-end inside a listing is bridged, a span with no delisting date ends at the first absent month-end (the final bars of a delisting are inside it), and renames of names with no composite FIGI are counted (`bridged_months`, `cik_renames_split`). Design and the dated revision: `docs/plans/2026-11-15-pit-anchor-map-and-stage2-instruments.md`.
- Rulings (lead, 2026-11-16): install after D4 at the 2026-11-09 anchor, with a rolled-back rehearsal first; the planner is not additive, so L = 2026-11-09 for the closed-list membership rule (`docs/plans/2026-11-15-stage2-membership-after-archive-end-amendment-draft.md`, pending adoption).
- `run_609.sh`: s2 builds the scratch map, s3 rehearses then applies the install, s4b measures the unplaced share of rows at or above the $1M floor by year and type (`scripts/ops/bars/ops_pit_unplaced_share.py`) and shows it to the owner before membership (s5) is built. They run only after the branch lands.
- Index migration for the identity-trigger probe: numbered 601 in the worktree (599 is the R2 cluster's); renumber at landing. Owner gates: `docs/plans/2026-11-16-609-owner-gates-summary.md`.

## Build status 2026-11-15 (lane L3, synthetic data only)

Code landed, not applied: migration 597 (`universe_membership`, `universe_membership_build`, insert-only), the pure rule `src/intelligence/universe_membership.py` (preregistered constants, `RULE_ID`), the single writer `services/universe_membership_writer.py` (rehearsal by default, `--through DAY`, `--apply`), and `services/corpus_universe.py`, which `corpus_rerun`, `corpus_rerun_data_gate` and `backfill_feature_factory._stage_context` now read as the compute universe (every symbol that was ever a member; no fallback to `compute_1d`, an empty ledger raises). Design: `docs/plans/2026-11-15-universe-membership-design.md`.

Still open: apply 597 after step 7; real build and member count by year to the owner (gate 5); the `proven_start_1d` verdict facts for the new names (the compute universe skips a name with no proven start); gating the S0 IC panel on membership at each date (a `src/intelligence/research` edit, needs `repro_frozen`); the core panel (90 percent of month-ends).

## Blocker I1 (review 2026-11-15): the IC universe differs from the corpus universe

The corpus now computes over `universe_membership` (`services/corpus_universe.py`), but the IC measurement still reads the `compute_eligible*` flags: `services/ic_measure.py:1158` (`_symbols` calls `snapshot.universe_symbols`) and `src/intelligence/research/snapshot.py` (`universe_symbols` and `_DAILY_UNSEEN_SQL`). A membership-universe corpus would be measured on another name set. `corpus_rerun.check_ic_universe_aligned` (a precondition in `rebuild_precondition_results`) imports both modules and fails loudly until each declares a module-level `UNIVERSE_SOURCE` that is `corpus_universe`. The fix edits `src/intelligence/research/snapshot.py`, so it waits for step 7 to finish and needs `repro_frozen` bit-identical (or a methodology-change entry), plus gating each date's IC panel on membership at that date.
