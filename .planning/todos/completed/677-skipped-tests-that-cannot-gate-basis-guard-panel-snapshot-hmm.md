---
claimable: true
status: completed
priority: P3
filed: 2026-11-26
source: indicagent-8c test hygiene audit (lane O, lead ruling 2026-11-25)
---

# Three skips that cannot gate

## What

1. `tests/unit/intelligence/test_basis_guard_invariant.py:55`: six cases (two kernels that need the upstream `_atr_raw_padded` output, times three seeds) skip with "covered by the end-to-end checks", so the volume-basis guard invariant (todo 560) is not tested for those two kernels. Recommendation: compute the upstream atr output in `_case` with the registry's own kernel and run the same property on them; if a kernel cannot be fed that way, replace the skip with an explicit allow-list that names the kernel and the check that covers it, so a new kernel cannot join it silently.
2. `tests/unit/research/test_panel_optional_fields.py:16` and `:44`: `test_the_family1_snapshot_still_verifies_and_loads` reads an uncommitted local snapshot at a hard-coded `/home/bg/...` path and skips everywhere, including this host. Recommendation: delete it. A test that depends on a generated local artifact cannot gate; the property it guards (a panel without optional fields writes the same bytes) is covered by `test_a_panel_without_fields_writes_the_same_bytes` in the same file and by `repro_frozen`. Record the deletion in the commit message.
3. `tests/unit/test_causal_hmm_decoding.py:114`: with the pinned seed the 2-state fit degenerates, so the test skips every run and its assertion never executes. Not a one-line fix (the fixture or the assertion needs rework); recommendation: change the synthetic regime data so the fit separates, then make a degenerate fit a failure instead of a skip.

## Done when

No skip in these three places remains, or each is replaced by an allow-list with a stated covering check.

## Closed 2026-11-27 (claimed and landed by indicagent-03, reviewed by indicagent-cb)

1. Basis guard: the two kernels that read `_atr_raw_padded` (`order_blocks`, `support_resistance`) now run the property. Their intermediate inputs come from `compute_kernels(..., outputs=...)` on the full series, as production feeds them, and the test asserts their producers read no volume. All 68 cases run; the skip is gone.
2. The family 1 snapshot test is deleted (it read an untracked local artifact at a hard-coded path and always skipped). What it guarded is pinned instead by `test_a_plain_panel_store_digest_is_pinned_and_loads_without_optional_fields`: the store digest of a plain three-bar panel and the None defaults of a loaded plain panel.
3. Causal HMM: the fixture is in percent units with a second switch (fresh seed), so the fit separates and the chain is not absorbing; setup requires Viterbi to recover the known segments at 95 percent or better with each regime on at least 10 percent of bars. `test_causal_and_viterbi_differ` is removed: on separated regimes the causal filter and Viterbi rightly agree, so it only ever passed by skipping. The prefix-causality test now checks states and filtered probabilities exactly, for production `alpha_pass_jit` and the reference decoder, with cuts after each switch and inside a run of ambiguous bars where the filter is not saturated; a companion test shows the same check fails on hmmlearn's forward-backward posteriors.
4. The side finding (an absorbing fitted chain's stationary prior misdecodes bar 0) is todo 687.
