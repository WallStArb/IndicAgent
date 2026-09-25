---
phase: 183
plan: 03
status: complete
requirements: [D-01, D-02, D-18]
---

# 183-03 summary: spec schema and git provenance

Executed inline by the orchestrator (the wave-1 executor stopped on an API limit before any
commit).

## What was built

- `spec.py`: strict, frozen, extra-forbidding pydantic models for family and book specs
  (panel, members, construction, scoring, guards, costs, combiner, power), the canonical
  sorted-key JSON hash (a book hashes its own model plus every family's canonical form),
  `load_spec_from_head` (parses `git show HEAD:<path>`, records the blob sha),
  `load_spec_from_file` (synthetic mode), `resolve_member` (refuses any path outside
  `src.intelligence.research.families.` before importing), and `ResearchEvaluationConfig`
  from `ScoringSpec.evaluation_config()`.
- `provenance.py`: `require_committed` (`git cat-file -e` then `git diff --quiet HEAD`),
  `dirty_paths`, `loaded_first_party_files`, `require_clean` (src/intelligence, research/specs
  and every loaded first-party module, untracked files included), `head_commit`, `repo_root`.

## Verification

- `test_spec.py` (16) and `test_runner_git.py` (13) pass.

## Deviations

- The plan expected YAML `no` to fail a bool field. PyYAML's safe loader reads it as False,
  which would pass silently. The spec loader is now a SafeLoader subclass with YAML 1.2
  booleans (true/false only), so `no`, `yes`, `on` and `off` stay strings and fail
  validation. It calls the loader directly rather than `yaml.safe_load`, so the plan's
  `grep safe_load` criterion is replaced by `grep SafeLoader`; `yaml.load(` still appears
  nowhere.
- `sub_periods` accepts YAML `[start, end]` lists through a before-validator; everything else
  stays strict.
