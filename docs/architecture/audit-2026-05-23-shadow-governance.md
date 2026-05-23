# Shadow Governance Consistency Audit

**Date:** 2026-05-23
**Auditor:** Claude Sonnet 4.6 (automated static analysis)
**Scope:** I7 shadow governance pipeline — enrollment, gates, suppression, weight loading

---

## Executive Summary

The shadow governance system has a structurally sound design (enrollment, promotion, demotion, suppression each exist) but has three execution gaps that silently corrupt its output:

1. **`is_shadow` is never stamped on signal dicts** — every signal reaches `signal_ledger` with `is_shadow=FALSE`, making the I7 shadow tracking column permanently useless. The shadow_cache is threaded through all layers but the final stamp is missing.
2. **Promotion and demotion queries include shadow signals** — the statistical gates train on `signal_ledger` rows without filtering `is_shadow = FALSE`, so live-track data is contaminated by shadow observations that should never count toward graduation.
3. **`swarm_agent` promotion/demotion is structurally dead** — the auditor queries `signal_ledger.setup_plugin` to evaluate agents, but swarm agents are not I7 plugins and have no rows in `signal_ledger` under their `agent_id`. Both gates always see `n=0` and never fire.

---

## Finding SG-1: `is_shadow` Never Stamped on Signal Dicts

**Severity:** CRITICAL
**Category:** Alpha Leakage / Information Destruction
**Files:** `src/intelligence/pipeline/executor.py:628-710`, `services/signal_writer_agent.py:201`

**Description:**
`PluginExecutor.run_i7_complete()` threads `shadow_cache` through to `run_i7_plugins()` (line 688) but the function body at lines 570-621 never calls `self._is_shadow()` and never stamps `sig["is_shadow"]` on any output dict. The post-processing block (lines 697-710) stamps `setup_plugin`, `symbol`, `tf`, and `regime_type` but omits `is_shadow`. Downstream, `signal_writer_agent._payload_to_ledger_entries()` reads `bool(sig.get("is_shadow", False))` at line 201, which is always `False`. Every signal reaches `signal_ledger` with `is_shadow=FALSE`, even for plugins that `shadow_registry` marks `is_shadow=TRUE`.

Consequence: shadow signals are persisted as live signals. The CIS weight trainer (`weight_updater.py:389`) queries `WHERE is_shadow = FALSE` believing it trains on live-only outcomes, but it trains on all outcomes including shadow observations. This is a feedback loop contamination: shadow performance directly influences the learned weights that govern live-signal confidence scoring.

**Fix:** In `run_i7_complete` (or in the post-processing loop at lines 697-710), add `sig["is_shadow"] = self._is_shadow(task.plugin_name, cache_snapshot.shadow_cache)` after setting `sig["setup_plugin"]`.

---

## Finding SG-2: Promotion Gate Includes Shadow Observations

**Severity:** HIGH
**Category:** Feedback Loop Gap
**Files:** `services/shadow_auditor_agent.py:115-124`

**Description:**
`_check_promotion()` queries `signal_ledger WHERE setup_plugin = $1 AND outcome IS NOT NULL AND outcome NOT IN (...)` with no `AND is_shadow = FALSE` filter. Because of SG-1, all ledger rows currently have `is_shadow=FALSE`, so the filter would be a no-op today. However, the intent is for shadow-tagged signals to be excluded from the promotion population (`n >= 100` should count only live-track outcomes). If SG-1 is fixed without also fixing this query, the promotion gate will still include shadow observations.

Even with SG-1 unfixed, this is a latent bug: if `is_shadow` is ever correctly stamped on some signals (e.g., via a one-time DB correction), the promotion count `n` will silently deflate and the gate will take longer to clear than intended.

**Fix:** Add `AND is_shadow = FALSE` to the `signal_rows` query in `_check_promotion()` at line 115.

---

## Finding SG-3: Demotion Gate Includes Shadow Observations

**Severity:** HIGH
**Category:** Feedback Loop Gap
**Files:** `services/shadow_auditor_agent.py:256-265`

**Description:**
`_check_demotion()` has the same problem as SG-2: the rolling EV[R] calculation at line 256 queries `signal_ledger WHERE setup_plugin = $1 AND outcome IS NOT NULL AND ... AND signal_computed_at > NOW() - INTERVAL ...` with no `is_shadow` filter. Shadow signals — which are generated alongside live signals on every bar — inflate `n` and dilute EV[R]. A plugin demoted due to degraded live performance could appear to recover if its shadow signals happen to have better EV[R] in the lookback window.

**Fix:** Add `AND is_shadow = FALSE` to the `signal_rows` query in `_check_demotion()` at line 256.

---

## Finding SG-4: Swarm Agent Promotion/Demotion Gates Are Dead

**Severity:** HIGH
**Category:** Feedback Loop Gap
**Files:** `services/shadow_auditor_agent.py:115-124`, `services/shadow_auditor_agent.py:256-265`, `src/core/ai/base_group_service.py:162-164`

**Description:**
`_shadow_registry_ensure_agents()` enrolls swarm agents (`correlation_v1`, `counterfactual_v1`, `regime_coherence_v1`, `skeptic_v1`, `ml_scorer_v1`) with `component_type='swarm_agent'`. The shadow auditor's promotion and demotion queries then look up `signal_ledger WHERE setup_plugin = $1` using the agent's `component_name` (e.g., `"correlation_v1"`). However, `signal_ledger.setup_plugin` is populated from I7 plugin names (e.g., `"trad_TrendFollow"`). Swarm agents have no rows in `signal_ledger` under their agent IDs.

Result: every auditor run finds `n=0` for all swarm agents. `_check_promotion()` always gets `ev_r=0.0`, `ci_lower=-inf`, so `_should_promote()` always returns `False`. `_check_demotion()` always gets `ev_r=0.0` which does not breach `-0.05`, so `demotion_consecutive_count` is reset to 0 on every cycle. Swarm agents are permanently stuck in their enrolled `is_shadow` state (enrolled as `is_shadow=TRUE` at `base_group_service.py:163`). They can never be promoted or demoted via the statistical gate.

Note: `alpha_swarm_agent._evaluate_agent()` implements a separate Spearman-rho-based weight learning cycle (via `signal_lineage JOIN signal_ledger`) and updates `shadow_registry.is_shadow` directly via `_refresh_shadow_state_from_registry()`. This shadow governance path is parallel to the auditor and functions correctly. However, the auditor's demotion logic at `_check_demotion()` then resets `demotion_consecutive_count=0` on every auditor cycle (because `ev_r=0.0 > -0.05`), effectively neutralizing any auditor-side demotion tracking for swarm agents.

**Fix:** Add a component-type branch in `_run_audit()`: skip `signal_ledger` lookups for `component_type='swarm_agent'` rows (they are governed by `alpha_swarm_agent` directly). Alternatively, add `WHERE component_type = 'i7_plugin'` to the initial `shadow_registry` fetch in `_run_audit()`.

---

## Finding SG-5: CIS Weight Startup Seeding — Confirmed Working but DB-Dependent

**Severity:** MEDIUM
**Category:** Feedback Loop Gap
**Files:** `src/intelligence/pipeline/cache_manager.py:327-343`, `services/intelligence_pipeline_agent.py:266`

**Description:**
`CacheManager.load_initial()` calls `_load_cis_weights()` which reads the `cis_weights` table at startup. This is executed before `start_refresh_loops()` creates the 1800-second background loop. The ordering is correct: there is no race condition if rows exist in `cis_weights`.

However, there is a **bootstrap-forever bug** when `cis_weights` table has no rows (system is new or table was cleared): `_load_cis_weights()` finds no rows and leaves `self._cis_weights = {}`. `SignalProcessor.sync_cis_weights()` is called per bar with `weights={}` — and the `if version != self._last_synced_cis_version and weights:` guard at line 213 evaluates `weights` as falsy. So `cis_scorer.update_weights()` is never called with bootstrap defaults; the scorer continues using `BOOTSTRAP_WEIGHTS` from its `__init__`. This is correct behavior (bootstrap weights are used until learned), but the condition `and weights:` means that even after weight_updater writes a valid row, if `cis_weights_version` happens to equal `self._last_synced_cis_version` (both start at 0), the first update is silently dropped.

Specifically: `_load_cis_weights()` sets `self._cis_weights_version = int(row["version"])` from the DB row. If the DB has version=1, the cache has version=1. The SignalProcessor initializes `_last_synced_cis_version=0`. On the first bar, it calls `sync_cis_weights(weights, version=1)` where `1 != 0 and weights` is truthy, so it syncs correctly. The bug only manifests if `cis_weights` table has rows but `version` starts at 0 — which is blocked by the `MAX(version) + 1` insert logic in `_write_weights_to_db`. **The race condition described in MEMORY.md does not currently exist** for the standard code path.

The real risk is the known bug documented in MEMORY.md: if `cis_weights` table is empty (common during development resets), the pipeline silently runs bootstrap weights forever with no observability signal that learned weights were available but not applied.

**Fix:** Add a log warning in `_load_cis_weights()` when the DB query returns no rows, and add an OTel gauge `cis_weights_version_loaded` so the startup weight version is observable in Grafana.

---

## Finding SG-6: Shadow Suppression Missing from `status` Field for Shadow Plugins

**Severity:** HIGH
**Category:** Alpha Leakage
**Files:** `src/intelligence/pipeline/signal_processor.py:405-411`, `services/signal_writer_agent.py:180-184`

**Description:**
`SignalProcessor.process()` stamps `sig["status"] = "pending" if sig.get("regime_eligible", True) else "regime_suppressed"` at line 411. There is no branch for shadow-suppressed signals. A signal from a plugin marked `is_shadow=TRUE` in `shadow_registry` should receive `status="regime_suppressed"` (or a new `status="shadow_suppressed"` if desired) to prevent the lifecycle tracker from activating and tracking it as a live trade.

Currently, shadow signals flow through the full pipeline (quality gate, regime gate, calibration, ranking, winner selection) as if they are live signals. They can become the `winner` and be published to `topic_signals_aggregated`. The signal lifecycle service will then attempt to activate them and track fills, which means a plugin under evaluation in shadow mode can influence real portfolio decisions.

**Fix:** After stamping CIS fields on ranked signals (after line 418), add: `if cache_snapshot.shadow_cache.get(sig.get("setup_plugin", ""), False): sig["is_shadow"] = True; sig["status"] = "regime_suppressed"`. Also add shadow winner suppression: a signal with `is_shadow=True` should never become `winner`. In `winner_selector.py` or in `process()`, filter shadow signals from winner eligibility.

---

## Finding SG-7: Shadow Winner Suppression Not Enforced

**Severity:** CRITICAL
**Category:** Alpha Leakage
**Files:** `src/intelligence/pipeline/signal_processor.py:421-433`, `src/intelligence/pipeline/winner_selector.py`

**Description:**
`select_winner()` at line 421 selects the winning signal from the `ranked` list. It has no awareness of shadow state. If a plugin that `shadow_registry` marks as `is_shadow=TRUE` fires a high-confidence signal, it can be selected as winner and published to `topic_signals_aggregated` (the live trading aggregation topic). This signal is then consumed by the lifecycle tracker, which activates it and begins tracking it as a real trade.

The CLAUDE.md shadow governance spec states shadow signals should be "suppressed" — they should be observable for evaluation but must not influence live trading decisions. The current implementation violates this: shadow mode provides zero actual suppression of live trade routing.

**Fix:** Before calling `select_winner()`, filter shadow plugins from the candidates: `eligible_ranked = [s for s in ranked if not cache_snapshot.shadow_cache.get(s.get("setup_plugin", ""), False)]`. Pass `eligible_ranked` to `select_winner()` while preserving the full `ranked` for ledger persistence.

---

## Finding SG-8: Promotion Gate Does Not Filter `never_activated` and `ttl_expired_behind` Outcomes, But Demotion Does — Asymmetric

**Severity:** MEDIUM
**Category:** Feedback Loop Gap
**Files:** `services/shadow_auditor_agent.py:118-122`, `services/shadow_auditor_agent.py:260-262`

**Description:**
`_check_promotion()` filters `outcome NOT IN ('never_activated', 'ttl_expired_behind')` (lines 121-122). `_check_demotion()` applies the same filter (lines 261-262). This is consistent. However, `_check_demotion()` does not filter `pnl_r IS NOT NULL` explicitly before computing EV[R]. The Python code at line 268 handles this: `[float(r["pnl_r"]) for r in signal_rows if r["pnl_r"] is not None]`. If all returned rows have `pnl_r=NULL`, `n=0` and `ev_r=0.0`. The demotion threshold check then passes (0.0 > -0.05), and `demotion_consecutive_count` is reset to 0. A plugin with consistently null PnL (no fills) will never be demoted even if it's been live for months.

This is a broader issue: signals for instruments that rarely fill (low-liquidity contracts) will have mostly-null `pnl_r`, making the demotion gate permanently inactive for those plugins.

**Fix:** Add `AND pnl_r IS NOT NULL` to the demotion query at line 256. Consider also adding it to the promotion query for symmetric treatment, though the promotion query already filters by PnL-bearing outcomes at Python level.

---

## Finding SG-9: `feature_validation_compute_agent` Writes `promotion_evidence` Column That Does Not Exist in Base Migration

**Severity:** LOW
**Category:** Information Destruction
**Files:** `src/intelligence/services/feature_validation_compute_agent.py:321-329`, `production/migrations/077_shadow_governance.sql`, `production/migrations/086_validation_results.sql`

**Description:**
The base `shadow_registry` schema in migration 077 does not include `promotion_evidence`. It is added by migration 086 (`ALTER TABLE shadow_registry ADD COLUMN IF NOT EXISTS promotion_evidence JSONB`). This is correct. However, `feature_validation_compute_agent.py` lists itself as reading from `shadow_registry` in its module docstring and writes `promotion_evidence`. If migration 086 has not been applied (e.g., on a fresh environment), the UPDATE silently fails with a column-not-found error, losing validation evidence.

**Fix:** Verify migration 086 is applied in all environments. The `IF NOT EXISTS` guard makes this safe for re-runs.

---

## Governance Coverage Matrix

| I7 Signal Type | shadow_registry_ensure() | Promotion Gate | Demotion Gate | Shadow Suppression (status) | Shadow Suppression (winner) |
|---|---|---|---|---|---|
| All 36 TIER_I7 plugins | YES — via `enroll_all_plugins()` called in `_setup()` | YES — runs in `shadow_auditor_agent`, queries `signal_ledger.setup_plugin` | YES — runs in `shadow_auditor_agent` | **NO** — `is_shadow` never stamped on signals (SG-1, SG-6) | **NO** — winner can be shadow plugin (SG-7) |
| `trad_CrossAssetDivergence` | YES — in TIER_I7, enrolled by `enroll_all_plugins()` | YES | YES | **NO** | **NO** |
| Swarm agents (correlation_v1, counterfactual_v1, regime_coherence_v1, skeptic_v1, ml_scorer_v1) | YES — via `_shadow_registry_ensure_agents()` in `alpha_swarm_agent._setup()` | **DEAD** — auditor finds 0 rows in `signal_ledger` for agent IDs (SG-4) | **DEAD** — same reason (SG-4) | N/A — swarm agents modify multipliers, not status fields | N/A |
| narrative_v1 (NarrativeComputeAgent) | YES — via `_shadow_registry_ensure_agents()` in `narrative_group_compute_agent._setup()` | **DEAD** — same as swarm agents (SG-4) | **DEAD** — same (SG-4) | N/A | N/A |

---

## Summary of Fixes (Priority Order)

| Priority | Finding | File | Change |
|---|---|---|---|
| P0 | SG-7: Shadow winner can trade live | `src/intelligence/pipeline/signal_processor.py:421` | Filter shadow plugins from `select_winner()` candidates |
| P0 | SG-1: `is_shadow` never stamped | `src/intelligence/pipeline/executor.py:697-710` | Add `sig["is_shadow"] = self._is_shadow(task.plugin_name, cache_snapshot.shadow_cache)` in `run_i7_complete` post-processing loop |
| P1 | SG-6: Shadow status not set | `src/intelligence/pipeline/signal_processor.py:405-418` | After CIS stamp, set `sig["status"]="regime_suppressed"` for shadow plugins |
| P2 | SG-2: Promotion includes shadow signals | `services/shadow_auditor_agent.py:118` | Add `AND is_shadow = FALSE` |
| P2 | SG-3: Demotion includes shadow signals | `services/shadow_auditor_agent.py:259` | Add `AND is_shadow = FALSE` |
| P2 | SG-4: Swarm auditor dead | `services/shadow_auditor_agent.py:84-103` | Skip `signal_ledger` lookups for `component_type = 'swarm_agent'` |
| P3 | SG-8: Null PnL never demotes | `services/shadow_auditor_agent.py:256` | Add `AND pnl_r IS NOT NULL` to demotion query |
| P3 | SG-5: No observability on weight seeding | `src/intelligence/pipeline/cache_manager.py:538-567` | Add warn log + OTel gauge when no CIS weights found at startup |
