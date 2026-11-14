# Unified I1-I7 intelligence pipeline (archived)

Date: 2026-03-29. Condensed to a stub 2026-11-14.
Outcome: built in v2.1; the v2.x I1-I7 plugin tier and signal path were deleted (plan 185-45, todo 509).

Idea kept: Compute stages run in-process and Kafka is a sink, not an inter-stage pipe (root CLAUDE.md DAG invariant 2); stateful compute checkpoints its state instead of replaying on restart.

Full text: git history, `docs/plans/archive/2026-03-29-intelligence-agent-unified-pipeline-design.md` as of `4f6109c12`.
