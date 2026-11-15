---
status: pending
priority: P3
filed: 2026-11-15
source: cleanup review 2026-11-15; follow-up of 619
---

# Shrink the phase181 snapshot that repro_frozen reads

## What

`logs/phase181/snapshot_dc800360d369f4d5` is 1.3 GB and is not in git; `scripts/research/determinism/repro_frozen.py` reads it with `logs/phase179/rerun_e14` (112 MB) and two small pickles to prove the frozen verdicts are bit-identical. The check needs only the slice of the snapshot that the frozen run actually reads. The rest is dead weight, and one copy outside git is a single point of loss for the frozen-verdict guard.

## Scope

1. Record which snapshot files `repro_frozen` opens (trace the reads, do not guess).
2. Build a minimal snapshot that holds only those files, with a manifest of sha256 per file and a hash of the full original recorded first.
3. Point `repro_frozen` at the minimal snapshot; run it against both and require bit-identical output.
4. Only then delete the full snapshot, keeping the original's hash in the summary card `docs/research/summary-cards/legacy-tsmom-sleeve.md`.

## Gates

- `repro_frozen` reports bit-identical on the minimal snapshot and on the original before the original is deleted, or a recorded methodology-change entry exists.
- Standard code gate (`/simplify`, `/review`, unit suite exit code, `tests/unit/research_tools/test_repro_frozen.py`); `src/intelligence/research/` and `statistics/` untouched.
- No edit while a fingerprinted run or step 7 window imports the touched modules; do it in a detached worktree off `origin/main`.

## Boundaries

The frozen artifacts are conclusions (records). Nothing is deleted until the bit-identical proof and a second copy of the minimal snapshot exist.
