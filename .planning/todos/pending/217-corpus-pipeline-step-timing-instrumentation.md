---
status: pending
priority: P2
filed: 2026-07-30
source: user mandate mid-session ("compute needs to improve") -- scoping todos 215/216
  required reconstructing step durations from `DONE in <N>s` lines scattered across
  multiple differently-named .out/.log files from restarted runs; this should be one
  queryable place instead
---

# Corpus pipeline step durations only exist as `DONE in <N>s` lines in per-run log
# files -- no durable, queryable record across runs

## Problem

`scripts/ops/corpus/ops_corpus_pipeline_run.sh` already prints `DONE in <N>s` per step
to stdout/its log file, but that's it -- no structured record survives across pipeline
restarts (this cycle alone produced `full_run_20260730_062050.out`,
`full_run_20260730_062200.out`, `resume_20260730_1225.log`, `resume_20260730_1240.log`,
each with a different subset of steps depending on `--from-step`). Answering "which
step dominates total runtime" required grep-and-reconstruct archaeology across all of
them (see todos 215/216). Every future speed investigation will hit the same tax.

## Fix

Have the orchestrator write each step's (job name, start_ts, end_ts, duration_s,
status) to a durable, queryable location -- either a row per step in a new/existing
observability table (`corpus_manifest`? check what already exists) or at minimum a
single append-only structured log file that survives `--from-step` restarts, distinct
from the per-run `.out` files. Should be cheap to add: the script already has the
timing data (`DONE in Ns` is computed from something), just needs to also persist it
structurally instead of only printing it.

## Sizing

Small, mechanical -- the timing data already exists at the print site, this just adds
a durable sink for it. Good "automate" candidate per CLAUDE.md's 5-step mandate (don't
make future investigations re-derive this by hand every time).
