# Idea docs still reference the pre-2026-07-04 phase numbers — cross-reference sweep needed

**Context:** on 2026-07-04, ROADMAP.md's Phases 143-152 were renumbered into logical dependency
order (v3.15 conditioning phases moved before v3.2's AnalogEngine, since nothing past Phase
142B.1 had execution artifacts yet — a safe, purely textual pass). The mapping:

| Old | New | Phase |
|---|---|---|
| 151 | 144 | Cross-Sectional Regime Model (`regime_group`) |
| 148 | 145 | Empirical Instrument Tag Calibrator |
| 143.5 | 146 | I7 Alpha Scorer Transition |
| 144 | 147 | Alpha Scoring System + v2.x Retirement Gate |
| 145 | 148 | AnalogEngine — Embedding Substrate + Retrieval |
| 146 | 149 | AnalogEngine — IC Factory + Scoring Engine + Enrichment |
| 147 | 150 | Feature Primitives Expansion + Interaction Layer |
| 149A | 151 | DistributionDriftMonitor |
| 150 | 152 | EnsembleHealthMonitor |
| 152 | 153 | ETF Universe Expansion (58→79) |
| 149 | 154 | Alternative Data Vectors |

**Already fixed:** `ROADMAP.md` itself (full pass), `docs/research/idea-catalog.md`, and
`docs/research/2026-07-08-intelligence-lifecycle-backlog-matrix.md` (renamed from the
2026-07-01 version in a full rewrite 2026-07-08; current phase numbers throughout).

**Still stale — grep confirmed references to old numbers, not yet fixed:**
- `docs/research/data-edge-source-thesis.md` (renamed from `edge-source-thesis.md`)
- `docs/research/cross-group-lead-lag-ic.md` — **archived since this todo was filed** (now
  `docs/research/archive/cross-group-lead-lag-ic.md` per `catalog.md`'s Archived section); skip
  unless it gets un-archived
- `docs/research/platform-canonical-simulator.md` (renamed from `canonical-simulator.md`;
  ROADMAP.md's own citation to this file was separately fixed 2026-07-12, this todo's phase-number
  sweep inside the doc's prose is still outstanding)
- `docs/research/phase142-redesign-musk5step-audit.md` — **gone entirely, not just archived**
  (checked 2026-07-12: absent from both `docs/research/` and `docs/research/archive/` despite
  `catalog.md`'s Archived section claiming it was moved there — that claim itself is stale); skip
- `docs/research/intel-confluence-detection-persistence-layer.md` (v3) (renamed from
  `intel-10-confluence-detection-persistence-layer.md`)
- `docs/research/comomentum-crowding-metric.md` — **archived since this todo was filed** (old
  Cluster 1, per `catalog.md`'s Archived section); skip unless it gets un-archived
- `docs/research/intel-case-substrate.md` (renamed from `intel-13-analog-engine.md`, then again
  from AnalogEngine to CaseSubstrate per `catalog.md`)
- `docs/research/regime-multi-regime-layer.md` (renamed from `intel-12-stratification-dimension.md`;
  ROADMAP.md's own citations to this file were separately fixed 2026-07-12, prose sweep still
  outstanding)
- `docs/research/measurement-governance-monitor.md` (renamed from `intel-14-integrity-monitor.md`;
  ROADMAP.md's own citations to this file were separately fixed 2026-07-12, prose sweep still
  outstanding)
- `docs/research/concept-governance-registries.md`

**Note (2026-07-12 housekeeping audit):** of the original 10 files, 3 have since been archived
outright (skip) and the rest have been renamed at least once since this todo was filed — list
corrected above so the eventual sweep targets real, current filenames. The underlying phase-number
staleness inside each doc's prose is unchanged by this correction; still needs the actual sweep.

**Action:** for each file above, grep for `Phase 151|148|144|145|146|147|149A|150|152|149` (bare
`143.5` too) and apply the mapping table. Do NOT blind-sed — these are free-form prose, not
structured tables; check each match's context (a bare "150" or "149" may be an APR value, dollar
amount, or unrelated number, not a phase reference). The ROADMAP.md pass used a script that only
touched numbers immediately preceded by "Phase "/"Phases " to avoid exactly this risk, and still
needed 4 manual fixes afterward for slash-separated lists like "(040/148)" — expect similar
misses per file.

**Blocked on:** nothing. Low urgency — these are reference/idea docs, not the live planning
source; a stale phase number here is confusing on read, not a silent-wrong-build risk the way a
stale ROADMAP.md phase number would be. Do opportunistically, or in one batch next time any of
these docs is touched for other reasons.
