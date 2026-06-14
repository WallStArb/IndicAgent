---
phase: 124
slug: signal-universe-integrity-cold-start-hardening
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-06-14
---

# Phase 124 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

**Scope reminder (CONTEXT D-09):** Phase 124 lands code + unit tests + a SQL sanity check on available data only. It does NOT run a full historical replay — authoritative fire-rate/edge validation is Phase 126's job. So the fire-rate SQL below is a *sanity* gate, not an *authoritative* gate.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest (project standard) |
| **Config file** | `pytest.ini` / project root config |
| **Quick run command** | `.venv/bin/pytest tests/unit/ -q` |
| **Full suite command** | `.venv/bin/pytest tests/unit/ -v` |
| **Estimated runtime** | ~60-120 seconds |

---

## Sampling Rate

- **After every task commit:** Run `.venv/bin/pytest tests/unit/ -q`
- **After every plan wave:** Run `.venv/bin/pytest tests/unit/ -v`
- **Before `/gsd:verify-work`:** Full suite must be green (ROADMAP success criterion #4)
- **Max feedback latency:** ~120 seconds

---

## Per-Deliverable Verification Map

Task IDs are assigned by the planner; rows below are keyed by deliverable so the planner can map each task into this contract.

| Deliverable | Wave | Requirement | Secure Behavior / Target | Test Type | Automated Command / Assertion | Status |
|-------------|------|-------------|--------------------------|-----------|-------------------------------|--------|
| Migration 130: promote 4 CTF columns + JSONB strip + backfill | A | QUALITY-02 | Columns added nullable; JSONB CTF keys stripped; backfill NULLIF handles null/missing/empty; single source of truth | migration up/down + SQL | `intelligence_features` has columns `ctf_score`, `ctf_trend_alignment`, `ctf_structure_alignment`, `ctf_regime_agreement`; `cross_timeframe_context` JSONB no longer carries those keys | ⬜ pending |
| feature_writer ON CONFLICT cold-start guard | A | QUALITY-02 | `DO UPDATE ... SET <4 ctf cols> WHERE intelligence_features.ctf_score IS NULL`; never `IS NULL OR = 0.0` | unit + SQL | unit test: insert row with NULL ctf_score then re-insert → CTF updated; insert row with 0.0 then re-insert → NOT overwritten (genuine neutral preserved). Per Phase 123 None-vs-0.0 semantics | ⬜ pending |
| CTF reader migration (grep-verified: `training_data.py`, `embedding.py`) | A | QUALITY-02 | All readers of CTF from JSONB read the new columns; no reader left on JSONB keys | unit + grep gate | grep for `cross_timeframe_context.*ctf_` in `src/` returns zero hits; readers return identical values pre/post | ⬜ pending |
| `--warmup` flag in run_historical_pipeline.py | A | QUALITY-02 | I1-I6-only pre-pass (skip_signals=True) runs before signal pass; additive, no plumbing conflict (skip_signals already exists in replay_symbol) | unit + CLI | `run_historical_pipeline.py --help` lists `--warmup`; with `--warmup`, two passes execute (warmup I1-I6, then signals) | ⬜ pending |
| trend_following structural rewrite | B | QUALITY-01 | Trigger re-anchored to structural entry (pullback-to-MA reversal bar / consolidation breakout); `trend_regime` demoted to context filter | unit | unit test feeds synthetic frames: continuous-trend-only → no fire; structural entry → fire once; reference SqueezeExpansion onset pattern | ⬜ pending |
| ofi_continuation structural rewrite | B | QUALITY-01 | Streak = context; trigger = fresh OFI acceleration/thrust bar on sustained imbalance | unit | synthetic streak-only → no fire; streak + acceleration bar → fire once | ⬜ pending |
| pattern_completion structural rewrite | B | QUALITY-01 | Trigger = pattern completion criterion (target reached / neckline break); instance consumed after fire (instance-ID registry, never re-fire same instance) | unit | same pattern instance → fires at most once; confidence-only crossing → no fire | ⬜ pending |
| liquidity_sweep_reclaim structural rewrite | B | QUALITY-01 | Rising-edge trigger + close-above swept level with acceptance (not a wick) | unit | rising-edge + close-above → fire; flag-stays-hot (no rising edge) → no fire; wick-only reclaim → no fire | ⬜ pending |
| anchored_vwap_reversion structural rewrite | B | QUALITY-01 | Departure (>= N ATR) + return structure + rejection/reclaim candle confirmation (not just price touching VWAP) | unit | proximity-only → no fire; departure + return + confirm → fire once | ⬜ pending |
| D6 fire-rate sanity SQL (aggregate + segmented) | B | QUALITY-01 | (1) All 5 plugins aggregate 15-30% → single digits; (2) no `setup_plugin × symbol × tf × regime` segment > ~5% | SQL diagnostic on available data | run D6 Part 1 + Part 2 (RESEARCH.md §Fire-Rate Diagnostic SQL) against `signal_ledger.setup_plugin`; expected reductions documented. NOTE: sanity only — authoritative gate deferred to Phase 126 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] No new framework — existing `pytest tests/unit/` covers all phase requirements.
- [ ] Shared synthetic-frame fixtures for the 5 plugin structural triggers (the planner/executor creates these under `tests/unit/`).

*Existing infrastructure covers all phase requirements. No Wave 0 install needed.*

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| D6 fire-rate SQL against live/corpus data | QUALITY-01 | Depends on real signal volume after a partial replay; unit tests use synthetic frames | Run D6 Part 1 + Part 2 (RESEARCH.md §Fire-Rate Diagnostic SQL) via `PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent`. Confirm all 5 plugins single-digit aggregate and no segment > ~5%. Sanity gate only; authoritative validation is Phase 126. |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 120s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
