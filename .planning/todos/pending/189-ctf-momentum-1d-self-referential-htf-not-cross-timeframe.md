# 189 -- `ctf_momentum` at 1d is not a cross-timeframe feature; it's a same-tf RSI oscillator

**Filed:** 2026-07-27
**Priority:** P3 as of 2026-07-27 (was P1 at filing) -- the valuable part (doc correction,
resolving the open research question) is done same-day; remaining items are opportunistic
design/audit follow-ons, not urgent

## Finding

`docs/research/data-edge-source-thesis.md`'s T5 section flagged an "unexplained
timeframe-instability": `ctf_momentum` shows validated **positive** IC at equity/15m (Phase
167's live construction trades this) but **negative** mean IC at equity/1d (T5's 1d
replication, 2026-07-27). The doc speculated "classic short-horizon-momentum /
long-horizon-reversal... not yet confirmed."

Reading `services/backfill_feature_factory.py`'s `_CTF_HIGHER_TF` mapping (line 130) resolves
this mechanically, not statistically:

```python
_CTF_HIGHER_TF: dict[str, str] = {
    "5m": "1h",
    "15m": "1h",
    "1h": "1d",
    "1d": "1d",   # <-- self-referential
}
```

`ctf_momentum` is built by `_build_ctf_series()` as a Wilder RSI (period=`rsi_mid_period`) over
the **HTF** bars, normalized to `[-1, +1]`. For 5m/15m/1h, this is genuinely cross-timeframe:
it measures the higher timeframe's momentum context relative to the faster execution grid.

For 1d, the HTF is 1d itself -- there is no higher timeframe in the corpus at all
(`SELECT DISTINCT timeframe FROM market_data_ohlcv` returns only `1m/5m/15m/1h/1d`, no weekly
bars). So at 1d, `ctf_momentum` degenerates into a **plain same-timeframe RSI oscillator** --
a structurally different statistic than the cross-timeframe divergence measure computed at
every other tf, silently sharing the same column name and no distinguishing metadata.

This is a well-known confound: same-tf RSI is a classic short-term mean-reversion signal
(high RSI → pullback), which plausibly explains the negative 1d IC directly -- no "timeframe
instability" of one coherent feature is occurring; two different features are being compared
under one name. The 15m result Phase 167 actually trades on is unaffected (5m/15m/1h all use
a genuine, different-tf HTF).

## Why this matters

- The T5 1d replication's "`ctf_momentum` negative at 1d" comparison point is invalid as
  evidence about the *same* feature's stability across timeframes -- it was comparing apples
  (1h-context momentum) to oranges (1d self-referential RSI) and didn't know it.
- Any future construction that treats `ctf_momentum` as "the same feature, timeframe-portable"
  will get a silent wrong answer at 1d specifically -- a `CLAUDE.md` "silent wrong answer is
  worse than loud crash" violation. There's no schema flag or naming distinction warning a
  future reader.

## Recommended fix (not yet done)

1. Update `docs/research/data-edge-source-thesis.md`'s T5 section: replace the "not yet
   investigated" framing with this mechanical explanation, and correct the implied claim that
   the 1d result says anything about `ctf_momentum`'s cross-tf stability.
2. Decide on the underlying design gap: either (a) exclude 1d from any `ctf_momentum`
   cross-tf-portability claim explicitly (simplest, no code change), or (b) if 1d-scoped
   constructions actually want a real cross-timeframe momentum feature, source a genuine HTF
   (would require ingesting/deriving weekly bars -- a real new data dependency, not currently
   in the corpus) -- do not do this speculatively; only if a live 1d construction later needs
   it.
3. Audit whether any other `_CTF_HIGHER_TF`-style self-referential fallback exists for
   `ctf_vwap_align`/`ctf_regime_align` (same dict, same degenerate case at 1d) -- same root
   cause, not yet checked.

## Scope

Doc correction (item 1) is small and should happen alongside this todo's filing. Items 2/3 are
judgment calls / audits, not urgent -- no live construction currently depends on 1d's
`ctf_momentum`.

**Update 2026-07-27:** Item 1 done -- `docs/research/data-edge-source-thesis.md`'s T5 section
corrected same day. Same session also tested `ctf_momentum`'s two siblings
(`ctf_vwap_align`/`ctf_regime_align`) through the identical T3 methodology
(`scripts/analysis/t3_ctf_family_check.py`): both rejected (`ctf_vwap_align` clears the
statistical bar but dies on turnover cost; `ctf_regime_align` doesn't clear its own CI at
either scale) -- `ctf_momentum` is not one member of a productive "CTF family," recorded in
the same doc section. Items 2/3 (design decision on 1d's degenerate HTF, audit of other
self-referential fallbacks) remain open, still not urgent.
