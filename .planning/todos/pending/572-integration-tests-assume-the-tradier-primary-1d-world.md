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
