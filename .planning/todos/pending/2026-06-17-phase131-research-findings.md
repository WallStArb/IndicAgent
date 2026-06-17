# Phase 131 — Empirical Research Findings

**Created:** 2026-06-17
**Purpose:** Root-cause findings from live DB investigation. Use these to replace hypotheses
in the Phase 131-133 spec before GSD planning begins.

---

## Finding 1 — Plugin coverage: 30/36 confirmed, 6 zeros

```sql
SELECT setup_plugin, COUNT(*) FROM signal_events GROUP BY 1 ORDER BY 2;
-- 30 distinct plugins, 6 with 0 rows
```

Zero-emission plugins (all 6 confirmed via DB):
- `trad_POCRejection` — known crash (A1, float(None))
- `trad_HVNRejection` — same crash (A1)
- `trad_MTFAlignment` — 0 signals (needs code trace)
- `trad_PrevDayLevelTest` — 0 signals (needs code trace)
- `trad_AnchoredVWAPReversion` — 0 signals (needs code trace)
- `trad_CrossAssetDivergence` — 0 signals (needs code trace)

Code trace for the 4 structural plugins NOT yet done — still hypothesis, not confirmed.

---

## Finding 2 — 10 zero-signal OHLCV symbols: 3 distinct root causes

```sql
-- 98 symbols in market_data_ohlcv; 107 in signal_events (19 expired rolled futures expected)
-- 10 in OHLCV with 0 signals: EURUSD, EWZ, FXI, GDXJ, ITB, USO, VLUE, VXK6, VXM6, ZNM6
```

**Root cause A — Not in instruments table OR contract_metadata:**
EWZ, FXI, GDXJ, ITB, USO, VLUE — ETFs that exist in OHLCV but have no instruments row.
`get_active_contracts()` only returns instruments from the `instruments` table.
These symbols are never passed to `replay_symbol()`. They had bars in OHLCV but were
never replayed. Fix: add to `instruments` table as equity/etf instruments.

**Root cause B — Expired rolled contracts (is_front_month=false = roll already occurred):**
VXK6, VXM6, ZNM6 — `is_front_month=false` means the roll has already happened; these
are no longer the active front-month contract. They DID have OHLCV bars during their
active window. 0 signals during that window is the same failure mode as A4 (rolled-contract
plugin errors on NQU6/YMM6/RTYM6) — the `asset_class` injection gap in `replay_symbol()`
likely affects VX/ZN contracts too. Their symptom differs (0 signals vs 201K plugin errors)
only in where the failure surfaces. The A4 fix should be confirmed against VX/ZN contracts.
NOT a replay scope issue — it's the same roll-chain handling gap as A4.

**Root cause C — In instruments (is_active=true) but 0 signals:**
EURUSD — active instrument, asset_class='fx'. Either replay excluded FX, or signal
generation fails for FX instruments. Check run_historical_pipeline.py line 2283
(`if instrument.asset_class in (AssetClass.FX, AssetClass.CRYPTO)`) — this branch
may have a different code path or may be excluded by replay flags. Related to A3
(stop gate on small-tick instruments) — FX pairs may be entirely emission-gated.

---

## Finding 3 — A4 root cause: asset_class not injected in replay pipeline

`run_historical_pipeline.py` calls `replay_symbol()` which calls `run_analysis_pipeline()`
and `run_i7_and_persist()` directly — it does NOT use `FeaturePipelineExecutor`.

The asset_class injection lives in `feature_pipeline_executor.py:332`:
```python
if instrument is not None:
    flat_features["asset_class"] = instrument.asset_class.value
```

This line is NEVER reached in replay. `run_analysis_pipeline()` in the script has no
equivalent injection. Result: `all_features["asset_class"]` is never set.

Why only rolled contracts error (NQU6/YMM6/RTYM6) and not front-month contracts:
- Front-month contracts (NQU6, RTYU6, YMU6) ARE in instruments table, but the
  rolled month variants (NQM6, YMM6, RTYM6) are NOT in instruments — they are
  only in contract_metadata. The instrument lookup at the pipeline level may
  succeed for front-month via a different path.
- STILL UNCONFIRMED — one more trace needed to verify this vs the missing
  asset_class theory.

**Fix:** In `replay_symbol()`, build a symbol→asset_class lookup from
`contract_metadata JOIN instruments` and inject `asset_class` into `all_features`
before passing to `run_i7_and_persist()`. Mirror what `FeaturePipelineExecutor` does.

---

## Finding 4 — I6 CTF zero bug (NEW, HIGH severity, not in master list)

**Confirmed from memory `project_i6_ctf_zero_bug.md`:**
- All 4,810,307 `intelligence_features` rows: `ctf_score=0.0` (not NULL)
- All 518,464 non-null `signal_events.ctf_score` = 0.0
- I1/I3 data is correct (RSI, ADX, trend_direction populated normally)

**Root cause (hypothesis, code fix not yet applied):**
`CrossTimeframeConfluencePlugin.compute_full()` builds `other_intel` from `intel_*`
frames (cached IntelligenceEvents for other TFs via `_last_events`). At the time I6
runs for a given bar, `_last_events` for other TFs is empty or stale — no prior bar
has populated it in this replay run. So `other_intel` entries return
`extract_trend_sign(intel)=0` (neutral), making `score_trend_alignment()` return 0
for all TFs, hence `ctf_score=0`.

**Key files:**
- `src/intelligence/confluence/cross_timeframe.py:66-150` — `compute_full()`
- `src/intelligence/confluence/confluence_alignment.py:37-60` — `score_trend_alignment`
- `src/intelligence/confluence/confluence_weights.py:45-58` — `extract_trend_sign`
- `src/intelligence/pipeline/feature_pipeline_executor.py:183-194` — `_last_events` build

**Fix approach:** Seed `_last_events` from `intelligence_features` DB before
replay begins (warmup from DB). Alternatively, restructure the bar merge loop in
`replay_symbol()` so lower-TF bars always populate `intelligence_cache` before
higher-TF bars that need I6 cross-TF scores.

**Impact:** All 537K signals have wrong ctf_score. Full re-replay needed after fix.
This must be in Phase 131 scope — it affects the entire corpus, not just a subset.

---

## What still needs investigation (Phase 131 first tasks)

1. **4 zero-emission plugins** — run targeted log trace + signal count per symbol/tf
   to confirm whether these are bugs or genuine data constraints. Do NOT accept
   "structural constraint" without empirical evidence.

2. **EURUSD 0 signals** — trace the FX code path in run_historical_pipeline.py
   around line 2283. Confirm whether FX is explicitly excluded or silently failing.

3. **VXK6/VXM6/ZNM6 0 signals** — confirm replay parameters included these symbols.
   Check what `--include-rolled` covers vs VIX/Treasury contract naming.

4. **A4 final confirmation** — verify the asset_class injection gap is the actual
   cause of rolled-contract errors by adding a single log line in replay_symbol()
   and checking whether asset_class appears in all_features for a test run.

5. **I6 CTF fix** — apply fix, run a 1-week sample replay, verify ctf_score
   distribution is non-zero before committing to a full corpus rebuild.
