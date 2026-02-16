# IndicAgent Development Roadmap

**Version:** 6.0.0
**Last Updated:** 2026-02-15
**Status:** I1-I6 Complete — See Current Status Document for Details

---

## Current Development Status

**Current development status and priorities are tracked in:**
**[`docs/current-status-and-priorities.md`](current-status-and-priorities.md)**

That document provides:
- **Current achievements** (I1-I6 complete, 33 plugins, 178 tests)
- **Ranked priorities** (regime models, I7 trading outputs, I8 AI intelligence)
- **Completed phases** with detailed descriptions

---

## Quick Navigation

**For current development priorities:**
[`docs/current-status-and-priorities.md`](current-status-and-priorities.md)

**For architecture details:**
[`CLAUDE.md`](../CLAUDE.md) - Project conventions and architecture overview

**For intelligence tier specifications:**
[`docs/architecture/intelligence-tiers.md`](architecture/intelligence-tiers.md) - I1-I8 framework

**For future indicator ideas:**
[`docs/plans/future-indicators-backlog.md`](plans/future-indicators-backlog.md) - Batched indicator backlog

**For historical context:**
[`docs/_archive/roadmaps-pre-cleanup/`](_archive/roadmaps-pre-cleanup/) - Previous roadmap versions

---

## Current Focus (Quick Summary)

### Next Priority: More Regime & Market Identification
- GARCH Volatility — conditional volatility forecasting
- Kalman Filter Trend — latent-state trend estimation
- Chart patterns (double top/bottom, head & shoulders, triangles/wedges)

### After That: I7 Trading Outputs — Setups & Signals
- Setup detection combining I3+I4+I5+SMC+I6 scores into actionable trade setups
- Signal generation with entry/exit/stop-loss levels
- Position sizing using HMM regime + volatility context

### Completed (February 2026):
- I1 Technical Indicators — 16 plugins with incremental compute_next()
- I2 Composite Indicators — Crossovers, slopes, distances
- I3 Market Structure — 3 plugins (swing detector, S/R, trend structure)
- I4 Context Classification — 3 plugins (volatility, trend, momentum)
- I5 Pattern Detection — 4 plugins (RSI divergence, BB squeeze, volume divergence, confluence)
- I6 Smart Money — 6 plugins (BOS/CHoCH, FVG, order blocks, liquidity sweeps, BOCPD, HMM regime)
- I6 Cross-Timeframe Confluence — 1 plugin with intelligence_cache state sharing
- Foundation Hardening — shared utils, temporal metadata, continuous scores
- Tier 2 Refactor — calculations.py + redis_streams_manager.py split into mixins
- Dead Code Removal — ~7,500 lines across three cleanup rounds
- Dependency Upgrades — pandas 3.0, redis 7.1, LangGraph 1.0, Next.js 15.5

---

**Continue to [`docs/current-status-and-priorities.md`](current-status-and-priorities.md) for detailed development plans.**
