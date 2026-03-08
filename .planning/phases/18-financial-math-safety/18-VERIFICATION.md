---
phase: 18-financial-math-safety
verified: 2026-03-08T14:30:00Z
status: passed
score: 13/13 must-haves verified
re_verification:
  previous_status: gaps_found
  previous_score: 9/13
  gaps_closed:
    - "trade_framer.py uses epsilon tolerance (1e-9) for all floating-point comparisons (FIN-01)"
    - "All LLM providers use configurable timeout from Settings (API-04)"
    - "market_analysis_service has per-key asyncio.Lock() for _plugin_states access (API-05)"
    - "indicator_service has per-key asyncio.Lock() for _i1_plugin_states access (API-06)"
  gaps_remaining: []
  regressions: []
---

# Phase 18: Financial Math Safety Verification Report

**Phase Goal:** Financial Math Safety — epsilon tolerance, magic number documentation, configurable timeouts, concurrency locks
**Verified:** 2026-03-08T14:30:00Z
**Status:** passed
**Re-verification:** Yes — after gap closure (plans 18-04 through 18-07)

## Goal Achievement

### Observable Truths

| #   | Truth                                                                            | Status     | Evidence                                                                                                    |
| --- | -------------------------------------------------------------------------------- | ---------- | ----------------------------------------------------------------------------------------------------------- |
| 1   | trade_framer.py uses epsilon tolerance (1e-9) for all floating-point comparisons | VERIFIED   | EPSILON_TOLERANCE used at 40+ sites (lines 175, 182, 189, 214, 219, 226, 230, 236, 243, 249, 257, 263, 276, 278, 284, 286, 292, 298, 304, 319, 321, 327, 329, 335, 341, 349, 362, 374, 380, 385, 389, 395, 406, 441, 451, 457, 462, 466, 472, 478, 485, 490, 598, 618, 642). No raw `> 0` / `< 0` on floats remain. |
| 2   | cis_scorer.py uses epsilon tolerance for slope/MACD/ROC direction comparisons    | VERIFIED   | EPSILON_TOLERANCE used at lines 206, 231, 234 for slope_dir, macd_dir, roc_dir                           |
| 3   | All ATR multipliers documented as named constants with inline comments             | VERIFIED   | 13 ATR multipliers documented with Renaissance framing (lines 55-75 in trade_framer.py)                    |
| 4   | Regime thresholds (0.35, 3, 0.1) documented as named constants                  | VERIFIED   | CIS_FIRE_THRESHOLD = 0.35, BUCKET_AGREE_MIN = 3, BUCKET_NOISE_FLOOR = 0.1 (cis_scorer.py lines 29-31)   |
| 5   | RSI zero-loss guard documented                                                   | VERIFIED   | 3-line inline comment at rsi.py lines 84-86 explaining behavior with Renaissance framing                    |
| 6   | Settings class exposes ibkr_timeout_sec with default 20.0s                      | VERIFIED   | Field defined at settings.py line 53-55 with AliasChoices for IBKR_TIMEOUT_SEC, IB_TIMEOUT_SEC           |
| 7   | Settings class exposes llm_timeout_sec with default 60.0s                        | VERIFIED   | Field defined at settings.py line 75-77 with AliasChoices for LLM_TIMEOUT_SEC                            |
| 8   | Timeout values configurable via environment variables                              | VERIFIED   | AliasChoices mappings confirmed for both timeout fields                                                     |
| 9   | IBKR provider uses configurable timeout from Settings                             | VERIFIED   | ibkr.py uses self._settings.ib_timeout_sec at line 81 (connectAsync) and line 314 (get_quote default)    |
| 10  | All LLM providers use configurable timeout from Settings                          | VERIFIED   | All four providers (OpenRouterProvider line 60, AnthropicProvider line 118, ZAIProvider line 182, OllamaProvider line 238) have `self.timeout = timeout or _default_llm_timeout()` |
| 11  | market_analysis_service has per-key asyncio.Lock() for _plugin_states access    | VERIFIED   | `_run_tier` is `async def`, wraps state access at line 212 with `async with self._get_state_lock(state_key)`. `_run_analysis_pipeline` is `async def`, called with `await` at line 316. All 6 `_run_tier` calls use `await`. |
| 12  | indicator_service has per-key asyncio.Lock() for _i1_plugin_states access       | VERIFIED   | `_run_i1_plugins` is `async def`. `_update_plugin_state` (line 232) and `_save_plugin_state` (line 244) are async helpers that wrap state access with `async with self._get_state_lock(state_key)`. Called with `await` at line 325. |
| 13  | ai_narrative_service has asyncio.Lock() for _latest_signals access               | VERIFIED   | _latest_signals_lock exists at line 308 and used at lines 501, 774 with `async with` context             |

**Score:** 13/13 truths verified

### Required Artifacts

| Artifact                                          | Expected                                                    | Status   | Details                                                                                                      |
| ------------------------------------------------- | ----------------------------------------------------------- | -------- | ------------------------------------------------------------------------------------------------------------ |
| `src/intelligence/trading/trade_framer.py`        | Trade framing with epsilon tolerance for float comparisons  | VERIFIED | EPSILON_TOLERANCE used at 40+ comparison sites; no raw `> 0` / `< 0` on floats remain                     |
| `src/intelligence/trading/cis_scorer.py`          | CIS scoring with epsilon tolerance for direction comparisons | VERIFIED | EPSILON_TOLERANCE used for slope_dir, macd_dir, roc_dir                                                    |
| `src/intelligence/indicators/rsi.py`              | RSI with documented zero-loss behavior                      | VERIFIED | 3-line inline comment at lines 84-86 with Renaissance framing                                                |
| `src/config/settings.py`                          | Configurable timeouts for IBKR and LLM providers            | VERIFIED | ib_timeout_sec (20.0s) and llm_timeout_sec (60.0s) with AliasChoices env var support                      |
| `src/providers/ibkr.py`                           | IBKR provider with configurable timeout                     | VERIFIED | Uses Settings.ib_timeout_sec in connectAsync (line 81) and get_quote (line 314)                            |
| `src/intelligence/llm_providers.py`               | All LLM providers with configurable timeout                 | VERIFIED | All four providers use `self.timeout = timeout or _default_llm_timeout()` in __init__                      |
| `services/market_analysis_service.py`             | Per-key lock for _plugin_states                             | VERIFIED | `_run_tier` async, state access wrapped with `async with self._get_state_lock(state_key)` at line 212      |
| `services/indicator_service.py`                   | Per-key lock for _i1_plugin_states                          | VERIFIED | Async helpers `_update_plugin_state` and `_save_plugin_state` wrap state access with per-key locks         |
| `services/ai_narrative_service.py`                | Lock for _latest_signals                                    | VERIFIED | _latest_signals_lock properly used in async with contexts at lines 501, 774                                |

### Key Link Verification

| From                                              | To                              | Via                                                         | Status | Details                                                                                          |
| ------------------------------------------------- | ------------------------------- | ----------------------------------------------------------- | ------ | ------------------------------------------------------------------------------------------------ |
| `src/intelligence/trading/trade_framer.py`        | EPSILON_TOLERANCE constant      | Direct use in comparisons                                   | WIRED  | 40+ comparison sites across the full file                                                        |
| `src/intelligence/trading/cis_scorer.py`          | EPSILON_TOLERANCE constant      | Direction comparisons for slope/MACD/ROC                   | WIRED  | Lines 206, 231, 234                                                                              |
| `src/providers/ibkr.py`                           | `src/config/settings.py`        | `self._settings.ib_timeout_sec`                            | WIRED  | Lines 81, 314                                                                                    |
| `src/intelligence/llm_providers.py`               | `src/config/settings.py`        | `_default_llm_timeout()` calling `Settings().llm_timeout_sec` | WIRED | All four providers: OpenRouter line 60, Anthropic line 118, ZAI line 182, Ollama line 238       |
| `services/market_analysis_service.py`             | `_plugin_states_locks` dict     | `async with self._get_state_lock(state_key)` in `_run_tier` | WIRED | Line 212 wraps state read/write; all 6 _run_tier calls await'd (lines 233, 237, 241, 245, 249, 256) |
| `services/indicator_service.py`                   | `_i1_plugin_states_locks` dict  | `async with self._get_state_lock` in `_update_plugin_state` and `_save_plugin_state` | WIRED | Lines 241, 249; called at lines 266, 268; `_run_i1_plugins` awaited at line 325 |
| `services/ai_narrative_service.py`                | `_latest_signals_lock`          | `async with self._latest_signals_lock`                     | WIRED  | Lines 501, 774                                                                                   |

### Requirements Coverage

| Requirement | Source Plan | Description                                                                          | Status   | Evidence                                                                                          |
| ----------- | ----------- | ------------------------------------------------------------------------------------ | -------- | ------------------------------------------------------------------------------------------------- |
| FIN-01      | 18-01/18-04 | System uses epsilon tolerance (1e-9) for all floating-point comparisons in trade_framer.py | SATISFIED | 40+ comparison sites use EPSILON_TOLERANCE; no raw `> 0` / `< 0` on floats remain          |
| FIN-02      | 18-01       | CIS scorer uses epsilon tolerance for slope/MACD/ROC direction comparisons            | SATISFIED | cis_scorer.py lines 206, 231, 234                                                                |
| FIN-03      | 18-01       | All magic numbers documented as named constants with inline comments                   | SATISFIED | ATR multipliers and regime thresholds documented with Renaissance framing                         |
| FIN-04      | 18-01       | ATR multipliers documented (0.25, 0.30, 0.20, 0.25, 0.50, 2.0, 0.001)               | SATISFIED | All 13 multipliers documented in trade_framer.py lines 55-75                                    |
| FIN-05      | 18-01       | Regime thresholds documented (0.35, 3, 0.1)                                          | SATISFIED | CIS_FIRE_THRESHOLD, BUCKET_AGREE_MIN, BUCKET_NOISE_FLOOR in cis_scorer.py lines 29-31           |
| FIN-06      | 18-01       | RSI zero-loss guard behavior documented in rsi.py                                    | SATISFIED | 3-line inline comment at rsi.py lines 84-86                                                      |
| API-01      | 18-02       | Settings class exposes ibkr_timeout_sec (default 20.0s)                               | SATISFIED | settings.py line 53-55 with AliasChoices support                                                 |
| API-02      | 18-02       | Settings class exposes llm_timeout_sec (default 60.0s)                               | SATISFIED | settings.py line 75-77 with AliasChoices support                                                 |
| API-03      | 18-03       | IBKR provider uses configurable timeout from Settings                                 | SATISFIED | ibkr.py uses self._settings.ib_timeout_sec at lines 81 and 314                                  |
| API-04      | 18-03/18-05 | All LLM providers use configurable timeout from Settings                              | SATISFIED | All four providers use `self.timeout = timeout or _default_llm_timeout()` in __init__            |
| API-05      | 18-03/18-06 | market_analysis_service has per-key asyncio.Lock() for _plugin_states access         | SATISFIED | `_run_tier` async, state access wrapped with lock at line 212; `_run_analysis_pipeline` async   |
| API-06      | 18-03/18-07 | indicator_service has per-key asyncio.Lock() for _i1_plugin_states access            | SATISFIED | `_update_plugin_state` and `_save_plugin_state` async helpers with per-key locks; `_run_i1_plugins` async |
| API-07      | 18-03       | ai_narrative_service has asyncio.Lock() for _latest_signals access                   | SATISFIED | _latest_signals_lock at line 308, used at lines 501 and 774                                      |

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
| ---- | ---- | ------- | -------- | ------ |
| None | -    | -       | -        | No anti-patterns found in gap-closure files                                                     |

### Human Verification Required

None — all artifacts and connections verified programmatically.

### Gaps Summary

All 4 gaps from the initial verification have been closed:

1. **FIN-01 (gap closure plan 18-04):** EPSILON_TOLERANCE is now used at 40+ comparison sites throughout `trade_framer.py`. No raw `> 0` / `< 0` comparisons on floating-point values remain.

2. **API-04 (gap closure plan 18-05):** All four LLM providers (OpenRouterProvider, AnthropicProvider, ZAIProvider, OllamaProvider) now have `timeout: float | None = None` in `__init__` with `self.timeout = timeout or _default_llm_timeout()`.

3. **API-05 (gap closure plan 18-06):** `_run_tier` is now `async def` with state access wrapped in `async with self._get_state_lock(state_key)`. `_run_analysis_pipeline` is now `async def` and called with `await` at line 316.

4. **API-06 (gap closure plan 18-07):** `_run_i1_plugins` is now `async def`. Two new async helpers `_update_plugin_state` and `_save_plugin_state` wrap state read and write with per-key lock. `_run_i1_plugins` is called with `await` at line 325.

No regressions detected in previously-passing items.

---

_Verified: 2026-03-08T14:30:00Z_
_Verifier: Claude (gsd-verifier)_
