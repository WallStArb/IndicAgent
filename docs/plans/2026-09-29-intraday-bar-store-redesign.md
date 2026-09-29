# Intraday bar store redesign

**Author:** Claude (Sonnet 5.5), 2026-09-29, at Brandon's request ("seems like that needs a
redesign", then the Renaissance, SoC, DAG and reuse brief), after the todo 462 measurements.
**Status:** proposed. A delta on phase 185, not a parallel design: most of the target already
exists in D-15, `BarDerivation` and plan 185-12. This doc names what 185 leaves open and what
must change so the pieces compose. Working record: todo 462.
**Informed by:** `docs/plans/2026-09-26-daily-data-foundation.md`,
`.planning/phases/185-daily-data-foundation/185-12-PLAN.md`, `services/bar_derivation.py`,
`.planning/todos/pending/462-stop-storing-synthetic-fill-bars-record-coverage-instead.md`.

## What is wrong (measured 2026-09-29)

The backfill pads `market_data_ohlcv` with flat placeholder bars for every calendar-grid slot the
provider did not return, and treats a stored placeholder as proof the slot was handled.

- 81% to 83% of intraday rows (1m, 5m, 15m, 1h) and 33% of 1d rows are placeholders.
- A placeholder is never replaced (`ON CONFLICT DO NOTHING`) and gap detection counts it as
  present, so a missing bar becomes a permanent, unflagged hole.
- 155,022 15m slots hold real 5m volume behind a placeholder (about 18.7B shares). Real-15m share
  of 5m-active slots: 99.6% to 100.0% for 2007 to 2023, then 97.7% (2024), 94.5% (2025), 98.4%
  (2026). Thirteen names (CCJ, COP, CRM, CTVA, CVS, DAL, DHI, DOCS, DOW, DUK, ECL, ELV, EMR) have
  every 2025 slot as a placeholder, and the hole is in `feature_vectors`. Only the 240 names with
  5m are measurable.
- The fill's `:00` 1h grid disagrees with the provider's (09:30 half-hour bar, then hourly).

## Principles

1. A stored bar is an assertion about the market: store only what the provider observed.
2. Absence is typed and lives outside the bar table: not asked, asked and empty, market closed,
   provider hole. "Asked and empty" is signal (no trade in the slot); a hole is a defect. The
   placeholder erased the difference.
3. Redundancy is error detection: independent measurements of one quantity reconcile, and a
   mismatch alarms; first write wins is never the resolver.
4. Canonical bars are a pure function of raw observations under a versioned rule; one writer per
   table. A rule that cannot emit a placeholder makes the defect impossible.
5. Holes do not propagate up the DAG. A derived bar built over an unanswered constituent is flagged
   or withheld, never emitted as complete.
6. Completeness is measured and exported per (symbol, timeframe, year), not assumed from row
   counts.

## What 185 already decides (reuse, do not rebuild)

| Need | Existing component | State |
|---|---|---|
| Every request with window and outcome | `ohlcv_request` via `ObservationSink` (append-only COPY, restricted role) | live since 185-09 |
| Raw answers kept | `ohlcv_observation` (1d), `ohlcv_intraday_raw_archive` (15m/1h) | tables live |
| 15m/1h from 5m on session-anchored edges | `BarDerivation(BaseBatch)`: archive, checksum-verify, delete segment (placeholders included), write derived rows, digests, constituent flags, one transaction per symbol, dry run by default | built (185-11), live rewrite is 185-12 |
| Session grid, digest, sessions | `src/intelligence/bars/` (`session_grid`, `digest`, `sessions`) | built |
| Parity of fetched vs derived bars | 185-12 (owner decision 2026-09-27) | planned |
| IBKR RTH grid for 15m/1h gap detection | 185-12 | planned |
| Single-writer and lease guards | `test_market_data_ohlcv_writer_boundary`, `ibkr_history_stream` lease | 185-12 / live |

Consequence: for 15m and 1h the placeholder deletion and the 13-name repair are `BarDerivation
--apply` (185-12), not new code. The HTF lane running now writes 15m/1h under pre-plan-12 code and
is cut over by 185-12.

## What 185 leaves open (this doc's scope)

1. 5m, 1m and 1d placeholders. 185 keeps the 1d fill (plan 23 still allows `synthetic_fill` in
   1d) and never touches 5m or 1m (1m not sized). 5m alone holds about 362M placeholder rows for
   the 240 names, three times the roughly 121M at 15m that 185-12 removes. 5m is the canonical
   intraday input; its fill is the one that must go first.
2. 5m gap detection depends on placeholders. Without an answered-window ledger a thin name's empty
   slots are re-requested every run.
3. Holes propagate. `BarDerivation` aggregates whatever 5m constituents exist; it does not ask
   whether the missing ones were answered-empty or unfetched.
4. Request record and bars persist in separate transactions, which is why the interim coverage
   check needs a raw-table `EXISTS` corroboration (a failed insert can leave a window that looks
   covered).
5. "Missing" has several definitions: `detect_gaps` in the pipeline, the gap logic in `bar_auditor`,
   and the placeholder presence both lean on. There is no shared one.
6. No completeness metric; the 13-name hole was found by an ad hoc query.

## Target DAG

```
provider (IBKR, one stream, lease)
   |  async fetch: transport only
   v
[fetch] --request+bars, ONE transaction--> [persist: writer]
                                              |-- ohlcv_request (coverage)
                                              '-- 5m bars, real only (raw = canonical at 5m)
[plan]  pure: expected slots - stored - answered windows - empty ranges = windows to ask
   ^ reads coverage; shared by fetch and audit (one definition of "missing")

5m real bars --> [derive: BarDerivation] --> 15m/1h derived + flags + digests
                                              (withheld or flagged when a constituent slot is unanswered)
raw 15m/1h fetch --> archive --> [parity audit vs derived]

all of the above --> [audit: reconcile, completeness] --> report, alarms, D0 labels (writes nothing else)
derived + 5m --> feature rebuild (186) --> research
```

One direction, no cycles, each node one job. Compute is pure (`plan`, `aggregate_session_grid`,
`bar_content_digest`); persistence is a writer; transport is the fetch; the audit reads and
reports.

## Design changes

1. **Atomic request and bars.** The persist node writes an answered request record and that
   request's bars in one transaction, reusing the `ObservationSink` shape (buffer, COPY, restricted
   role). Coverage is then true by construction, the interim raw-table `EXISTS` corroboration and
   its allow-list entry are deleted, and the fetch and persist stages decouple.
2. **One pure `plan` function**, in Ring 1 next to `sessions.py` (for example
   `src/intelligence/bars/gap_plan.py`): expected slots, stored timestamps, answered windows and
   empty ranges in, windows to ask out. The pipeline and `bar_auditor` both call it, so the
   fetcher's plan and the auditor's alarm cannot disagree: a finished run must leave the plan
   empty, and that is a testable invariant. The interim `AnsweredWindows` moves there; only the
   SQL loader stays in the script layer.
3. **Coverage-aware derivation.** `BarDerivation` marks a derived bar `partial_constituents` (the
   existing `bar_quality_flag` mechanism) when a constituent 5m slot lies in an unanswered window,
   and the tradeable view and the S0 panel treat that as NaN. Holes stop at the derivation edge.
4. **Completeness as a first-class output.** The daily audit (185-23) computes, per (symbol,
   timeframe, year), the share of expected session slots that are real or answered-empty, exports it
   to Prometheus and Grafana, and feeds it to the D0 data-quality labels on research attempts.
   Threshold in APR.
5. **Typed absence feeds research.** Answered-empty slots are a real observation (no trade). The
   panel reads them as a liquidity fact, distinct from NaN holes, instead of losing both to a
   placeholder or a dropped row.
6. **Kill the fill at 5m and 1m** (`--real-bars-only`, built), then delete the rows in a
   compressed-hypertable migration (decompress, delete, recompress, bare `VACUUM`), after a digest
   check that the real rows are unchanged. 1d follows D2.
7. **Async where it pays.** Fetch is one stream by lease, so parallel fetch is not the lever.
   Pipeline persistence behind a bounded queue so the fetch never waits on a write (todo 453
   already scopes this; it composes with change 1). The nightly derivation stays a per-symbol
   oneshot batch.

## Biases and edge cases guarded

- A complete-case filter that drops names with holes selects toward liquid names, because thin
  names have legitimately empty slots. Coverage separates answered-empty from unfetched so thin
  names are not dropped as incomplete.
- Zero-volume as the definition of a placeholder (`volume > 0` in the tradeable view) is a proxy;
  once no placeholders remain the predicate is `source`, not volume.
- Half-days, DST days and the 09:30 half-hour bar are handled by the existing session grid; the
  `plan` function uses it, not the on-the-hour UTC slots.
- Derived versus fetched disagreement is recorded, never resolved silently.
- Any research verdict on 15m or 1h that included the affected names and years is listed in the
  research ledger with its sample loss.

## Order

1. Done: `--real-bars-only`, answered-window gap detection (default off).
2. Smoke test one 5m symbol; resume the 5m lane with the flag (paused now).
3. Extract `plan`; move the answered-window type; persist request and bars atomically (removes the
   `EXISTS` check).
4. 185-12 as planned, rebased over the pipeline changes above (it edits the same fetch loop).
5. Coverage-aware derivation flag; completeness audit in 185-23.
6. 5m and 1m placeholder deletion after the digest check; then the 1d fill with D2.

## Conflicts and sequencing

- 185-12 and the interim flag both edit `infrastructure_run_historical_pipeline.py`. 185-12 must
  be planned against the current file, and after it lands 15m/1h fetches go to the archive, so the
  flag then matters only for 5m and 1m.
- The 5m lane restarts only with the flag, and the HTF chain must not be edited while its loop runs.
- Phase 186's rebuild waits on 185-12 (already its precondition); this doc gives the measured reason.

## Success criteria

- No `synthetic_fill` rows in `market_data_ohlcv` outside 1d, and no code path writes one there.
- Completeness at or above the 2007 to 2023 level (99.6%) for every 5m-active name and year, or a
  typed reason for each shortfall.
- The fetcher's plan is empty after a clean run and the auditor agrees, tested.
- The 13 names' 15m and 1h are rebuilt and `feature_vectors` for them is complete.
- A daily alarm fires on a coarse hole or placeholder over real finer-timeframe volume.

## Open questions

- Whether 5m-derived 1h agrees with the provider's 1h at the 09:30 half-hour edge (185-12's parity
  check answers it).
- How coverage seeding treats a session day where a thin name legitimately did not trade.
- Whether the 2024 to 2026 concentration traces to one backfill event.
