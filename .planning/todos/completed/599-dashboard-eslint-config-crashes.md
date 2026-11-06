---
status: closed
priority: P2
filed: 2026-11-06
closed: 2026-11-06
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

## Outcome (2026-11-06)

Three causes, not one. (1) `FlatCompat` resolved eslint-config-next into a circular reference; the
config now imports its native flat exports. (2) eslint-plugin-react detects the React version through
APIs ESLint 10 removed; `settings.react.version` names it. (3) typescript-eslint refuses TypeScript 7
(the stack now matches Delta); `npm run lint` preloads `tools/typescript6-shim.cjs`, which serves
`@typescript/typescript6` to `require("typescript")`, while tsc and the build stay on 7. Findings: one
render-purity error (`Date.now()` in `history-chart.tsx`, now read once at mount) and one hook
dependency warning (`lanesTop`), both fixed. `npm run lint` is clean. Dashboard gate:
`cd dashboard && npx tsc --noEmit && npm run lint && npm test`.
