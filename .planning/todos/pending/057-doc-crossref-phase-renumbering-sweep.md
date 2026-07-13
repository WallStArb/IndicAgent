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
- `docs/research/stratification-dimension-unification.md` (renamed from `intel-12-stratification-dimension.md`;
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

---

**Second renumbering round, 2026-07-13:** StratificationDimension Formalization was inserted as
integer Phase 145 (after briefly landing as 145.1, then 144.1 — see ROADMAP.md's Phase 145 entry
for that intermediate history), cascading every phase number 145 and above up by one, including
the previously-fixed-number IntegrityMonitor cluster (151/152 → 152/153, absorbed cleanly since
153 was free — the old ETF Universe Expansion phase number, retired 2026-07-04 per the table
above). The mapping (old → new, this round only):

| Old | New | Phase |
|---|---|---|
| 144.1 | 145 | StratificationDimension Formalization (new) |
| 145 | 146 | Empirical Instrument Tag Calibrator |
| 146 | 147 | I7 Alpha Scorer Transition |
| 147 | 148 | Alpha Scoring System + v2.x Retirement Gate |
| 148 | 149 | CaseSubstrate — Embedding + Retrieval Foundation |
| 149 | 150 | CaseSubstrate — Case Predictors + Measurement Integration |
| 150 | 151 | Feature Primitives Expansion + Theory-Motivated Interaction Layer |
| 151 | 152 | DistributionDriftMonitor |
| 152 | 153 | EnsembleHealthMonitor |
| 154 | 155 | Alternative Data Vectors |
| 155 | 156 | Portfolio State Foundation |
| 156 | 157 | Position Sizing & Risk Management |
| 157 | 158 | Live Execution Layer |
| 158 | 159 | Cost Calibration Feedback Loop + Execution Scoring |
| 159 | 160 | Concept Registry MVP |
| 160 | 161 | Controlled Vocabulary System |

**Already fixed this round:** `ROADMAP.md` (full pass, including the milestone-summary bullets
and the v3.0a IntegrityMonitor details block — a second location for 151/152 this round's sweep
had to discover, since it lives outside the narrative `### Phase N` sections the first round's
script targeted), `docs/research/2026-07-08-intelligence-lifecycle-backlog-matrix.md`,
`.planning/todos/PRIORITIES.md`, `.planning/todos/pending/111-stratification-classification.md`,
`.planning/todos/pending/056-phase146-147-v2x-retirement-stale.md` (filename kept as-is per the
first round's own precedent of not renaming files, just updating prose and noting the mismatch).

**Not yet fixed this round — same low-urgency/opportunistic treatment as the first round's list
above, now folded into one combined backlog:** every file in the original "Still stale" list
above (unchanged by this round, since none of those docs mention 145-160 in the affected range
except where already noted) plus any `pending/`/`deferred/` todo referencing old 145-152 that
wasn't already touched — spot-checked but not exhaustively swept: 077, 036, 019, 070, 097, 060,
104, 083, 026, 033, 074, 073. `completed/` todos and `docs/plans/archive/`/`docs/research/archive/`
docs are deliberately excluded from both rounds — frozen historical record, not live
cross-references; renumbering their embedded phase numbers would misrepresent what those numbers
meant at the time they were written.
