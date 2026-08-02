---
status: pending
priority: P1
filed: 2026-07-30
source: user mandate mid-session ("compute needs to improve") -- step-duration audit of
  today's corpus pipeline run found this, but the process wasn't running at audit time
  so it couldn't be py-spy'd like todo 215's ic_engine finding
---

# `regime_writer.py` (corpus pipeline step 2, per-symbol GaussianHMM fit) took 13,053s
# (3h37m) in today's run -- the single largest step measured so far, but not yet
# profiled to a specific root cause

## Evidence

`logs/corpus_pipeline/full_run_20260730_062200.out`: step 2/8 (`regime_writer`) ran
06:22:01 -> 09:59:34 EDT, `DONE in 13053s`. `infra.regime_writer.workers` = 12
(ProcessPoolExecutor, one `GaussianHMM` fit per (symbol, tf) cell, `n_iter` = 200,
5D observations, `hmm_random_state` = 42 -- see `[[project_hmm_improvement_decisions]]`).
Roughly comparable total cost to todo 215's `ic_engine` finding (the pipeline's other
dominant step) -- these two steps are the corpus pipeline's actual bottleneck, not the
other 6 steps (step 3 = 2291s, step 4 = ~100-170s; steps 1/6/7/8 not yet measured this
cycle).

Unlike todo 215, this was NOT caught by a live profile -- the process had already
finished by the time this audit ran, so there's no `py-spy` stack evidence yet, only
the wall-clock total. Root cause is unconfirmed: could be inherent EM-iteration cost
(`n_iter=200` x however many symbols fail to converge and trigger the documented
same-seed retry at `n_iter*2`, see todo 108), scaler/data-prep redone per cell,
or something else entirely.

There's a separate, unrelated prior investigation into this same script,
`[[project_regime_refit_wedge]]` -- that one is about a STALL/wedge bug (workers going
to 0% CPU with no progress), not steady-state throughput. Don't conflate the two; this
todo is about normal-path cost, not the wedge.

## What to do

Next time `regime_writer.py --refit` (or a plain corpus-pipeline run) has it actively
running, `py-spy dump` several worker PIDs the same way todo 215 did, to find out
whether the EM fit itself dominates, retries are frequent enough to matter, or
something else (I/O, data prep) is the real cost. Only after that evidence exists is a
fix worth designing -- don't guess at an HMM-specific optimization without a profile,
same discipline as todo 215.

## Sizing

Investigation first (cheap, non-invasive `py-spy dump` against a live run) -- sizing
for any resulting fix depends entirely on what that finds.
