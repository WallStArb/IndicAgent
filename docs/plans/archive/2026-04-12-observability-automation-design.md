# Observability, alerting and automation (archived)

Date: 2026-04-12. Condensed to a stub 2026-11-14.
Outcome: partly built: base-class health signals live in `BaseDaemon`; alerting is deliberately not wired (UAT, no-op receiver).

Idea kept: Incidents went unseen for hours because nothing alerted; every daemon inherits its health signals from the base class instead of wiring them per service.

Full text: git history, `docs/plans/archive/2026-04-12-observability-automation-design.md` as of `4f6109c12`.
