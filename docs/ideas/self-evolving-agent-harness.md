# Self-evolving agent harness - Idea

**Status:** Parked 2026-11-09 by the lead (indicagent-d8), with a revisit trigger; none of the three new parts is adopted. The owner can overrule.
**Author:** Claude session, 2026-11-09, from the owner's shared description of Rakesh Gohel's self-evolving agent harness framework.
**Decision:** lead indicagent-d8, 2026-11-09 (section below).
**Informed by:** Rakesh Gohel's self-evolving agent harness (perception, reasoning, protected competence, observability, self-update); `docs/plans/2026-09-24-evidence-framework.md` (E15-E18); the agentic research loop bullet in `.planning/IDEAS.md` (2026-10-28); `scripts/research/determinism/repro_frozen.py`; `tools/gate.py`.

## Decision (2026-11-09, lead indicagent-d8)

Parked; adopt nothing now. Reasons: the two gates already exist by hand (E15-E18 for quality, `repro_frozen` plus the verify-every-landing loop for regression), as the mapping below records; the three new-if-built parts are infrastructure for failure data that does not exist yet, since the lead-worker fleet is one day old, so trajectory capture would record a sample of nothing and root-cause clustering would overfit noise, the exact risk the 2026-10-28 agentic-loop ruling names; and Musk step 1, the bottleneck is not learning from failures but running enough lanes to have any. Revisit trigger: after a few weeks of fleet operation, if the lead's manual verification loop is the bottleneck, the first build is trajectory capture alone, because diagnosis and clustering are worthless without it.

## The claim

An agent harness can detect, diagnose and fix its own failures without breaking what already works, provided every self-update earns its place through explicit gates. The loop runs perception → reasoning → planning → protection → observation → self-improvement.

## The loop

1. Input reaches a perception layer; a reasoning engine (chain-of-thought, ReAct, plan-and-execute) produces a trajectory: task, executed steps, outcome.
2. Evaluation routes it: answer directly when the goal is achieved, otherwise plan (sub-tasks) and execute again.
3. Every trajectory, decision and error signal lands in an observability layer.
4. A self-update unit reads the observability layer, rewrites prompts, tools or logic, and proposes each change as a candidate with a checkpoint.

## Protected competence

The central safety mechanism sits between a candidate update and its acceptance. Two gates, both required:

- Quality gate: the update addresses a root-cause class of failures, not one trace.
- Performance gate: no regression on the protected set of known-good capabilities.

Either gate failing rejects the update. The agent may change itself only in ways that demonstrably leave existing competence intact.

## Precise error signals

Two signals per failure, kept distinct:

- Terminal failure (what happened): the observed bad outcome.
- First divergence `t_fail` against a successful reference trajectory `t_ref` (where it broke): the earliest step at which the failed run departs from a known-good path.

Terminal failure alone invites symptom patches; divergence localization points at the step worth fixing.

## Real generalization

Improvements must target systematic failure patterns (tool-usage errors, reasoning mistakes, planning errors and premature stops, one-off cases), found by grouping failed traces by root cause rather than patching traces individually. Hardcoded answers, benchmark-specific hacks and leaked-training-data shortcuts are exactly what the gates exist to keep out.

## What this repo already does by hand

The mapping is close enough that a build would be an automation of existing practice, not a new philosophy:

| Framework element | Existing practice |
|---|---|
| Quality gate | E15-E18: admission gates that never peek at returns, count every look, select with StepM |
| Performance gate (regression protection) | `repro_frozen` bit-identical after any `src/intelligence/research/` or `statistics/` edit; pytest before commit; `tools/gate.py` |
| Observability layer | structlog service logs, OTel spans and metrics, `job_completed_total`, the research ledger as the counted record |
| Self-update unit with checkpoints | lead and worker sessions editing CLAUDE.md, memory and skills under review gates; git as the checkpoint |
| Reference trajectory `t_ref` | frozen books and preregistered specs; a rerun is compared against the recorded recipe |

## What would be new here

- Trajectory capture: session transcripts and handoff files as queryable failure traces, not just recovery artifacts.
- First-divergence diagnosis (`t_fail` vs `t_ref`) applied to agent work, not only to research determinism.
- Root-cause clustering of failed sessions (tool misuse, premature stops, wrong-altitude scope) feeding a gated change to CLAUDE.md rules, hooks or skills.

The agentic research loop ruling (2026-10-28) governs the adjacent case and applies here too: if an agent ever proposes harness edits against a score, every candidate counts as a look and the forward span stays out of the proposer's reach. A self-update accepted on a noisy quality signal is overfitting the harness.

## Open questions

- Is the quality gate ever measurable, or always a judgment call with a recorded reason (the admission-gate pattern)?
- What is the protected set for harness changes: the frozen books, the test suite, or a curated set of past session outcomes?
- Does the value justify trajectory storage beyond what sessions already leave behind?
