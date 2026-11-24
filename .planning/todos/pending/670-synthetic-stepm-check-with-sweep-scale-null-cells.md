---
status: pending
priority: P1
filed: 2026-11-24
source: indicagent-3d family-order note, lead ruling 2026-11-24
---

# A synthetic StepM check with sweep-scale correlated null cells before any IC sweep

## What

E21 counts every measured IC cell as an attempt in the StepM universe. A full 1d level 1 sweep is about 277 columns x 4 horizons = 1,100 cells added to the 16 series after family 10 (24 charged rows). The correction tightens with every cell, so the sweep could drop `reversal_21` (adjusted p 0.0135 and 0.0045 on 12 series) from the selection set.

## Done when

A synthetic check, with no real-data compute and no counted look: StepM (the shipped module, the APR fwer, block mean and seed) run on the recorded 16 series plus about 1,100 correlated null cells drawn to match the feature-column correlation structure (use the stored-column correlations only after the corpus exists; before that a factor model with the observed cross-column correlation range), reporting whether `reversal_21` stays selected at its recorded t. The result sets `n_looks` for the sweep declaration. No sweep runs before this and 671.
