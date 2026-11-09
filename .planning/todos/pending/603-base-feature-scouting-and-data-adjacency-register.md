---
status: pending
priority: P1
filed: 2026-11-09
source: owner 2026-11-09 (a process that looks at the data we have and adjacent retrievable data, proposes new base features; same thinking for regimes and families)
---

# Base feature scouting: the data adjacency register, then admission gates

## What

Design: `docs/ideas/base-feature-scouting-and-the-research-ladder.md`. The proposer measures every numeric column that exists; nothing asks what should exist. Build the lowest rung first.

## Steps

1. Data adjacency register (a doc under `docs/reference/` first): one row per field each source serves or could serve (source, field, availability time, history start, retrieval cost, stored yes/no/partial, base features enabled, status). Seed from the Massive file columns and REST endpoints, Alpaca bar and quote fields, IBKR fields, FRED, Yahoo, EDGAR, FINRA; diff against `ohlcv_raw` and stored tables. Verify availability and point-in-time quality for each seed row before capture.
2. Capture the cheap ones with the Massive onboarding (todo 600): trade count, VWAP, extended hours in raw, dated shares outstanding and market cap, splits, dividends and ticker events.
3. Admission gate set as code (causality, memory, NaN-not-fill, asset-agnostic, point-in-time, unit-free, coverage floor, feature-to-feature uniqueness; never the target), recorded rejection reasons, registration through `ConceptRegistryService`.
4. Negative-space log and the per-batch `L` increment in the ledger (shares the budget of todos 440 and 601).
5. Glossary first (naming rule): `base feature` (composition `base`), `data adjacency register`, `admission gate`, before any code.

## Gates

No IC before admission. Capture carries no look count; every admitted column does. No model admits a feature.

## Owner ruling 2026-11-09: extended hours

Extended-hours bars (pre-market, after-hours, and the overnight session from 2026-12-06) stay raw only: stored, never selected; canonical 5m stays the RTH grid. Summary features (pre-market return, range, volume share, after-hours return) come later from a separate kernel over raw and attach to open-time and daily features.

## Source findings 2026-11-09 (Massive docs, verified by reading)

Massive has no earnings endpoint in its own stocks section; earnings come from partner feeds (Benzinga from 2010-04-30, `date`, `time` EST, `date_status`, `last_updated`; TMX/Wall Street Horizon corporate events from 2018) on expansion plans, with no before-open or after-close flag and no revision history stated. Its point-in-time handling is thin: income statements have no as-of parameter and `filing_date` is the most recent filing for the period. Ticker events are marked experimental and market holidays are forward-looking only. Our `corporate_action` (effective_date, factor, recorded_at, supersedes) is stronger on point in time than Massive's; our `dividend_events` lacks declaration, record and pay dates, which Massive's dividends endpoint serves on all plans.
