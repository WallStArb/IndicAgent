import { stalenessRatio, pipelineLagS, tfToMinutes } from "../format";

describe("tfToMinutes", () => {
  it("maps known timeframes to minutes", () => {
    expect(tfToMinutes("1m")).toBe(1);
    expect(tfToMinutes("5m")).toBe(5);
    expect(tfToMinutes("15m")).toBe(15);
    expect(tfToMinutes("1h")).toBe(60);
    expect(tfToMinutes("4h")).toBe(240);
    expect(tfToMinutes("1d")).toBe(1440);
  });

  it("returns 1 for unknown timeframe", () => {
    expect(tfToMinutes("unknown")).toBe(1);
  });
});

describe("stalenessRatio", () => {
  it("returns null when ratio < 1.0", () => {
    const now = Date.now();
    const ts = new Date(now - 3 * 60 * 1000).toISOString(); // 3m ago
    expect(stalenessRatio(ts, 5)).toBeNull(); // 3/5 = 0.6
  });

  it("returns ratio when >= 1.0", () => {
    const now = Date.now();
    const ts = new Date(now - 7 * 60 * 1000).toISOString(); // 7m ago
    const ratio = stalenessRatio(ts, 5); // 7/5 = 1.4
    expect(ratio).not.toBeNull();
    expect(ratio!).toBeCloseTo(1.4, 0);
  });

  it("returns null for invalid timestamp", () => {
    expect(stalenessRatio("invalid", 5)).toBeNull();
  });
});

describe("pipelineLagS", () => {
  it("returns seconds between bar close and signal computed", () => {
    const barClose = "2026-03-06T05:10:00.000Z";
    const signalAt = "2026-03-06T05:10:00.800Z";
    expect(pipelineLagS(signalAt, barClose)).toBeCloseTo(0.8, 1);
  });

  it("returns null for missing or invalid timestamps", () => {
    expect(pipelineLagS(undefined, "2026-03-06T05:10:00Z")).toBeNull();
    expect(pipelineLagS("2026-03-06T05:10:00Z", undefined)).toBeNull();
  });
});
