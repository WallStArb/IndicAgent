---
phase: 182
status: passed
verified: 2026-09-25
---

# Phase 182 verification

Goal: every active instrument carries a dated, tiered classification that stratification, peer
grouping, reporting and onboarding read from one source of truth.

| Must-have | Evidence (live, 2026-09-25) | Result |
|---|---|---|
| Every active instrument classified (D-09) | 0 of 273 active, 0 of 295 rows without a current assignment; coverage audit `Uncovered active instruments: 0` | pass |
| Depth follows the instrument (D-05) | minimum assigned level 2 (sector); onboarding refuses level < 2 | pass |
| No history before the build date (D-07) | all valid_from = 2026-09-25; migration 368 refuses backdated or scheduled writes | pass |
| Point-in-time invariants enforced, not conventional (D-01) | 5 triggers + exclusion constraint live (367, 368); 24 live-DB integration tests pass | pass |
| One source of truth for sector (D-10) | get_active_contracts: 273 instruments, 30 level-2 sectors, 0 unclassified; no production reader of contract_details->>'sector' | pass |
| Read layer, explicit unclassified stratum (D-08) | ClassificationService tests pass; level < 1 and inconsistent paths raise | pass |
| Gates run | /simplify (654afcead), code review (10 findings: 8 fixed in 37d0b2217 and 91b4d01a9, 1 filed as todo 431, 1 relayed to phase 183 owners), full unit suite green, vulture clean | pass |

Not GitHub-CI-enforced: the integration tests (live DB, run with `--noconftest` until todo 413).
Open follow-ups: todo 431; deferred-items.md (RSPG stale contract_details name, VIX/VX duplicate
rows, invalid default session_id values in two builders, a single classification writer when
reclassification is built); research snapshot.py sector read (phase 183 owners).
