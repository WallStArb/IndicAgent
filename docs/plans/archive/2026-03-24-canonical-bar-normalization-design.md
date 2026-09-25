# Canonical Bar Normalization — Design Spec

**Date:** 2026-03-24
**Status:** Shipped
**Milestone:** v2.1

> **Name drift note (2026-03-28):** `tws_daemon` / `tws_daemon.py` referenced in this doc is now `data_provider_agent` / `DataProviderAgent` (Phase 53.3 rename, in progress).

---

## Problem

`market_data_ohlcv` is inconsistently populated:

- **Live path (tws_daemon):** emits a 1m bar every minute — flat bar (`OHLC=prev_close, volume=0`) when no trades occur. Canonical 1440-bar/day grid.
- **Backfill path (historical_backfill.py):** stores only bars IBKR returns. Quiet minutes have no row. Gaps exist for every instrument during low-activity periods.

This means `intelligence_features` computed from backfilled data is computed on a gapped series — different distribution than live inference. A Renaissance violation: the model trains on data that does not match what it sees in production.

**Goal:** `market_data_ohlcv` is always a complete canonical grid. Every minute (or TF slot) the market was open has exactly one row — either a real trade bar or a labeled synthetic fill. No gaps, ever.

---

## Design Principles (Renaissance)

1. **Every open-session slot is a data point.** A quiet minute on an active futures market is signal — not absence of data.
2. **Never fabricate price from nothing.** Synthetic bars require a `prev_close` from the same session. No price → no bar.
3. **Data provenance is sacred.** Every row knows its origin. `WHERE source != 'synthetic_fill'` always returns pure trade data.
4. **Deterministic and reproducible.** Same IBKR data + same `pandas_market_calendars` version → identical canonical grid. No heuristics, no magic thresholds.
5. **The calendar is the authority.** Holidays, maintenance windows, half-days — sourced from `pandas_market_calendars` where applicable; session day-of-week rules used for FX where PMC has no meaningful calendar.

---

## Architecture

### New Module: `src/core/bar_normalizer.py`

Single responsibility: given a sorted list of OHLCV bars + session context, return a complete canonical grid with no gaps during verified open sessions.

**Interface:**

```python
def normalize_bars(
    bars: list[dict],
    symbol: str,
    timeframe: str,
    session_id: str,
    exchange: str,
    start: datetime,
    end: datetime,
) -> list[dict]:
    """
    Returns `bars` with synthetic flat bars inserted for every expected
    timestamp within [start, end] that falls inside a verified open session
    but has no corresponding bar in `bars`.

    Synthetic bars: OHLC = prev_close, volume = 0, source = "synthetic_fill".
    If no prev_close is available at the start of a gap, that gap is skipped
    (never fabricate a price from nothing).

    Args:
        bars: sorted list of OHLCV dicts (must include 'timestamp', 'open',
              'high', 'low', 'close', 'volume', 'source')
        symbol: instrument base symbol (e.g. "ES", "SPY")
        timeframe: "1m", "5m", "15m", "1h", "4h", "1d"
        session_id: from instrument contract_details — actual codebase values:
                    "futures_24_5", "nyse", "crypto_24_7", "fx_24_5"
        exchange: IBKR exchange string from contract_details (e.g. "CME",
                  "CBOT", "COMEX", "NYMEX", "CFE", "ARCA", "NASDAQ")
                  Used to select the correct pandas_market_calendars calendar
                  for futures, where session_id alone is ambiguous.
        start: inclusive range start (UTC)
        end: inclusive range end (UTC)

    Returns:
        Complete list of bars ordered by timestamp. Real bars preserve their
        original source value. Synthetic bars have source="synthetic_fill".
    """
```

**Algorithm:**

1. Determine the PMC calendar (or day-of-week rule) using `_resolve_calendar(session_id, exchange)` — see mapping below
2. Generate complete expected timestamp grid within `[start, end]` at `timeframe` resolution, filtered to verified open session slots only (holidays, maintenance windows, half-days excluded)
3. Build index of existing bars by timestamp
4. Walk expected grid in order:
   - Slot has real bar → emit as-is, update `prev_close`
   - Slot is missing + `prev_close` available → emit synthetic flat bar, update `prev_close`
   - Slot is missing + no `prev_close` → skip (gap at start of series)
5. Return complete list

### Calendar Resolution: `_resolve_calendar(session_id, exchange)`

Two-stage lookup. `session_id` determines the approach; `exchange` disambiguates within futures.

**Stage 1 — session_id routing:**

| `session_id` | Trading days | Session window per day |
|---|---|---|
| `nyse` | NYSE calendar (holidays + half-days) | **04:00–20:00 ET** (pre-market through after-hours); half-days end at 13:00 ET |
| `crypto_24_7` | Every day | 00:00–24:00 UTC — always open |
| `fx_24_5` | Mon–Fri day-of-week rule | 00:00–24:00 UTC per trading day |
| `futures_24_5` | PMC calendar from Stage 2 exchange lookup | Per-exchange Globex session hours |

**NYSE session detail:** IBKR returns equity/ETF bars from 4:00am–8:00pm ET (`useRTH=False`). The canonical grid covers the full 16-hour window. NYSE calendar is used exclusively for determining which **days** are trading days and early-close times — the session hours (4am–8pm) are fixed regardless of PMC's RTH window definition. On half-days (e.g. day before Thanksgiving, Christmas Eve), PMC provides the early close time and the session ends there instead of 8pm ET.

**Stage 2 — futures exchange → PMC calendar:**

| IBKR `exchange` | `pandas_market_calendars` calendar | Instruments |
|---|---|---|
| `CME` | `CME_Equity` | ES, NQ, RTY |
| `CBOT` | `CBOT` | YM, ZB, ZT, ZN, ZF, ZC, ZS, ZW |
| `COMEX` | `CME` | GC, SI, HG |
| `NYMEX` | `CME` | CL, NG |
| `CFE` | `CBOE` | VIX |

Note: IBKR exchange strings and PMC calendar names are not the same. The mapping above is explicit — do not infer one from the other.

> **CME maintenance window:** `CME_Equity` and `CBOT` calendars in `pandas_market_calendars` encode Globex session hours including the Sunday maintenance window. Verify coverage against the pinned PMC version at implementation time and add a smoke test that confirms the Sunday gap is correctly excluded.
> **PMC version:** Pin `pandas-market-calendars>=4.3` in `requirements.txt` — maintenance window data improved significantly in 4.x.

### FX Session Logic

FX instruments (`fx_24_5`: EUR, GBP, USD) use a day-of-week rule consistent with the existing `TradingSession` model in `src/core/models.py`:
- Open: Sunday 17:00 ET (Monday 00:00 UTC)
- Close: Friday 17:00 ET (Friday 22:00 UTC)
- No PMC calendar — avoids disagreement with the existing session model

### Source Tags

| `source` value | Meaning |
|---|---|
| `"authoritative"` | Live TWS real-time bar — includes quiet-minute flat bars emitted by tws_daemon when no 5s ticks arrived. The live daemon had an active feed and confirmed no trades. |
| `"historical_backfill"` | Real IBKR historical bar |
| `"derived_1m"` | HTF bar aggregated from 1m in backfill |
| `"synthetic_fill"` | **New** — flat bar synthesized during normalization; verified open session, no IBKR trade data returned |

**Acknowledged divergence:** Live flat bars carry `source="authoritative"` because the tws_daemon had a live feed and directly observed no trades. Backfill synthetic fills carry `source="synthetic_fill"` because their absence is inferred from missing IBKR historical data — epistemically weaker. This distinction is intentional and preserved. `WHERE source = 'authoritative'` returns only live-confirmed bars. `WHERE source IN ('authoritative', 'historical_backfill', 'synthetic_fill')` returns the full canonical grid.

---

## Integration Points

### 1. `historical_backfill.py` — fetch stage (inline, automatic)

After IBKR returns bars for a symbol+timeframe gap, before `INSERT INTO market_data_ohlcv`:

```python
raw_bars = ibkr_fetch(symbol, tf, gap_start, gap_end)
canonical_bars = normalize_bars(
    raw_bars, symbol, tf,
    session_id=instrument.session_id,
    exchange=instrument.exchange,
    start=gap_start, end=gap_end
)
db_upsert(canonical_bars)  # ON CONFLICT DO NOTHING — idempotent
```

All future fetches automatically produce canonical output. No gaps enter the table from the backfill path.

### 2. `historical_backfill.py` — `--normalize` flag (historical pass)

Reads existing `market_data_ohlcv` rows per symbol+timeframe over the full stored range, runs `normalize_bars`, upserts missing synthetic fills.

- Idempotent — safe to re-run
- Covers all data predating this feature
- Applies to ALL symbols and ALL timeframes
- `ON CONFLICT DO NOTHING` — existing real bars never overwritten
- Progress reported per symbol

```bash
python production/scripts/historical_backfill.py --normalize
python production/scripts/historical_backfill.py --normalize --symbols ESM6,ZBM6
```

### Required co-change: `_TF_MINUTES` in `historical_backfill.py`

The `_TF_MINUTES` dict (used by `detect_gaps`) currently lacks `"4h"`. Must add `"4h": 240` alongside the normalizer implementation — omitting it causes a `KeyError` or incorrect gap detection when normalizing 4h bars.

---

## Guarantee

After `--normalize` runs and all future fetches use `normalize_bars`:

> **If the market was open, the row exists. If the row exists, it is a real trade, a live-confirmed flat bar, or a labeled synthetic fill. No gaps, ever.**

---

## Dependencies

- `pandas-market-calendars>=4.3` — add to `requirements.txt`
- No schema changes to `market_data_ohlcv` — `source` column already exists

---

## Testing

Unit tests in `tests/unit/test_bar_normalizer.py`:

| Test case | Assertion |
|---|---|
| Equity: gap spanning overnight (8pm–4am) | No fill across session boundary |
| Equity: gap on market holiday | No fill — entire day excluded |
| Equity: half-day early close (1pm ET) | Filled 4am–13:00 ET, not filled 13:00–20:00 ET |
| Equity: gap at 5:32am pre-market (trading day) | Flat bars filled |
| Equity: gap at 10:32am RTH (trading day) | Flat bars filled |
| Equity: gap at 6:15pm after-hours (trading day) | Flat bars filled |
| Futures_24_5: gap at 2am weekday | Filled |
| Futures_24_5: gap over weekend | Not filled |
| Futures_24_5: gap during CME Sunday maintenance | Not filled |
| crypto_24_7: any gap | Filled |
| FX: gap within Mon–Fri window | Filled |
| FX: gap over weekend | Not filled |
| No prev_close at start of series | Gap skipped, no price fabricated |
| Idempotent: running normalize twice | Same result |
| HTF (15m): gap on trading day | Correct 15m slots filled |
| HTF (1d): gap on market holiday | No synthetic daily bar inserted |
| source preservation: `derived_1m` bars | Source not overwritten to `synthetic_fill` |
| `4h` timeframe | Normalizes correctly (requires `_TF_MINUTES` co-change) |

---

## Out of Scope

- Modifying `tws_daemon.py` live flat bar logic (handled separately — see Live Code note below)
- Changing `intelligence_features` schema — downstream consumers unchanged
- Changing replay logic — replay reads canonical `market_data_ohlcv` unchanged

## Live Code Note

`tws_daemon.py` flat bar behavior is correct by design. When no 5s ticks arrive for a minute (quiet pre-market, illiquid period, holiday), the heartbeat emits `OHLC=prev_close, volume=0` — this is the right canonical representation of "market was accessible, no trades occurred." The live daemon does not need calendar awareness because IBKR simply stops sending 5s bars when the exchange is closed, and the session boundary reset logic handles overnight/weekend gaps. No changes to `tws_daemon.py` are required.
