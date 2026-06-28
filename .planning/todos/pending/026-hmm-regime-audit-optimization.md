---
**Created:** 2026-06-28
**Area:** intelligence
**Type:** optimization
**Priority:** P3
**Effort:** 3-5 days
**Benefit:** Reduces corpus pipeline runtime; optimizes HMM per-symbol compute
**Risk:** low (performance only)
**Gate:** None
---

# 026 — HMM Regime Audit & Optimization

**Priority: P0 (performance) through P4 (future) — see full plan**
**Plan:** `docs/plans/2026-06-28-hmm-regime-audit-optimization.md`

Consolidates and supersedes:
- 007-numba-jit-hmm-inference.md
- 023-hmm-parameter-lookahead-bias.md

## Summary

10 gaps across per-symbol HMM (`regime_writer.py`) and cross-sectional model (`equity_regime_model.py`). Ordered by impact:

| Priority | Finding | File |
|---|---|---|
| P0 | Numba JIT forward-filter -- 20+ hr → ~30 min | `regime_writer.py:234`, new `hmm_jit.py` |
| P1a | Expanding rank for cross-sectional VIX proxy (look-ahead bug) | `equity_regime_model.py:175` |
| P1b | TF-normalized windows for VIX z-score and 200MA | `equity_regime_model.py:75-76` |
| P2a | Multiple HMM restarts, pick max log-likelihood | `regime_writer.py:377` |
| P2b | Degenerate model detection (occupation fraction gate) | `regime_writer.py:439` |
| P2c | Regime churn feature (`hmm_churn` column) | `regime_writer.py` + migration |
| P3 | Empirical threshold calibration for vix/breadth cuts | `equity_regime_model.py` APR |
| P4a | Rolling HMM refit (parameter look-ahead bias) -- gated on P0 | `regime_writer.py` |
| P4b | Expanding StandardScaler | `regime_writer.py:375` |

See plan doc for full context, APR keys, and implementation notes.
