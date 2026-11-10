# Massive admission design: data-layer refinement review

**Status:** review findings for the lead to rule on, 2026-11-10. Nothing here edits the design
(`docs/plans/2026-11-10-massive-admission-db-design.md`); each finding carries a proposed
amendment. Design-only review: no code, no DB writes.
**Author:** review worker session, 2026-11-10, at the lead's assignment (items 1 to 3 of the
refinement brief; the month-window capture lane was cut by the owner).
**Informed by:** `docs/plans/2026-11-10-massive-admission-db-design.md`,
`docs/reference/massive-plan-entitlements.md`, `docs/reference/data-adjacency-register.md`,
`.planning/todos/pending/600-massive-flat-files-all-history-vendor.md`, the captures under
`data/massive/reference/` (sampled read-only with `-I` python, not trusted imports), and two
read-only DB queries (canonical per-timeframe counts; `ohlcv_raw` 1m source).

## Verdict

The design holds against the invariants; sections 10 and 11 answer the right questions. The
gaps found are three pre-admission blockers (backup scope, reproduction-check coverage,
serve-time currency), four material holes (TRUNCATE fallback, identity-map evidence limits,
future-dated corporate actions, third-witness operationality), and a set of minor amendments.
None of them argue against admission; all of them are cheap to close before execution starts.

## Findings, ranked

### Blocking, before execution starts

**F1. The offsite backup list omits `data/massive/reference/` (1.8 GB, irreplaceable).**
Todo 600 open item 1 names `data/massive/files/` and `data/massive/manifest/` only. The
reference tree holds the entity-map raw material (per-ticker events for 36,869 tickers, the
tickers universe active and delisted, IPOs, the full financials, ratios, float, short interest
and short volume sets, two splits and dividends families) and it cannot be re-fetched once the
plan lapses. The admission design's step 3 consumes exactly this tree. Add it to the backup
ruling, and tar the per-ticker directories before the offsite copy: nine datasets at 36,869
tiny gz files each is about 332k inodes, which a naive `rsync` will crawl.

**F2. The post-2016 byte-exact reproduction check proves the rebuild mechanics but none of the
new code paths.** Every 2016+ span reads unchanged Alpaca/IBKR raw, so `ops_selection_gate
--compare` exercising 2016+ proves chunk alignment, the load engine, compression and the
derived-15m/1h pass. It cannot see a broken 5m rescale, a broken daily-rule version bump or a
misrouted Massive kind: those fire only on pre-2016 Massive rows, where no incumbent
comparison exists (Massive is primary with no fallback). The check would pass with the rescale
code deleted. Required additions to step 7:
- A seam witness at 2016-01-04: adjusted-close level continuity, Massive 2015 into Alpaca
  2016, per the 592 rule (level over the span, not the junction step). Split-free names must
  be continuous; split-era offsets must reconcile to the corporate-action factor.
- A rescale canary at unit level, run before the data rebuild: the factor algebra on a known
  split (NVDA 2024 10:1) asserted against a hand-computed expected series, so the code path
  has a test that does not depend on data state.
- State the residual in the caveat text: pre-2016 adjustment correctness rests on
  `corporate_action` quality plus the internal witnesses (day-vs-minute, split-step detector,
  seam), because there is no independent vendor comparison for it.

**F3. Serve-time currency: the archive is verified against the manifest, but the manifest is
not verified against the vendor.** `--verify` proves local integrity (sha256 matches what was
downloaded). It does not prove the file still matches what the vendor serves today. While the
plan is live, re-stat all 11,658 keys (HEAD requests, minutes of work), diff ETag and size
against `servetimes_*.jsonl`, and re-download any drift. After the plan lapses a restatement
can never be repaired, and raw is permanent. Two related assertions for the load path:
- Join the downloader manifest to `servetimes_*.jsonl` on ETag, and fail loudly on mismatch;
  a mismatched key means the recorded LastModified is not the serve time of the file on disk,
  and `answered_at` (temporal integrity, section 10) would be silently wrong.
- The downloader's ETag-based re-fetch (section 4, still open) is load-bearing for the nightly
  update decision too; it stays a step 0 precondition, and the size-skip path must not fire on
  an ETag change with equal size.

### Material

**F4. TRUNCATE is all-or-nothing and the design's own 1m condition implies a fallback the
mechanism cannot express.** Chunks are 90-day time ranges mixing all timeframes, so keeping 1m
while rebuilding the rest means row-level DELETE: decompression, bloat, and exactly the
incidents the compressed-hypertable migration rule exists for. The design says "confirm first
that 1m has a raw source to rebuild from, else keep its rows". Verified 2026-11-10: the source
exists, `ohlcv_raw` vendor `ibkr` holds 9,775,958 1m rows (233 symbols, 2026-03-23 to
2026-10-01), matching canonical's 9,775,958. Proposed amendment: make the confirmation a hard
abort precondition re-run immediately before TRUNCATE, and name the fallback now (build into a
new table and swap names) so a failed precondition does not improvise a delete path mid-run.
Also verify no foreign key references `market_data_ohlcv` before TRUNCATE (TRUNCATE fails on
referenced tables without CASCADE), and confirm the chunk compression settings (segment_by,
orderby) carry over; value-level comparison is unaffected, but the storage shape should not
drift by accident.

**F5. The identity map's evidence chain has measured limits the design should record.**
Verified from the sweep, not the docs:
- Delisted rows in the tickers universe carry no identifiers. Sampled row keys: `active,
  currency_name, delisted_utc, last_updated_utc, locale, market, name, primary_exchange,
  ticker`. No cik, no composite_figi, no share_class_figi. Section 6's "Massive ticker details
  give share-class FIGI and CIK" is true only for active tickers.
- Per-ticker events answer only for active tickers: 23,040 of 36,869 events responses are
  NOT_FOUND and all of them are the delisted-format queries; all 13,829 OK responses are
  active queries. 15,448 events total, every one of type `ticker_change` (no delisting or
  listing event type; delist dates come from the universe's `delisted_utc`).
- The walk-back therefore works for current names, and only through the active chain's own
  response: it carries `composite_figi` and `cik` on the body, and its events list the earlier
  ticker strings with dates (verified: A, Agilent, BBG000C2V3D6, lists AWD to 2005-11-23 then
  A from 2003-09-10). The `ticker_change` rows carry no from/to; the FIGI on the response body
  is the only join key across the chain.
Proposed amendments: write the mechanism as FIGI-grouping of the events responses (not a
per-ticker walk of dead tickers), record the measured NOT_FOUND rate in the step 3 gate, note
that NOT_FOUND arrives as an HTTP 200 with a NOT_FOUND body (the loader must parse body
status, not HTTP status), and state for stage 2 that dead-name identifiers must come from
outside Massive (SEC, hand-lists), since its endpoints do not answer for dead tickers.

**F6. Future-dated corporate actions need announcement-time gating written into the design.**
The captured splits run to execution date 2027-01-13 and the v3 dividends to ex-date
2030-12-13. The entitlement doc flags the leak risk (surprise 1) but section 5 of the design
does not mention it. The `inferred_by = massive_reference` rows land in `corporate_action`,
which selection reads by effective date. Proposed amendment: every reference-derived
corporate-action row carries `recorded_at` = capture time, and selection never joins a
reference-derived row by effective or ex date alone. This is consistent with canonical's
stored convention (adjusted on today's knowledge), which is exactly why the recorded_at gate
must live in the reference-derived subset, not in the convention.

**F7. The third-witness tie-break is not yet operational.** Section 8a names the witnesses
but not the record. Proposed amendment: a disagreement ledger row per unresolved case (name,
span, the claimed incumbent defect, witness citations, verdict, deciding session id), plus an
explicit precedence order. One witness needs re-anchoring: for Massive-internal checks (day
file vs minute aggregate), Massive's own day close is an exchange-official close, but it is
Massive, not a third party; the independent exchange-official-close witness pre-2016 is the
IBKR 1d row. Say so, or the day-vs-minute discrepancy inherits a circular witness.

**F8. The 8a check runner needs a universe-closure meta-check.** The gates saga's standing
lesson: count the whole list, never report from a tail. Section 8a says "for every mapped
name" but asserts no closure. Proposed amendment: the runner emits a complete partition of the
mapped universe (name, era, outcome in {pass, gap list, stop}), the per-bucket counts must sum
to the mapped total, and a partial run reports as partial. One line in the 8a preamble; it
converts every per-check table into a claim that can be audited.

**F9. Classify Alpaca adjustment-epoch seams in the price-agreement check.** Alpaca raw is
adjusted as served at capture time, and history fetched at different epochs can carry
different adjustment bases inside one 2016+ span. A Massive-vs-Alpaca scale disagreement may
therefore be an incumbent epoch seam, the Alpaca sibling of the 587 IBKR `smart_trades` class
in the adjustment-factor row. Proposed amendment: extend the name-era pre-classification to
name it, route it through the third witness, and keep it out of the vendor-wide stop bucket.

### Minor

**F10. Reference layout: two series is fine; declare the manifest layout canonical and record
layout provenance.** Both layouts carry sha256 per file and a capture timestamp, and the
design's reference table (section 6: vendor, endpoint, key, as-of date, body, served_at)
ingests either. The differences that matter: layout A (`capture_log.jsonl` + `pageNNNN.json`
in undated directories) would collide on a second run; layout B (dated directory +
`manifest/YYYYMMDD.jsonl`, 332,019 lines) does not. Proposed amendment: layout B is canonical
for any future capture; the loader ingests both manifests once, records which layout each row
came from, and carries the manifest line's sha256 into the reference row's lineage (section 10
lineage addition). Splits and dividends exist in both families and both surfaces; keep both as
the two witnesses they already proved to be (the two families agree on the AAPL and NVDA rows).

**F11. The overview capture contradicts the entitlement doc's SIC line.** The sweep captured
`overview` for all 36,869 tickers (about 17 MB gz); rows carry `sic_code`,
`sic_description`, `share_class_shares_outstanding`, `ticker_root`, `round_lot`,
`primary_exchange`. "No SIC codes" is true only of the 404'd `/v3/reference/sic` endpoint.
Proposed amendment: an entitlement-table row for `/stocks/vX/overview` (or whichever path the
manifest records), and a note that Massive SIC is a cross-check witness against SCH, never a
replacement; it covers delisted names' industry, which SCH cannot, and stage 2 will want it.
The adjacency register also has no rows for float, short interest, short volume, ratios or
overview under Massive REST; seed them at the quarterly pass from the captured schemas, not
from memory.

**F12. Dividend facts to correct before the reference load.** Neither captured family carries
a declaration date or the `historical_adjustment_factor` the adjacency register's Massive
dividends row claims; the v3 family has `dividend_type`, the bulk family `distribution_type`,
both have ex, record and pay dates. The bulk family includes non-US tickers and currencies
(sample: ticker "6866", JPY), so the reference load needs a venue or currency filter, and the
register row's adjustment-factor claim should be corrected to match what was served.

**F13. Float and ratios are snapshot-only.** Both surfaces returned exactly one row per
ticker (verified across sampled files): float with `effective_date`, ratios dated 2026-11-09.
There is no served history; a panel can only be built by recapture cadence. Worth one line in
the register rows so no proposer assumes depth later.

**F14. Step 0's quiet rule should enumerate the writers.** "Fetcher timers quiet during
canonical rewrites" under-specifies. The canonical writers to quiesce: D7 bar audits, split
detection, the dividend writer, any corpus/rerun service, and the selection gate itself. The
Alpaca nightly writes raw only and may run; say so, or the quiet window gets padded.

## Invariant notes

Section 10 is sound. Two additions follow from the findings: lineage gains the reference-row
manifest sha256 (F10) and the serve-time ETag join (F3); point_in_time gains the
announcement-time gate on reference-derived corporate actions (F6). `no_fill` is correctly
preserved by the no-fallback ruling and the traded-minutes-only reader. Determinism is
correctly pinned to raw, policy and the recorded corporate-action horizon; the mapping spans
add the recorded `ticker_event` ids, which is sufficient.

## Pre-admission checklist (the lead's gating list, assembled from the above)

1. Backup ruling extended to `data/massive/reference/`, tarred for the offsite copy (F1).
2. ETag re-stat of all keys while the plan is live; drift re-downloaded (F3).
3. Downloader ETag re-fetch landed; manifest-to-servetimes ETag join asserted in the load
   path (F3).
4. Law 528 amendment and the admission call recorded (already in section 11; restated because
   the retract path is a precondition of the first raw load).
5. 1m raw-source confirmation re-run immediately before TRUNCATE; fallback named (F4).
6. FK reference check on `market_data_ohlcv` (F4).
7. The rescale canary test passing at unit level before the data rebuild (F2).
