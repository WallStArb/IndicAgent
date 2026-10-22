# 531: Schema relations with live readers and no glossary entry: gloss, rename, or drop

Filed: 2026-10-10
Owner: pending
Priority: P2 (naming-system and glossary conformance; no behavior risk)

Survey 2026-10-10 of all 90 public relations against `docs/foundation/glossary.md`
and live code. The strict rule ("every domain term has exactly one definition;
glossary wins on collision") is met by the base-table/qualified-view pattern
(`market_data_ohlcv` + `market_data_ohlcv_tradeable`, `bar_hold` +
`bar_hold_current`, ...) but nine relations have code readers and no glossary
entry:

- `market_data_5m` (view): genuine naming violation, no concept basis; 1 code
  reference. Rename to a concept name or fold into the tradeable-surface pattern.
- `instrument_metadata`: overlaps `instruments`; decide redundant vs distinct
  concept, then gloss or merge.
- `setup_performance`, `cis_weights`, `drift_state`, `dlq_events`,
  `integrity_monitor`, `remediation_ledger`: v2.x-era self-healing/scoring
  stack, named but never glossed. Each: gloss it, retire it (v2.x remainder,
  todo 509 class), or rename to its concept.
- `parity_certification_state`: zero code references, zero glossary hits --
  dead-table candidate, verify then drop per verify-then-delete.

Process: renames need a test sweep (`grep -r OldName tests/`) and a migration
in one breath; the pre-commit glossary check only fails on retired terms, so
consider extending it to flag new unglossed relations instead of retrofitting
CI enforcement for existing ones. Not urgent: nothing here blocks the rebuild
(186-26) or touches the write path.

Status 2026-10-22 (phase 191 plan 18): phase 191's glossary pass covered the
new raw-layer names only (plan 191-01: `ohlcv_raw`, the vendor and kind
vocabularies, the revision extension). The `market_data_5m` naming pass is
the explicit deferral D-191-H (planner decision, owner acknowledgement
pending); the other eight relations above are untouched and stay open here.
