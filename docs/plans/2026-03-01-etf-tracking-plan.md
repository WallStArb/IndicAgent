# [ETF Tracking] Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add full ETF tracking support (indicators, patterns, signals, AI narratives) to IndicAgent, with configurable ETF qualification via IBKR.

**Architecture:** Add `AssetClass.ETF` to `Instrument` model, extend IBKR qualification to handle ETF instruments, wire existing dashboard ETF UI to real data streams.

**Tech Stack:** Python, TypeScript, IBKR ib_insync, Redis, Pydantic

---

## Context

**Current State:**
- Dashboard has ETF section configured (SPY, QQQ, IWM) with "ETF Trading" profile
- Backend supports: futures (contracts with expiry), FX, crypto (AssetClass)
- IBKR is the data provider for all instruments
- No ETF support exists in Settings or Instrument model
- 24 active contracts, all futures/FX/crypto

**Key Insight:** Dashboard ETF UI already exists - just needs backend to generate real intelligence data instead of placeholder configuration.

---

## Task Structure

### Task 1: Add ETF AssetClass to core models

**Files:**
- Create: `src/core/models.py` (modify existing AssetClass)
- Test: `tests/unit/core/test_models.py` (create if doesn't exist)

**Step 1: Write failing test**

```python
def test_etf_asset_class_exists():
    from src.core.models import AssetClass
    assert hasattr(AssetClass, 'ETF')
    assert AssetClass.ETF == 'etf'
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/unit/core/test_models.py::test_etf_asset_class_exists -v`
Expected: FAIL with "ETF" not found

**Step 3: Add ETF to AssetClass**

Modify `src/core/models.py` - add `ETF = "etf"` to AssetClass enum

**Step 4: Run test to verify it passes**

Run: `pytest tests/unit/core/test_models.py::test_etf_asset_class_exists -v`
Expected: PASS

**Step 5: Commit**

```bash
git add src/core/models.py tests/unit/core/test_models.py
git commit -m "feat(core): add ETF asset class to models"
```

---

### Task 2: Add ETF Instruments to Settings defaults

**Files:**
- Create: `src/config/settings.py` (add ETFs to default contracts)
- Test: `tests/unit/config/test_settings.py` (create if doesn't exist)

**Step 1: Write failing test**

```python
def test_etf_in_defaults():
    from src.config.settings import Settings, get_active_contracts
    s = Settings()
    contracts = s.contracts
    etf_symbols = [c.symbol for c in contracts if c.asset_class.name == 'ETF']
    assert 'SPY' in etf_symbols
    assert 'QQQ' in etf_symbols
    assert 'IWM' in etf_symbols
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/unit/config/test_settings.py::test_etf_in_defaults -v`
Expected: FAIL with no ETFs found

**Step 3: Add ETFs to Settings.build_contracts()**

Modify `src/config/settings.py` - add SPY, QQQ, IWM ETFs with `AssetClass.ETF`, no expiry

**Step 4: Run test to verify it passes**

Run: `pytest tests/unit/config/test_settings.py::test_etf_in_defaults -v`
Expected: PASS

**Step 5: Commit**

```bash
git add src/config/settings.py tests/unit/config/test_settings.py
git commit -m "feat(config): add ETF instruments to default contracts"
```

---

### Task 3: Extend IBKR qualification for ETFs

**Files:**
- Create: `src/providers/ibkr.py` (add ETF support to qualify_instrument)
- Test: `tests/unit/providers/test_ibkr.py` (create if doesn't exist)

**Step 1: Write failing test**

```python
def test_etf_qualification():
    from src.providers.ibkr import IBKRProvider, Instrument
    # ETFs should qualify via SMART or specific ETF exchange
    provider = IBKRProvider(...)
    etf = Instrument(symbol='SPY', exchange='SMART', asset_class=AssetClass.ETF, ...)
    result = provider.qualify_instrument(etf)
    assert result is not None
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/unit/providers/test_ibkr.py::test_etf_qualification -v`
Expected: FAIL with ETF not qualifying

**Step 3: Add ETF support to IBKRProvider.qualify_instrument()**

Modify `src/providers/ibkr.py` - handle ETF `AssetClass.ETF` case, set `exchange='SMART'` for ETFs

**Step 4: Run test to verify it passes**

Run: `pytest tests/unit/providers/test_ibkr.py::test_etf_qualification -v`
Expected: PASS

**Step 5: Commit**

```bash
git add src/providers/ibkr.py tests/unit/providers/test_ibkr.py
git commit -m "feat(ibkr): add ETF qualification support"
```

---

### Task 4: Update symbol-config.ts for ETF sector

**Files:**
- Create: `dashboard/src/lib/symbol-config.ts` (update loadConfig to fetch ETFs from API)
- Test: `dashboard/__tests__/symbol-config.test.ts` (create if doesn't exist)

**Step 1: Write failing test**

```typescript
describe('ETF configuration loaded from API', () => {
  it('includes ETFs from API response', async () => {
    // Mock fetch to return ETFs in instruments
    const mockFetch = jest.spyOn(global, 'fetch').mockResolvedValue({
      instruments: [
        { symbol: 'SPY', name: 'SPDR S&P 500', sector: 'etf', is_active: true, asset_class: 'ETF' },
        { symbol: 'QQQ', name: 'Invesco QQQ', sector: 'etf', is_active: true, asset_class: 'ETF' },
      ]
    });

    const config = symbolConfig;
    await config.loadConfig();

    const spyInfo = config.getSymbolInfo('SPY');
    expect(spyInfo?.sector).toBe('etf');
    expect(spyInfo?.contract).toBeUndefined(); // ETFs don't have contract codes

    const etfs = config.config.dashboard_symbols.etfs;
    expect(etfs.length).toBe(2); // Should include fetched ETFs
  });
});
```

**Step 2: Run test to verify it fails**

Run: `cd dashboard && npm test -- symbol-config.test.ts`
Expected: FAIL with static ETF config only

**Step 3: Update SymbolConfig.loadConfig() to fetch ETFs from API**

Modify `dashboard/src/lib/symbol-config.ts` - extend API response handling to include ETF instruments, update `etfs` array

**Step 4: Run test to verify it passes**

Run: `cd dashboard && npm test -- symbol-config.test.ts`
Expected: PASS

**Step 5: Commit**

```bash
git add dashboard/src/lib/symbol-config.ts dashboard/__tests__/symbol-config.test.ts
git commit -m "feat(dashboard): load ETFs from API response"
```

---

### Task 5: Add ETF support to all services

**Files:**
- Create: `services/indicator_service.py` (check if ETFs need special handling)
- Create: `services/market_analysis_service.py` (should work generically with Instruments)
- Test: `tests/unit/service_tests/test_market_analysis_service.py` (ETF-specific test)

**Step 1: Write failing test**

```python
def test_market_analysis_handles_etf():
    from src.config.settings import Settings, get_active_contracts
    from services.market_analysis_service import MarketAnalysisService

    s = Settings()
    etf_symbols = [c for c in s.contracts if c.asset_class.name == 'ETF']
    assert 'SPY' in etf_symbols

    # Service should include ETFs in its processing
    # ETFs should generate indicators like any other instrument
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/unit/service_tests/test_market_analysis_service.py::test_market_analysis_handles_etf -v`
Expected: FAIL with ETFs not in active symbols

**Step 3: Verify services handle ETFs generically**

Verify `indicator_service.py` and `market_analysis_service.py` use `get_active_contracts()` - should already include ETFs. No changes needed if architecture is generic.

**Step 4: Run test to verify it passes**

Run: `pytest tests/unit/service_tests/test_market_analysis_service.py::test_market_analysis_handles_etf -v`
Expected: PASS (no changes needed)

**Step 5: Commit**

```bash
git add tests/unit/service_tests/test_market_analysis_service.py
git commit -m "test(services): verify generic ETF handling"
```

---

### Task 6: Add ETF config to environment

**Files:**
- Create: `.env` (add ETF configuration flags)

**Step 1: Add ETF configuration to .env**

```bash
# Add to .env:
ETF_ENABLED=true
ETF_SYMBOLS=SPY,QQQ,IWM
```

**Step 2: Commit**

```bash
git add .env
git commit -m "feat(config): add ETF configuration flags"
```

---

### Task 7: Add ETF API endpoint

**Files:**
- Create: `src/api/routes/instruments.py` (verify ETFs are included in response)
- Test: `tests/unit/api/test_instruments_routes.py` (create if doesn't exist)

**Step 1: Write failing test**

```python
def test_instruments_endpoint_includes_etfs():
    import asyncio
    from src.api.main import app

    async def main():
        # Mock ETF in instruments
        # GET /api/instruments should return ETFs

    async with httpx.AsyncClient(app=app, base_url="http://test") as client:
            response = await client.get("/api/instruments")
            data = response.json()

            etf_count = sum(1 for i in data if i.get('asset_class') == 'ETF')
            assert etf_count > 0, "Response should include ETFs"
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/unit/api/test_instruments_routes.py::test_instruments_endpoint_includes_etfs -v`
Expected: FAIL with no ETFs in response

**Step 3: Verify /api/instruments returns ETFs**

Ensure `src/api/routes/instruments.py` returns all instruments including ETFs when `is_active=True`. No changes needed if generic.

**Step 4: Run test to verify it passes**

Run: `pytest tests/unit/api/test_instruments_routes.py::test_instruments_endpoint_includes_etfs -v`
Expected: PASS (no changes needed)

**Step 5: Commit**

```bash
git add tests/unit/api/test_instruments_routes.py
git commit -m "test(api): verify ETFs in instruments endpoint"
```

---

### Task 8: Update AI narrative service for ETF support

**Files:**
- Create: `services/ai_narrative_service.py` (verify ETF narratives work)
- Test: `tests/unit/service_tests/test_ai_narrative_service.py` (add ETF test)

**Step 1: Write failing test**

```python
def test_narrative_service_handles_etf():
    from services.ai_narrative_service import AINarrativeService, parse_aggregated_signal

    # ETF signal should be parseable
    etf_signal = {
        b'symbol': b'SPY',
        b'direction': b'1',
        b'confidence': b'0.85',
        b'setup_plugin': b'mean_reversion',
        # ... other required fields
    }

    parsed = parse_aggregated_signal(etf_signal)
    assert parsed is not None
    assert parsed['symbol'] == 'SPY'
    assert parsed['setup_plugin'] == 'mean_reversion'
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/unit/service_tests/test_ai_narrative_service.py::test_narrative_service_handles_etf -v`
Expected: FAIL with ETF not supported

**Step 3: Verify AI narrative service works with ETFs**

Ensure `ai_narrative_service.py` processes ETF signals correctly. ETFs have `symbol` but no `contract` - should work with current generic handling.

**Step 4: Run test to verify it passes**

Run: `pytest tests/unit/service_tests/test_ai_narrative_service.py::test_narrative_service_handles_etf -v`
Expected: PASS (no changes needed)

**Step 5: Commit**

```bash
git add tests/unit/service_tests/test_ai_narrative_service.py
git commit -m "test(ai-narrative): verify ETF signal handling"
```

---

### Task 9: Remove static ETF config from dashboard

**Files:**
- Create: `dashboard/src/lib/symbol-config.ts` (remove hardcoded ETF fallback)
- Test: Update `dashboard/__tests__/symbol-config.test.ts`

**Step 1: Write failing test**

```typescript
describe('ETF config uses API data, not static fallback', () => {
  it('removes hardcoded ETFs when API data loaded', async () => {
    const config = symbolConfig;
    await config.loadConfig();

    const spyInfo = config.getSymbolInfo('SPY');
    const etfList = config.config.dashboard_symbols.etfs;

    // After API load, ETFs should come from instruments response
    // Static fallback ETFs should be minimal or removed
    expect(etfList.length).toBeGreaterThan(0);
    expect(config.config.dashboard_symbols.etfs.length).toBeLessThan(10); // Not hardcoded
  });
});
```

**Step 2: Run test to verify it fails**

Run: `cd dashboard && npm test -- symbol-config.test.ts`
Expected: FAIL with hardcoded ETFs still present

**Step 3: Remove static ETF fallback config**

Modify `dashboard/src/lib/symbol-config.ts` - remove or minimize hardcoded `etfs` array since data now comes from API

**Step 4: Run test to verify it passes**

Run: `cd dashboard && npm test -- symbol-config.test.ts`
Expected: PASS

**Step 5: Commit**

```bash
git add dashboard/src/lib/symbol-config.ts dashboard/__tests__/symbol-config.test.ts
git commit -m "feat(dashboard): remove static ETF fallback, use API data"
```

---

### Task 10: Create ETF trading profile

**Files:**
- Create: `dashboard/src/lib/symbol-config.ts` (add ETF Trading profile)

**Step 1: Add ETF Trading profile**

Modify `dashboard/src/lib/symbol-config.ts` - add `etf_trading` profile with SPY, QQQ, IWM symbols

**Step 2: Commit**

```bash
git add dashboard/src/lib/symbol-config.ts
git commit -m "feat(dashboard): add ETF Trading profile"
```

---

### Task 11: Update documentation

**Files:**
- Create: `CLAUDE.md` (document ETF tracking support)
- Create: `docs/concepts/etf-tracking.md` (ETF tracking architecture doc)

**Step 1: Update CLAUDE.md**

Add ETF tracking notes to CLAUDE.md under "Current Status" and "Development Standards" sections.

**Step 2: Create ETF tracking architecture doc**

Create `docs/concepts/etf-tracking.md` documenting ETF architecture, data model, and integration points.

**Step 3: Commit**

```bash
git add CLAUDE.md docs/concepts/etf-tracking.md
git commit -m "docs: document ETF tracking support"
```

---

## Summary

This plan adds full ETF tracking support to IndicAgent in 11 bite-sized tasks:

1. **Core Models** - Add `AssetClass.ETF`
2. **Settings** - Add default ETF instruments (SPY, QQQ, IWM)
3. **IBKR Provider** - Extend qualification for ETFs (SMART exchange)
4. **Dashboard Config** - Load ETFs from API instead of static config
5. **Services** - Verify generic ETF handling (no changes needed)
6. **Environment** - Add ETF configuration flags
7. **API** - Verify ETFs included in instruments endpoint
8. **AI Narratives** - Verify ETF signal handling (no changes needed)
9. **Dashboard Cleanup** - Remove static ETF fallback
10. **Profiles** - Add ETF Trading profile
11. **Documentation** - Update CLAUDE.md and create ETF architecture doc

**Estimated Complexity:** Medium - involves model changes, IBKR qualification, and dashboard integration

**Testing Strategy:** TDD - failing test → implement → verify passing → commit
