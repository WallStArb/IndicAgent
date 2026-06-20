# Phase 131: Signal Generation Integrity — Context

**Gathered:** 2026-06-17
**Status:** Ready for planning

<domain>
## Phase Boundary

Fix every systematic signal generation bug that produces zero emissions or wrong values corpus-wide. Every plugin that should fire does fire. Every active instrument produces signals. Corpus rebuild is reliable. Phase 133 cannot begin until Phase 131 verification gate passes.

**Verification gate:** Unit tests green; targeted 2-week replay shows 35 of 35 eligible plugins emitting signals (CrossAssetDivergence is the only exclusion — formally architectural live-only, not a fixable bug); no zero-signal instruments in active contract list from fixable bugs; all investigation items resolved with empirical findings documented.

</domain>

<decisions>
## Implementation Decisions

### D-01: ETF coverage — retired instruments are NOT added back

The 6 ETFs present in `market_data_ohlcv` with 0 signals (EWZ, FXI, GDXJ, ITB, USO, VLUE) are **intentionally retired instruments**, each replaced by a better equivalent in the current active instrument list:

| Retired | Replaced by |
|---------|-------------|
| EWZ (Brazil) | EEM (broad EM) |
| FXI (China Large-Cap) | KWEB (China Internet) |
| GDXJ (Junior Gold Miners) | GDX (Senior Miners kept) |
| ITB (Home Construction) | XHB (Homebuilders kept) |
| USO (Oil ETF) | CL futures + OIH + XOP |
| VLUE (MSCI Value Factor) | VTV + QUAL |

Do NOT add these to `instruments` or `settings.py`. The "Root cause A" fix described in the spec is dropped. Symbol coverage gap reduces to: A4 rolled-contract fix (VXK6/VXM6/ZNM6).

### D-02: CrossAssetDivergence is formally live-only — 35/36 plugin corpus target

`trad_CrossAssetDivergence` requires `frames['cross_asset']` from the live `cross_asset_service`. Historical replay processes single symbols; pre-loading cross-instrument bar arrays would produce an approximation of the real-time state, not the actual state. An approximated corpus entry whose generation mechanism differs from production is worse than a missing entry — it introduces state-mismatch bias into ML training.

**Decision:** Document as live-only in the plugin file with `# live-only: requires cross_asset_service real-time state`. Corpus targets **35/36 plugins**. This is the only plugin where zero-emission is architectural, not a bug. Live signal accumulation post-Phase 133 fills the gap.

Do NOT wire cross-asset context into replay for this phase or the next.

### D-03: A7 CTF fix — DB seed at replay startup

`ctf_score=0.0` corpus-wide because `_last_events[symbol][tf]` is empty when I6 runs for bar 1. Fix: seed `_last_events` from `intelligence_features` DB before replay begins.

**Approach locked:** Before the first bar per (symbol, TF), query `intelligence_features` for the most recent row per TF, reconstruct a minimal `IntelligenceEvent` from I3 fields (`trend_direction`, `trend_strength`, etc.), and populate `_last_events[symbol][tf]`. This is the faithful approach — it represents what the system knew from the prior run.

**Why not the bar merge loop alternative:** In single-symbol replay, you have no prior-TF data for bar 1 regardless of TF ordering. The fix would require multi-symbol orchestration — a bigger scope change than the DB seed. The DB is the canonical record of prior state; seeding from it is correct, not a workaround.

**Query cost:** ~316 queries (79 symbols × 4 TFs), parallelizable, single-row `ORDER BY ts DESC LIMIT 1` — adds under 1 second to a multi-hour rebuild.

**Critical detail for planner:** The existing `intelligence_features` rows have correct I3 fields even in the broken corpus (I1/I3 data confirmed correct; only `ctf_score` was wrong). So seeding from the current DB gives valid I3 input for I6 recomputation.

**Changes:** `feature_pipeline_executor.py` (add `_seed_last_events_from_db()` method) + `replay_symbol()` in `run_historical_pipeline.py` (call seed before event loop).

**Verification checkpoint:** Run 1-week sample replay after fix. `ctf_score` distribution must be non-zero (expected range 0.1–0.9 for bars with real trend). Do NOT proceed to Phase 133 full rebuild without this verification passing.

### D-04: Remaining zero-emission plugins — fixes as specified in spec

All four remaining zero-emission plugins have confirmed root causes and specified fixes. Implement as written in the spec; no discretion here:

- `trad_MTFAlignment` — no separate fix needed; downstream of A7. Fix A7 → fires automatically.
- `trad_PrevDayLevelTest` — increase `bar_histories` deque `maxlen` from 200 to 800 in `replay_symbol()` at `run_historical_pipeline.py:1649`.
- `trad_AnchoredVWAPReversion` — restructure gate ordering in plugin: check departure state and reclaim condition BEFORE clearing state when `abs(sigma) < sigma_min`. **State-clearing sequence is load-bearing:** on the reclaim bar the exact order must be (1) detect reclaim → (2) emit signal → (3) clear departure state → (4) return. Clearing state before step 2 re-introduces the bug. Leaving state active after emission causes a duplicate signal on the next bar when sigma stabilizes near zero.
- `trad_CrossAssetDivergence` — document as live-only (D-02 above).

### D-05: Symbol coverage — VXK6/VXM6/ZNM6 via A4 fix only

VXK6/VXM6/ZNM6 share the same root cause as A4 (asset_class not injected in `replay_symbol()`). The A4 fix (build `symbol→asset_class` lookup from `contract_metadata` and inject into `all_features` before `run_i7_and_persist()`) must be verified against VX and ZN contract series specifically. These are not separate fixes — they fall out of the A4 fix.

EURUSD is a **FX model gap** — not a fixable bug in Phase 131. HMM not trained on FX dynamics, session VWAP bands flat for 24h trading, DivergenceStack min_agreeing unreachable. Document as FX model gap; keep out of ML training corpus until FX-specific plugin tuning is addressed (future phase).

### D-06: A4 root cause confirmation — first task before any code

The research findings doc (`.planning/todos/pending/2026-06-17-phase131-research-findings.md`) explicitly marks A4 as "STILL UNCONFIRMED — one more trace needed." The spec treats it as confirmed. These are contradictory. Do not write the A4 fix until the root cause is confirmed empirically.

**Confirmation task (first task in Phase 131):** Add a single log statement in `replay_symbol()` that logs `all_features.get("asset_class")` for a rolled-contract symbol, then run a 10-symbol test replay targeting NQM6 or YMM6. If asset_class is None in the log output, root cause A4 is confirmed. Document the confirmation before proceeding.

### Claude's Discretion

- Exact query pattern for `_seed_last_events_from_db()` — use `asyncpg` with `SELECT` per (symbol, tf) batched in parallel via `asyncio.gather()`; reconstruct `IntelligenceEvent` from just the I3-tier fields needed by `extract_trend_sign()`
- Whether to add a `--no-seed` flag for testing the unseeded path — yes, add it; useful for verifying the fix by comparing before/after ctf_score distributions
- Order of A-series fixes in plans — confirm A4 first (diagnostic, 10-symbol test), then A4/A6 code fixes (simple targeted), then A7 (non-trivial DB seed), then zero-emission plugins (require A7 first for MTFAlignment verification)

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Primary Spec
- `docs/plans/2026-06-17-phases-131-133-signal-corpus-integrity.md` §"Phase 131" — full root-cause analysis, fix approaches, verification gate, all A-series and B-series items

### Research Findings (confirmed root causes)
- `.planning/todos/pending/2026-06-17-phase131-research-findings.md` — empirical DB findings; root causes for A4, A7, symbol coverage gaps, plugin zeros
- `.planning/todos/pending/2026-06-17-poc-hvn-rejection-float-nonetype.md` — A1 exact fix (already applied in commit 591fee51)

### Key Code Files
- `production/scripts/run_historical_pipeline.py:1649` — `bar_histories` deque maxlen (A-PrevDayLevel fix)
- `production/scripts/run_historical_pipeline.py:1729-1731` — `intel_*` frame injection into `frames` (A7 context)
- `src/intelligence/pipeline/feature_pipeline_executor.py:183-194` — `_last_events` construction (A7 fix location)
- `src/intelligence/confluence/cross_timeframe.py:66-150` — `compute_full()`, `other_intel` build (A7 upstream)
- `src/intelligence/confluence/confluence_weights.py:45-58` — `extract_trend_sign()` (A7 returns 0 for None)
- `src/intelligence/features/smc_context/bocpd_changepoint.py:278` — A6 look-ahead bias (one-liner fix)
- `src/intelligence/trading/i7_setups/trad_AnchoredVWAPReversion.py` — gate ordering bug

### Validation Target
- `docs/plans/phase-127-validation-report.md` — empirical corpus measurements; baseline for Phase 131 verification

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `feature_pipeline_executor.py._last_events` — the dict to seed; already uses `Dict[str, Dict[str, IntelligenceEvent]]` structure keyed by `(symbol, tf)`. Seed method inserts into this existing structure.
- `IntelligenceEvent` from `src/intelligence/schemas.py` — construct minimal instance from I3 fields only (trend_direction, trend_strength, etc.) for the DB seed; tier-code field `i3` maps to `regime_features` column

### Established Patterns
- asyncpg parallel query pattern — use `asyncio.gather()` to batch (symbol, tf) seed queries; connection pool from `database_manager.py`
- `replay_symbol()` already has a pre-loop initialization section — add seed call here before the bar event loop, not inside it

### Integration Points
- A4 fix touches `replay_symbol()` in `run_historical_pipeline.py` — add `symbol→asset_class` lookup from `contract_metadata` at the start of `replay_symbol()`, inject before calling `run_i7_and_persist()`
- A7 seed and A4 fix both modify `replay_symbol()` init section — coordinate in the same plan to avoid merge conflicts

</code_context>

<specifics>
## Specific Ideas

- Verification approach for A7: run `SELECT ctf_score, COUNT(*) FROM intelligence_features WHERE ts > NOW() - INTERVAL '1 week' GROUP BY 1 ORDER BY 1` after the 1-week sample replay. Any non-zero values confirm the fix.
- For `trad_CrossAssetDivergence` live-only annotation: add a class-level docstring note AND a `_CORPUS_EXCLUDABLE = True` marker that the verification step can query to distinguish intentional live-only plugins from bugs.

</specifics>

<deferred>
## Deferred Ideas

- FX-specific plugin tuning (EURUSD HMM, session VWAP adaptation, DivergenceStack min_agreeing) — future phase after ML baseline established
- ETF additions for retired instruments (EWZ, FXI, GDXJ, ITB, USO, VLUE) — permanently closed; replaced by better equivalents
- Wiring cross-asset context into historical replay — architecturally incorrect; live-only by design
- `--include-rolled` scope clarification for VIX/Treasury contract naming — investigate as part of A4 fix verification

</deferred>

---

*Phase: 131-signal-generation-integrity*
*Context gathered: 2026-06-17*
