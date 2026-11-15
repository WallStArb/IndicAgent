# Todo 516 re-verify plan, for after step 7 D1

**Status:** DRAFT 2026-11-15, read-only plan; no query below has run against post-step-7 data. Today the canonical 1d table is empty (step 7 is rebuilding it from raw), so the expected values below come from raw as it stands and from B4's `expected_after`; the plan runs after D1, once, and its output decides what is left of todo 516.
**Why:** readiness finding 7. Todo 516 was written for the IBKR d2-v2 world. After step 7 the 1d source is Massive under d2-v6, served as served (unadjusted route, rescaled only by market splits). Each of its three parts is re-judged against canonical before any effort is spent.
**Boundary:** every statement is a SELECT or a file read. No write, no `--release-hold`, no edit to `src/intelligence/bars/daily_rule.py` (a step 7 import). `PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent`.

## What the raw evidence already shows (2026-11-15, before step 7 finishes)

- Part 1 premise. CTVA's raw 1d closes around the spin-off, by vendor: Massive and Alpaca serve the as-traded series (2026-09-28 77.74, 09-29 77.87, 09-30 77.65, 10-01 12.57, 10-02 11.92). IBKR carries both the as-traded series and the 39/7-adjusted rewrite of the same dates (13.95, 13.98, 13.94 for 09-28 to 09-30). 13.94 is 77.65 x 7/39, the factor of the voided split row. Under the new policy neither IBKR series is read, so the rewrite that made the hold necessary never reaches canonical.
- Part 3 is already fixed. `daily_rule._stale_for` uses `obs.bar_date > split.effective_date` (`src/intelligence/bars/daily_rule.py:376`, comment: effective_date is the last day on the old scale), with a regression test at `tests/unit/bars/test_daily_rule.py:594` (d2-v5 fixed d2-v4's off-by-one). The todo text is stale on this point; the re-verify only confirms the test still passes.
- Part 2 names. Raw 1d rows today: MSM has Massive from 2003-09-10 (5,833 rows); IESC from 2016-05-26 (2,633); ELE only from 2025-11-25 (244, against IBKR from 2021-01-08); TIGO has none from Massive (Alpaca from 2019-01-09, 1,974). None has a canonical 1d row today.

## Queries and expected values

Run after D1 (`--verify` exited 0, so every (timeframe, month) of 1d already holds B4's `expected_after`). Replace nothing but `:archive_end` (the B4 `archive_end`, 2026-11-16 in `logs/massive_step7/delta_pre_reopen_20261115/switch_summary.json`).

**Q1, CTVA closes around the event are as traded.**
```sql
SELECT timestamp::date AS d, vendor, kind, close
FROM market_data_ohlcv
WHERE symbol = 'CTVA' AND timeframe = '1d' AND timestamp::date BETWEEN '2026-09-28' AND '2026-10-02'
ORDER BY 1;
```
Expected: five rows, vendor massive, closes 77.74, 77.87, 77.65, 12.57, 11.92 (the Massive raw values read from `ohlcv_raw`, which are final for dates inside the archive). Pass: all five within 0.005 of the raw Massive close, and none within 0.005 of 13.95, 13.98 or 13.94. Fail: any adjusted-by-39/7 value, a missing row, or a vendor other than massive.

**Q2, no CTVA bar is rewritten, over the whole hold span.**
```sql
SELECT count(*) AS n, count(*) FILTER (WHERE abs(c.close / r.close - 1) > 0.005) AS differing
FROM market_data_ohlcv c
JOIN ohlcv_raw r ON r.symbol = c.symbol AND r.timeframe = '1d' AND r.timestamp = c.timestamp
 AND r.vendor = 'massive' AND r.kind = 'sip_flat'
WHERE c.symbol = 'CTVA' AND c.timeframe = '1d' AND c.timestamp::date BETWEEN '2019-05-24' AND '2026-09-30';
```
Expected: n equal to the count of Massive raw sessions in the span (about 1,870; the raw total today is 1,875 distinct dates), differing 0. A CTVA split row would divide closes (the one recorded row is voided); the 2026-09-30 effective date is the last old-scale day, so no difference is expected. Pass: differing = 0. Fail: any difference; list the dates and read each against `corporate_action_current` for CTVA before anything else.

**Q3, the return across the event is the distribution, and nothing else rescaled it.**
```sql
SELECT (SELECT close FROM market_data_ohlcv WHERE symbol='CTVA' AND timeframe='1d' AND timestamp::date='2026-10-01')
     / (SELECT close FROM market_data_ohlcv WHERE symbol='CTVA' AND timeframe='1d' AND timestamp::date='2026-09-30') AS ratio;
```
Expected: 12.57 / 77.65 = 0.1619 (a -83.8 percent one-day move, as the todo records). Pass: within 0.001. This is the premise of part 1's research-layer half: the series is the right as-traded one and the crossing return is a distribution, not a loss.

**Q4, the hold and corporate action state (reads only).**
```sql
SELECT symbol, timeframe, reason, first_affected_date, last_affected_date, releases FROM bar_hold_current WHERE symbol = 'CTVA';
SELECT action_type, effective_date, factor FROM corporate_action_current WHERE symbol = 'CTVA';
```
Expected: the `unclassified_rescale` hold still listed, no live corporate action (the split row is voided, so `corporate_action_current` is empty for CTVA). Pass: as stated. Meaning: the hold is a record of the old problem; whether it still blocks anything after d2-v6 is read from `services/bar_hold.py` and the nightly's use of `bar_hold_current`, not assumed.

**Q5, part 2 names against the entity map and Massive rows.**
```sql
WITH n(symbol) AS (VALUES ('ELE'),('IESC'),('MSM'),('TIGO'))
SELECT n.symbol,
       count(c.*) AS canon_rows, min(c.timestamp)::date AS first, max(c.timestamp)::date AS last,
       (SELECT count(DISTINCT timestamp::date) FROM ohlcv_raw r WHERE r.symbol = n.symbol AND r.timeframe = '1d'
          AND r.vendor = 'massive' AND r.timestamp::date <= :archive_end) AS massive_sessions,
       (SELECT count(DISTINCT timestamp::date) FROM ohlcv_raw r WHERE r.symbol = n.symbol AND r.timeframe = '1d'
          AND r.vendor = 'alpaca' AND r.timestamp::date > :archive_end) AS alpaca_after
FROM n LEFT JOIN market_data_ohlcv c ON c.symbol = n.symbol AND c.timeframe = '1d'
GROUP BY n.symbol ORDER BY 1;
```
Expected: canon_rows = massive_sessions + alpaca_after, minus the sessions B4 drops (zero volume, no ticker span, gap-list rows; each name's drops are in the switch delta CSV and loss report under `logs/massive_step7/`). From raw today, ELE should land near 244 plus Alpaca after the archive end, IESC near 2,633, MSM near 5,833, and TIGO at the Alpaca-after-archive-end count only, because Massive holds no 1d row for TIGO.
Pass per name: canon_rows equals massive_sessions + alpaca_after exactly (selection is a pure function of raw, `ops_selection_gate --compare` already proves it). A difference that equals the name's listed drop reasons is explained; one that does not is a finding.

**Q6, are the names in the loss report.**
```sql
SELECT symbol FROM instruments WHERE symbol IN ('ELE','IESC','MSM','TIGO');
```
and `grep -E '^(ELE|IESC|MSM|TIGO),' data/ticker_entity_map/20261114_6195ae11abff/gap_list.csv`. Expected: the four are active instruments; a name in the gap list or `no_ticker_span` category is already tracked there (TIGO is the likely one).

## Decision rule

| Part | Survives if | Otherwise |
|---|---|---|
| 1, d2 rule for a spin-off | never: moot. d2-v6 serves Massive as served and IBKR is gone, so no vendor rewrite reaches canonical (Q1, Q2 pass) | if Q1 or Q2 fails, the premise is not dead and the d2 rule is reopened as a new todo with the failing dates |
| 1, schema `spin_off` action type and research-layer distribution event | survives, narrowed: Q3 shows the crossing return is the -83.8 percent distribution; a return across the ex date must carry the distribution as a total-return event or be NaN (`no_fill`), and the stage 2 universe has many such events. Scope it with the census below | drop only if the census finds none other than CTVA |
| 1, CTVA hold release (`--release-hold`) | decided by Q4 and the `bar_hold` code read: if no nightly or rule reads the hold after step 7, record the hold as inert and close it by its own recorded release; no daily dry run is needed because canonical already equals raw | if the nightly still reads it, release per the todo's original steps then |
| 2, ELE, IESC, MSM, TIGO | moot when Q5 passes for each: canonical is Massive from 2003-09-10 and the old IBKR "agree share" measure no longer exists | a name Q5 flags goes to the gap list or entity map lane (`no_ticker_span`), not to 516 |
| 3, effective_date off by one | already fixed (d2-v5); confirm the case at `tests/unit/bars/test_daily_rule.py:594` still passes | none |

Scoping census for the narrowed part 1 (read-only, run once, informational): names with an adjacent-session close ratio below 0.35 or above 2.9 in canonical 1d and no `corporate_action_current` row within three sessions; the count is the size of the spin-off problem on the stage 2 universe, because a spin-off, a reverse-split miss or a bad print look the same until classified.
```sql
WITH r AS (
  SELECT symbol, timestamp::date AS d, close / lag(close) OVER (PARTITION BY symbol ORDER BY timestamp) AS ratio
  FROM market_data_ohlcv WHERE timeframe = '1d')
SELECT count(*) AS events, count(DISTINCT symbol) AS names FROM r
WHERE (ratio < 0.35 OR ratio > 2.9)
  AND NOT EXISTS (SELECT 1 FROM corporate_action_current a WHERE a.symbol = r.symbol AND abs(a.effective_date - r.d) <= 3);
```
Run it on the membership names only if the table is large (join `universe_membership`); no expected value, it is a measurement that sizes the follow-up.

## Outputs

One result file under `logs/massive_step7/post_step7_readiness_20261115/` holding each query's text and rows, one line per part with survives or moot and the reason, and the follow-up todos (a narrowed 516 for the distribution event, a gap-list note for any Q5 name). Todo 516 itself is edited by the lead, after, with the stale parts 1 (d2 rule), 2 and 3 struck.
