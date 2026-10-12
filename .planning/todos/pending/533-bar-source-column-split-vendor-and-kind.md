# 533: bar `source` column mixes vendor and kind; split into vendor plus route/kind

Filed: 2026-10-12
Owner: pending
Priority: P2 (do with the next migration that rewrites these tables; not worth a standalone
rewrite)

Evidence (2026-10-12): `market_data_ohlcv.source` and `ohlcv_intraday_raw_archive.source`
hold two different kinds of value in one column:

| Label | Rows (canonical + archive) | Names |
|---|---|---|
| `alpaca` | 220M + 82M | vendor |
| `tradier` | 6.7M | vendor |
| `ibkr_named` | 99M + 120M | vendor plus fetch kind (named contract) |
| `ibkr_fallback` | 181K | vendor plus the d2-v2 rule outcome |
| `derived_5m` | 135M | a computation and its input timeframe, not a vendor |

`ohlcv_load.source` holds vendors only (CHECK: tradier, ibkr, derived, alpaca). The mismatch
broke every IBKR ingress write from 2026-10-10 15:03 UTC to 2026-10-12 (aaa67e637 copied the
bar label into the load row; fixed in 33a177772). `src/intelligence/bars/sources.LABEL_VENDOR`
(31e61063c) is now the single label-to-vendor map and the ingress contract refuses an unmapped
label, so the gap is closed for writes. Readers still disagree: the completeness report's SQL
`CASE` (`scripts/ops/bars/ops_capture_completeness.py`) maps only `ibkr_named` and
`derived_5m`, and `src/intelligence/bars/integrity_checks._PRIMARY_LABEL` is a reverse copy.

The qualifiers carry meaning: `market_data_ohlcv_tradeable` nulls volume by label
(`ibkr_venue`, `ibkr_fallback`: venue volume, not consolidated), and `CANONICAL_1D_SOURCES`, the
1d digest and D7 read the labels. A plain rename to `ibkr` would lose that.

Design direction: `source` = vendor only (the `ohlcv_load` vocabulary), plus a separate
route/kind column (`named`, `venue`, `fallback`, `grid_5m`), the way `ohlcv_observation` already
keeps `route` apart. Readers that need volume validity read the kind column.

Cost: about 450M rows across compressed hypertables (decompress, update, recompress, bare
`VACUUM` per the compressed-column migration template), plus every reader of `source`
(tradeable view, D7, 1d digest, `CANONICAL_1D_SOURCES`, completeness report). Until then, the
ops `CASE` and `_PRIMARY_LABEL` should read from `LABEL_VENDOR` or carry a test that pins them
to it. Related: todo 530 (writer-labeled loads have no bar-label join; same vocabulary gap).

Adjacent finding (code review, 2026-10-12): for archive-destination timeframes (15m/1h), a
refusal by the archive writer is followed by `_record_refusal`'s `archive_refusal_rows`, which
upserts the same rows into the same archive table (latest answer wins), overwriting the stored
observations the refusal meant to protect. The raw archive should be append-only per
(vendor, observed_at) rather than last-wins; decide that alongside the vendor/kind split.
