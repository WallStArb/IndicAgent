import { readdirSync, readFileSync } from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";
import { hero } from "@/lib/copy/landing";

const root = path.resolve(__dirname, "..");
const copyFile = path.join(root, "src/lib/copy/landing.ts");
const landingDir = path.join(root, "src/components/landing");

// Header comments state the rules and so name the banned terms; only shipped strings are scanned.
const copy = readFileSync(copyFile, "utf8")
  .split("\n")
  .filter((line) => !line.trim().startsWith("//"))
  .join("\n");
const landingComponents = readdirSync(landingDir)
  .filter((f) => f.endsWith(".tsx"))
  .map((f) => [f, readFileSync(path.join(landingDir, f), "utf8")] as const);

// Text the public landing page may never carry. Glossary-banned terms are listed in
// docs/foundation/glossary.md (retired vocabulary).
const BANNED: [string, RegExp][] = [
  ["em dash", /—/],
  ["curly quote", /[‘’“”]/],
  ["fund name", /renaissance|medallion|two sigma|d\.?e\.? shaw|citadel|bridgewater/i],
  ["person name", /simons|musk|goyette|brandon/i],
  ["performance language", /\b(outperform\w*|track record|profitab\w*|profits?|sharpe|annuali[sz]ed|alpha generation|beat the market)\b/i],
  // Market participants as a counterparty ("investors whose flows...") are fine; an offer to them is not.
  ["investor language", /\b(our investors?|for investors?|investor relations|invest with us|subscribers?|our clients|assets under management|AUM|prospectus|minimum investment)\b/i],
  ["returns claim", /\b(our|its|the platform's|delivers?|delivered|earns?|earned|generates?|generated) (\w+ )?returns?\b/i],
  ["glossary: ensemble", /ensemble/i],
  ["glossary: swarm", /swarm/i],
  ["glossary: alpha score", /alpha score/i],
  ["glossary: sleeve", /sleeve/i],
];

// A thing that is only being built must not be described as running. Each pattern is a
// subject followed, in the same sentence, by a present-tense verb of operation.
const SUBJECTS = "(agentic (research|loop|workflow)s?|the (research|agentic) loop|forward runner|sealed shadow|shadow book|capital|the population of (candidate )?ideas)";
const RUNNING_VERBS = "(runs|is running|are running|is live|are live|operates|is operating|trades|is trading|executes|allocates|is allocated|is deployed|deploys|selects|generates)";
const OVERCLAIM = new RegExp(`\\b${SUBJECTS}\\b[^.;]*\\b${RUNNING_VERBS}\\b`, "i");

// Counted-result claims: the ledger was reset and no family has a counted result.
const RESULT_CLAIMS: [string, RegExp][] = [
  ["counted number", /\b\d[\d,]*\s+(counted|significant|surviv\w+|verdicts?|validated|confirmed)\b/i],
  ["found an edge", /\b(found|has found|have found|discovered|proved|proven|confirmed) (an? |the )?(statistically )?(significant )?edge\b/i],
  ["edge survives", /\bedge (survives|survived|holds|confirmed)\b/i],
  ["significant result", /\bsignificant (result|finding)s?\b/i],
];

// Sentences in the copy that are legitimately about the future state, kept to a fixed list.
const HONEST_FUTURE = /(designed to|is to be|are to be|to become|being built|is not running|not yet|nothing earns|until it)/i;

function sentences(text: string): string[] {
  return text.split(/(?<=[.!?])\s+|\n/).map((s) => s.trim()).filter(Boolean);
}

describe("landing copy guard", () => {
  it("is the file under test", () => {
    expect(copy).toContain("export const hero");
  });

  it.each(BANNED)("copy has no %s", (_label, pattern) => {
    expect(copy.match(pattern)?.[0] ?? null).toBeNull();
  });

  it.each(landingComponents)("component %s has no banned content", (_name, text) => {
    for (const [label, pattern] of BANNED) {
      expect(pattern.test(text), `${label} in ${_name}`).toBe(false);
    }
  });

  it("describes nothing that is only being built as running", () => {
    const offenders = sentences(copy).filter((s) => OVERCLAIM.test(s) && !HONEST_FUTURE.test(s));
    expect(offenders).toEqual([]);
  });

  it.each(RESULT_CLAIMS)("makes no counted-result claim (%s)", (_label, pattern) => {
    expect(copy.match(pattern)?.[0] ?? null).toBeNull();
  });

  it("allows the word agentic", () => {
    expect(hero.title.join(" ")).toMatch(/agentic/i);
  });

  it("states that the agentic research loop is not running and no result is counted", () => {
    expect(hero.loop).toMatch(/designed to become agentic/);
    expect(hero.loop).toMatch(/is being built and is not running/);
    expect(hero.body).toMatch(/no counted results yet/);
  });

  it("flags an invented present-tense claim (the guard itself works)", () => {
    expect(OVERCLAIM.test("Agentic research runs every night.")).toBe(true);
    expect(OVERCLAIM.test("The forward runner trades live capital.")).toBe(true);
    expect(OVERCLAIM.test("Sealed shadow is running on every book.")).toBe(true);
    expect(OVERCLAIM.test("Capital is allocated by the loop.")).toBe(true);
  });
});
