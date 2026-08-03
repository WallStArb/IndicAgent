# 247: Edge Source Thesis / catalog.md assert nonlinear_interaction_combiner "SUBSTANTIAL" -- stale vs. todo 245's finding

**Filed:** 2026-08-03

## What's wrong

`docs/research/data-edge-source-thesis.md` (top summary + § "Nonlinear Interaction Combiner" heading)
and `docs/research/catalog.md`'s Edge Source Thesis table row both currently assert
`nonlinear_interaction_combiner confirmed real, SUBSTANTIAL at 1h and 15m (the actionable tf), small
at 1d`.

That verdict was written before todo 245's 1h with/without-CTF-columns diagnostic ran (both files'
last edits predate the diagnostic CSV and the commit that recorded it -- `catalog.md` 09:09,
`data-edge-source-thesis.md` 11:20, diagnostic CSV 13:36, commit `70d48527` 14:09, same day
2026-08-03). The diagnostic found the tree's 1h effect collapses 90.6% (point_ic 0.1811 -> 0.0171)
once `ctf_momentum`/`ctf_vwap_align`/`ctf_regime_align` are excluded from the training matrix -- a
small, real, statistically significant edge survives (diff=0.0106, ci_lower=0.0064), but "SUBSTANTIAL"
is no longer an accurate characterization of the 1h result. See
[[project_ctf_momentum_leak_and_nonlinear_combiner_status]] (auto-memory) for the full chain.

## Why this wasn't fixed inline

Both docs are large, actively-evolving research documents with many interconnected claims (caveats,
falsification bars, cross-references) written by a separate concurrent thread investigating a 5m OOM
bug the same day. Rewriting the "SUBSTANTIAL" verdict correctly requires reading and reconciling that
whole section, not a one-line find/replace -- flagging here rather than guessing at a fix.

## What needs to happen

1. Re-read `data-edge-source-thesis.md`'s full Nonlinear Interaction Combiner section (~line 445-674)
   and `catalog.md`'s table row against todo 245's actual finding.
2. Decide whether "SUBSTANTIAL" downgrades to "small, real" for 1h specifically, and whether the 15m
   claim needs its own re-diagnostic (todo 245's own "what's still open" list already calls for a 15m/5m
   version of this same with/without-CTF-columns check -- that result should land before rewriting the
   15m claim, not be guessed at from the 1h result).
3. Update both docs' language together so they don't drift back out of sync.

## Priority

P2 -- doesn't block any live production path (todo 245's memory note already confirms
`ensemble_weights`/`alpha_publisher` are uncontaminated), but leaves a canonical research doc asserting
a superseded verdict, which risks someone citing "SUBSTANTIAL" as settled in a future session.
