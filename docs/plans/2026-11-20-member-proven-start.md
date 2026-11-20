# Member proven start and the stage 2 data gate (todo 609, step s8)

Status: fixes A and B implemented 2026-11-20 (gate read translates the raw kind; `member_proven_start` and `ops_member_history_audit --apply`); the apply and the gate rerun wait for the heavy slot. Analysis below is the pre-build investigation. Evidence: `logs/massive_step7/post_step7_readiness_20261115/run_609_s8_plan_only.log`, light SQL on `integrity_monitor`, `universe_membership`, `instruments`, `ohlcv_raw`, and the code paths cited below.

The s8 gate line is `data_gate: FAIL; names 12561 (5m tier 1230); failing name-years 21849; without a proven start 11163`. It has two independent causes, plus a third consequence for the tier load. One is a missing record, one is a defect in the gate's 5m read, and the third is a real load.

## 1. What the gate reads as a proven start

- Reader: `services.corpus_rerun_data_gate.run_data_gate` calls `services.backfill_feature_factory.proven_starts(conn, names)`. The same function feeds the rebuild (`_stage_context` starts, `fetch_row_counts`), so the gate and the rebuild share one start per name.
- Store: table `integrity_monitor`, rows with `metric_name = 'proven_start_1d'` (`INFO_PROVEN_START` in `src/intelligence/bars/integrity_checks.py`), `monitor_type = 'bar_integrity'`, `subject = '<SYMBOL>|1d'`, `metric_value` = the proleptic ordinal of the start session, `passed` = a start exists. The reader takes the latest row per subject and drops a name whose latest row has `passed = false` or that has no row.
- Writer: the 1d verdict run in `services/bar_reconciliation_audit.py` (the loop around line 2548 calls `judge_name_1d`, then appends the fact at about line 2595). The pure rule is `integrity_checks.proven_start(sessions, answered, min_coverage)`: the earliest answered session s whose session coverage over [s, last session] reaches `session_coverage_min`; None when the last session itself is unanswered.
- When: every run of that verdict (daily; 764 failing and 37,461 passing facts exist between 2026-11-02 and 2026-11-19, over 1,529 distinct names).

## 2. Why 11,163 members have none

The verdict run judges only the active backfill universe (`is_active`), 1,529 names. It never evaluates a dead name. The count of members without a fact is exactly the count of inactive members:

| group | members | has fact | no fact |
| --- | --- | --- | --- |
| active, 5m tier | 1,230 | 1,230 | 0 |
| active, not tier | 168 | 168 | 0 |
| inactive, 5m tier | 3,708 | 0 | 3,708 |
| inactive, not tier | 7,455 | 0 | 7,455 |
| total | 12,561 | 1,398 | 11,163 |

The 647 audit (`src/intelligence/bars/member_history.py`, `scripts/ops/bars/ops_member_history_audit.py`) is a different check. It proves each member has canonical 1d bars and writes only a CSV (`data/member_history_audit/2026-11-20/`); it never writes `integrity_monitor`. So both statements hold: all 12,561 members have bars, and 11,163 have no start record.

Running the existing verdict over dead names would not help. `judge_name_1d` takes `window.last_session` (the last completed session of the calendar) as the end of the judged span. A dead name's last session is long past, so it is unanswered and `proven_start` returns None by construction, a failing fact. The record needs a span that ends at the name's own last session.

### The 21,849 failing name-years

The gate does not report a reason per name-year, and the plan-only run did not persist `failing_name_years`. What can be established without rerunning the gate (a heavy read of `ohlcv_raw`):

- Names without a start are refused before name-years are formed (`evaluate`: `without_start`), so the 11,163 contribute zero failing name-years. Segments, tallies and failing years exist only for the 1,398 names with a start.
- Those 1,398 names have 24,675 name-years from their start year to 2026 (tier 22,086; non-tier 2,589). The non-tier 168 are judged on the 1d term only (`none/1d_only`, zero at depth is expected for them and is not a failure).
- Failing 21,849 is 98.9 percent of the 22,086 tier name-years. So essentially every tier name-year fails, and the 237 that do not are inferred to be Alpaca-era years of the 79 names reported at depth. The per-year reason (partial, missing, 1d-missing) is not measured here. Rerun the gate after fix B below and read `failing_name_years` before concluding anything finer.

## 3. The 5m failure is a kind-label defect, not an unloaded tier

The gate says `massive/sip_flat_adj: names 1230, at depth 0, none 1230`. But the 1,230 active tier names do have 5m in raw: on 2019-06-03, 1,025 of them have Massive 5m rows (the rest listed later), and AAPL has 1,482 Massive 5m rows in January 2010.

Cause: `_5M_SESSION_BARS_SQL` in `services/corpus_rerun_data_gate.py` filters `ohlcv_raw` by `r.kind = %(kind)s` with the canonical label `sip_flat_adj`. Raw stores Massive 5m under `sip_flat_agg` (and 1d under `sip_flat`). `src/intelligence/bars/vendor_kind.py` documents exactly this ("never `r.kind = m.kind`, that join silently misses Massive rows") and provides `raw_kind_for_canonical(vendor, kind, timeframe)`; `bar_reconciliation_audit.py` uses it, the gate does not (grep finds no use). The Alpaca era is unaffected because `sip_rth` is the same in raw and canonical, which is why 79 names are at depth. With zero bars found and no Massive coverage-evidence triple (`COVERAGE_EVIDENCE` lists only IBKR and Alpaca), every Massive-era session tallies as missing and every tier name-year fails. The tests miss it because `test_corpus_rerun_data_gate.py` fixtures store rows under the canonical kind.

### Fix B (gate read)

- File and function: `iter_5m_session_bars` in `services/corpus_rerun_data_gate.py`; pass `raw_kind_for_canonical(vendor, kind, TF_5M)` as the SQL `kind` parameter. The segment's era label stays canonical.
- No migration. The gate is read-only and not a fingerprinted writer; it is imported by `services.corpus_rerun`, so land it before the pin and edit nothing the rebuild imports afterwards.
- Tests: add a fixture that stores Massive 5m rows under `sip_flat_agg` and asserts they tally (a failing test first); keep the existing canonical-kind fixtures only where they test segment labels.
- This is a read-path repair, not a loosening: thresholds are unchanged. Some name-years may then fail legitimately (thin names, halts; Massive has no answer record, so a session with no bar counts missing, not no-trade). Those must fail and stay visible; do not add a Massive coverage-evidence exemption to make them pass.

## 4. Fix A: a proven start for inactive members

Recommendation: extend the writer, keep one reader. A gate-only fallback to "first canonical 1d bar" would diverge from `backfill_feature_factory.proven_starts`, which feeds the rebuild floor (`NO_FLOOR` for names without a fact), and it would drop the hole-tolerant rule that makes the start a coverage property rather than a first-bar date. One record, one reader, one writer.

Design:

1. Pure function in `src/intelligence/bars/member_history.py`: `member_proven_start(stats, calendar, answered_dates, min_coverage)`. It builds the name's own span, `[max(first canonical 1d bar, the calendar's first session, 2000-01-03), last canonical 1d bar]` over the NYSE session calendar, and returns `integrity_checks.proven_start(span, answered, min_coverage)` (reuse; do not reimplement). `answered` = stored canonical tradeable 1d dates plus the name's `ohlcv_empty_history` spans, same as `judge_name_1d`. Threshold is the existing `session_coverage_min` APR value, not a new constant.
2. Writer: the audit run writes the facts, not the gate. `ops_member_history_audit.py --apply` (or a named writer batch beside it; the audit itself stays read-only by default) inserts `integrity_monitor` rows for inactive members only: `monitor_type='bar_integrity'`, `subject='<SYM>|1d'`, `metric_name='proven_start_1d'`, `metric_value=ordinal`, `passed = start is not None`, `training_window_end` = the audit date. Single_writer: `bar_reconciliation_audit` stays the only writer for active names (rows keyed by an `is_active` partition: it never judges a dead name; the member audit never writes an active one). If one writer per row key is wanted strictly, add a `source` marker in the row's existing detail column; no new table, no migration.
3. Reader unchanged. `proven_starts` takes the latest row per subject; a name that later reactivates falls back to the verdict run, whose newer `evaluated_at` wins.
4. Point in time: the start uses only bars with timestamps up to the name's last bar, and the record carries its audit date. It never reads returns (bar presence only), matching D4.
5. No fill: a missing session is NaN, not a placeholder; an unanswered session lowers coverage, never gets credited. Answered-empty spans credit only recorded spans.
6. Observability: the audit logs counts of written, passing and `None` starts; a `None` start is a failing fact and keeps the name refused by the gate (a name that should fail, fails).

Failure modes to test:

- Reused ticker. `symbol` is the series key; a symbol that belongs to two securities would stitch two histories and produce one start. Take the span from the security's own ticker-event interval (`ticker_entity_map_pit.py`, `universe_membership` per security), not `min(timestamp)` over the symbol. Check how many members share a symbol before the build; not verified here.
- Span starts before the first bar of the calendar (pre-2003-09-10 names). The span start is clipped to the calendar's first session, exactly as `judge_name_1d` does (`max(min(stored), era_start)`); the earlier 1d rows are counted by `fetch_pre_calendar_1d`. Test a name with bars from 1998 and one that dies before 2003-09-10 (no session in range: start None, name refused, which is correct and must stay visible).
- Name whose last bar is far before its delisting (data hole at the end). The last bar is the span end, so coverage is judged to it; the 647 findings already flag members with a stale last bar. Do not pad to a delisting date.
- Low-density names (member density p01 is 0.758, p05 0.949). With the coverage rule, the start moves later or is None; both are correct outcomes. Report the shift distribution (first bar vs start) in the audit log.
- Idempotency: rerunning appends a new fact per name; the reader takes the latest, so reruns are safe but the table grows by 11,163 rows per run; run it once before the pin and after any member-history reload.

Gates for the change: `/simplify`, `/review`, targeted tests for `member_history`, `integrity_checks`, the audit script and `corpus_rerun_data_gate`; no research or statistics edit, so `repro_frozen` is not required. The audit script and `member_history.py` are not imported by a live fingerprinted run; the data gate and `services.corpus_rerun` are, so confirm no run is live before editing them.

## 5. Is the unloaded 5m tier a separate failure?

Yes, a third item, and larger than the log suggests. After fix B the 1,230 active tier names should be at depth. The 3,708 inactive tier names have no 5m at all in raw (0 of 3,708 on 2019-06-03), and they were invisible to the gate because they have no start. Once fix A gives them a start, the gate will find them with zero 5m depth and refuse them. The tier is 4,938 names ever (1,230 active, 3,708 inactive); the 1,230 count in the log is the active slice only.

Load needed: 5m for the 3,708 inactive tier names from the Massive minute archive already on disk (86.8 GB, every ticker, 2003-09-10 onward), aggregated by our reader to `sip_flat_agg`, through the load engine's per-year compare gate (`ops_massive_load --timeframe 5m`, preregistration amendment order, `2026-11-15-stage2-5m-tier-and-intraday-universe.md` Part 3, and the amendment before the load that records the measured cost estimate). No new vendor purchase.

Sizing (estimates from the readiness files, not measured on the load):

- Rows. `tier_cost_projection.csv` gives a whole-history lower bound of 49,596 tier name-years; the 1,230 active tier names account for 22,086; about 27,500 are to load. At the measured median of 18,129 rows per name-year (`tier_cost_rows_per_name_year.csv`; the 5m RTH ceiling is 19.7k) that is about 0.5 billion 5m rows, 1.25 times today's 397.6 million.
- Raw and canonical bars. Canonical stores 702 million rows over all timeframes in 26 GB (about 37 bytes per row compressed); raw is the same order. Another 0.5 billion rows is roughly 20 GB canonical plus 20 to 30 GB raw. Small against 1.6 TB free (246 GB used of 1.9 TB), and against the up to 200 GB of Massive tape also coming.
- Rebuild peak. The plan peak of 891 GB (s1, intraday 787 GB) counts only rows that exist now, so it excludes these names. Scaling the intraday term by 1.25 on rows gives about 1.8 TB for one span, above the 1,167 GB limit; `plan_spans` then splits the rebuild into several spans rather than fail. Expect the span count and wall time to grow, not a hard blocker, but the "1 span, 891 GB, 276 GB headroom" reading in the log is not the final plan. Re-run `--plan-only` after the tier load. The plan's compression ratio 6 is an APR seed; the pilot measures the real one.
- Order: fix B and fix A first (cheap, reads only), rerun the gate, land the amendment and the tier load, run the load under one heavy job at a time with `setsid`, rerun the gate, then pin.

## Not verified

- Per-reason breakdown of the 21,849 name-years (needs a gate rerun after fix B).
- Number of members that share a symbol with another security (reused tickers).
- The exact bytes per row for the new 5m load and the post-load span plan.
- Whether any live fingerprinted run or timer currently imports the gate or the audit modules.
