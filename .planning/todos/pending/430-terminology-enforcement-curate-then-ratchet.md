---
status: pending
priority: P1
filed: 2026-09-25
source: owner directive 2026-09-25 ("terminology aligned in docs, UX, plans, codebase, and enforced"); audit of tools/check_glossary.py the same day
---

# Terminology enforcement: curate the glossary's bans, then enforce everywhere with a ratchet

## What the audit found (2026-09-25)

1. **Most bans silently never fire.** `tools/check_glossary.py` splits `**Banned:**` lines on
   commas, so any line written with quotes or a "(use X)" note parses into fragments like
   `'"market detector'` that match nothing. 20 of 29 ban lines use that form. A corrected parse
   gives 66 ban terms and about 550 existing uses across the tree, none of them ever flagged. The
   check reports "Glossary terms clean" while enforcing a third of the rules: a silent wrong answer.
2. **Several bans are bad rules.** Some carry qualifiers no regex can check ("emitter" as
   standalone, "shadow mode" as a standalone system name, "HMM layer" as if regime IS the layer).
   "shadow mode" has 157 uses and is also a stated project principle ("shadow mode first").
   "signal ledger" collides with the real `signal_ledger` view.
3. **Multi-word bans never match identifiers.** `SignalSource` (research layer) uses the banned
   "signal source" and passes, because the identifier scan only checks single-word bans.
4. **Coverage stops at `.py` and `.md`.** Dashboard UX (`dashboard/src/**/*.ts(x)`), research
   specs (`research/specs/*.yaml`), SQL migrations and workflow files are never scanned.
5. **Only changed files are checked** (pre-commit and CI both), so a new ban never reaches
   untouched files, and nothing records how many old violations remain.
6. **The E15 research vocabulary** (book, family, predictor, clock, horizon, ...) went into the
   glossary on 2026-09-25 (commit 7e37d50ce) with no bans, so nothing enforces it yet.

## Plan (in order; each step lands green)

1. **Curate.** Split each entry's rules into `**Banned:**` (plain comma list of exact terms,
   mechanically enforced) and `**Avoid:**` (contextual guidance, not enforced). Re-decide the
   bad rules explicitly (keep "shadow mode" allowed; scope "signal ledger" to prose, not the view
   name). Add a `**Scope:**` field (path globs) for bans that apply only in one area, for
   example research-layer prose and identifiers say `predictor`, not "signal"
   (`src/intelligence/research/**`, `research/specs/**`).
2. **Make the checker strict.** A `**Banned:**` line it cannot parse fails the check (loud, not
   silent). Multi-word bans match token sequences in identifiers (`SignalSource` matches
   "signal source"). Scan `.py .md .ts .tsx .yaml .yml .sql`. Tests for each.
3. **Ratchet.** A committed baseline (`tools/glossary_baseline.json`: file, term, count). CI
   runs full-tree whenever `glossary.md`, the checker or the baseline changes, and on every PR
   for changed files; any count above baseline fails; a count below baseline fails until the
   baseline is lowered in the same commit, so cleanup is recorded.
4. **Resolve research-layer collisions first.** `SignalSource` -> `Predictor` and research
   "signal" prose -> predictor, coordinated with the phase 183 session (it is building on
   `SignalSource`; rename after 183-10 or by that session). Until then the identifier carries a
   dated baseline entry citing this todo.
5. **Symbolic codes go to CVR, not the glossary.** Clock names, construction names, family and
   member ids in research specs become `controlled_vocabulary` namespaces; the spec loader
   rejects unregistered codes (same shape as `VocabularyDriftAuditor`).
6. **Burn down the baseline** opportunistically; UX strings first (user-facing), then code,
   then docs. Archived docs stay excluded.

## Done when

The checker enforces every `**Banned:**` term in all six file types, fails loudly on an
unparseable rule, CI holds the baseline as a ratchet, the research-layer rename is done, and
research spec codes validate against CVR.
