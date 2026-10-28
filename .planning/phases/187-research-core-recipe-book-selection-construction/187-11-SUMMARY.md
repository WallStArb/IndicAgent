---
phase: 187-research-core-recipe-book-selection-construction
plan: 11
status: complete
completed: 2026-10-28
commits: [e193c23ae, 0a56ade9c]
requirements: [R-187-01, R-187-02, R-187-03, R-187-09, R-187-24]
---

# 187-11 summary: typed domains, recipes, research stage

- **Summary card first (e193c23ae).** The plan drops the `ensemble_strategy` domain only after a
  card covers its rows. `legacy-ensemble-champion` covers the production run, not the five
  registry rows, so `legacy-ensemble-strategy-registry` was written from the database with the
  12 annotations copied verbatim (E2's invalidated A/B, E1 deployed without a formal win).
- **Migration 530, applied live 2026-10-28** (rolled-back proof first, then the real run; the
  test database replays it too). Domains are `feature, family, member, combiner,
  construction_rule, book, method`. The 11 construction rows retyped (member 4, family 1 plus the
  five old deprecated verdicts, book 1 with its metadata kind rewritten to `book`); the five
  ensemble_strategy rows and their 5 gate, 1 transition and 12 annotation rows were deleted
  after a dump to `data/backups/187-11/`, with the counts re-checked inside the transaction
  (a baseline database with neither domain passes). `research_run.recipe_hash` and
  `instrument_classification (scheme, code)` gained covering indexes (found by the new catalog
  test); `research_construction_rule`, `research_combiner` and `research_timeframe` CVR
  namespaces seeded; `concept_research_stage` created. The 21 existing run rows are untouched.
- **Ledger and recipes.** `recipe.py` builds recipe content as a pure function (the concept
  name is hashed, unset optional fields are not, commit and author are not). `start_runs`
  writes typed identities (a pod is a book with metadata kind pod), a `concept_recipe` version
  per touched concept whose hash is new, `research_run.recipe_hash` and `informed_by`, and
  refuses an unregistered CVR code or a non-terminal informing run before any write.
  `run_spec.py --informed-by`; `research_stage.py` answers have-we-tried-this.

Deviations: the recording-ConfigService wrapper became a guard test that no research module
reads APR, plus `RunContext.apr_values` (the book's budget keys) pinned in the book recipe.
The CVR check reads `controlled_vocabulary` inside the ledger transaction instead of through
`VocabularyService`. Combiner and construction rule are concept rows but not `concept_parent`
parents of a book: the live deprecation cascade would otherwise deprecate every book when a
shared rule is deprecated; the book's recipe inputs carry the dependency instead. Review and
simplify passes were fresh-context Claude reviewers (Codex and AGY out of quota).

Open: `compare-all` waits on the running 187-03 apply. Migration 526 (todo 553) breaks the
integration baseline replay on origin (`feature_vectors_v2` missing in the baseline); reported
to 3a, and the 33 integration tests were run with that one error tolerated in an uncommitted
local conftest tweak. `ConceptRegistryService`'s ensemble_strategy path has no rows now; its
unit tests mock the database and are unchanged.
