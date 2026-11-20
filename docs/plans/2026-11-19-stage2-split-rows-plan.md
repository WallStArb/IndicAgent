# Stage 2 split rows plan (todo 646)

Status: proposed 2026-11-19, read-only measurement only; no `corporate_action` row written, no derivation run.

## Decision

Record the stage 2 names' splits through the path the active names used: Massive splits reference (the two captured families, `reference_raw`, 2026-11-10) as the event source, the name's own Massive unadjusted 1d tape as the confirming witness, `ops_massive_split_audit.py` to propose and `ops_split_calendar_audit.py --apply-massive` to write `massive_reference` rows. The only change is scope: the audit's reconciliation and attribution read `instruments WHERE is_active` (`_ACTIVE_SQL`, `OWN_ATTRIBUTIONS` through the events chain) and must read the stage 2 names, attributing by `ticker_event` spans (33,828 of the 33,850 inactive names have unretired spans), never by ticker label. A price jump alone never becomes a row.

## What the active names did

The 913 current rows (929 recorded) are 504 `massive_reference`, 393 `calendar_audit` (Yahoo calendar, confirmed against raw), 15 `calendar_market`, 1 `operator`. `massive_reference` rows are proposed by the audit (event attributed to the instrument, ratio a recognised split ratio, tape confirms at the vendor's date), written with `recorded_at` = the capture's `served_at`, and every cited `reference_raw` page must exist. `ops_split_detect` is only the by-hand supersede, void and hold tool. The A3 sweep `--strict` gate counts active names only; it refuses the Massive witness (a Massive bar cannot witness itself) and needs the Yahoo witness.

## Sources that carry ratios for the dead names

The Massive reference is not active-only: `/v3/reference/splits` holds 28,880 events on 19,557 tickers and the bulk family (`splits/20261110/*.gz`) 28,005 events on 18,866 tickers (reverse_split 15,981, forward_split 8,269, stock_dividend 3,755), 1978 to 2027, both in `reference_raw` and `data/massive/reference/splits/`. Yahoo's calendar needs a live fetch and is thin for delisted names; treat it as a second witness where it answers, not a requirement.

## Measurement (read-only, raw massive sip_flat 1d)

Inactive names in `universe_membership`: 11,163 of 12,561 (the rest are active). Events matched by ticker label with dots removed (an upper bound; reused tickers and dotted keys such as `ACV.A` need span attribution). A tape check takes the day-to-day close ratio within 3 days of the execution date and within ln 0.25 of the event ratio; events whose ratio sits inside 0.833 to 1.2, or whose date is outside the name's raw span, are not testable.

| group | events | names | outside raw span | ratio near 1 | testable | tape confirmed | unconfirmed |
|---|---|---|---|---|---|---|---|
| tier_5m ever | 1,707 | 943 | 448 | 166 | 1,093 | 999 (647 names) | 94 (80 names) |
| non-tier members | 3,018 | 1,724 | 974 | 178 | 1,866 | 1,582 (1,108 names) | 284 (232 names) |

So about 2,580 confirmable events on about 1,755 names, against 913 current rows for the whole active set. Price-first view: close-to-close steps above 20 percent that snap to a recognised ratio (max numerator 50, denominator 4, tolerance 0.002) with no Massive event within 3 days: tier 1,610 step-days on 955 names, non-tier 3,674 on 1,962 names. These are mostly real moves, bad bars and reused-ticker joins, not splits; they are the unresolved list, not a source of rows.

## Review rule

1. A row needs a Massive event attributed by span to the instrument, a recognised ratio, the tape step at the vendor's date, and `execution_date <= 2026-10-30` or served before the capture (the audit's `announced` and `before_archive` classes stay listed).
2. Tape-unconfirmed events (378 names) are not written; stock_dividend events with a flat tape are expected and listed. An event unconfirmed in the tape but with a Yahoo calendar answer is judged by the calendar audit path.
3. Tape steps with no event (the 1,610 and 3,674 above) get no row. The names stay on the unresolved list; the existing `unconfirmed_split` quarantine rule applies where a calendar split is left unconfirmed. A pin prerequisite is a count of these among the 4,938 tier names, reported to the owner.
4. The owner reviews a sample before the commit: all tier names with an event of ratio above 20 or below 0.05, 50 random others, and every dotted-key name.
5. Independent review of the code change (scope only) and a dry run listing before `--commit`; dividends stay unknown, never zero.

## Run cost

Proposal run: reads the reference pages and the 1d tape of about 12,500 names; the active audit took 59 s for 1,529 names, so under 10 minutes here. The measurement above took 35 s of SQL. Writing: about 2,600 rows in one transaction. Derivation: `services.bar_derivation --stage daily --symbols` for about 1,755 names, light next to the 5m runs; one heavy job at a time, outside 04:40Z to 06:00Z. Then the sweep over the stage 2 names (witness Yahoo) and `--strict` extended to them (an `--include-inactive` rule, ledgered), added to the `run_609.sh` s8 pin prerequisites.

## Open questions only the owner can settle

1. Is a tape-unconfirmed Massive event (about 378 names) left unrecorded, or does it need the Yahoo calendar before the pin?
2. Do the 4,938 tier names gate the pin alone, or all 11,163 inactive members?
3. Does `--strict` cover inactive names permanently, or only these members?
