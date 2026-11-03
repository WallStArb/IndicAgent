# eAI-style evolutionary optimization of APR parameters - retired

**Status:** Retired 2026-11-03, superseded by the unified evidence rules; not queued, will not
be built in this form. Full text in git history at this path (last substantive version
2026-08-03).

**Disposition:** the genome-as-APR-vector narrowing was the right cut, but two things since
removed the idea's foundation. First, the substrate: the fitness loop was specified to reuse
`ic_engine` and `ensemble_trainer` code paths, both deleted in phase 186; the unified design
replaced them with the research runner, where every run is recorded and counted. Second, and
decisively: under E18 every fitness evaluation is a counted look, so an evolutionary search
spends the scarcest resource, looks, fastest. Search power was never the binding constraint;
honest look budget is. A preregistered calibration study of one parameter through the runner
always dominates a breeder over the same look budget, and needs none of this machinery.

**What survives, one line:** the APR lifecycle's `ml_learned` provenance category (Phase 109)
remains designed and unimplemented; if a parameter is ever calibrated by search, it is one
preregistered optimization study through the research runner with every fit counted, not an
autonomous breeder. No component of the original sketch (agent carriers, reproduction, gene
bank) earns a build under that rule.

**Provenance:** interactive session, 2026-08-03 (original, from an owner proposal); retired
2026-11-03 under the owner's curation mandate. The original's cautionary core - todo 245's
tree exploiting a lookahead-contaminated column, one level removed into parameter space - is
already encoded structurally by the counting rules and the data lane's integrity work.
