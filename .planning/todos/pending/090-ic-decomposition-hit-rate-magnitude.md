# 090 — IC decomposition: hit-rate × magnitude

**Source:** `docs/research/fable-2026-07-07-renaissance-layer-refinements.md` §7 (L4-4). Split out
of todo 071, which originally covered both L4-2 (empirical null calibration, now investigated —
see todo 089 and `docs/research/measurement-ic-engine.md`'s Measurement Gaps table) and this item
(L4-4, unrelated scope, still fully open). Todo 071 is closed and moved to
`.planning/todos/completed/`; this todo carries its remaining scope forward standalone.

**Priority:** medium — cheap, standalone, no schema dependency.
**Gate:** none structurally; practically wants a healthy `feature_ic_scores` table to run against.

## L4-4 — IC decomposition: hit-rate × magnitude

A single Spearman IC conflates directional accuracy (sign agreement fraction) and magnitude
alignment (are the big predictions the big moves). Two predictors with identical IC can have
opposite profiles and decay differently (magnitude alignment usually dies first as an edge
crowds). Report both as diagnostic columns (no gate change): `sign_hit_rate` and
IC-conditional-on-large-`|prediction|`. Cheap kernel additions; sharpens Phase 143's decay
monitors for free.
