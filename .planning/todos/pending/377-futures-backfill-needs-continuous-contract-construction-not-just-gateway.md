---
status: pending
priority: P2
filed: 2026-09-13
source: user correction during universe-expansion scoping discussion -- the assistant had
  framed the 22 empty futures/FX instruments as blocked only on `ib-gateway` being down; user
  pointed out the real blocker is roll/forward-curve construction, verified true by reading
  `scripts/ops/roll/ops_roll_batch.py` and `commodity_momentum_ts.py`
---

# Futures backfill is blocked on missing continuous-contract construction, not just the IBKR gateway

## What

The 22 registered-but-empty instruments (`.planning/STATE.md`) split into two very different
problems:

**4 FX pairs (EURUSD/GBPUSD/USDCHF/USDJPY, all IDEALPRO spot)** have no roll/expiry/curve
issue at all -- mechanically identical to backfilling an equity. Blocked only on `ib-gateway`
being up (confirmed `Exited (1)` as of 2026-09-13).

**18 futures (ES/NQ/RTY/YM/CL/NG/GC/SI/HG/VIX/VX/ZB/ZF/ZN/ZT/ZC/ZS/ZW)** need a continuous-
contract construction methodology that does not exist in this codebase:

- `scripts/ops/roll/ops_roll_batch.py` and the roll-detection design
  (`docs/plans/archive/2026-03-17-automated-roll-detection-design.md`) only handle the LIVE,
  forward case -- detecting a roll as it happens and promoting front-month in
  `contract_metadata` going forward. Nothing stitches ~20 years of expired contract-months
  (e.g. ESZ06, ESH07, ESM07, ...) into one continuous historical series.
- `contract_metadata` tracks individual roll-chain links (e.g. `ESZ6.roll_from = 'ESU6'`) --
  that's bookkeeping for the live roll, not a back-adjustment methodology for history.
- No real forward-curve/term-structure data source exists anywhere in this codebase.
  `commodity_momentum_ts.py`'s contango/backwardation regime signal is a **proxy** built from
  commodity ETF price-acceleration (OIH/XLE/GLD/DBC/etc.), explicitly documented in its own
  module docstring as an "ETF-based proxy for contango/backwardation direction" -- this exists
  precisely because no real curve data source was ever built. Worth checking whether this
  proxy is good enough to keep permanently (it's already live and used for regime labeling)
  before assuming real curve data needs to be acquired at all.

## Open questions before this can be scoped as a phase

1. **Back-adjustment methodology choice**: back-adjusted (level-shifted, preserves
   returns/momentum continuity, distorts absolute price levels across history) vs.
   ratio-adjusted vs. unadjusted-with-roll-log (preserves real levels, injects a jump at every
   roll date that will corrupt any feature computed across a roll boundary unless explicitly
   roll-aware). This is not cosmetic -- it changes every momentum/return feature computed on
   the resulting series. Needs its own design decision, likely with a written rationale given
   how much this project weighs causal-construction correctness elsewhere
   (`docs/research/platform-canonical-simulator.md`'s per-producer causal-construction laws).
2. **IBKR historical depth per expired contract-month** -- unverified. Equities have ~20 years
   via a single continuous symbol; individual expired futures contract-months are commonly
   much shallower via standard IBKR historical requests. Needs a live check (a handful of
   `reqHistoricalData` calls against specific expired contract codes) before assuming full
   equity-length history is even obtainable.
3. **Forward-curve data**: build real term-structure capture, or formally decide the existing
   ETF proxy is sufficient and stop treating "real curve data" as a to-do at all.

## Overlap check against the existing 231-symbol universe (2026-09-13, user-prompted)

Checked every proposed instrument against `instruments` for an already-present ETF proxy
before assuming any of the 18 futures / 4 FX pairs adds real breadth:

**Redundant, don't bother (14 of 22):**
- ES/NQ/RTY/YM vs. SPY/QQQ/IWM/DIA (both present) -- index futures and their tracking ETFs
  are arbitraged against the same underlying index, correlation >0.99 by construction.
- ZN/ZB/ZF/ZT vs. TLT/IEF/SHY (both present, matching duration buckets).
- GC/SI vs. GLD/SLV (both present, physically-backed, near-1:1 tracking).
- EURUSD/USDJPY vs. FXE/FXY (both present -- CurrencyShares trusts, structurally about as
  close to spot FX as an ETF gets).

**Not redundant, genuine gaps (8 of 22) -- confirmed no proxy exists:**
- CL/NG (energy): only XLE/OIH/XOP/AMLP (equity-sector) exist, not a direct commodity ETF
  (no USO/UNG/UCO/BNO in the universe) -- sector equities correlate with oil/gas price only
  loosely (equity/leverage/operational factors dilute it). Would be the first direct
  commodity-price exposure in the corpus.
- HG (copper): only DBB (industrial-metals basket: copper+aluminum+zinc) exists, no
  copper-specific proxy (no CPER/JJC) -- basket dilutes copper-specific moves. Partial overlap.
- ZC/ZS/ZW (grains): only DBA (diversified agri basket: corn+soy+wheat+sugar+coffee+
  cattle+hogs) exists, no single-grain proxy (no CORN/WEAT/SOYB) -- single-crop weather/supply
  shocks decouple from a diversified basket.
- VX (VIX futures): no vol-ETF proxy exists at all (no VXX/UVXY/SVXY/VIXY) -- `vix_z` is cash
  VIX *level*, a different signal than the futures term structure/roll yield.
- GBPUSD/USDCHF: no FXB/FXF equivalent anywhere in the universe.

**Implication for scoping:** if futures backfill is pursued at all, target the 7-instrument
list (CL, NG, HG, ZC, ZS, ZW, VX) rather than all 18 -- the continuous-contract construction
cost (methodology choice, per-contract-month IBKR depth check) is the same regardless of list
size, so building it for 7 genuinely novel exposures is a much better ROI than building it for
18 where 10 would be redundant with ETFs already in the corpus. Of the FX pairs, only
GBPUSD/USDCHF are worth adding; drop EURUSD/USDJPY from any backfill plan.

## Action

Scope as its own phase via `/gsd-discuss-phase` when futures backfill is prioritized --
not something to execute ad hoc alongside the FX backfill. Scope to the 7-futures /
2-FX-pairs targeted list above, not the full 18/4, given the redundancy findings.

## Cross-refs

- `.planning/STATE.md` Strategic Plan section -- "22 registered futures/FX instruments... have
  ZERO rows" (didn't previously distinguish FX from futures or state the roll/curve reason).
- `src/intelligence/regime_signals/commodity_momentum_ts.py` -- the ETF-proxy workaround.
- `scripts/ops/roll/ops_roll_batch.py`, `docs/plans/archive/2026-03-17-automated-roll-detection-design.md` -- existing live-only roll infra.
