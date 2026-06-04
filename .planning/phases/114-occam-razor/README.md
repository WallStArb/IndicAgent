# Phase 114: Occam's Razor — Complexity-Aware Model Selection

**Status:** Planning
**Milestone:** v2.8 AI Platform & Evolvable Agents
**Last Updated:** 2026-06-03

## Objective

Implement complexity-aware model selection: for every shadow ML agent, build a simpler baseline and apply a statistical test with complexity penalty. If the baseline wins or ties, reject the complex model.

## Requirements

| ID | Title | Source |
|----|-------|--------|
| 114-OCCAM-01 | Baseline Registry | ai-occam-razor.md |
| 114-OCCAM-02 | Statistical Test Engine | ai-occam-razor.md |
| 114-OCCAM-03 | Shadow Registry Integration | ai-occam-razor.md |
| 114-OCCAM-04 | OTel Metrics & Dashboards | ai-occam-razor.md |

## Plans

| Plan | Title | Status |
|------|-------|--------|
| 114-01 | Baseline Registry + Linear/Rule Builders | Planning |
| 114-02 | Statistical Test Engine + Bootstrap CI | Planning |
| 114-03 | Shadow Registry Enhancement + Rejection Flow | Planning |
| 114-04 | OTel Metrics + Grafana Dashboard | Planning |

## Dependencies

- **Requires:** Phase 095 (Pydantic AI Agent Execution Layer) — all agents inherit from BaseAIWorker
- **Requires:** Phase 096 (Agent Registry) — ORE registered and built via YAML
- **Feeds into:** Phase 101 (Composite Fitness Function) — Occam penalty as one fitness component

## Success Criteria

- All shadow ML agents have an associated baseline
- Statistical test with bootstrap CI produces decisive winner
- Rejection automatically updates `shadow_registry.is_shadow = TRUE`
- OTel metrics emit evaluation counts, rejections, complexity ratios
- At least one complex model rejected (or validation that all are justified)

## Documentation

- Foundation principle: `docs/foundation/occam-razor.md`
- Implementation spec: `docs/ideas/ai-occam-razor.md`
- Phase context: `.planning/phases/114-occam-razor/114-CONTEXT.md`
