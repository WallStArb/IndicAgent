# North star: the twenty-two truths

**Version:** 1.0
**Status:** current
**Last Updated:** 2026-10-14
**Tags:** principles, north-star, evidence, culture

The invariants the work is built on, stated once in plain language and grouped. Written
2026-10-14 while rebuilding the Delta Investment Group website, where the same text is
published (without naming any firm or person, and with plainer words where this repo's
glossary has a canonical term, such as regime). Each truth is the plain statement of
rules that live in more technical form elsewhere in this repo; the "Enforced by" line
points there. `principles.md` and the other foundation docs remain the detailed source;
where they and this file disagree, fix one of them in the same commit.

The six marked **lead** are the ones the website puts first.

## What counts as true

How a result earns the right to be believed.

### 1. Proof before belief (lead)

**Intuition proposes. Measurement decides.**

We do not call anything an edge because the argument for it is good. Every idea meets the same measurement, and until it survives that measurement it does not exist as far as capital is concerned.

Anyone can be certain. Certainty is not evidence, and we build the work so that it is never asked to be.

Where it shows up: A candidate with a good story and a weak measurement waits. The story is kept with the result.

Enforced by: Promotion through UCR status (`candidate -> shadow_only -> active -> deprecated`); only `ConceptRegistryService` flips a status.

### 2. The default is no edge (lead)

**Every positive result carries the burden of proof.**

We start from the assumption that an idea predicts nothing. Markets are crowded, most inputs are public, and an edge that looks easy has usually been found and traded away already.

So we argue against every winner before it earns weight. Is it a data leak, a fluke, a lean on the market, or a cost we forgot?

Where it shows up: A strong early result is a reason to look harder for the mistake.

Enforced by: Evidence framework E15 (book as the unit of test); adversarial review cadence in `principles.md`.

### 3. Judge only what could have been traded

**We measure at prices someone could actually have had, after cost.**

A return measured at a closing price nobody could have traded at makes an idea look better than it is, especially over short horizons. We measure from a price where a trade could really have been placed, and we take the cost out.

An effect that is real but too small to survive cost is not an edge. It is an interesting fact.

Where it shows up: Entries and exits use the next opening price. A result that needs a trade that could not have happened is discarded.

Enforced by: `panel.forward_returns` targets are `ln(open[T+N+1] / open[T+1])`, market-on-open entry and exit; promotion needs positive net expectation (E18).

### 4. Only what was knowable at the time

**Nothing borrows from the future.**

We read every input as it stood at the moment it describes: which securities existed, how they were classified, what kind of market it was, and the data itself. Anything that could only have been known later stays out of the test.

That applies to labels as much as to prices. A regime label decided by looking at what came next is a leak, however convenient it is.

Where it shows up: A sector label from today is never used to explain a year when the company was classified differently.

Enforced by: Research invariants `temporal_integrity` and `point_in_time` (universe, classification, tags, APR as of t); causal regime labels only.

### 5. Unseen data is spent once (lead)

**Searching is a screen. Confirmation happens once, on data nobody has searched.**

Data we have searched cannot also confirm. Results on it only decide which ideas deserve a real test. The real test is a single run on data nobody has looked at, applied to the whole book, meaning every idea together and how they are combined, not to a favorite.

Because that data can be used only once, we protect it. Going back to it after a disappointing answer is how weak ideas get through.

Where it shows up: A book is frozen before its test, and the verdict is recorded whichever way it falls.

Enforced by: E15 to E18: one confirmation of a frozen book on its own unsearched forward span.

### 6. Every look is counted

**Each pass over the data spends some credibility.**

Test enough ideas on the same history and some will look good by chance. So we record every look, and the bar for what counts as real rises with the number of looks.

We correct for selection too. The best of many is biased upward simply by being the best.

Where it shows up: An idea reopened under a new name counts as another look, not a fresh start.

Enforced by: E18: every look at the vintage is counted; selection by Romano-Wolf StepM.

### 7. We do not run tests that cannot answer

**Some questions cannot be settled with the data at hand.**

Sometimes the effect is too small or the history too short for any result to mean anything. We refuse those tests before a number exists.

Neighboring observations share information, so we count independent observations, not rows of data. Knowing takes time, and we say how much.

Where it shows up: A test whose method could not detect the effect it is looking for is rejected at the design stage.

Enforced by: E15: no underpowered test runs; power is checked before any real-data statistic. Non-overlapping observation windows.

### 8. Measure outcomes, not activity

**Ideas tested and features built are not results.**

A measure that becomes a target stops being a good measure. We judge the work on outcomes, on what an idea added once the market is removed, never on how much was produced.

Most of what gets built is wrong. Building got cheaper. Finding out that it is wrong did not.

Where it shows up: We never report the number of new ideas as progress.

Enforced by: Outcome metrics only; see `product-laws.md` (Goodhart).

## Where edge comes from

What we look for, and what we refuse to assume.

### 9. Edge is discovered, not designed

**A person proposes what to measure. The data decides what predicts.**

Nothing in the work encodes someone's theory of what a good setup looks like. People propose measurements from many directions, and the data decides which ones predict and which combinations matter.

For any design choice we ask who decides what matters here. If the answer is the researcher, the choice is wrong.

Where it shows up: A pattern someone named by hand is never allowed to define what counts as confirmation.

Enforced by: Families enter a book by pre-registration and mechanical guards, never by an outcome screen; the combiner sets member weights.

### 10. Many small edges, combined (lead)

**No single measurement is the insight.**

Each measurement predicts a little. The edge is in the combination of many, weighted by the data. A hundred views that move together are worth far less than a hundred independent ones.

Agreement only counts between sources that could have disagreed. Two measures of the same thing confirm nothing.

Where it shows up: Several readings of the same price move are weighed as one view, not several.

Enforced by: The walk-forward combiner over many registered family members; effective-N for correlated sources.

### 11. Every edge has a counterparty (lead)

**We name who is on the other side, and why they are wrong.**

A lasting edge comes from better information, better processing, someone who has to trade for reasons other than price, a behavior that persists, or a risk others will not carry. Every family of ideas we study states which one, and who pays.

A reward for carrying risk is called a reward for carrying risk. It is not skill.

Where it shows up: Every family on the research page names its counterparty and what would make it stop paying.

Enforced by: `docs/research/data-edge-source-thesis.md`: every construction names its counterparty.

### 12. The market is taken out

**A result is what is left once the tide is removed.**

A rising market lifts everything and a falling one sinks everything. A result that is mostly the market is not skill. We judge results on what remains after the market and other common moves are removed.

That is the only version of a result that can be compared from one year to the next.

Where it shows up: A book that wins only when the market rises is exposure, not edge.

Enforced by: S1 residualized targets remove the common component before measurement.

### 13. Stability counts as much as size

**A small edge that holds beats a large one that comes and goes.**

A large result that shows up one month and vanishes the next is weaker than a small one that is there every month. Weight follows the one that holds.

We measure stability on separate, non-overlapping stretches of time, so a lucky run cannot pass for it.

Where it shows up: Two ideas with the same average are not equal if one of them swings.

Enforced by: Stability measured on non-overlapping windows; IC Sharpe over raw IC.

### 14. Condition on context, never discard it

**Every claim carries the kind of market it was measured in.**

Markets change, and a rule that works in one kind of market can fail in another. We take every measurement within a regime, and every weight is specific to that regime.

We throw nothing away for looking wrong. An observation from the wrong kind of market is information about where a rule does not hold.

Where it shows up: A measure that works in calm markets is not allowed to act in stressed ones.

Enforced by: Regime is a conditioning variable for measurement, not a gate (`docs/concepts/regime-awareness.md`).

## How the practice runs

The habits that keep the work honest as it grows.

### 15. Influence is earned and can be lost (lead)

**Weight follows the evidence, and goes when the evidence goes.**

No idea has influence by default. An idea earns weight with proof, and the work is designed to take that weight away when the measured edge fades, without anyone having to notice.

Getting weight back is harder than losing it. A cut weight returns only on a fresh block of independent evidence, so the work follows real change and does not swing on noise.

Where it shows up: By design, a fading idea is cut first and has to prove itself again to come back.

Enforced by: UCR lifecycle with decay and hysteresis: recovery needs a new block of independent observations.

### 16. What was turned down is data

**We keep what we refused, and study what failed.**

We keep the ideas we declined, along with what happened next. A system that studies only what it acted on never learns where the line between taking and leaving should be.

We measure everything everywhere, not only where we expected it to work. A result seen only where a hand-made filter fired is confirmation bias. A failure is a reason to redesign, not to patch.

Where it shows up: A rejected idea can come back later with its full history attached.

Enforced by: Rejected candidates and frozen verdicts are kept in the research ledger and `research_run`; raw capture keeps every vendor row.

### 17. Nothing is overwritten

**Every result can be reproduced.**

Raw data is permanent. A correction is added as a new record, and missing data stays missing; we never invent values to fill a gap. Any result can be rebuilt exactly from the data, the code and the specification it came from.

The reason an idea was retired lives in a record, not in someone's memory. Years later, the question of why it was dropped still has an answer.

Where it shows up: Every setting is a versioned record that says who changed it and why.

Enforced by: Research invariants `determinism`, `lineage` and `no_fill`; raw data is permanent; every APR change has `changed_by` and `reason`.

### 18. Every source clears the same bar

**A new kind of data gets no exemption.**

What we test is the book: the ideas in it, how they are combined, and the rule that turns a forecast into positions. There is one forecast for each security at each moment, not competing ones.

We pay for data only after it shows that it predicts, and stale information fades to neutral. A source is not trusted for being expensive or exciting.

Where it shows up: A new kind of data goes through the same measurement every other kind passed.

Enforced by: One forecast per (symbol, timeframe, bar); every new information domain clears the same measurement.

### 19. The vocabulary is the model

**A term has one meaning, because a loose word hides a loose idea.**

Every name we use is held to a test: an expert who has never seen the work should be able to tell what a thing is from its name. Where two terms could mean the same thing, we retire one.

Precise language is precise thinking, so we treat the vocabulary as part of the model.

Where it shows up: When the code and the glossary disagree, the glossary wins.

Enforced by: `naming-system.md` and `glossary.md`; the glossary wins over code on collision.

### 20. Question first, delete second, simplify third

**Speed and automation come last.**

Before improving a step, we ask whether it should exist at all. Making a step faster that should have been deleted is wasted work, so speed and automation come only after a step has earned its place.

People set the rules in advance, and the system applies them the same way every time. We do not change rules in the middle of a losing stretch, and a loud failure is better than a quiet error.

Where it shows up: When a simple model ties a complex one, the simple one wins.

Enforced by: `musk-5-step-process.md`; Done-Coding SOP; loud failures over silent wrong answers.

## How risk is held

The limits that sit above every forecast.

### 21. Risk sits above the forecast

**Limits can halt the book, and nothing in the research can override them.**

Risk is not an input to the forecast. It sits above it, with the authority to stop the book, and nothing in the research can argue with it.

Monitoring is meant to be continuous, not a quarterly review. This part of the work is being built, and we describe it as a principle until it runs.

Where it shows up: A halt can never be lifted by the thing it halted.

Enforced by: Designed: the forward runner and capital tier (phase 188). Not yet built.

### 22. No single bet matters

**Many small positions, never one large one.**

When capital is committed, it will be spread across many small positions in liquid securities, sized from the cautious end of the evidence, not the hopeful end, and increased only as results on new data arrive.

A book is to be tested under stress before capital is committed, and watched after. We treat leverage as the thing that ends careers.

Where it shows up: Size follows the cautious end of the evidence, never the hopeful one.

Enforced by: Designed: capital sized net of costs, from the low end of the evidence, after confirmation (E15). Not yet built.
