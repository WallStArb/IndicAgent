---
status: pending
priority: P2
filed: 2026-11-06
source: lead (indicagent-4d), from the landing page restore (04d969f4d, 98bd25aac)
---

# Dashboard eslint crashes on its config; no dashboard code is linted

## What

`cd dashboard && npx eslint <file>` fails with "Oops! Something went wrong!" (ESLint 10.0.2, a
circular reference in `eslint.config.mjs`), in the shared checkout as in any worktree. Every
dashboard change since the ESLint 10 upgrade has shipped unlinted; tsc and `next build` still run.

## Done when

`npx eslint src` runs on the dashboard and reports real findings (fix or record them), and the
dashboard gate in the SOP includes it.
