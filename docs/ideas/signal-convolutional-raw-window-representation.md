# Convolutional Raw-OHLCV-Window Representation — Idea

**Status:** Idea — not planned, and skeptically framed on arrival (see verdict below). Needs a
Fable rigor pass before any further consideration, and should not be promoted to
`docs/research/` on the strength of the source paper alone.
**Author:** Claude (Sonnet 5), interactive session, 2026-08-03 — not a Fable dispatch. Source
paper read in full (all 9 pages); the critique below is this session's own analysis, not the
source paper's self-assessment.
**Origin:** User request to review arXiv:2512.21804, "S&P 500 Stock's Movement Prediction using
CNN" (Rahul Gupta, Stanford), and consider whether it's worth a project idea doc.
**Extracted 2026-08-03:** the one narrow, salvageable insight (candidate causal return-path-shape
input features, tested via incremental IC over the existing 264-feature set, NOT the paper's raw
price/CNN method) was folded into `docs/research/data-edge-source-thesis.md`'s
`nonlinear_interaction_combiner` section rather than left only here -- see that doc for the
live-tracked version of the idea.

---

## What the source paper actually does

A 1D-CNN (8 conv layers + 2 fully-connected + softmax, binary cross-entropy loss) trained
**per individual stock** (not cross-sectionally) to classify next-window direction (BUY/SELL),
using a sliding window of raw daily OHLCV **and** raw adjusted-OHLCV (10 channels total:
OPEN/HIGH/LOW/CLOSE/VOLUME + ADJ_ variants) as the input "image" — no engineered features at
all, deliberately in contrast to feature-engineering-based approaches. The stated novelty is
using split/dividend-unadjusted prices *alongside* adjusted prices so the model can, in
principle, learn to recognize split/dividend events itself rather than have them pre-corrected
away. Reported validation accuracy reaches 91% on one example (JPM, 30-day horizon); other
examples shown (NVIDIA 5-day, BAC 30-day, an aggregated "Tech sector" 3-day) range ~78-86%.

Despite the arXiv-late-2025 identifier, every citation in the paper is 2015-2018 and the
methodology (single-author Stanford course-project format, built on top of a named GitHub base
repo) reads as a 2018-vintage class project, not current research. That alone isn't
disqualifying, but it sets the right expectation for how much methodological rigor to expect
before checking.

## Why this needs a skeptical read before anything else

This paper fails on exactly the axes this project already got burned on or already guards
against structurally. Not a nitpick list — each of these is independently sufficient to make
the reported numbers untrustworthy as evidence of a real edge:

1. **Raw price levels as model input is a known anti-pattern in this codebase, not a novel
   choice.** [[project_v3_feature_port_raw_price_antipattern]] — v3's `FeatureFactory` learned
   this the hard way in Phase 163: raw price levels are non-stationary and (in a cross-sectional
   context) non-comparable across symbols; only ATR-distance/percentage-normalized companions
   are ever valid measurement inputs. This paper's core method is feeding raw OPEN/HIGH/LOW/
   CLOSE directly into the network, normalized only by a single global min-max
   (`z = (x-min)/(max-min)`) computed once over 8-24 years of history per stock. Even
   per-stock (not cross-sectional), a stock's own price level drifts by an order of magnitude
   over decades — the paper's own Figure 2 shows AAPL falling from ~$650 to ~$100 across the
   2012-2018 window purely from a split, still within the same "global normalization" window.
   A single min-max scale computed once over that range does not make the input stationary
   bar-to-bar; it just rescales a moving target once. This is precisely the failure mode our own
   memory documents as already-corrected-for elsewhere in this codebase, not an open question.

2. **Train/test shuffling on overlapping sliding windows is very likely leaking future
   information into training.** "The whole dataset was discretized by using split and shuffle
   technique to process the train data discretely and prevent overfitting" (§3). For a
   single time series turned into overlapping sliding windows (window *i* and window *i+1*
   differ by one bar and share almost all their input), shuffling before the train/test split
   means near-duplicate windows routinely land on both sides of the split. This is the textbook
   time-series leakage error this project's entire walk-forward/embargo discipline
   (`ic_math.py`'s `build_walk_forward_folds`, explicit `embargo_bars` everywhere, e.g. nonlinear_interaction_combiner's own
   288-bar 5m embargo) exists to prevent. The paper never mentions an embargo or any
   walk-forward discipline at all.

3. **No cost model, no Sharpe, no economic significance check.** Classification accuracy only.
   No baseline comparison against the naive "always predict up" classifier (equity daily/monthly
   direction has a well-known positive unconditional base rate — an unstated class-imbalance
   check would be needed before 91% "accuracy" means anything).

4. **No statistical significance testing, no multiple-comparisons correction.** Four different
   (stock, horizon, learning-rate) combinations are shown with no correction for the much larger
   number of combinations that were almost certainly tried during "hyperparameter tuning and
   babysitting the model" (§ Hyperparameters Tuning lists 4 heights × 3 channel counts × 4
   learning rates × 2 optimizers × a batch-size range as the searched grid). This is exactly the
   garden-of-forking-paths problem this project's BH-FDR/day-clustered-bootstrap apparatus
   (used identically for every thesis in `docs/research/data-edge-source-thesis.md`) exists to
   catch. A single best-of-many-tries 91% number, reported without that correction, is not
   evidence of anything by this project's own standards.

5. **Split-unadjusted price channels are a data-integrity landmine, presented as a feature
   rather than examined as one.** The paper's own stated novelty (feeding raw split-unadjusted
   prices so the model "learns" splits) means the model sees a stock's price *discontinuously
   halve or double overnight* on a known calendar event, mixed into the same channel set as the
   continuous adjusted series. Whether the model is learning genuine structure or just
   memorizing "this exact instrument's split calendar" (which generalizes to nothing) is never
   tested — no held-out symbols, no held-out split events, no ablation removing the
   unadjusted channels to check if they're pulling their weight or just adding noise/overfitting
   surface. This project's own adversarial-data-error-hunt todo (052) treats corporate-action
   artifacts as exactly this kind of landmine, worth a dedicated check class of its own, not a
   free input channel.

6. **Per-stock, not cross-sectional.** Despite the title, the model is trained separately per
   stock (4 stocks/1 sector shown, not the full S&P 500 the title implies). This project's whole
   IC-engine/ensemble apparatus is built around cross-sectional, pooled measurement precisely
   because per-symbol models on ~5,000-8,000 bars of daily history have a severe small-sample
   power problem (see todo 166's 1d small-sample finding, same statistical issue at a smaller
   scale here).

## The one genuinely interesting question underneath the flawed execution

Strip away the specific (badly flawed) implementation and there is a real, distinct
Signal-Extraction question this project hasn't tested: **does letting a model learn its own
representation directly from a raw rolling multi-bar window (return-based, not price-level, and
properly causal) find structure that neither the current linear ensemble nor the already-tested
non-linear tree combiner (`nonlinear_interaction_combiner`, née nonlinear_interaction_combiner) capture from the 264 already
hand-engineered features?**

This is meaningfully different from `nonlinear_interaction_combiner`, which combines
already-engineered scalar features non-linearly (interaction structure). This candidate would
instead ask whether the *raw time-series shape* of a window (return sequence, volume sequence)
itself carries information the engineered scalar features lose — closer in spirit to how a
human chart-reader looks at candle patterns, but tested with the same rigor as everything else
on this doc.

### If this were ever pursued, what would actually need to change vs. the source paper

None of this is scoped as a plan — this is what a *rigorous* version would require, for the
record, if a future session decides it's worth the effort:

- **Inputs must be stationary, not raw price levels.** Log-returns and volume z-scores per bar,
  not OPEN/HIGH/LOW/CLOSE/ADJ_* levels. This alone removes most of finding #1 above and matches
  every existing feature in this codebase's own convention.
- **No split-unadjusted channel**, or if tested at all, only as an isolated ablation with an
  explicit falsification bar (does removing it change OOS IC materially), not baked in as an
  assumed positive.
- **Walk-forward folds with the same embargo discipline as nonlinear_interaction_combiner** (`ic_math.py`'s
  `build_walk_forward_folds`), never a shuffled train/test split.
- **Cross-sectional/pooled training**, not per-symbol, both to get real statistical power and
  because a per-symbol convolutional model reintroduces exactly the small-sample problem this
  project already has evidence about (todo 166).
- **Day-clustered bootstrap CI + BH-FDR across the full symbol set**, exactly like cross_sectional_relative_value/nonlinear_interaction_combiner/every
  other thesis, not a handful of cherry-picked (stock, horizon) examples.
- **A cost-hurdle check and cross-sectional-neutral decomposition**, matching nonlinear_interaction_combiner's own rigor
  pass, before any claim this is more than a classification-accuracy curiosity.
- **Compared directly against `nonlinear_interaction_combiner`'s existing, already-more-validated
  result on the same OOS population** — this candidate only earns its place if it beats or adds
  incrementally to what the tree combiner over engineered features already does, not just
  "learns something."

## Recommendation

**Low priority, skeptical prior.** This is not a promising lead to chase — it's a genuinely
different Signal-Extraction axis (worth naming for completeness), but it collides directly with
an anti-pattern this project already paid a real cost to learn and correct (raw price levels),
and the source paper's own reported numbers carry essentially none of the statistical weight
this project requires to treat a result as evidence. There is also a real, unresolved
operationalization gap already flagged for the *better-validated* existing non-linear thesis
(`nonlinear_interaction_combiner`) — retraining cadence, model storage/versioning
(`ensemble_trainer.py` has no story for a serialized model of any kind, see
[todo 238](../../.planning/todos/pending/238-nonlinear-interaction-combiner-ranked-cross-sectional-relative-value-pre-registration.md)) —
and this candidate would face the identical gap with a strictly weaker starting evidence base.
Not worth scoping ahead of clearing that queue. Revisit only if `nonlinear_interaction_combiner`
itself is confirmed valuable enough in production to justify the model-infrastructure
investment, at which point this becomes a natural, cheap incremental question to ask on the
same infrastructure rather than a standalone build.

## References

- Source: arXiv:2512.21804, "S&P 500 Stock's Movement Prediction using CNN," Rahul Gupta,
  Stanford University
- [[project_v3_feature_port_raw_price_antipattern]] — the directly-relevant prior institutional
  lesson this paper's core method collides with
- `docs/research/data-edge-source-thesis.md` — `nonlinear_interaction_combiner` section (the
  existing, better-validated non-linear Signal-Extraction thesis this candidate would need to
  beat, not just supplement)
- [todo 238](../../.planning/todos/pending/238-nonlinear-interaction-combiner-ranked-cross-sectional-relative-value-pre-registration.md) —
  the model-infrastructure gap any future non-linear thesis (this one included) will hit
