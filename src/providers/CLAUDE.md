# Data Providers — Developer Reference

## Batch history leaves (phase 190)

Vendor batch-history mechanics live in per-vendor leaves satisfying the `HistoryProvider`
protocol (`src/providers/base.py`): `AlpacaProvider`. Callers dispatch via
`history_leaf(vendor, ...)` (`src/providers/__init__.py`), never a concrete leaf import
outside this ring (CI fence: `tests/unit/test_provider_leaf_boundary.py`). A leaf owns its
vendor's credentials, pagination, native pacing, and symbology; policy never enters a leaf.
Alpaca credentials come from `.env` (`ALPACA_KEY_ID`/`ALPACA_SECRET_KEY`) via Settings;
pacing is APR-backed (`infra.alpaca.rate_limit_max_requests`, migration 469). The nightly
capture runner is `scripts/ops/bars/ops_bar_nightly.py`.

The IBKR provider, its gateway and its fetcher were deleted 2026-11-13 (git history holds them).
Historical bars come from the Massive archive and the Alpaca nightly through the raw-capture loaders.
