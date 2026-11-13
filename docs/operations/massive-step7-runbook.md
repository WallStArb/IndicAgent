# Massive admission step 7: canonical drop and one-pass rebuild

Author: session for the lead (indicagent-32), 2026-11-11
Status: prepared, not executed. Every command below is ordered; each carries its gate (what must be true to go on) and its abort rule. Nothing here deletes raw data; the deletion list is a separate, Opus-reviewed document this runbook only feeds.
Informed by: `docs/plans/2026-11-10-massive-admission-db-design.md` (sections 5, 8 step 7 and its amendments, 8a, 8b), `docs/plans/2026-11-10-massive-admission-refinement-review.md` (F2, F4, F14), `docs/plans/2026-11-11-bulk-raw-load-path-design.md` (section 6, the step 5 gate), `docs/plans/2026-11-11-split-horizon-fresh-check.md`, `.planning/todos/pending/608-massive-step4-split-findings-for-review.md`, `scripts/ops/bars/{ops_source_policy,ops_selection_gate}.py`, `services/{bar_selection,bar_derivation}.py`, `src/intelligence/bars/{daily_rule,split_rescale}.py`, read-only measurements on the live DB (2026-11-11).

## What step 7 does

Canonical `market_data_ohlcv` is a pure function of raw, policy and the pinned split horizon. Step 7 switches the policy to Massive and rebuilds canonical from raw in one pass: TRUNCATE, then every timeframe rebuilt by its own writer (5m and 1m by selection, 1d by the daily stage, 15m and 1h by the grid stage). `ohlcv_raw` is never touched.

Two policy stages, in order (design 8b):

| Stage | 5m and 1d defaults | Gap-list names | Checked by |
|---|---|---|---|
| 1 | IBKR before 2003-09-10; Massive 2003-09-10 to 2016-01-04, no fallback; the live Alpaca default (fallback IBKR) from 2016-01-04, unchanged | IBKR symbol rows over their gap spans before 2016-01-04 | post-2016 canonical reproduced byte for byte; the 2016-01-04 seam witness |
| 2 | IBKR before 2003-09-10; Massive 2003-09-10 to 2026-11-10, no fallback; Alpaca, no fallback, after | IBKR before 2016-01-04; Alpaca from 2016-01-04; names no vendor kind serves (futures, fx) keep IBKR | pre-2016 canonical reproduced byte for byte from stage 1; the archive-end seam witness; per-year compares |

The 2003-09-10 boundary is a refinement of the design text ("Massive primary before 2016-01-04"): canonical 1d holds IBKR history back to 1998-12, before Massive's first file. A Massive default from 1990 with no fallback would drop it. 5m has no bar before 2006, so the boundary changes nothing there; it is kept for one shape across timeframes.

## Tools (this branch)

| Tool | Role | Writes |
|---|---|---|
| `scripts/ops/bars/ops_canonical_summary_card.py` | the card (counts and order-independent content digests per timeframe, symbol, vendor, kind, UTC month) and the card-to-card compare | files only |
| `scripts/ops/bars/ops_massive_policy_plan.py` | builds the stage 1 and stage 2 `--plan` files from live policy, the pinned gap list and the 1d raw fingerprint; validates each with the writer's own `parse_plan` | files only |
| `scripts/ops/bars/ops_canonical_rebuild.py` | `--preflight` (hard-abort preconditions, pins the horizon), `--rebuild` (span-major, chunk-aligned selection of 5m and 1m, compress as it goes, resumable), `--finish` (policy recompression, ANALYZE, storage-shape check) | canonical (through `select_and_write`) |
| `scripts/ops/bars/ops_seam_witness.py` | level continuity across a seam against Massive's own split-adjusted raw (the 592 rule) | files only |
| D7 `split_horizon_fresh` | every canonical Massive 5m bar carries the splits known now (required 5m check) | integrity_monitor |

Existing tools used: `ops_source_policy --plan`, `ops_selection_gate --compare`, `services.bar_derivation --stage daily|grid`, `ops_table_backup`, `massive_download --restat`, `ops_restatement_review`, D7.

Set once per session:

```bash
cd /home/bg/dev/indicagent
PY=.venv/bin/python
OUT=logs/massive_step7            # all step 7 evidence; mkdir -p "$OUT"
GAP=data/ticker_entity_map/20261110_be44ac7d4ea7/gap_list.csv   # the map the sweep loaded under; pin it
PSQL="env PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -v ON_ERROR_STOP=1"
```

`ops_massive_load --gap-list` defaults to the lexically last directory under `data/ticker_entity_map/`, which sorts by digest, not time. Confirm `$GAP` is the file the sweep used (its sha256 in `logs/massive_sweep/` reports or the sweep command line) before anything below reads it.

## Part A: preconditions (no canonical write yet)

Each line is a gate. Any red stops step 7; nothing below starts.

A1. The raw load sweep is complete. `logs/massive_sweep/status.txt` has an `OK <year>` line for every year 2003 to 2026 (2026 through the archive end), and for every year both `compare_<Y>_5m_pre.json` and `compare_<Y>_5m_post.json` exist (the step 5 amendment: a skipped compare leaves the year ungated). For every year: `real_differences == 0`, `n_canonical` unchanged, and `after.unselected_slots - before.unselected_slots` equals the year's Massive-only count. The 1d row balance lines read `offered == bars out`.
Abort: any year missing or unbalanced.

A2. Section 8a load checks have run over loaded raw and emit a complete partition of the mapped universe (name, era, outcome in pass, gap list, stop; bucket counts sum to the mapped total). No systemic stop (units, session offset, record sanity, volume bands). Name-level outcomes of the checks are FLAGS (amendment 2026-11-12, design 8a): a flagged name-era stays Massive-primary and is listed in the data adjacency register; it never gets an IBKR symbol row. `$GAP` is the identity gap list only (names Massive does not serve; IBKR is their only source).
Abort: a systemic stop, or a partial run reported as a result.

Amendment 2026-11-13 (lead, after the first full 8a run, r5h/r5i): a stop is scoped to its (era, timeframe), not to the switch as a whole (design 8a R1). The partition reports stops as `era/tf` in `stageC_stop_eras.json`, and A2's abort applies only to a stage A or B stop on the minute or day file as a whole, or to a partial run. A stopped (era, timeframe) keeps its incumbent default in the stage 1 plan: `ops_massive_policy_plan.py` takes the 8a out dir (pinned by path and the summary's sha256, never "newest") and emits per-timeframe default spans that exclude every stopped era, so the Massive default becomes a set of spans per timeframe rather than one span. The first full run gives 2014 to 2026 ok on both timeframes; 1d 2004 to 2007 is a close-definition difference (todo 610) that takes Massive by the one-definition rule; 1d 2008 to 2013 stops and keeps IBKR unless the stop is explained first. Every span seam this creates (1d at 2008-01-01 and 2014-01-01 if 2008 to 2013 stays IBKR) gets an `ops_seam_witness` run in Part D next to the 2016 seam. Not built yet: the plan builder's 8a input (todo 600, after the 8a runner lands).

A3. Split reconciliation recorded. Todo 608's held classes are ruled (items 2, 3, 4, 7 at minimum listed with a disposition; item 1 and 5 are already ruled). After 9b's 1d load covers every year, rerun the lone-break sweep with Massive as the witness:

```bash
$PY -m scripts.ops.bars.ops_split_calendar_audit --sweep --witness massive > "$OUT/split_sweep_massive.txt"
```
Gate: every break is classified (real move, missing split, identity), and every missing market split the sweep finds is either recorded (`massive_reference` row through the writer) or listed with the names it affects. A missing split leaves an unseen step in canonical Massive history; this is the last point it is cheap to fix.

A4. `split_horizon_fresh` exists and runs. This branch adds it (design note `docs/plans/2026-11-11-split-horizon-fresh-check.md`); it must be landed and D7 run once green on it before the switch (every name passes trivially today: no canonical Massive row exists).

A5. Serve-time currency, zero drift (refinement review F3; repeat immediately before step 7 while the plan is live):

```bash
$PY -m scripts.infrastructure.massive.massive_download --restat --drift-report "$OUT/etag_drift.json"
```
Gate: the drift report lists no key. Abort: any drift; re-download it, reload the affected year (A1 gate again).

A6. The rescale canary at unit level (refinement review F2 (b)), on the code being run:

```bash
$PY -m pytest -n 0 -p no:cacheprovider -q \
  "tests/unit/bars/test_split_rescale.py::test_nvda_ten_for_one_canary_matches_the_hand_computed_series" \
  tests/unit/bars/test_split_rescale.py tests/unit/test_bar_selection.py \
  tests/unit/scripts/test_ops_selection_gate.py tests/unit/bars/test_daily_rule_massive.py \
  tests/unit/bars/test_split_horizon_fresh.py
```
Gate: exit 0.

A7. Restatement flags. Today every `--compare` exits 3 on `unreviewed_basis_flags` (290 on 2026-11-11), which is residue, not a difference. Review them (`$PY -m scripts.ops.bars.ops_restatement_review --all`, then `--mark ... --by ... --note ... --apply`) so the post-rebuild gate can read exit 0, or record the count and require it unchanged before and after. Recommended: review them; a basis-change flag inside the rebuilt span is exactly what the switch should not inherit unread.

A8. IBKR 5m raw export (reversible-first; deletion is later and separate). Raw is not touched by step 7, but the export is cheapest while the system is quiet:

```bash
$PY -m scripts.ops.db.ops_table_backup --dump --backup-dir data/backups/ibkr-5m-raw-$(date -u +%F) \
  --table ohlcv_raw:timestamp:timestamptz --where "vendor = 'ibkr' AND timeframe = '5m'"
$PY -m scripts.ops.db.ops_table_backup --verify --backup-dir data/backups/ibkr-5m-raw-$(date -u +%F) \
  --table ohlcv_raw:timestamp:timestamptz --where "vendor = 'ibkr' AND timeframe = '5m'"
```
Gate: `--verify` exit 0 (live recount and sha256 per year slice).

A9. Snapshot the live policy (the rollback input; every abort rule after C2 restores from it):

```bash
for tf in 5m 1d; do
  $PY -m scripts.ops.bars.ops_massive_policy_plan --snapshot --timeframe $tf --out "$OUT/policy_before_$tf.json"
done
```
Gate: a restore plan built from it right now is a no-op (2 defaults retired and re-inserted, every symbol row kept, none inserted; read-only check 2026-11-11: 5m 2 rows, 1d 97 rows, 95 kept):

```bash
for tf in 5m 1d; do
  $PY -m scripts.ops.bars.ops_massive_policy_plan --restore "$OUT/policy_before_$tf.json" --timeframe $tf --out "$OUT/restore_noop_$tf.json"
done
```

Restore procedure, named R below (any abort after C2 applied a plan):

```bash
for tf in 5m 1d; do
  $PY -m scripts.ops.bars.ops_massive_policy_plan --restore "$OUT/policy_before_$tf.json" --timeframe $tf --out "$OUT/restore_$tf.json"
  $PY -m scripts.ops.bars.ops_source_policy --plan "$OUT/restore_$tf.json"            # dry run
  $PY -m scripts.ops.bars.ops_source_policy --plan "$OUT/restore_$tf.json" --apply
done
```

A10. Quiesce (design step 0 and F14). Stop, and keep stopped until Part D passes:

```bash
sudo systemctl stop indicagent-bar-derivation-daily.timer indicagent-bar-derivation-grid.timer \
  indicagent-bar-reconciliation-audit.timer indicagent-dividend-event-writer-yahoo.timer \
  indicagent-regime-coverage-auditor.timer indicagent-alpaca-nightly.timer \
  indicagent-compression-auditor.service
systemctl is-enabled indicagent-ibkr-history-fetcher.timer   # must print disabled (it is, 2026-11-11)
```
The compression auditor force-runs the compression job on an overdue chunk, which would compress a chunk the rebuild is still filling. Also stopped: any hand-run `ops_split_detect`, `ops_source_policy`, `ops_selection_gate`, the sweep driver and corpus or rerun services. The design lets the Alpaca nightly run because it "writes raw only"; it does not: its 5m path selects into canonical through the load engine. Stop it for the window (about one day). On restart its tail asks the missed sessions again; confirm the first run after Part D loads them (its ledger rows for the missed dates).

## Part B: before the drop

B1. Summary card (derived data is dropped only after its card exists):

```bash
$PY -m scripts.ops.bars.ops_canonical_summary_card --card "$OUT/card_before"
sha256sum "$OUT"/card_before/* > "$OUT/card_before.sha256"
```
The card also writes, mandatorily, `export_1d_red_lineage.csv.gz`: every column of the canonical 1d rows of each name whose latest 1d `lineage_missing` or `canonical_recompute` verdict is red, the rows raw cannot rebuild and the TRUNCATE would otherwise lose without a trace (on 2026-11-11: CTVA, 1,848 lineage-missing and 1,877 recompute-drifted bars; SCCO, 4,145 and 4,268; 6,231 canonical 1d rows exported in the read-only smoke run). `card.json` lists the red verdicts and the exported names.
Measured: about 0.75M rows/s on a 5m month (2.7 s for one month of every name), so about 15 minutes for the 597M canonical rows. Gate: the card's totals per timeframe match the 2026-11-11 inventory to within what the nightlies added since (5m 401.8M, 15m 139.8M, 1h 38.5M, 1d 7.57M, 1m 9.78M, 4h 0). Abort: a timeframe missing or off by more than recent nightlies explain.

B2. Pre-image, mandatory. Two parts:

- The red lineage export written by B1 (above). Gate: `card.json` `red_lineage.exported_symbols` covers every name in `red_lineage.verdicts`, and its row count is nonzero for each.
- A disposition per red verdict, written before C3 to `$OUT/lineage_dispositions.json` (`{"SYMBOL|1d|check": "disposition"}`). The C3 preflight refuses while any red verdict lacks one. Pre-classified on 2026-11-11, both as expected D1 differences:

```json
{
  "CTVA|1d|lineage_missing": "expected D1 difference: canonical 1d rows with no raw lineage (todo 592 era); the rebuild serves what raw holds, the old rows survive in export_1d_red_lineage.csv.gz",
  "CTVA|1d|canonical_recompute": "expected D1 difference: canonical differs from d2 over raw; the rebuild makes it equal by construction",
  "SCCO|1d|lineage_missing": "expected D1 difference: as CTVA",
  "SCCO|1d|canonical_recompute": "expected D1 difference: as CTVA"
}
```
A new red name found by B1 that is not on this list gets its own written disposition (and a look at why raw cannot rebuild it) before C3, never a copy of these lines.

Optional on top: a whole-table pre-image (`ops_table_backup --dump --table market_data_ohlcv:timestamp:timestamptz` to `data/backups/canonical-pre-step7-<date>`, then `--verify`; about 1 to 1.5 hours and 25 to 35 GB), which holds the old rows for any symbol-month D1 flags.

B3. Old canonical equals the selection of raw under the old policy, every direct timeframe:

```bash
$PY -m scripts.ops.bars.ops_selection_gate --compare --timeframes 5m 1m --out "$OUT/compare_before.json"
```
Measured: 330 s per 27M-row 5m year, so about 85 minutes. Gate: `real_differences == 0`, `n_months_digest_mismatch == 0`, `session_choices_unrecorded == 0`, `mixed_vendor_sessions == 0`; exit 0, or 3 with only the A7 flag count. This anchors the byte-exact claim: the post-2016 policy does not change in stage 1, so its selection does not change.

B4. Coverage-loss census. Sessions where IBKR answered a traded bar before 2016-01-04 and Massive has no bar, for names not on the gap list, become NaN after the switch (by design for zero-volume IBKR buckets; a silent loss when Massive simply lacks the name). Count them before deciding:

```sql
-- 1d: IBKR traded sessions with no Massive day bar, 2003-09-10 to 2016-01-04
WITH ib AS (
  SELECT symbol, ("timestamp" AT TIME ZONE 'UTC')::date AS d FROM ohlcv_raw
  WHERE timeframe = '1d' AND vendor = 'ibkr' AND kind = 'smart_trades' AND volume > 0
    AND "timestamp" >= '2003-09-10' AND "timestamp" < '2016-01-04'),
ms AS (
  SELECT symbol, ("timestamp" AT TIME ZONE 'America/New_York')::date AS d FROM ohlcv_raw
  WHERE timeframe = '1d' AND vendor = 'massive' AND kind = 'sip_flat'
    AND "timestamp" >= '2003-09-09' AND "timestamp" < '2016-01-05')
SELECT ib.symbol, extract(year FROM ib.d)::int AS year, count(*) AS lost_sessions
FROM ib LEFT JOIN ms USING (symbol, d) WHERE ms.d IS NULL
GROUP BY 1, 2 ORDER BY 3 DESC;
```
Run it into `$OUT/coverage_loss_1d.csv`, then drop the names and spans the stage 1 plan keeps on IBKR (its `symbol_rows`). Gate: the remaining list is reviewed; each name is either accepted (delisted afterlife, halts) or added to the gap list and the plan rebuilt. A systemic share (more than a few percent of mapped names) stops step 7: the identity map, not the switch, is wrong. Repeat for 5m by session (same shape on `timeframe = '5m'`, `kind = 'named'` for IBKR and `sip_flat_agg` for Massive, grouping by session date) if the 1d list is not clean.

B5. Deletion list for Opus review (`docs/plans/<date>-massive-step7-deletion-list.md`), written from the card's `derived` section. It is reviewed before anything in it runs; nothing in this runbook executes it. Content it must rule on:

| Item | Count source | Why it is on the list |
|---|---|---|
| `bar_quality_flag` rows before 2016-01-04, per rule | card `derived` | flags key on (symbol, timeframe, timestamp): an IBKR-era flag would quarantine the Massive bar at the same stamp through the tradeable view. Rule-derived flags are recomputed by the scrub; human and one-off rules (`operator_bad_bar`, `legacy_price_sanity_status`, `vendor_disagreement`, `unconfirmed_split`, `pre_split_unrefetched`, `busted_trade_window`) need a per-row disposition (`busted_trade_window` 2010-05-06 is a market event and stays) |
| `market_regimes` (5,354,790 rows) | card `derived` | derived from canonical bars; rebuilt by its own stage after the data gate |
| `bar_session_choice` | card `derived` | none dropped: selection clears and rewrites the choices of every session it selects |
| `bar_content_digest` | card `derived` | append-only history; nothing dropped, the current view moves |
| IBKR 5m raw | A8 export | not in step 7; listed so the later deletion cites the verified export |

Ordering constraint: no 2016+ flag may be dropped before Part D's byte-exact check, because the grid stage excludes quarantined 5m bars and a dropped post-2016 flag would change 15m and 1h by itself.

## Part C: policy, drop, rebuild (stage 1)

C1. Build and review the plans:

```bash
for tf in 5m 1d; do
  $PY -m scripts.ops.bars.ops_massive_policy_plan --stage 1 --timeframe $tf --gap-list "$GAP" --out "$OUT/plan_stage1_$tf.json"
done
```
Read-only dry build on 2026-11-11 (current gap list): 5m 3 defaults, 580 IBKR symbol rows on 580 names; 1d 3 defaults, the same 580 rows, the 95 live 2016+ IBKR rows kept, none retired. Both validated by `parse_plan`. Gate: the counts are explained by the gap list, and a reviewer reads the plan's defaults block. 580 of 1,551 names keep IBKR for some pre-2016 span (473 `before_first_event` spans); that share is the identity map's, and the lead should accept it explicitly.

C2. Preflight first, then dry run and apply, in one sitting, 5m first. The preflight runs here as well as at C3, so a precondition that fails (a quiet unit, the lineage gate, the 1m source, a future split) stops step 7 before the policy has moved:

```bash
$PY -m scripts.ops.bars.ops_canonical_rebuild --preflight --state "$OUT/rebuild_state.json" \
  --card "$OUT/card_before" --dispositions "$OUT/lineage_dispositions.json"
```
Abort (nothing applied yet): any failure; fix it and rerun. If you stop here instead, run K.

K, the abort step: a clean preflight unschedules compression job 1078 so no chunk is compressed mid-fill; every abort path from here on ends with

```bash
$PY -m scripts.ops.bars.ops_canonical_rebuild --abort --state "$OUT/rebuild_state.json"
```
which reschedules it (it looks the job up when the state never recorded one). Leaving it unscheduled stops compression of every chunk, raw's peers included, until someone notices.


```bash
$PY -m scripts.ops.bars.ops_source_policy --plan "$OUT/plan_stage1_5m.json"           # dry run, rolled back
$PY -m scripts.ops.bars.ops_source_policy --plan "$OUT/plan_stage1_5m.json" --apply
$PY -m scripts.ops.bars.ops_source_policy --plan "$OUT/plan_stage1_1d.json"
$PY -m scripts.ops.bars.ops_source_policy --plan "$OUT/plan_stage1_1d.json" --apply
```
Abort after any apply (the 1d apply refuses after the 5m one succeeded, or any later reason to stop before C3): R, then K. R copes with a timeframe that was never switched: its restore plan is the A9 no-op.
Gate: each dry run prints counts equal to the plan (defaults retired 2 or 3, inserted 3, symbol rows as built). The 1d apply refuses if the raw fingerprint moved since the build (rebuild the plan) or the live default ids differ (someone changed policy). Ignore the printed `next:` hints; Part C replaces them. Two `ops_source_policy` rules changed on this branch to admit these plans: a 1d plan pins every live default id it retires, not exactly two (stage 1 leaves three; the apply still checks the pinned set against the live set under the table lock), and a kept symbol row beside new rows of its name is refused only when their date spans overlap (it was refused on the name alone).

C3. Preflight, immediately before the TRUNCATE (hard abort, design amendment of F4):

```bash
$PY -m scripts.ops.bars.ops_canonical_rebuild --preflight --state "$OUT/rebuild_state.json" \
  --card "$OUT/card_before" --dispositions "$OUT/lineage_dispositions.json"
```
It checks: the lineage gate (every latest red 1d `lineage_missing` and `canonical_recompute` verdict has a written disposition and its name's canonical 1d rows are in the card's export); no foreign key references `market_data_ohlcv` (none on 2026-11-11); every canonical timeframe has a raw source (1m: raw IBKR 1m equals canonical 1m exactly, 9,775,958 on 2026-11-10; 4h holds none); the chunk grid is the epoch-aligned 90-day grid (true for all 114 chunks on 2026-11-11); no split row dated after today (none on 2026-11-11; see risk 18); one compression policy job (1078, `compress_after` 30 days); the quiet units and processes; disk headroom from the APR floor. It records the compression settings (segment by symbol, timeframe; order by timestamp) and pins the split horizon (the first preflight of the state file pins it, C2's; `--horizon` sets it there). On a resume's preflight (windows already written) the raw-source check is skipped, since a partly rebuilt table measures nothing, and the pre-TRUNCATE counts are kept. Gate: `PREFLIGHT OK`.
Abort: any failure. Restore the policy (R, A9) and run K before anything else: the stage 1 rows are live and nothing may select under them while canonical is the old one. If the 1m source or a foreign key fails, the named fallback is the new-table-and-swap path (build the rebuilt timeframes into a new hypertable and swap names in one transaction, the 191-14 pattern; the swap tooling is in git at `2f43c5435^:scripts/ops/bars/ops_canonical_vendor_kind_swap.py`). It is not built: `select_and_write` and both derivation stages write `market_data_ohlcv` by name, so the fallback needs a target-table parameter in all three writers first, as its own plan. Never improvise a row-level DELETE: it decompresses chunks and leaves bloat (the migration 312 incident class).

C4. TRUNCATE (seconds; frees the 21 GB the table holds):

```bash
$PSQL -c "SET lock_timeout = '30s'; TRUNCATE market_data_ohlcv;"
$PSQL -c "SELECT count(*) FROM market_data_ohlcv;"   # 0
```
Abort: a lock timeout means something still reads or writes canonical; find it (`pg_stat_activity`), stop it, rerun C3. If step 7 stops here instead: R, then K.

C5. Rebuild the direct timeframes, oldest window first, one horizon:

```bash
$PY -m scripts.ops.bars.ops_canonical_rebuild --rebuild --state "$OUT/rebuild_state.json" --timeframes 5m 1m --from 2003-09-01
```
One invocation for both timeframes: a window's chunk is compressed only after every timeframe of the run has filled it, so a second run would insert into compressed chunks (decompression and bloat). `--from` is the first raw 5m bar (check `SELECT min("timestamp") FROM ohlcv_raw WHERE timeframe = '5m'`; Massive starts 2003-09-10, IBKR 5m 2006, raw 1m 2026-03-23). Each 90-day chunk window: every instrument through `select_and_write` per timeframe (one commit per symbol), then the chunk compressed if it is older than the policy's 30 days. The preflight unscheduled the policy job (1078) so it cannot compress a chunk mid-fill; C8 reschedules it. One JSON line per window in `rebuild_state.jsonl`: new, unselected (slots only an unranked vendor holds, mostly IBKR pre-2016 zero-volume buckets: missing is NaN), off_grid, skipped_null_volume, sessions_fallback, seconds.
Guards the driver enforces itself: it refuses to start when `market_data_ohlcv` holds any row and this state file has written no window, when `--from` is after any requested timeframe's first raw bar (recorded by the preflight), or when the quiet list is not quiet (re-checked on every resume); it stops when a symbol's selection replaced, found equal or retracted a stored row (`changed`, `unchanged` or `dropped` above 0; the one symbol a crash left between its commit and the state save may find its own rows). `--preflight --reset` refuses once any window was written, so a resumed rebuild keeps its one horizon. A resume also needs the policy the preflight recorded (a digest of every live policy id): after R the preflight refuses the old state, so a restored policy is rebuilt from a fresh TRUNCATE and state file, never resumed into a half-built table. After K, `--rebuild` refuses until a new preflight unschedules the job again.
Gate per window: `changed == unchanged == dropped == 0`. Projection rule: after the first three full-size windows (2006 on), multiply their mean seconds by the windows left; if the projection passes 12 hours, stop after the current window and decide (continue overnight, or build a COPY-based canonical writer as its own plan). Abort (a driver STOP, or the decision not to continue): R, then K; canonical stays partial and the quiet list stays stopped until a rebuild completes under some policy. Resume: rerun the same command; it skips completed windows and symbols.

C6. 1d, from raw under the new policy (d2-v6 serves Massive as `sip_flat_adj`), the whole universe, not `--changed-only`:

```bash
$PY -m services.bar_derivation --stage daily --apply --report "$OUT/daily_rebuild.tsv"
```
Abort (failed symbols that a rerun does not clear): R, then K. Gate: the batch completes with zero failed symbols; `refused`, `unserved_primary` and `zero_volume` counts are read and explained (a Massive-only session under an IBKR symbol row is unserved by design).

C7. 15m and 1h from the rebuilt 5m, the whole universe:

```bash
$PY -m services.bar_derivation --stage grid --apply
```
Gate: zero failed symbols. Abort: R, then K.

C8. Finish: reschedule and run the compression policy job (it recompresses the chunks C6 and C7 wrote into), ANALYZE, the storage shape against the preflight record:

```bash
$PY -m scripts.ops.bars.ops_canonical_rebuild --finish --state "$OUT/rebuild_state.json"
```
Gate: `FINISH OK` (it reschedules the job itself). Abort: a storage-shape drift is fixed in place (settings, recompress); values are unaffected.

## Part D: checks (stage 1)

D1. Byte-exact from 2016 (proves the whole rebuild path: chunk alignment, the writers, compression, the derived pass):

```bash
$PY -m scripts.ops.bars.ops_canonical_summary_card --card "$OUT/card_after"
$PY -m scripts.ops.bars.ops_canonical_summary_card --compare "$OUT/card_before" "$OUT/card_after" --from 2016-01-01 \
  --expected 1d:CTVA 1d:SCCO --out "$OUT/compare_card_2016.json"
$PY -m scripts.ops.bars.ops_selection_gate --compare --timeframes 5m 1m --out "$OUT/compare_after.json"
```
`--from 2016-01-01` equals the 2016-01-04 seam here: 2016-01-01 is a holiday and the 2nd and 3rd a weekend, so no bar of any timeframe falls in between. Gate: the card compare exits 0 (every 2016+ group of every timeframe identical in count and digest, except the B2-dispositioned names passed as `--expected`, whose 1d differences are listed apart in `expected_differences` and read against the export), and the selection gate meets the B3 criteria. The 1d and grid stages are covered only by the card; the selection gate covers 5m and 1m.
Abort and rollback: any difference. The card's report names the symbol-months; the B2 export (and the whole-table pre-image, if taken) shows the rows. Raw is untouched, so rollback is R (A9: the restore plans built from `policy_before_<tf>.json`) followed by C2's preflight, C3 to C8 again under a fresh state file; between the decision and that rerun, K. Until then canonical is rebuilt but not trusted: keep the quiet list stopped.

D2. Seam witness at 2016-01-04 (F2 (a)), level over the span, both timeframes:

```bash
$PY -m scripts.ops.bars.ops_seam_witness --seam 2016-01-04 --timeframe 1d --out "$OUT/seam_2016_1d.csv"
$PY -m scripts.ops.bars.ops_seam_witness --seam 2016-01-04 --timeframe 5m --out "$OUT/seam_2016_5m.csv"
```
Gate: zero `unexplained` among names with no split in the window. `reconciled_split` rows (an offset equal to a run of the name's recorded splits: an Alpaca capture-epoch seam, or a split one side lacks) and every `unexplained` row on a split-era name go to the disagreement ledger (design 8a) with the third witness named. Smoke run 2026-11-11 at 2024-06-10 (NVDA, AAPL, SPY, CENT, SNEX; 1d and 5m): every name `canonical_matches_massive`, NVDA's 10:1 split included.

Also the 2003-09-10 seam (IBKR 1d history into Massive), one-sided by construction (Massive has no bar before it):

```bash
$PY -m scripts.ops.bars.ops_seam_witness --seam 2003-09-10 --timeframe 1d --incoming raw:ibkr/smart_trades --out "$OUT/seam_2003_ibkr.csv"
```
Read the after-side level: IBKR's adjusted level against Massive over the first 20 sessions; an offset is a pre-2003 IBKR level defect the ledger records (informational, not a stop).

D3. Rescale canaries on data (F2 (b) ran at unit level in A6):

```bash
# NVDA 2024-06-07 10:1: canonical (Alpaca in stage 1) against Massive divided by the split
$PY -m scripts.ops.bars.ops_seam_witness --seam 2024-06-10 --timeframe 5m --symbols NVDA --out "$OUT/canary_nvda_2024.csv"
# pre-2016 splits canonical now serves from Massive (NVDA 2006-04-07 2:1, 2007-09-11 3:2),
# against IBKR's own adjusted series, an independent arm
$PY -m scripts.ops.bars.ops_seam_witness --seam 2007-09-12 --timeframe 1d --symbols NVDA --incoming raw:ibkr/smart_trades --out "$OUT/canary_nvda_2007.csv"
```
Gate: `canonical_matches_massive` on both. A `reconciled_split` here is a rescale defect, not an epoch seam: stop (R, then K, then the rescale fix and a full rerun).

D4. D7, sample then all. D7 has no symbol filter; run it once and read a named sample first (NVDA, AAPL, SPY, BRK.B, A, AAL, CENT, RJF, OKE, WST, UHAL, SNEX, ES), then the universe:

```bash
$PY services/bar_reconciliation_audit.py
```
Gate: on the sample, every required check green except the KNOWN-ACCEPTED rows of todo 608 item 5 (CENT and RJF should now be green, since Massive replaced their pre-2016 spans; SNEX stays an Alpaca epoch seam). Universe: `split_horizon_fresh` green on every name, and every other red verdict either existed before step 7 or is explained by the switch (a new red `split_continuity` or `canonical_recompute` on a pre-2016 span stops step 7).

D5. Restart the quiet list (A10, reversed; the compression auditor too), the Alpaca nightly last, and confirm its first run backfills the missed sessions.

D6. Docs (design section 9, the step 7a commit) land after D1 to D4 pass.

## Part E: stage 2 (after the 2016 to 2025 load checks pass)

Before stage 2, rerun from Part A: A5 (serve-time re-stat, zero drift), A9 (a fresh `policy_before_<tf>.json` snapshot of the stage 1 policy: stage 2's rollback restores stage 1, not the pre-switch policy) and A10 (the quiet list, stopped again). Stage 2 repeats Parts B to D with the stage 2 plans and a new state file (`$OUT/rebuild_state_stage2.json`, so the horizon is pinned afresh), as a second TRUNCATE and full rebuild, not a per-year reselect. Every 2016+ 5m row changes vendor; reselecting them in place would upsert about 270M rows into compressed chunks (decompress, then recompress), the bloat class the TRUNCATE path avoids, and the full rebuild gives stage 2 its own mechanical proof: the pre-2016 canonical stage 1 built must come back byte for byte.

```bash
for tf in 5m 1d; do
  $PY -m scripts.ops.bars.ops_massive_policy_plan --stage 2 --timeframe $tf --gap-list "$GAP" --out "$OUT/plan_stage2_$tf.json"
done
```
Build it from the live state after stage 1 (it retires every live symbol row by name; gap-list names get IBKR before 2016-01-04 and Alpaca from it to the archive end). Checks: the card compare `--to 2016-01-01` (pre-2016 identical to stage 1's after-card); per-year `ops_selection_gate --compare --start Y-01-01 --end Y+1-01-01` reports for 2016 to 2026 (expected differences against the stage 1 card are the Alpaca epoch seams and rounding, classified under 8a); the archive-end seam:

```bash
$PY -m scripts.ops.bars.ops_seam_witness --seam 2026-11-10 --timeframe 1d --incoming raw:alpaca/sip_rth --out "$OUT/seam_archive_end.csv"
```
(after the archive end there is no Massive reference, so the witness reads Alpaca's level against Massive over the sessions before the seam: the series canonical continues with).

Open decisions for stage 2 (the lead's):

- Futures and fx (22 names, gap reason `asset_class_outside_vendor`): the plan keeps them on IBKR through the archive end. After it the Alpaca default serves nothing for them, the IBKR fetcher is disabled and the gateway lapse decision is 2026-12-01 (todo 544). Either an IBKR open-ended symbol row (the 1d plan refuses rows past the fingerprint window today) or the names leave intraday scope.
- d2-v6 era logic reads `alpaca_era_start` from the first Alpaca-primary default; stage 2 moves it to 2026-11-10. Before the stage 2 apply, check the daily rule's IBKR volume-basis and zero-volume guards under Alpaca symbol rows with no fallback (a unit test with the stage 2 rows).
- 1m stays on IBKR (its only source); "IBKR retired from selection" covers 5m and 1d.

## Estimates

Measured inputs (2026-11-10 and 11): canonical 597.4M rows, 21 GB on disk, 90 GB before compression (6.3x to 7.2x per chunk); post-2016 rows 5m 273.5M, 15m 95.2M, 1h 26.2M, 1d 3.8M; pre-2016 5m 128.3M (IBKR). Massive 5m 2023: 23.2M rows (36.7k rows/s raw load); the 9b sweep measured 33k to 36k new rows/s on the bulk path, so a 5m year loads in about 12 minutes. Card digest 0.75M rows/s. Selection gate compare 83k rows/s (330 s per 27M-row 5m year). Grid writer 16.7k rows/s (73.1M new rows in 72.8 min, 2026-10-11). Daily stage over every name 8.5 min with no writes.

Rebuilt 5m: about 273.5M (2016+, unchanged) plus about 200M to 250M pre-2016 Massive (2023's 23.2M a year falling with the name count in earlier years), so about 470M to 520M rows. The 5m write rate through `select_and_write` into fresh chunks is not measured (its multi-row INSERT has never run on an empty target at scale); 20k to 40k rows/s is the range from the raw path's measured server INSERT (44.8k rows/s) and the grid writer (16.7k).

| Step | Wall time | Basis |
|---|---|---|
| A (preconditions, export) | 2 to 3 h | IBKR 5m export dominates (unmeasured) |
| B1 card | 15 min | measured rate |
| B2 pre-image (optional) | 1 to 1.5 h | estimate |
| B3 compare | 1.5 h | measured rate |
| C3 preflight | 10 to 20 min | full-table counts, unmeasured |
| C5 5m and 1m | 5 to 9 h | 490M rows at 20k to 40k rows/s plus about 145k selection calls; projected after 3 windows |
| C6 daily | 20 to 40 min | 7.6M rows new, estimate |
| C7 grid | 3 to 3.5 h | 180M to 200M rows at the measured 16.7k rows/s |
| C8 finish | 30 to 60 min | recompressing the derived inserts, unmeasured |
| D card, compares, witness, D7 | 2.5 to 3 h | measured compare rate; D7 unmeasured |

Stage 1 end to end: about 16 to 22 hours of wall time, 12 to 15 of them with canonical empty or partial. Start it in a morning so the paused 04:40 and 05:20 UTC nightlies are the only scheduled losses. Stage 2 is the same again minus A.

Disk: TRUNCATE frees 21 GB. Peak during the rebuild: one uncompressed 5m window (about 3 GB), the 1d, 15m and 1h inserts into compressed chunks before C8 (about 190M rows, 25 to 35 GB uncompressed), and WAL (`max_wal_size` 16 GB). Budget 80 GB of headroom; the sweep reported 631 GB free after 2023. End state about 23 to 26 GB. The A8 export and B2 pre-image add their own files (estimate 15 to 35 GB each).

## Risk register

Each row: what can fail silently, how it is caught, and the abort or rollback. Raw is never touched, so every rollback is a policy change plus a rebuild.

| # | Silent failure | Caught by | Abort or rollback |
|---|---|---|---|
| 1 | A missing split leaves a step in canonical Massive history (no record, no rescale) | A3 sweep; D4 `split_continuity`, seam witness | record the split, reselect the name (`--reselect-only`), re-derive its grid |
| 2 | A split recorded after the rebuild's horizon leaves every earlier Massive 5m bar on the old scale | D7 `split_horizon_fresh` (required check, holds the name) | reselect the name; the reselect trigger on split writes is not built |
| 3 | The 1d daily stage reads `corporate_action_current` without a horizon while 5m pins one; a split landing during the window gives 1d and 5m different scales | quiet list stops split writers; D4 `canonical_recompute` and `split_horizon_fresh` | rerun C6 for the name and reselect its 5m |
| 4 | Pre-2016 IBKR-era quarantine flags quarantine the Massive bar at the same stamp | B5 deletion list; D4 sample | flag disposition per the reviewed list, then rescrub |
| 5 | A post-2016 flag dropped early changes the grid, and D1 then fails for a reason unrelated to the rebuild | B5 ordering constraint | restore the flag rows, rerun C7 |
| 6 | The Alpaca nightly selects into canonical during the window (the design's "raw only" is wrong for 5m) | A10 stops it; C3 refuses while it is active | if it ran, cut the D1 compare before its first touched month and rerun B3 logic for that month |
| 7 | IBKR traded sessions with no Massive bar become NaN for names not on the gap list (a silent depth loss) | B4 census | add the names or spans to the gap list, rebuild the plan |
| 8 | The gap list read is not the one the sweep loaded under (the default picks the lexically last directory) | `$GAP` pinned and its sha256 in every plan's evidence | rebuild the plan from the right file |
| 9 | Massive incomplete against IBKR's zero-volume buckets would hand whole sessions to IBKR if a fallback were ranked | plans carry no fallback under Massive (ruling 2); C2 dry-run counts | none needed; a plan with a fallback fails review |
| 10 | The 1m rows cannot be rebuilt (raw short) and are lost to the TRUNCATE | C3 hard abort, re-run immediately before C4 | stop; the new-table-and-swap fallback is its own plan |
| 11 | Chunk compression settings or the chunk grid drift after the rebuild | C8 compares against the preflight record | fix the settings and recompress; values are unaffected |
| 12 | The byte-exact check passes with the Massive code paths broken (it reads only unchanged 2016+ raw) | D2 seam witness, D3 data canaries, A6 unit canaries, D7 `split_horizon_fresh` | stop; fix the rescale path, rerun C5 to D |
| 13 | An order-independent card digest collides (sum of 60-bit hashes) | count is compared beside the digest; B3/D1 selection gate on 5m and 1m compares rows exactly | none practical; the 1d and grid stages are also covered by D7 `canonical_recompute` and `digest_fresh` |
| 14 | A reused ticker loaded under the wrong instrument (identity) | step 3 map; A2 identity check; D2 `unexplained` rows | the mapping retract path (law 528 amendment) by load id, then rebuild the name |
| 15 | Stage 2 retires IBKR and futures/fx lose canonical after the archive end | Part E open decision | decide before building the stage 2 plan |
| 16 | The 5m rebuild runs far longer than estimated and leaves canonical partial for a day | C5 projection rule after three windows | resume is safe; consumers stay stopped until D passes |
| 17 | A disk floor is crossed mid-rebuild (derived inserts plus WAL) | the driver checks the APR floor before every window; C3 | stop, free space, resume (K if the stop is long) |
| 18 | A split recorded before it executes (a future reference recapture lists them; the 2026-11-10 capture held one to 2027-01-13) divides Massive 1d history at once under d2-v6, which has no executed-by-horizon filter, while selection leaves 5m unscaled until it executes: 1d and 5m sit on different scales, and D7 `canonical_recompute` replays the same rule so it stays green | C3 refuses while any such row exists | align d2-v6 with `splits_known_at` (a rule version bump, its own plan) before any recapture applies future rows |
| 19 | The compression policy job or the compression auditor compresses a chunk the rebuild is still filling | C3 unschedules job 1078 and refuses while the auditor runs; the driver compresses a window only after every timeframe | C8 reschedules, and K on every abort path; a chunk compressed early only costs recompression |

## Not built (named)

- A target-table parameter for `select_and_write` and both derivation stages, needed only by the new-table-and-swap fallback (C3).
- The reselect trigger on a split write (design section 5); `split_horizon_fresh` is the hold meanwhile.
- A `--symbols` filter on D7 (D4 reads a sample out of the full run instead).
- d2-v6's executed-by-horizon filter for Massive 1d (risk 18); the C3 guard holds until it exists.
