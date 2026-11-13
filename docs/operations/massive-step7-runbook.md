# Massive admission step 7: canonical drop and one-pass rebuild without IBKR

Author: session for the lead (indicagent-32), 2026-11-11; rewritten 2026-11-13 for the owner rulings (worker session for lead indicagent-d0)
Status: prepared, not executed. Every command below is ordered; each carries its gate (what must be true to go on) and its abort rule. Parts A to D never touch raw. Part F (export, verify, then delete IBKR raw; retire IBKR) is written here and runs only after Part D passes.
Informed by: the owner rulings of 2026-11-13 in `.planning/todos/pending/600-massive-flat-files-all-history-vendor.md` ("IBKR is removed entirely"; then "use Massive for every date it has"), `docs/plans/2026-11-10-massive-admission-db-design.md` (sections 5, 8, 8b, 8c), `docs/plans/2026-11-10-massive-admission-refinement-review.md` (F2, F4, F14), `docs/plans/2026-11-11-split-horizon-fresh-check.md`, `scripts/ops/bars/{ops_source_policy,ops_selection_gate,ops_massive_policy_plan,ops_massive_switch_delta,ops_identity_witness}.py`, read-only measurements on the live DB (2026-11-11 and 2026-11-13).

## What step 7 does

Canonical `market_data_ohlcv` is a pure function of raw, policy and the pinned split horizon. Step 7 switches the policy and rebuilds canonical from raw in one pass: TRUNCATE, then every timeframe rebuilt by its own writer (5m by selection, 1d by the daily stage, 15m and 1h by the grid stage). `ohlcv_raw` is not touched until Part F.

One stage. The policy (`ops_massive_policy_plan.py --switch`, one plan per timeframe):

| Timeframe | Defaults | Symbol rows |
|---|---|---|
| 5m, 1d | Massive [1990-01-01, archive end), Alpaca [archive end, open); no fallback anywhere | Alpaca, no fallback, over each identity gap-list span clipped to [2016-01-04, archive end) |
| 1m, 4h | Massive [1990-01-01, open) | none |
| 15m, 1h | derived, unchanged | none |

The archive end is the first NYSE session after the manifest's last file day (2026-11-10 today), computed by `archive_end_of`, the one helper the plan and the delta script share. Massive holds no bar before its first file (2003-09-10) and no 1m or 4h bar, so those slots select nothing and leave canonical by construction. The Massive default still starts at 1990-01-01 because selection raises on a slot no policy row covers (`rank_vendors`, `resolve_policy`) and IBKR raw stays in the database through the rebuild: a policy that left the pre-2003 span uncovered would crash the rebuild, where this one keeps selection loud on a real coverage hole. Every live IBKR default and symbol row is retired; no row with IBKR as primary or fallback stays live (`ibkr_rows(plan)` is empty, and the builder refuses otherwise).

What leaves canonical, accepted by ruling (2026-11-13), each listed in the evidence and the data adjacency register:

- every slot before 2003-09-10 (1d: 643,922 rows, IBKR, 703 names; survivors only and on IBKR's pre-2008 close definition);
- canonical 1m (9,775,958 IBKR rows, 2026-03-23 to 2026-10-01; nothing in research reads 1m, Massive's minute files stay on disk as the archive);
- gap-list spans before 2016-01-04 that the identity witness (A11) does not place, and IBKR slots inside gap spans from 2016-01-04 (the gap rows carry no fallback);
- `predecessor_history`: bars an incumbent served under today's ticker before the security existed (SPAC shells, merged-away predecessors; 34 names on 1d, 53 on 5m, every lost session before both the name's first map span and its list_date);
- `vendor_has_no_bar`: sessions or 5m buckets where the incumbent had a traded bar and Massive's own file under the map's ticker has no trade (1d: 2,341 slots on 138 names, 0.04 percent of the span; 5m: IBKR 35,728 bars on 646 names, Alpaca 4,416 on 462; missing stays missing; zero load holes, i.e. no case where Massive's file holds the trade and raw lacks it);
- `outside_session`: IBKR 5m bars stamped outside the NYSE regular session (5m: 24,044 bars on 574 names); canonical 5m is session-bound and extended hours stay in raw only (standing ruling);
- zero-volume IBKR placeholders (the tradeable view drops them anyway).

The lists behind these counts (1d and 5m, one row per name-session or bar with its cause) are B4's `switch_losses.csv` and the day-file and minute-file checks of its `unexplained` rows; they go into the step 7 evidence and the data adjacency register.

## Tools

| Tool | Role | Writes |
|---|---|---|
| `scripts/ops/bars/ops_canonical_summary_card.py` | the card (counts and order-independent content digests per timeframe, symbol, vendor, kind, UTC month) | files only |
| `scripts/ops/bars/ops_massive_policy_plan.py` | `--switch` builds one plan per timeframe; `--snapshot` and `--restore` for rollback; validates each with the writer's own `parse_plan` | files only |
| `scripts/ops/bars/ops_massive_switch_delta.py` | the expected delta per (timeframe, month) with every lost slot classified; `--verify` is the D1 gate | files only |
| `scripts/ops/bars/ops_identity_witness.py` | the design 8c identity witness for gap-list spans (IBKR stored raw used once as evidence before its deletion) | files only |
| `scripts/ops/bars/ops_canonical_rebuild.py` | `--preflight`, `--rebuild` (span-major, chunk-aligned selection, compress as it goes, resumable), `--finish` | canonical (through `select_and_write`) |
| `scripts/ops/bars/ops_seam_witness.py` | level continuity across a seam against Massive's own split-adjusted raw | files only |
| D7 `split_horizon_fresh` | every canonical Massive 5m bar carries the splits known now | integrity_monitor |

Set once per session:

```bash
cd /home/bg/dev/indicagent
PY=.venv/bin/python
OUT=logs/massive_step7            # all step 7 evidence; mkdir -p "$OUT"
GAP=data/ticker_entity_map/20261110_be44ac7d4ea7/gap_list.csv   # the map the sweep loaded under; pin it (A11 replaces it)
SEAM=2026-11-12                  # the manifest's last file day; D2's --seam reads this, never a hardcoded date
PSQL="env PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -v ON_ERROR_STOP=1"
```

`ops_massive_load --gap-list` defaults to the lexically last directory under `data/ticker_entity_map/`, which sorts by digest, not time. Confirm `$GAP` is the file the sweep used (its sha256 in `logs/massive_sweep/` reports or the sweep command line) before anything below reads it.

## Part A: preconditions (no canonical write yet)

Each line is a gate. Any red stops step 7; nothing below starts.

A1. The raw load sweep is complete. `logs/massive_sweep/status.txt` has an `OK <year>` line for every year 2003 to 2026 (2026 through the archive end), and for every year both `compare_<Y>_5m_pre.json` and `compare_<Y>_5m_post.json` exist. For every year: `real_differences == 0`, `n_canonical` unchanged, and `after.unselected_slots - before.unselected_slots` equals the year's Massive-only count. The 1d row balance lines read `offered == bars out`.
Amendment 2026-11-13: the sweep's scratch logs were deleted uncommitted, so the per-year file checks cannot be re-run; the sweep itself gated on them at load time (2026-11-11, all years green). The evaluable residue is database-side: record per-year, per-kind `ohlcv_raw` row counts into `$OUT/a1_raw_counts.txt` and confirm every year 2003 to 2026 has Massive rows (2026 through the archive end) before treating A1 as green.
Abort: any year missing or unbalanced.

A2. The section 8a load checks are the admission record and gate nothing (owner ruling 2026-11-13: the 8a runner compares against IBKR and is archived at tag `archive/massive-8a-load-checks`, not landed). Copy the r5j and r5k out dirs to `data/backups/massive-8a-admission-record/` and record their sha256 in `$OUT/8a_record.sha256`. Gate: the copy exists and verifies.

A3. Split reconciliation recorded. Todo 608's held classes are ruled (items 2, 3, 4, 7 at minimum listed with a disposition; items 1 and 5 are already ruled). Rerun the lone-break sweep with Massive as the witness:

```bash
$PY -m scripts.ops.bars.ops_split_calendar_audit --sweep --witness massive > "$OUT/split_sweep_massive.txt"
```
Gate: every break is classified (real move, missing split, identity), and every missing market split the sweep finds is either recorded (`massive_reference` row through the writer) or listed with the names it affects. A missing split leaves an unseen step in canonical Massive history; this is the last point it is cheap to fix.

A4. `split_horizon_fresh` exists and runs (design note `docs/plans/2026-11-11-split-horizon-fresh-check.md`); D7 run once green on it before the switch.

A5. Serve-time currency, zero drift (refinement review F3; repeat immediately before step 7):

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
  tests/unit/bars/test_split_horizon_fresh.py tests/unit/scripts/test_ops_massive_policy_plan.py \
  tests/unit/scripts/test_ops_massive_switch_delta.py
```
Gate: exit 0.

A7. Restatement flags. Review them (`$PY -m scripts.ops.bars.ops_restatement_review --all`, then `--mark ... --by ... --note ... --apply`) so the post-rebuild gate can read exit 0, or record the count and require it unchanged before and after.

A8. d2-v6 under the switch policy. The daily rule reads `alpaca_era_start` from the first Alpaca-primary default (it moves from 2016-01-04 to the archive end) and carries IBKR volume-basis and zero-volume guards. Gate: a unit test that runs the daily rule over the switch plan's rows (Massive default, Alpaca gap rows with no fallback, Alpaca after the archive end) passes. Not built yet (see Not built); step 7 does not start without it.

A9. Snapshot the live policy (the rollback input; every abort rule after C2 restores from it):

```bash
for tf in 5m 1d 1m 4h; do
  $PY -m scripts.ops.bars.ops_massive_policy_plan --snapshot --timeframe $tf --out "$OUT/policy_before_$tf.json"
done
```
Gate: a restore plan built from it right now is a no-op (every default retired and re-inserted, every symbol row kept, none inserted):

```bash
for tf in 5m 1d 1m 4h; do
  $PY -m scripts.ops.bars.ops_massive_policy_plan --restore "$OUT/policy_before_$tf.json" --timeframe $tf --out "$OUT/restore_noop_$tf.json"
done
```

Restore procedure, named R below (any abort after C2 applied a plan):

```bash
for tf in 5m 1d 1m 4h; do
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
systemctl is-enabled indicagent-ibkr-history-fetcher.timer   # must print disabled
```
The compression auditor force-runs the compression job on an overdue chunk, which would compress a chunk the rebuild is still filling. Also stopped: any hand-run `ops_split_detect`, `ops_source_policy`, `ops_selection_gate`, the sweep driver and corpus or rerun services. The Alpaca nightly's 5m path selects into canonical through the load engine; stop it for the window. On restart its tail asks the missed sessions again; confirm the first run after Part D loads them.

A11. Identity witness and map amendment (design 8c, before step 7 and before Part F deletes IBKR raw). IBKR's stored raw is used once here as evidence, never as a source:

```bash
$PY -m scripts.ops.bars.ops_identity_witness --gap-list "$GAP" --out "$OUT/identity_witness"
```
The rule is the declared one (8c, commit 8d10bd030), applied as is by the recorded owner override. The run of 2026-11-13 placed 183 of 616 spans in scope (thin 223, predecessor_history 76, predecessor_marker 44, level_unexplained 42, returns_disagree 35, identity_evidence_missing 13); the placed spans recover 281,149 pre-2016 IBKR 1d slots and 13,572,205 5m. Then, in order: the lead reads the placed list; the identity map takes the placed rows as a dated amendment through the map's own writer (never a hand edit), which writes the new map directory and its shrunken gap list; Massive raw is loaded for the placed names and spans (`ops_massive_load` under the new map, A1's gates for the touched years); `$GAP` is repointed to the new gap list. Gate: the map amendment's own validation, the load's row balance, and a re-run of the witness on the new gap list finding no `placed` span left.

## Part B: before the drop

B1. Summary card (derived data is dropped only after its card exists):

```bash
$PY -m scripts.ops.bars.ops_canonical_summary_card --card "$OUT/card_before"
sha256sum "$OUT"/card_before/* > "$OUT/card_before.sha256"
```
The card also writes `export_1d_red_lineage.csv.gz`, every column of the canonical 1d rows of each name whose latest 1d `lineage_missing` or `canonical_recompute` verdict is red (CTVA and SCCO on 2026-11-11). Gate: the card's totals per timeframe match the 2026-11-13 inventory to within what the nightlies added since (5m 415.7M, 1d 7.27M, 1m 9.78M, 4h 0). Abort: a timeframe missing or off by more than recent nightlies explain.

B2. Pre-image, mandatory: the red lineage export written by B1 (`card.json` `red_lineage.exported_symbols` covers every name in `red_lineage.verdicts`), and a disposition per red verdict in `$OUT/lineage_dispositions.json` before C3:

```json
{
  "CTVA|1d|lineage_missing": "expected D1 difference: canonical 1d rows with no raw lineage (todo 592 era); the rebuild serves what raw holds, the old rows survive in export_1d_red_lineage.csv.gz",
  "CTVA|1d|canonical_recompute": "expected D1 difference: canonical differs from d2 over raw; the rebuild makes it equal by construction",
  "SCCO|1d|lineage_missing": "expected D1 difference: as CTVA",
  "SCCO|1d|canonical_recompute": "expected D1 difference: as CTVA"
}
```
A new red name found by B1 gets its own written disposition before C3.

B3. Old canonical equals the selection of raw under the old policy:

```bash
$PY -m scripts.ops.bars.ops_selection_gate --compare --timeframes 5m 1m --out "$OUT/compare_before.json"
```
Gate: `real_differences == 0`, `n_months_digest_mismatch == 0`, `session_choices_unrecorded == 0`, `mixed_vendor_sessions == 0`; exit 0, or 3 with only the A7 flag count. This anchors the expected delta: the before side is exactly what raw and the old policy give.

B4. The expected delta, read-only, from the live selection BEFORE the drop and after A11's load:

```bash
$PY -m scripts.ops.bars.ops_massive_switch_delta --timeframes 1d 5m --gap-list "$GAP" --out "$OUT/delta"
$PSQL -At -c "SELECT count(*) FROM market_data_ohlcv WHERE timeframe = '1m'" > "$OUT/delta/1m_leaves.txt"
```
Per (timeframe, UTC month) it full-joins canonical with Massive's raw slots and writes `switch_delta.csv` (before by vendor, pre-2003, Massive slots, moved, gained, lost by vendor, gap-row Alpaca, after the archive end, `expected_after`), `switch_losses.csv` (every lost slot, one row per name-session, classified gap_list, after_listing_end, zero_volume, no_ticker_span, unexplained) and `switch_summary.json`. Measured on 2026-11-13 before A11 (1d; the 5m run predates the gap rows and is redone here): before 7,266,037, expected after 5,525,817; pre-2003 643,922; moved to Massive 5,429,562; gained 91,707; lost 1,188,005 (gap_list 1,142,419, no_ticker_span 41,803, unexplained 2,341, zero_volume 1,442). Gate: `unexplained` is zero or every row is named (the day-file check: `vendor_has_no_bar` or `load_hole`; any `load_hole` stops step 7 until the load is repaired), every `no_ticker_span` name is `predecessor_history` (lost sessions before its first map span and before its list_date) or fixed in the map, and the lead accepts the summary. Keep `$OUT/delta` unchanged: D1 verifies against it.

B5. Deletion list for review (`docs/plans/<date>-massive-step7-deletion-list.md`), written from the card's `derived` section. Nothing in this runbook executes it:

| Item | Count source | Why it is on the list |
|---|---|---|
| `bar_quality_flag` rows before the archive end, per rule | card `derived` | flags key on (symbol, timeframe, timestamp): a flag set on an IBKR- or Alpaca-era bar would quarantine the Massive bar at the same stamp through the tradeable view. Rule-derived flags are recomputed by the scrub; human and one-off rules (`operator_bad_bar`, `legacy_price_sanity_status`, `vendor_disagreement`, `unconfirmed_split`, `pre_split_unrefetched`, `busted_trade_window`) need a per-row disposition (`busted_trade_window` 2010-05-06 is a market event and stays) |
| `market_regimes` | card `derived` | derived from canonical bars; rebuilt by its own stage after the data gate |
| `bar_session_choice`, `bar_content_digest` | card `derived` | nothing dropped: selection rewrites the choices of every session it selects; the digest history is append-only |

Ordering constraint: no flag on a bar from the archive end on, or inside an Alpaca gap row, may be dropped before D1, because the grid stage excludes quarantined 5m bars and a dropped flag would change 15m and 1h by itself.

## Part C: policy, drop, rebuild

C1. Build and review the plans:

```bash
for tf in 5m 1d 1m 4h; do
  $PY -m scripts.ops.bars.ops_massive_policy_plan --switch --timeframe $tf --gap-list "$GAP" --out "$OUT/plan_$tf.json"
done
```
Gate: each plan prints its defaults; 5m and 1d read `1990-01-01 massive, <archive end> alpaca`, 1m and 4h `1990-01-01 massive`; no row names IBKR (the builder refuses otherwise); `retire_default_ids` equals the live defaults; every live symbol row is retired (`replaced` when its name gets an Alpaca gap row, else `superseded_by_default`); the Alpaca gap rows equal the gap list's spans clipped to [2016-01-04, archive end), merged per name. A reviewer reads every defaults block.

C2. Preflight first, then dry run and apply, in one sitting, 5m first:

```bash
$PY -m scripts.ops.bars.ops_canonical_rebuild --preflight --state "$OUT/rebuild_state.json" \
  --card "$OUT/card_before" --dispositions "$OUT/lineage_dispositions.json"
```
Abort (nothing applied yet): any failure; fix it and rerun. If you stop here instead, run K.

K, the abort step: a clean preflight unschedules compression job 1078 so no chunk is compressed mid-fill; every abort path from here on ends with

```bash
$PY -m scripts.ops.bars.ops_canonical_rebuild --abort --state "$OUT/rebuild_state.json"
```
which reschedules it.

```bash
for tf in 5m 1d 1m 4h; do
  $PY -m scripts.ops.bars.ops_source_policy --plan "$OUT/plan_$tf.json"            # dry run, rolled back
  $PY -m scripts.ops.bars.ops_source_policy --plan "$OUT/plan_$tf.json" --apply
done
```
Abort after any apply: R, then K. Gate: each dry run prints counts equal to the plan. The 1d apply refuses if the raw fingerprint moved since the build (rebuild the plan) or the live default ids differ. After the four applies: `SELECT count(*) FROM bar_source_policy_current WHERE 'ibkr' IN (primary_source, coalesce(fallback_source, ''))` returns 0.

C3. Preflight, immediately before the TRUNCATE (hard abort, design amendment of F4):

```bash
$PY -m scripts.ops.bars.ops_canonical_rebuild --preflight --state "$OUT/rebuild_state.json" \
  --card "$OUT/card_before" --dispositions "$OUT/lineage_dispositions.json"
```
It checks the lineage gate, no foreign key on `market_data_ohlcv`, a raw source per canonical timeframe, the epoch-aligned 90-day chunk grid, no split row dated after today, one compression policy job, the quiet units and processes, disk headroom; it records the compression settings and pins the split horizon. Gate: `PREFLIGHT OK`.
Abort: any failure. R and K before anything else. Never improvise a row-level DELETE (the migration 312 incident class).

C4. TRUNCATE:

```bash
$PSQL -c "SET lock_timeout = '30s'; TRUNCATE market_data_ohlcv;"
$PSQL -c "SELECT count(*) FROM market_data_ohlcv;"   # 0
```
Abort: a lock timeout means something still reads or writes canonical; find it, stop it, rerun C3. If step 7 stops here instead: R, then K.

C5. Rebuild 5m, oldest window first, one horizon (1m is not rebuilt: its policy serves nothing, so it leaves):

```bash
$PY -m scripts.ops.bars.ops_canonical_rebuild --rebuild --state "$OUT/rebuild_state.json" --timeframes 5m --from 2003-09-01
```
Each 90-day chunk window: every instrument through `select_and_write` (one commit per symbol), then the chunk compressed if older than the policy's 30 days. One JSON line per window in `rebuild_state.jsonl`. Guards the driver enforces: it refuses to start on a non-empty table with no written window, when `--from` is after the first raw bar, or when the quiet list is not quiet; it stops when a selection replaced, found equal or retracted a stored row. Gate per window: `changed == unchanged == dropped == 0`. Projection rule: after the first three full-size windows, multiply their mean seconds by the windows left; past 12 hours, stop after the current window and decide. Abort: R, then K. Resume: rerun the same command.

C6. 1d, from raw under the new policy (d2-v6 serves Massive as `sip_flat_adj`), the whole universe:

```bash
$PY -m services.bar_derivation --stage daily --apply --report "$OUT/daily_rebuild.tsv"
```
Gate: zero failed symbols; `refused`, `unserved_primary` and `zero_volume` counts are read and explained. Abort: R, then K.

C7. 15m and 1h from the rebuilt 5m:

```bash
$PY -m services.bar_derivation --stage grid --apply
```
Gate: zero failed symbols. Abort: R, then K.

C8. Finish (reschedules and runs the compression policy job, ANALYZE, the storage shape against the preflight record):

```bash
$PY -m scripts.ops.bars.ops_canonical_rebuild --finish --state "$OUT/rebuild_state.json"
```
Gate: `FINISH OK`.

## Part D: checks

D1. The expected delta, exactly:

```bash
$PY -m scripts.ops.bars.ops_canonical_summary_card --card "$OUT/card_after"
$PY -m scripts.ops.bars.ops_massive_switch_delta --gap-list "$GAP" --out "$OUT/delta" \
  --verify "$OUT/card_before" "$OUT/card_after"
$PY -m scripts.ops.bars.ops_selection_gate --compare --timeframes 5m --out "$OUT/compare_after.json"
```
Gate: `--verify` exits 0: every (timeframe, month) of 5m and 1d holds exactly B4's `expected_after` rows, 1m and 4h hold none, no row carries vendor ibkr, and every Alpaca group wholly inside a gap row is byte-identical to the before card; the selection gate meets the B3 criteria. A count failure is listed whole in `$OUT/delta/switch_verify.json`; each differing month is read against B4's rows (a Massive slot selection refused, a quarantine flag, a CTVA/SCCO lineage name) before anything else. 15m and 1h have no expected count: they follow 5m and are covered by D7 `canonical_recompute` and `digest_fresh`.
The gate's strength: verify is count-exact per (timeframe, month) plus byte-identity for Alpaca gap groups; Massive-era content correctness is owned by D3/D4/D7. Review-cosmetic defects accepted there, noted and not fixed: crash-window totals double-count, the `_running` pgrep wrapper can miss a process, and `Settings()` vs `get_settings()` is inconsistent across the scripts.
Abort and rollback: any unexplained difference. Raw is untouched, so rollback is R followed by C2's preflight and C3 to C8 again under a fresh state file; between the decision and that rerun, K.

D2. Seam witness at the archive end only (the one seam the policy has; before it Massive's own series runs through every date):

```bash
for tf in 1d 5m; do
  $PY -m scripts.ops.bars.ops_seam_witness --seam "$SEAM" --timeframe $tf --incoming raw:alpaca/sip_rth \
    --out "$OUT/seam_archive_end_$tf.csv"
done
```
After the archive end there is no Massive reference, so the witness reads Alpaca's level against Massive over the sessions before the seam: the series canonical continues with. Gate: zero `unexplained` among names with no split in the window; `reconciled_split` rows (an Alpaca capture-epoch seam) go to the disagreement ledger with the third witness named.

D3. Rescale canary on data:

```bash
# NVDA 2024-06-07 10:1: canonical (now Massive) against Massive divided by the split
$PY -m scripts.ops.bars.ops_seam_witness --seam 2024-06-10 --timeframe 5m --symbols NVDA --out "$OUT/canary_nvda_2024.csv"
# NVDA 2006-04-07 2:1, 2007-09-11 3:2, against IBKR's own adjusted series (still in raw until Part F), an independent arm
$PY -m scripts.ops.bars.ops_seam_witness --seam 2007-09-12 --timeframe 1d --symbols NVDA --incoming raw:ibkr/smart_trades --out "$OUT/canary_nvda_2007.csv"
```
Gate: `canonical_matches_massive` on the first; the second reads IBKR's level against the rescaled Massive over the span (an offset is an IBKR-side adjustment, informational). A `reconciled_split` on the first is a rescale defect: stop (R, K, the rescale fix and a full rerun).

D4. D7, sample then all. Run it once and read a named sample first (NVDA, AAPL, SPY, BRK.B, A, AAL, CENT, RJF, OKE, WST, UHAL, SNEX), then the universe:

```bash
$PY services/bar_reconciliation_audit.py
```
Gate: `split_horizon_fresh` green on every name; every other red verdict either existed before step 7 or is explained by the switch (a new red `split_continuity` or `canonical_recompute` stops step 7).

D5. Restart the quiet list (A10, reversed; the compression auditor too), the Alpaca nightly last, and confirm its first run backfills the missed sessions.

D6. Docs (design section 9, the step 7a commit) land after D1 to D4 pass, with B4's accepted-loss lists in the evidence and the data adjacency register.

## Part F: IBKR raw export, verify, delete; IBKR retired (after Part D passes)

Written, not executed. The order is the owner's: step 7's checks pass, then export and restore-verify, then delete, then retire code, gateway and docs. Raw stays in the database until here as the rollback. IBKR raw held 365.4M rows on 2026-11-13 (5m 224.7M, 15m 94.0M, 1h 25.4M, 1m 9.78M, 1d 11.48M across smart_trades, smart_adjusted and five venue kinds), plus its `ohlcv_revision` rows (1d 4.51M, 5m 78k, 15m, 1h and 4h a few thousand).

F1. Export, one compressed dump per table slice, under one directory:

```bash
BK=data/backups/ibkr-raw-2026-11
RET_UNTIL=$(date -d "+30 days" +%F)   # recorded in the manifest; required by --dump
$PY -m scripts.ops.db.ops_table_backup --dump --backup-dir "$BK" \
  --table 'ohlcv_raw:timestamp:timestamptz' --where "vendor = 'ibkr'" --retention-until "$RET_UNTIL"
$PY -m scripts.ops.db.ops_table_backup --dump --backup-dir "$BK" \
  --table 'ohlcv_revision:timestamp:timestamptz' --where "vendor = 'ibkr'" --retention-until "$RET_UNTIL"
$PY -m scripts.ops.db.ops_table_backup --verify --backup-dir "$BK" \
  --table 'ohlcv_raw:timestamp:timestamptz' --where "vendor = 'ibkr'"
$PY -m scripts.ops.db.ops_table_backup --verify --backup-dir "$BK" \
  --table 'ohlcv_revision:timestamp:timestamptz' --where "vendor = 'ibkr'"
```
Gate: both `--verify` runs exit 0 (live recount and sha256 per year slice). The dump refuses below its disk margin.

F2. Restore into a scratch schema and compare, per (kind, timeframe), the row count and a content digest of the restored rows against the live rows:

```bash
$PSQL -c "CREATE SCHEMA ibkr_restore_check; CREATE TABLE ibkr_restore_check.ohlcv_raw (LIKE public.ohlcv_raw);"
for f in "$BK"/ohlcv_raw_*.csv.gz; do
  zcat "$f" | $PSQL -c "\copy ibkr_restore_check.ohlcv_raw FROM STDIN WITH (FORMAT csv, HEADER true)"
done
DIGEST="SELECT kind, timeframe, count(*), sum(('x' || left(md5(concat_ws('|', symbol,
  (extract(epoch FROM \"timestamp\") * 1000000)::bigint, float8send(open), float8send(high),
  float8send(low), float8send(close), coalesce(volume::text, 'null'))), 15))::bit(60)::bigint)
  FROM %s WHERE vendor = 'ibkr' GROUP BY 1, 2 ORDER BY 1, 2"
$PSQL -At -c "$(printf "$DIGEST" public.ohlcv_raw)" > "$OUT/ibkr_live_digest.txt"
$PSQL -At -c "$(printf "$DIGEST" ibkr_restore_check.ohlcv_raw)" > "$OUT/ibkr_restored_digest.txt"
diff "$OUT/ibkr_live_digest.txt" "$OUT/ibkr_restored_digest.txt"
```
The same for `ohlcv_revision` (its own scratch table and digest over its columns). Gate: `diff` prints nothing for both tables. Then `DROP SCHEMA ibkr_restore_check CASCADE`.
Abort: any difference; the dump is not trusted, nothing is deleted.

F3. Delete IBKR raw. `ohlcv_raw` is a compressed hypertable: a row-level DELETE decompresses chunks and leaves bloat, so the delete is its own reviewed migration (decompress the affected chunks, DELETE `WHERE vendor = 'ibkr'`, recompress, and end with a bare `VACUUM ohlcv_raw;`, the CLAUDE.md rule from the migration 312 incident; template `docs/foundation/timescaledb-compressed-column-migration.md`), plus `DELETE FROM ohlcv_revision WHERE vendor = 'ibkr'`. The raw last-wins law (528) keeps every vendor answer; this deletion is the owner's explicit exception, recorded with the dump's manifest sha256 in the migration's comment and in the methodology change ledger. Gate: `SELECT count(*) FROM ohlcv_raw WHERE vendor = 'ibkr'` returns 0, the D1 card recomputed after the delete equals `card_after` (canonical does not change), and `ops_selection_gate --compare` still meets the B3 criteria.

F4. Removal list (each its own reviewed commit, after F3; a repo-wide grep before deleting any shared helper):

- the `ib-gateway` container (`production/docker-compose`), its credentials in `.env`, and the 2FA procedure in `docs/reference/gotchas.md`;
- `src/providers/ibkr.py`, `src/providers/ibkr_adapter.py`, `services/ibkr_provider.py` and their callers (`scripts/infrastructure/backfill/_history_fetch_item.py`, `scripts/infrastructure/infrastructure_gateway_auth_probe.py`, `scripts/infrastructure/classification_ibkr_sourcing.py`, `scripts/infrastructure/reference_identity_capture.py` (the ISIN source of the identity map: replace or freeze before deleting), `scripts/infrastructure/universe_expansion_onboard_manifest.py`, `services/borrow_availability_capture.py`), `src/providers/__init__.py` exports;
- the IBKR fetcher lane in `scripts/infrastructure/backfill/ohlcv_history_fetcher.py` (its provider registry entry and `FetcherLock` use for IBKR), and the ask ledger rows of IBKR (`ohlcv_request`, read through `ohlcv_ask_current`; keep the table if Alpaca or Massive asks still use it);
- systemd units `indicagent-ibkr-history-fetcher.{service,timer}`, `indicagent-ibkr-provider.service`, `indicagent-gateway-auth-probe.{service,timer}`, and their entries in `_DAG_ORDER` and `_AGENT_ID_TO_UNIT` (`services/service_auditor.py`) and the `alert.lag.*` APR keys;
- todo 544 (gateway version desupport) closed as moot;
- CLAUDE.md: the IBKR line under Core Runtime (provider, gateway container, fetcher under `FetcherLock`), the IBKR wording in the Raw capture rule, the IBKR clientId memory, and the ubuntu1 gateway note; `docs/reference/gotchas.md` backfill and gateway sections.

## Estimates

Measured inputs (2026-11-10 to 13): canonical 5m 415.7M rows, 1d 7.27M, 1m 9.78M; Massive 5m slots in span 370.2M (B4 before A11); card digest 0.75M rows/s; selection gate compare 83k rows/s; grid writer 16.7k rows/s; daily stage over every name 8.5 min with no writes. The expected-delta run took about 10 minutes for 1d and about 2 hours for 5m.

| Step | Wall time | Basis |
|---|---|---|
| A11 witness, map amendment and load of placed spans | 3 to 5 h | witness about 1 h measured; the load at the sweep's 33k rows/s for up to 14M 5m rows |
| B1 card | 15 min | measured rate |
| B3 compare | 1.5 h | measured rate |
| B4 delta | 2 to 2.5 h | measured |
| C3 preflight | 10 to 20 min | full-table counts, unmeasured |
| C5 5m | 4 to 8 h | about 380M rows at 20k to 40k rows/s plus the selection calls; projected after 3 windows |
| C6 daily | 20 to 40 min | estimate |
| C7 grid | 2.5 to 3.5 h | 140M to 180M rows at the measured 16.7k rows/s |
| C8 finish | 30 to 60 min | unmeasured |
| D card, verify, compare, witness, D7 | 2.5 to 3 h | measured compare rate; D7 unmeasured |
| F1 to F2 export and restore check | 4 to 8 h | 365M rows, unmeasured |

Step 7 end to end: about 14 to 20 hours of wall time, 10 to 14 of them with canonical empty or partial. Start it in a morning so the paused nightlies are the only scheduled losses. Disk: TRUNCATE frees about 21 GB; budget 80 GB of headroom for the rebuild and the F1 dump's own files (estimate 30 to 50 GB).

## Risk register

Each row: what can fail silently, how it is caught, and the abort or rollback. Raw is never touched before Part F, so every rollback before it is a policy change plus a rebuild.

| # | Silent failure | Caught by | Abort or rollback |
|---|---|---|---|
| 1 | A missing split leaves a step in canonical Massive history | A3 sweep; D4 `split_continuity`, D3 canary | record the split, reselect the name, re-derive its grid |
| 2 | A split recorded after the rebuild's horizon leaves earlier Massive 5m bars on the old scale | D7 `split_horizon_fresh` | reselect the name |
| 3 | The daily stage and 5m see different split horizons | quiet list stops split writers; D4 | rerun C6 for the name and reselect its 5m |
| 4 | Old-era quarantine flags quarantine the Massive bar at the same stamp | B5 deletion list; D1 count failure on that month | flag disposition per the reviewed list, then rescrub |
| 5 | A plan leaves an IBKR row live (a primary, a fallback, a kept row) | the builder refuses (`ibkr_rows`), unit test; C2's count query | rebuild the plan |
| 6 | Alpaca loses slots only the IBKR fallback filled | B4 counts them (lost_ibkr after the archive end and in gap rows) and names each class; accepted by ruling | none: missing stays missing |
| 7 | The expected delta does not match the rebuild | D1 `--verify` per (timeframe, month), whole lists | read the month against B4; R and rebuild if the cause is the rebuild |
| 8 | A selection or derivation path writes canonical during B4 or D1 | both are read-only sessions; A10 quiet list | rerun B4 after the stray writer is stopped |
| 9 | The gap list read is not the one the plan and the delta used | `$GAP` pinned; its sha256 in every plan's evidence | rebuild the plan and B4 from the right file |
| 10 | A reused ticker or predecessor history placed under today's security | 8c continuity gate (list_date, markers) and correlation; D4 | the mapping retract path (law 528 amendment) by load id, then rebuild the name |
| 11 | d2-v6 misreads the moved `alpaca_era_start` or a no-fallback gap row | A8 unit test | fix the rule before step 7 |
| 12 | The byte-exact gap-row check passes with the Massive code paths broken | D3 canary, A6 unit canaries, D7 `split_horizon_fresh` | stop; fix the rescale path, rerun C5 to D |
| 13 | An order-independent card digest collides | counts compared beside the digest; the selection gate compares 5m rows exactly | none practical |
| 14 | The IBKR dump is incomplete or corrupt and raw is deleted | F1 `--verify`, F2 restore and per-(kind, timeframe) digest compare before F3 | nothing is deleted until F2 passes |
| 15 | The 5m rebuild runs far longer than estimated | C5 projection rule | resume is safe; consumers stay stopped until D passes |
| 16 | A disk floor is crossed mid-rebuild or mid-dump | the driver's APR floor; the dump's disk margin | stop, free space, resume |
| 17 | A split recorded before it executes divides Massive 1d at once under d2-v6 while 5m waits | C3 refuses while any such row exists | align d2-v6 with `splits_known_at` before any recapture applies future rows |
| 18 | The compression job compresses a chunk the rebuild is still filling | C3 unschedules job 1078; the driver compresses a window only after it is filled | C8 reschedules, and K on every abort path |

## Not built (named)

- A8's unit test of d2-v6 over the switch plan's rows (moved `alpaca_era_start`, Alpaca gap rows with no fallback).
- The identity map's dated-amendment writer path for A11's placed spans, and the load of their Massive raw.
- A target-table parameter for `select_and_write` and both derivation stages (the new-table-and-swap fallback of C3).
- The reselect trigger on a split write (design section 5); `split_horizon_fresh` is the hold meanwhile.
- A `--symbols` filter on D7.
- d2-v6's executed-by-horizon filter for Massive 1d (risk 17); the C3 guard holds until it exists.
- The F3 migration and the F4 commits.
