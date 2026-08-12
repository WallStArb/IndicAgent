---
phase: 144
slug: cross-sectional-regime-model-regime-group-planned
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-07-12
---

# Phase 144 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest (`.venv/bin/pytest`) |
| **Config file** | none dedicated — project-wide `tests/unit/` convention |
| **Quick run command** | `.venv/bin/pytest tests/unit/test_regime_signals_breadth_vol.py tests/unit/test_regime_signals_curve_credit.py tests/unit/test_cross_sectional_regime_model.py tests/unit/test_ic_engine_routing.py -v` |
| **Full suite command** | `.venv/bin/pytest tests/unit/ -q` |
| **Estimated runtime** | ~15s quick / ~4min full suite |

---

## Sampling Rate

- **After every task commit:** Run that task's own new test file (quick run command scoped to it)
- **After every plan wave:** Run `.venv/bin/pytest tests/unit/ -q` (full suite — must stay green;
  5695 passing as of Phase 143, 1 pre-existing unrelated failure tolerated:
  `test_no_smooth_or_backward_in_factory`)
- **Before `/gsd:verify-work`:** Full suite must be green
- **Max feedback latency:** ~15s (quick command)

---

## Per-Task Verification Map

No formal `REQ-XX` IDs exist for this phase (`phase_req_ids` is null). Mapped to the plan doc's
own Task structure instead, since that is this phase's actual acceptance surface.

| Task ID | Plan doc source | Wave | Requirement | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|-----------------|-----------|-------------------|-------------|--------|
| 144-01 | Task 1 (migration 229) | 1 | `regime_group` column exists, data preserved | N/A | manual SQL | `psql ... -c "\d market_regimes"` | N/A (SQL) | ⬜ pending |
| 144-02 | Task 2 (breadth_vol) | 1 | Causal rank (no look-ahead), TF-window scaling | Signal must not leak future data into past bars | unit | `.venv/bin/pytest tests/unit/test_regime_signals_breadth_vol.py -v` | ❌ W0 | ⬜ pending |
| 144-03 | Task 3 (curve_credit) | 1 | Signal direction correctness, tier bucketing | N/A | unit | `.venv/bin/pytest tests/unit/test_regime_signals_curve_credit.py -v` | ❌ W0 | ⬜ pending |
| 144-04 | Task 4 (dispatcher) | 2 | Group config parsing, symbol resolution, label assignment | N/A | unit | `.venv/bin/pytest tests/unit/test_cross_sectional_regime_model.py -v` | ❌ W0 | ⬜ pending |
| 144-05 | Task 5 (ic_engine routing) | 3 | Symbol→group routing, ambiguity detection, unrouted-symbol exclusion | Never silently defaults to `"equity"` — loud crash on ambiguity, loud log on exclusion | unit | `.venv/bin/pytest tests/unit/test_ic_engine_routing.py -v` | ❌ W0 | ⬜ pending |
| 144-05b | Task 5 (cross-sectional pooling fix) | 3 | `symbol_list` filter scopes pooled IC to peer group only (fixes confirmed contamination bug) | N/A | integration/manual | `psql` row-count spot check post-run | N/A — needs live DB | ⬜ pending |
| 144-06 | D-05 acceptance gate | 4 (post-corpus-rerun) | TLT vs. `rates` group IC separation gap (bands 0.01/0.05 per todo 026) | N/A | manual SQL | ad hoc query against `feature_ic_scores.regime_scope` — query itself is a Wave 0 deliverable (Open Question 3 from research) | N/A — queued behind 143.1-07 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `tests/unit/test_regime_signals_breadth_vol.py` — covers Task 2, **plus one new test not in
      the plan doc**: a causal-rank regression test asserting a later-window value change does not
      alter an earlier rank (mirror `test_vix_pct_rank_causal_property` from
      `tests/unit/services/test_equity_regime_model_causal.py`) — the plan doc's original
      `breadth_vol.py` code uses a non-causal whole-series `pd.rank()`, a real regression if
      copied verbatim (see 144-RESEARCH.md Common Pitfalls #1).
- [ ] `tests/unit/test_regime_signals_curve_credit.py` — covers Task 3, plan doc's version is complete.
- [ ] `tests/unit/test_cross_sectional_regime_model.py` — covers Task 4, plan doc's version is complete.
- [ ] `tests/unit/test_ic_engine_routing.py` — covers Task 5's `_build_symbol_regime_class`, plan
      doc's version is complete.
- [ ] No test framework install needed — pytest already configured and green project-wide.

*Existing infrastructure covers most requirements; the two gaps above (causal-rank test,
acceptance-gate SQL query) are the only Wave 0 additions beyond the plan doc's own test files.*

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Migration applies cleanly, `asset_class` data preserved under new column name | Task 1 | Schema DDL, not unit-testable | `PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -c "\d market_regimes"` — expect `regime_group` column, row counts unchanged |
| Dry-run label distribution sane (no single label >50% of any group/tf) | Task 4 Step 7 (plan doc) | Requires live bar data | `.venv/bin/python services/cross_sectional_regime_model.py --dry-run --tf 1d` then inspect log `distinct_labels` |
| `rates` group correctly excludes previously-contaminated `fi_*` symbols from equity cells | Task 5 (contamination fix) | Requires live DB with both groups populated | `psql` query comparing pre/post symbol membership in equity-labeled `feature_ic_scores` rows |
| D-05 Step 1 separation gate (TLT vs. rates group) | 144-CONTEXT.md D-05 | Statistical judgment call against pre-committed falsifiers (F1/F2), not a pass/fail unit test | Run query from `docs/research/fable-2026-07-07-phase144-conditioning-decision.md` §6 Input 1 protocol against post-143.1-07 corpus; compare gap to todo 026's bands |

---

## Validation Sign-Off

- [ ] All tasks have automated verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references (causal-rank test, acceptance-gate SQL)
- [ ] No watch-mode flags
- [ ] Feedback latency < 15s (quick command)
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
