# Plugin Tier Registry Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Eliminate duplicated plugin tier lists across service files and make bad plugin names crash at startup instead of silently skipping.

**Architecture:** Add `validate_tier()` to `PluginRegistry`; define canonical `TIER_*` constants in `register_plugins.py` using `plugin.name` attributes (not raw strings); services import these constants and validate at `__init__` time.

**Tech Stack:** Python, pytest, existing `PluginRegistry` in `src/intelligence/plugins.py`

---

## Task 1: Add `validate_tier()` to PluginRegistry

**Files:**
- Modify: `src/intelligence/plugins.py`
- Test: `tests/unit/intelligence/test_plugin_registry.py` (create)

**Step 1: Write the failing test**

```python
# tests/unit/intelligence/test_plugin_registry.py
import pytest
from src.intelligence.plugins import PluginRegistry


def _make_registry_with(indicator_names=(), pattern_names=()):
    reg = PluginRegistry()
    for n in indicator_names:
        class FakePlugin:
            name = n
        reg.indicators[n] = FakePlugin()
    for n in pattern_names:
        class FakePlugin:
            name = n
        reg.patterns[n] = FakePlugin()
    return reg


def test_validate_tier_passes_when_all_names_registered():
    reg = _make_registry_with(indicator_names=["RSI", "ATR"], pattern_names=["smc_FVG"])
    reg.validate_tier(["RSI", "ATR"], "I1")       # indicators
    reg.validate_tier(["smc_FVG"], "SMC")          # patterns


def test_validate_tier_raises_on_unknown_indicator():
    reg = _make_registry_with(indicator_names=["RSI"])
    with pytest.raises(ValueError, match="I1.*typo_plugin"):
        reg.validate_tier(["RSI", "typo_plugin"], "I1")


def test_validate_tier_raises_on_unknown_pattern():
    reg = _make_registry_with(pattern_names=["smc_FVG"])
    with pytest.raises(ValueError, match="SMC.*missing_plugin"):
        reg.validate_tier(["smc_FVG", "missing_plugin"], "SMC")


def test_validate_tier_raises_on_empty_registry():
    reg = PluginRegistry()
    with pytest.raises(ValueError, match="I1.*RSI"):
        reg.validate_tier(["RSI"], "I1")


def test_validate_tier_empty_list_always_passes():
    reg = PluginRegistry()
    reg.validate_tier([], "I1")  # nothing to validate
```

**Step 2: Run to verify it fails**

```bash
cd /home/bg/dev/indicagent
.venv/bin/pytest tests/unit/intelligence/test_plugin_registry.py -v
```
Expected: FAIL — `PluginRegistry` has no `validate_tier` method.

**Step 3: Implement `validate_tier()` in `plugins.py`**

Add after `list_patterns()`:

```python
def validate_tier(self, names: list[str], tier: str) -> None:
    """Raise ValueError at startup if any name is not in the registry.

    Checks both indicators and patterns so callers don't need to know
    which bucket a plugin lives in.
    """
    all_known = set(self.indicators) | set(self.patterns)
    unknown = [n for n in names if n not in all_known]
    if unknown:
        raise ValueError(
            f"Tier {tier} references unregistered plugin(s): {unknown}. "
            f"Check register_plugins.py and the TIER_* constants."
        )
```

**Step 4: Run tests**

```bash
.venv/bin/pytest tests/unit/intelligence/test_plugin_registry.py -v
```
Expected: 5 PASS.

**Step 5: Commit**

```bash
cd /home/bg/dev/indicagent
git add src/intelligence/plugins.py tests/unit/intelligence/test_plugin_registry.py
git commit -m "feat: add PluginRegistry.validate_tier() — hard crash on unknown plugin names"
```

---

## Task 2: Add canonical `TIER_*` constants to `register_plugins.py`

**Files:**
- Modify: `src/intelligence/register_plugins.py`
- Test: `tests/unit/intelligence/test_plugin_registry.py` (extend)

**Step 1: Write the failing tests**

Append to `test_plugin_registry.py`:

```python
def test_tier_constants_are_lists_of_strings():
    from src.intelligence.register_plugins import (
        TIER_I1, TIER_I3, TIER_I4, TIER_I5, TIER_SMC, TIER_I6, TIER_I7,
    )
    for tier, lst in [
        ("TIER_I1", TIER_I1), ("TIER_I3", TIER_I3), ("TIER_I4", TIER_I4),
        ("TIER_I5", TIER_I5), ("TIER_SMC", TIER_SMC), ("TIER_I6", TIER_I6),
        ("TIER_I7", TIER_I7),
    ]:
        assert isinstance(lst, list), f"{tier} must be a list"
        assert all(isinstance(n, str) for n in lst), f"{tier} must contain strings"
        assert len(lst) > 0, f"{tier} must not be empty"


def test_tier_constants_match_registry():
    """Every name in a TIER_* constant must be registered after register_all_plugins()."""
    from src.intelligence.plugins import PluginRegistry
    from src.intelligence.register_plugins import (
        TIER_I1, TIER_I3, TIER_I4, TIER_I5, TIER_SMC, TIER_I6, TIER_I7,
        register_all_plugins,
    )
    reg = PluginRegistry()
    # Temporarily swap the singleton so registration fills our local registry
    import src.intelligence.register_plugins as rp_module
    import src.intelligence.plugins as plugins_module
    original = plugins_module.registry
    plugins_module.registry = reg
    rp_module.registry = reg
    try:
        register_all_plugins()
        for tier_name, tier_list in [
            ("TIER_I1", TIER_I1), ("TIER_I3", TIER_I3), ("TIER_I4", TIER_I4),
            ("TIER_I5", TIER_I5), ("TIER_SMC", TIER_SMC), ("TIER_I6", TIER_I6),
            ("TIER_I7", TIER_I7),
        ]:
            reg.validate_tier(tier_list, tier_name)  # raises if any name missing
    finally:
        plugins_module.registry = original
        rp_module.registry = original


def test_tier_i1_has_23_plugins():
    from src.intelligence.register_plugins import TIER_I1
    assert len(TIER_I1) == 23, f"Expected 23 I1 plugins, got {len(TIER_I1)}: {TIER_I1}"


def test_tier_i7_has_7_plugins():
    from src.intelligence.register_plugins import TIER_I7
    assert len(TIER_I7) == 7, f"Expected 7 I7 plugins, got {len(TIER_I7)}: {TIER_I7}"
```

**Step 2: Run to verify it fails**

```bash
.venv/bin/pytest tests/unit/intelligence/test_plugin_registry.py -v -k "tier_constants"
```
Expected: FAIL — `TIER_I1` not importable yet.

**Step 3: Add `TIER_*` constants to end of `register_plugins.py`**

Add after the closing of `register_all_plugins()`:

```python
# ---------------------------------------------------------------------------
# Canonical tier plugin lists — single source of truth.
# Built from plugin.name attributes so any rename propagates automatically.
# Services import these instead of maintaining their own string lists.
# ---------------------------------------------------------------------------

TIER_I1: list[str] = [
    rsi_plugin.name,
    ma_plugin.name,
    ma_compare_plugin.name,
    macd_plugin.name,
    atr_plugin.name,
    bb_plugin.name,
    stoch_plugin.name,
    cci_plugin.name,
    wr_plugin.name,
    mfi_plugin.name,
    obv_plugin.name,
    vwap_plugin.name,
    supertrend_plugin.name,
    adx_plugin.name,
    keltner_plugin.name,
    donchian_plugin.name,
    roc_ppo_plugin.name,
    aroon_plugin.name,
    chandelier_plugin.name,
    cmf_plugin.name,
    hv_plugin.name,
    psar_plugin.name,
    stoch_rsi_plugin.name,
]

TIER_I3: list[str] = [
    swing_plugin.name,
    sr_plugin.name,
    trend_plugin.name,
]

TIER_I4: list[str] = [
    vol_regime_plugin.name,
    trend_regime_plugin.name,
    momentum_ctx_plugin.name,
    garch_vol_plugin.name,
    kalman_trend_plugin.name,
]

TIER_I5: list[str] = [
    rsi_div_plugin.name,
    squeeze_plugin.name,
    vol_div_plugin.name,
    confluence_plugin.name,
    trend_confluence_plugin.name,
    double_tb_plugin.name,
    head_shoulders_plugin.name,
    triangle_wedge_plugin.name,
]

TIER_SMC: list[str] = [
    bos_choch_plugin.name,
    fvg_plugin.name,
    ob_plugin.name,
    liq_sweep_plugin.name,
    bocpd_plugin.name,
    hmm_plugin.name,
]

TIER_I6: list[str] = [
    ctf_plugin.name,
]

TIER_I7: list[str] = [
    trend_follow_plugin.name,
    mean_revert_plugin.name,
    liq_sweep_reclaim_plugin.name,
    mtf_align_plugin.name,
    squeeze_exp_plugin.name,
    vwap_deviation_plugin.name,
    momentum_breakout_plugin.name,
]
```

**Step 4: Run tests**

```bash
.venv/bin/pytest tests/unit/intelligence/test_plugin_registry.py -v
```
Expected: All tests PASS.

**Step 5: Commit**

```bash
git add src/intelligence/register_plugins.py tests/unit/intelligence/test_plugin_registry.py
git commit -m "feat: add canonical TIER_* constants to register_plugins — single source of truth for plugin tier lists"
```

---

## Task 3: Wire `indicator_service.py` to use `TIER_I1` + validate on startup

**Files:**
- Modify: `services/indicator_service.py`

**Step 1: No new test needed** — existing 493 tests cover behaviour; startup validation is integration-level. Verify after the change by running unit tests.

**Step 2: Replace the hardcoded list and add startup validation**

In `indicator_service.py`:

1. Change the import line for `register_all_plugins`:
```python
# Before:
from src.intelligence.register_plugins import register_all_plugins
# After:
from src.intelligence.register_plugins import TIER_I1, register_all_plugins
```

2. Replace the `I1_PLUGINS` constant block (lines 41-66) with:
```python
# I1 plugin names — imported from register_plugins (single source of truth)
I1_PLUGINS = TIER_I1
```

3. In `IndicatorService.__init__()`, after `register_all_plugins()` is called, add:
```python
registry.validate_tier(I1_PLUGINS, "I1")
```

Find where `register_all_plugins()` is called in `__init__` and add the validation line immediately after it.

**Step 3: Run tests**

```bash
.venv/bin/pytest tests/unit/ -v --tb=short -q
```
Expected: 493 PASS, 0 failures.

**Step 4: Commit**

```bash
git add services/indicator_service.py
git commit -m "refactor: indicator_service imports TIER_I1 from register_plugins, validates on startup"
```

---

## Task 4: Wire `market_analysis_service.py` to use `TIER_*` + validate

**Files:**
- Modify: `services/market_analysis_service.py`

**Step 1: Replace imports and lists**

1. Change `register_all_plugins` import line:
```python
# Before:
from src.intelligence.register_plugins import register_all_plugins
# After:
from src.intelligence.register_plugins import (
    TIER_I3, TIER_I4, TIER_I5, TIER_SMC, TIER_I6,
    register_all_plugins,
)
```

2. Replace the five hardcoded list constants (I3_PLUGINS through I6_PLUGINS):
```python
# Plugin tier lists — imported from register_plugins (single source of truth)
I3_PLUGINS = TIER_I3
I4_PLUGINS = TIER_I4
I5_PLUGINS = TIER_I5
SMC_PLUGINS = TIER_SMC
I6_PLUGINS = TIER_I6
```

3. In `MarketAnalysisService.__init__()`, after `register_all_plugins()`:
```python
for tier_list, tier_name in [
    (I3_PLUGINS, "I3"), (I4_PLUGINS, "I4"), (I5_PLUGINS, "I5"),
    (SMC_PLUGINS, "SMC"), (I6_PLUGINS, "I6"),
]:
    registry.validate_tier(tier_list, tier_name)
```

**Step 2: Run tests**

```bash
.venv/bin/pytest tests/unit/ -v --tb=short -q
```
Expected: 493 PASS.

**Step 3: Commit**

```bash
git add services/market_analysis_service.py
git commit -m "refactor: market_analysis_service imports TIER_* from register_plugins, validates on startup"
```

---

## Task 5: Wire `intelligence_processor_service.py` to use `TIER_*` + validate

**Files:**
- Modify: `services/intelligence_processor_service.py`

**Step 1: Replace imports and lists**

1. Change `register_all_plugins` import line:
```python
# Before:
from src.intelligence.register_plugins import register_all_plugins  # noqa: E402
# After:
from src.intelligence.register_plugins import (  # noqa: E402
    TIER_I1, TIER_I3, TIER_I4, TIER_I5, TIER_SMC, TIER_I6,
    register_all_plugins,
)
```

2. Replace all hardcoded list constants:
```python
# Plugin tier lists — imported from register_plugins (single source of truth)
I1_PLUGINS = TIER_I1
I3_PLUGINS = TIER_I3
I4_PLUGINS = TIER_I4
I5_PLUGINS = TIER_I5
SMC_PLUGINS = TIER_SMC
I6_PLUGINS = TIER_I6
```

3. In `IntelligenceProcessorService.__init__()`, after `register_all_plugins()`:
```python
for tier_list, tier_name in [
    (I1_PLUGINS, "I1"), (I3_PLUGINS, "I3"), (I4_PLUGINS, "I4"),
    (I5_PLUGINS, "I5"), (SMC_PLUGINS, "SMC"), (I6_PLUGINS, "I6"),
]:
    registry.validate_tier(tier_list, tier_name)
```

**Step 2: Run tests**

```bash
.venv/bin/pytest tests/unit/ -v --tb=short -q
```
Expected: 493 PASS.

**Step 3: Commit**

```bash
git add services/intelligence_processor_service.py
git commit -m "refactor: intelligence_processor_service imports TIER_* from register_plugins, validates on startup"
```

---

## Task 6: Wire `signal_generator_service.py` to use `TIER_I7` + validate

**Files:**
- Modify: `services/signal_generator_service.py`

**Step 1: Replace import and list**

1. Change `register_all_plugins` import line:
```python
# Before:
from src.intelligence.register_plugins import register_all_plugins
# After:
from src.intelligence.register_plugins import TIER_I7, register_all_plugins
```

2. Replace the `I7_PLUGINS` constant:
```python
# I7 plugin names — imported from register_plugins (single source of truth)
I7_PLUGINS = TIER_I7
```

3. In `SignalGeneratorService.__init__()`, after `register_all_plugins()`:
```python
registry.validate_tier(I7_PLUGINS, "I7")
```

**Step 2: Run full test suite**

```bash
.venv/bin/pytest tests/unit/ -v --tb=short -q
```
Expected: 493 PASS.

**Step 3: Lint check**

```bash
.venv/bin/ruff check services/ src/intelligence/plugins.py src/intelligence/register_plugins.py --fix
```
Expected: 0 errors.

**Step 4: Commit**

```bash
git add services/signal_generator_service.py
git commit -m "refactor: signal_generator_service imports TIER_I7 from register_plugins, validates on startup"
```

---

## Task 7: Update CLAUDE.md and STATUS.md

**Files:**
- Modify: `docs/for-ai-assistants/CLAUDE.md`
- Modify: `docs/STATUS.md`

**Step 1: Update CLAUDE.md standards section**

Replace the two "plugin list sync gotcha" and "plugin name must match" entries added earlier with a single updated entry:

```markdown
- **Plugin tier lists — single source of truth**: `TIER_I1` … `TIER_I7` constants in `src/intelligence/register_plugins.py` are the canonical lists. Services import them — do NOT define local string lists. Services call `registry.validate_tier()` at startup, which hard-crashes if any name is missing from the registry. Adding a new plugin: (1) register it in `register_all_plugins()`, (2) add it to the appropriate `TIER_*` constant — done everywhere automatically.
```

**Step 2: Add completed phase to STATUS.md**

In the "Recent Changes" section at the top, add:
```markdown
### 2026-02-22 (v4.9.1)
- REFACTOR Plugin tier lists consolidated into TIER_* constants in register_plugins.py (single source of truth)
- ADD PluginRegistry.validate_tier() — hard crash at service startup on unknown plugin names
- FIX All service files now import tier constants; no more duplicated string lists
- FIX Plugin list gaps: ctx_KalmanTrend, patt_DoubleTB/HeadShoulders/TriangleWedge, smc_HMMRegime, MAComposite, ADX, KeltnerChannels, DonchianChannels wired in both service files
```

**Step 3: Commit**

```bash
git add docs/for-ai-assistants/CLAUDE.md docs/STATUS.md
git commit -m "docs: update CLAUDE.md and STATUS.md for plugin tier registry refactor"
```

---

## Verification

After all tasks complete, confirm everything works end-to-end:

```bash
# Full unit test suite
.venv/bin/pytest tests/unit/ -v --tb=short -q
# Expected: 502+ PASS (493 existing + ~9 new registry tests)

# Lint
.venv/bin/ruff check . --fix
# Expected: 0 errors

# Smoke test: services start and validate without crash
cd /home/bg/dev/indicagent
.venv/bin/python -c "
from src.intelligence.register_plugins import register_all_plugins, TIER_I1, TIER_I3, TIER_I4, TIER_I5, TIER_SMC, TIER_I6, TIER_I7
from src.intelligence.plugins import registry
register_all_plugins()
for lst, name in [(TIER_I1,'I1'),(TIER_I3,'I3'),(TIER_I4,'I4'),(TIER_I5,'I5'),(TIER_SMC,'SMC'),(TIER_I6,'I6'),(TIER_I7,'I7')]:
    registry.validate_tier(lst, name)
    print(f'{name}: {len(lst)} plugins OK')
"
```

Expected output:
```
I1: 23 plugins OK
I3: 3 plugins OK
I4: 5 plugins OK
I5: 8 plugins OK
SMC: 6 plugins OK
I6: 1 plugins OK
I7: 7 plugins OK
```
