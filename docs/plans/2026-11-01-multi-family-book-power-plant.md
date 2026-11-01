# The power plant for a multi-family book (todo 562)

Status: DRAFT design note, 2026-11-01, pending the code work (the shared tree holds 491's
uncommitted src/intelligence/research/ edits; nothing here is implemented). Author: data lane
session (indicagent-93). Informed by: todo 562, 187-14's contribution accounting, the unified
design sections 4.1 and 4.2 and the pod-book grammar, glossary, and the two live plants
(`SameSlotPlant` in intraday_periodicity, `LegsPlant` in overnight_intraday).

## The decision

Per-family plants run in turn; the book's power is the minimum over its families. No joint
plant. When `check_family_plant` sees N families on one panel, it validates each family's own
`make_plant` against the shared panel, and the refusal rule requires the book to detect every
family's planted signal through the book's full pipeline (members, S7 combiner, construction)
at the pinned coefficient. The weakest family's power is the book's power.

## Why the minimum, not a joint plant

1. **The combiner cannot create power.** S7 weights are non-negative and fold-fit; they pass a
   family's signal through or dilute it. If any family's planted structure is undetectable
   through the book, the book is blind whenever that family is the only carrier, which is the
   deployment-realistic case: families matter in different regimes (segment by regime). A joint
   plant answers a different question, "can the combiner detect several families planted at
   once", and answers it optimistically: averaging members cancels member noise, so the joint
   curve would green-light a book that fails alone. The minimum is the honest bound.
2. **Certification transfers.** Each family's plant is already certified by that family's
   battery; reusing it unchanged keeps the certification valid. A joint plant is a new synthetic
   process that would need its own certification and its own entry in the battery, for one
   refusal rule.
3. **Minimal mechanism, no new concept.** Turn-taking adds a loop and a min; the alternative
   adds a new plant concept (glossary entry, spec surface, determinism surface) that duplicates
   what the per-family plants already do.
4. **It is what 187-14's accounting needs.** Leave-one-family-out and Shapley refit decompose
   the book by family anyway: LOFO's leave-one-out run IS a per-family-signal run, so the power
   check and the accounting share the same turn-taking shape and one implementation serves both.
5. **Bit-identical degeneracy.** With one family the loop runs once and the behavior is exactly
   today's: single-family books keep their verdicts and `repro_frozen` stays bit-identical.

## The pod-book half of the grammar needs nothing

The design (section 4.1) already fixes the other combination: families on different clocks
cannot share a panel and combine only at the P&L level as a pod book, whose series is the
session-level sum of its member books' E17 D_s. Each member book carries its own power check,
so a pod is powered exactly when its members are; no plant spans a pod and none should. The
`_check_book` panel/horizon guard and the pod grammar compose with the minimum rule without
new machinery.

## What the implementation owes (when the tree clears)

- `check_family_plant` drops the `len(families) != 1` refusal; it validates every family's
  module and its plant against the shared panel, and the power check runs once per family with
  that family's plant while all members read the same synthetic panel.
- The book's power is `min` over families; the refusal names the family that failed, not just
  the count.
- 187-14's stubbed test goes away; a two-family synthetic book runs `run_book` unstubbed and is
  powered or refused on its merits.
- `repro_frozen` bit-identical for every existing single-family book.
