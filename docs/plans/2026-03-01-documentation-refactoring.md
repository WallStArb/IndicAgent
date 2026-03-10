# Documentation Refactoring Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Update all stale documentation to reflect current state: v5.6.0, v1.0 shipped, 63 plugins, 803 tests, 24 contracts, ZAI LLM provider included.

**Architecture:** Single comprehensive plan covering 5 documentation files with ~30 bite-sized tasks. Each task verifies counts via codebase before updating, then applies changes with atomic commits.

**Tech Stack:** bash, grep, pytest, git

---

## Overview

Update stale information across documentation files to match current project state. All count-based updates verified via codebase inspection before applying.

**Files:**
- `README.md` - High priority, 10 tasks
- `docs/STATUS.md` - High priority, 7 tasks
- `docs/architecture/intelligence-bus.md` - Medium priority, 2 tasks
- `docs/concepts/intelligence-tiers.md` - Medium priority, 5 tasks
- `docs/architecture/plugin-registry-and-dag-execution.md` - Medium priority, 6 tasks

**Total:** ~30 tasks, ~1-2 hours estimated

---

### Task 1: Verify and update README.md version header

**Files:**
- Modify: `README.md:5`

**Step 1: Verify current version**

Run: `grep -n "^Version:" CLAUDE.md | head -1`
Expected: `Version: 5.8.0`

**Step 2: Update README.md header**

```diff
- **Version:** 5.6.0 | **Status:** v1.0 Shipped | 62 plugins · 784 tests · 23 contracts
+ **Version:** 5.8.0 | **Status:** v1.0 Shipped | 63 plugins · 803 tests · 24 contracts
```

**Step 3: Commit**

```bash
git add README.md
git commit -m "docs(readme): update version to 5.8.0 and stats (63 plugins, 803 tests, 24 contracts)"
```

---

### Task 2: Remove stale contracts from README.md list

**Files:**
- Modify: `README.md:210-219`

**Step 1: Identify contracts to remove**

Contracts to remove: BZ, NG, SR1, BTC (removed or migrated to spot FX/crypto)

**Step 2: Update contract list**

```diff
- - **Energy:** CL, BZ, NG
+ - **Energy:** CL
- - **Rates:** ZN, ZF, ZB, ZT, SR1
+ - **Rates:** ZN, ZF, ZB, ZT
- - **Crypto:** BTC
+ - **FX:** EURUSD, GBPUSD, USDJPY, USDCHF (spot/IDEALPRO)
+ - **Crypto:** BTCUSD, ETHUSD, SOLUSD (spot/PAXOS)
```

**Step 3: Commit**

```bash
git add README.md
git commit -m "docs(readme): update contract list - remove BZ/NG/SR1/BTC, add FX/crypto"
```

---

### Task 3: Update README.md plugin count

**Files:**
- Modify: `README.md:27`

**Step 1: Verify current plugin count**

Run: `grep -c "register_" src/intelligence/register_plugins.py`
Expected: count of 63

**Step 2: Update plugin count**

```diff
- | **Intelligence** | 62 plugins: I1 (23), I3 (3), I4 (5), I5 (8), I6 SMC (6), I6 confluence (1), I7 setups (14) + 4 aggregation components; I8 AI narratives (per-signal + group synthesis); Dashboard operational |
+ | **Intelligence** | 63 plugins: I1 (23), I3 (3), I4 (5), I5 (8), I6 SMC (6), I6 confluence (1), I7 setups (14) + 4 aggregation components; I8 AI narratives (per-signal + group synthesis); Dashboard operational |
```

**Step 3: Commit**

```bash
git add README.md
git commit -m "docs(readme): update plugin count from 62 to 63"
```

---

### Task 4: Update README.md test count

**Files:**
- Modify: `README.md:258`

**Step 1: Verify current test count**

Run: `pytest tests/unit/ --co -q | grep "test session"`
Expected: `803 collected items`

**Step 2: Update test count**

```diff
- - **Test suite:** 784 passing, 0 ruff errors.
+ - **Test suite:** 803 passing, 0 ruff errors.
```

**Step 3: Commit**

```bash
git add README.md
git commit -m "docs(readme): update test count from 784 to 803"
```

---

### Task 5: Add ZAI to README.md LLM providers

**Files:**
- Modify: `README.md:224`

**Step 1: Verify LLM providers exist**

Run: `ls src/intelligence/llm_providers.py | grep -c "Provider"`
Expected: count of 3 (ZAIProvider, OpenRouterProvider, OllamaProvider)

**Step 2: Add ZAI to tech stack section**

```diff
- - LangChain 1.2; LLM providers: Ollama (local) + OpenRouter (cloud)
+ - LangChain 1.2; LLM providers: ZAI (GLM-5, primary), OpenRouter (fallback), Ollama (fallback)
```

**Step 3: Commit**

```bash
git add README.md
git commit -m "docs(readme): add ZAI to LLM providers"
```

---

### Task 6: Update README.md AI narrative I8 section

**Files:**
- Modify: `README.md:86-88`

**Step 1: Update AI narrative service diagram**

```diff
- ai_narrative_service ──────────────► narratives:SYMBOL:TF
- (Ollama qwen3:8b per-signal +        narratives:group:GROUP_NAME ──► SSE ──► Dashboard
-  phi4-mini:3.8b group synthesis)
+ ai_narrative_service ──────────────► narratives:SYMBOL:TF
+ (ZAI GLM-5 / OpenRouter / Ollama per-signal +        narratives:group:GROUP_NAME ──► SSE ──► Dashboard
+  qwen3:8b group synthesis)
```

**Step 2: Commit**

```bash
git add README.md
git commit -m "docs(readme): update AI narrative service to show ZAI provider chain"
```

---

### Task 7: Update README.md phase count to 10

**Files:**
- Modify: `README.md:253`

**Step 1: Verify phase count**

Run: `ls .planning/phases/ | wc -l`
Expected: 10 phases (0-9)

**Step 2: Update phase count**

```diff
- **v1.0 shipped 2026-02-28. All 9 phases complete.**
+ **v1.0 shipped 2026-02-28. All 10 phases complete.**
```

**Step 3: Commit**

```bash
git add README.md
git commit -m "docs(readme): update phase count from 9 to 10"
```

---

### Task 8: Update docs/STATUS.md version and date

**Files:**
- Modify: `docs/STATUS.md:3-5`

**Step 1: Update header**

```diff
- > **Last Updated:** 2026-02-28
- > **Version:** 5.6.0
- > **Phase:** Phases 0–7 complete — 62 plugins, 781 tests; Phase 7 (CIS) complete
+ > **Last Updated:** 2026-03-01
+ > **Version:** 5.8.0
+ > **Phase:** Phases 0–9 complete — 63 plugins, 803 tests; Phase 7 (CIS) complete
```

**Step 2: Commit**

```bash
git add docs/STATUS.md
git commit -m "docs(status): update version to 5.8.0 and last updated date"
```

---

### Task 9: Update docs/STATUS.md test count

**Files:**
- Modify: `docs/STATUS.md:13`

**Step 1: Update test count**

```diff
- **Test Coverage:** 781 unit tests passing, 0 lint errors
+ **Test Coverage:** 803 unit tests passing, 0 lint errors
```

**Step 2: Commit**

```bash
git add docs/STATUS.md
git commit -m "docs(status): update test count from 781 to 803"
```

---

### Task 10: Update docs/STATUS.md plugin count

**Files:**
- Modify: `docs/STATUS.md:49`

**Step 1: Update plugin total**

```diff
- **Total Plugins:** 62 registered (23 I1 + 3 I3 + 5 I4 + 8 I5 + 6 SMC + 1 I6 confluence + 14 I7)
+ **Total Plugins:** 63 registered (23 I1 + 3 I3 + 5 I4 + 8 I5 + 6 SMC + 1 I6 confluence + 14 I7 + 1 Aggregation + 2 Trading)
```

**Step 2: Commit**

```bash
git add docs/STATUS.md
git commit -m "docs(status): update plugin count from 62 to 63"
```

---

### Task 11: Update docs/STATUS.md phases to 0-9

**Files:**
- Modify: `docs/STATUS.md:4-5`

**Step 1: Update phase status**

```diff
- > **Phase:** Phases 0–7 complete — 62 plugins, 781 tests; Phase 7 (CIS) complete
+ > **Phase:** Phases 0–9 complete — 63 plugins, 803 tests; Phase 7 (CIS) complete
```

**Step 2: Commit**

```bash
git add docs/STATUS.md
git commit -m "docs(status): update phases from 0-7 to 0-9"
```

---

### Task 12: Add ZAI to docs/STATUS.md LLM providers

**Files:**
- Modify: `docs/STATUS.md:154`

**Step 1: Add ZAI to development environment**

```diff
- **LLM Providers:** Ollama (local: qwen3:8b, phi4-mini:3.8b, etc.) + OpenRouter (cloud)
+ **LLM Providers:** ZAI (GLM-5, primary), OpenRouter (fallback), Ollama (fallback)
```

**Step 2: Commit**

```bash
git add docs/STATUS.md
git commit -m "docs(status): add ZAI to LLM providers"
```

---

### Task 13: Update docs/STATUS.md Phases 8-9 status

**Files:**
- Modify: `docs/STATUS.md:59-76`

**Step 1: Update Phase 8 status from Priority 1 to complete**

```diff
- ### Priority 1: Phase 8 — ML Scoring Model / Dashboard Completion
+ ### Phase 8 — Dashboard Completion (ML Scoring deferred)
```

**Step 2: Commit**

```bash
git add docs/STATUS.md
git commit -m "docs(status): update Phase 8 status to complete"
```

---

### Task 14: Fix docs/STATUS.md typo

**Files:**
- Modify: `docs/STATUS.md:25`

**Step 1: Fix typo in service name**

```diff
- | `indicagent-signal-tracker` — signal lifecycle | 9115 | `/metrics` |
+ | `indicagent-signal-tracker` — signal lifecycle | 9115 | `/metrics` |
```

**Step 2: Commit**

```bash
git add docs/STATUS.md
git commit -m "docs(status): fix typo signal-tracker"
```

---

### Task 15: Update docs/architecture/intelligence-bus.md version

**Files:**
- Modify: `docs/architecture/intelligence-bus.md:3-4`

**Step 1: Update version and date**

```diff
- **Version:** 4.1.0
- **Last Updated:** 2026-02-14
+ **Version:** 5.8.0
+ **Last Updated:** 2026-03-01
```

**Step 2: Commit**

```bash
git add docs/architecture/intelligence-bus.md
git commit -m "docs(intel-bus): update version to 5.8.0"
```

---

### Task 16: Add ZAI to docs/architecture/intelligence-bus.md

**Files:**
- Modify: `docs/architecture/intelligence-bus.md:1`

**Step 1: Add ZAI to architecture overview**

```diff
- IndicAgent is an **institutional-grade, real-time market intelligence platform** for futures trading — built from the ground up around a plugin-native architecture, a typed intelligence bus, and a zero-database live pipeline that keeps end-to-end latency in the sub-millisecond range.

+ IndicAgent is an **institutional-grade, real-time market intelligence platform** for futures trading — built from the ground up around a plugin-native architecture, a typed intelligence bus, and a zero-database live pipeline that keeps end-to-end latency in the sub-millisecond range. LLM providers: ZAI (GLM-5, primary), OpenRouter (fallback), Ollama (fallback).
```

**Step 2: Commit**

```bash
git add docs/architecture/intelligence-bus.md
git commit -m "docs(intel-bus): add ZAI to LLM providers"
```

---

### Task 17: Update docs/concepts/intelligence-tiers.md version

**Files:**
- Modify: `docs/concepts/intelligence-tiers.md:3-4`

**Step 1: Update version and date**

```diff
- **Last Updated:** 2026-02-28
+ **Last Updated:** 2026-03-01
```

**Step 2: Commit**

```bash
git add docs/concepts/intelligence-tiers.md
git commit -m "docs(intel-tiers): update last updated date"
```

---

### Task 18: Update docs/concepts/intelligence-tiers.md plugin count

**Files:**
- Modify: `docs/concepts/intelligence-tiers.md:90`

**Step 1: Update I7 total**

```diff
- | I7 | Trading outputs | 14 (9 original + 5 CIS) | COMPLETE (Phase 7: +5 CIS plugins, CIS aggregator, WeightUpdater) |
+ | I7 | Trading outputs | 19 (9 original + 5 CIS + 1 Aggregation + 2 Trading) + 4 components | COMPLETE (Phase 7: +5 CIS plugins, CIS aggregator, WeightUpdater; Phase 8-9: dashboard completion) |
```

**Step 2: Commit**

```bash
git add docs/concepts/intelligence-tiers.md
git commit -m "docs(intel-tiers): update I7 plugin count"
```

---

### Task 19: Update docs/concepts/intelligence-tiers.md test count

**Files:**
- Modify: `docs/concepts/intelligence-tiers.md:90`

**Step 1: Update totals**

```diff
- **Total Plugins:** 62 registered (23 I1 + 3 I3 + 5 I4 + 8 I5 + 6 SMC + 1 I6 confluence + 14 I7) | 781 unit tests
+ **Total Plugins:** 63 registered (23 I1 + 3 I3 + 5 I4 + 8 I5 + 6 SMC + 1 I6 confluence + 14 I7 + 1 Aggregation + 2 Trading) | 803 unit tests
```

**Step 2: Commit**

```bash
git add docs/concepts/intelligence-tiers.md
git commit -m "docs(intel-tiers): update plugin count to 63 and test count to 803"
```

---

### Task 20: Update docs/concepts/intelligence-tiers.md I8 section

**Files:**
- Modify: `docs/concepts/intelligence-tiers.md:97-105`

**Step 1: Add ZAI to I8 description**

```diff
- | I8 | AI Intelligence | 1 service | RUNNING (per-signal + group synthesis) |
+ | I8 | AI Intelligence | 1 service | RUNNING (ZAI GLM-5 per-signal + OpenRouter/Ollama fallback + group synthesis) |
```

**Step 2: Commit**

```bash
git add docs/concepts/intelligence-tiers.md
git commit -m "docs(intel-tiers): update I8 to include ZAI provider"
```

---

### Task 21: Update docs/concepts/intelligence-tiers.md OpenRouter mention

**Files:**
- Modify: `docs/concepts/intelligence-tiers.md:240`

**Step 1: Update OpenRouter availability text**

```diff
- **Also Available:** OpenRouter (Cloud LLM) — Use OpenRouter for cloud-hosted models when local inference is too slow.
+ **Also Available:** ZAI (GLM-5, primary), OpenRouter (fallback), Ollama (fallback) — Use ZAI for primary LLM, OpenRouter/Ollama as fallbacks.
```

**Step 2: Commit**

```bash
git add docs/concepts/intelligence-tiers.md
git commit -m "docs(intel-tiers): update LLM providers to include ZAI"
```

---

### Task 22: Update docs/architecture/plugin-registry-and-dag-execution.md version

**Files:**
- Modify: `docs/architecture/plugin-registry-and-dag-execution.md:3-5`

**Step 1: Update version**

```diff
- **Version:** 4.1.0
- **Last Updated:** 2026-02-14
+ **Version:** 5.8.0
+ **Last Updated:** 2026-03-01
```

**Step 2: Commit**

```bash
git add docs/architecture/plugin-registry-and-dag-execution.md
git commit -m "docs(plugin-registry): update version to 5.8.0"
```

---

### Task 23: Update docs/architecture/plugin-registry-and-dag-execution.md plugin count

**Files:**
- Modify: `docs/architecture/plugin-registry-and-dag-execution.md:5`

**Step 1: Update plugin count**

```diff
- **Status:** 31 Plugins Operational — I1–I5 Complete, DAG Execution Active
+ **Status:** 63 Plugins Operational — I1–I8 Complete, DAG Execution Active
```

**Step 2: Commit**

```bash
git add docs/architecture/plugin-registry-and-dag-execution.md
git commit -m "docs(plugin-registry): update plugin count from 31 to 63"
```

---

### Task 24: Update docs/architecture/plugin-registry-and-dag-execution.md test count

**Files:**
- Modify: `docs/architecture/plugin-registry-and-dag-execution.md:334`

**Step 1: Update test count**

```diff
- - **Total: 123 unit tests passing, 0 ruff errors**
+ - **Total: 803 unit tests passing, 0 ruff errors**
```

**Step 2: Commit**

```bash
git add docs/architecture/plugin-registry-and-dag-execution.md
git commit -m "docs(plugin-registry): update test count from 123 to 803"
```

---

### Task 25: Update docs/architecture/plugin-registry-and-dag-execution.md I1 list

**Files:**
- Modify: `docs/architecture/plugin-registry-and-dag-execution.md:197-216`

**Step 1: Add missing I1 indicators to list**

```diff
### I1 Indicator Plugins (16) — All support incremental `compute_next()`
+ ### I1 Indicator Plugins (23) — All support incremental `compute_next()`
| Plugin | Category | Key Outputs |
|--------|----------|-------------|
| RSI | Momentum | `rsi_14` |
+ | Plugin | Category | Key Outputs |
+--------|----------|-------------|
+ | RSI | Momentum | `rsi_14` |
+ | MACD | Trend | `macd_12_26_9`, `macd_signal_12_26_9`, `macd_histogram_12_26_9` |
+ | SMA/EMA | Trend | `sma_20`, `sma_50`, `ema_12`, `ema_26` |
+ | ATR | Volatility | `atr_14` |
+ | Bollinger Bands | Volatility | `bb_20_2_upper`, `bb_20_2_mid`, `bb_20_2_lower` |
+ | Stochastic | Momentum | `stoch_k_14`, `stoch_d_14` |
+ | CCI | Momentum | `cci_20` |
+ | Williams %R | Momentum | `willr_14` |
+ | MFI | Volume | `mfi_14` |
+ | OBV | Volume | `obv_value`, `obv_slope` |
+ | VWAP | Volume | `vwap_value` |
+ | ADX/DMI | Trend | `adx_14`, `plus_di_14`, `minus_di_14` |
+ | Keltner Channels | Volatility | `kc_upper_20`, `kc_mid_20`, `kc_lower_20` |
+ | Donchian Channels | Volatility | `donchian_upper_20`, `donchian_mid_20`, `donchian_lower_20` |
+ | ROC/PPO | Momentum | `roc_14`, `ppo_12_26`, `ppo_signal_12_26` |
+ | MA Composites | Composite | `ma_cross_20_50`, `ma_distance_20` |
+ | Supertrend | Trend | `supertrend_direction`, `supertrend_trend` |
+ | PSAR | Trend | `psar` |
+ | StochRSI | Momentum | `stochrsi_k`, `stochrsi_d` |
+ | CMF | Volume | `cmf_value` |
+ | Aroon | Trend | `aroon_up`, `aroon_down`, `aroon_os` |
+ | ChandelierExit | Trend | `chandelier_exit_long`, `chandelier_exit_short` |
+ | HistoricalVolatility | Volatility | `hist_vol_mean`, `hist_vol_upper`, `hist_vol_lower` |
```

**Step 2: Commit**

```bash
git add docs/architecture/plugin-registry-and-dag-execution.md
git commit -m "docs(plugin-registry): update I1 plugin list from 16 to 23 indicators"
```

---

### Task 26: Add ZAI to docs/architecture/plugin-registry-and-dag-execution.md LLM providers

**Files:**
- Modify: `docs/architecture/plugin-registry-and-dag-execution.md:399-401`

**Step 1: Add ZAI to I8 section**

```diff
### I8: AI Intelligence
+ ZAI (GLM-5) - Primary LLM provider via ZAIProvider in llm_providers.py
- Ollama (local) - Fallback via OllamaProvider
- OpenRouter (cloud) - Fallback via OpenRouterProvider
```

**Step 2: Commit**

```bash
git add docs/architecture/plugin-registry-and-dag-execution.md
git commit -m "docs(plugin-registry): add ZAI to I8 LLM providers"
```

---

## Summary

**Files updated:** 5
**Tasks:** 26 bite-sized tasks
**Estimated time:** 1-2 hours
**Risk:** Low - straightforward string replacements with verification

**Verification approach:** All count-based updates verified via `grep`, `pytest`, or code inspection before applying.

**Commits per file:** Batch related changes when possible (e.g., multiple README.md changes in one commit).
