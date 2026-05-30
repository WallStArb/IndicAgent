"use client";

import type { PatternData } from "@/lib/types";
import { fmtNum } from "@/lib/format";
import { ZoneLabel, DirectionalPill, Metric } from "./ui/metric-components";

interface PatternPanelProps {
  patterns: PatternData | null;
}

/** I5 Pattern Detection — compact column layout */
export function PatternPanel({ patterns }: PatternPanelProps) {
  const p = patterns;

  const signals: {
    label: string;
    type: "bullish" | "bearish" | "neutral";
    detail: string;
  }[] = [];

  if (p?.rsi_divergence) {
    signals.push({ label: "RSI Div", type: p.rsi_divergence === "bullish" ? "bullish" : "bearish", detail: `${fmtNum(p.rsi_div_confidence, 0)}%` });
  }
  if (p?.macd_divergence) {
    signals.push({ label: "MACD Div", type: p.macd_divergence === "bullish" ? "bullish" : "bearish", detail: `${fmtNum(p.macd_div_confidence, 0)}%` });
  }
  if (p?.cmf_divergence) {
    signals.push({ label: "CMF Div", type: p.cmf_divergence === "bullish" ? "bullish" : "bearish", detail: `${fmtNum(p.cmf_div_confidence, 0)}%` });
  }
  if (p?.obv_divergence) {
    signals.push({ label: "OBV Div", type: p.obv_divergence === "bullish" ? "bullish" : "bearish", detail: `${fmtNum(p.obv_div_confidence, 0)}%` });
  }
  if (p?.volume_divergence) {
    signals.push({ label: "Vol Div", type: p.volume_divergence === "bullish" ? "bullish" : "bearish", detail: `${fmtNum(p.vol_div_confidence, 0)}%` });
  }
  if (p?.bb_squeeze) {
    signals.push({ label: "Squeeze", type: "neutral", detail: `×${p.squeeze_count ?? 0}` });
  }
  // Chart patterns — only show when actively forming/confirmed
  if (p?.dt_db_pattern && p.dt_db_pattern > 0) {
    const labels = ["", "DT form", "DT conf", "DB form", "DB conf"];
    const type = p.dt_db_pattern <= 2 ? "bearish" : "bullish";
    signals.push({ label: labels[p.dt_db_pattern] ?? "DT/DB", type, detail: `${fmtNum((p.dt_db_confidence ?? 0) * 100, 0)}%` });
  }
  if (p?.hs_pattern && p.hs_pattern > 0) {
    const labels = ["", "H&S form", "H&S conf", "IH&S form", "IH&S conf"];
    const type = p.hs_pattern <= 2 ? "bearish" : "bullish";
    signals.push({ label: labels[p.hs_pattern] ?? "H&S", type, detail: `${fmtNum((p.hs_confidence ?? 0) * 100, 0)}%` });
  }
  if (p?.tri_pattern && p.tri_pattern > 0) {
    const triLabels = ["", "Asc△", "Desc△", "Sym△", "↑Wedge", "↓Wedge"];
    const type = (p.tri_breakout_bias ?? 0) > 0 ? "bullish" : (p.tri_breakout_bias ?? 0) < 0 ? "bearish" : "neutral";
    signals.push({ label: triLabels[p.tri_pattern] ?? "Triangle", type, detail: `${fmtNum((p.tri_confidence ?? 0) * 100, 0)}%` });
  }
  if (p?.flag_pattern && p.flag_pattern > 0) {
    signals.push({ label: p.flag_pattern === 1 ? "Bull Flag" : "Bear Flag", type: p.flag_pattern === 1 ? "bullish" : "bearish", detail: "" });
  }
  if (p?.pennant_pattern && p.pennant_pattern > 0) {
    signals.push({ label: "Pennant", type: "neutral", detail: "" });
  }
  if (p?.cup_handle_pattern && p.cup_handle_pattern > 0) {
    signals.push({ label: p.cup_handle_pattern === 2 ? "C&H conf" : "C&H form", type: "bullish", detail: "" });
  }
  if (p?.abcd_pattern_active) {
    signals.push({ label: "ABCD", type: (p.abcd_direction ?? 0) > 0 ? "bullish" : "bearish", detail: "" });
  }
  // Candlestick patterns
  if (p?.engulfing_bull) signals.push({ label: "Engulf", type: "bullish", detail: "" });
  if (p?.engulfing_bear) signals.push({ label: "Engulf", type: "bearish", detail: "" });
  if (p?.pin_bar_bull) signals.push({ label: "Pin Bar", type: "bullish", detail: "" });
  if (p?.pin_bar_bear) signals.push({ label: "Pin Bar", type: "bearish", detail: "" });
  if (p?.hammer_detected) signals.push({ label: "Hammer", type: "bullish", detail: "" });
  if (p?.shooting_star_detected) signals.push({ label: "Shoot★", type: "bearish", detail: "" });
  if (p?.morning_star) signals.push({ label: "Morn★", type: "bullish", detail: "" });
  if (p?.evening_star) signals.push({ label: "Eve★", type: "bearish", detail: "" });
  if (p?.three_white_soldiers) signals.push({ label: "3 Bulls", type: "bullish", detail: "" });
  if (p?.three_black_crows) signals.push({ label: "3 Bears", type: "bearish", detail: "" });
  if (p?.doji_detected) signals.push({ label: "Doji", type: "neutral", detail: "" });

  return (
    <div className="px-2 py-1">
      <div className="flex items-start gap-2">
        <ZoneLabel tier="I5" />
        <div className="flex flex-wrap items-center gap-x-2 gap-y-0.5">
          {signals.length > 0 ? (
            signals.map((sig, i) => <DirectionalPill key={`${sig.label}-${i}`} {...sig} />)
          ) : (
            <span className="text-[0.6rem] text-[var(--text-muted)] italic">
              No patterns
            </span>
          )}

          {/* Trend confluence score */}
          {p?.trend_confluence_score != null && p.trend_confluence_score > 0.1 && (
            <Metric
              label="TConf"
              value={
                <span className="font-bold" style={{ color: "var(--green)" }}>
                  {fmtNum(p.trend_confluence_score, 2)}
                </span>
              }
            />
          )}

          {/* Mean-reversion confluence */}
          {p?.confluence_score !== undefined && (
            <Metric
              label="MRConf"
              value={
                <span
                  className="font-bold"
                  style={{
                    color:
                      p.confluence_score > 0.3
                        ? "var(--green)"
                        : p.confluence_score < -0.3
                          ? "var(--red)"
                          : "var(--text-secondary)",
                  }}
                >
                  {p.confluence_score > 0 ? "+" : ""}
                  {fmtNum(p.confluence_score, 2)}
                </span>
              }
            />
          )}
        </div>
      </div>
    </div>
  );
}
