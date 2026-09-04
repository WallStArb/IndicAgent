# Instrument Data Model

**Canonical name:** Instrument Data Model
**Status:** current
**Last Updated:** 2026-09-04

---

## What It Is

Everything IndicAgent knows about a symbol — its identity, its metadata, its narrative history,
and every classification claim made about it — lives across four tables, not one. This doc is
the map: what each table owns, how they key together, and where the boundaries are deliberately
drawn. It doesn't duplicate the two governance registries built on top of this base (ITR, CVR)
in depth — it shows where they attach and links out to their own canonical docs.

```
instruments                 ← core identity (PK: symbol)
  ├─ instrument_metadata     ← 1:1, sparse enrichment (listing_date, issuer, description)
  ├─ instrument_annotations  ← 1:many, narrative timeline (thesis / ai_insight / signal_context / regime_note)
  └─ instrument_tags         ← 1:many, falsifiable classification claims (governed by ITR)
        └─ tag_vocabulary    ← controlled taxonomy of tag concepts (governed by ITR)

contract_details.asset_class ─┐
contract_details.sector      ─┴─ free-text JSONB fields, partially cross-checked against
                                  controlled_vocabulary (governed by CVR — see Gaps below)
```

No single query or view joins all four tables today — a consumer wanting "everything about
TLT" runs four separate lookups. See Known Gaps.

---

## Table Schemas

### `instruments` — core identity

**231 active / 253 total rows** (`is_active` distinguishes tradeable-now from historical/rolled-off).
<!-- src: \d instruments + SELECT count(*)/count(*) FILTER (WHERE is_active) FROM instruments — verified 2026-09-04 -->
<!-- src: instruments.symbol PK, no top-level asset_class column — SELECT DISTINCT contract_details->>'asset_class' FROM instruments GROUP BY 1 returns fx(4)/futures(18)/equity(231) across all 253 rows — verified 2026-09-04 -->

| Column | Type | Description |
|--------|------|--------------|
| `symbol` | TEXT PRIMARY KEY | The tradeable identifier — e.g. `TLT`, `CL`, `6E`. Contract-specific (a rolled future gets a new row), not the same as `base`. |
| `base` | TEXT NOT NULL | The underlying root symbol a roll chain shares — e.g. `CL` is `base` for both the front-month and next-month WTI contracts. Indexed (`idx_instruments_base`) for roll-chain lookups. |
| `contract_details` | JSONB | Provider-shaped contract spec — see below. |
| `is_active` | BOOLEAN DEFAULT true | The canonical "is this tradeable right now" flag. ETF-filter pattern: `is_active = true AND contract_details->>'asset_class' = 'equity'`. |
| `expiry` | DATE | Futures/options only; `NULL` for equities/ETFs/FX. |
| `created_at` / `updated_at` | TIMESTAMPTZ | |

**`contract_details` JSONB shape** (observed keys, not a formal schema — this is IBKR's contract
shape passed through, not a designed IndicAgent structure):

```json
{
  "base": "CL", "symbol": "CL", "name": "Crude Oil WTI",
  "asset_class": "futures", "sector": "energy",
  "exchange": "NYMEX", "currency": "USD", "expiry": "",
  "tick_size": 0.01, "point_value": 1000.0,
  "session_id": "futures_24_5", "provider": "ibkr", "provider_meta": {}
}
```

Two fields matter far beyond the rest:

- **`asset_class`** — `'equity'` (ETFs) / `'futures'` / `'fx'`. The canonical instrument-type
  filter cited throughout this codebase (`instruments.contract_details->>'asset_class'`, no
  top-level column). **Drift-audited**: `VocabularyDriftAuditor` (`src/config/vocabulary_drift.py`)
  runs `SELECT DISTINCT contract_details->>'asset_class' FROM instruments WHERE is_active = true`
  against CVR's `asset_class` namespace every pipeline run and alerts on any unregistered value.
- **`sector`** — free text, **not** drift-audited (see Known Gaps). 48 distinct values currently
  in use across active instruments, at inconsistent granularity (`healthcare` and
  `healthcare_biotech` both exist; so do `industrials`, `industrials_rail`, and
  `industrials_trucking`).

**`trg_instruments_notify` trigger** (`notify_instrument_change()`) fires `NOTIFY instruments` on
every INSERT/UPDATE/DELETE. `FeatureVectorPipeline` (`src/intelligence/pipeline/cache_manager.py`)
holds a dedicated `LISTEN instruments` connection to invalidate its in-memory contract cache the
moment the universe changes, rather than polling. That connection needs `idle_session_timeout`
exempted at the session level (fixed 2026-08-08) — see the file's inline comment for why a
LISTEN connection can't tolerate a DB-wide idle-session reaper.

### `instrument_metadata` — sparse enrichment

**58 active / 61 total rows — ~25% coverage of the active universe.** Not required, not
backfilled automatically; populated opportunistically (Phase A's original 58-ETF seed accounts
for nearly all current rows).

| Column | Type | Description |
|--------|------|--------------|
| `symbol` | TEXT PRIMARY KEY, FK → `instruments(symbol)` | |
| `listing_date` | DATE | Inception date — distinct from `market_data_ohlcv`'s earliest bar, which reflects backfill depth, not the instrument's actual age. |
| `underlying_index` | TEXT | e.g. `S&P 500`, `Nasdaq-100`, `Russell 2000` |
| `issuer` | TEXT | e.g. `State Street`, `Invesco`, `BlackRock` |
| `description` | TEXT | One-line human-readable summary |
| `created_at` / `updated_at` | TIMESTAMPTZ | |

Example row:

```
symbol | listing_date | underlying_index | issuer       | description
SPY    | 1993-01-22   | S&P 500          | State Street | SPDR S&P 500 ETF — oldest and most liquid US equity ETF
```

### `instrument_annotations` — narrative timeline

**595 rows** (537 `ai_insight` / 58 `thesis`; `signal_context` and `regime_note` are
schema-allowed but currently unwritten — see Known Gaps). Point-in-time validity via
`valid_from`/`valid_to`, not a mutable "current state" row — `valid_to IS NULL` means still live.

| Column | Type | Description |
|--------|------|--------------|
| `id` | UUID PRIMARY KEY | |
| `symbol` | TEXT NOT NULL, FK → `instruments(symbol)` | |
| `annotation_type` | TEXT NOT NULL, CHECK | `'thesis'` \| `'signal_context'` \| `'ai_insight'` \| `'regime_note'` |
| `content` | TEXT NOT NULL | Free-form narrative |
| `source` | TEXT NOT NULL, CHECK | `'human'` \| `'ai'` |
| `model_id` | TEXT | e.g. `'tag-calibrator'` for machine-written rows |
| `confidence` | FLOAT, CHECK `[0,1]` | Only populated on some `ai` rows |
| `valid_from` / `valid_to` | TIMESTAMPTZ | |

Today's actual usage is narrower than the schema allows: `thesis` rows are 100% human, and
`ai_insight` rows are ~100% `TagCalibrator`'s own discovery/contradiction/expiry notes
(`model_id='tag-calibrator'`) — e.g. *"TagCalibrator measurement contradicts human-asserted tag
'yield_curve' for KRE: ..."*. This table is where ITR's empirical measurement engine explains
itself in prose, not just numbers.

### `instrument_tags` + `tag_vocabulary` — falsifiable classification claims

Full schema, lifecycle, and governance: **[Instrument Tag Registry](instrument-tag-registry.md)**
— not duplicated here. Summary for this doc's purposes: 1,244 tag assignments across 74 vocabulary
terms and 6 categories (`macro_driver` 383, `exposure` 318, `sensitivity` 284, `signal_role` 136,
`cycle_position` 83, `factor_regime` 40). A tag is a *falsifiable hypothesis*, not a static
category — `sensitivity`/`factor_regime`/`macro_driver` tags are empirically measured (OLS beta,
HAC p-value, BH-FDR) and can expire; `exposure`/`cycle_position`/most `signal_role` tags are
permanent human priors, never measured.

---

## Worked Example — TLT

Pulling the full picture for one symbol means four separate queries. All values below are live
(`SELECT`-verified, not illustrative):

**1. Identity** (`instruments`):
```
symbol=TLT  base=TLT  is_active=true
contract_details: {name: "iShares 20+ Year Treasury Bond ETF", asset_class: equity,
                    sector: equity, exchange: SMART, session_id: nyse, ...}
```
Note `sector: equity` — `contract_details.sector` classifies the *wrapper* (TLT trades as an
equity-structured ETF), not the *exposure* (treasuries). That distinction lives one layer down,
in ITR's `fi_treasury`/`rate_sensitive` tags below. Reading `contract_details.sector` alone and
expecting an asset-class-style breakdown is exactly the trap the Known Gaps section below warns
about — the two systems answer different questions and aren't reconciled today.

**2. Metadata** (`instrument_metadata`):
```
listing_date=2002-07-22  underlying_index="ICE US Treasury 20+ Year"  issuer=BlackRock
description="iShares 20+ Year Treasury Bond ETF"
```

**3. Tags** (`instrument_tags`, via ITR):
```
benchmark        weight=1.0   source=human      (signal_role — permanent prior)
fi_treasury      weight=1.0   source=human      (exposure — permanent prior)
fed_policy       weight=1.0   source=human      (macro_driver — permanent prior)
spread_leg       weight=1.0   source=human      (signal_role — permanent prior)
rate_sensitive   weight=1.0   source=human      (sensitivity — permanent prior)
risk_off         weight=0.9   source=human      (cycle_position — permanent prior)
recession        weight=0.9   source=human      (cycle_position — permanent prior)
yield_curve      weight=0.93  source=empirical  loading=+0.935  p<0.001  passes_fdr=true
credit_risk      weight=0.58  source=empirical  loading=-0.581  p<0.001  passes_fdr=true
inflation        weight=0.57  source=empirical  loading=-0.572  p<0.001  passes_fdr=true
yen_carry        weight=0.39  source=empirical  loading=+0.393  p<0.001  passes_fdr=true
dollar_strength  weight=0.28  source=empirical  loading=-0.284  p<0.001  passes_fdr=true
oil_price        weight=0.28  source=empirical  loading=-0.275  p<0.001  passes_fdr=true
em_flows         weight=0.26  source=empirical  loading=+0.255  p<0.001  passes_fdr=true
```
Seven permanent human-seeded priors (what TLT structurally *is*) plus seven independently
*measured* factor loadings TagCalibrator discovered — none of which were asserted by a human,
all of which cleared FDR-corrected significance against a real return series.

**4. Annotations** (`instrument_annotations`, 8 rows for TLT):
```
thesis     | human |                | "20+ year treasury — the duration benchmark. The dominant
                                       instrument for expressing rate regime views..."
ai_insight | ai    | tag-calibrator | "TagCalibrator empirically discovered 'yield_curve' for TLT
                                       (loading=0.935, bh_adjusted_p=0.0000, sample_n=...)"
ai_insight | ai    | tag-calibrator | ...6 more discovery notes, one per empirically-found tag
```
One human thesis, plus TagCalibrator narrating its own discovery of every empirical tag in
prose — this is the audit trail ITR itself doesn't have a dedicated table for (see ITR's Known
Gaps: "no dedicated audit-log table").

---

## Known Gaps

- **`sector` is free text with no controlled vocabulary and no drift audit.** Unlike
  `asset_class` (CVR-registered, `VocabularyDriftAuditor`-enforced), `sector` has accumulated 48
  distinct values at inconsistent granularity through organic growth during the 2026-08-05/06
  universe expansion (`healthcare` vs. `healthcare_biotech`; `industrials` vs. `industrials_rail`
  vs. `industrials_trucking`; `materials` vs. three `materials_*` subcategories). Nothing
  currently prevents a fifth `materials_*` variant from being added next expansion. Promoting
  `sector` into CVR (a `controlled_vocabulary` namespace + drift-audit source-column entry) would
  close this the same way `asset_class` is already closed — not yet done.
- **`instrument_metadata` covers ~25% of the active universe.** No backfill job populates it for
  newly added instruments; it was seeded once for the original Phase A ETF set and hasn't kept
  pace with the 111→231 expansion.
- **`instrument_annotations.annotation_type` is half-used.** `signal_context` and `regime_note`
  are valid per the CHECK constraint but have zero rows — either dead schema surface or an
  unbuilt consumer, not yet determined which.
- **No unified view joins the four tables.** Each consumer (ITR's three live readers, any
  ad-hoc investigation) writes its own JOIN. A `symbol_profile` view (or similar) exists only as
  an idea, not code — see `docs/research/intel-symbol-state-query-layer.md` for adjacent
  discussion of a descriptive per-symbol query layer.

---

## Related Docs

- `docs/foundation/instrument-tag-registry.md` — full ITR spec: tag lifecycle, TagCalibrator,
  live consumers, tag category taxonomy.
- `docs/foundation/controlled-vocabulary-registry.md` — CVR spec: how `asset_class` (and other
  symbolic taxonomies) are registered and drift-audited; the mechanism `sector` doesn't use yet.
- `docs/foundation/glossary.md` — canonical definition of `tag` (§"Instrument Vocabulary Terms").
- `docs/research/intel-symbol-state-query-layer.md` — adjacent idea: a per-symbol descriptive
  query layer that would sit on top of this data model.
