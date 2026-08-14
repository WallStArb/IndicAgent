# 309 - Triage the vulture dead-code baseline (1136 whitelisted findings)

**Filed:** 2026-08-14
**Source:** Wiring vulture into CI (`pyproject.toml`'s `[tool.vulture]`, `.github/workflows/ci.yml`'s
"Vulture (dead code)" step). Vulture was in `requirements.txt` since before this session but had
zero config, zero CI/pre-commit wiring — pure dead weight. Fixed this session: config + CI gate
added, but the entire pre-existing findings set (1136 items) was frozen into
`tools/vulture_whitelist.py` via `vulture --make-whitelist` rather than triaged by hand — same
"grandfather existing, block new" pattern this project already uses for `[tool.ruff]`'s E501
baseline. CI now blocks any *new* dead code but is silent on the existing backlog.
**Status:** pending, P2 — real value (some fraction of 1136 is genuine dead code, not false
positive), not urgent (CI gate on new code is the load-bearing protection now).

## What's in the backlog

833 unused variable / 117 unused method / 104 unused function / 52 unused attribute / 25 unused
class / 4 unused property / 1 unused import, all at vulture's default 60% confidence except 8
items at 90-100%. Spot-checking during this session found the "unused variable" bucket dominated
by a known vulture false-positive pattern: dataclass/Pydantic field declarations (e.g.
`src/intelligence/schemas.py`'s `model_config`, `rsi_bars_in_extreme`, `prior_session_low`) that
vulture can't distinguish from real unused locals because it doesn't understand attribute access
through `model_validate`/dynamic dispatch. Real dead code is almost certainly mixed in among the
false positives — not yet separated.

## Approach

Work through `tools/vulture_whitelist.py` in batches (by file or by directory), for each entry
either: (a) delete the entry + the dead code it names, or (b) confirm real via dynamic dispatch
(dataclass field, plugin registry lookup, `getattr`, pytest fixture, etc.) and leave it whitelisted
with a comment noting why. `--min-confidence 90` first pass is the highest-signal subset (currently
only 7 items — check those first, they're likeliest to be real). One already fixed this session as
a freebie found while wiring the tool: `src/intelligence/ai/context.py`'s `if False else` dead
ternary branch (100% confidence — genuinely unreachable code, not a false positive).

## Progress (2026-08-14, first triage pass)

**Baseline dropped 1136 -> 993, two real fixes landed (commits `5fffec98b`, `c1014e5be`):**

1. `[tool.vulture]`'s `exclude = ["src/intelligence/archive/*"]` was silently inert — vulture
   matches exclude patterns against absolute paths, and a pattern with no leading `*/` can never
   match one. Confirmed via a controlled test (identical 475-finding count scanning
   `src/intelligence/archive/` with and without the flag). Fixed to `"*/src/intelligence/archive/*"`,
   confirmed 0 findings post-fix, whitelist regenerated (archive/'s 155 entries no longer needed —
   genuinely excluded now, not accidentally whitelisted).
2. `BaseDaemon.last_processed_at` (property + backing field, `src/core/agent/base.py`) was
   genuinely dead, not a false positive — zero external callers anywhere in the repo, and its own
   write site was already redundantly setting the OTel gauge
   `AGENT_LAST_MESSAGE_TIMESTAMP_SECONDS` with the identical value one line below. Removed both.

**Full triage of the `unused class` category (25 items) — methodology finding, worth reading
before continuing this todo:** every item resolved to one of two buckets, no further action
needed on any of them:
- **Confirmed real usage vulture can't see** (isinstance/Protocol checks, static/classmethod
  calls, dataclass instantiation only inside a test file) — `IAIAgent`, `StateSerializer`,
  `SubscriptionManager`, `ICResult`, `StreamMerger`, `CUSUMMonitor`, `WarmupProvider`,
  `KSDriftMonitor` — all instantiated/asserted directly in a test file, just not in a way
  vulture's static analysis credits as "used."
- **Genuinely zero live callers, but archived-zone code, not a gap** — `ArchitectureViolation`,
  `PluginCallResult`, `MacroSignals`, `ShadowTransitionEvent`, `BarIntelligenceRecord`,
  `TemplateEvaluator`, `CorrelationAnalyzer`, `SkepticEvaluator`, `RegimeCoherenceAnalyzer`,
  `CounterfactualEvaluator`, `PluginValidator`, `Dag`, `DataQualityMonitor`,
  `IntelligenceJournal` — all v2.x archived plugin-system or dormant-AI-swarm code (per root
  CLAUDE.md's Architecture section), or pre-v3.0 scaffolding, never physically moved to
  `src/intelligence/archive/`. Per this project's own "Check archived before investigating" rule,
  don't chase these further — they're expected-dead, not bugs.
- **Two notable finds, same shape, worth flagging even though out of scope to fix here**:
  `FeatureRepository` (`src/persistence/repository/feature_repository.py`) and `ParityRepository`
  + `FieldViolation` (`src/persistence/repository/parity_repository.py`,
  `src/core/schemas/parity.py`) all write to `intelligence_features` — the v2.x table CLAUDE.md
  marks ARCHIVED, no live consumer since 2026-07-02 — and `ParityRepository`/`FieldViolation`
  were explicitly retired in `d22c1b3d2 feat(storage): retire shadow writer + parity auditor
  (Phase 104-02 Task 1)`. `FeatureRepository` got an unrelated "HIGH-03" maintenance fix
  (`8e070a2ec`) well after the table it targets went dead — a small signal that liveness isn't
  being re-checked before maintenance lands on old code. Not this todo's job to fix; flagging for
  whoever eventually does todo 056's decommission-in-fact pass.

**Not yet triaged**: `unused function` (104), `unused method` (117), `unused attribute` (52),
`unused variable` (833, minus a handful already resolved by the archive-exclude fix). Given the
`unused class` pass, expect the same two-bucket split to dominate — worth checking `unused
function`/`unused method`/`unused attribute` next (more likely to contain real, actionable dead
code than `unused variable`, which is mostly the known dataclass/Pydantic-field false-positive
pattern in `src/intelligence/schemas.py` specifically, 276 of the 833).

## Where

- `tools/vulture_whitelist.py` — the frozen baseline
- `pyproject.toml`'s `[tool.vulture]` — config (paths, exclude, min_confidence)
- `.github/workflows/ci.yml`'s "Vulture (dead code)" step — the gate itself
