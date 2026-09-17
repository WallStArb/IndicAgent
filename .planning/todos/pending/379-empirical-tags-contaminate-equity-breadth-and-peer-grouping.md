---
status: pending
priority: P0
filed: 2026-09-17
source: found by two independent cross-AI reviews (Codex, Fable) of a same-day fix to
  ic_engine.py's regime-group routing (commit b8af2b749) -- Fable confirmed the risk they
  flagged is not hypothetical but currently active, with live symbol-level evidence
---

# Empirical tags (source='empirical') currently contaminate equity breadth and cross-sectional peer grouping

## What

Fixing `ic_engine.py`'s regime-group routing (commit `b8af2b749`, same day) surfaced that
`instrument_tags` rows are conflated across two different meanings: `source='human'`
(curated, definitional -- "this instrument IS an equity") and `source='empirical'`
(`TagCalibrator`'s auto-measured factor-proxy correlations, persisted regardless of economic
meaningfulness or common-beta confounding). `ic_engine.py` needed a strict category answer
(exactly one regime group), so filtering to human-only tags was unambiguously correct there.

Two other live consumers read `instrument_tags` with the same no-source-filter pattern and
were NOT fixed in that commit -- confirmed by Fable to be **currently, actively wrong**, not
just theoretically at risk:

- `services/equity_regime_model.py:284-291` -- breadth-universe query:
  `EXISTS (SELECT 1 FROM instrument_tags t WHERE t.symbol = m.symbol AND (t.tag LIKE 'eq_%'
  OR t.tag LIKE 'intl_%'))`, no source filter.
- `services/cross_sectional_regime_model.py:379` -- peer-group resolution:
  `SELECT symbol, array_agg(tag) FROM instrument_tags GROUP BY symbol`, feeds the same
  `tag_filter`/`signal_tag_filter` matching, no source filter.

**Confirmed live** (Fable, 2026-09-17): GLD, AGG, EMB, EMLC, DBC, FXA, FXE (gold, aggregate
bonds, EM bonds, EM local-currency bonds, a commodity index, two FX ETFs) all carry empirical
`eq_*`-prefixed tags with zero corresponding human `eq_*` tag, and are right now being counted
into `equity_regime_model.py`'s equity breadth signal. This is the exact failure mode that
file's own docstring (lines ~275-278) already warns against for TLT ("would incorrectly
reduce breadth") -- it's arriving through a door the original author didn't anticipate
(empirical tag pollution, since `TagCalibrator` had never successfully persisted an empirical
tag before 2026-09-16, the same-day root cause behind the `ic_engine.py` fix).

## Why this is NOT the same fix as ic_engine.py's (read before patching)

`ic_engine.py`'s routing needed exactly one categorical answer -- empirical (sensitivity)
tags are structurally the wrong kind of evidence for that question regardless of how strong
or statistically significant the measured correlation is (confirmed: filtering by
`passes_fdr=true` instead of by `source` resolved 0 of that bug's 144 collisions).

`equity_regime_model.py`'s breadth signal and `cross_sectional_regime_model.py`'s peer
grouping are explicitly ABOUT sensitivity/behavioral similarity, not categorical identity --
an empirical `eq_momentum`/`equity_beta`-style tag is arguably the philosophically MORE
correct signal for "does this instrument behave like an equity for breadth-counting
purposes," not less. The reason it's currently wrong is that these tags are drowning in
common-beta noise (per the `ic_engine.py` fix's own finding: with n=250+ observations,
trivial shared-market-beta correlation reaches statistical significance easily, so
`passes_fdr=true` alone doesn't separate signal from noise here either).

A blind copy of the `source='human'`-only fix would be a **defensible stopgap** (removes the
current contamination) but is a bigger hammer than the underlying question calls for --
discards empirical sensitivity data that may have genuine value here once properly filtered
for real economic meaning (not just statistical significance) rather than presence/absence.

## Recommended next step

Scope this as its own fix, not a copy-paste:
1. Decide, deliberately: does breadth/peer-grouping want (a) human tags only as an immediate
   stopgap, or (b) a materiality-filtered empirical signal (e.g. weight above some
   economically-justified threshold, not just `passes_fdr`) as the more correct long-term
   answer? Option (a) is safe and fast; option (b) needs its own design pass.
2. Whichever is chosen, apply consistently to BOTH `equity_regime_model.py` and
   `cross_sectional_regime_model.py` -- they share the same underlying contamination.
3. Given `equity_regime_model.py`'s breadth signal likely feeds live regime classification
   used elsewhere, check blast radius (what currently reads its output) before changing it,
   same "measure twice" discipline as the `ic_engine.py` fix.

## Cross-refs

- `services/ic_engine.py`'s `_build_symbol_regime_class` (commit `b8af2b749`) -- the sibling
  fix this todo was found alongside; read its full reasoning before touching either of the two
  files named here.
- [[project_phase174_closed_cross_asset_pivot]], [[project_portfolio_covariance_weighting_diagnostic]]
  -- the VIXY/EMLC onboarding thread that led to finding this.
