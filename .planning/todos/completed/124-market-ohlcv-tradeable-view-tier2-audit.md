---
status: done
priority: P1
filed: 2026-07-16
closed: 2026-07-31
source: split from todo 035's full-tree audit (docs/plans/archive/2026-07-16-market-data-ohlcv-active-bars-boundary-design.md)
reclassified: 2026-07-20 -- P3->P1, "style/DRY only" claim below is now WRONG for
  backfill_feature_factory.py; see "2026-07-20 correction" section
---

## 2026-07-31 — remaining 10 Tier-2 files closed, boundary test allow-list clean

All 10 files carried on `test_market_data_ohlcv_boundary.py`'s `_ALLOW_LIST` as
"PENDING (todo 124)" are now resolved. 9 migrated to `market_data_ohlcv_tradeable`
(genuine correctness gaps, not just style/DRY) and removed from the allow-list entirely;
1 (`infrastructure_run_historical_pipeline.py`) partially migrated with the rest
reclassified PERMANENT with a written rationale:

- **`services/bar_replay_provider.py`** — replays bars into the LIVE `market.bars`/
  `market.bars.htf` topics as if arriving in real time. Migrated (todo's own worry:
  systemd unit's `ExecStart` is stale, pointing at a nonexistent
  `bar_replay_provider_agent` module -- separate bug, same class as todo 200, not fixed
  here).
- **`scripts/ops/roll/ops_roll_batch.py`** — both the "is this contract still trading"
  liveness check and the pre-roll volume-validation SUM(volume) query migrated. The
  liveness check specifically: an expired futures contract's calendar grid could
  otherwise show a permanently-"recent" synthetic-fill bar, masking that it needs
  rolling.
- **`scripts/infrastructure/backfill/infrastructure_fetch_htf_bars.py`** — aggregates 1m
  bars into HTF candles published to the live topic; a synthetic-fill 1m bar would
  fabricate a fake HTF candle.
- **`src/providers/base_provider_agent.py`** — real bug, not just a Tier-2 style call:
  `_gap_already_filled`'s `expected_bars` is a pure calendar-time count
  (`window_seconds // tf_seconds`); this gate decides whether to skip a real IBKR fetch.
  Counting raw rows let a synthetic-fill-only window be judged "already filled,"
  silently masking a genuine outage gap forever instead of backfilling it. No existing
  test for this file.
- **`src/intelligence/services/bar_history_seeder.py`** — the `market_data_ohlcv`
  fallback path seeds `BarHistory`, the live compute path's rolling-window state
  directly, at agent startup.
- **`scripts/infrastructure/backfill/infrastructure_context_features_writer.py`** —
  mirrors `backfill_feature_factory.py`'s already-migrated OHLCV fetch; feeds
  `vix_z`/`yield_slope_z`/`flight_quality` into `context_features`, an IC engine
  measurement input.
- **`scripts/infrastructure/backfill/infrastructure_run_historical_pipeline.py`** —
  investigated in full, not left as a hedge. The `min(timestamp)` gap-reorder query
  migrated (zero behavior change: `normalize_bars()` can never fabricate a fill before a
  symbol's first real bar). Everything else (`_detect_gaps`, the writer paths,
  `run_normalize`'s own fetch/store) is genuinely PERMANENT: this script both creates
  and consumes its own synthetic fills as a self-consistent "calendar slot handled"
  bookkeeping system -- `_detect_gaps` deliberately treats a prior synthetic fill as
  "already there" so a correctly-closed weekend/holiday slot isn't re-requested from
  IBKR on every re-run. Migrating those would break the idempotent design (confirmed via
  the file's own `[rca_analysis 2026-07-05, F1/F2]` comment block). Allow-list entry
  updated to PERMANENT with this reasoning instead of staying open indefinitely.
- **`scripts/debug/analysis/debug_bic_k_selection.py`** — mirrors `regime_writer.py`'s
  own OHLCV fetch for a K-selection study; reading the raw table would fit against a
  different observation matrix than production HMM fits.
- **`scripts/debug/replay/debug_lifecycle_replay.py`** — replays bars through zone/stop/
  target signal-outcome evaluation, writing to `trade_executions`; a synthetic-fill bar
  would report a false "price never moved" outcome.
- **`src/persistence/repository/feature_snapshot_repository.py`** — `get_ohlcv_fallback`
  seeds live compute-agent warmup state, same category as `bar_history_seeder.py`.

Todo 160's DELETE + recompute step (mentioned below) remains open -- unaffected by this
batch, still gated on DB quiet time as noted 2026-07-21.

## 2026-07-21 progress — the 3 proven-impact files are fixed

`backfill_feature_factory.py`, `regime_writer.py`, and `forward_return_writer.py` all now read
`market_data_ohlcv_tradeable` instead of raw `market_data_ohlcv` + inline `volume > 0`. The view
also filters `price_sanity_status IS DISTINCT FROM 'confirmed_corrupt'`, closing the gap todo 160
proved live (KRE 5m 2007-09-18 18:15). `forward_return_writer.py`'s fix was verified safe for its
`LEAD()`/`WINDOW` clause specifically: SQL evaluates `WHERE` before window functions in the same
query level, so the existing `volume > 0` filter (now the view) already excluded placeholder bars
from the window *before* this fix — adding the corrupt-row exclusion doesn't change that ordering,
it only tightens the same already-filtered row set. `test_market_data_ohlcv_boundary.py`'s
allow-list entries for all 3 files removed (zero raw hits remain); both boundary tests plus every
directly-relevant unit test suite (`test_backfill_feature_factory.py`, `test_regime_writer*.py`,
`test_forward_return_writer.py`, `test_forward_return_session_boundary.py`,
`test_known_corrupt_print_cleanup.py`, `test_price_sanity.py`) pass; ruff/black clean.

**Not done yet (deliberately, to avoid DB contention with the concurrent 143.1-08 backfill
running at time of this fix):** the recompute this todo's own "Not yet done" section calls for —
re-running todo 160's DELETE + recompute for the currently-flagged `confirmed_corrupt` rows now
that the underlying read bug is fixed. That's a real data-mutation step against the same
`feature_vectors` table other work is reading from mid-corpus-rerun; do it once the DB is quieter,
not concurrently. **Also not done:** the remaining 11 Tier-2 files still needing a per-file
"style/DRY vs. correctness" judgment call (`bar_replay_provider.py`, `ops_roll_batch.py`,
`infrastructure_fetch_htf_bars.py`, `base_provider_agent.py`, `bar_history_seeder.py`,
`infrastructure_context_features_writer.py`, `infrastructure_run_historical_pipeline.py`, and
others per the design doc) — no live reproduction found for any of them yet, unlike the 3 fixed
here, so this remains judgment-call work, not urgent proven-bug work.

# 124 — `market_data_ohlcv_tradeable` view: Tier-2 file audit

## 2026-07-20 correction — `backfill_feature_factory.py`'s "style/DRY only" claim is stale

The "already filtering correctly, only a style/DRY benefit" assessment below was made
2026-07-16, **before `price_sanity_status` existed** (added by todo 149's migration,
2026-07-19/20). At that time `volume > 0` alone WAS equivalent to
`market_data_ohlcv_tradeable`'s filter. It no longer is: the view now also filters
`price_sanity_status IS DISTINCT FROM 'confirmed_corrupt'`, and confirmed-corrupt rows keep
`volume > 0` by design (price columns are never mutated, only the status flag is set).
`backfill_feature_factory.py`'s `volume > 0`-only filter lets these rows straight through.

**Confirmed with a live reproduction (todo 160, 2026-07-20):** KRE 5m 2007-09-18 18:15 was
correctly flagged `price_sanity_status='confirmed_corrupt'` and `forward_returns` recomputed
sane for it, but `feature_vectors.true_range_pct` for that exact bar is still the corrupt
value (7.855) — because `backfill_feature_factory.py` recomputed it from the same
unmutated raw `high=400` row. This is a live, proven correctness gap, not a hypothetical
one — it's why todo 147 (vol-normalized target `low_bull` divergence) still can't close
after two rounds of "correction." `regime_writer.py` and `forward_return_writer.py` carry
the same `volume > 0`-only exposure and haven't been checked for a live reproduction yet, but
inherit the identical risk (any future `confirmed_corrupt` row whose corruption happens to
land in a column their computation reads).

**Reclassified P3 -> P1** given proven, not hypothetical, correctness impact. At minimum,
`backfill_feature_factory.py`'s migration to `market_data_ohlcv_tradeable` should be
prioritized ahead of the other 13 files in this audit — see Fix order below.

## Problem

Todo 035 closed by fixing the 3 live call sites with zero placeholder-bar filtering
(`cross_sectional_regime_model.py`, `counterfactual_tracker.py`, `ops_oos_holdout_eval.py`) and
building `market_data_ohlcv_tradeable` as the single boundary. 14 more files reference the raw
table and were deliberately not touched in that pass (see the design doc's "not yet classified"
and "already correctly filtered" lists) — each needs a genuine per-file judgment call on whether
it should migrate to the view, and 3 of them (`regime_writer.py`, `forward_return_writer.py`,
`backfill_feature_factory.py`) were assessed 2026-07-16 as already filtering correctly with an
inline `volume > 0`, believed at the time to be only a style/DRY benefit, not a correctness fix,
from switching — **see the 2026-07-20 correction above: this is no longer true for
`backfill_feature_factory.py`, and the other two need re-checking against the same risk.**

## Not yet done

**Do `services/backfill_feature_factory.py` first** — proven correctness impact (above),
unlike the other 13 files which are still a style/DRY-only judgment call as far as evidence
shows. After that: `regime_writer.py` and `forward_return_writer.py` next, given they share
the identical `volume > 0`-only exposure pattern and just haven't had a live reproduction
found yet — worth a quick check for any `confirmed_corrupt` row whose corruption lands in a
column each of them reads, not just assumed safe by absence of evidence. Then the remaining
files listed in `tests/unit/test_market_data_ohlcv_boundary.py`'s `_ALLOW_LIST` with a
"Tier-2" or "not yet classified" reason: read the call site, determine whether it needs
tradeable-only bars or genuinely wants the full calendar grid (e.g. backfill completeness
checks may intentionally count against the full grid), migrate to
`market_data_ohlcv_tradeable` where appropriate, and remove its entry from the allow-list.

After `backfill_feature_factory.py`'s migration lands, todo 160's DELETE + recompute step for
the currently-flagged `confirmed_corrupt` rows needs to be redone (the recompute prior to the
migration used the same raw-table read and reproduced the same corruption).

## References

- `docs/plans/archive/2026-07-16-market-data-ohlcv-active-bars-boundary-design.md` — full audit,
  per-file classification as of 2026-07-16
- `tests/unit/test_market_data_ohlcv_boundary.py` — the allow-list to shrink as files are
  reviewed
- `.planning/todos/completed/035-market-ohlcv-active-bars-view.md` — closed todo this splits from
- `.planning/todos/pending/160-vwo-dia-kre-corrupt-prints-uncorrected.md` — the live
  reproduction that reclassified this todo's priority 2026-07-20
