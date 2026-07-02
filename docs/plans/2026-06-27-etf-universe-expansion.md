# ETF Universe Expansion Plan

> **⚠️ DECISION (2026-06-30): `USO` and `UNG` dropped from this expansion.**
> Both are contango vehicles with structural negative roll yield — their returns are dominated by *decay*, not by any feature we want IC on. Non-stationary returns teach the ensemble spurious "signals" that are just the roll-decay schedule. This is the same reason `VIXY`/`UVXY` are already excluded.
>
> **Principle:** exclude all structural-negative-carry / contango vehicles from the IC corpus. Commodity exposure remains via `DBC` (broad basket, lighter roll drag), `DBA`, `DBB`, `PPLT`. Vol regime is NOT lost — it is captured as an *input* via the SPY realized-vol z-score VIX proxy in the cross-sectional regime model, not as a decaying tradeable instrument.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Expand the ETF universe from 58 → 79 instruments by adding commodity (energy, metals, agriculture, broad), international, FX, transportation, high-dividend-yield, market-neutral factor, and high-beta ETFs. Tag all new instruments with fine-grained sub-tags required by the commodity and FX regime groups defined in the cross-sectional regime model plan. Re-tag existing instruments with the new sub-tags where applicable.

**Dependency:** `docs/plans/2026-07-01-cross-sectional-regime-model.md` — regime group tag filters (`commodity_energy_crude`, `commodity_metals_precious`, `fx_*`, etc.) must exist in `tag_vocabulary` before regime groups can be enabled.

**Pipeline:** New instruments flow through the same 6-step corpus pipeline as existing ones. Steps 5-6 (ensemble_trainer, alpha_publisher) use per-symbol pooled IC weights — they naturally incorporate new symbols once IC scores exist.

**Tech Stack:** SQL (psycopg2), bash (backfill scripts), APR (config_state)

## Global Constraints

- Exception variable name is `error` — `except X as error:`
- All timestamps UTC
- No hardcoded numeric constants — all thresholds via APR
- All DB queries use `PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent`
- `instruments.contract_details` is JSONB — pass dict directly (asyncpg) or `json.dumps()` (psycopg2)
- New instruments must be `is_active = true` to be included by `get_active_contracts()`
- Backfill client-id 41 (provider uses 35; default 56 exceeds `_MAX_CLIENT_ID=50`)

---

## New Instruments

| Symbol | Name | Group | IPO | 1d days | Notes |
|---|---|---|---|---|---|
| DBC | Invesco DB Commodity Index | commodity_broad | 2006-02-03 | 7300 | GSCI-weighted: ~55% energy, ~15% metals, ~30% agri |
| DBA | Invesco DB Agriculture Fund | commodity_agri | 2007-01-05 | 7000 | Corn, wheat, soybeans, sugar |
| DBB | Invesco DB Base Metals Fund | commodity_metals | 2007-01-05 | 7000 | Aluminum, copper, zinc |
| PPLT | Aberdeen Platinum ETF | commodity_metals | 2010-01-08 | 5500 | Platinum spot |
| EZU | iShares MSCI Eurozone ETF | international | 2000-07-25 | 7300 | Eurozone equities (IBKR practical limit ~20yr) |
| EWG | iShares MSCI Germany ETF | international | 1996-03-12 | 7300 | Germany; oldest non-US single-country ETF |
| EWZ | iShares MSCI Brazil ETF | international | 2000-07-10 | 7300 | Brazil; commodity-exporter EM |
| VWO | Vanguard FTSE Emerging Markets ETF | international | 2005-03-04 | 7700 | Most liquid EM ETF |
| FXI | iShares China Large-Cap ETF | international | 2004-10-05 | 8000 | China H-shares |
| MCHI | iShares MSCI China ETF | international | 2011-03-29 | 5500 | China broad MSCI |
| UUP | Invesco DB US Dollar Index Bullish | fx | 2007-02-20 | 7000 | Dollar index (DXY proxy); reference symbol for fx_dollar_carry |
| FXE | Invesco CurrencyShares Euro Trust | fx | 2005-12-12 | 7700 | EUR/USD |
| FXY | Invesco CurrencyShares Japanese Yen | fx | 2007-02-20 | 7000 | JPY/USD |
| EDV | Vanguard Extended Duration Treasury ETF | rates | 2007-12-06 | 6800 | 25yr+ zero-coupon; extends rate sensitivity range |
| IYT | iShares Transportation Average ETF | transports | 2003-11-12 | 7300 | Rails/trucking/air/marine; classic leading-indicator sector, no prior coverage |
| FXA | Invesco CurrencyShares Australian Dollar Trust | fx | 2006-06-26 | 7300 | AUD/USD; commodity-currency proxy (China/metals/agri beta), diversifies FX group beyond reserve currencies |
| VYM | Vanguard High Dividend Yield ETF | defensive_yield | 2006-11-10 | 7300 | Broad market, screens on trailing yield alone — raw high-yield factor, complements SCHD's quality-dividend screen |
| SDOG | ALPS Sector Dividend Dogs ETF | defensive_yield | 2012-02-07 | 5200 | Literal "Dogs of the Dow" methodology — 5 highest yielders per GICS sector, equal-weighted, sector-diversified |
| BTAL | AGF US Market Neutral Anti-Beta Fund | factor_market_neutral | 2011-08-16 | 5100 | Long low-beta / short high-beta, dollar-neutral; near-zero equity beta — "Betting Against Beta" factor, no redundancy elsewhere in universe |
| IPO | Renaissance IPO ETF | high_beta | 2013-10-11 | 4500 | Recent-listing high-beta factor; long-only, liquid, no structural decay |
| SPHB | Invesco S&P 500 High Beta ETF | high_beta | 2011-05-05 | 5100 | Top-100 highest-beta S&P 500 names; liquid, non-leveraged high-vol factor, orthogonal to ARKK thematic tilt |

**Total: 58 → 79 instruments**

---

## Existing Instrument Re-tagging

New fine-grained sub-tags added alongside existing coarse tags (backward compat preserved).

| Symbol | Add tags | Rationale |
|---|---|---|
| GLD | `commodity_metals_precious` | Refines `commodity_metals` |
| SLV | `commodity_metals_precious` | Silver = 50% precious, 50% industrial; primary classification is precious |
| GDX | `commodity_metals_precious` | Gold miners — regime driven by gold price |
| AMLP | `commodity_energy_pipeline` | Midstream infrastructure; refines `commodity_energy` |
| OIH | `commodity_energy_crude` | Oil services — crude price beta |
| XOP | `commodity_energy_crude` | Oil & gas exploration — crude price beta |
| XLE | `commodity_energy_crude` | Broad energy sector — crude dominated |

---

## File Map

| File | Action | Purpose |
|---|---|---|
| `production/migrations/188_etf_expansion.sql` | Create | Tag vocabulary extension + re-tag existing + register 21 new instruments |
| `scripts/infrastructure/backfill/infrastructure_backfill_new_etfs.sh` | Create | Historical OHLCV backfill for all 21 new symbols |
| `scripts/ops/corpus/ops_corpus_new_etfs.sh` | Create | Corpus pipeline steps 1-6 scoped to new symbols |

---

## Task 0: Migration 188 — Tag Vocabulary + Instrument Registration

**Files:**
- Create: `production/migrations/188_etf_expansion.sql`

- [ ] **Step 1: Write the migration**

```sql
-- production/migrations/188_etf_expansion.sql
-- Migration 188: ETF universe expansion — 58 → 79 instruments.
--
-- 1. Extend tag_vocabulary with fine-grained commodity and FX sub-tags
-- 2. Re-tag existing instruments with fine-grained sub-tags
-- 3. Register 21 new instruments in instruments table

BEGIN;

-- ---------------------------------------------------------------------------
-- 1. Tag vocabulary extension
-- ---------------------------------------------------------------------------

INSERT INTO tag_vocabulary (tag, category, description) VALUES
    ('commodity_energy_crude',    'exposure', 'Crude oil futures or equity proxy — WTI/Brent price beta'),
    ('commodity_energy_pipeline', 'exposure', 'Midstream energy infrastructure — income, not crude spot beta'),
    ('commodity_metals_precious', 'exposure', 'Precious metals — gold, silver, platinum; monetary/inflation store of value'),
    ('commodity_metals_industrial','exposure','Industrial base metals — copper, aluminum, zinc; global demand proxy'),
    ('commodity_agri',            'exposure', 'Agricultural commodities — grains, softs, livestock'),
    ('commodity_broad',           'exposure', 'Broad commodity index — diversified across energy, metals, agriculture'),
    ('fx_usd',                    'exposure', 'US dollar index — long USD vs basket of major currencies'),
    ('fx_major',                  'exposure', 'Major developed-market currency vs USD — EUR, JPY, GBP, CHF'),
    ('fx_em',                     'exposure', 'Emerging market currency basket vs USD'),
    ('fx_commodity',              'exposure', 'Commodity-linked currency vs USD — AUD, CAD, NZD; proxy for China/metals/agri demand'),
    ('transports',                'exposure', 'Transportation sector — rails, trucking, air freight, marine; leading-indicator cyclical'),
    ('defensive_yield',           'exposure', 'High-dividend-yield equity — contrarian/mean-reversion factor distinct from dividend-quality (SCHD)'),
    ('factor_market_neutral',     'exposure', 'Long-short, dollar-neutral factor exposure — near-zero equity beta by construction (e.g. anti-beta)'),
    ('high_beta',                 'exposure', 'Liquid, non-leveraged high-volatility equity factor — elevated beta without structural rebalancing decay')
ON CONFLICT (tag) DO NOTHING;

-- ---------------------------------------------------------------------------
-- 2. Re-tag existing instruments with fine-grained sub-tags
--    Existing coarse tags (commodity_energy, commodity_metals) are preserved.
-- ---------------------------------------------------------------------------

INSERT INTO instrument_tags (symbol, tag, weight, source, evidence) VALUES
    -- Precious metals
    ('GLD', 'commodity_metals_precious', 1.0, 'human', '{"reason": "gold is the benchmark precious metal"}'),
    ('SLV', 'commodity_metals_precious', 0.8, 'human', '{"reason": "silver primary classification precious; 50% industrial but monetary regime driver"}'),
    ('GDX', 'commodity_metals_precious', 0.9, 'human', '{"reason": "gold miner equity; regime driven by gold price"}'),
    -- Energy sub-tags
    ('OIH', 'commodity_energy_crude',    0.9, 'human', '{"reason": "oil services — strong crude price beta"}'),
    ('XOP', 'commodity_energy_crude',    1.0, 'human', '{"reason": "oil & gas exploration — direct crude beta"}'),
    ('XLE', 'commodity_energy_crude',    0.8, 'human', '{"reason": "broad energy sector; crude-dominated"}'),
    ('AMLP','commodity_energy_pipeline', 1.0, 'human', '{"reason": "midstream MLP infrastructure; income not spot crude"}')
ON CONFLICT (symbol, tag) DO NOTHING;

-- ---------------------------------------------------------------------------
-- 3. Register 16 new instruments
--    contract_details mirrors SPY pattern: symbol, base, name, asset_class,
--    exchange, sector, tick_size, session_id, point_value, provider_meta.
--    asset_class = 'equity' for ETFs (including FX and commodity ETFs —
--    these are equity-structured funds, not futures).
-- ---------------------------------------------------------------------------

INSERT INTO instruments (symbol, base, contract_details, is_active) VALUES
    ('DBC',  'DBC',  '{"symbol":"DBC","base":"DBC","name":"Invesco DB Commodity Index Tracking Fund","asset_class":"equity","exchange":"SMART","sector":"commodity","tick_size":0.01,"session_id":"nyse","point_value":1.0,"provider_meta":{}}', true),
    ('DBA',  'DBA',  '{"symbol":"DBA","base":"DBA","name":"Invesco DB Agriculture Fund","asset_class":"equity","exchange":"SMART","sector":"commodity","tick_size":0.01,"session_id":"nyse","point_value":1.0,"provider_meta":{}}', true),
    ('DBB',  'DBB',  '{"symbol":"DBB","base":"DBB","name":"Invesco DB Base Metals Fund","asset_class":"equity","exchange":"SMART","sector":"commodity","tick_size":0.01,"session_id":"nyse","point_value":1.0,"provider_meta":{}}', true),
    ('PPLT', 'PPLT', '{"symbol":"PPLT","base":"PPLT","name":"Aberdeen Standard Physical Platinum Shares ETF","asset_class":"equity","exchange":"SMART","sector":"commodity","tick_size":0.01,"session_id":"nyse","point_value":1.0,"provider_meta":{}}', true),
    ('EZU',  'EZU',  '{"symbol":"EZU","base":"EZU","name":"iShares MSCI Eurozone ETF","asset_class":"equity","exchange":"SMART","sector":"international","tick_size":0.01,"session_id":"nyse","point_value":1.0,"provider_meta":{}}', true),
    ('EWG',  'EWG',  '{"symbol":"EWG","base":"EWG","name":"iShares MSCI Germany ETF","asset_class":"equity","exchange":"SMART","sector":"international","tick_size":0.01,"session_id":"nyse","point_value":1.0,"provider_meta":{}}', true),
    ('EWZ',  'EWZ',  '{"symbol":"EWZ","base":"EWZ","name":"iShares MSCI Brazil ETF","asset_class":"equity","exchange":"SMART","sector":"international","tick_size":0.01,"session_id":"nyse","point_value":1.0,"provider_meta":{}}', true),
    ('VWO',  'VWO',  '{"symbol":"VWO","base":"VWO","name":"Vanguard FTSE Emerging Markets ETF","asset_class":"equity","exchange":"SMART","sector":"international","tick_size":0.01,"session_id":"nyse","point_value":1.0,"provider_meta":{}}', true),
    ('FXI',  'FXI',  '{"symbol":"FXI","base":"FXI","name":"iShares China Large-Cap ETF","asset_class":"equity","exchange":"SMART","sector":"international","tick_size":0.01,"session_id":"nyse","point_value":1.0,"provider_meta":{}}', true),
    ('MCHI', 'MCHI', '{"symbol":"MCHI","base":"MCHI","name":"iShares MSCI China ETF","asset_class":"equity","exchange":"SMART","sector":"international","tick_size":0.01,"session_id":"nyse","point_value":1.0,"provider_meta":{}}', true),
    ('UUP',  'UUP',  '{"symbol":"UUP","base":"UUP","name":"Invesco DB US Dollar Index Bullish Fund","asset_class":"equity","exchange":"SMART","sector":"fx","tick_size":0.01,"session_id":"nyse","point_value":1.0,"provider_meta":{}}', true),
    ('FXE',  'FXE',  '{"symbol":"FXE","base":"FXE","name":"Invesco CurrencyShares Euro Currency Trust","asset_class":"equity","exchange":"SMART","sector":"fx","tick_size":0.01,"session_id":"nyse","point_value":1.0,"provider_meta":{}}', true),
    ('FXY',  'FXY',  '{"symbol":"FXY","base":"FXY","name":"Invesco CurrencyShares Japanese Yen Trust","asset_class":"equity","exchange":"SMART","sector":"fx","tick_size":0.01,"session_id":"nyse","point_value":1.0,"provider_meta":{}}', true),
    ('EDV',  'EDV',  '{"symbol":"EDV","base":"EDV","name":"Vanguard Extended Duration Treasury ETF","asset_class":"equity","exchange":"SMART","sector":"fixed_income","tick_size":0.01,"session_id":"nyse","point_value":1.0,"provider_meta":{}}', true),
    ('IYT',  'IYT',  '{"symbol":"IYT","base":"IYT","name":"iShares Transportation Average ETF","asset_class":"equity","exchange":"SMART","sector":"transports","tick_size":0.01,"session_id":"nyse","point_value":1.0,"provider_meta":{}}', true),
    ('FXA',  'FXA',  '{"symbol":"FXA","base":"FXA","name":"Invesco CurrencyShares Australian Dollar Trust","asset_class":"equity","exchange":"SMART","sector":"fx","tick_size":0.01,"session_id":"nyse","point_value":1.0,"provider_meta":{}}', true),
    ('VYM',  'VYM',  '{"symbol":"VYM","base":"VYM","name":"Vanguard High Dividend Yield ETF","asset_class":"equity","exchange":"SMART","sector":"defensive_yield","tick_size":0.01,"session_id":"nyse","point_value":1.0,"provider_meta":{}}', true),
    ('SDOG', 'SDOG', '{"symbol":"SDOG","base":"SDOG","name":"ALPS Sector Dividend Dogs ETF","asset_class":"equity","exchange":"SMART","sector":"defensive_yield","tick_size":0.01,"session_id":"nyse","point_value":1.0,"provider_meta":{}}', true),
    ('BTAL', 'BTAL', '{"symbol":"BTAL","base":"BTAL","name":"AGF US Market Neutral Anti-Beta Fund","asset_class":"equity","exchange":"SMART","sector":"factor_market_neutral","tick_size":0.01,"session_id":"nyse","point_value":1.0,"provider_meta":{}}', true),
    ('IPO',  'IPO',  '{"symbol":"IPO","base":"IPO","name":"Renaissance IPO ETF","asset_class":"equity","exchange":"SMART","sector":"high_beta","tick_size":0.01,"session_id":"nyse","point_value":1.0,"provider_meta":{}}', true),
    ('SPHB', 'SPHB', '{"symbol":"SPHB","base":"SPHB","name":"Invesco S&P 500 High Beta ETF","asset_class":"equity","exchange":"SMART","sector":"high_beta","tick_size":0.01,"session_id":"nyse","point_value":1.0,"provider_meta":{}}', true)
ON CONFLICT (symbol) DO NOTHING;

COMMIT;
```

- [ ] **Step 2: Apply the migration**

```bash
PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent \
    -f production/migrations/188_etf_expansion.sql
```

Expected: no errors. `INSERT 9` (tag_vocabulary), `INSERT 7` (instrument_tags re-tags), `INSERT 14` (instruments).

- [ ] **Step 3: Verify**

```bash
PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -c "
SELECT COUNT(*) as total_instruments FROM instruments WHERE is_active = true AND contract_details->>'asset_class' = 'equity';
SELECT COUNT(*) as new_tags FROM tag_vocabulary WHERE tag LIKE 'commodity_%' OR tag LIKE 'fx_%';
SELECT symbol, tag FROM instrument_tags WHERE tag LIKE 'commodity_%_crude' OR tag LIKE 'commodity_%_precious' OR tag LIKE 'commodity_%_pipeline' ORDER BY tag, symbol;
"
```

Expected: 74 total instruments, 11+ new tags, 7 re-tagged existing instruments.

- [ ] **Step 4: Tag new instruments**

```bash
PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -c "
INSERT INTO instrument_tags (symbol, tag, weight, source, evidence) VALUES
    -- DBC
    ('DBC', 'commodity_broad',        1.0, 'human', '{\"reason\": \"GSCI-weighted broad commodity index\"}'),
    ('DBC', 'benchmark',              1.0, 'human', '{\"reason\": \"benchmark broad commodity ETF\"}'),
    ('DBC', 'inflation',              0.9, 'human', '{\"reason\": \"broad commodity basket is inflation proxy\"}'),
    ('DBC', 'late_cycle',             0.8, 'human', '{\"reason\": \"commodities outperform late expansion\"}'),
    ('DBC', 'regime_classifier',      0.8, 'human', '{\"reason\": \"commodity regime signal\"}'),
    -- DBA
    ('DBA', 'commodity_agri',         1.0, 'human', '{\"reason\": \"corn, wheat, soybeans, sugar basket\"}'),
    ('DBA', 'benchmark',              1.0, 'human', '{\"reason\": \"benchmark agriculture ETF\"}'),
    ('DBA', 'inflation',              0.7, 'human', '{\"reason\": \"food prices are inflation component\"}'),
    ('DBA', 'dollar_strength',        0.7, 'human', '{\"reason\": \"USD inverse — dollar drives agri exports\"}'),
    -- DBB
    ('DBB', 'commodity_metals_industrial', 1.0, 'human', '{\"reason\": \"aluminum, copper, zinc — industrial demand\"}'),
    ('DBB', 'benchmark',              1.0, 'human', '{\"reason\": \"benchmark base metals ETF\"}'),
    ('DBB', 'china_demand',           0.9, 'human', '{\"reason\": \"industrial metals driven by China manufacturing\"}'),
    ('DBB', 'leading_indicator',      0.8, 'human', '{\"reason\": \"copper/base metals lead global PMI\"}'),
    ('DBB', 'early_cycle',            0.7, 'human', '{\"reason\": \"industrial metals recover early in expansion\"}'),
    -- PPLT
    ('PPLT','commodity_metals_precious', 0.9, 'human', '{\"reason\": \"platinum — precious metal with industrial auto-catalyst demand\"}'),
    ('PPLT','commodity_metals_industrial', 0.6, 'human', '{\"reason\": \"40% auto-catalyst industrial demand\"}'),
    ('PPLT','benchmark',              1.0, 'human', '{\"reason\": \"benchmark platinum ETF\"}'),
    ('PPLT','inflation',              0.7, 'human', '{\"reason\": \"precious metal inflation hedge\"}'),
    -- EZU
    ('EZU', 'intl_developed',         1.0, 'human', '{\"reason\": \"eurozone developed market equities\"}'),
    ('EZU', 'benchmark',              1.0, 'human', '{\"reason\": \"benchmark eurozone ETF\"}'),
    ('EZU', 'dollar_strength',        0.9, 'human', '{\"reason\": \"EUR/USD sensitivity — weak dollar boosts EZU in USD terms\"}'),
    ('EZU', 'regime_classifier',      0.8, 'human', '{\"reason\": \"eurozone regime independent of US\"}'),
    ('EZU', 'spread_leg',             0.9, 'human', '{\"reason\": \"US vs Europe spread\"}'),
    -- EWG
    ('EWG', 'intl_developed',         1.0, 'human', '{\"reason\": \"Germany equities — industrial/export bellwether\"}'),
    ('EWG', 'benchmark',              1.0, 'human', '{\"reason\": \"benchmark Germany ETF\"}'),
    ('EWG', 'dollar_strength',        0.8, 'human', '{\"reason\": \"EUR/USD sensitivity\"}'),
    ('EWG', 'china_demand',           0.7, 'human', '{\"reason\": \"German exports sensitive to China industrial demand\"}'),
    ('EWG', 'leading_indicator',      0.7, 'human', '{\"reason\": \"German manufacturing leads European cycle\"}'),
    -- EWZ
    ('EWZ', 'intl_em',                1.0, 'human', '{\"reason\": \"Brazil EM equities\"}'),
    ('EWZ', 'benchmark',              1.0, 'human', '{\"reason\": \"benchmark Brazil ETF\"}'),
    ('EWZ', 'em_flows',               0.9, 'human', '{\"reason\": \"Brazil driven by EM capital flows\"}'),
    ('EWZ', 'commodity_broad',        0.7, 'human', '{\"reason\": \"Brazil equity index commodity-exporter dominated\"}'),
    ('EWZ', 'dollar_strength',        0.9, 'human', '{\"reason\": \"BRL/USD sensitive — strong dollar hurts EWZ\"}'),
    -- VWO
    ('VWO', 'intl_em',                1.0, 'human', '{\"reason\": \"Vanguard broad EM — most liquid EM ETF\"}'),
    ('VWO', 'benchmark',              1.0, 'human', '{\"reason\": \"benchmark broad EM ETF\"}'),
    ('VWO', 'em_flows',               1.0, 'human', '{\"reason\": \"primary EM flow vehicle\"}'),
    ('VWO', 'dollar_strength',        0.9, 'human', '{\"reason\": \"strong dollar = EM outflow\"}'),
    ('VWO', 'regime_classifier',      0.8, 'human', '{\"reason\": \"EM risk-on/off regime signal\"}'),
    -- FXI
    ('FXI', 'intl_em',                1.0, 'human', '{\"reason\": \"China H-share large-cap equities\"}'),
    ('FXI', 'benchmark',              1.0, 'human', '{\"reason\": \"benchmark China H-share ETF\"}'),
    ('FXI', 'china_demand',           1.0, 'human', '{\"reason\": \"direct China equity exposure\"}'),
    ('FXI', 'em_flows',               0.8, 'human', '{\"reason\": \"China is dominant EM flow destination\"}'),
    -- MCHI
    ('MCHI','intl_em',                1.0, 'human', '{\"reason\": \"MSCI China broad — includes A-shares\"}'),
    ('MCHI','benchmark',              1.0, 'human', '{\"reason\": \"MSCI China benchmark\"}'),
    ('MCHI','china_demand',           1.0, 'human', '{\"reason\": \"broad China market exposure\"}'),
    ('MCHI','spread_leg',             0.8, 'human', '{\"reason\": \"FXI vs MCHI spread (H-share vs MSCI divergence)\"}'),
    -- UUP
    ('UUP', 'fx_usd',                 1.0, 'human', '{\"reason\": \"dollar index — long USD vs EUR/JPY/GBP/CAD/SEK/CHF basket\"}'),
    ('UUP', 'benchmark',              1.0, 'human', '{\"reason\": \"benchmark USD index ETF\"}'),
    ('UUP', 'dollar_strength',        1.0, 'human', '{\"reason\": \"IS the dollar strength signal\"}'),
    ('UUP', 'regime_classifier',      0.9, 'human', '{\"reason\": \"dollar regime drives cross-asset flows\"}'),
    ('UUP', 'risk_off',               0.7, 'human', '{\"reason\": \"dollar tends to strengthen in risk-off\"}'),
    -- FXE
    ('FXE', 'fx_major',               1.0, 'human', '{\"reason\": \"EUR/USD — largest FX pair\"}'),
    ('FXE', 'benchmark',              1.0, 'human', '{\"reason\": \"benchmark euro ETF\"}'),
    ('FXE', 'dollar_strength',        0.9, 'human', '{\"reason\": \"primary EUR/USD exposure — inverse UUP\"}'),
    ('FXE', 'spread_leg',             1.0, 'human', '{\"reason\": \"UUP/FXE spread\"}'),
    -- FXY
    ('FXY', 'fx_major',               1.0, 'human', '{\"reason\": \"JPY/USD — yen carry trade vehicle\"}'),
    ('FXY', 'benchmark',              1.0, 'human', '{\"reason\": \"benchmark yen ETF\"}'),
    ('FXY', 'yen_carry',              1.0, 'human', '{\"reason\": \"yen strengthens when carry unwinds\"}'),
    ('FXY', 'risk_off',               0.8, 'human', '{\"reason\": \"JPY is safe haven — strengthens in risk-off\"}'),
    ('FXY', 'spread_leg',             0.9, 'human', '{\"reason\": \"FXE/FXY cross\"}'),
    -- EDV
    ('EDV', 'fi_treasury',            1.0, 'human', '{\"reason\": \"25yr+ zero-coupon Treasuries\"}'),
    ('EDV', 'benchmark',              1.0, 'human', '{\"reason\": \"benchmark ultra-long duration ETF\"}'),
    ('EDV', 'rate_sensitive',         1.0, 'human', '{\"reason\": \"highest duration in universe — most rate-sensitive\"}'),
    ('EDV', 'fed_policy',             0.9, 'human', '{\"reason\": \"ultra-long end driven by long-run Fed expectations\"}'),
    ('EDV', 'recession',              0.9, 'human', '{\"reason\": \"flight to ultra-long quality in recession\"}'),
    ('EDV', 'spread_leg',             1.0, 'human', '{\"reason\": \"TLT/EDV duration spread\"}'),
    ('EDV', 'yield_curve',            0.9, 'human', '{\"reason\": \"captures long-end yield curve moves\"}'),
    -- IYT
    ('IYT', 'transports',             1.0, 'human', '{\"reason\": \"rails, trucking, air freight, marine — Dow Transports composition\"}'),
    ('IYT', 'benchmark',              1.0, 'human', '{\"reason\": \"benchmark transportation sector ETF\"}'),
    ('IYT', 'leading_indicator',      0.9, 'human', '{\"reason\": \"freight volumes lead broad economic cycle turns\"}'),
    ('IYT', 'early_cycle',            0.7, 'human', '{\"reason\": \"transports recover early in expansion\"}'),
    ('IYT', 'recession',              0.7, 'human', '{\"reason\": \"freight demand rolls over ahead of recession\"}'),
    -- FXA
    ('FXA', 'fx_commodity',           1.0, 'human', '{\"reason\": \"AUD/USD — commodity-currency proxy\"}'),
    ('FXA', 'benchmark',              1.0, 'human', '{\"reason\": \"benchmark AUD ETF\"}'),
    ('FXA', 'china_demand',           0.9, 'human', '{\"reason\": \"AUD tightly correlated to China industrial demand\"}'),
    ('FXA', 'commodity_broad',        0.8, 'human', '{\"reason\": \"AUD tracks metals/agri terms-of-trade\"}'),
    ('FXA', 'spread_leg',             0.8, 'human', '{\"reason\": \"FXA/FXY risk-on vs risk-off currency cross\"}'),
    -- VYM
    ('VYM', 'defensive_yield',        1.0, 'human', '{\"reason\": \"broad market screened purely on trailing dividend yield\"}'),
    ('VYM', 'benchmark',              1.0, 'human', '{\"reason\": \"benchmark high-dividend-yield ETF\"}'),
    ('VYM', 'risk_off',               0.7, 'human', '{\"reason\": \"high-yield equities rotate into favor in risk-off/late-cycle\"}'),
    ('VYM', 'spread_leg',             0.8, 'human', '{\"reason\": \"VYM/SCHD raw-yield vs quality-dividend spread\"}'),
    -- SDOG
    ('SDOG', 'defensive_yield',       1.0, 'human', '{\"reason\": \"literal Dogs-of-the-Dow methodology — top 5 yielders per GICS sector\"}'),
    ('SDOG', 'benchmark',             1.0, 'human', '{\"reason\": \"benchmark sector-diversified high-yield ETF\"}'),
    ('SDOG', 'risk_off',              0.7, 'human', '{\"reason\": \"contrarian/mean-reversion yield rotation, defensive tilt\"}'),
    ('SDOG', 'spread_leg',            0.7, 'human', '{\"reason\": \"VYM/SDOG broad vs sector-equal-weight yield spread\"}'),
    -- BTAL
    ('BTAL', 'factor_market_neutral', 1.0, 'human', '{\"reason\": \"long low-beta / short high-beta, dollar-neutral construction\"}'),
    ('BTAL', 'benchmark',             1.0, 'human', '{\"reason\": \"benchmark anti-beta long-short ETF\"}'),
    ('BTAL', 'risk_off',              0.8, 'human', '{\"reason\": \"low-beta outperforms high-beta in risk-off — BTAL rises\"}'),
    ('BTAL', 'regime_classifier',     0.8, 'human', '{\"reason\": \"near-zero net beta isolates factor rotation independent of market direction\"}'),
    -- IPO
    ('IPO', 'high_beta',              1.0, 'human', '{\"reason\": \"recent-listing factor — structurally higher volatility, no leverage/decay\"}'),
    ('IPO', 'benchmark',              1.0, 'human', '{\"reason\": \"benchmark recent-IPO ETF\"}'),
    ('IPO', 'risk_off',               0.8, 'human', '{\"reason\": \"speculative/high-beta names sell off hardest in risk-off\"}'),
    ('IPO', 'spread_leg',             0.7, 'human', '{\"reason\": \"IPO/SPY high-beta vs broad market spread\"}'),
    -- SPHB
    ('SPHB', 'high_beta',             1.0, 'human', '{\"reason\": \"top-100 highest-beta S&P 500 constituents\"}'),
    ('SPHB', 'benchmark',             1.0, 'human', '{\"reason\": \"benchmark high-beta S&P 500 ETF\"}'),
    ('SPHB', 'risk_off',              0.8, 'human', '{\"reason\": \"high-beta names amplify drawdowns in risk-off\"}'),
    ('SPHB', 'spread_leg',            0.8, 'human', '{\"reason\": \"SPHB/USMV high-beta vs low-vol factor spread\"}')
ON CONFLICT (symbol, tag) DO NOTHING;
"
```

- [ ] **Step 5: Verify tag coverage**

```bash
PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -c "
SELECT i.symbol,
       COUNT(it.tag) as tag_count,
       array_agg(it.tag ORDER BY it.tag) as tags
FROM instruments i
LEFT JOIN instrument_tags it ON i.symbol = it.symbol
WHERE i.symbol IN ('DBC','DBA','DBB','PPLT','EZU','EWG','EWZ','VWO','FXI','MCHI','UUP','FXE','FXY','EDV','IYT','FXA','VYM','SDOG','BTAL','IPO','SPHB')
GROUP BY i.symbol
ORDER BY i.symbol;
"
```

Expected: all 21 symbols present, each with 3-7 tags, no nulls.

- [ ] **Step 6: Verify regime group routing**

```bash
PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -c "
-- Verify commodity_energy group will resolve correctly
SELECT symbol FROM instrument_tags
WHERE tag IN ('commodity_energy_crude','commodity_energy_pipeline')
ORDER BY symbol;
-- Expected: AMLP, OIH, XLE, XOP + new symbols

-- Verify commodity_metals group
SELECT symbol FROM instrument_tags
WHERE tag IN ('commodity_metals_precious','commodity_metals_industrial')
ORDER BY symbol;
-- Expected: DBB, GDX, GLD, PPLT, SLV

-- Verify fx group
SELECT symbol FROM instrument_tags WHERE tag LIKE 'fx_%' ORDER BY symbol;
-- Expected: FXA, FXE, FXY, UUP

-- Verify defensive_yield group
SELECT symbol FROM instrument_tags WHERE tag = 'defensive_yield' ORDER BY symbol;
-- Expected: SDOG, VYM

-- Verify factor_market_neutral group
SELECT symbol FROM instrument_tags WHERE tag = 'factor_market_neutral' ORDER BY symbol;
-- Expected: BTAL

-- Verify high_beta group
SELECT symbol FROM instrument_tags WHERE tag = 'high_beta' ORDER BY symbol;
-- Expected: IPO, SPHB

-- Verify transports tag
SELECT symbol FROM instrument_tags WHERE tag = 'transports' ORDER BY symbol;
-- Expected: IYT
"
```

- [ ] **Step 7: Commit**

```bash
git add production/migrations/188_etf_expansion.sql
git commit -m "feat(migrations): ETF universe expansion 58→79 — new tags, re-tag existing, register 21 instruments (migration 188)"
```

---

## Task 1: Historical OHLCV Backfill

**Prerequisite:** Task 0 complete (instruments registered). TWS must be running.

**Files:**
- Create: `scripts/infrastructure/backfill/infrastructure_backfill_new_etfs.sh`

All 21 new instruments need full OHLCV history across 4 timeframes. IBKR practical limits:
- `1d`: up to 20yr (7300 days) for most ETFs
- `1h`: up to ~15yr (5500 days)
- `5m`: up to ~5yr (1825 days)
- `15m`: up to ~7yr (2555 days)

- [ ] **Step 1: Write the backfill script**

```bash
#!/usr/bin/env bash
# scripts/infrastructure/backfill/infrastructure_backfill_new_etfs.sh
# Backfill OHLCV for the 21 new ETFs added in migration 188.
# Re-run safe: ON CONFLICT DO NOTHING in bar writer.
# Usage: bash scripts/infrastructure/backfill/infrastructure_backfill_new_etfs.sh

set -euo pipefail

SCRIPT="scripts/infrastructure/backfill/infrastructure_run_historical_pipeline.py"
PYTHON=".venv/bin/python"
CLIENT_ID=41
LOG_DIR="logs/backfill_new_etfs"
mkdir -p "$LOG_DIR"

# 1d: days back to cover full inception history
declare -A DAYS_1D=(
    [DBC]=7300   [DBA]=7000
    [DBB]=7000   [PPLT]=5500
    [EZU]=7300   [EWG]=7300   [EWZ]=7300   [VWO]=7700
    [FXI]=8000   [MCHI]=5500
    [UUP]=7000   [FXE]=7700   [FXY]=7000
    [EDV]=6800
    [IYT]=7300   [FXA]=7300
    [VYM]=7300   [SDOG]=5200
    [BTAL]=5100
    [IPO]=4500   [SPHB]=5100
)

# 1h: IBKR practical limit ~15yr for these ETFs
DAYS_1H=5500

# 15m: ~7yr
DAYS_15M=2555

# 5m: ~5yr (IBKR hard limit)
DAYS_5M=1825

NEW_SYMBOLS=(DBC DBA DBB PPLT EZU EWG EWZ VWO FXI MCHI UUP FXE FXY EDV IYT FXA VYM SDOG BTAL IPO SPHB)

total_stored=0
errors=()

run_backfill() {
    local symbol=$1
    local tf=$2
    local days=$3
    local logfile="$LOG_DIR/${symbol}_${tf}_$(date +%Y%m%d_%H%M%S).log"

    echo "  -> $symbol/$tf ($days days)..."
    PYTHONUNBUFFERED=1 "$PYTHON" "$SCRIPT" \
        --fetch-only \
        --symbols "$symbol" \
        --timeframes "$tf" \
        --client-id "$CLIENT_ID" \
        --days "$days" \
        > "$logfile" 2>&1

    local stored
    stored=$(grep -oP "stored \K[0-9,]+" "$logfile" | tr -d ',' | tail -1 || echo 0)

    if grep -q "fetch error\|Error\|Traceback" "$logfile"; then
        echo "     ERROR — see $logfile"
        errors+=("$symbol/$tf")
    else
        echo "     OK: $stored bars"
        total_stored=$((total_stored + stored))
    fi
}

echo "======================================================="
echo " New ETF Backfill — 21 symbols × 4 timeframes"
echo " $(date)"
echo "======================================================="

for sym in "${NEW_SYMBOLS[@]}"; do
    echo
    echo "=== $sym ==="
    run_backfill "$sym" "1d"  "${DAYS_1D[$sym]}"
    run_backfill "$sym" "1h"  "$DAYS_1H"
    run_backfill "$sym" "15m" "$DAYS_15M"
    run_backfill "$sym" "5m"  "$DAYS_5M"
done

echo
echo "======================================================="
echo " Done: $total_stored total bars stored"
if [ ${#errors[@]} -gt 0 ]; then
    echo " Errors: ${errors[*]}"
    exit 1
fi
echo " $(date)"
echo "======================================================="
```

- [ ] **Step 2: Commit the script**

```bash
git add scripts/infrastructure/backfill/infrastructure_backfill_new_etfs.sh
chmod +x scripts/infrastructure/backfill/infrastructure_backfill_new_etfs.sh
git commit -m "feat(scripts): add backfill_new_etfs.sh for 21 new ETF universe expansion symbols"
```

- [ ] **Step 3: Run backfill (TWS must be running)**

```bash
bash scripts/infrastructure/backfill/infrastructure_backfill_new_etfs.sh
```

**Expected duration:** ~65-125 minutes (21 symbols × 4 TFs, sequential, rate-limited by IBKR pacing).

- [ ] **Step 4: Verify bar coverage**

```bash
PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -c "
SELECT symbol, timeframe,
       COUNT(*) as bars,
       MIN(timestamp)::date as earliest,
       MAX(timestamp)::date as latest
FROM market_data_ohlcv
WHERE symbol IN ('DBC','DBA','DBB','PPLT','EZU','EWG','EWZ','VWO','FXI','MCHI','UUP','FXE','FXY','EDV','IYT','FXA','VYM','SDOG','BTAL','IPO','SPHB')
GROUP BY symbol, timeframe
ORDER BY symbol, timeframe;
"
```

Expected: each symbol has bars in all 4 timeframes. `5m` earliest should be ~2021. `1d` earliest should reflect IPO date column from the instruments table.

---

## Task 2: Corpus Pipeline — New Symbols

**Prerequisite:** Task 1 complete (OHLCV bars present for all 21 symbols).

**Files:**
- Create: `scripts/ops/corpus/ops_corpus_new_etfs.sh`

Run all 6 corpus pipeline steps scoped to the 21 new symbols only. Uses `--symbols` flag and `--compute-only` where applicable to avoid re-fetching existing data.

- [ ] **Step 1: Seed backfill_status for new symbols**

Per the backfill_status gotcha: `--compute-only` silently skips if backfill_status is missing. Seed from market_data_ohlcv:

```bash
PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -c "
INSERT INTO backfill_status (symbol, timeframe, status, fetch_complete)
SELECT DISTINCT symbol, timeframe, 'pending', true
FROM market_data_ohlcv
WHERE symbol IN ('DBC','DBA','DBB','PPLT','EZU','EWG','EWZ','VWO','FXI','MCHI','UUP','FXE','FXY','EDV','IYT','FXA','VYM','SDOG','BTAL','IPO','SPHB')
ON CONFLICT (symbol, timeframe) DO NOTHING;
"
```

- [ ] **Step 2: Write corpus script**

```bash
#!/usr/bin/env bash
# scripts/ops/corpus/ops_corpus_new_etfs.sh
# Run corpus pipeline steps 1-6 for the 21 new ETF symbols.
# Assumes OHLCV bars are already present (Task 1 complete).
# Usage: bash scripts/ops/corpus/ops_corpus_new_etfs.sh [--from-step N]

set -euo pipefail

PYTHON=".venv/bin/python"
SYMBOLS="DBC DBA DBB PPLT EZU EWG EWZ VWO FXI MCHI UUP FXE FXY EDV IYT FXA VYM SDOG BTAL IPO SPHB"
FROM_STEP=${2:-1}

echo "======================================================="
echo " Corpus Pipeline — 21 new ETF symbols"
echo " From step: $FROM_STEP"
echo " $(date)"
echo "======================================================="

bash scripts/ops/corpus/ops_corpus_pipeline_run.sh \
    --symbols $SYMBOLS \
    --from-step "$FROM_STEP" \
    --compute-only

echo "======================================================="
echo " Done: $(date)"
echo "======================================================="
```

- [ ] **Step 3: Commit the script**

```bash
git add scripts/ops/corpus/ops_corpus_new_etfs.sh
chmod +x scripts/ops/corpus/ops_corpus_new_etfs.sh
git commit -m "feat(scripts): add corpus_new_etfs.sh for 14-symbol corpus pipeline run"
```

- [ ] **Step 4: Run corpus pipeline**

```bash
bash scripts/ops/corpus/ops_corpus_new_etfs.sh
```

**Expected duration:** 2-4 hours (16 symbols through feature_factory, regime_writer, forward_return_writer, ic_engine, ensemble_trainer, alpha_publisher).

- [ ] **Step 5: Verify corpus output**

```bash
PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -c "
SELECT
    (SELECT COUNT(DISTINCT symbol) FROM feature_vectors
     WHERE symbol IN ('DBC','DBA','DBB','PPLT','EZU','EWG','EWZ','VWO','FXI','MCHI','UUP','FXE','FXY','EDV','IYT','FXA','VYM','SDOG','BTAL','IPO','SPHB'))
     AS fv_symbols,
    (SELECT COUNT(*) FROM feature_ic_scores
     WHERE symbol IN ('DBC','DBA','DBB','PPLT','EZU','EWG','EWZ','VWO','FXI','MCHI','UUP','FXE','FXY','EDV','IYT','FXA','VYM','SDOG','BTAL','IPO','SPHB'))
     AS ic_score_rows,
    (SELECT COUNT(*) FROM alpha_events
     WHERE symbol IN ('DBC','DBA','DBB','PPLT','EZU','EWG','EWZ','VWO','FXI','MCHI','UUP','FXE','FXY','EDV','IYT','FXA','VYM','SDOG','BTAL','IPO','SPHB'))
     AS alpha_events;
"
```

Expected: 21 fv_symbols, >0 ic_score_rows, >0 alpha_events.

---

## Task 3: Enable Commodity and FX Regime Groups

**Prerequisite:** Tasks 0-2 complete. commodity_momentum_ts and fx_dollar_carry signal modules implemented (cross-sectional regime model plan Tasks 6-7).

Enable the commodity and FX groups by updating `alpha.regime.groups` in APR:

- [ ] **Step 1: Enable groups via APR update**

```bash
PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -c "
UPDATE config_state
SET config_value = (
    SELECT jsonb_agg(
        CASE
            WHEN grp->>'name' IN ('commodity_energy','commodity_metals','commodity_agri','fx')
            THEN grp || '{\"enabled\": true}'::jsonb
            ELSE grp
        END
    )::text
    FROM jsonb_array_elements(config_value::jsonb) grp
),
version = version + 1,
updated_at = now()
WHERE config_key = 'alpha.regime.groups';
"
```

- [ ] **Step 2: Verify all groups enabled**

```bash
PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -c "
SELECT jsonb_array_elements(config_value::jsonb)->>'name' as group_name,
       jsonb_array_elements(config_value::jsonb)->>'enabled' as enabled
FROM config_state WHERE config_key = 'alpha.regime.groups';
"
```

Expected: all 6 groups show `enabled: true`.

- [ ] **Step 3: Run cross_sectional_regime_model for new groups**

```bash
.venv/bin/python services/cross_sectional_regime_model.py --tf 5m 15m 1h 1d
```

Expected: `market_regimes` populated for commodity_energy, commodity_metals, commodity_agri, fx groups.

- [ ] **Step 4: Verify regime label distribution**

```bash
PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -c "
SELECT regime_group, tf, regime_label, COUNT(*),
       ROUND(100.0 * COUNT(*) / SUM(COUNT(*)) OVER (PARTITION BY regime_group, tf), 1) AS pct
FROM market_regimes
WHERE regime_group NOT IN ('equity', 'rates')
GROUP BY 1, 2, 3
ORDER BY 1, 2, 3;
"
```

Pass criteria: no label exceeds 60% for any (group, tf). All 4 commodity/FX groups have rows for all 4 timeframes.

- [ ] **Step 5: Commit**

```bash
git commit -m "feat(etf-expansion): enable commodity and FX regime groups in APR"
```

---

## Verification

Full universe check after all tasks complete:

```bash
PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -c "
-- Universe size
SELECT COUNT(*) as total FROM instruments
WHERE is_active = true AND contract_details->>'asset_class' = 'equity';

-- Regime group membership
SELECT regime_group_tag, COUNT(*) as symbols FROM (
    SELECT DISTINCT symbol,
        CASE
            WHEN tag LIKE 'fx_%' THEN 'fx'
            WHEN tag LIKE 'fi_%' THEN 'rates'
            WHEN tag LIKE 'commodity_%' THEN 'commodity'
            WHEN tag LIKE 'eq_%' OR tag LIKE 'intl_%' THEN 'equity'
        END as regime_group_tag
    FROM instrument_tags
    WHERE tag LIKE 'fx_%' OR tag LIKE 'fi_%' OR tag LIKE 'commodity_%'
       OR tag LIKE 'eq_%' OR tag LIKE 'intl_%'
) t WHERE regime_group_tag IS NOT NULL
GROUP BY regime_group_tag ORDER BY regime_group_tag;

-- market_regimes coverage
SELECT regime_group, tf, COUNT(DISTINCT regime_label) as label_count, COUNT(*) as rows
FROM market_regimes GROUP BY 1, 2 ORDER BY 1, 2;
"
```

Pass criteria:
- 79 total active equity instruments
- Commodity group: 10+ symbols (existing energy/metals + new ETFs)
- Transports group: 1 symbol (IYT)
- Defensive-yield group: 3 symbols (SCHD existing + VYM, SDOG)
- Factor-market-neutral group: 1 symbol (BTAL)
- High-beta group: 2 symbols (IPO, SPHB)
- FX group: 4 symbols (UUP, FXE, FXY, FXA)
- Rates group: 11+ symbols (existing + EDV)
- All 6 regime groups producing labels across all 4 timeframes
