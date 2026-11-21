# Stage 2: the 5m tier, the intraday corpus universe, and their sequencing

Author: worker indicagent-c6 for the lead, 2026-11-15. Resolves todo 609 blocker I2.
Status: Part 1 is ADOPTED 2026-11-18 (owner decision taken through the lead): the 5m tier amendment of `2026-11-13-stage2-universe-preregistration.md` (recorded there as Amendment 2026-11-18), adopted before any return-based look at the universe. Parts 2 and 3 are the design and the order.

## The problem

`corpus_universe` (todo 609, lane L3) returns every name ever in `universe_membership`, about 16,000 names, and the corpus rerun uses that one list for every timeframe. The data gate's 5m term fails a name-year whose 5m-uncovered share passes `max_missing_session_fraction`, and the intraday verdict scan runs over the same list. The preregistration loads 5m only for a top liquidity tier whose size it leaves to a later amendment. A 1d-only name would fail the 5m term. The fix needs the tier defined first (Part 1), then an intraday variant of the universe and a gate that uses it (Part 2).

## Part 1: amendment draft (dated 2026-11-15, pre-look)

Text to append to the preregistration if the owner adopts it.

> Amendment 2026-11-15 (5m tier). No return-based look at the universe has happened.
>
> Tier rule. At each NYSE month-end t, a security is in the 5m tier when it is a member at t (every membership condition holds) and its trailing 60-session median of close x volume is at or above $25M to enter, and a tier member stays while it is at or above $12.5M (half the entry floor, the same hysteresis ratio as membership). Tier state carries forward month to month separately from membership state. The tier is nested in the membership by construction and is decided from data known at t only. The values are research-design constants of the preregistration and the spec hash, not APR keys, and `RULE_ID` is bumped for them.
>
> Loading and compute. 5m is loaded and computed for every name that is in the tier at any month-end, over its whole 5m history (features arrive warmed when a name enters the tier, as for 1d). A name outside the tier has no 5m features and is outside every 5m result. 1d covers the whole membership. IC on 5m is gated by tier membership at each date the way 1d is gated by membership; the constant core panel for 5m is the names in the tier at 90 percent or more of the vintage's month-ends.
>
> The measured cost estimate (rows per name-year, feature-compute time per name-year, and disk) is taken on the 5m already loaded for the current names and recorded here before the first tier load; it can lower the floor's reach only through a new dated amendment, never by choosing a floor after seeing results.

### Why $25M and $12.5M

Chosen from the 2026-11-12 sizing table (single floor, no hysteresis, day files) and arithmetic on it; nothing here looks at returns.

| Floor | Names ever in | Already ours | New | Members per month-end (median, min, max) |
|---|---|---|---|---|
| $10M | 8,003 | 1,448 | 6,555 | 2,026 (1,033 to 3,454) |
| $25M (chosen) | 5,525 | 1,355 | 4,170 | 1,313 (571 to 2,539) |
| $100M (2024 and 2015 counts only) | not measured | not measured | not measured | about 800 and 600 |

1. Intraday executability is the binding reason, and the membership floor does not cover it. A 5m bar of a name trading $1M a day averages about $13k ($1M over 78 bars); a $25k position (the preregistration's own example at 2.5 percent of daily volume) is about 190 percent of one 5m bar's dollar volume. At $25M a day the average bar is about $320k and the same position is about 8 percent of it. A 5m signal on a name below the tier cannot be traded at the horizon it was learned on, and its bars are also the sparsest (Massive emits no bar for a bucket without trades, and the loader never fills), so its 5m features carry the most NaN. The preregistration already ruled that the tradability floor is the floor of the promoted set; this sets it per timeframe.
2. Cost stays near today's. The tier's member-month name-years are about 1,313 x 23.2 years = 30.5k. Loading whole histories of every name that is ever in the tier is larger, planning figure 46k name-years (1.5x, since a name's tier months are a part of its life). At most 78 x 252 = 19.7k RTH rows a name-year (fewer for sparse names) that is 0.6 to 0.9 billion 5m rows. Today's corpus is at most 1,529 names x 23 years = 35k name-years, about 0.7 billion rows. So the tier is about the same 5m volume as the corpus that is already planned, and it removes the survivorship the 1,529 carry. The $10M floor would be 47k member-month name-years (about 70k whole-history), twice today. The planning figures are arithmetic on the sizing table and are replaced by the measured estimate before any load.
3. Continuity with what step 7 loads. 1,355 of our 1,529 names qualify at $25M (89 percent), so almost all 5m already in raw is inside the tier; the 174 current names below it keep their raw 5m (raw is permanent) and are simply outside the 5m corpus, which is the rule applied to them, not an exception.
4. Breadth is not lost where it matters. The membership stays at $1M for 1d, about 4,150 names a month-end; the tier is the part of it where an intraday signal can be traded. Both panels (point in time and constant core) exist at each tier.

### Sources and forward feed

- New tier names' 5m comes from the Massive minute archive already acquired (86.8 GB, every ticker, 2003-09-10 onward), aggregated by our reader to 5m (`sip_flat_agg`); no new vendor purchase, so the plan lapse about 2026-12-10 does not limit the tier. Before 2016 it is Massive only with no fallback, as for the current names. Names whose 5m is already in raw are not reloaded.
- Forward: the Alpaca nightly (`ops_bar_nightly.py`) reads every active instrument. A live tier name needs an active `instruments` row (the onboarding SOP's stage 2 exception, gate 4). The nightly's 5m volume is about the same as today's (the tier is the size of today's list), so its APR request budget is unchanged; a tier entrant mid-year is picked up by its instrument row and warmed from the archive.
- The one dated dependency is the point-in-time reference capture (`--pit-snapshots`, done 2026-11-13, 6,132 files under `data/massive/reference/pit_snapshots/20261113/`, not yet loaded into `reference_raw`): the membership, and so the tier, cannot be built without it, and it is not re-capturable after the plan lapses.

### Measured cost estimate, 2026-11-21 (recorded before the first tier load)

Taken after the stage 2 membership rebuild under rule `stage2-2026-11-21` (`run_609.sh s7`; files in `logs/massive_step7/post_step7_readiness_20261115/`). Rows per name-year on a 60-name hash sample (910 name-years, 2004 to 2025): median 19,470, mean 18,129, p90 19,620. The tier holds 5,192 securities ever, 33,734 name-years while a tier member and at least 62,227 whole-history name-years. Projected 5m rows: 0.66 billion on member years only, 1.21 billion on whole histories (62,227 x 19,470). The planning figure above (46k whole-history name-years, 0.6 to 0.9 billion rows) is exceeded by about 35 percent in name-years. Storage at the canonical ratio (24 GB for 702.7M rows across all timeframes) is about 41 GB compressed. Feature-compute time per name-year is not estimated here; the corpus pilot measures it.

## Part 2: design (the intraday variant and the gate)

Principle: one table, one writer, one rule for both. The tier is a column of the membership, never a second table.

### Files and changes

1. `production/migrations/597_universe_membership.sql` (lane L3, tip 4a168b75e, not applied): add `tier_5m boolean NOT NULL` to `universe_membership`, with the column comment. It is free before 597 is applied; after, it is a new migration. Nothing else in the migration moves.
2. `src/intelligence/universe_membership.py`: `MembershipRule` gains `tier_entry_floor = 25_000_000.0` and `tier_exit_floor = 12_500_000.0` (validated `0 < exit <= entry`, entry at or above the membership entry floor); `MembershipRow.tier_5m`; `decide` takes `was_tier` and sets `tier_5m` from the same median it already computes, so no second pass over the bars; `memberships_for_security` carries the tier state next to the membership state, and a name that leaves the membership resets both; `RULE_ID` becomes `stage2-2026-11-15`.
3. `services/universe_membership_writer.py`: the insert columns and record tuple gain `tier_5m`; the seed of a resumed build reads `symbol, tier_5m` from the last built month; the log reports members and tier members by year (the count by year the owner sees under gate 5 gets both columns).
4. `services/corpus_universe.py`: `corpus_universe(conn, *, intraday: bool = False)`. The default is every name ever a member (1d); `intraday=True` is every name with `tier_5m` true at any month-end. One shared SQL constant with a `WHERE` fragment, one ledger check, no fallback, same refusal on an empty ledger or table.
5. `services/corpus_rerun_data_gate.py`: `run_data_gate` builds `intraday = {c.symbol for c in corpus_universe(conn, intraday=True)}`. `evaluate` takes `intraday_names`; for a name outside it, segments are one 1d-only era (no 5m policy lookup, no `fetch_answers` pairs, no `record_session_bars`), the failing test is the 1d term only, and the era table gets a `1d_only` row counted separately so the report still shows every name. For a name inside it the term is unchanged. `names_checked` stays the whole universe and the result gains `intraday_names`, so the gate result says which names the 5m term judged.
6. `services/rebuild_preconditions.py` and `services/corpus_rerun.py::rebuild_precondition_results`: the intraday verdict scan (`fetch_bar_verdict_inputs`, which already narrows to `tfs` minus 1d) takes the intraday symbols; `fetch_d2_inputs` and the 1d checks keep the whole universe.
7. `services/backfill_feature_factory.py`: `_StageContext` gains `intraday: frozenset[str]` from `corpus_universe(conn, intraday=True)`. A helper `chunk_for(tf, chunk)` returns the chunk unchanged for 1d and filtered to the tier for an intraday tf; the three places that plan a (chunk, tf) group (`run_rebuild_stage`, `planned_units`, the compression bound loop at about lines 1342 to 1360) call `_plan_group` with `chunk_for(tf, chunk)` and treat an empty chunk as the existing empty group (`_plan_group` already returns None for one, counted under `empty_groups`). Chunking itself is unchanged, so 1d unit keys do not move.
8. `services/corpus_rerun.py::check_ic_universe_aligned` (L3): per timeframe once I1 lands; 1d against `corpus_universe(conn)`, 5m against the intraday variant.
9. Tests: the tier decision on synthetic bars (enters at $25M, stays between $12.5M and $25M, leaves below, resets on losing membership, tier implies member); the writer carries tier state across a resume; `corpus_universe(intraday=True)` is a subset of the default; the gate on a mixed synthetic universe passes a 1d-only name with no 5m, fails an intraday name with a 5m hole, and fails a 1d hole on either; `planned_units` for 5m omits non-tier names and leaves 1d unchanged; the precondition tripwire still fails loudly when a reader declares another source. Docs: the glossary entry for the tier, `docs/foundation/canonical-truth-registry.md` is untouched.

### Code-key impact

`rebuild_code_key()` hashes the writer's import closure. `services/backfill_feature_factory.py` and `services/corpus_universe.py` are in it (the factory imports the latter since L3), and `src/intelligence/universe_membership.py` is reached through the writer module, so items 2, 4 and 7 move the key. `corpus_rerun_data_gate.py`, `rebuild_preconditions.py` and `corpus_rerun.py` are read by the step runner, not by the units, so items 5, 6 and 8 do not move a unit key. The move is the same single move L3 already causes: none of this code is live today (L3 is held, no corpus run exists), so land items 1 to 9 in the same push as L3 or before the corpus rerun pin, and no edit to these files after the pin, because one edit afterwards discards every completed unit. 1d unit keys do not change from item 7 because 1d chunking is untouched; the 5m units are new in any case. No file under `src/intelligence/research/` or `statistics/` is touched, so `repro_frozen` is not triggered by Part 2.

### Gates

Unit suite exit code, ruff, black, glossary, the duplicate-test check, independent review, and a rehearsal build of the membership on a scratch database showing the tier count by year next to the member count.

## Part 3: sequencing

1. Part 1 amendment: ADOPTED 2026-11-18 (owner decision taken through the lead), a design choice counted under E18 before any look.
2. Step 7 Part C and D1 finish (running). Nothing in this plan touches what step 7 imports.
3. Fold Part 2 items 1 to 3 into the L3 branch while 597 is unapplied, with the amendment's `RULE_ID`; fold items 4 to 9 in the same branch. One independent review of the lot, then land after D1, with the L3 hold.
4. Load the reference snapshots into `reference_raw`, apply 597, run the identity-map rebuild and the dead-name instrument rows (preregistration gates 3 and 4 in their amended order), then the membership rehearsal. The owner sees the member and tier counts by year (gate 5) before any compute.
5. Measure the 5m cost on the loaded names, record the estimate as the amendment's last step, then load the tier's 5m from the archive with the load engine's per-year compare gate.
6. Land I1 (the IC wiring plan: mask, spec value, `ic_measure`). It must precede the corpus rerun, because `check_ic_universe_aligned` is a rebuild precondition and blocks the rerun until both readers declare the corpus source; 1d first, the 5m side reads the tier mask.
7. Then the A3 split sweep, the pre-rerun window (todos 551, 552, 558, 516), the 584 pin, the corpus rerun, and the first counted tests.

Order constraints in one line: amendment before the load; Part 2 code before the corpus rerun pin and never after; I1 before the rerun (the precondition) and before any counted IC; the plan lapse about 2026-12-10 binds only the reference capture, which is already on disk, so none of this races it, but load it into `reference_raw` early so a defect in the capture is found while a re-pull is still possible.
