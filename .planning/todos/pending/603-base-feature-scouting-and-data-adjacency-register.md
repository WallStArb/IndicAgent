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
4. Rejections and proposals recorded as `concept_registry` rows (no new table); `L` declared in the existing research ledger before each run and counting measured features (shares the budget of todos 440 and 601).
5. Glossary first (naming rule): `base feature` (composition `base`), `data adjacency register`, `admission gate`, before any code.

## Gates

No IC before admission. Capture carries no look count; every admitted column does. No model admits a feature.

## Owner ruling 2026-11-09: extended hours

Extended-hours bars (pre-market, after-hours, and the overnight session from 2026-12-06) stay raw only: stored, never selected; canonical 5m stays the RTH grid. Summary features (pre-market return, range, volume share, after-hours return) come later from a separate kernel over raw and attach to open-time and daily features.

## Source findings 2026-11-09 (Massive docs, verified by reading)

Massive has no earnings endpoint in its own stocks section; earnings come from partner feeds (Benzinga from 2010-04-30, `date`, `time` EST, `date_status`, `last_updated`; TMX/Wall Street Horizon corporate events from 2018) on expansion plans, with no before-open or after-close flag and no revision history stated. Its point-in-time handling is thin: income statements have no as-of parameter and `filing_date` is the most recent filing for the period. Ticker events are marked experimental and market holidays are forward-looking only. Our `corporate_action` (effective_date, factor, recorded_at, supersedes) is stronger on point in time than Massive's; our `dividend_events` lacks declaration, record and pay dates, which Massive's dividends endpoint serves on all plans.

## Owner ruling 2026-11-09: blind model proposer allowed

A model may propose base features under four rules: it never sees IC, verdicts or returns; every proposal is a timestamped spec with a mechanism, logged always and counted in `L` once measured; admission is mechanical and only `ConceptRegistryService` flips status; refining results into neighbours is a separate pre-registered step. Discovery classes A to E (mechanism, combinatorial, target-free structure, target-aware learning, error analysis) and the order of use are in the idea doc.

## Review 2026-11-09

Simplified after a five-step review: no daemon, no new ledger; four small artifacts (register, admission gate function, `L` in the research ledger, discovery methods as runner jobs built after the first counted test). Admission statistics use the discovery span only; learned latent features are fit on that span, frozen with a hash and applied causally. See the idea doc, 'Corrections after review'.

## Counting is a price, not a cap (2026-11-09)

Ideas are never limited by the look count; the count only sets the evidence bar for measured features. Keep exploration cheap with an exploration span versus a confirmation span, effective-dimension reduction (class C), and hierarchical gatekeeping. The span split needs reconciling with E15-E18 (every look at the vintage is counted) and an owner ruling before use; see the idea doc.
