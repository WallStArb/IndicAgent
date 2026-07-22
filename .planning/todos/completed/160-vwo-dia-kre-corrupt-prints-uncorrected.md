---
status: completed
priority: P0
filed: 2026-07-20
completed: 2026-07-22
source: todo 147's true_range_pct CV re-check, re-run after 151/154 to verify their
  correction pass actually resolved the low_bull CV outlier -- it didn't. Root cause
  investigation below revised once from the initial framing after checking
  price_sanity_status directly (see "Correction" note).
---

## Disposition (2026-07-22)

The fix scoped by this todo's own "Fix" section (flag VWO/DIA via the existing tool,
apply 124's already-landed code fix, recompute) turned out to be incomplete on
contact: running `ops_known_corrupt_print_cleanup.py --symbols VWO DIA` in dry-run
found **zero** CONFIRMED_CORRUPT candidates for either symbol -- the tool's
candidate discovery was never built to find them. Traced why: discovery is seeded
entirely from `forward_returns.return_{scale}_suspect` flags, and a corruption
confined to `high`/`low` (VWO's `high=99999.99`, DIA's `high=100000`, both with a
sane `open`/`close`) never trips a return-based flag (`forward_returns` is computed
open-to-open). Live-checked: only 18-20 of 320 registered `(symbol, tf)` pairs were
ever discoverable that way -- 94% of the corpus was never scanned by this tool at
all, not just these two symbols.

**Real fix: rewrote the tool's candidate-discovery query** (`ops_known_corrupt_print_cleanup.py`,
`_ALL_TF_PAIRS_SQL` replacing `_CANDIDATE_TF_PAIRS_SQL`) to scan every registered
`(symbol, tf)` pair directly via `backfill_status` (~320 pairs, cheap -- single-
partition window-function queries, not a full-corpus row scan) instead of proxying
through derived-return suspect flags. This is the systemic fix, not a hand-patch of
the 2 known rows.

**Live full-corpus dry-run under the fix found 40 CONFIRMED_CORRUPT bars across 14
symbols** (DBC/DIA/EDV/EFA/EWG/FXI/GLD/IWM/RSP/SPY/UUP/VWO/VYM/XRT) -- 20x the
previously-known count (KRE + DIA/1d already fixed by prior sessions). Every row the
identical clean signature (`isolated_spike_neighbors_agree`: tightly-agreeing
neighbors, single-field order-of-magnitude outlier). Most consequential single find:
SPY's `high=1441.65` on a bar where open/close were ~$142 -- SPY's corpus-wide
weight makes this the highest-value single correction in the batch. 28 rows
correctly classified `MARKET_EVENT` (the known 2010-05-06 Flash Crash cluster,
cross-symbol corroborated) and excluded from correction, matching todo 152's
established precedent. Applied after human review of the dry-run report plus an
explicit operator confirmation given the blast radius grew from 2 symbols to 14.

**A second gap found closing out the CV re-check** (see todo 147's disposition):
2 more corrupt prints (FXY 5m 2008-09-24, IWM 5m 2007-08-08) were sitting just
under the tool's 10x default `--magnitude-threshold` (FXY ~9.97x, IWM ~9.90x) --
the same threshold-sensitivity gap todo 154 already flagged for KRE (needed
threshold 8, not 10). Re-scanned with `--magnitude-threshold 9`, found and applied
7 more CONFIRMED_CORRUPT rows across FXY/IWM's other timeframes (the same corrupt
tick propagates through 15m/1h/1d aggregation from the 5m source bar).

**Recompute**, all 46 affected `(symbol, tf)` pairs total (45 from the main batch +
1 already covered, plus FXY/IWM's 8): `backfill_status` reset to `pending`,
`feature_vectors`/`forward_returns` deleted for those pairs (full history per pair,
not a bounded window -- avoids under-sizing the lookback/lookahead contamination
radius), `backfill_feature_factory.py --compute-only --workers 4` (12 workers
OOM-killed twice at ~5-6 min elapsed, confirmed via `journalctl -k` not guessed --
2.3-2.9GB RSS per worker exceeded available memory; 4 workers completed cleanly),
`forward_return_writer.py --training-window-end 2025-12-24T05:15:00Z`. Zero
orphaned processes at any point (checked after every run).

**New gotcha for `docs/reference/gotchas.md`:** `backfill_feature_factory.py
--compute-only`'s default worker count is unsafe for a multi-symbol full-history
recompute on this machine -- use `--workers 4` for anything touching more than a
handful of symbols at once.

Full verification and closing CV numbers: see todo 147's disposition (the CV metric
this todo's fix was gating).

# `price_sanity_status='confirmed_corrupt'` doesn't reach feature computation; VWO/DIA also never flagged at all

## 2026-07-21 status: code fix landed, recompute still pending

Todo 124's fix is in — `backfill_feature_factory.py` (and `regime_writer.py`/
`forward_return_writer.py`, same exposure pattern) now read `market_data_ohlcv_tradeable`
instead of raw `market_data_ohlcv` + inline `volume > 0`. The KRE row's `feature_vectors.
true_range_pct` will still show the stale corrupt value (7.855) until the recompute this todo
calls for actually runs against the fixed code — that recompute is deliberately not yet done
(concurrent DB load from the 143.1-08 backfill at time of the code fix; see todo 124's own
2026-07-21 note). VWO/DIA also still need their candidate-discovery gap addressed separately
(never flagged at all, a different bug from KRE's) before this todo can close.

## Correction to initial framing

This todo originally claimed "VWO/DIA/KRE were all never corrected." That's only true for
VWO and DIA. **KRE was correctly identified and flagged** — verified live:
`market_data_ohlcv.price_sanity_status='confirmed_corrupt'` for the KRE row, and
`forward_returns.return_fast/return_mid` for that bar are sane and not suspect (151/154 did
their job for the columns they touch). The actual bug is one level deeper and affects KRE
too, despite it being "correctly" flagged.

## What's wrong

Two distinct gaps, found investigating why todo 147's `true_range_pct` CV check still fails
post-151/154:

**1. VWO (2007-05-02 15:00, 1h, `high=99999.99`) and DIA (2009-06-02 14:00, 5m,
`high=100000`) were never flagged at all** — `price_sanity_status` is NULL for both, verified
live via psql. Same candidate-discovery gap 154 already documented for KRE: discovery is
seeded from `forward_returns.return_*_suspect` flags, and these two prints apparently never
tripped that flag either (both were found via todo 147's independent CV investigation, not
this tool's own discovery path).

**2. Even a correctly-flagged row (KRE) still corrupts `feature_vectors.true_range_pct`,
because the flag never reaches feature computation.** `market_data_ohlcv_tradeable` (the
view CLAUDE.md mandates for all compute/measurement reads) DOES filter
`price_sanity_status IS DISTINCT FROM 'confirmed_corrupt'` correctly. But
`services/backfill_feature_factory.py` — the service that actually computes
`feature_vectors.true_range_pct` — reads the RAW `market_data_ohlcv` table directly (its own
docstring: "Source invariant (T1/D-05): Only market_data_ohlcv is read for compute"), not the
tradeable view. Confirmed via `tests/unit/test_market_data_ohlcv_boundary.py`'s allow-list:
`backfill_feature_factory.py` is listed as "Already correctly filters with `volume > 0`
(confirmed correct via empirical audit **2026-07-16**... Tier-2 follow-up, todo 124's sibling
audit list)."

**That audit predates `price_sanity_status`, which didn't exist until todo 149's migration
(2026-07-19/20).** `volume > 0` and the tradeable view's filter WERE equivalent when audited
— they no longer are. `price_sanity_status='confirmed_corrupt'` rows still have `volume > 0`
(price columns are deliberately never mutated, per Renaissance data-retention principle), so
`backfill_feature_factory.py`'s `volume > 0`-only filter lets them straight through. This is
why 154's KRE fix (`DELETE FROM feature_vectors` + `backfill_feature_factory.py
--compute-only --symbols KRE` recompute) reproduced the exact same corrupt `true_range_pct`
value on recompute — the recompute read the same raw, unmutated, still-`high=400` row again.
`ops_known_corrupt_print_cleanup.py`'s own docstring claims setting the flag "closes th[e]
residual exposure" for features computed directly from raw OHLCV (momentum_z_*, volatility_
rank, etc.) — that claim is **not true for the batch/backfill computation path**, only for
any consumer that actually reads `market_data_ohlcv_tradeable`.

## Blast radius

Small and bounded today: `SELECT price_sanity_status, count(*) FROM market_data_ohlcv GROUP
BY price_sanity_status` → 20 rows `confirmed_corrupt`, 16 `ambiguous`, 484 `plausible`, rest
NULL (out of 215.6M total rows). But every one of those 20 `confirmed_corrupt` rows still
feeds `true_range_pct` and every other feature computed directly from raw high/low/close
(`body_ratio`, `upper_wick_ratio`, `lower_wick_ratio`, `range_vs_atr`, `bar_close_pos`,
`dist_from_high`/`dist_from_low`, `stoch_k`, `range_pct`, etc. — same exposure class
`ops_known_corrupt_print_cleanup.py`'s own docstring names) via `backfill_feature_factory.py`.
Not urgent by row count, but architecturally the "flag it and downstream consumers respect
it" contract is silently false for the one consumer (feature computation) the correction
mechanism was built to protect.

## Fix

1. **VWO/DIA**: run `ops_known_corrupt_print_cleanup.py --symbols VWO DIA --apply` (human
   dry-run review first, per its own safety design) to flag them — same as KRE's fix, just
   two more rows.
2. **The real fix**: migrate `services/backfill_feature_factory.py` to read from
   `market_data_ohlcv_tradeable` instead of raw `market_data_ohlcv` — this is exactly what
   [todo 124](124-market-ohlcv-tradeable-view-tier2-audit.md) already tracks, but its current
   text ("would only gain a style/DRY benefit, not a correctness fix") is now **stale** —
   written 2026-07-16, before `price_sanity_status` existed. Updated 124 directly with this
   finding; that todo now owns the actual fix, this one is the evidence trail.
3. After 124's fix lands, redo the DELETE + recompute sequence for all `confirmed_corrupt`
   rows (KRE plus the newly-flagged VWO/DIA) so `feature_vectors`/`forward_returns` actually
   exclude them, then re-run todo 147's CV check a third time.

## References

- `.planning/todos/pending/147-vol-normalized-target-low-bull-divergence.md` — the CV
  re-check this gap was found investigating
- `.planning/todos/pending/124-market-ohlcv-tradeable-view-tier2-audit.md` — now the owner
  of the actual fix (raw-table → tradeable-view migration for
  `backfill_feature_factory.py`); updated with this finding
- `scripts/ops/corpus/ops_known_corrupt_print_cleanup.py:1-12` — docstring claims this
  "closes th[e] residual exposure" for raw-OHLCV-derived features; not true for the batch
  compute path given (2) above
- `services/backfill_feature_factory.py:16` — "Source invariant (T1/D-05): Only
  market_data_ohlcv is read for compute"
- `tests/unit/test_market_data_ohlcv_boundary.py` `_ALLOW_LIST["services/backfill_feature_factory.py"]`
  — the stale 2026-07-16 "confirmed correct" note
- Live verification (2026-07-20): `market_data_ohlcv.price_sanity_status` NULL for VWO
  2007-05-02/DIA 2009-06-02, `'confirmed_corrupt'` for KRE 2007-09-18;
  `feature_vectors.true_range_pct` still 7.855 for the KRE row despite the flag and a
  completed recompute; `forward_returns` for the same KRE row is sane (return computation
  uses `open`, unaffected by this particular corrupt `high` value — coincidental, not
  systematic protection)
- Distinct from the 2010-05-06 IGV/CWB/VUG cluster also surfaced in this CV re-check — that's
  the real Flash Crash, legitimate per todo 152's crisis-event precedent, not corrupt
