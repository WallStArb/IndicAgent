# Multi-family book power plant (archived)

Date: 2026-11-01. Archived 2026-11-13.
Outcome: implemented the same day (todo 562, landed at `f6bbbe2e5`): per-family plants in turn,
and the book's power is the minimum over its families. The design lives in
`src/intelligence/research/runner.py` (`check_family_plant`, `family_plant`).

Idea kept: a book spanning several families is powered only if EVERY family clears its plant, so
the book-level gate takes the minimum over family plants rather than a joint pool; a strong family
cannot carry a dead one past promotion.

Full text: git history, `6f15cdde5`.
