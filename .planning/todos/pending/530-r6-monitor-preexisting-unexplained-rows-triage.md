# 530: Triage the R6 completeness monitor's pre-existing unexplained rows

Filed: 2026-10-10
Owner: pending
Priority: P0 with todo 533 (owner, 2026-10-12); closes at 533 step 9

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
