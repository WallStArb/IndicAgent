---
status: pending
priority: P3
filed: 2026-11-15
amended: 2026-11-15
source: cleanup review 2026-11-15; follow-up of 619
---

# Put the frozen-verdict artifacts into the off-site backup set (shrink dropped)

## What

`scripts/research/determinism/repro_frozen.py` proves the frozen verdicts are bit-identical from `logs/phase179/rerun_e14` (112 MB) and `logs/phase181` (1.3 GB, of which `snapshot_dc800360d369f4d5/all_X.npy` is 1.1 GB). None of it is in git, and todo 618's ship set (`data/...`) does not name `logs/`, so one disk holds the only copy of the guard's inputs.

The first draft of this todo shrank the snapshot. Dropped after reading the code (Musk step 1): `verify_snapshot` recomputes a sha256 over the whole directory and the directory name is that hash (`src/intelligence/research/store.py`, a guarded module), so a minimal copy is a different artifact with a different hash and weakens the integrity guard; and the saving is 1.3 GB on a disk that is 12 percent full (1.6 TB free). The s2sig path reads only `sessions`, `sleeve_closes`, `sleeve_opens` and `meta.json` apr, but the hash check needs every file, so the weight is the price of the check.

## Scope

1. Add `logs/phase179/rerun_e14` and `logs/phase181` to the set todo 618 ships off-site, with a sha256 manifest of every file (the snapshot's own directory hash is already one).
2. In the off-site restore rehearsal (618 item 5), restore these two directories to a scratch path and run `repro_frozen` against them; require bit-identical.
3. Name the two directories in the 618 runbook as "frozen-verdict inputs, never GC'd" next to the protection list in the gotchas section "Scratch and run directories".

## Gates

- Waits on the owner's provider decision in 618; no work before it.
- `repro_frozen` reports bit-identical on the restored copy.

## Boundaries

No edit to `store.py`, `repro_frozen.py` or the snapshot. Nothing is deleted or moved.
