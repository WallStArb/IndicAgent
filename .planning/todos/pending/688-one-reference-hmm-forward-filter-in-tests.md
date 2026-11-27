---
objective: O1
status: pending
priority: P3
filed: 2026-11-27
source: indicagent-cb review of todo 677
---

# One reference HMM forward filter in the tests

## What

The numpy reference forward filter exists twice: `tests/unit/_hmm_decode_helpers._causal_decode` and the oracle in `tests/unit/test_hmm_jit.py`. Keep one (the helper), make `test_hmm_jit.py` import it, and delete the copy, so the oracle that `alpha_pass_jit` is checked against cannot drift.

## Done when

One reference implementation; `tests/unit/test_hmm_jit.py` and `tests/unit/test_causal_hmm_decoding.py` pass with it. Tests only, outside every pin closure.
