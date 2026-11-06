// All copy for the landing page. Components arrange it and hold none of their own.
// Rules: no fund or person names, no performance or investor language, nothing described as
// running that is only being built. The hero facts are the only figures. Principles, families
// and retired ideas are adapted from the public site copy and re-checked against STATE.md, the
// glossary and the research ledger (reset on 2026-10-30, so no family has a counted result).

export type GroupId = "true" | "edge" | "practice" | "risk";

export type Truth = {
  id: number;
  group: GroupId;
  title: string;
  line: string;
  essay: string[];
  example: string;
  lead: boolean;
};

export type KindId =
  | "temporal"
  | "cross-sectional"
  | "lead-lag"
  | "flows-events"
  | "structure"
  | "volume-flow"
  | "discovery";

export type Family = {
  kind: KindId;
  name: string;
  idea: string;
  mechanism: string;
  counterparty: string;
  status: string;
  retireIf: string;
  truths: number[];
};

export type EdgeStep = {
  name: string;
  term: string;
  body: string;
  guards?: { name: string; body: string }[];
};

export const hero = {
  status: "Agentic quantitative research platform",
  strip: "ingest · feature · measure · research · book",
  tagline: "Honest edge research: nothing earns capital until it survives a counted test",
  title: ["Agentic", "Quantitative", "Research Platform"],
  body: "AI agents design, build, review and operate IndicAgent under the same rules as the code. Independent reviews come before a design is adopted. Every hypothesis on features, signals, regimes and factors is tested fast and counted honestly, with every look at the data counted and selection made under a multiple-testing correction. There are no counted results yet; the research ledger was reset on 2026-10-30 and starts clean.",
  loop: "The research loop itself is designed to become agentic: a population of candidate ideas is to be generated, tested on data it has not seen, and selected with no person in the loop, inside the same evidence gates. That loop is being built and is not running.",
  facts: [
    { value: "1,529", label: "US equities and ETFs" },
    { value: "5m to 1d", label: "Bar timeframes" },
    { value: "From 2000", label: "Daily history, where vendors have it" },
    { value: "Every look", label: "Counted against the vintage" },
  ],
};

export const agents = {
  eyebrow: "How the agents work",
  title: "Agents do the work; the gates decide what counts",
  intro: "The platform is designed, built, reviewed and operated with AI agents working under the same rules as the code.",
  steps: [
    { name: "Plan", body: "An agent writes the design and the test before any code exists, and the design states what would make it fail." },
    { name: "Build", body: "An agent writes the change under the same naming, data and determinism rules as any other code." },
    { name: "Review", body: "Independent reviews, from more than one model, come before a design is adopted, and every change is reviewed again before it lands." },
    { name: "Verify", body: "Mechanical gates and a counted test bind the agents. Nothing an agent produces reaches capital without proof." },
  ],
};

export const triangle = {
  eyebrow: "Shape",
  title: "The shape of the work is a triangle.",
  intro: "The wide base is where ideas come from. The narrow point is what is given weight. Most of the work is deciding, honestly, what falls away in between.",
  figureLabel: "A triangle filling from its wide base to its apex: many candidates, fewer survivors, a few that hold.",
  stages: [
    { label: "Many candidates are proposed", note: "From many directions, none favored. People propose what to measure; the data decides what predicts." },
    { label: "Fewer survive measurement", note: "Tested on data they have not seen, with every look counted and the best of many corrected for being the best." },
    { label: "A few hold", note: "Only these are meant to be given weight, and only while the evidence holds. Weight is designed to leave when the edge fades." },
  ],
};

export const ideas = {
  eyebrow: "Principles",
  title: "The ideas the rest depend on.",
  intro: "Everything else on this page follows from these. The six that matter most come first; the rest are grouped by what they protect.",
  exampleLabel: "Where it shows up",
  restTitle: "The rest, by group",
};

export const groups: { id: GroupId; title: string; blurb: string }[] = [
  {
    id: "true",
    title: "What counts as true",
    blurb: "How a result earns the right to be believed.",
  },
  {
    id: "edge",
    title: "Where edge comes from",
    blurb: "What we look for, and what we refuse to assume.",
  },
  {
    id: "practice",
    title: "How the practice runs",
    blurb: "The habits that keep the work honest as it grows.",
  },
  {
    id: "risk",
    title: "How risk is held",
    blurb: "The limits that sit above every forecast.",
  },
];

export const truths: Truth[] = [
  {
    id: 1,
    group: "true",
    title: "Proof before belief",
    line: "Intuition proposes. Measurement decides.",
    essay: [
      "We do not call anything an edge because the argument for it is good. Every idea meets the same measurement, and until it survives that measurement it does not exist as far as capital is concerned.",
      "Anyone can be certain. Certainty is not evidence, and we build the work so that it is never asked to be.",
    ],
    example:
      "A candidate with a good story and a weak measurement waits. The story is kept with the result.",
    lead: true,
  },
  {
    id: 2,
    group: "true",
    title: "The default is no edge",
    line: "Every positive result carries the burden of proof.",
    essay: [
      "We start from the assumption that an idea predicts nothing. Markets are crowded, most inputs are public, and an edge that looks easy has usually been found and traded away already.",
      "So we argue against every winner before it earns weight. Is it a data leak, a fluke, a lean on the market, or a cost we forgot?",
    ],
    example:
      "A strong early result is a reason to look harder for the mistake.",
    lead: true,
  },
  {
    id: 3,
    group: "true",
    title: "Judge only what could have been traded",
    line: "We measure at prices someone could actually have had, after cost.",
    essay: [
      "A return measured at a closing price nobody could have traded at makes an idea look better than it is, especially over short horizons. We measure from a price where a trade could really have been placed, and we take the cost out.",
      "An effect that is real but too small to survive cost is not an edge. It is an interesting fact.",
    ],
    example:
      "Entries and exits use the next opening price. A result that needs a trade that could not have happened is discarded.",
    lead: false,
  },
  {
    id: 4,
    group: "true",
    title: "Only what was knowable at the time",
    line: "Nothing borrows from the future.",
    essay: [
      "We read every input as it stood at the moment it describes: which securities existed, how they were classified, what kind of market it was, and the data itself. Anything that could only have been known later stays out of the test.",
      "That applies to labels as much as to prices. A regime decided by looking at what came next is a leak, however convenient it is.",
    ],
    example:
      "A sector label from today is never used to explain a year when the company was classified differently.",
    lead: false,
  },
  {
    id: 5,
    group: "true",
    title: "Unseen data is spent once",
    line: "Searching is a screen. Confirmation happens once, on data nobody has searched.",
    essay: [
      "Data we have searched cannot also confirm. Results on it only decide which ideas deserve a real test. The real test is a single run on data nobody has looked at, applied to the whole book, meaning every idea together and how they are combined, not to a favorite.",
      "Because that data can be used only once, we protect it. Going back to it after a disappointing answer is how weak ideas get through.",
    ],
    example:
      "A book is frozen before its test, and the verdict is recorded whichever way it falls.",
    lead: true,
  },
  {
    id: 6,
    group: "true",
    title: "Every look is counted",
    line: "Each pass over the data spends some credibility.",
    essay: [
      "Test enough ideas on the same history and some will look good by chance. So we record every look, and the bar for what counts as real rises with the number of looks.",
      "We correct for selection too. The best of many is biased upward simply by being the best.",
    ],
    example:
      "An idea reopened under a new name counts as another look, not a fresh start.",
    lead: false,
  },
  {
    id: 7,
    group: "true",
    title: "We do not run tests that cannot answer",
    line: "Some questions cannot be settled with the data at hand.",
    essay: [
      "Sometimes the effect is too small or the history too short for any result to mean anything. We refuse those tests before a number exists.",
      "Neighboring observations share information, so we count independent observations, not rows of data. Knowing takes time, and we say how much.",
    ],
    example:
      "A test whose method could not detect the effect it is looking for is rejected at the design stage.",
    lead: false,
  },
  {
    id: 8,
    group: "true",
    title: "Measure outcomes, not activity",
    line: "Ideas tested and features built are not results.",
    essay: [
      "A measure that becomes a target stops being a good measure. We judge the work on outcomes, on what an idea added once the market is removed, never on how much was produced.",
      "Most of what gets built is wrong. Building got cheaper. Finding out that it is wrong did not.",
    ],
    example:
      "We never report the number of new ideas as progress.",
    lead: false,
  },
  {
    id: 9,
    group: "edge",
    title: "Edge is discovered, not designed",
    line: "A person proposes what to measure. The data decides what predicts.",
    essay: [
      "Nothing in the work encodes someone's theory of what a good setup looks like. People propose measurements from many directions, and the data decides which ones predict and which combinations matter.",
      "For any design choice we ask who decides what matters here. If the answer is the researcher, the choice is wrong.",
    ],
    example:
      "A pattern someone named by hand is never allowed to define what counts as confirmation.",
    lead: false,
  },
  {
    id: 10,
    group: "edge",
    title: "Many small edges, combined",
    line: "No single measurement is the insight.",
    essay: [
      "Each measurement predicts a little. The edge is in the combination of many, weighted by the data. A hundred views that move together are worth far less than a hundred independent ones.",
      "Agreement only counts between sources that could have disagreed. Two measures of the same thing confirm nothing.",
    ],
    example:
      "Several readings of the same price move are weighed as one view, not several.",
    lead: true,
  },
  {
    id: 11,
    group: "edge",
    title: "Every edge has a counterparty",
    line: "We name who is on the other side, and why they are wrong.",
    essay: [
      "A lasting edge comes from better information, better processing, someone who has to trade for reasons other than price, a behavior that persists, or a risk others will not carry. Every family of ideas we study states which one, and who pays.",
      "A reward for carrying risk is called a reward for carrying risk. It is not skill.",
    ],
    example:
      "Every family of ideas below names its counterparty and what would make it stop paying.",
    lead: true,
  },
  {
    id: 12,
    group: "edge",
    title: "The market is taken out",
    line: "A result is what is left once the tide is removed.",
    essay: [
      "A rising market lifts everything and a falling one sinks everything. A result that is mostly the market is not skill. We judge results on what remains after the market and other common moves are removed.",
      "That is the only version of a result that can be compared from one year to the next.",
    ],
    example:
      "A book that wins only when the market rises is exposure, not edge.",
    lead: false,
  },
  {
    id: 13,
    group: "edge",
    title: "Stability counts as much as size",
    line: "A small edge that holds beats a large one that comes and goes.",
    essay: [
      "A large result that shows up one month and vanishes the next is weaker than a small one that is there every month. Weight follows the one that holds.",
      "We measure stability on separate, non-overlapping stretches of time, so a lucky run cannot pass for it.",
    ],
    example:
      "Two ideas with the same average are not equal if one of them swings.",
    lead: false,
  },
  {
    id: 14,
    group: "edge",
    title: "Condition on context, never discard it",
    line: "Every claim carries the kind of market it was measured in.",
    essay: [
      "Markets change, and a rule that works in one kind of market can fail in another. We take every measurement within a regime, and every weight is specific to that regime.",
      "We throw nothing away for looking wrong. An observation from the wrong kind of market is information about where a rule does not hold.",
    ],
    example:
      "A measure that works in calm markets is not allowed to act in stressed ones.",
    lead: false,
  },
  {
    id: 15,
    group: "practice",
    title: "Influence is earned and can be lost",
    line: "Weight follows the evidence, and goes when the evidence goes.",
    essay: [
      "No idea has influence by default. An idea earns weight with proof, and the work is designed to take that weight away when the measured edge fades, without anyone having to notice.",
      "Getting weight back is harder than losing it. A cut weight returns only on a fresh block of independent evidence, so the work follows real change and does not swing on noise.",
    ],
    example:
      "By design, a fading idea is cut first and has to prove itself again to come back.",
    lead: true,
  },
  {
    id: 16,
    group: "practice",
    title: "What was turned down is data",
    line: "We keep what we refused, and study what failed.",
    essay: [
      "We keep the ideas we declined, along with what happened next. A system that studies only what it acted on never learns where the line between taking and leaving should be.",
      "We measure everything everywhere, not only where we expected it to work. A result seen only where a hand-made filter fired is confirmation bias. A failure is a reason to redesign, not to patch.",
    ],
    example:
      "A rejected idea can come back later with its full history attached.",
    lead: false,
  },
  {
    id: 17,
    group: "practice",
    title: "Nothing is overwritten",
    line: "Every result can be reproduced.",
    essay: [
      "Raw data is permanent. A correction is added as a new record, and missing data stays missing; we never invent values to fill a gap. Any result can be rebuilt exactly from the data, the code and the specification it came from.",
      "The reason an idea was retired lives in a record, not in someone's memory. Years later, the question of why it was dropped still has an answer.",
    ],
    example:
      "Every setting is a versioned record that says who changed it and why.",
    lead: false,
  },
  {
    id: 18,
    group: "practice",
    title: "Every source clears the same bar",
    line: "A new kind of data gets no exemption.",
    essay: [
      "What we test is the book: the ideas in it, how they are combined, and the rule that turns a forecast into positions. There is one forecast for each security at each moment, not competing ones.",
      "We pay for data only after it shows that it predicts, and stale information fades to neutral. A source is not trusted for being expensive or exciting.",
    ],
    example:
      "A new kind of data goes through the same measurement every other kind passed.",
    lead: false,
  },
  {
    id: 19,
    group: "practice",
    title: "The vocabulary is the model",
    line: "A term has one meaning, because a loose word hides a loose idea.",
    essay: [
      "Every name we use is held to a test: an expert who has never seen the work should be able to tell what a thing is from its name. Where two terms could mean the same thing, we retire one.",
      "Precise language is precise thinking, so we treat the vocabulary as part of the model.",
    ],
    example:
      "When the code and the glossary disagree, the glossary wins.",
    lead: false,
  },
  {
    id: 20,
    group: "practice",
    title: "Question first, delete second, simplify third",
    line: "Speed and automation come last.",
    essay: [
      "Before improving a step, we ask whether it should exist at all. Making a step faster that should have been deleted is wasted work, so speed and automation come only after a step has earned its place.",
      "People set the rules in advance, and the system applies them the same way every time. We do not change rules in the middle of a losing stretch, and a loud failure is better than a quiet error.",
    ],
    example:
      "When a simple model ties a complex one, the simple one wins.",
    lead: false,
  },
  {
    id: 21,
    group: "risk",
    title: "Risk sits above the forecast",
    line: "Limits can halt the book, and nothing in the research can override them.",
    essay: [
      "Risk is not an input to the forecast. It sits above it, with the authority to stop the book, and nothing in the research can argue with it.",
      "Monitoring is meant to be continuous, not a quarterly review. This part of the work is being built, and we describe it as a principle until it runs.",
    ],
    example:
      "A halt can never be lifted by the thing it halted.",
    lead: false,
  },
  {
    id: 22,
    group: "risk",
    title: "No single bet matters",
    line: "Many small positions, never one large one.",
    essay: [
      "When capital is committed, it will be spread across many small positions in liquid securities, sized from the cautious end of the evidence, not the hopeful end, and increased only as results on new data arrive.",
      "A book is to be tested under stress before capital is committed, and watched after. We treat leverage as the thing that ends careers.",
    ],
    example:
      "Size follows the cautious end of the evidence, never the hopeful one.",
    lead: false,
  },
];

export const edgeSteps = {
  eyebrow: "Method",
  title: "How an edge is found.",
  intro: "From one measurement to a claim of edge, and every place the claim can fail on the way.",
  steps: [
    {
      name: "Measure every bar",
      term: "Feature",
      body: "A feature is one plain measurement taken on every bar of every security: a level, a change, a z-score, an average. It carries few assumptions and no view about whether to buy. It is computed whether or not anyone expects it to matter, so nothing is measured only where it was expected to work.",
    },
    {
      name: "Measure prediction on tradeable returns",
      term: "Information coefficient",
      body: "The rank correlation between a feature and the return that follows it, from one opening price to a later one, so only what could have been traded counts. Returns measured from closing prices capture overnight gaps nobody can trade and overstate the signal. A useful correlation is small, and that is expected.",
    },
    {
      name: "Ask whether it holds",
      term: "Stability",
      body: "Neighboring bars share information, so confidence intervals come from a bootstrap that respects how market data repeats itself. A small effect that is there in every stretch of time beats a larger one that comes and goes.",
    },
    {
      name: "Know what kind of market it was",
      term: "Regime",
      body: "Each regime is labeled using only what was known at that moment, with the model refit walk-forward and never on the path that followed. A measure that works only in one kind of market is known for exactly that.",
    },
    {
      name: "Correct for searching",
      term: "Counted looks",
      body: "Many ideas are tested on the same history, so some will look good by chance. Every look at a vintage is recorded in the research ledger, and selection uses a step-down multiple test over everything tried, so the best of many is corrected for being the best.",
    },
    {
      name: "Is it the market in disguise?",
      term: "Market-neutral tests",
      body: "A rising market can make almost anything look predictive. Separate tests stand between a result and the word edge, and each is meant to end ideas that passed the others.",
      guards: [
        { name: "Residual targets", body: "Prediction is judged on returns with the market and common moves already removed." },
        { name: "Static-tilt benchmark", body: "Every book is compared with a version that does nothing but hold the same average lean. If nothing is left after subtracting it, the result is exposure." },
        { name: "Shuffled nulls", body: "The real ranking has to beat many random reshufflings of the same data, or it is chance." },
      ],
    },
    {
      name: "Combine",
      term: "Combiner and book",
      body: "Family members are weighted into one forecast for each security, walk-forward, using only data that came before. The book is the members, the combiner, and the rule that turns a forecast into positions. The book, not an idea, is what gets tested.",
    },
    {
      name: "Confirm once, after cost",
      term: "Promotion",
      body: "A frozen book is tested once on data nobody has searched. Costs never enter a test statistic, but a book is promoted only when its net expectation is positive. The bar is high on purpose.",
    },
  ] satisfies EdgeStep[],
};

export const familiesCopy = {
  eyebrow: "Families",
  title: "Families of ideas, each with a reason to exist.",
  intro: "A family is a few variants of one mechanism, named before any result is seen. Each states why it might work, who is on the other side, and what would retire it. None has a counted result yet.",
  whyLabel: "Why it might work",
  counterpartyLabel: "Who is on the other side",
  retireLabel: "Retired if",
  restsOn: "Rests on ideas",
};

export const kinds: { id: KindId; title: string; blurb: string }[] = [
  {
    id: "temporal",
    title: "Temporal and seasonal",
    blurb: "Patterns tied to the clock and the calendar.",
  },
  {
    id: "cross-sectional",
    title: "Cross-sectional",
    blurb: "One name measured against its peers.",
  },
  {
    id: "lead-lag",
    title: "Lead and lag",
    blurb: "Information that reaches one market before another.",
  },
  {
    id: "flows-events",
    title: "Flows and events",
    blurb: "Trading that happens for reasons other than price.",
  },
  {
    id: "structure",
    title: "Price structure and anchoring",
    blurb: "Where price has been, and why it matters again.",
  },
  {
    id: "volume-flow",
    title: "Volume and order flow",
    blurb: "Who is trading, and how urgently.",
  },
  {
    id: "discovery",
    title: "Discovery",
    blurb: "Letting a governed search propose what to measure.",
  },
];

export const familyList: Family[] = [
  {
    kind: "temporal",
    name: "Same time of day",
    idea: "Returns in a given slot of the trading day tend to resemble returns in the same slot on earlier days.",
    mechanism:
      "Participants with daily schedules, such as funds rebalancing and orders sliced across the day, act at similar times and leave a repeating footprint.",
    counterparty: "Traders whose timing is set by a schedule, not by price.",
    status: "Not yet tested",
    retireIf: "The pattern fails on later data, or cost per session consumes it.",
    truths: [3, 5, 11],
  },
  {
    kind: "temporal",
    name: "Overnight versus intraday",
    idea: "The part of a return earned overnight and the part earned in the session behave differently and carry different information.",
    mechanism:
      "Different participants are active in each window, and information arrives at different times.",
    counterparty:
      "Holders who cannot trade overnight, and those who must trade the open.",
    status: "Not yet tested",
    retireIf: "The split carries no information once the market is removed.",
    truths: [3, 11, 12],
  },
  {
    kind: "temporal",
    name: "Calendar and period-end position",
    idea: "Where a day sits in the week, month, quarter or year relates to returns.",
    mechanism:
      "Rebalancing, payroll flows and reporting dates concentrate flows into predictable windows.",
    counterparty: "Investors whose flows are fixed by the calendar.",
    status: "Not yet tested",
    retireIf:
      "It is among the most published of effects, so it is retired if it does not survive being counted among every other look.",
    truths: [2, 6, 11],
  },
  {
    kind: "cross-sectional",
    name: "Short-term reversal",
    idea: "Names that moved sharply over a short window tend to give some of it back relative to their peers.",
    mechanism:
      "Demand for immediate liquidity pushes price past fair value, and it recovers as liquidity returns.",
    counterparty: "Those who need immediate execution and pay for it.",
    status: "Not yet tested",
    retireIf: "Reversal is explained by a tilt in the market, or disappears after cost.",
    truths: [3, 11, 12],
  },
  {
    kind: "cross-sectional",
    name: "Residual and industry momentum",
    idea: "A trend measured after the market and industry moves are removed continues longer than the raw trend.",
    mechanism:
      "Information about a single firm spreads slowly once the common moves are stripped out.",
    counterparty: "Slow-reacting holders of the firm.",
    status: "Not yet tested",
    retireIf: "There is no persistence on later data.",
    truths: [4, 5, 12],
  },
  {
    kind: "lead-lag",
    name: "Fund to constituent",
    idea: "Moves in a fund can lead the names inside it, or the reverse, over short horizons.",
    mechanism:
      "A fund and its holdings are priced in different places by different participants, and the faster one leads.",
    counterparty: "Those pricing the slower side from stale information.",
    status: "Not yet tested",
    retireIf: "The delay shrinks below what cost allows.",
    truths: [3, 11, 14],
  },
  {
    kind: "lead-lag",
    name: "Cross-asset and cross-sector transfer",
    idea: "Information shows up in one market or sector before it reaches a related one.",
    mechanism:
      "Attention and capital are limited, so related markets do not reprice at the same moment.",
    counterparty: "Participants who watch only one market.",
    status: "Not yet tested",
    retireIf: "The lead disappears when measured at prices that could be traded.",
    truths: [3, 10, 11],
  },
  {
    kind: "flows-events",
    name: "Period-end marking",
    idea: "Managers mark positions near reporting dates, moving prices in ways that tend to reverse.",
    mechanism: "A reporting date creates an incentive to show certain holdings or levels.",
    counterparty: "Managers acting for a reporting date, not for price.",
    status: "Not yet tested",
    retireIf: "The effect does not survive the count of looks.",
    truths: [2, 6, 11],
  },
  {
    kind: "flows-events",
    name: "Tax-loss selling",
    idea: "Names that have fallen face selling pressure near year end, followed by recovery.",
    mechanism: "Tax rules create a deadline that forces sales.",
    counterparty: "Taxable holders working to a deadline.",
    status: "Not yet tested",
    retireIf: "The pressure cannot be told apart from ordinary reversal.",
    truths: [2, 11, 12],
  },
  {
    kind: "flows-events",
    name: "Options expiry",
    idea: "Prices near large option positions can be pinned into expiry and released afterward.",
    mechanism:
      "Dealers hedging large positions buy and sell in ways that dampen price, then free it.",
    counterparty: "Dealers hedging a book, not expressing a view.",
    status: "Held: needs option data that is not captured",
    retireIf: "Heavily optioned names and a control group behave alike.",
    truths: [2, 11, 14],
  },
  {
    kind: "flows-events",
    name: "Index reconstitution",
    idea: "Names entering or leaving an index move because funds must trade, not because anything about the company changed.",
    mechanism: "Index funds trade on a known date, in known size.",
    counterparty: "Funds that must buy or sell on a schedule.",
    status: "Held: no point-in-time record of the changes exists yet",
    retireIf:
      "A clean point-in-time record of the changes cannot be had, or the effect is gone.",
    truths: [4, 11, 17],
  },
  {
    kind: "structure",
    name: "Price anchoring",
    idea: "Distance from a salient past price, such as the yearly high, shapes how far a move continues or reverses.",
    mechanism:
      "Participants anchor on reference prices and under-react when price approaches them.",
    counterparty: "Anchored participants.",
    status: "Not yet tested",
    retireIf: "The sign or size does not hold on later data.",
    truths: [5, 11, 14],
  },
  {
    kind: "structure",
    name: "Volume profile",
    idea: "Where trading has concentrated in the past marks levels that matter again.",
    mechanism:
      "Prices accepted by many participants become reference points for later decisions.",
    counterparty: "Traders who ignore where the crowd has been.",
    status: "Not yet tested",
    retireIf: "The levels add nothing once simple price measures are accounted for.",
    truths: [2, 10, 14],
  },
  {
    kind: "volume-flow",
    name: "Participation and order flow",
    idea: "Unusual participation, and an imbalance between buying and selling pressure, precede moves.",
    mechanism:
      "Informed or urgent trading leaves traces in volume and in the shape of bars.",
    counterparty: "Passive providers of liquidity.",
    status: "Not yet tested",
    retireIf: "The proxy taken from bars is too noisy to survive cost.",
    truths: [3, 10, 11],
  },
  {
    kind: "discovery",
    name: "Generated families",
    idea: "A registered grammar over price and volume primitives proposes candidate measures, and selection happens inside the test.",
    mechanism:
      "Discovery without preconceptions, where every expansion of the grammar is counted as a look.",
    counterparty:
      "None is assumed in advance. Anything found must name one before it earns weight.",
    status: "Not yet tested",
    retireIf: "Nothing found survives the counted selection.",
    truths: [6, 9, 18],
  },
];

export const retiredCopy = {
  eyebrow: "Retired ideas",
  title: "Retiring ideas honestly is part of the method.",
  intro: "Ideas leave for reasons, and the reasons are kept. These are the kinds of reasons that have ended ideas here. None is a failure of the practice; each is the practice working.",
};

export const layers = {
  title: "Four layers",
  note: "data flows one way, each layer reads only the one below",
  items: [
    {
      layer: "01",
      name: "Data foundation",
      subtitle: "Ingest · raw capture · canonical bars",
      accent: false,
      badges: ["ingest"],
      items: [
        "IBKR and Alpaca bars, 5m to 1d, for US equities and ETFs",
        "Every vendor answer is stored raw, last-wins, with a revision log",
        "Canonical bars are a rebuildable selection from raw plus a source policy",
        "Bad prints are flagged and quarantined, never deleted",
      ],
      example: "ohlcv_raw -> market_data_ohlcv -> market_data_ohlcv_tradeable",
    },
    {
      layer: "02",
      name: "Features and measurement",
      subtitle: "Feature store · regimes · information coefficient",
      accent: false,
      badges: ["feature", "measure"],
      items: [
        "Feature vectors per bar, written once by a single writer",
        "Market regimes labeled with walk-forward fitting",
        "Information coefficient term structure per feature and horizon",
        "Targets are executable: market-on-open entry and exit",
      ],
      example: "feature_vectors · market_regimes · ic_measure",
    },
    {
      layer: "03",
      name: "Research machine",
      subtitle: "Panel · families · guards · combiner · book test",
      accent: true,
      badges: ["research"],
      items: [
        "A point-in-time panel feeds family tests, guards, a combiner, and a construction rule",
        "Every look at a vintage is recorded in the research ledger",
        "Selection uses Romano-Wolf StepM over everything tried on the vintage",
        "Results are bit-exact reproducible from snapshot, code, and spec hash",
      ],
      example: "panel -> target -> families -> guards -> combiner -> book test",
    },
    {
      layer: "04",
      name: "Frozen books",
      subtitle: "Promotion · sealed forward shadow",
      accent: false,
      badges: ["book"],
      items: [
        "Promotion requires positive net expectation after costs",
        "A frozen book is confirmed once on its own unsearched forward span",
        "The forward runner and sealed shadow are being built; no book is running yet",
        "Capital follows proof, never the other way round",
      ],
      example: "frozen book -> forward runner -> sealed shadow -> capital",
    },
  ],
};

export const guarantees = {
  eyebrow: "Data",
  title: "What the data layer guarantees",
  items: [
    {
      label: "Raw capture",
      value: "Nothing a vendor serves is dropped",
      desc: "Every vendor answer lands in one raw table, last-wins, with a revision log that records restatements. Restatements are detected, never blocked. Canonical bars are a selection from raw plus a source policy, and a gate proves the selection is a pure function of raw.",
      accent: "cyan",
    },
    {
      label: "Data integrity",
      value: "Quarantine, flag, never delete",
      desc: "Scrub rules flag suspect bars and a quarantine list hides them from research while keeping them stored. Nightly reconciliation writes integrity verdicts that rebuilds and promotion read. A coverage ledger records which requests ran, per timeframe and provider.",
      accent: "amber",
    },
    {
      label: "Determinism",
      value: "Bit-exact from the recipe",
      desc: "A result is a function of the data snapshot hash, the code key, and the spec hash. Frozen verdicts are replayed after every change to the research or statistics code and must come back bit-identical.",
      accent: "cyan",
    },
  ] as { label: string; value: string; desc: string; accent: "cyan" | "amber" }[],
};

export const cta = {
  text: "The cockpit is read-only: what each stage holds, how fresh it is, and what the ledger has counted.",
  link: "Open the pipeline",
};

export const retiredReasons: { title: string; lesson: string }[] = [
  {
    title: "It looked into the future without anyone meaning it.",
    lesson:
      "A measurement joined to data that was not yet known at the time. The result went away when the join was corrected, and the rule against it was written down.",
  },
  {
    title: "The signal was real. The cost was larger.",
    lesson:
      "Something genuinely predicted, but trading on it paid more than it earned. A signal is not an edge until it survives what it costs to act.",
  },
  {
    title: "It was the market in disguise.",
    lesson:
      "A result that was mostly a tilt toward the market's direction. With the market removed, nothing was left.",
  },
  {
    title: "It worked on the data it was fit to, and nowhere else.",
    lesson:
      "Strong in the stretch it was searched on, absent on data it had not seen. In-sample results are a screen, not a verdict.",
  },
  {
    title: "A data fault made a model look stronger than it was.",
    lesson:
      "A fault in the inputs inflated a result until it was found and corrected. The finding was recorded, not hidden, and results from before the ledger was reset are not carried forward as evidence.",
  },
  {
    title: "The mechanism named never appeared.",
    lesson:
      "An idea built on a specific flow was checked against a control group that behaved the same way. If the control behaves alike, the mechanism is not the cause.",
  },
  {
    title: "Two related names did not move together after all.",
    lesson:
      "Economic links are not statistical links. Pairs that seemed bound by the same business did not hold together when tested.",
  },
];
