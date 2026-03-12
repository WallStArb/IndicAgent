# Follow up with "lik" on ML Pattern Details

**Created:** 2026-03-11
**Status:** pending
**Type:** Research/coordination
**Priority:** medium

---

## Context

Collaborator "lik" reached out on Discord offering to contribute ML classification patterns (Random Forest, KNN, SVM) they've used for years to detect profitable trading patterns. Created research doc `docs/ideas/ml-classification-pattern-recognition.md` exploring integration options.

## Open Questions from Research Doc

1. **Specific patterns:** What patterns does "lik" want to detect? Are they already covered by existing I5 patterns (RSI divergence, double top, squeeze, etc.) or new patterns?

2. **Labeled dataset:** Does "lik" have a manually labeled dataset, or should we bootstrap from existing `signal_ledger` outcomes?

3. **Regime scope:** Should ML classifier be global (all symbols) or per-symbol (symbol-specific patterns)?

4. **Real-time vs offline:** Is the goal real-time signal enrichment (Idea 1: ML Setup Confidence Booster) or offline analysis tool (Idea 3: Feature Importance Dashboard)?

5. **Evaluation criteria:** What constitutes "successful" ML integration? Win rate improvement? Reduced false signals? Latency requirements?

## Action Items

- [ ] Reach out to "lik" via Discord with link to research doc
- [ ] Ask 5 open questions above
- [ ] Clarify what "main pattern" refers to—is it a specific pattern type or a class of patterns?
- [ ] Understand if they have labeled training data or need IndicAgent to bootstrap from `signal_ledger`
- [ ] Ask about preferred integration approach (Idea 1 enrichment layer vs Idea 3 discovery tool)
- [ ] Get timeline for collaboration—when can they dedicate time to this?
- [ ] Document answers in research doc `docs/ideas/ml-classification-pattern-recognition.md`
- [ ] Based on answers, determine if we should create implementation plan or defer

## Notes

**ML Stack Context Found:**
- `docs/ideas/tech-stack.md` — Defines current stack: LLM (I8) = Ollama, ML = sklearn
- `docs/ideas/ml-learning-machine.md` — Full ML Agent stack design with library decisions:
  - Phase 1: scipy, alphalens-reloaded, evidently, tsfresh (discovery)
  - Phase 2: lightgbm, shap, optuna, statsmodels (training)
  - Phase 3: river (online learning)
  - **Current sklearn usage:** `src/intelligence/weight_updater.py` uses LogisticRegression for CIS weights
  - Random Forest, KNN, SVM would be **additional sklearn classifiers** (not AI stack changes)

**Research Doc Alignment:**
- My research (`ml-classification-pattern-recognition.md`) proposes **expanding sklearn usage** — consistent with existing ML stack
- LLM (Ollama) stays for narrative generation — not replaced by classification
- Updated research doc to reference tech-stack.md and ml-learning-machine.md explicitly

**Next refinement needed:**
- Collaborator input needed: What specific patterns? Labeled data or bootstrap from signal_ledger? Real-time or offline?
- Once answered, choose which implementation idea(s) to prioritize

## Success Criteria

- [ ] All 5 questions answered by "lik"
- [ ] Research doc updated with collaborator inputs
- [ ] Decision made on which implementation idea(s) to prioritize
- [ ] If green-light, create implementation plan via `/brainstorming` → `/writing-plans`
