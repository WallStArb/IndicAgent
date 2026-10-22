# 530: Triage the R6 completeness monitor's pre-existing unexplained rows

Filed: 2026-10-10
Owner: pending
Status: CLOSED 2026-10-22, with phase 191 plan 18 (todo 533 step 9)
Priority: was P0 with todo 533 (owner, 2026-10-12); closes at 533 step 9

## Closure evidence (phase 191)

Every residue class this todo tracked is dissolved by the (vendor, kind) raw layout, measured
green at the phase close:

- Plan 03 (191-03-SUMMARY.md): the bulk backfill counted every old-store row class into
  `ohlcv_raw` (archive 201.7M, observation 15.6M, canonical 318.5M) and its balance check
  enumerated the whole residue to the row; the small live-fetcher twins and the 10 rows
  without a source key were dispositioned by plan 04's delta check before the cutover.
- Plan 11 (191-11-SUMMARY.md): R6 was rebuilt over the raw plane and "balances every served
  bar against ohlcv_raw and the revision log"; it exits 0 live.
- Plan 17 (191-17-SUMMARY.md, close gate 1): `ops_capture_completeness --gate` exit 0,
  unexplained 0 in every (source, timeframe) group (2026-10-18 run).

The open item this file last carried (derived 1d: 859,949 writer-labeled load rows with no
bar-label join) no longer exists as a class: loads are keyed to raw by (vendor, kind) and R6
balances them without a bar-label join. The R6 gate now runs in the nightly without paging on
known-dead rows, which was the todo's done-when.

The R6 capture-completeness check (todo 528) is now clean for alpaca 5m
(authored + archived reconciles exactly). It surfaces pre-existing
unexplained rows that predate the capture law and involve no live drop
path:

- derived 15m: 2,944,906 / derived 1d: 859,949 / derived 1h: 800,054 --
  grid rows written (ledger `written`) under source 'derived' but the
  canonical store counts zero rows under that source; likely a source-label
  mismatch between what the D2 derivation wrote in the ledger and what the
  rows carry in market_data_ohlcv (e.g. relabeled at the d2-v3 apply).
- ibkr 5m: 7,297,960 -- served minus written on grid loads, likely
  pre-fence writes or the pre-cutover fetcher's uncovered span.
- tradier 1d: 416,317 -- same class; tradier is retired (frozen class C,
  todo 519), so this is a record-hygiene item only.

Triage: for each (source, timeframe), decide whether the gap is a ledger
labeling artifact (fix the report or relabel the ledger rows), a pre-ledger
span (reclassify as preledger_rows), or real loss (write the exclusion
rule per the data-retention policy). Then the R6 gate can run with
--gate in the nightly without paging on known-dead rows.

## Update 2026-10-10 late (two of three items resolved)

- derived 15m/1h: RESOLVED (a28718c81) -- the report maps the grid's bar label
  derived_5m to the ledger's writer label; both reconcile to zero unexplained.
- ibkr 5m: RESOLVED (same class, commit follows) -- the ledger's pre-190 rows say
  source='ibkr' while the authored bars carry ibkr_named; sampled spans (40/40) are
  fully occupied under ibkr_named, so the 7.3M was vocabulary drift, not loss. The
  report normalizes ibkr_named to the writer label.
- derived 1d: OPEN -- the daily rule's load rows name the writer ('derived') while
  the 1d bars carry the authoring vendor's source (ibkr_named/tradier/
  ibkr_fallback), so no bar-label join exists. 859,949 rows. Needs a matching rule
  (per-span author mapping from D2's lineage) or an explicit ledger-vocabulary home
  for writer-labeled loads. Triage alongside todo 532's verdict work.
