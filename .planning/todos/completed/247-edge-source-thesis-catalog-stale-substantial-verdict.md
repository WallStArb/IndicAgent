# 247: Edge Source Thesis / catalog.md assert nonlinear_interaction_combiner "SUBSTANTIAL" -- stale vs. todo 245's finding

**Filed:** 2026-08-03
**Closed:** 2026-08-04

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

## Done, 2026-08-04

All three tfs now measured (todo 245 CLOSED same day, 1h/15m/5m all confirmed leak-driven at
90.6%/79.1%/43.8% collapse respectively, small real residual survives at every tf) -- the 15m
re-diagnostic this todo's own step 2 said to wait for has landed, so this fix uses real numbers
throughout, not a 1h-only guess.

Both docs corrected together, same session, so they can't drift back out of sync with each other:

- `docs/research/data-edge-source-thesis.md` (v2.0 -> v2.1): header Priority line, the
  "Nonlinear Interaction Combiner" section heading (was "real and substantial at 15m/1h, small at
  1d" -> now states the residual survives-but-superseded framing), and a new "Correction,
  2026-08-04" block with the full 3-tf table, inserted directly after the heading -- the original
  2026-08-03 heading text and the full historical result narrative below it are preserved
  verbatim as history, not deleted, per this project's documentation-standards convention
  (canonical docs carry their own revision history, don't silently rewrite prior claims).
- `docs/research/catalog.md`: Edge Source Thesis row updated to the same corrected characterization.

**While fixing this, found the same doc's Cross-Sectional Relative Value / Phase 167 section
carried an equally stale "PASSED, PRODUCTIONIZED AND GATED" headline** -- Phase 167's live Gate
1/Gate 2 ranks on the same leaked `ctf_momentum` column (todo 243), and a same-day diagnostic-tier
re-verification found Gate 1 now fails under the corrected join. Corrected in the same pass
(both `data-edge-source-thesis.md` and `catalog.md`), plus `docs/research/trade-construction-layer.md`
(the canonical "one doc owns the gate numbers" doc, which had zero mention of the leak before this
pass) -- not filed as a separate todo since it's the identical stale-verdict-in-a-canonical-doc
problem this todo already exists to fix, just a different section of the same investigation.
