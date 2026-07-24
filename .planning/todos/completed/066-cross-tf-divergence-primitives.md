---
**Created:** 2026-07-06
**Closed:** 2026-07-24
**Area:** intelligence
**Type:** feature
**Priority:** P2
**Effort:** 1 day
**Benefit:** Adds 3 cross-timeframe return-divergence primitives to the Renaissance basket for IC discovery
**Risk:** low (additive features; IC engine prunes if no signal)
**Gate:** Phase 142.5 complete (OPEN) — deferred OUT of 142.5 by explicit scope decision
---

**Closed 2026-07-24 — content fully captured in `/gsd-plan-phase 151`.** `ret_div_1m_5m`/
`ret_div_5m_1h`/`ret_div_1h_1d` are built exactly as designed here in
`151-05-PLAN.md` (Wave 4). Confirmed via the same-day Fable review below: mechanically
identical to the already-live `ofi_div` pattern, tier-1 classification correct, no APR key
needed. Remaining work (build + IC screen) tracked under Phase 151, not this todo.

**Status (moved to deferred/, 2026-07-10):** New FeatureFactory columns meant to land in the v3.15/Phase 144 corpus-rerun batch (rides with todos 073/074/075 per the source doc's own sequencing note: batching conditioning/feature changes into one ic_engine re-run rather than burning rerun cycles piecemeal). Revive alongside that batch.

# 066 — Cross-Timeframe Divergence Primitives

**Priority: Medium — completes the Renaissance primitive basket**
**Source:** `docs/research/signal-renaissance-primitives-ohlcv.md` (Interaction Primitives → Cross-Timeframe Divergences)

---

## Context

Phase 142.5 (Renaissance Primitives) implemented 91 of the 94 spec primitives. Three were
explicitly deferred OUT with documented rationale (see `142.5-PLAN-OUTLINE.md` Scope Decisions):

| Feature | Formula |
|---|---|
| `ret_div_1m_5m` | `ret_1m_last - ret_5m_last` |
| `ret_div_5m_1h` | `ret_5m_last - ret_1h_last` |
| `ret_div_1h_1d` | `ret_1h_last - ret_1d_last` |

## Why deferred (not dropped)

These are the ONLY spec primitives requiring HTF-cache cross-timeframe coupling — they pull a
higher-timeframe bar's last return from `feature_cache.py` and difference it against the current
TF's return. Every other primitive in Phase 142.5 is a stateless single-TF per-bar transform, and
the phase deliberately kept a uniform single-TF DAG contract (`requires_htf=false` for all 91 new
rows). Cross-TF divergences would be `requires_htf=true`, clustering with the existing `ctf_*`
features. Bundling them into a dedicated cross-TF unit avoids mixing two compute surfaces in one phase.

## Scope when picked up

1. Add 3 float fields to `FeatureVector` (schemas.py); bump `_REGISTRY_ROW_COUNT` 152 → 155.
2. Compute in `FeatureFactory` by pulling HTF last-return from `feature_cache.py` (pattern: existing `ctf_*` features).
3. Add 3 columns to a new migration; seed 3 `feature_registry` rows with `requires_htf=true`,
   group_name `cross_tf`, tier `1_interaction`, parent_features set to the two per-TF returns.
4. Add `_cold_start_vector` fallbacks (0.0) and `FEATURE_VECTOR_DOMAIN` entries.
5. Add a `test_cross_tf_divergences` unit test.

No new APR keys (differences of two atomic per-TF returns, no window).

## Fable review (2026-07-24, dispatched alongside todo 123 — never independently checked before)

**Verdict: KEEP as designed, tier-1 classification confirmed correct.** Grounded against live
`feature_registry`: mechanically identical to the already-live `ofi_div` (`ofi_z -
momentum_z_fast`, a bare subtraction of two atomics, `tier=1_interaction`) — just cross-TF
instead of same-TF, no interpretive "agreement" judgment imposed. Correctly sits below the
theory-laden `ctf_momentum`/`ctf_vwap_align`/`ctf_regime_align` trio (all `tier=2_theory`
because they assert cross-TF *agreement* means something specific, not because cross-TF itself
is theory-laden). Non-redundant — `ctf_*` measure agreement, this measures magnitude divergence.

**Cross-TF DAG concern: routine, not novel.** `feature_cache.py` HTF coupling is already proven
exactly 3 times at `requires_htf=true` (the `ctf_*` features); this reuses the same plumbing,
no new architectural risk.

**Naming: correct as-is.** `1m`/`5m`/`1h`/`1d` are DAG-topology/schema identifiers (timeframe
labels), correctly exempt from naming-system.md §7's gradient-vocabulary rule — they aren't
tunable calibration parameters, they name which timeframe pair is being differenced.

**No APR key needed — the todo's own "no new APR keys" note is confirmed correct.**
