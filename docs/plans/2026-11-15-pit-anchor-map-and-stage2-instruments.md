# Pit-anchor identity map and stage 2 instrument rows

Author: worker indicagent-7d for the lead, 2026-11-15. Resolves todo 609 gaps G1 and G2.
Status: DRAFT. Section 1 is an amendment text for `2026-11-13-stage2-universe-preregistration.md`; it changes nothing until the lead adopts it, before any return-based look at the universe. Sections 2 to 6 are the implementation design. Nothing here has run against live data except read-only profiles.

## 0. Measured facts (2026-11-15, read-only, 558 snapshots)

`reference_raw_current` holds 6,132 `pit_snapshots` pages: one `@active` and one `@inactive` list for each of 279 month-ends from 2003-09-30. Per `@active` snapshot about 8,000 records in 2003 and 13,000 to 14,000 in 2026 (13,241 in the last, 2026-11-09), no ticker twice in one snapshot, 33,280 distinct tickers over the capture, 7,252 of them with more than one key over time. The year rows below count records over all of a year's snapshots.

| Year | records | composite FIGI | CIK | `type` served | no CIK and no FIGI |
|---|---|---|---|---|---|
| 2003 | 32,738 | 24% | 83% | 1% | 15.8% |
| 2010 | 92,560 | 40% | 90% | 64% | 9.1% |
| 2016 | 99,630 | 60% | 94% | 74% | 4.5% |
| 2020 | 108,188 | 77% | 94% | 99% | 1.9% |
| 2026 | 141,042 | 82% | 87% | 100% | 0.1% |

`@inactive` records carry a CIK for 2.57M of 3.31M rows, a `delisted_utc`, and no FIGI. Two consequences. A FIGI-only anchor would leave most pre-2012 names unplaced, which is the survivorship stage 2 exists to remove, so the CIK key of the 2026-11-13 amendment is required. And `type` is served for only 1 to 66 percent of records before 2017, so it cannot be part of an identity key without splitting a continuous listing in two when the vendor starts serving it.

## 1. Amendment draft (dated 2026-11-15, pre-look)

> Amendment 2026-11-15 (pit-anchor identity details). No return-based look at the universe has happened. The 2026-11-13 key rule stands (composite FIGI; where absent, CIK plus share class). Details it left open:
>
> 1. Key kinds. A record's key is its composite FIGI when served (kind `composite_figi`); otherwise its CIK together with its ticker string (kind `cik_ticker`). The share-class FIGI is stored as an identifier when served and decides nothing. `type` is evidence, never identity: it is recorded per span and the membership rule reads it from the snapshot at t.
> 2. One key per record, one ticker per key. A ticker string appears once in a snapshot, so every record has exactly one key. A composite FIGI served under two tickers in one snapshot is claimed twice: both records are unplaced for that month-end, whatever the reason.
> 3. Runs. A ticker's consecutive month-ends form one run while the identity holds. A record is compared with the run's accumulated identity (the first composite FIGI and CIK the run has seen): two composite FIGIs must be equal; otherwise (one side lacks a composite FIGI, or both do) the two CIKs must be equal and present. A ticker missing from exactly one month-end between two observations of one identity (absent from the active list, or its record dropped as claimed twice) is bridged: one run, the month counted in `bridged_months`; a missing month in which another record with no key held the ticker is not bridged. A run ends at the first month-end where the ticker is absent for two in a row or the identity breaks; a ticker whose identity breaks is two securities. A composite-only record followed by a CIK-only record of the same security is such a break and is counted, not merged.
> 4. Securities. Runs that share a composite FIGI are one security (a rename). A run with no composite FIGI is the security `(CIK, ticker)`; runs of one pair are one security. A run with neither a CIK nor a composite FIGI is unplaced.
> 5. Span boundaries. A span starts at the first month-end of the run (at the archive start, 2003-09-10, when the run is present in the first snapshot) and ends at the delisting date of the `@inactive` record of the same ticker and CIK when that date falls after the last month-end and not after the first month-end the ticker is absent from; with no such date it ends at that first absent month-end, exclusive, when the ticker left the list with no other holder in its place, and the day after the last month-end when another holder took the ticker at that month-end; a run present in the last snapshot is open. A run present in the first snapshot starts at the latest delisting date, inside the archive window, of another holder of the ticker (an `@inactive` record with a different CIK), else at the archive start. The days between a ticker's last month-end and the next holder's first month-end are in no span: a bar there belongs to no named security. This costs at most one month of listing history and delisting tail per run; it never gives a bar to the wrong holder.
> 6. Additive only. A pit run whose composite FIGI (or share-class FIGI) is a live identifier is left to the live map and counted as `already_live`; so is every run of the key of the latest holder, in the capture, of a ticker string that is an instrument symbol with no live span (the stage 1 gap-list names: 125 active equity instruments hold a ticker and no span, and ten of them, such as ROKU and KVUE, have already left the vendor's active list; a second, inactive instrument would split the name). An instrument that has spans does not claim a new holder's run. A ticker string held by a live span in a window is not assigned to a pit security in that window.
> 7. Reported before membership: unplaced share of records by year and by served `type` (`unplaced` = no key, claimed twice, clipped by a live span), and the securities and spans added, written into the map's `map_diff.json`.

### Revision 2026-11-16 (indicagent-65, review of the first build; pre-look, before adoption)

Measured on the first build (33,937 securities, 37,684 pit spans, 25,983 closed): 3,361 closed spans (13 percent) had no delisting date and ended the day after the last month-end, so the final partial month of bars of a delisting fell outside every span, which is the failure mode "a member that vanishes without a final bar" the preregistration lists; and 1,326 consecutive spans of one security under one ticker were separated by a gap of 70 days or less (751 of 35 days or less), about 55,600 calendar days of bars in no span inside continuous listings, mostly one dropped month. The delisting boundary itself was checked against the day files: for 35 of 35 sampled 2019 common-stock delistings with bars near the date the last bar is before `delisted_utc`, never on it, so an exclusive end at the delisting date is right. Items 3 and 5 above now carry the bridging and the absent-month end rule; the plan reports `bridged_months` and `cik_renames_split` (names with no composite FIGI whose CIK continues under another ticker within 70 days, which the key rule leaves as two securities). The first month of a listing (between the previous month-end and a run's first month-end) is still outside its span; that loss delays membership entry by at most a month and is disclosed, not fixed here.

## 2. What exists and what is added

The pure planner is `src/intelligence/bars/ticker_entity_map_pit.py`: snapshots in, runs, securities, spans and accounting out. No I/O, no clock, the same inputs give byte-identical output. `services/ticker_entity_map_writer.py` gains `--pit-anchor` (builds a scratch map directory, reads only) and `--pit-install` (rebuilds the plan from live inputs, refuses unless it equals the directory, then writes; rehearsal unless `--apply`). Rollback is the existing `--rollback INSTALL_ID`, extended to retire the identifiers a pit install inserted. `src/config/instrument_onboarding.py` gains `onboard_stage2_instruments()`, the one writer of the stage 2 instrument rows.

Map directory contract: the same five files and the same pins as the installed map. `gap_list.csv` is the pinned map's list, unchanged (so the directory digest is unchanged and the date part is the version date). `pinned_spans.csv` is every live span. `spans.csv` is the pinned spans (origin `kept`) plus the pit spans (origin `pit`). `span_accounting.csv` has one row per pit run with its disposition. `map_diff.json` records the pins: the sha256 of the pit snapshot rows (id and file sha256, sorted), the live spans, the live identifiers, the planner's rule id, and the residual report of section 1 item 7.

## 3. Schema

Migration 598 adds identifier scheme `cik_ticker` (value `<10-digit CIK>:<ticker>`) to `security_identifier`'s scheme check and value-format check. `ticker_event.security_identifier_id` is NOT NULL and the scheme set has no CIK scheme, so without it a FIGI-less security cannot hold a span. No data moves and no compressed table is touched, so no `VACUUM` clause is owed. Numbered 598 on 2026-11-15; renumber at landing (`tools/gate.py` stops on a clash).

Migration 601 (numbered 601 because 599 is the R2 cluster's; renumber at landing) adds a partial index on `ticker_event (security_identifier_id) WHERE retired_at IS NULL`. The identity trigger probes `ticker_event` once for every identifier a rollback retires; without the index that probe is a sequential scan, measured 10.3 ms on 39,600 rows against 0.01 ms with the index, so the rehearsal's rollback of 47,674 identifiers costs about 8 minutes without it.

## 4. Symbols and instrument rows (the SOP exception)

`instruments.symbol` is the primary key and a reused ticker is two securities. The symbol of a new security is its ticker string when no instrument row has that symbol and no earlier-starting new security in the build takes it; otherwise `<TICKER>~<8 characters of the key value>`. The symbol is fixed at insertion and recorded in `spans.csv`; a later build reads the existing rows and never renames one.

The SOP exception (the design reserved it for stage 2; this note defines it for the lead's ruling): the stage 2 rows go in through `onboard_stage2_instruments()`, in the module that is already the single writer of `instruments`, instead of `onboard_instrument()`, because `onboard_instrument()` requires an IBKR qualification, a sector-level classification and sets `is_active` true. The exception differs in exactly these ways:

1. Qualified by the pit map's placement (its span evidence), not by IBKR.
2. `is_active` false, `compute_eligible`, `compute_eligible_1d` and `live_tradeable` false (the check constraint requires it), `universe_cohort` `stage2_pit`, `universe_entry_date` the install day. No name becomes a capture target by this path: the Alpaca nightly reads active instruments only. A name enters capture later by its own promotion.
3. No classification, tag or metadata rows: the vendor gives no sector for a dead name and a guessed one would be a hand-written fact. The rows carry `provider_meta` with the key, the first and last month-end and the served types, so the absence is on the row.
4. Rerun-safe: an existing row of cohort `stage2_pit` with the same key is accepted; any other existing row with the symbol refuses the run.

Rule 6 of the SOP (a name is never deleted or deactivated) holds: nothing here deactivates or deletes. A rollback retires the spans and identifiers and leaves the inactive instrument rows in place (the foreign keys restrict deleting them).

## 5. Rollback and pins

The install is one transaction under the `ticker_event` table lock, after `require_massive_quiet`. It inserts instrument rows, identifiers and spans, then checks the live span set equals the map's span set. Each span's evidence carries `map_install` (install id, map digest, rows inserted, the pre-install sha256 of the live rows, `new_symbol` where the install created the instrument). `--rollback` retires the spans by install id, retires the identifiers of the `new_symbol` securities, and checks the live rows again hash to the pre-install value.

## 6. Failure modes designed against

- A bar loaded under the wrong holder of a reused ticker: spans never cover a month the ticker was not observed with that key; the gap months are in no span.
- A silent merge of two share classes: CIK-only keys include the ticker, and a composite FIGI claimed twice in a snapshot is unplaced.
- A screen on history or returns: the planner reads identifiers and dates only; no bar, no price, no volume.
- A hardcoded name list: none; every decision is a function of the snapshots and the live tables.
- A missing month in the capture bridging two runs: consecutive snapshot dates more than 35 days apart refuse the build.
- A partial capture: a month-end without both lists, contiguous pages, an OK status and a last page without `next_url` refuses the build.
- Touching live tables outside a rehearsal: the build reads only; the install is a rolled-back rehearsal unless `--apply`.

## 7. Not decided here

- Install timing (lead ruling 2026-11-16). The install runs after step 7 D4 at the capture's last snapshot, 2026-11-09, so the stage 2 membership list L of `docs/plans/2026-11-15-stage2-membership-after-archive-end-amendment-draft.md` is 2026-11-09. The planner is not additive: an installed pit security's open run is `already_live` to a later plan, and extending or closing it would rewrite installed spans, so a later list (2026-11-30) is raw evidence only. An extend-only planner (new securities and new spans after the installed map, never editing one) is a possible follow-up with its own amendment; it is not built.
- Residual by liquidity. The by-year report counts month-end records. The preregistration asks for the unplaced share of rows that meet the $1M rule, by year and type; `scripts/ops/bars/ops_pit_unplaced_share.py` measures it from the day files, the snapshot types and the installed spans (close level, volume and dates only), and step s4b of `run_609.sh` runs it before membership is built and shows the table to the owner.
- The pit map is a one-time install at the capture's last snapshot. A later capture cannot extend or close an installed pit security (its open run is `already_live`, and a reused ticker after a delisting would be clipped by the open span). Extending a pit security needs its own amendment; the residual report names the open pit spans.
- Splitting a continuous listing at a vendor key upgrade where the CIKs differ is accepted as two securities; the residual report counts it.
- `share_class_figi` as a rename-linking key: not used (composite FIGI already links renames).
- The membership writer's price, type and liquidity tests are unchanged and read the snapshot at t; this note only supplies the names, spans and instrument rows they join to.
