---
created: 2026-06-14T10:38:00.000Z
title: Strip extrinsic ctf_factor from detect_spike_signal confidence composite
area: intelligence
files:
  - src/intelligence/trading/microstructure_utils.py:102-111
---

## Problem

Phase 118 (`refactor(118): intrinsic-only confidence across all trading plugins`)
stripped extrinsic factors from individual plugin confidence composites, but
`microstructure_utils.detect_spike_signal` — shared by `trad_OFISpike` and
`trad_CVDSpike` — was missed.

Line 102-111:
```python
ctf_factor = clamp01((abs(ctf_score) - get_min_ctf_score()) / (1.0 - get_min_ctf_score()))
raw = 0.45 * z_score_score + 0.25 * volume_score + 0.20 * ctf_factor + 0.10 * persistence_score
```

`ctf_factor` is extrinsic (I6 cross-TF confluence) — it does not measure the
intrinsic quality of the spike itself. It violates the Phase 118 contract.

This also compounds the I6 cold-start replay bug: `ctf_score=0.0` during replay
zeros the 20% slot, depressing all spike confidence scores even after the
cold-start is fixed.

## Solution

Remove `ctf_factor` from the raw composite. Reweight the remaining 3 intrinsic
factors to sum to 1.0:

```python
# Before
raw = 0.45 * z_score_score + 0.25 * volume_score + 0.20 * ctf_factor + 0.10 * persistence_score

# After — intrinsic only
raw = 0.50 * z_score_score + 0.30 * volume_score + 0.20 * persistence_score
```

Weights are provisional — subject to ML discovery tuning. The principle is:
- z-score magnitude is the primary intrinsic signal (largest weight)
- Volume confirms the spike is real (secondary)
- Persistence (spike vs price return) confirms it's not noise (tertiary)

Update unit tests in `tests/unit/intelligence/` for OFISpike and CVDSpike
confidence calculations.

Do this fix before re-running the replay (see companion todo:
2026-06-14-fix-i6-ctf-cold-start-replay.md).
