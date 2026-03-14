# Equity Expansion Phase B: Full ETF Rollout (33 ETFs)

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add the remaining 33 ETFs to settings.py, bringing the total to 60 instruments (22 + 38). Phase A pilot (5 ETFs) must be validated before starting Phase B.

**Prerequisite:** Phase A complete and pilot validated — run `validate_equity_backfill.py --symbol SPY --symbol XLF --symbol TLT --symbol GLD --symbol SMH` and confirm exit code 0 before proceeding.

**Architecture:** Pure config expansion — no infrastructure changes. All guards, session handling, and provider abstraction were built in Phase A. ETF bars flow through the existing pipeline unchanged.

**Spec:** `docs/superpowers/specs/2026-03-13-equity-expansion-renaissance.md`

**Tech Stack:** Python 3.11, pydantic v2, pytest

---

## Chunk 1: ETF Universe Expansion

### Task 1: Add 33 remaining ETFs to settings.py

**Files:**
- Modify: `src/config/settings.py`
- Modify: `tests/unit/config/test_settings_equity.py` (update count assertions)

**ETFs to add (33):**

| Category | Symbols |
|---|---|
| Broad market | QQQ, IWM, DIA |
| Sectors | XLK, XLE, XLC, XLY, XLV, XLI, XLU, XLRE, XLP, XLB |
| Industry/thematic | IBB, GDX, GDXJ, XOP, ITB |
| Credit/rates | HYG, LQD, IEF, SHY, EMB |
| Factor | MTUM, QUAL, VLUE, USMV |
| International | EFA, EEM, EWZ, FXI |
| Macro/commodity | SLV, USO |

All: `asset_class=AssetClass.EQUITY`, `session_id="nyse"`, `exchange="SMART"`, `point_value=1.0`, `tick_size=0.01`, `expiry=""`.

- [ ] **Step 1: Write failing tests**

```python
# Append to or update tests/unit/config/test_settings_equity.py


class TestFullETFRollout:
    BROAD_MARKET = {"QQQ", "IWM", "DIA"}
    SECTORS = {"XLK", "XLE", "XLC", "XLY", "XLV", "XLI", "XLU", "XLRE", "XLP", "XLB"}
    INDUSTRY = {"IBB", "GDX", "GDXJ", "XOP", "ITB"}
    CREDIT = {"HYG", "LQD", "IEF", "SHY", "EMB"}
    FACTOR = {"MTUM", "QUAL", "VLUE", "USMV"}
    INTERNATIONAL = {"EFA", "EEM", "EWZ", "FXI"}
    COMMODITY = {"SLV", "USO"}

    ALL_NEW_ETFS = (
        BROAD_MARKET | SECTORS | INDUSTRY | CREDIT | FACTOR | INTERNATIONAL | COMMODITY
    )

    def test_all_33_etfs_present(self):
        from src.config.settings import Settings
        symbols = {inst.symbol for inst in Settings().instruments}
        missing = self.ALL_NEW_ETFS - symbols
        assert not missing, f"Missing ETFs: {missing}"

    def test_all_etfs_are_equity_nyse(self):
        from src.config.settings import Settings
        from src.core.models import AssetClass
        for inst in Settings().instruments:
            if inst.symbol in self.ALL_NEW_ETFS:
                assert inst.asset_class == AssetClass.EQUITY
                assert inst.session_id == "nyse"
                assert inst.exchange == "SMART"

    def test_total_instrument_count_60(self):
        """22 futures/FX/crypto + 38 ETFs = 60 total."""
        from src.config.settings import Settings
        assert len(Settings().instruments) == 60

    def test_equity_count_38(self):
        from src.config.settings import Settings
        from src.core.models import AssetClass
        equities = [i for i in Settings().instruments if i.asset_class == AssetClass.EQUITY]
        assert len(equities) == 38

    def test_pilot_etfs_still_present(self):
        from src.config.settings import Settings
        symbols = {inst.symbol for inst in Settings().instruments}
        for sym in ["SPY", "XLF", "TLT", "GLD", "SMH"]:
            assert sym in symbols, f"Pilot ETF {sym} should still be present"

    def test_no_duplicate_symbols(self):
        from src.config.settings import Settings
        symbols = [inst.symbol for inst in Settings().instruments]
        assert len(symbols) == len(set(symbols)), "Duplicate symbols in instruments list"

    def test_all_etfs_have_unit_point_value(self):
        from src.config.settings import Settings
        from src.core.models import AssetClass
        for inst in Settings().instruments:
            if inst.asset_class == AssetClass.EQUITY:
                assert inst.point_value == 1.0

    def test_all_etfs_have_standard_tick_size(self):
        from src.config.settings import Settings
        from src.core.models import AssetClass
        for inst in Settings().instruments:
            if inst.asset_class == AssetClass.EQUITY:
                assert inst.tick_size == 0.01

    def test_get_active_contracts_includes_all_etfs(self):
        from src.config.settings import get_active_contracts
        active = set(get_active_contracts())
        for sym in self.ALL_NEW_ETFS:
            assert sym in active, f"{sym} missing from get_active_contracts()"
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
.venv/bin/pytest tests/unit/config/test_settings_equity.py::TestFullETFRollout -v 2>&1 | head -30
```

Expected: Multiple failures — 33 ETF symbols missing.

- [ ] **Step 3: Add 33 ETFs to settings.py get_default_instruments()**

Append after the 5 pilot ETFs already added in Phase A. Keep the same `Instrument(...)` pattern:

**Broad market (3):**
```python
            Instrument(symbol="QQQ",  name="Invesco QQQ Trust", asset_class=AssetClass.EQUITY,
                       exchange="SMART", sector="broad_market", session_id="nyse",
                       point_value=1.0, tick_size=0.01),
            Instrument(symbol="IWM",  name="iShares Russell 2000 ETF", asset_class=AssetClass.EQUITY,
                       exchange="SMART", sector="broad_market", session_id="nyse",
                       point_value=1.0, tick_size=0.01),
            Instrument(symbol="DIA",  name="SPDR Dow Jones Industrial Average ETF",
                       asset_class=AssetClass.EQUITY, exchange="SMART", sector="broad_market",
                       session_id="nyse", point_value=1.0, tick_size=0.01),
```

**Sectors (10):**
```python
            Instrument(symbol="XLK",  name="Technology Select Sector SPDR", asset_class=AssetClass.EQUITY,
                       exchange="SMART", sector="technology", session_id="nyse", point_value=1.0, tick_size=0.01),
            Instrument(symbol="XLE",  name="Energy Select Sector SPDR", asset_class=AssetClass.EQUITY,
                       exchange="SMART", sector="energy", session_id="nyse", point_value=1.0, tick_size=0.01),
            Instrument(symbol="XLC",  name="Communication Services SPDR", asset_class=AssetClass.EQUITY,
                       exchange="SMART", sector="communications", session_id="nyse", point_value=1.0, tick_size=0.01),
            Instrument(symbol="XLY",  name="Consumer Discretionary SPDR", asset_class=AssetClass.EQUITY,
                       exchange="SMART", sector="consumer_discretionary", session_id="nyse", point_value=1.0, tick_size=0.01),
            Instrument(symbol="XLV",  name="Health Care Select Sector SPDR", asset_class=AssetClass.EQUITY,
                       exchange="SMART", sector="healthcare", session_id="nyse", point_value=1.0, tick_size=0.01),
            Instrument(symbol="XLI",  name="Industrial Select Sector SPDR", asset_class=AssetClass.EQUITY,
                       exchange="SMART", sector="industrials", session_id="nyse", point_value=1.0, tick_size=0.01),
            Instrument(symbol="XLU",  name="Utilities Select Sector SPDR", asset_class=AssetClass.EQUITY,
                       exchange="SMART", sector="utilities", session_id="nyse", point_value=1.0, tick_size=0.01),
            Instrument(symbol="XLRE", name="Real Estate Select Sector SPDR", asset_class=AssetClass.EQUITY,
                       exchange="SMART", sector="real_estate", session_id="nyse", point_value=1.0, tick_size=0.01),
            Instrument(symbol="XLP",  name="Consumer Staples Select Sector SPDR", asset_class=AssetClass.EQUITY,
                       exchange="SMART", sector="consumer_staples", session_id="nyse", point_value=1.0, tick_size=0.01),
            Instrument(symbol="XLB",  name="Materials Select Sector SPDR", asset_class=AssetClass.EQUITY,
                       exchange="SMART", sector="materials", session_id="nyse", point_value=1.0, tick_size=0.01),
```

**Industry/thematic (5):**
```python
            Instrument(symbol="IBB",  name="iShares Biotechnology ETF", asset_class=AssetClass.EQUITY,
                       exchange="SMART", sector="biotech", session_id="nyse", point_value=1.0, tick_size=0.01),
            Instrument(symbol="GDX",  name="VanEck Gold Miners ETF", asset_class=AssetClass.EQUITY,
                       exchange="SMART", sector="gold_miners", session_id="nyse", point_value=1.0, tick_size=0.01),
            Instrument(symbol="GDXJ", name="VanEck Junior Gold Miners ETF", asset_class=AssetClass.EQUITY,
                       exchange="SMART", sector="gold_miners", session_id="nyse", point_value=1.0, tick_size=0.01),
            Instrument(symbol="XOP",  name="SPDR Oil & Gas Exploration ETF", asset_class=AssetClass.EQUITY,
                       exchange="SMART", sector="energy", session_id="nyse", point_value=1.0, tick_size=0.01),
            Instrument(symbol="ITB",  name="iShares U.S. Home Construction ETF", asset_class=AssetClass.EQUITY,
                       exchange="SMART", sector="homebuilders", session_id="nyse", point_value=1.0, tick_size=0.01),
```

**Credit/rates (5):**
```python
            Instrument(symbol="HYG",  name="iShares iBoxx High Yield Corporate Bond ETF",
                       asset_class=AssetClass.EQUITY, exchange="SMART", sector="credit",
                       session_id="nyse", point_value=1.0, tick_size=0.01),
            Instrument(symbol="LQD",  name="iShares iBoxx Investment Grade Corporate Bond ETF",
                       asset_class=AssetClass.EQUITY, exchange="SMART", sector="credit",
                       session_id="nyse", point_value=1.0, tick_size=0.01),
            Instrument(symbol="IEF",  name="iShares 7-10 Year Treasury Bond ETF",
                       asset_class=AssetClass.EQUITY, exchange="SMART", sector="rates",
                       session_id="nyse", point_value=1.0, tick_size=0.01),
            Instrument(symbol="SHY",  name="iShares 1-3 Year Treasury Bond ETF",
                       asset_class=AssetClass.EQUITY, exchange="SMART", sector="rates",
                       session_id="nyse", point_value=1.0, tick_size=0.01),
            Instrument(symbol="EMB",  name="iShares J.P. Morgan USD Emerging Markets Bond ETF",
                       asset_class=AssetClass.EQUITY, exchange="SMART", sector="emerging_markets",
                       session_id="nyse", point_value=1.0, tick_size=0.01),
```

**Factor (4):**
```python
            Instrument(symbol="MTUM", name="iShares MSCI USA Momentum Factor ETF",
                       asset_class=AssetClass.EQUITY, exchange="SMART", sector="factor",
                       session_id="nyse", point_value=1.0, tick_size=0.01),
            Instrument(symbol="QUAL", name="iShares MSCI USA Quality Factor ETF",
                       asset_class=AssetClass.EQUITY, exchange="SMART", sector="factor",
                       session_id="nyse", point_value=1.0, tick_size=0.01),
            Instrument(symbol="VLUE", name="iShares MSCI USA Value Factor ETF",
                       asset_class=AssetClass.EQUITY, exchange="SMART", sector="factor",
                       session_id="nyse", point_value=1.0, tick_size=0.01),
            Instrument(symbol="USMV", name="iShares MSCI USA Min Vol Factor ETF",
                       asset_class=AssetClass.EQUITY, exchange="SMART", sector="factor",
                       session_id="nyse", point_value=1.0, tick_size=0.01),
```

**International (4):**
```python
            Instrument(symbol="EFA",  name="iShares MSCI EAFE ETF", asset_class=AssetClass.EQUITY,
                       exchange="SMART", sector="international", session_id="nyse", point_value=1.0, tick_size=0.01),
            Instrument(symbol="EEM",  name="iShares MSCI Emerging Markets ETF",
                       asset_class=AssetClass.EQUITY, exchange="SMART", sector="emerging_markets",
                       session_id="nyse", point_value=1.0, tick_size=0.01),
            Instrument(symbol="EWZ",  name="iShares MSCI Brazil ETF", asset_class=AssetClass.EQUITY,
                       exchange="SMART", sector="emerging_markets", session_id="nyse", point_value=1.0, tick_size=0.01),
            Instrument(symbol="FXI",  name="iShares China Large-Cap ETF", asset_class=AssetClass.EQUITY,
                       exchange="SMART", sector="emerging_markets", session_id="nyse", point_value=1.0, tick_size=0.01),
```

**Macro/commodity (2):**
```python
            Instrument(symbol="SLV",  name="iShares Silver Trust", asset_class=AssetClass.EQUITY,
                       exchange="SMART", sector="commodity", session_id="nyse", point_value=1.0, tick_size=0.01),
            Instrument(symbol="USO",  name="United States Oil Fund", asset_class=AssetClass.EQUITY,
                       exchange="SMART", sector="energy", session_id="nyse", point_value=1.0, tick_size=0.01),
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
.venv/bin/pytest tests/unit/config/test_settings_equity.py -v
```

Expected: All pass including `TestFullETFRollout`.

- [ ] **Step 5: Update Phase A count assertion**

In `TestPilotETFs.test_total_instruments_count`, change `== 27` to `== 60` (now Phase B is done, the count is 60 in the same settings file). Or delete that test if it conflicts. The canonical count test is `TestFullETFRollout.test_total_instrument_count_60`.

- [ ] **Step 6: Full unit regression**

```bash
.venv/bin/pytest tests/unit/ -x -q 2>&1 | tail -10
```

- [ ] **Step 7: Verify symbol count via python**

```bash
.venv/bin/python -c "
from src.config.settings import Settings
from src.core.models import AssetClass
s = Settings()
equities = [i for i in s.instruments if i.asset_class == AssetClass.EQUITY]
print(f'Total: {len(s.instruments)}, Equities: {len(equities)}, Non-equities: {len(s.instruments)-len(equities)}')
"
```

Expected: `Total: 60, Equities: 38, Non-equities: 22`

- [ ] **Step 8: Commit**

```bash
git add src/config/settings.py tests/unit/config/test_settings_equity.py
git commit -m "feat(config): add 33 remaining ETFs — 60 total instruments (22 + 38 ETFs)"
```

---

## Chunk 2: Documentation Update

### Task 2: Update CLAUDE.md files

**Files:**
- Modify: `src/providers/CLAUDE.md`
- Modify: `CLAUDE.md` (top-level)

- [ ] **Step 1: Update providers/CLAUDE.md**

- Change "Active Contracts (27)" (set in Phase A) to "Active Contracts (60)"
- Update the contract list to show all 60 (futures grouped, ETFs grouped by category)
- Remove any mentions of PLJ6, SOLUSD, PL (already done in Phase A)
- Note that IBKR subscription limit is 80 (default) — at 60 instruments we have 20 slots headroom

- [ ] **Step 2: Update CLAUDE.md status section**

Update the "Current Status" block:
- Tests count (will increase after Phase B tests run)
- Plugin/instrument count reference
- Note: "v1.9 NEXT: equity expansion Phase B complete — 60 instruments in pipeline"

- [ ] **Step 3: Commit**

```bash
git add src/providers/CLAUDE.md CLAUDE.md
git commit -m "docs: update instrument counts to 60 — Phase B ETF expansion complete"
```

---

## Final Phase B Verification

- [ ] **Full unit test suite**

```bash
.venv/bin/pytest tests/unit/ -q 2>&1 | tail -10
```

- [ ] **Lint check**

```bash
.venv/bin/ruff check . 2>&1 | grep -v "E501" | head -20
```

- [ ] **Instrument universe sanity check**

```bash
.venv/bin/python -c "
from src.config.settings import Settings, get_active_contracts
from src.core.models import AssetClass
s = Settings()
by_class = {}
for inst in s.instruments:
    by_class.setdefault(inst.asset_class.value, []).append(inst.symbol)
for cls, syms in sorted(by_class.items()):
    print(f'{cls}: {len(syms)} — {sorted(syms)[:5]}...')
print(f'Total active contracts: {len(get_active_contracts())}')
"
```

Expected: equity: 38, futures: 16, fx: 4, crypto: 2 = 60 total.

---

## Post-Phase B: Backfill & Pilot Validation (Manual Ops)

These steps require a live IBKR paper trading connection and are run manually, not in CI.

- [ ] **Backfill pilot 5 ETFs (Phase A validation)**

```bash
.venv/bin/python production/scripts/historical_backfill.py \
    --fetch-only --symbols SPY,XLF,TLT,GLD,SMH --days 14
.venv/bin/python production/scripts/historical_backfill.py \
    --replay-only --symbols SPY,XLF,TLT,GLD,SMH --days 14
```

- [ ] **Run validation script on pilot ETFs**

```bash
.venv/bin/python production/scripts/validate_equity_backfill.py \
    --symbol SPY --symbol XLF --symbol TLT --symbol GLD --symbol SMH
```

Expected exit code: 0. If non-zero: investigate `useRTH` propagation before proceeding to full backfill.

- [ ] **Backfill all 33 remaining ETFs**

Run in batches of ~10 to avoid overwhelming IBKR rate limits:

```bash
# Batch 1: Broad market + sectors
.venv/bin/python production/scripts/historical_backfill.py \
    --fetch-only --symbols QQQ,IWM,DIA,XLK,XLE,XLC,XLY,XLV,XLI,XLU --days 14
.venv/bin/python production/scripts/historical_backfill.py \
    --replay-only --symbols QQQ,IWM,DIA,XLK,XLE,XLC,XLY,XLV,XLI,XLU --days 14

# Batch 2: More sectors + industry
.venv/bin/python production/scripts/historical_backfill.py \
    --fetch-only --symbols XLRE,XLP,XLB,IBB,GDX,GDXJ,XOP,ITB --days 14
.venv/bin/python production/scripts/historical_backfill.py \
    --replay-only --symbols XLRE,XLP,XLB,IBB,GDX,GDXJ,XOP,ITB --days 14

# Batch 3: Credit/rates + factor
.venv/bin/python production/scripts/historical_backfill.py \
    --fetch-only --symbols HYG,LQD,IEF,SHY,EMB,MTUM,QUAL,VLUE,USMV --days 14
.venv/bin/python production/scripts/historical_backfill.py \
    --replay-only --symbols HYG,LQD,IEF,SHY,EMB,MTUM,QUAL,VLUE,USMV --days 14

# Batch 4: International + commodity
.venv/bin/python production/scripts/historical_backfill.py \
    --fetch-only --symbols EFA,EEM,EWZ,FXI,SLV,USO --days 14
.venv/bin/python production/scripts/historical_backfill.py \
    --replay-only --symbols EFA,EEM,EWZ,FXI,SLV,USO --days 14
```

- [ ] **Run validation on all 38 ETFs**

```bash
.venv/bin/python production/scripts/validate_equity_backfill.py \
    --symbol SPY --symbol QQQ --symbol IWM --symbol DIA \
    --symbol XLF --symbol XLK --symbol XLE --symbol XLC --symbol XLY \
    --symbol XLV --symbol XLI --symbol XLU --symbol XLRE --symbol XLP --symbol XLB \
    --symbol SMH --symbol IBB --symbol GDX --symbol GDXJ --symbol XOP --symbol ITB \
    --symbol HYG --symbol LQD --symbol TLT --symbol IEF --symbol SHY --symbol EMB \
    --symbol MTUM --symbol QUAL --symbol VLUE --symbol USMV \
    --symbol EFA --symbol EEM --symbol EWZ --symbol FXI \
    --symbol GLD --symbol SLV --symbol USO
```

Expected: All lines show "OK: SYMBOL — 0 off-hours rows". Exit code 0.

- [ ] **Restart live services to pick up new instruments**

```bash
# User runs in terminal (sudo required):
sudo systemctl restart indicagent-tws indicagent-indicator indicagent-market-analysis indicagent-signal-generator
```

Monitor logs:
```bash
journalctl -u indicagent-indicator -f
```

Expected: logs show subscription confirmed for new ETF symbols.
