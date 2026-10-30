# Clean restart runbook: features, factors, forward returns, IC and ICIR

**Author:** Claude (Opus 5.5, indicagent research lane), 2026-10-30
**Informed by:** owner decision 2026-10-30 (no real-data tests until data and features are clean; earlier results voided),
`.planning/STATE.md` restart conditions, todos 564, 566, 571, `docs/plans/2026-09-26-unified-research-to-production-design.md`.
**Status:** draft; the order below is the plan, the "state" column was checked 2026-10-30.

The measure stage is built; the restart is a sequence of gates, not new machinery. Each stage reads only the
stage above it, and nothing in a later stage runs until the earlier stage's gate holds.

| # | Stage | Component | State 2026-10-30 | Gate to pass |
|---|---|---|---|---|
| 1 | Bars | `ohlcv_raw` to `market_data_ohlcv`, view `market_data_ohlcv_tradeable` | 1d and 5m current; fallback volume served (migration 543); 71 held-name 1d gaps open (todo 566) | selection gate exit 0, D7 holds closed or named |
| 2 | Features | `services/backfill_feature_factory.py` into `feature_vectors_v2` | 1d built from 2005-01-03 for 1,314 names (pre-543 volume); intraday not built | todo 564 kernel batch applied once (hma_slope_z, dead columns, calendar start, field rename, delete list), then rebuild all timeframes on one code pin |
| 3 | Factors | S1 residualization, `research/factors.py` (`VINTAGE_1`), loadings fit on rows before the target window | built and certified on synthetic data; S1 drift bias on momentum members open (todo 547) | decide the S1 drift before any momentum-type member is certified |
| 4 | Forward returns | kernel `panel.forward_returns`, `ln(open[T+N+1] / open[T+1])`, no target table | built; every target is the kernel (`measure/targets.py`) | none; panels end at `alpha.validation.oos_start` |
| 5 | IC and ICIR | `services/ic_measure.py` writing `feature_ic_scores_v2` (IC, p, BH-FDR, walk-forward, `ic_sharpe`, `ic_sharpe_hac`, shrunk and partial IC) | table empty; refuses while any symbol lacks a `bar_content_digest` row and refuses rows reaching `oos_start` | run per timeframe after stage 2; `--start` is a timezone-aware timestamp |
| 6 | Concept layer | `ConceptRegistryService` | 306 features `active` on voided evidence | reset after stage 2 completes (todo 571), then features re-earn `active` from stage 5 |
| 7 | Families, StepM, books | `run_spec.py`, `select_books.py` | ledger reset (migration 544); statistics certified on synthetic data | owner decides vintage handling; then one counted look per pre-registered spec |

## Rules that carry over

- Never edit `src/intelligence/features/` or the modules `backfill_feature_factory.py` imports while a stage runs; one code pin per rebuild.
- A 1d measurement starts at the first rebuilt session, 2005-01-03 (`ic_measure.py --start 2005-01-03T00:00:00Z`), until the market calendar
  (`_PMC_RANGE_START`, now 2005-01-01) is moved in the same kernel batch; 1d bars exist from 1999.
- Volume kernels see SMART volume on the IBKR fallback bars (a basis change at the Alpaca seam); `venue` bars stay NULL.
- IC and ICIR are descriptive screens here, counted and FDR-corrected inside `ic_measure`; they do not select books, StepM does.
