# Macro factor constructions from the deleted streaming services

**Status:** Idea reference. The code is deleted; this note keeps the constructions and the defects so a rebuilt version does not repeat them.
**Author:** session indicagent-02, 2026-11-14, from the code at tag `archive/futures-chain-2026-11` (local tag, commit 17eec3373, the parent of the row 5 deletion in todo 614).
**Origin:** `services/macro_analyzer.py` and `src/intelligence/macro/` were dormant streaming code. They were deleted because they persisted their own output, read futures that are not in the universe, and filled missing data with a neutral value. The macro layer is rebuilt on the batch kernels and the stored economic series (`signal-macro-context-layer.md`).

## Flight to quality

- Inputs: SPY and TLT daily-or-intraday closes, averaged simple returns over a 10-bar lookback.
- Score: `tanh(100 * (mean SPY return - mean TLT return))`, in [-1, +1]. Positive is risk-on, negative is risk-off.
- Regime: risk_on above +0.2% relative return, risk_off below -0.2%, else neutral.
- Idea not built: a third leg from VIX futures (VIX up with SPY down is strong risk-off).

## Yield curve slope

- Inputs: ZT and ZB rate-futures closes over the macro lookback window (`settings.macro_window_bars`, default 10). Proxy yield is `-log(price / 100)`; the slope is the ZT proxy minus the ZB proxy, averaged over the window, and the score is `tanh(10 * average slope)`.
- Regimes, checked in this order: inverted when the latest ZB proxy is above the latest ZT proxy, else steepening when the raw average slope is above 0.10, flattening when below -0.10, else normal. The cuts apply to the raw slope, not the score. Steepening and flattening label the slope's level, not its change.
- Weakness: a futures price is not a yield, so the proxy is not a true spread and the sign needs care. The current plan uses the stored series (the 10-year change, todo 481) instead.

## Known defects the rebuilt version must not repeat

- Missing input became a value. With fewer than 2 bars for either symbol, or too few valid returns, flight to quality returned `ftq_score = 0.0` and `ftq_regime = "neutral"`; a zero return replaced a zero previous close. Yield curve did the same: too little data returned slope 0.0 and "normal", and unparseable latest closes became 0.0 yields. This breaks `no_fill`: a missing input is NaN, never a neutral score.
- The score uses an arbitrary scale (`* 100.0` inside `tanh`) and a fixed 0.2% regime cut; a rebuilt version states its scale from the data (a z-score against a declared window) and declares any cut in a dated table.
- Returns are averaged per bar with no as-of rule; the batch kernels carry the as-of alignment (`src/intelligence/features/kernels/macro.py`), which the rebuilt version must use.
