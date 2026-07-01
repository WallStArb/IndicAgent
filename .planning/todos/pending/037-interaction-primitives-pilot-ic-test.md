# 037 — Pilot IC Test on Hand-Picked Interaction Primitives

**Status:** pending
**Priority:** P2 — cheap, high information value, settles a real open question with existing infrastructure
**Gate:** Phase B corpus re-run complete (need a clean, corrected corpus and IC Engine to measure against)
**Concept doc:** `docs/ideas/interaction-factory.md` — this todo is the evidence-gathering step that doc's "Build Trigger" now requires before Interaction Factory itself is built

## Why

Interaction Factory (systematic combinatorial generation of ~30,000 feature-pair candidates) has an unproven premise: that atomic features are IC-saturated and second-order interaction effects are where the next real signal lives. Nothing currently establishes this. Building the full 30K-candidate sweep before checking this would risk spending significant compute on an unproven hypothesis, and a council review (2026-07-01) concluded the honest yield estimate after proper batch-FDR + partial-correlation control is likely single digits to low tens of survivors, not hundreds.

There's a cheap, already-available way to get a real empirical answer: `renaissance-primitives-ohlcv.md` already specifies ~20-30 hand-picked "Interaction Primitives" (`vol_body_product`, `price_vol_corr`, etc.) as a "reasonable starting point and sanity check." Nobody has actually measured them.

## What

1. Add the ~20-30 hand-picked interaction primitives from `renaissance-primitives-ohlcv.md` as ordinary Feature Factory columns (`domain='feature'` equivalent, same as any atomic feature) — trivial backfill cost at this scale, zero new infrastructure (no generator, no `compound_ic_scores` table, no `CompoundPrimitiveEvaluator` needed for a pilot this small).
2. Run them through the existing, already-live IC Engine — same corpus, same methodology (Spearman IC, Fisher-z CI, BH-FDR, walk-forward embargo) already applied to every atomic feature.
3. **Critical: measure incremental IC after controlling for parent atomics (partial correlation), not naive IC.** A product or ratio of two features shares substantial variance with its parents by construction — naive IC on the compound will be inflated. The real question is whether it explains variance its parents don't already explain.

## Decision rule

- **If the pilot cohort shows genuine incremental IC** (survives FDR, non-trivial after partial-correlation control) for a meaningful fraction of the ~20-30 candidates → real evidence that interaction effects carry signal in this dataset. That's the trigger condition to plan Interaction Factory's full systematic build.
- **If the pilot cohort shows near-zero incremental IC** → strong evidence against the premise. Shelve Interaction Factory outright rather than leaving it as a permanently deferred "someday" idea — a null result on the cheap, favorably-selected (hand-picked, domain-intuition-backed) cohort is a stronger signal than a null result would be on randomly-generated pairs.

## Effort

Small — 1-2 days. Mostly Feature Factory column additions + backfill; the measurement step reuses IC Engine as-is.
