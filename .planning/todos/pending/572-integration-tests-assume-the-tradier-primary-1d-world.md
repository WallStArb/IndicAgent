---
status: pending
priority: P2
filed: 2026-10-30
source: plan 191-24 verify run (tests/integration against the live DB)
---

# Two integration files still assume the Tradier-primary 1d world

`tests/integration/test_d2_single_writer_live.py` (4 of its tests fail) and
`tests/integration/test_derived_grid_live.py::test_1h_volume_close_and_open_agree_with_ibkr_smart_1d_observations`
fail against the live DB on 2026-10-30. They are not in CI (integration dir), so nothing flagged them.

- d2 file: it pins the d2-v2 identity set (`("tradier", "consolidated")` is expected in the corpus), the
  IBKR exception policy rows, lineage with request ids for every visible 1d bar (CTVA 2019 has none),
  and a recompute sample. Tradier rows are deleted (plan 20) and canonical 1d is Alpaca SIP primary under
  D-191-Q, so the expectations are the old world. Rewrite against the stored rule (d2-v3) and the current
  identity set, or delete the tests the audit already covers (`canonical_identities`, `lineage`).
- derived grid file: volume within 1% of the IBKR SMART TRADES 1d observation is 98.90% of 879,633
  sessions against a 0.99 floor. Same cause as todo 569 (IBKR rounds fractional-share volume once per
  aggregate); decide the floor from the measured share, not by loosening to pass.

Plan 191-24's code criterion (no Tradier branch in the fetcher-imported scripts) is met; this todo holds
its integration-test criterion.

## Rewrite landed (research lane, 2026-10-31, commit f2cf5c094)

The five failures decomposed into one stale-world assumption plus one real finding:

- The corpus itself had already moved (Tradier rows deleted, the D-191-Q default rows live), so the
  identity test failed on its own module constant. It now binds `CANONICAL_1D_SOURCES` from
  `sources.py`, the same arrays the stage and audit read, and asserts the alpaca and ibkr/named
  eras are both present.
- The (ibkr, named) placement check's own SQL read `bar_source_policy` with `LIMIT 1` and no
  ordering: with the expired Tradier default row (`[1990-01-01, 2026-10-07)`) overlapping the
  ibkr default (`[1990-01-01, 2016-01-04)`), it resolved 1999 dates to Tradier and flagged
  3,219,247 legitimate bars (WEYS, DECK, ...). It now reads `bar_source_policy_current` with the
  resolver's precedence. Under the real resolver the corpus is clean.
- Lineage: corpus-wide, 1,848 of 7,142,409 rows have NULL request_ids, all CTVA d2-v4 2019, the
  recorded `unclassified_rescale` hold (todo 516). The audit's `lineage_missing` names exactly
  that (and CTVA's policy_conformance and canonical_recompute). The integration test keeps only
  rule-version uniformity, which the audit does not check.
- The recompute sample excludes held names (the write contract skips them, plan 185-51), replaces
  the Tradier-based both-vendors category with canonical rows of both eras (1,159 names), and its
  served-since check reads the alpaca series.
- The 1h volume grid floor moves 0.99 to 0.985 under the 2026-10-30 measurement (98.90% of
  879,633 within 1%), the drop against 185-31 being IBKR fractional-share rounding (todo 569).

A held name's recompute mismatch being excluded is not loosening to pass: the hold is the record,
and the audit reports it continuously.
