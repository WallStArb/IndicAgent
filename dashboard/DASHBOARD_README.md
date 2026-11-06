# IndicAgent dashboard

The landing page and the read-only research cockpit for IndicAgent, an agentic quantitative
research platform. The cockpit shows what each pipeline stage holds, how fresh it is, and what
the research ledger has counted. It never writes.

## Routes

| Route | What it shows |
|---|---|
| `/` | Landing page: positioning, the triangle, principles, how an edge is found, families, retired ideas |
| `/pipeline` | Each DAG stage (ingest, feature, regime, measure, research, book): status and newest row |
| `/data` | Bar coverage per timeframe and vendor |
| `/instruments`, `/instruments/[symbol]` | Universe map and the per-name passport |
| `/concepts` | Concept lifecycle and IC evidence |
| `/research` | Runs recorded in the research ledger |
| `/books` | Frozen books (not built yet) |
| `/system` | Service health |

Data comes from the FastAPI read-only routes (`src/api/routes/`) through `src/hooks/use-api.ts`.

## Stack

Next.js 16, React 19, Tailwind 4, TypeScript 7, `motion`, shadcn/ui primitives
(`src/components/ui/`), Vitest. Kept at the same versions as the Delta Investment site.

## Copy

All landing copy lives in `src/lib/copy/landing.ts`; components only arrange it.
`tests/copy-guard.test.ts` enforces the rules: no fund or person names, no performance or
investor language, no counted-result claims, and nothing described as running that is still
being built (the agentic research loop, the forward runner, sealed shadow, capital).

## Commands

```
npx tsc --noEmit && npm run lint && npm test   # the gate
npm run build && npx next start -p <port>      # local preview
bash tools/smoke.sh <port>; node tools/overflow.mjs http://localhost:<port>
node tools/motion-check.mjs http://localhost:<port>
```

`indicagent-dashboard.service` runs `npm run build` then `npm run start` from the shared
checkout. After any package change, run `npm ci` there before restarting the service.
