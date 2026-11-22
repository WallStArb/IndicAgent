---
status: pending
priority: P3
filed: 2026-11-22
source: CI repair 2026-11-22 (commit 2c1a0d2b6), lead ruling to file the 38 as typing debt
---

# Typing debt: 38 mypy errors absorbed into the baseline by the CI resync

## What

The mypy step of CI runs on Python 3.13 with only the lint tools installed (no project dependencies), so numpy and pydantic types are `Any` there. The baseline had been stale since the Vulture step went red and hid the Mypy step. The resync in that environment (`2c1a0d2b6`) removed 220 resolved entries and added 38 existing errors, net 182 fewer. The 38 are real typing debt, not new bugs:

- `src/intelligence/research/construction.py`: 26
- `src/intelligence/research/spec.py`: 5
- `src/intelligence/research/runner.py`: 2
- one each in `statistics/stepm.py`, `research/snapshot.py`, `research/portfolio.py`, `bars/labels.py`, `config/settings.py`

The baseline file should only shrink (`.mypy-baseline.txt`).

## Done when

- `mypy src/ --ignore-missing-imports | mypy-baseline filter` exits 0 and `mypy-baseline sync` removes these 38 lines, run in the CI-equivalent environment (a Python 3.13 venv with only `mypy` and `mypy-baseline`; the dev venv gives misleading output).
- Research and statistics files change only with `repro_frozen` bit-identical and the battery code keys checked (a real annotation changes the AST and moves every battery code key and `code_content_key`; targeted `# type: ignore[code]  # reason` comments do not).

## Not before

No live fingerprinted run or step window imports the files; prefer batching with the next planned research edit so a code-key move happens once.
